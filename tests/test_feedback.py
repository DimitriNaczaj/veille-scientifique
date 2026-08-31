import csv
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from veille.feedback import (
    FeedbackSettings,
    create_feedback_token,
    export_feedback_csv,
    feedback_mailto,
    run_feedback_import,
)
from veille.models import ParsedMessage, PublicationCandidate, PublicationPriority
from veille.storage import Store


SECRET = "feedback-secret-for-tests"
IDENTITY = "doi:10.1234/feedback.1"


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
                        doi="10.1234/feedback.1",
                        title="A feedback-worthy article",
                        url="https://doi.org/10.1234/feedback.1",
                    ),
                ),
            ),
            "newsletter.eml",
        )
    finally:
        store.close()


def validation_email(path, choice, token, sender="consultant@example.org"):
    message = EmailMessage()
    message["Message-ID"] = "<{}@example.org>".format(choice)
    message["From"] = sender
    message["To"] = "science-digest@example.org"
    message["Subject"] = "[Veille feedback] Validation"
    message.set_content(
        "Veille scientifique Bellegarde\n\n"
        "VEILLE-FEEDBACK/1\n"
        "choice={}\n"
        "token={}\n".format(choice, token)
    )
    path.write_bytes(message.as_bytes())


class FeedbackTests(unittest.TestCase):
    def test_builds_three_mailto_validation_messages_with_signed_identity(self):
        settings = FeedbackSettings(
            enabled=True,
            recipient="science-digest@example.org",
            authorized_sender="consultant@example.org",
            folder="INBOX",
            inbox="/tmp/feedback",
            token_secret=SECRET,
            sync_limit=50,
        )

        links = {
            priority: feedback_mailto(
                IDENTITY,
                "A feedback-worthy article",
                priority,
                settings,
            )
            for priority in (
                PublicationPriority.HIGH,
                PublicationPriority.WATCH,
                PublicationPriority.EXCLUDED,
            )
        }

        self.assertEqual(len(set(links.values())), 3)
        for priority, link in links.items():
            parsed = urlparse(link)
            query = parse_qs(parsed.query)
            self.assertEqual(parsed.scheme, "mailto")
            self.assertEqual(parsed.path, "science-digest@example.org")
            self.assertIn("[Veille feedback]", query["subject"][0])
            self.assertIn("VEILLE-FEEDBACK/1", query["body"][0])
            self.assertIn("choice={}".format(priority.value), query["body"][0])
            self.assertIn("token=", query["body"][0])

    def test_imports_sent_validation_and_keeps_an_append_only_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            token = create_feedback_token(IDENTITY, SECRET)
            validation_email(inbox / "first.eml", "excluded", token)

            first = run_feedback_import(
                inbox,
                database,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )
            second = run_feedback_import(
                inbox,
                database,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            self.assertEqual(first.accepted, 1)
            self.assertEqual(first.rejected, 0)
            self.assertEqual(second.accepted, 0)
            self.assertEqual(second.already_processed, 1)
            store = Store(database)
            try:
                feedback = store.latest_publication_feedback(IDENTITY)
                self.assertEqual(feedback["priority"], "excluded")
                self.assertEqual(feedback["sender"], "consultant@example.org")
                self.assertEqual(store.feedback_count(), 1)
            finally:
                store.close()

    def test_rejects_a_forged_sender_and_a_tampered_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            token = create_feedback_token(IDENTITY, SECRET)
            validation_email(
                inbox / "forged.eml",
                "high",
                token,
                sender="attacker@example.org",
            )
            validation_email(
                inbox / "tampered.eml",
                "watch",
                token + "x",
            )

            report = run_feedback_import(
                inbox,
                database,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            self.assertEqual(report.accepted, 0)
            self.assertEqual(report.rejected, 2)
            self.assertEqual(len(report.warnings), 2)
            store = Store(database)
            try:
                self.assertEqual(store.feedback_count(), 0)
            finally:
                store.close()

    def test_exports_feedback_with_the_original_ai_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "feedback"
            inbox.mkdir()
            database = root / "veille.sqlite"
            add_publication(database)
            validation_email(
                inbox / "feedback.eml",
                "excluded",
                create_feedback_token(IDENTITY, SECRET),
            )
            run_feedback_import(
                inbox,
                database,
                authorized_sender="consultant@example.org",
                token_secret=SECRET,
            )

            output = root / "feedback.csv"
            report = export_feedback_csv(database, output)

            self.assertEqual(report["feedback_count"], 1)
            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["publication_identity"], IDENTITY)
            self.assertEqual(rows[0]["user_priority"], "excluded")
            self.assertEqual(rows[0]["title"], "A feedback-worthy article")
            self.assertEqual(rows[0]["ai_priority"], "")


if __name__ == "__main__":
    unittest.main()
