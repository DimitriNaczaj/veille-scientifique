import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from veille.__main__ import main
from veille.reporting import format_daily_error, format_daily_report


REPORT = {
    "ai_enabled": True,
    "email_sent": False,
    "errors": [],
    "pipeline": {
        "ai_input_tokens": 499,
        "ai_output_tokens": 84,
        "errors": [],
        "messages_processed": 1,
        "messages_skipped": 8,
        "publications_ai_analyzed": 1,
        "publications_detected": 1,
        "publications_excluded": 1,
        "publications_new": 1,
        "publications_pending": 0,
        "publications_relevant": 0,
        "warnings": [],
    },
    "recipient": None,
    "service": "daily",
    "status": "ok",
    "sync": {
        "errors": [],
        "folder": "Articles",
        "last_uid": 1367,
        "messages_available": 1,
        "messages_downloaded": 1,
        "messages_existing": 0,
        "warnings": [],
    },
    "warnings": [],
}


class StubReport:
    errors = ()

    def as_dict(self):
        return REPORT


class PartialReport:
    errors = ("Analyse impossible",)

    def as_dict(self):
        report = dict(REPORT)
        report["status"] = "partial"
        report["errors"] = ["Analyse impossible"]
        return report


class DailyReportingTests(unittest.TestCase):
    def test_formats_daily_json_as_a_concise_french_report(self):
        output = format_daily_report(REPORT)

        self.assertIn("VEILLE SCIENTIFIQUE", output)
        self.assertIn("Statut                  OK", output)
        self.assertIn("Dossier IMAP            Articles", output)
        self.assertIn("Messages téléchargés    1", output)
        self.assertIn("Articles analysés       1", output)
        self.assertIn("Articles retenus        0", output)
        self.assertIn("Articles écartés        1", output)
        self.assertIn("Tokens IA               583 (499 entrée + 84 sortie)", output)
        self.assertIn("Newsletter envoyée      non", output)
        self.assertIn("Avertissements          aucun", output)
        self.assertIn("Erreurs                 aucune", output)
        self.assertNotIn("null", output)
        self.assertNotIn("{\"", output)

    def test_daily_cli_can_emit_the_human_report(self):
        stdout = io.StringIO()
        with patch("veille.__main__.run_daily", return_value=StubReport()), redirect_stdout(
            stdout
        ):
            exit_code = main(
                ["daily", "--config", "unused.ini", "--format", "human"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), format_daily_report(REPORT))

    def test_human_report_keeps_a_nonzero_exit_code_and_lists_report_errors(self):
        stdout = io.StringIO()
        with patch(
            "veille.__main__.run_daily", return_value=PartialReport()
        ), redirect_stdout(stdout):
            exit_code = main(
                ["daily", "--config", "unused.ini", "--format", "human"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("Statut                  PARTIAL", stdout.getvalue())
        self.assertIn("  - Analyse impossible", stdout.getvalue())

    def test_daily_cli_formats_an_exception_for_human_output(self):
        stderr = io.StringIO()
        with patch(
            "veille.__main__.run_daily",
            side_effect=RuntimeError("Configuration absente"),
        ), redirect_stderr(stderr):
            exit_code = main(
                ["daily", "--config", "unused.ini", "--format", "human"]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.getvalue().strip(),
            format_daily_error("Configuration absente"),
        )
        self.assertNotIn('{"error"', stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
