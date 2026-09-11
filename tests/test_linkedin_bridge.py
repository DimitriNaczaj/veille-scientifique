import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from veille.linkedin_bridge import (
    LINKEDIN_REQUEST_MARKER,
    create_linkedin_request_token,
    linkedin_request_identity,
    linkedin_request_mailto,
    load_linkedin_settings,
)


SECRET = "linkedin-bridge-secret"
IDENTITY = "doi:10.1234/linkedin.1"


class LinkedinBridgeTests(unittest.TestCase):
    def test_loads_settings_without_a_feedback_section(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "veille.ini"
            config.write_text(
                """[imap]
username = science-digest@example.org

[linkedin]
enabled = true
recipient = science-digest@example.org
token_secret = linkedin-secret
""",
                encoding="utf-8",
            )

            settings = load_linkedin_settings(config)

            self.assertTrue(settings.enabled)
            self.assertEqual(settings.recipient, "science-digest@example.org")
            self.assertEqual(settings.token_secret, "linkedin-secret")

    def test_builds_a_signed_mailto_request(self):
        link = linkedin_request_mailto(
            IDENTITY,
            "A behavioral science article",
            "science-digest@example.org",
            SECRET,
        )

        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        body = query["body"][0]
        token = next(
            line.split("=", 1)[1]
            for line in body.splitlines()
            if line.startswith("token=")
        )

        self.assertEqual(parsed.scheme, "mailto")
        self.assertEqual(parsed.path, "science-digest@example.org")
        self.assertIn("[Veille vers LinkedIn]", query["subject"][0])
        self.assertIn(LINKEDIN_REQUEST_MARKER, body)
        self.assertEqual(linkedin_request_identity(token, SECRET), IDENTITY)

    def test_rejects_a_modified_request_token(self):
        token = create_linkedin_request_token(IDENTITY, SECRET)
        replacement = "0" if token[-1] != "0" else "1"

        with self.assertRaisesRegex(ValueError, "Signature"):
            linkedin_request_identity(token[:-1] + replacement, SECRET)

    def test_rejects_a_feedback_token_used_as_a_linkedin_request(self):
        from veille.feedback import create_feedback_token

        token = create_feedback_token(IDENTITY, SECRET)

        with self.assertRaisesRegex(ValueError, "LinkedIn"):
            linkedin_request_identity(token, SECRET)


if __name__ == "__main__":
    unittest.main()
