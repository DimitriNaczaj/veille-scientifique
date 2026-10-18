import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from veille.citations import RIS_FILENAME
from veille.delivery import SMTPDigestSender, load_digest_delivery_settings
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


def write_config(path, attach_ris=False, linkedin=False):
    linkedin_section = ""
    if linkedin:
        linkedin_section = """

[linkedin]
enabled = true
recipient = science-digest@example.org
token_secret = linkedin-secret
"""
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
from_name = Bellegarde Science Digest
subject_prefix = Veille scientifique
attach_ris = {}
{}""".format(str(attach_ris).lower(), linkedin_section),
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
            digest.write_text(
                "<html><body><h1>Veille</h1>"
                '<img src="cid:bellegarde-logo-black">'
                '<img src="cid:bellegarde-logo-white">'
                "</body></html>",
                encoding="utf-8",
            )
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
            self.assertEqual(
                message["From"],
                "Bellegarde Science Digest <science-digest@example.org>",
            )
            self.assertEqual(message["Subject"], "Veille scientifique — 1 article")
            self.assertTrue(message.is_multipart())
            self.assertIn(
                "Social norms and household energy conservation",
                message.get_body(preferencelist=("plain",)).get_content(),
            )
            self.assertIn(
                "<h1>Veille</h1>",
                message.get_body(preferencelist=("html",)).get_content(),
            )
            related_images = {
                part["Content-ID"]: part
                for part in message.walk()
                if part.get_content_maintype() == "image"
            }
            self.assertEqual(
                set(related_images),
                {"<bellegarde-logo-black>", "<bellegarde-logo-white>"},
            )
            self.assertEqual(
                {image.get_filename() for image in related_images.values()},
                {"logo-baseline-black.png", "logo-baseline-white.png"},
            )
            for image in related_images.values():
                self.assertEqual(image.get_content_type(), "image/png")
                self.assertTrue(image.get_payload(decode=True).startswith(b"\x89PNG"))
            self.assertFalse(
                any(
                    part.get_content_type() == "application/x-research-info-systems"
                    for part in message.walk()
                )
            )

    def test_sends_digest_to_multiple_comma_separated_recipients(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            digest = root / "digest.html"
            digest.write_text("<html><body>Veille</body></html>", encoding="utf-8")
            write_config(config)
            content = config.read_text(encoding="utf-8").replace(
                "recipient = consultant@bellegarde.example",
                "recipient = consultant@bellegarde.example, eric@bellegarde.example",
            )
            config.write_text(content, encoding="utf-8")
            publication = NewPublication(
                identity="doi:10.1234/test",
                doi="10.1234/test",
                title="Article",
                url=None,
                source_subject="Newsletter",
                source_sender="alerts@example.org",
                priority=PublicationPriority.HIGH,
            )

            sender = SMTPDigestSender(config, smtp_factory=FakeSMTP)
            sender.send(digest, (publication,))

            message = FakeSMTP.instances[0].messages[0]
            self.assertEqual(
                message["To"],
                "consultant@bellegarde.example, eric@bellegarde.example",
            )

    def test_attaches_ris_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            digest = root / "digest.html"
            digest.write_text("<html><body>Veille</body></html>", encoding="utf-8")
            write_config(config, attach_ris=True)
            publication = NewPublication(
                identity="doi:10.1234/test",
                doi="10.1234/test",
                title="Article",
                url=None,
                source_subject="Newsletter",
                source_sender="publisher@example.org",
            )

            SMTPDigestSender(config, smtp_factory=FakeSMTP).send(digest, (publication,))

            message = FakeSMTP.instances[0].messages[0]
            attachments = list(message.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), RIS_FILENAME)

    def test_plain_alternative_contains_the_linkedin_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            digest = root / "digest.html"
            digest.write_text("<html><body>Veille</body></html>", encoding="utf-8")
            write_config(config, linkedin=True)
            publication = NewPublication(
                identity="doi:10.1234/linkedin",
                doi="10.1234/linkedin",
                title="Article LinkedIn",
                url=None,
                source_subject="Newsletter",
                source_sender="publisher@example.org",
            )

            SMTPDigestSender(config, smtp_factory=FakeSMTP).send(
                digest, (publication,)
            )

            plain = FakeSMTP.instances[0].messages[0].get_body(
                preferencelist=("plain",)
            ).get_content()
            self.assertIn("Préparer un post LinkedIn :", plain)
            self.assertIn("VEILLE-LINKEDIN%2F1", plain)

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

    def test_defers_digest_on_saturday_and_sunday(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille.ini"
            digest = root / "digest.html"
            digest.write_text("<html></html>", encoding="utf-8")
            write_config(config)
            publication = NewPublication(
                identity="doi:10.1234/weekend",
                doi="10.1234/weekend",
                title="Article du week-end",
                url=None,
                source_subject="Newsletter",
                source_sender="publisher@example.org",
            )

            for day in (17, 18):
                with self.subTest(day=day), patch(
                    "veille.delivery.paris_now",
                    return_value=datetime(2026, 10, day, 8, 30),
                ):
                    FakeSMTP.instances = []
                    sender = SMTPDigestSender(
                        config,
                        smtp_factory=FakeSMTP,
                        defer_weekends=True,
                    )
                    result = sender.send(digest, (publication,))

                    self.assertFalse(sender.sent)
                    self.assertTrue(result.deferred)
                    self.assertIn("lundi", result.reason)
                    self.assertEqual(FakeSMTP.instances, [])

    def test_refuses_real_recipient_equal_to_smtp_test_recipient(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "veille.ini"
            config.write_text(
                """[imap]
host = mail.example.org
username = science-digest@example.org
password = super-secret-password

[smtp]
test_recipient = consultant@bellegarde.example

[digest]
recipient = Consultant@Bellegarde.Example
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "destinataire de test"):
                load_digest_delivery_settings(config)


if __name__ == "__main__":
    unittest.main()
