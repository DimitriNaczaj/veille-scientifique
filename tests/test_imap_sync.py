import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from email.message import EmailMessage
from pathlib import Path

from veille.__main__ import main


def message_bytes(message_id, subject):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = "alerts@example.org"
    message["To"] = "science-digest@example.org"
    message["Subject"] = subject
    message.set_content("DOI: 10.1234/example")
    return message.as_bytes()


class FakeSyncIMAP:
    instances = []

    def __init__(self, host, port, ssl_context=None):
        self.host = host
        self.port = port
        self.login_credentials = None
        self.selection = None
        self.fetches = []
        self.logged_out = False
        self.__class__.instances.append(self)

    def login(self, username, password):
        self.login_credentials = (username, password)
        return "OK", [b"authenticated"]

    def select(self, folder, readonly=False):
        self.selection = (folder, readonly)
        return "OK", [b"2"]

    def response(self, name):
        if name == "UIDVALIDITY":
            return "UIDVALIDITY", [b"4242"]
        return None, None

    def uid(self, command, *args):
        if command == "SEARCH":
            criterion = args[-1]
            if criterion == "UID 13:*":
                return "OK", [b""]
            return "OK", [b"11 12"]
        if command == "FETCH":
            uid = int(args[0])
            self.fetches.append(uid)
            return "OK", [
                (
                    "{} (UID {} RFC822 {{{}}}".format(uid, uid, 10).encode("ascii"),
                    message_bytes(
                        "<{}@example.org>".format(uid),
                        "Newsletter {}".format(uid),
                    ),
                ),
                b")",
            ]
        raise AssertionError("Commande IMAP inattendue: {}".format(command))

    def logout(self):
        self.logged_out = True
        return "BYE", [b"logout"]


class EmptyThenNewIMAP(FakeSyncIMAP):
    search_count = 0

    def uid(self, command, *args):
        if command == "SEARCH":
            self.__class__.search_count += 1
            if self.__class__.search_count == 1:
                return "OK", [b""]
            return "OK", [b"5"]
        return super().uid(command, *args)


def write_config(path):
    Path(path).write_text(
        """[imap]
host = mail.example.org
port = 993
username = science-digest@example.org
password = super-secret-password
folder = Articles
""",
        encoding="utf-8",
    )


class IMAPSyncCommandTests(unittest.TestCase):
    def setUp(self):
        FakeSyncIMAP.instances = []
        EmptyThenNewIMAP.instances = []
        EmptyThenNewIMAP.search_count = 0

    def test_downloads_new_uids_read_only_and_resumes_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            inbox = root / "inbox"
            database = root / "data" / "veille.sqlite"
            write_config(config)

            first_stdout = io.StringIO()
            with redirect_stdout(first_stdout):
                first_exit = main(
                    [
                        "sync-imap",
                        "--config",
                        str(config),
                        "--inbox",
                        str(inbox),
                        "--database",
                        str(database),
                        "--limit",
                        "10",
                    ],
                    imap_factory=FakeSyncIMAP,
                )

            self.assertEqual(first_exit, 0)
            first = json.loads(first_stdout.getvalue())
            self.assertEqual(first["messages_downloaded"], 2)
            self.assertEqual(first["last_uid"], 12)
            self.assertEqual(first["uidvalidity"], "4242")
            self.assertEqual(
                sorted(path.name for path in inbox.glob("*.eml")),
                ["imap-4242-11.eml", "imap-4242-12.eml"],
            )
            client = FakeSyncIMAP.instances[0]
            self.assertEqual(client.selection, ("Articles", True))
            self.assertEqual(client.fetches, [11, 12])
            self.assertTrue(client.logged_out)

            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                second_exit = main(
                    [
                        "sync-imap",
                        "--config",
                        str(config),
                        "--inbox",
                        str(inbox),
                        "--database",
                        str(database),
                    ],
                    imap_factory=FakeSyncIMAP,
                )

            self.assertEqual(second_exit, 0)
            second = json.loads(second_stdout.getvalue())
            self.assertEqual(second["messages_downloaded"], 0)
            self.assertEqual(FakeSyncIMAP.instances[1].fetches, [])

    def test_latest_initialization_skips_historical_messages_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            write_config(config)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "sync-imap",
                        "--config",
                        str(config),
                        "--inbox",
                        str(root / "inbox"),
                        "--database",
                        str(root / "veille.sqlite"),
                        "--initial-mode",
                        "latest",
                    ],
                    imap_factory=FakeSyncIMAP,
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["messages_downloaded"], 0)
            self.assertEqual(report["messages_skipped_on_initialization"], 2)
            self.assertEqual(report["last_uid"], 12)
            self.assertEqual(FakeSyncIMAP.instances[0].fetches, [])

    def test_empty_initialization_does_not_skip_the_first_future_message(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            inbox = root / "inbox"
            database = root / "veille.sqlite"
            write_config(config)
            arguments = [
                "sync-imap",
                "--config",
                str(config),
                "--inbox",
                str(inbox),
                "--database",
                str(database),
                "--initial-mode",
                "latest",
            ]

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments, imap_factory=EmptyThenNewIMAP), 0)
            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout):
                self.assertEqual(main(arguments, imap_factory=EmptyThenNewIMAP), 0)

            report = json.loads(second_stdout.getvalue())
            self.assertEqual(report["messages_downloaded"], 1)
            self.assertEqual(report["last_uid"], 5)


if __name__ == "__main__":
    unittest.main()
