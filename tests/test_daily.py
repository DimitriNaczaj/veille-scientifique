import io
import json
import mailbox
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from tests.test_digest_delivery import FakeSMTP
from tests.test_imap_sync import FakeSyncIMAP
from veille.__main__ import main
from veille.feedback import create_feedback_token
from veille.linkedin_bridge import create_linkedin_request_token
from veille.mbox_import import run_mbox_import
from veille.models import ParsedMessage, PublicationCandidate
from veille.storage import Store


class StubResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit=None):
        return json.dumps(
            {
                "message": {
                    "title": ["Social norms and household energy conservation"],
                    "abstract": (
                        "A randomized field experiment tests behavioral responses "
                        "to social norms among households."
                    ),
                    "container-title": ["Behavioral Science"],
                    "published": {"date-parts": [[2026, 8, 21]]},
                    "author": [{"given": "Amina", "family": "Martin"}],
                    "URL": "https://doi.org/10.1234/example",
                }
            }
        ).encode("utf-8")


class EmptyIMAP(FakeSyncIMAP):
    def select(self, folder, readonly=False):
        self.selection = (folder, readonly)
        return "OK", [b"0"]

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b""]
        return super().uid(command, *args)


class DailyCommandTests(unittest.TestCase):
    def setUp(self):
        FakeSyncIMAP.instances = []
        FakeSMTP.instances = []
        clock = patch(
            "veille.delivery.paris_now",
            return_value=datetime(2026, 10, 12, 8, 30),
        )
        clock.start()
        self.addCleanup(clock.stop)

    def test_runs_sync_enrichment_digest_and_delivery_in_one_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            config.write_text(
                """[imap]
host = mail.example.org
port = 993
username = science-digest@example.org
password = super-secret-password
folder = Articles
initial_mode = all

[smtp]
host = smtp.example.org
port = 587
security = starttls

[digest]
recipient = consultant@bellegarde.example

[app]
inbox = {inbox}
database = {database}
output = {output}
sync_limit = 10
enrichment_limit = 10
ai_limit = 5
""".format(
                    inbox=root / "inbox",
                    database=root / "data" / "veille.sqlite",
                    output=root / "out" / "digest.html",
                ),
                encoding="utf-8",
            )

            def open_request(request, timeout, context=None):
                return StubResponse()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    ["daily", "--config", str(config), "--no-ai"],
                    imap_factory=FakeSyncIMAP,
                    smtp_factory=FakeSMTP,
                    http_opener=open_request,
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["sync"]["messages_downloaded"], 2)
            self.assertEqual(report["pipeline"]["publications_new"], 1)
            self.assertEqual(report["pipeline"]["publications_relevant"], 1)
            self.assertFalse(report["ai_enabled"])
            self.assertTrue(report["email_sent"])
            self.assertEqual(
                report["recipient"], "consultant@bellegarde.example"
            )
            self.assertTrue((root / "out" / "digest.html").is_file())
            self.assertEqual(len(FakeSMTP.instances[0].messages), 1)

    def test_weekend_digest_is_deferred_and_sent_on_monday(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            config.write_text(
                """[imap]
host = mail.example.org
port = 993
username = science-digest@example.org
password = super-secret-password
folder = Articles
initial_mode = all

[smtp]
host = smtp.example.org
port = 587
security = starttls

[digest]
recipient = consultant@bellegarde.example

[app]
inbox = {inbox}
database = {database}
output = {output}
sync_limit = 10
enrichment_limit = 10
ai_limit = 5
""".format(
                    inbox=root / "inbox",
                    database=root / "data" / "veille.sqlite",
                    output=root / "out" / "digest.html",
                ),
                encoding="utf-8",
            )

            def open_request(request, timeout, context=None):
                return StubResponse()

            saturday_output = io.StringIO()
            with patch(
                "veille.delivery.paris_now",
                return_value=datetime(2026, 10, 17, 8, 30),
            ), redirect_stdout(saturday_output):
                saturday_exit_code = main(
                    ["daily", "--config", str(config), "--no-ai"],
                    imap_factory=FakeSyncIMAP,
                    smtp_factory=FakeSMTP,
                    http_opener=open_request,
                )

            saturday = json.loads(saturday_output.getvalue())
            self.assertEqual(saturday_exit_code, 0)
            self.assertFalse(saturday["email_sent"])
            self.assertEqual(saturday["pipeline"]["publications_relevant"], 1)
            self.assertEqual(saturday["pipeline"]["publications_pending"], 1)
            self.assertEqual(FakeSMTP.instances, [])

            monday_output = io.StringIO()
            with redirect_stdout(monday_output):
                monday_exit_code = main(
                    ["daily", "--config", str(config), "--no-ai"],
                    imap_factory=FakeSyncIMAP,
                    smtp_factory=FakeSMTP,
                    http_opener=open_request,
                )

            monday = json.loads(monday_output.getvalue())
            self.assertEqual(monday_exit_code, 0)
            self.assertTrue(monday["email_sent"])
            self.assertEqual(monday["pipeline"]["publications_relevant"], 1)
            self.assertEqual(monday["pipeline"]["publications_pending"], 0)
            self.assertEqual(len(FakeSMTP.instances), 1)
            self.assertEqual(len(FakeSMTP.instances[0].messages), 1)

    def test_daily_never_delivers_the_historical_mbox_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "articles.mbox"
            archive = mailbox.mbox(str(source), create=True)
            message = EmailMessage()
            message["Message-ID"] = "<historical@example.org>"
            message["From"] = "publisher@example.org"
            message["Subject"] = "Historical newsletter"
            message.set_content(
                "Social norms and household choices\nDOI: 10.1234/history.1"
            )
            archive.add(message)
            archive.flush()
            archive.close()
            database = root / "veille.sqlite"
            run_mbox_import(
                source,
                database,
                root / "catalog.csv",
                root / "import.json",
            )
            config = root / "veille.ini"
            config.write_text(
                """[imap]
host = mail.example.org
username = science-digest@example.org
password = super-secret-password
folder = Articles
initial_mode = latest

[smtp]
test_recipient = science-digest@example.org

[digest]
recipient = consultant@bellegarde.example

[app]
inbox = {inbox}
database = {database}
output = {output}
""".format(
                    inbox=root / "inbox",
                    database=database,
                    output=root / "digest.html",
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["daily", "--config", str(config), "--no-ai"],
                    imap_factory=EmptyIMAP,
                    smtp_factory=FakeSMTP,
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["pipeline"]["publications_delivered"], 0)
            self.assertEqual(report["pipeline"]["publications_pending"], 0)
            self.assertFalse(report["email_sent"])
            self.assertEqual(FakeSMTP.instances, [])

    def test_daily_imports_a_sent_feedback_validation_from_inbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            store = Store(database)
            try:
                store.add_message(
                    ParsedMessage(
                        identity="<source@example.org>",
                        subject="Newsletter",
                        sender="publisher@example.org",
                        publications=(
                            PublicationCandidate(
                                identity="doi:10.1234/daily-feedback",
                                doi="10.1234/daily-feedback",
                                title="Daily feedback article",
                                url=None,
                            ),
                        ),
                    ),
                    "source.eml",
                )
                store.mark_delivered(store.catalog_publications())
            finally:
                store.close()

            feedback_inbox = root / "feedback-inbox"
            feedback_inbox.mkdir()
            feedback_message = EmailMessage()
            feedback_message["Message-ID"] = "<feedback@example.org>"
            feedback_message["From"] = "consultant@bellegarde.example"
            feedback_message["To"] = "science-digest@example.org"
            feedback_message["Subject"] = "[Veille feedback] Écarté"
            feedback_message.set_content(
                "VEILLE-FEEDBACK/1\nchoice=excluded\ntoken={}\n".format(
                    create_feedback_token(
                        "doi:10.1234/daily-feedback", "feedback-secret"
                    )
                )
            )
            (feedback_inbox / "feedback.eml").write_bytes(
                feedback_message.as_bytes()
            )
            article_inbox = root / "article-inbox"
            article_inbox.mkdir()
            config = root / "veille.ini"
            config.write_text(
                """[imap]
host = mail.example.org
username = science-digest@example.org
password = super-secret-password
folder = Articles
initial_mode = latest

[digest]
recipient = consultant@bellegarde.example

[feedback]
enabled = true
recipient = science-digest@example.org
authorized_sender = consultant@bellegarde.example
folder = INBOX
inbox = {feedback_inbox}
token_secret = feedback-secret
sync_limit = 50

[app]
inbox = {article_inbox}
database = {database}
output = {output}
""".format(
                    feedback_inbox=feedback_inbox,
                    article_inbox=article_inbox,
                    database=database,
                    output=root / "digest.html",
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["daily", "--config", str(config), "--no-ai", "--no-send"],
                    imap_factory=EmptyIMAP,
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertTrue(report["feedback"]["enabled"])
            self.assertEqual(report["feedback"]["sync"]["folder"], "INBOX")
            self.assertEqual(report["feedback"]["import"]["accepted"], 1)
            self.assertEqual(FakeSyncIMAP.instances[0].selection, ("INBOX", True))
            self.assertEqual(FakeSyncIMAP.instances[1].selection, ("Articles", True))

    def test_daily_imports_linkedin_request_from_shared_feedback_inbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            publication_identity = "doi:10.1234/daily-linkedin"
            store = Store(database)
            try:
                store.add_message(
                    ParsedMessage(
                        identity="<source-linkedin@example.org>",
                        subject="Newsletter",
                        sender="publisher@example.org",
                        publications=(
                            PublicationCandidate(
                                identity=publication_identity,
                                doi="10.1234/daily-linkedin",
                                title="Daily LinkedIn article",
                                url=None,
                            ),
                        ),
                    ),
                    "source.eml",
                )
                store.mark_delivered(store.catalog_publications())
            finally:
                store.close()

            feedback_inbox = root / "feedback-inbox"
            feedback_inbox.mkdir()
            request = EmailMessage()
            request["Message-ID"] = "<linkedin@example.org>"
            request["From"] = "consultant@bellegarde.example"
            request["To"] = "science-digest@example.org"
            request["Subject"] = "[Veille vers LinkedIn] Daily LinkedIn article"
            request.set_content(
                "VEILLE-LINKEDIN/1\ntoken={}\n".format(
                    create_linkedin_request_token(
                        publication_identity, "linkedin-secret"
                    )
                )
            )
            (feedback_inbox / "linkedin.eml").write_bytes(request.as_bytes())
            article_inbox = root / "article-inbox"
            article_inbox.mkdir()
            linkedin_output = root / "linkedin" / "01 - À PRÉPARER"
            config = root / "veille.ini"
            config.write_text(
                """[imap]
host = mail.example.org
username = science-digest@example.org
password = super-secret-password
folder = Articles
initial_mode = latest

[digest]
recipient = consultant@bellegarde.example

[feedback]
enabled = true
recipient = science-digest@example.org
authorized_sender = consultant@bellegarde.example
folder = INBOX
inbox = {feedback_inbox}
token_secret = feedback-secret
sync_limit = 50

[linkedin]
enabled = true
recipient = science-digest@example.org
authorized_sender = consultant@bellegarde.example
folder = INBOX
inbox = {feedback_inbox}
output = {linkedin_output}
token_secret = linkedin-secret
sync_limit = 50
download_pdf = false

[app]
inbox = {article_inbox}
database = {database}
output = {output}
""".format(
                    feedback_inbox=feedback_inbox,
                    linkedin_output=linkedin_output,
                    article_inbox=article_inbox,
                    database=database,
                    output=root / "digest.html",
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["daily", "--config", str(config), "--no-ai", "--no-send"],
                    imap_factory=EmptyIMAP,
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertTrue(report["linkedin"]["enabled"])
            self.assertEqual(report["linkedin"]["import"]["accepted"], 1)
            self.assertEqual(len(list(linkedin_output.iterdir())), 1)
            self.assertEqual(len(FakeSyncIMAP.instances), 2)


if __name__ == "__main__":
    unittest.main()
