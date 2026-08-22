import csv
import io
import json
import mailbox
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from email.message import EmailMessage
from pathlib import Path

from veille.mbox_import import run_mbox_import
from veille.__main__ import main
from veille.mail_parser import publication_identity_from_title
from veille.models import ParsedMessage, PublicationCandidate, WorkMetadata
from veille.pipeline import run_pipeline
from veille.storage import Store


def add_message(target, message_id, subject, body):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = "publisher@example.org"
    message["To"] = "science-digest@example.org"
    message["Subject"] = subject
    message.set_content(body)
    target.add(message)


def add_html_message(target, message_id, sender, subject, markup):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = sender
    message["To"] = "science-digest@example.org"
    message["Subject"] = subject
    message.set_content("Version HTML disponible.")
    message.add_alternative(markup, subtype="html")
    target.add(message)


class MboxImportTests(unittest.TestCase):
    def test_migrates_existing_reverse_order_duplicates_to_doi_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite"
            title = "How social norms shape household energy decisions"
            connection = sqlite3.connect(str(database))
            try:
                connection.executescript(
                    """
                    CREATE TABLE publications (
                        identity TEXT PRIMARY KEY,
                        doi TEXT UNIQUE,
                        title TEXT,
                        url TEXT,
                        first_seen_at TEXT NOT NULL,
                        delivered_at TEXT
                    );
                    CREATE TABLE publication_metadata (
                        publication_identity TEXT PRIMARY KEY REFERENCES publications(identity),
                        status TEXT NOT NULL,
                        title TEXT,
                        abstract TEXT,
                        journal TEXT,
                        published_date TEXT,
                        authors_json TEXT NOT NULL DEFAULT '[]',
                        url TEXT,
                        checked_at TEXT NOT NULL
                    );
                    INSERT INTO publications VALUES (
                        'title:legacy', NULL, '{}', 'https://publisher.example/article',
                        '2026-08-20T00:00:00+00:00', NULL
                    );
                    INSERT INTO publications VALUES (
                        'doi:10.1234/merged.1', '10.1234/merged.1', NULL, NULL,
                        '2026-08-21T00:00:00+00:00', NULL
                    );
                    INSERT INTO publication_metadata VALUES (
                        'doi:10.1234/merged.1', 'success', '{}', NULL, NULL,
                        NULL, '[]', NULL, '2026-08-21T00:00:00+00:00'
                    );
                    """.format(title, title)
                )
                connection.commit()
            finally:
                connection.close()

            store = Store(database)
            try:
                self.assertEqual(store.publication_count(), 1)
            finally:
                store.close()

            connection = sqlite3.connect(str(database))
            try:
                doi = connection.execute("SELECT doi FROM publications").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(doi, "10.1234/merged.1")

    def test_metadata_title_reconciles_doi_and_title_in_both_arrival_orders(self):
        title = "How social norms shape household energy decisions"
        metadata = WorkMetadata(
            title=title,
            abstract=None,
            journal="Behavioral Science",
            published_date="2026-08-21",
            authors=(),
            url="https://doi.org/10.1234/metadata.1",
        )
        doi_candidate = PublicationCandidate(
            identity="doi:10.1234/metadata.1",
            doi="10.1234/metadata.1",
            title=None,
            url=None,
        )
        title_candidate = PublicationCandidate(
            identity=publication_identity_from_title(title),
            doi=None,
            title=title,
            url="https://publisher.example/article",
        )
        for order in ("doi-first", "title-first"):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as directory:
                store = Store(Path(directory) / "veille.sqlite")
                try:
                    if order == "doi-first":
                        store.add_message(
                            ParsedMessage(
                                identity="doi-message",
                                subject="DOI alert",
                                sender="publisher@example.org",
                                publications=(doi_candidate,),
                            ),
                            "doi.eml",
                        )
                        store.save_metadata(doi_candidate.identity, metadata)
                        store.add_message(
                            ParsedMessage(
                                identity="title-message",
                                subject="Title alert",
                                sender="publisher@example.org",
                                publications=(title_candidate,),
                            ),
                            "title.eml",
                        )
                    else:
                        store.add_message(
                            ParsedMessage(
                                identity="title-message",
                                subject="Title alert",
                                sender="publisher@example.org",
                                publications=(title_candidate,),
                            ),
                            "title.eml",
                        )
                        store.add_message(
                            ParsedMessage(
                                identity="doi-message",
                                subject="DOI alert",
                                sender="publisher@example.org",
                                publications=(doi_candidate,),
                            ),
                            "doi.eml",
                        )
                        store.save_metadata(doi_candidate.identity, metadata)

                    self.assertEqual(store.publication_count(), 1)
                finally:
                    store.close()

    def test_refuses_any_output_path_that_could_overwrite_another_artifact(self):
        for collision in ("database", "catalog", "report"):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "articles.mbox"
                target = mailbox.mbox(str(source), create=True)
                try:
                    add_message(
                        target,
                        "<collision@example.org>",
                        "Collision test",
                        "Behavioral choices\nDOI: 10.1234/collision.1",
                    )
                    target.flush()
                finally:
                    target.close()
                original_bytes = source.read_bytes()
                paths = {
                    "database": root / "veille.sqlite",
                    "catalog": root / "catalog.csv",
                    "report": root / "report.json",
                }
                paths[collision] = source

                with self.assertRaisesRegex(ValueError, "distincts"):
                    run_mbox_import(
                        source,
                        paths["database"],
                        paths["catalog"],
                        paths["report"],
                    )

                self.assertEqual(source.read_bytes(), original_bytes)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "articles.mbox"
            target = mailbox.mbox(str(source), create=True)
            target.close()
            shared_output = root / "shared-output"
            with self.assertRaisesRegex(ValueError, "distincts"):
                run_mbox_import(
                    source,
                    root / "veille.sqlite",
                    shared_output,
                    shared_output,
                )

    def test_merges_title_identity_when_same_article_later_has_a_doi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "articles.mbox"
            target = mailbox.mbox(str(source), create=True)
            try:
                add_html_message(
                    target,
                    "<provisional@example.org>",
                    "alerts@wiley.com",
                    "First alert",
                    '<a href="https://el.wiley.com/ls/click?upn=first">'
                    "How social norms shape household energy decisions"
                    "</a>",
                )
                add_message(
                    target,
                    "<canonical@example.org>",
                    "Second alert",
                    "How social norms shape household energy decisions\n"
                    "DOI: 10.1234/merged.1",
                )
                target.flush()
            finally:
                target.close()

            report = run_mbox_import(
                source,
                root / "veille.sqlite",
                root / "catalog.csv",
                root / "report.json",
            )

            self.assertEqual(report.publications_detected, 2)
            self.assertEqual(report.publications_unique, 1)
            with (root / "catalog.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["doi"], "10.1234/merged.1")

    def test_reuses_doi_identity_when_title_only_occurrence_arrives_later(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "articles.mbox"
            target = mailbox.mbox(str(source), create=True)
            try:
                add_message(
                    target,
                    "<canonical-first@example.org>",
                    "First alert",
                    "How social norms shape household energy decisions\n"
                    "DOI: 10.1234/merged.1",
                )
                add_html_message(
                    target,
                    "<provisional-second@example.org>",
                    "alerts@wiley.com",
                    "Second alert",
                    '<a href="https://el.wiley.com/ls/click?upn=second">'
                    "How social norms shape household energy decisions"
                    "</a>",
                )
                target.flush()
            finally:
                target.close()

            report = run_mbox_import(
                source,
                root / "veille.sqlite",
                root / "catalog.csv",
                root / "report.json",
            )

            self.assertEqual(report.publications_detected, 2)
            self.assertEqual(report.publications_unique, 1)
            with (root / "catalog.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["doi"], "10.1234/merged.1")

    def test_imports_wiley_and_taylor_tracking_links_through_mbox_seam(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "publishers.mbox"
            target = mailbox.mbox(str(source), create=True)
            try:
                add_html_message(
                    target,
                    "<wiley-mbox@example.org>",
                    "alerts@wiley.com",
                    "Wiley alert",
                    '<a href="https://el.wiley.com/ls/click?upn=wiley-token">'
                    "Behavioral spillovers across organizational teams"
                    "</a>",
                )
                add_html_message(
                    target,
                    "<taylor-mbox@example.org>",
                    "alerts@tandfonline.com",
                    "Taylor and Francis alert",
                    '<a href="https://url6649.tandfonline.com/ls/click?upn=taylor-token">'
                    "Social influence and preventive decisions in communities"
                    "</a>",
                )
                target.flush()
            finally:
                target.close()

            report = run_mbox_import(
                source,
                root / "veille.sqlite",
                root / "catalog.csv",
                root / "report.json",
            )

            self.assertEqual(report.messages_processed, 2)
            self.assertEqual(report.publications_unique, 2)
            self.assertEqual(
                report.sender_domains["wiley.com"]["publications_detected"], 1
            )
            self.assertEqual(
                report.sender_domains["tandfonline.com"]["publications_detected"],
                1,
            )

    def test_imports_and_deduplicates_plain_mbox_into_catalog_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "articles.mbox"
            target = mailbox.mbox(str(source), create=True)
            try:
                add_message(
                    target,
                    "<first@example.org>",
                    "First newsletter",
                    "Social influence and household choices\nDOI: 10.1234/shared.1",
                )
                add_message(
                    target,
                    "<second@example.org>",
                    "Second newsletter",
                    "The same publication appears again\nDOI: 10.1234/shared.1",
                )
                target.flush()
            finally:
                target.close()

            database = root / "data" / "veille.sqlite"
            catalog = root / "out" / "catalog.csv"
            report_path = root / "out" / "import-report.json"

            report = run_mbox_import(source, database, catalog, report_path)

            self.assertEqual(report.messages_total, 2)
            self.assertEqual(report.messages_processed, 2)
            self.assertEqual(report.messages_skipped, 0)
            self.assertEqual(report.messages_without_publication, 0)
            self.assertEqual(report.publications_detected, 2)
            self.assertEqual(report.publications_new, 1)
            self.assertEqual(report.publications_unique, 1)
            self.assertEqual(report.errors, ())
            with catalog.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["doi"], "10.1234/shared.1")
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8")),
                report.as_dict(),
            )

            store = Store(database)
            try:
                self.assertEqual(store.pending_publications(), ())
                self.assertEqual(store.pending_count(), 0)
            finally:
                store.close()

            inbox = root / "inbox"
            inbox.mkdir()
            repeated_message = EmailMessage()
            repeated_message["Message-ID"] = "<live-repeat@example.org>"
            repeated_message["From"] = "publisher@example.org"
            repeated_message["Subject"] = "Live repeat"
            repeated_message.set_content(
                "Social influence and household choices\nDOI: 10.1234/shared.1"
            )
            (inbox / "repeat.eml").write_bytes(repeated_message.as_bytes())
            live = run_pipeline(
                inbox,
                database,
                root / "digest.html",
                deliver_unenriched=True,
            )
            self.assertEqual(live.publications_new, 0)
            self.assertEqual(live.publications_delivered, 0)

            repeated = run_mbox_import(source, database, catalog, report_path)

            self.assertEqual(repeated.messages_processed, 0)
            self.assertEqual(repeated.messages_skipped, 2)
            self.assertEqual(repeated.messages_without_publication, 0)
            self.assertEqual(repeated.publications_detected, 2)
            self.assertEqual(repeated.publications_new, 0)
            self.assertEqual(repeated.publications_unique, 1)
            with catalog.open(newline="", encoding="utf-8") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)
            self.assertEqual(
                repeated.sender_domains["example.org"],
                {
                    "messages": 2,
                    "messages_without_publication": 0,
                    "publications_detected": 2,
                },
            )

    def test_imports_mbox_stored_inside_zip_without_altering_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mbox_path = root / "source.mbox"
            target = mailbox.mbox(str(mbox_path), create=True)
            try:
                add_message(
                    target,
                    "<zipped@example.org>",
                    "Zipped newsletter",
                    "Decision making under uncertainty\nDOI: 10.5678/zipped.1",
                )
                target.flush()
            finally:
                target.close()
            source = root / "articles.mbox.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.write(mbox_path, "Mailbox Export/mbox")
                archive.writestr("__MACOSX/._source.mbox", b"appledouble metadata")
            original_bytes = source.read_bytes()

            report = run_mbox_import(
                source,
                root / "veille.sqlite",
                root / "catalog.csv",
                root / "report.json",
            )

            self.assertEqual(report.messages_processed, 1)
            self.assertEqual(report.publications_unique, 1)
            self.assertEqual(source.read_bytes(), original_bytes)

    def test_exposes_import_through_command_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "articles.mbox"
            target = mailbox.mbox(str(source), create=True)
            try:
                add_message(
                    target,
                    "<cli@example.org>",
                    "Command line newsletter",
                    "Behavioral spillovers in teams\nDOI: 10.9012/cli.1",
                )
                target.flush()
            finally:
                target.close()
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "import-mbox",
                        "--source",
                        str(source),
                        "--database",
                        str(root / "veille.sqlite"),
                        "--catalog",
                        str(root / "catalog.csv"),
                        "--report",
                        str(root / "report.json"),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["messages_processed"], 1)


if __name__ == "__main__":
    unittest.main()
