import sqlite3
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from veille.mail_parser import normalize_doi, parse_message
from veille.pipeline import run_pipeline


def write_email(path, message_id, subject, plain=None, markup=None):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = "éditeur@example.org"
    message["To"] = "veille@bellegarde.example"
    message["Subject"] = subject
    message.set_content(plain or "Version HTML disponible.")
    if markup:
        message.add_alternative(markup, subtype="html")
    Path(path).write_bytes(message.as_bytes())


class NormalizeDoiTests(unittest.TestCase):
    def test_normalizes_url_case_and_trailing_punctuation(self):
        self.assertEqual(
            normalize_doi("https://doi.org/10.1234/ABC.Def."),
            "10.1234/abc.def",
        )


class PipelineTests(unittest.TestCase):
    def test_extracts_html_links_deduplicates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            database = root / "data" / "veille.sqlite"
            digest = root / "out" / "digest.html"

            write_email(
                inbox / "newsletter-1.eml",
                "<newsletter-1@example.org>",
                "Nouvelles publications — revue A",
                plain=(
                    "Choice architecture in public services\n"
                    "DOI: 10.1234/BEHAV.2026.001\n\n"
                    "Social norms and energy use\n"
                    "https://doi.org/10.5555/norms.42\n"
                ),
            )
            write_email(
                inbox / "newsletter-2.eml",
                "<newsletter-2@example.org>",
                "Sommaire — revue B",
                markup=(
                    "<h2>Article déjà signalé</h2>"
                    '<a href="https://doi.org/10.1234/behav.2026.001">Consulter</a>'
                    "<h2>Defaults and mobility</h2>"
                    '<a href="https://doi.org/10.9999/mobility-7">Consulter</a>'
                ),
            )

            first = run_pipeline(inbox, database, digest)
            self.assertEqual(first.messages_processed, 2)
            self.assertEqual(first.messages_skipped, 0)
            self.assertEqual(first.publications_detected, 4)
            self.assertEqual(first.publications_new, 3)
            self.assertEqual(first.errors, ())

            with sqlite3.connect(str(database)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM publications").fetchone()[0], 3
                )

            html = digest.read_text(encoding="utf-8")
            self.assertIn("3 nouvelle(s) publication(s)", html)
            self.assertIn("Choice architecture in public services", html)
            self.assertIn("10.9999/mobility-7", html)

            second = run_pipeline(inbox, database, digest)
            self.assertEqual(second.messages_processed, 0)
            self.assertEqual(second.messages_skipped, 2)
            self.assertEqual(second.publications_new, 0)
            self.assertIn(
                "Aucune nouvelle publication détectée",
                digest.read_text(encoding="utf-8"),
            )

    def test_uses_content_hash_when_message_id_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "message.eml"
            message = EmailMessage()
            message["From"] = "éditeur@example.org"
            message["Subject"] = "Sans identifiant"
            message.set_content("Article\n10.1111/example.1")
            path.write_bytes(message.as_bytes())

            parsed = parse_message(path)
            self.assertTrue(parsed.identity.startswith("sha256:"))
            self.assertEqual(parsed.publications[0].doi, "10.1111/example.1")


if __name__ == "__main__":
    unittest.main()
