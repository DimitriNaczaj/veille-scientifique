import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

from veille.linkedin_bridge import create_linkedin_request_token
from veille.linkedin_import import run_linkedin_import
from veille.models import ParsedMessage, PublicationCandidate
from veille.storage import Store


SECRET = "linkedin-secret"
IDENTITY = "doi:10.1234/linkedin-import.1"


def add_publication(database):
    store = Store(database)
    try:
        store.add_message(
            ParsedMessage(
                identity="<newsletter@example.org>",
                subject="Newsletter",
                sender="publisher@example.org",
                publications=(
                    PublicationCandidate(
                        identity=IDENTITY,
                        doi="10.1234/linkedin-import.1",
                        title="An article for LinkedIn",
                        url="https://doi.org/10.1234/linkedin-import.1",
                    ),
                ),
            ),
            "newsletter.eml",
        )
    finally:
        store.close()


def request_email(
    path,
    message_id="<linkedin-request@example.org>",
    sender="consultant@example.org",
):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = sender
    message["To"] = "science-digest@example.org"
    message["Subject"] = "[Veille vers LinkedIn] An article for LinkedIn"
    message.set_content(
        "VEILLE-LINKEDIN/1\n"
        "token={}\n".format(create_linkedin_request_token(IDENTITY, SECRET))
    )
    path.write_bytes(message.as_bytes())


class LinkedinImportTests(unittest.TestCase):
    def test_accepts_request_from_any_configured_digest_recipient(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            request_email(inbox / "request.eml", sender="eric@example.org")

            report = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org, eric@example.org",
                token_secret=SECRET,
                pdf_fetcher=None,
            )

            self.assertEqual(report.accepted, 1)
            self.assertEqual(report.rejected, 0)

    def test_downloads_the_full_article_into_the_preparation_package(self):
        class PdfFetcher:
            def fetch(self, doi, destination):
                self.doi = doi
                Path(destination).write_bytes(b"%PDF-1.7\nfull article")
                return SimpleNamespace(
                    source_url="https://repository.example/article.pdf",
                    license="cc-by",
                    sha256="abc123",
                    size_bytes=21,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            request_email(inbox / "request.eml")
            fetcher = PdfFetcher()

            report = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
                pdf_fetcher=fetcher,
            )

            package = next(output.iterdir())
            self.assertEqual(report.accepted, 1)
            self.assertEqual(fetcher.doi, "10.1234/linkedin-import.1")
            self.assertTrue((package / "sources" / "article.pdf").is_file())
            self.assertTrue((package / "sources" / "pdf-origin.json").is_file())

    def test_keeps_the_request_actionable_when_no_open_pdf_exists(self):
        from veille.article_pdf import PdfUnavailableError

        class MissingPdfFetcher:
            def fetch(self, _doi, _destination):
                raise PdfUnavailableError("Aucun PDF ouvert.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            request_email(inbox / "request.eml")

            report = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
                pdf_fetcher=MissingPdfFetcher(),
            )

            package = next(output.iterdir())
            self.assertEqual(report.accepted, 1)
            self.assertTrue((package / "PDF-À-AJOUTER.md").is_file())
            self.assertIn("Aucun PDF ouvert", report.warnings[0])

    def test_quarantines_a_folder_marked_duplicate_after_identity_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            package = output / "duplicate-article"
            inbox.mkdir()
            (package / "sources").mkdir(parents=True)
            (package / "brief.md").write_text("Brief", encoding="utf-8")
            database = root / "veille.sqlite"
            add_publication(database)
            store = Store(database)
            try:
                store.connection.execute(
                    "INSERT INTO linkedin_request_messages("
                    "message_identity, source_path, sender, publication_identity, "
                    "destination, status, reason, recorded_at"
                    ") VALUES ('merge', 'mail.eml', 'consultant@example.org', ?, ?, "
                    "'duplicate', 'Article fusionné.', '2030-01-01')",
                    (IDENTITY, str(package)),
                )
                store.connection.commit()
            finally:
                store.close()

            run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            self.assertFalse(package.exists())
            quarantined = root / "04 - ERREURS" / "duplicate-article"
            self.assertTrue(quarantined.is_dir())
            self.assertIn(
                "Article fusionné.",
                (quarantined / "error.md").read_text(encoding="utf-8"),
            )

    def test_imports_request_as_an_unapproved_preparation_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            request_email(inbox / "request.eml")

            report = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            self.assertEqual(report.accepted, 1)
            package = next(output.iterdir())
            self.assertTrue((package / "brief.md").is_file())
            self.assertTrue((package / "sources" / "article-de-veille.md").is_file())
            self.assertTrue((package / "sources" / "demande.eml").is_file())
            self.assertTrue((package / "media").is_dir())
            self.assertFalse((package / "publication.md").exists())

    def test_deduplicates_distinct_messages_for_the_same_article(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            request_email(inbox / "first.eml", "<first@example.org>")

            first = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )
            request_email(inbox / "second.eml", "<second@example.org>")
            second = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            self.assertEqual(first.accepted, 1)
            self.assertEqual(second.already_processed, 2)
            self.assertEqual(len(list(output.iterdir())), 1)

    def test_rejects_a_forged_sender_without_stopping_valid_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            request_email(inbox / "valid.eml", "<valid@example.org>")
            request_email(inbox / "forged.eml", "<forged@example.org>")
            forged = (inbox / "forged.eml").read_text(encoding="utf-8")
            (inbox / "forged.eml").write_text(
                forged.replace(
                    "From: consultant@example.org", "From: attacker@example.org"
                ),
                encoding="utf-8",
            )

            report = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            self.assertEqual(report.accepted, 1)
            self.assertEqual(report.rejected, 1)

    def test_rejects_an_unknown_publication_without_breaking_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback-inbox"
            output = root / "01 - À PRÉPARER"
            inbox.mkdir()
            database = root / "veille.sqlite"
            store = Store(database)
            store.close()
            request_email(inbox / "request.eml")

            report = run_linkedin_import(
                inbox,
                database,
                output,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            self.assertEqual(report.accepted, 0)
            self.assertEqual(report.rejected, 1)
            store = Store(database)
            try:
                row = store.connection.execute(
                    "SELECT status, publication_identity, reason "
                    "FROM linkedin_request_messages"
                ).fetchone()
                self.assertEqual(row[0], "rejected")
                self.assertIsNone(row[1])
                self.assertIn("Publication inconnue", row[2])
                self.assertEqual(
                    store.connection.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
