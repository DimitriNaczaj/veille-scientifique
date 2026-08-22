import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from veille.__main__ import main
from veille.secret_migration import set_openai_api_key


_EXECUTABLE_TEMP_ROOT = Path(__file__).parents[1]


class SecretMigrationTests(unittest.TestCase):
    def test_openai_key_setter_replaces_all_old_values_without_exposing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory) / "secrets.env"
            secrets.write_text(
                "SCIENCE_DIGEST_MAIL_PASSWORD=mail-key\n"
                "OPENAI_API_KEY=malformed-command-text\n"
                "OPENAI_API_KEY=duplicate-old-key\n",
                encoding="utf-8",
            )
            api_key = "sk-proj-" + "A" * 40

            report = set_openai_api_key(
                secrets, reader=lambda prompt: api_key
            )

            content = secrets.read_text(encoding="utf-8")
            self.assertTrue(report.updated)
            self.assertEqual(content.count("OPENAI_API_KEY="), 1)
            self.assertIn("SCIENCE_DIGEST_MAIL_PASSWORD=mail-key\n", content)
            self.assertIn(
                "OPENAI_API_KEY={}\n".format(shlex.quote(api_key)), content
            )
            self.assertNotIn("malformed-command-text", content)
            self.assertNotIn("duplicate-old-key", content)
            self.assertNotIn(api_key, json.dumps(report.as_dict()))
            self.assertEqual(os.stat(secrets).st_mode & 0o777, 0o600)

    def test_openai_key_setter_is_exposed_through_masked_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory) / "secrets.env"
            api_key = "sk-proj-" + "B" * 40
            stdout = io.StringIO()

            with patch(
                "veille.secret_migration.getpass.getpass", return_value=api_key
            ), redirect_stdout(stdout):
                exit_code = main(
                    ["set-openai-key", "--secrets", str(secrets)]
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["service"], "openai-key-setup")
            self.assertTrue(report["updated"])
            self.assertNotIn(api_key, stdout.getvalue())

    def test_openai_key_setter_rejects_multiline_paste_without_changing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory) / "secrets.env"
            original = "SCIENCE_DIGEST_MAIL_PASSWORD=mail-key\n"
            secrets.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Clé OpenAI invalide"):
                set_openai_api_key(
                    secrets,
                    reader=lambda prompt: "sk-proj-valid-looking\rprintf commands",
                )

            self.assertEqual(secrets.read_text(encoding="utf-8"), original)

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
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory(
            dir=str(_EXECUTABLE_TEMP_ROOT)
        ) as executable_directory:
            root = Path(directory)
            output = root / "environment.txt"
            (root / "openai.env").write_text(
                "OPENAI_API_KEY=legacy-key\n", encoding="utf-8"
            )
            (root / "secrets.env").write_text(
                "OPENAI_API_KEY=combined-key\n"
                "SCIENCE_DIGEST_MAIL_PASSWORD=mail-key\n"
                "SCIENCE_DIGEST_SMTP_PASSWORD=smtp-key\n",
                encoding="utf-8",
            )
            python = Path(executable_directory) / "python"
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o700)
            launcher = Path(__file__).parents[1] / "scripts" / "run-daily.sh"
            environment = os.environ.copy()
            environment.update(
                {
                    "VEILLE_ROOT": str(root),
                    "PYTHON_BIN": str(python),
                    "VEILLE_TEST_OUTPUT": str(output),
                }
            )
            probe = r"""
exec() {
    printf '%s\n' "$OPENAI_API_KEY" > "$VEILLE_TEST_OUTPUT"
    printf '%s\n' "$SCIENCE_DIGEST_MAIL_PASSWORD" >> "$VEILLE_TEST_OUTPUT"
    printf '%s\n' "$SCIENCE_DIGEST_SMTP_PASSWORD" >> "$VEILLE_TEST_OUTPUT"
}
source "$1"
"""

            subprocess.run(
                ["bash", "-c", probe, "launcher-probe", str(launcher)],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "combined-key\nmail-key\nsmtp-key\n",
            )

    def test_daily_launcher_detects_python_when_not_explicitly_configured(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory(
            dir=str(_EXECUTABLE_TEMP_ROOT)
        ) as executable_directory:
            root = Path(directory)
            fake_bin = Path(executable_directory)
            python = fake_bin / "python3.9"
            output = root / "python-invocation.txt"
            python.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$0\" \"$@\" > \"$VEILLE_TEST_OUTPUT\"\n",
                encoding="utf-8",
            )
            python.chmod(0o700)
            launcher = Path(__file__).parents[1] / "scripts" / "run-daily.sh"
            environment = os.environ.copy()
            environment.pop("PYTHON_BIN", None)
            environment.update(
                {
                    "PATH": "{}:/usr/bin:/bin".format(fake_bin),
                    "VEILLE_ROOT": str(root),
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
                "{}\n-m\nveille\ndaily\n--config\n{}\n".format(
                    python, root / "veille-scientifique.ini"
                ),
            )

    def test_daily_launcher_skips_an_incompatible_python_candidate(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory(
            dir=str(_EXECUTABLE_TEMP_ROOT)
        ) as executable_directory:
            root = Path(directory)
            fake_bin = Path(executable_directory)
            incompatible = fake_bin / "python3.9"
            compatible = fake_bin / "python3"
            output = root / "python-invocation.txt"
            incompatible.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            incompatible.chmod(0o700)
            compatible.write_text(
                "#!/bin/sh\n"
                "if [ \"${1:-}\" = '-c' ]; then exit 0; fi\n"
                "printf '%s\\n' \"$0\" \"$@\" > \"$VEILLE_TEST_OUTPUT\"\n",
                encoding="utf-8",
            )
            compatible.chmod(0o700)
            launcher = Path(__file__).parents[1] / "scripts" / "run-daily.sh"
            environment = os.environ.copy()
            environment.pop("PYTHON_BIN", None)
            environment.update(
                {
                    "PATH": "{}:/usr/bin:/bin".format(fake_bin),
                    "VEILLE_ROOT": str(root),
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
                output.read_text(encoding="utf-8").splitlines()[0],
                str(compatible),
            )


if __name__ == "__main__":
    unittest.main()
