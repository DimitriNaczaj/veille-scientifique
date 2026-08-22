import tempfile
import unittest
from pathlib import Path

from veille.delivery import SMTPDigestSender
from veille.models import NewPublication, PublicationPriority


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages = []
        self.tls = False
        self.login_credentials = None
        self.__class__.instances.append(self)

    def ehlo(self):
        return 250, b"ok"

    def starttls(self, context=None):
        self.tls = context is not None
        return 220, b"ready"

    def login(self, username, password):
        self.login_credentials = (username, password)
        return 235, b"ok"

    def send_message(self, message):
        self.messages.append(message)
        return {}

    def quit(self):
        return 221, b"bye"


def write_config(path):
    Path(path).write_text(
        """[imap]
host = mail.example.org
username = science-digest@example.org
password = super-secret-password

[smtp]
host = smtp.example.org
port = 587
security = starttls

[digest]
recipient = consultant@bellegarde.example
from_address = science-digest@example.org
subject_prefix = Veille comportementale Bellegarde
""",
        encoding="utf-8",
    )


class DigestDeliveryTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.instances = []

    def test_sends_multipart_digest_to_configured_recipient(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            digest = root / "digest.html"
            digest.write_text("<html><body><h1>Veille</h1></body></html>", encoding="utf-8")
            write_config(config)
            publication = NewPublication(
                identity="doi:10.1234/test",
                doi="10.1234/test",
                title="Social norms and household energy conservation",
                url="https://doi.org/10.1234/test",
                source_subject="Newsletter",
                source_sender="alerts@example.org",
                summary_fr="Les normes sociales réduisent la consommation.",
                priority=PublicationPriority.HIGH,
            )
            sender = SMTPDigestSender(config, smtp_factory=FakeSMTP)

            sender.send(digest, (publication,))

            self.assertTrue(sender.sent)
            self.assertEqual(sender.recipient, "consultant@bellegarde.example")
            client = FakeSMTP.instances[0]
            self.assertTrue(client.tls)
            self.assertEqual(
                client.login_credentials,
                ("science-digest@example.org", "super-secret-password"),
            )
            self.assertEqual(len(client.messages), 1)
            message = client.messages[0]
            self.assertEqual(message["To"], "consultant@bellegarde.example")
            self.assertIn("Veille comportementale Bellegarde", message["Subject"])
            self.assertTrue(message.is_multipart())
            self.assertIn(
                "Social norms and household energy conservation",
                message.get_body(preferencelist=("plain",)).get_content(),
            )
            self.assertIn(
                "<h1>Veille</h1>",
                message.get_body(preferencelist=("html",)).get_content(),
            )

    def test_does_not_send_an_empty_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            digest = root / "digest.html"
            digest.write_text("<html></html>", encoding="utf-8")
            write_config(config)
            sender = SMTPDigestSender(config, smtp_factory=FakeSMTP)

            sender.send(digest, ())

            self.assertFalse(sender.sent)
            self.assertEqual(FakeSMTP.instances, [])


if __name__ == "__main__":
    unittest.main()
