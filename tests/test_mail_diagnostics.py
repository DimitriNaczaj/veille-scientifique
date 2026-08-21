import io
import json
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from veille.__main__ import main


class FakeIMAP:
    instances = []

    def __init__(self, host, port, ssl_context=None):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.connection_timeout = socket.getdefaulttimeout()
        self.login_credentials = None
        self.selection = None
        self.logged_out = False
        self.__class__.instances.append(self)

    def login(self, username, password):
        self.login_credentials = (username, password)
        return "OK", [b"authenticated"]

    def select(self, folder, readonly=False):
        self.selection = (folder, readonly)
        return "OK", [b"1300"]

    def logout(self):
        self.logged_out = True
        return "BYE", [b"logout"]


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ehlo_count = 0
        self.started_tls = False
        self.login_credentials = None
        self.messages = []
        self.closed = False
        self.__class__.instances.append(self)

    def ehlo(self):
        self.ehlo_count += 1
        return 250, b"mail.example.org"

    def starttls(self, context=None):
        self.started_tls = context is not None
        return 220, b"ready for tls"

    def login(self, username, password):
        self.login_credentials = (username, password)
        return 235, b"authenticated"

    def send_message(self, message):
        self.messages.append(message)
        return {}

    def quit(self):
        self.closed = True
        return 221, b"bye"


class FailingIMAP(FakeIMAP):
    def login(self, username, password):
        raise RuntimeError("authentication failed for {}".format(password))


def write_config(path):
    Path(path).write_text(
        """[imap]
host = mail.example.org
port = 993
username = science-digest@example.org
password = super-secret-password
folder = INBOX
""",
        encoding="utf-8",
    )


class MailDiagnosticCommandTests(unittest.TestCase):
    def setUp(self):
        FakeIMAP.instances = []
        FakeSMTP.instances = []

    def test_imap_command_authenticates_and_selects_mailbox_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "veille.ini"
            write_config(config)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["test-imap", "--config", str(config)],
                    imap_factory=FakeIMAP,
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(
                report,
                {
                    "folder": "INBOX",
                    "host": "mail.example.org",
                    "messages": 1300,
                    "port": 993,
                    "service": "imap",
                    "status": "ok",
                },
            )
            client = FakeIMAP.instances[0]
            self.assertEqual(client.connection_timeout, 15)
            self.assertEqual(
                client.login_credentials,
                ("science-digest@example.org", "super-secret-password"),
            )
            self.assertEqual(client.selection, ("INBOX", True))
            self.assertTrue(client.logged_out)
            self.assertIsNone(socket.getdefaulttimeout())
            self.assertNotIn("super-secret-password", stdout.getvalue())

    def test_smtp_command_uses_starttls_and_sends_test_message_to_self(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "veille.ini"
            write_config(config)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["test-smtp", "--config", str(config), "--send-test"],
                    smtp_factory=FakeSMTP,
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(
                report,
                {
                    "host": "mail.example.org",
                    "port": 587,
                    "recipient": "science-digest@example.org",
                    "security": "starttls",
                    "service": "smtp",
                    "status": "ok",
                    "test_message_sent": True,
                },
            )
            client = FakeSMTP.instances[0]
            self.assertEqual(client.ehlo_count, 2)
            self.assertTrue(client.started_tls)
            self.assertEqual(
                client.login_credentials,
                ("science-digest@example.org", "super-secret-password"),
            )
            self.assertEqual(len(client.messages), 1)
            self.assertEqual(
                client.messages[0]["To"], "science-digest@example.org"
            )
            self.assertIn("Test de connexion", client.messages[0]["Subject"])
            self.assertTrue(client.closed)
            self.assertNotIn("super-secret-password", stdout.getvalue())

    def test_connection_error_never_exposes_password(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "veille.ini"
            write_config(config)
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["test-imap", "--config", str(config)],
                    imap_factory=FailingIMAP,
                )

            self.assertEqual(exit_code, 1)
            self.assertNotIn("super-secret-password", stderr.getvalue())
            self.assertIn("[secret masqué]", stderr.getvalue())

    def test_malformed_config_never_exposes_its_content(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "veille.ini"
            config.write_text(
                "[imap]\npassword super-secret-password\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["test-imap", "--config", str(config)])

            self.assertEqual(exit_code, 1)
            self.assertNotIn("super-secret-password", stderr.getvalue())
            self.assertIn("configuration INI est invalide", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
