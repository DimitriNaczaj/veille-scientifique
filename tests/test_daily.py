import io
import json
import mailbox
import tempfile
import unittest
from contextlib import redirect_stdout
from email.message import EmailMessage
from pathlib import Path

from tests.test_digest_delivery import FakeSMTP
from tests.test_imap_sync import FakeSyncIMAP
from veille.__main__ import main
from veille.mbox_import import run_mbox_import


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


if __name__ == "__main__":
    unittest.main()
