import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from veille.linkedin_worker import run_linkedin_worker


class LinkedinWorkerTests(unittest.TestCase):
    def test_syncs_then_imports_without_running_the_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            output = root / "publisher" / "01 - À PRÉPARER"
            config = root / "veille.ini"
            config.write_text(
                """[imap]
username = science@example.org

[linkedin]
enabled = true
recipient = science@example.org
authorized_sender = dimitri@example.org
token_secret = secret
inbox = {inbox}
output = {output}
download_pdf = false
""".format(inbox=inbox, output=output),
                encoding="utf-8",
            )
            sync_report = type("Sync", (), {"errors": (), "as_dict": lambda self: {}})()
            import_report = type(
                "Import",
                (),
                {
                    "rejected": 0,
                    "warnings": (),
                    "as_dict": lambda self: {"accepted": 0},
                },
            )()

            with patch("veille.linkedin_worker.run_imap_sync", return_value=sync_report) as sync, patch(
                "veille.linkedin_worker.run_linkedin_import", return_value=import_report
            ) as importer:
                report = run_linkedin_worker(config, root / "veille.sqlite")

            self.assertEqual(report.as_dict()["service"], "linkedin-worker")
            self.assertEqual(sync.call_count, 1)
            self.assertEqual(sync.call_args.kwargs["initial_mode"], "all")
            self.assertEqual(importer.call_count, 1)
