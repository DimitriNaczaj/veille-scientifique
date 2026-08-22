import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from veille.__main__ import main


class SecretMigrationTests(unittest.TestCase):
    def test_extracts_inline_password_preserves_other_secrets_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "veille-scientifique.ini"
            secrets = root / "secrets.env"
            password = "pa ss$'word"
            smtp_password = "distinct smtp$password"
            config.write_text(
                """[imap]
host = mail.example.org
username = science-digest@example.org
password = {}
folder = Articles

[smtp]
host = mail.example.org
password = {}
""".format(password, smtp_password),
                encoding="utf-8",
            )
            secrets.write_text("OPENAI_API_KEY=legacy-key\n", encoding="utf-8")
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "migrate-secrets",
                        "--config",
                        str(config),
                        "--secrets",
                        str(secrets),
                    ]
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertTrue(report["migrated"])
            config_text = config.read_text(encoding="utf-8")
            self.assertNotIn(password, config_text)
            self.assertNotIn(smtp_password, config_text)
            self.assertNotIn("password =", config_text)
            self.assertIn(
                "password_env = SCIENCE_DIGEST_MAIL_PASSWORD", config_text
            )
            self.assertIn(
                "password_env = SCIENCE_DIGEST_SMTP_PASSWORD", config_text
            )
            secrets_text = secrets.read_text(encoding="utf-8")
            self.assertIn("OPENAI_API_KEY=legacy-key\n", secrets_text)
            self.assertIn(
                "SCIENCE_DIGEST_MAIL_PASSWORD={}\n".format(shlex.quote(password)),
                secrets_text,
            )
            self.assertIn(
                "SCIENCE_DIGEST_SMTP_PASSWORD={}\n".format(
                    shlex.quote(smtp_password)
                ),
                secrets_text,
            )
            self.assertEqual(os.stat(config).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(secrets).st_mode & 0o777, 0o600)

            first_secrets = secrets_text
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                second_exit_code = main(
                    [
                        "migrate-secrets",
                        "--config",
                        str(config),
                        "--secrets",
                        str(secrets),
                    ]
                )

            self.assertEqual(second_exit_code, 0)
            self.assertFalse(json.loads(stdout.getvalue())["migrated"])
            self.assertEqual(secrets.read_text(encoding="utf-8"), first_secrets)

    def test_daily_launcher_loads_legacy_then_prefers_combined_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "environment.txt"
            fake_python = root / "fake-python"
            fake_python.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$OPENAI_API_KEY" > "$VEILLE_TEST_OUTPUT"
printf '%s\n' "$SCIENCE_DIGEST_MAIL_PASSWORD" >> "$VEILLE_TEST_OUTPUT"
printf '%s\n' "$SCIENCE_DIGEST_SMTP_PASSWORD" >> "$VEILLE_TEST_OUTPUT"
""",
                encoding="utf-8",
            )
            fake_python.chmod(0o700)
            (root / "openai.env").write_text(
                "OPENAI_API_KEY=legacy-key\n", encoding="utf-8"
            )
            (root / "secrets.env").write_text(
                "OPENAI_API_KEY=combined-key\n"
                "SCIENCE_DIGEST_MAIL_PASSWORD=mail-key\n"
                "SCIENCE_DIGEST_SMTP_PASSWORD=smtp-key\n",
                encoding="utf-8",
            )
            launcher = Path(__file__).parents[1] / "scripts" / "run-daily.sh"
            environment = os.environ.copy()
            environment.update(
                {
                    "VEILLE_ROOT": str(root),
                    "PYTHON_BIN": str(fake_python),
                    "VEILLE_TEST_OUTPUT": str(output),
                }
            )

            subprocess.run(
                ["bash", str(launcher)],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "combined-key\nmail-key\nsmtp-key\n",
            )


if __name__ == "__main__":
    unittest.main()
