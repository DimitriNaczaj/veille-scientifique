import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.test_digest_delivery import FakeSMTP
from veille.__main__ import main
from veille.reporting import format_backfill_daily
from veille.models import (
    AIAnalysis,
    ParsedMessage,
    PublicationCandidate,
    PublicationPriority,
    WorkMetadata,
)
from veille.storage import Store


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def write_config(path):
    Path(path).write_text(
        """[imap]
host = mail.example.org
username = science-digest@example.org
password = mail-password

[smtp]
host = mail.example.org
test_recipient = science-digest@example.org

[digest]
recipient = consultant@example.org

[ai]
enabled = true
model = gpt-5.6-luna
api_key_env = OPENAI_API_KEY
""",
        encoding="utf-8",
    )


class BackfillPlanCommandTests(unittest.TestCase):
    def test_daily_backfill_report_is_readable_and_explicitly_says_no_ai(self):
        output = format_backfill_daily(
            {
                "status": "waiting_for_approval",
                "ai_called": False,
                "plan": {
                    "publications_available": 42,
                    "publications_ai_candidates": 12,
                    "enrichment_pending": 3,
                    "expected": {"cost_usd": 0.012345},
                    "maximum": {"cost_usd": 0.045678},
                    "ready_for_ai": False,
                    "sample_output": "/tmp/rattrapage-sample.csv",
                    "sample_size": 50,
                },
            }
        )

        self.assertIn("RATTRAPAGE", output)
        self.assertIn("EN ATTENTE D’APPROBATION", output)
        self.assertIn("Appel IA", output)
        self.assertIn("non", output)
        self.assertIn("Publications disponibles    42", output)
        self.assertIn("Échantillon CSV", output)
        self.assertIn("/tmp/rattrapage-sample.csv", output)

    def test_plan_refuses_paths_that_can_overwrite_the_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "veille.sqlite"
            Store(database).close()
            stderr = io.StringIO()

            with patch("sys.stderr", stderr):
                exit_code = main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(database),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("distincts", json.loads(stderr.getvalue())["error"])

    def test_budget_reservation_follows_title_identity_when_doi_arrives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            store = Store(database)
            try:
                title = "Social norms and household behavior"
                store.add_message(
                    ParsedMessage(
                        identity="message:title-only",
                        subject="Ancienne newsletter",
                        sender="archive@example.org",
                        publications=(
                            PublicationCandidate(
                                identity="title:social-norms-and-household-behavior",
                                doi=None,
                                title=title,
                                url="https://example.org/article",
                            ),
                        ),
                    ),
                    root / "archive.mbox#1",
                    delivery_eligible=False,
                )
                provisional = store.backfill_publications()[0]
                reservation_id, status = store.reserve_backfill_budget(
                    provisional.identity,
                    "gpt-5.6-luna",
                    "bellegarde-v2",
                    0.01,
                    1.0,
                    0.0,
                )
                self.assertIsNotNone(reservation_id)
                self.assertEqual(status, "reserved")

                store.add_message(
                    ParsedMessage(
                        identity="message:doi",
                        subject="Nouvelle occurrence",
                        sender="alerts@example.org",
                        publications=(
                            PublicationCandidate(
                                identity="doi:10.1234/norms",
                                doi="10.1234/norms",
                                title=title,
                                url="https://doi.org/10.1234/norms",
                            ),
                        ),
                    ),
                    root / "new.eml",
                    delivery_eligible=False,
                )

                self.assertEqual(store.backfill_budget_usage()[0], 0.01)
                self.assertEqual(
                    store.release_backfill_budget_reservation(reservation_id),
                    "doi:10.1234/norms",
                )
                retried_id, retried_status = store.reserve_backfill_budget(
                    "doi:10.1234/norms",
                    "gpt-5.6-luna",
                    "bellegarde-v2",
                    0.01,
                    0.005,
                    0.0,
                )
                self.assertIsNone(retried_id)
                self.assertEqual(retried_status, "budget")
            finally:
                store.close()

    def test_releasing_merged_reservation_preserves_completed_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "veille.sqlite")
            try:
                title = "Social norms and household behavior"
                store.add_message(
                    ParsedMessage(
                        identity="message:two-identities",
                        subject="Anciennes newsletters",
                        sender="archive@example.org",
                        publications=(
                            PublicationCandidate(
                                identity="title:norms",
                                doi=None,
                                title=title,
                                url="https://example.org/title",
                            ),
                            PublicationCandidate(
                                identity="doi:10.1234/norms",
                                doi="10.1234/norms",
                                title="Different provisional title",
                                url="https://doi.org/10.1234/norms",
                            ),
                        ),
                    ),
                    root / "archive.mbox#1",
                    delivery_eligible=False,
                )
                completed_id, _ = store.reserve_backfill_budget(
                    "title:norms",
                    "gpt-5.6-luna",
                    "bellegarde-v2",
                    0.01,
                    1.0,
                    0.0,
                )
                store.complete_backfill_budget_reservation(
                    completed_id, 0.003, 100, 20
                )
                reserved_id, _ = store.reserve_backfill_budget(
                    "doi:10.1234/norms",
                    "gpt-5.6-luna",
                    "bellegarde-v2",
                    0.01,
                    1.0,
                    0.0,
                )

                store.add_message(
                    ParsedMessage(
                        identity="message:merge",
                        subject="Occurrence avec DOI",
                        sender="alerts@example.org",
                        publications=(
                            PublicationCandidate(
                                identity="doi:10.1234/norms",
                                doi="10.1234/norms",
                                title=title,
                                url="https://doi.org/10.1234/norms",
                            ),
                        ),
                    ),
                    root / "new.eml",
                    delivery_eligible=False,
                )

                self.assertAlmostEqual(store.backfill_budget_usage()[0], 0.013)
                self.assertEqual(
                    store.release_backfill_budget_reservation(reserved_id),
                    "doi:10.1234/norms",
                )
                self.assertAlmostEqual(store.backfill_budget_usage()[0], 0.003)
            finally:
                store.close()

    def test_builds_a_costed_plan_without_calling_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            output = root / "rattrapage-plan.json"
            sample_output = root / "rattrapage-sample.csv"
            store = Store(database)
            try:
                message = ParsedMessage(
                    identity="message:rattrapage",
                    subject="Ancienne newsletter",
                    sender="alerts@example.org",
                    publications=(
                        PublicationCandidate(
                            identity="doi:10.1234/norms",
                            doi="10.1234/norms",
                            title="Social norms and household behavior",
                            url="https://doi.org/10.1234/norms",
                        ),
                        PublicationCandidate(
                            identity="doi:10.1234/rocks",
                            doi="10.1234/rocks",
                            title="Mineral composition of ancient rocks",
                            url="https://doi.org/10.1234/rocks",
                        ),
                    ),
                )
                store.add_message(
                    message,
                    root / "archive.mbox#1",
                    delivery_eligible=False,
                )
                store.save_metadata(
                    "doi:10.1234/norms",
                    WorkMetadata(
                        title="Social norms and household behavior",
                        abstract="A field experiment studies behavioral change.",
                        journal="Behavioral Science",
                        published_date="2025",
                        authors=("A. Martin",),
                        url="https://doi.org/10.1234/norms",
                    ),
                )
            finally:
                store.close()

            stdout = io.StringIO()
            with patch(
                "veille.ai.OpenAIAnalyzer.analyze",
                side_effect=AssertionError("Aucun appel IA autorisé"),
            ), redirect_stdout(stdout):
                exit_code = main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(output),
                        "--model",
                        "gpt-5.6-luna",
                        "--profile",
                        "standard",
                        "--sample-output",
                        str(sample_output),
                        "--sample-size",
                        "50",
                    ]
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(stdout.getvalue())
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report, plan)
            self.assertEqual(plan["service"], "backfill-plan")
            self.assertEqual(plan["status"], "ok")
            self.assertFalse(plan["ai_called"])
            self.assertTrue(plan["approval_required"])
            self.assertEqual(plan["publications_available"], 2)
            self.assertEqual(plan["publications_ai_candidates"], 1)
            self.assertEqual(plan["publications_locally_excluded"], 1)
            self.assertEqual(
                plan["profile_comparison"],
                {"strict": 1, "standard": 1, "large": 1},
            )
            self.assertEqual(plan["abstracts_available"], 1)
            self.assertEqual(plan["model"], "gpt-5.6-luna")
            self.assertEqual(plan["pricing_usd_per_million"]["input"], 0.20)
            self.assertEqual(
                plan["pricing_usd_per_million"]["input_upper_bound"], 0.25
            )
            self.assertEqual(plan["pricing_usd_per_million"]["output"], 1.20)
            self.assertGreater(plan["expected"]["input_tokens"], 0)
            self.assertGreater(plan["expected"]["output_tokens"], 0)
            self.assertGreaterEqual(
                plan["conservative"]["cost_usd"],
                plan["expected"]["cost_usd"],
            )
            self.assertGreaterEqual(
                plan["maximum"]["cost_usd"],
                plan["conservative"]["cost_usd"],
            )
            self.assertEqual(plan["enrichment_pending"], 0)
            self.assertTrue(plan["ready_for_ai"])
            self.assertTrue(plan["plan_id"])
            with sample_output.open(encoding="utf-8", newline="") as stream:
                sample = list(csv.DictReader(stream))
            self.assertEqual(len(sample), 1)
            self.assertEqual(sample[0]["title"], "Social norms and household behavior")
            self.assertEqual(sample[0]["relevance_score"], "7")
            self.assertEqual(plan["sample_output"], str(sample_output))
            self.assertEqual(plan["sample_size"], 1)
            self.assertEqual(
                plan["sample_sha256"],
                hashlib.sha256(sample_output.read_bytes()).hexdigest(),
            )

    def test_profile_comparison_ignores_cached_abstracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            output = root / "plan.json"
            store = Store(database)
            try:
                store.add_message(
                    ParsedMessage(
                        identity="message:cached-abstract",
                        subject="Ancienne newsletter",
                        sender="archive@example.org",
                        publications=(
                            PublicationCandidate(
                                identity="doi:10.1234/generic",
                                doi="10.1234/generic",
                                title="A generic empirical study",
                                url="https://doi.org/10.1234/generic",
                            ),
                        ),
                    ),
                    root / "archive.mbox#1",
                    delivery_eligible=False,
                )
                store.save_metadata(
                    "doi:10.1234/generic",
                    WorkMetadata(
                        title="A generic empirical study",
                        abstract="A behavioral psychology field experiment.",
                        journal="Behavioral Science",
                        published_date="2025",
                        authors=("A. Martin",),
                        url="https://doi.org/10.1234/generic",
                    ),
                )
            finally:
                store.close()

            with redirect_stdout(io.StringIO()):
                exit_code = main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                plan["profile_comparison"],
                {"strict": 0, "standard": 0, "large": 0},
            )
            self.assertEqual(plan["publications_ai_candidates"], 1)

    def test_can_print_a_readable_french_plan_without_historical_wording(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            output = root / "plan.json"
            self._seed_candidate(database, root)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(output),
                        "--format",
                        "human",
                    ]
                )

            report = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("RATTRAPAGE – PLAN SANS IA", report)
            self.assertIn("Candidates pour l’IA", report)
            self.assertIn("Coût prudent", report)
            self.assertIn("OpenAI – vérifiés le 2026-07-30", report)
            self.assertIn("0.20 / 1.20 $US", report)
            self.assertIn("Aucun appel IA effectué.", report)
            self.assertNotIn("historique", report.casefold())

    def test_run_refuses_a_sample_that_no_longer_matches_the_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            sample_path = root / "sample.csv"
            config = root / "veille.ini"
            write_config(config)
            self._seed_candidate(database, root)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "backfill-plan",
                            "--database",
                            str(database),
                            "--output",
                            str(plan_path),
                            "--sample-output",
                            str(sample_path),
                        ]
                    ),
                    0,
                )
            sample_path.write_text("échantillon modifié\n", encoding="utf-8")
            stderr = io.StringIO()

            with patch("sys.stderr", stderr):
                exit_code = main(
                    [
                        "backfill-run",
                        "--config",
                        str(config),
                        "--database",
                        str(database),
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(root / "digest.html"),
                        "--budget-usd",
                        "1.00",
                        "--no-send",
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("échantillon", json.loads(stderr.getvalue())["error"])

    def test_run_refuses_sample_and_digest_path_collision_before_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            shared_output = root / "rattrapage.html"
            config = root / "veille.ini"
            write_config(config)
            self._seed_candidate(database, root)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "backfill-plan",
                            "--database",
                            str(database),
                            "--output",
                            str(plan_path),
                            "--sample-output",
                            str(shared_output),
                        ]
                    ),
                    0,
                )
            calls = []
            stderr = io.StringIO()

            with patch.dict(
                "os.environ", {"OPENAI_API_KEY": "api-secret"}
            ), patch("sys.stderr", stderr):
                exit_code = main(
                    [
                        "backfill-run",
                        "--config",
                        str(config),
                        "--database",
                        str(database),
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(shared_output),
                        "--budget-usd",
                        "1.00",
                        "--no-send",
                    ],
                    ai_opener=lambda *args, **kwargs: calls.append(args),
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(calls, [])
            self.assertIn("distincts", json.loads(stderr.getvalue())["error"])

    def test_enriches_the_catalog_before_estimating_without_calling_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            output = root / "plan.json"
            config = root / "veille.ini"
            write_config(config)
            store = Store(database)
            try:
                store.add_message(
                    ParsedMessage(
                        identity="message:needs-abstract",
                        subject="Ancienne newsletter",
                        sender="alerts@example.org",
                        publications=(
                            PublicationCandidate(
                                identity="doi:10.1234/norms",
                                doi="10.1234/norms",
                                title="Social norms and household behavior",
                                url="https://doi.org/10.1234/norms",
                            ),
                            PublicationCandidate(
                                identity="doi:10.1234/minerals",
                                doi="10.1234/minerals",
                                title="Mineral composition of ancient rocks",
                                url="https://doi.org/10.1234/minerals",
                            ),
                        ),
                    ),
                    root / "archive.mbox#1",
                    delivery_eligible=False,
                )
            finally:
                store.close()

            requests = []

            def open_request(request, timeout, context=None):
                requests.append(request.full_url)
                return StubResponse(
                    {
                        "message": {
                            "title": ["Social norms and household behavior"],
                            "abstract": "A randomized field experiment tests behavioral change.",
                            "container-title": ["Behavioral Science"],
                            "published": {"date-parts": [[2025, 1, 1]]},
                            "author": [{"given": "A.", "family": "Martin"}],
                            "URL": "https://doi.org/10.1234/norms",
                        }
                    }
                )

            stdout = io.StringIO()
            with patch(
                "veille.ai.OpenAIAnalyzer.analyze",
                side_effect=AssertionError("Aucun appel IA autorisé"),
            ), redirect_stdout(stdout):
                exit_code = main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(output),
                        "--config",
                        str(config),
                        "--enrichment-limit",
                        "10",
                    ],
                    http_opener=open_request,
                )

            plan = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(plan["abstracts_available"], 1)
            self.assertEqual(plan["publications_enriched"], 1)
            self.assertEqual(plan["enrichment_pending"], 0)
            self.assertTrue(plan["ready_for_ai"])
            self.assertEqual(plan["publications_available"], 2)
            self.assertEqual(plan["publications_ai_candidates"], 1)
            self.assertEqual(plan["publications_locally_excluded"], 1)
            self.assertEqual(len(requests), 1)

    def test_enrichment_stops_after_three_consecutive_service_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            output = root / "plan.json"
            config = root / "veille.ini"
            write_config(config)
            store = Store(database)
            try:
                store.add_message(
                    ParsedMessage(
                        identity="message:outage",
                        subject="Ancienne newsletter",
                        sender="archive@example.org",
                        publications=tuple(
                            PublicationCandidate(
                                identity="doi:10.1234/outage{}".format(index),
                                doi="10.1234/outage{}".format(index),
                                title="Behavioral experiment {}".format(index),
                                url="https://doi.org/10.1234/outage{}".format(index),
                            )
                            for index in range(5)
                        ),
                    ),
                    root / "archive.mbox#1",
                    delivery_eligible=False,
                )
            finally:
                store.close()
            calls = []

            def failing_opener(*args, **kwargs):
                calls.append(args)
                raise OSError("service indisponible")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(output),
                        "--config",
                        str(config),
                        "--enrichment-limit",
                        "10",
                    ],
                    http_opener=failing_opener,
                )

            plan = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 3)
            self.assertEqual(len(plan["warnings"]), 4)
            self.assertIn("trois erreurs", plan["warnings"][-1])

    def test_budget_guard_stops_before_the_first_ai_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            config = root / "veille.ini"
            write_config(config)
            self._seed_candidate(database, root)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "backfill-plan",
                            "--database",
                            str(database),
                            "--output",
                            str(plan_path),
                        ]
                    ),
                    0,
                )

            stdout = io.StringIO()
            calls = []
            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                stdout
            ):
                exit_code = main(
                    [
                        "backfill-run",
                        "--config",
                        str(config),
                        "--database",
                        str(database),
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(root / "digest.html"),
                        "--budget-usd",
                        "0.000001",
                        "--no-send",
                    ],
                    ai_opener=lambda *args, **kwargs: calls.append(args),
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, [])
            self.assertFalse(report["ai_called"])
            self.assertTrue(report["budget_exhausted"])
            self.assertEqual(report["publications_ai_analyzed"], 0)
            self.assertEqual(report["publications_remaining"], 1)
            self.assertLessEqual(report["actual_cost_usd"], 0.000001)

    def test_rejects_a_non_finite_budget_before_any_ai_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            config = root / "veille.ini"
            write_config(config)
            self._seed_candidate(database, root)
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(plan_path),
                    ]
                )
            stderr = io.StringIO()
            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), patch(
                "sys.stderr", stderr
            ):
                exit_code = main(
                    [
                        "backfill-run",
                        "--config",
                        str(config),
                        "--database",
                        str(database),
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(root / "digest.html"),
                        "--budget-usd",
                        "nan",
                        "--no-send",
                    ],
                    ai_opener=lambda *args, **kwargs: self.fail("Appel IA interdit"),
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("budget", json.loads(stderr.getvalue())["error"].casefold())

    def test_runs_an_approved_plan_and_records_actual_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            output = root / "digest.html"
            config = root / "veille.ini"
            write_config(config)
            self._seed_candidate(database, root)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "backfill-plan",
                            "--database",
                            str(database),
                            "--output",
                            str(plan_path),
                        ]
                    ),
                    0,
                )

            result = {
                "relevant": True,
                "priority": "high",
                "summary_fr": "Une intervention robuste réduit la consommation.",
                "bellegarde_value": "Résultat directement mobilisable.",
                "applications": ["Concevoir un message normatif"],
                "themes": ["normes sociales"],
            }

            def open_request(request, timeout, context=None):
                return StubResponse(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": json.dumps(result)}
                                ],
                            }
                        ],
                        "usage": {"input_tokens": 321, "output_tokens": 87},
                    }
                )

            stdout = io.StringIO()
            FakeSMTP.instances = []
            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                stdout
            ):
                exit_code = main(
                    [
                        "backfill-run",
                        "--config",
                        str(config),
                        "--database",
                        str(database),
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(output),
                        "--budget-usd",
                        "0.01",
                    ],
                    smtp_factory=FakeSMTP,
                    ai_opener=open_request,
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.is_file())
            self.assertTrue(report["ai_called"])
            self.assertFalse(report["budget_exhausted"])
            self.assertEqual(report["publications_ai_analyzed"], 1)
            self.assertEqual(report["publications_relevant"], 1)
            self.assertEqual(report["ai_input_tokens"], 321)
            self.assertEqual(report["ai_output_tokens"], 87)
            self.assertEqual(report["actual_cost_usd"], 0.000169)
            self.assertEqual(report["billed_cost_upper_bound_usd"], 0.000185)
            self.assertLessEqual(
                report["billed_cost_upper_bound_usd"], report["budget_usd"]
            )
            self.assertTrue(report["email_sent"])
            self.assertTrue(
                FakeSMTP.instances[0].messages[0]["Subject"].startswith(
                    "Rattrapage —"
                )
            )
            store = Store(database)
            try:
                self.assertEqual(store.backfill_publications(), ())
            finally:
                store.close()

    def test_article_limit_caps_analyses_even_when_articles_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            config = root / "veille.ini"
            write_config(config)
            store = Store(database)
            try:
                store.add_message(
                    ParsedMessage(
                        identity="message:two-candidates",
                        subject="Ancienne newsletter",
                        sender="archive@example.org",
                        publications=tuple(
                            PublicationCandidate(
                                identity="doi:10.1234/norms{}".format(index),
                                doi="10.1234/norms{}".format(index),
                                title="Social norms behavioral experiment {}".format(index),
                                url="https://doi.org/10.1234/norms{}".format(index),
                            )
                            for index in (1, 2)
                        ),
                    ),
                    root / "archive.mbox#1",
                    delivery_eligible=False,
                )
                for index in (1, 2):
                    store.save_metadata(
                        "doi:10.1234/norms{}".format(index),
                        WorkMetadata(
                            title="Social norms behavioral experiment {}".format(index),
                            abstract="A randomized behavioral field experiment.",
                            journal="Behavioral Science",
                            published_date="2025",
                            authors=("A. Martin",),
                            url="https://doi.org/10.1234/norms{}".format(index),
                        ),
                    )
            finally:
                store.close()
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(plan_path),
                    ]
                )

            calls = []

            def open_request(request, timeout, context=None):
                calls.append(request)
                return StubResponse(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps(
                                            {
                                                "relevant": False,
                                                "priority": "excluded",
                                                "summary_fr": "Écartée.",
                                                "bellegarde_value": "",
                                                "applications": [],
                                                "themes": [],
                                            }
                                        ),
                                    }
                                ],
                            }
                        ],
                        "usage": {"input_tokens": 100, "output_tokens": 20},
                    }
                )

            stdout = io.StringIO()
            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                stdout
            ):
                exit_code = main(
                    [
                        "backfill-run",
                        "--config",
                        str(config),
                        "--database",
                        str(database),
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(root / "digest.html"),
                        "--budget-usd",
                        "0.10",
                        "--article-limit",
                        "1",
                        "--no-send",
                    ],
                    ai_opener=open_request,
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(report["publications_ai_analyzed"], 1)
            self.assertEqual(report["publications_remaining"], 1)

    def test_budget_is_cumulative_across_the_whole_backfill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            config = root / "veille.ini"
            write_config(config)
            self._seed_candidate(database, root)
            store = Store(database)
            try:
                previous = ParsedMessage(
                    identity="message:previous",
                    subject="Ancienne newsletter déjà traitée",
                    sender="archive@example.org",
                    publications=(
                        PublicationCandidate(
                            identity="doi:10.1234/previous",
                            doi="10.1234/previous",
                            title="Previous behavioral publication",
                            url="https://doi.org/10.1234/previous",
                        ),
                    ),
                )
                store.add_message(
                    previous,
                    root / "archive.mbox#2",
                    delivery_eligible=False,
                )
                previous_publication = next(
                    publication
                    for publication in store.backfill_publications()
                    if publication.identity == "doi:10.1234/previous"
                )
                store.save_ai_assessment(
                    previous_publication.identity,
                    AIAnalysis(
                        relevant=False,
                        priority=PublicationPriority.EXCLUDED,
                        summary_fr="Déjà analysée.",
                        bellegarde_value="",
                        applications=(),
                        themes=(),
                        input_tokens=10000,
                        output_tokens=10000,
                        model="gpt-5.6-luna",
                        prompt_version="ancienne-version",
                    ),
                )
                store.mark_delivered((previous_publication,))
            finally:
                store.close()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "backfill-plan",
                            "--database",
                            str(database),
                            "--output",
                            str(plan_path),
                        ]
                    ),
                    0,
                )

            calls = []
            stdout = io.StringIO()
            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                stdout
            ):
                exit_code = main(
                    [
                        "backfill-run",
                        "--config",
                        str(config),
                        "--database",
                        str(database),
                        "--plan",
                        str(plan_path),
                        "--output",
                        str(root / "digest.html"),
                        "--budget-usd",
                        "0.01",
                        "--no-send",
                    ],
                    ai_opener=lambda *args, **kwargs: calls.append(args),
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, [])
            self.assertTrue(report["budget_exhausted"])
            self.assertEqual(report["campaign_input_tokens"], 10000)
            self.assertEqual(report["campaign_output_tokens"], 10000)
            self.assertEqual(report["campaign_cost_upper_bound_usd"], 0.0145)
            self.assertEqual(report["budget_remaining_usd"], 0.0)

    def test_ambiguous_ai_failure_keeps_a_reservation_and_prevents_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            plan_path = root / "plan.json"
            config = root / "veille.ini"
            write_config(config)
            self._seed_candidate(database, root)
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "backfill-plan",
                        "--database",
                        str(database),
                        "--output",
                        str(plan_path),
                    ]
                )
            command = [
                "backfill-run",
                "--config",
                str(config),
                "--database",
                str(database),
                "--plan",
                str(plan_path),
                "--output",
                str(root / "digest.html"),
                "--budget-usd",
                "0.10",
                "--no-send",
            ]

            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), patch(
                "sys.stderr", io.StringIO()
            ):
                first_exit = main(
                    command,
                    ai_opener=lambda *args, **kwargs: (_ for _ in ()).throw(
                        OSError("réponse perdue")
                    ),
                )

            calls = []
            stdout = io.StringIO()
            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                stdout
            ):
                second_exit = main(
                    command,
                    ai_opener=lambda *args, **kwargs: calls.append(args),
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(first_exit, 1)
            self.assertEqual(second_exit, 0)
            self.assertEqual(calls, [])
            self.assertFalse(report["budget_exhausted"])
            self.assertGreater(report["campaign_cost_upper_bound_usd"], 0)
            self.assertIn("réservation IA #1 est inachevée", report["warnings"][0])

            release_stdout = io.StringIO()
            with redirect_stdout(release_stdout):
                release_exit = main(
                    [
                        "backfill-release-reservation",
                        "--database",
                        str(database),
                        "--reservation-id",
                        "1",
                        "--confirm-unbilled",
                    ]
                )

            release_report = json.loads(release_stdout.getvalue())
            self.assertEqual(release_exit, 0)
            self.assertTrue(release_report["reservation_released"])

            result = {
                "relevant": False,
                "priority": "excluded",
                "summary_fr": "Écartée.",
                "bellegarde_value": "",
                "applications": [],
                "themes": [],
            }

            def successful_opener(request, timeout, context=None):
                calls.append(request)
                return StubResponse(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps(result),
                                    }
                                ],
                            }
                        ],
                        "usage": {"input_tokens": 100, "output_tokens": 20},
                    }
                )

            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                io.StringIO()
            ):
                third_exit = main(command, ai_opener=successful_opener)

            self.assertEqual(third_exit, 0)
            self.assertEqual(len(calls), 1)

    def test_daily_backfill_honors_the_global_ai_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            config = root / "veille.ini"
            write_config(config)
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "[ai]\nenabled = true", "[ai]\nenabled = false"
                )
                + """
[app]
database = {database}

[backfill]
enabled = true
plan = {plan}
output = {output}
sample = {sample}
sample_size = 25
profile = standard
enrichment_limit = 0
article_limit = 15
budget_usd = 1.00
""".format(
                    database=database,
                    plan=root / "plan.json",
                    output=root / "rattrapage.html",
                    sample=root / "rattrapage-sample.csv",
                ),
                encoding="utf-8",
            )
            self._seed_candidate(database, root)
            calls = []
            stdout = io.StringIO()

            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                stdout
            ):
                exit_code = main(
                    ["backfill-daily", "--config", str(config)],
                    ai_opener=lambda *args, **kwargs: calls.append(args),
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, [])
            self.assertEqual(report["status"], "waiting_for_approval")
            self.assertFalse(report["ai_called"])

    def test_daily_backfill_refuses_sample_and_digest_path_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            config = root / "veille.ini"
            write_config(config)
            shared_output = root / "rattrapage.html"
            with config.open("a", encoding="utf-8") as stream:
                stream.write(
                    """
[app]
database = {database}

[backfill]
enabled = false
plan = {plan}
output = {output}
sample = {output}
profile = standard
""".format(
                        database=database,
                        plan=root / "plan.json",
                        output=shared_output,
                    )
                )
            self._seed_candidate(database, root)
            stderr = io.StringIO()

            with patch("sys.stderr", stderr):
                exit_code = main(
                    ["backfill-daily", "--config", str(config)]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("distincts", json.loads(stderr.getvalue())["error"])
            self.assertFalse(shared_output.exists())

    def test_daily_backfill_prepares_a_plan_but_never_calls_ai_before_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "veille.sqlite"
            config = root / "veille.ini"
            write_config(config)
            with config.open("a", encoding="utf-8") as stream:
                stream.write(
                    """
[app]
database = {database}

[backfill]
enabled = false
plan = {plan}
output = {output}
sample = {sample}
sample_size = 25
profile = standard
enrichment_limit = 100
article_limit = 15
budget_usd = 1.00
""".format(
                        database=database,
                        plan=root / "plan.json",
                        output=root / "rattrapage.html",
                        sample=root / "rattrapage-sample.csv",
                    )
                )
            self._seed_candidate(database, root)
            calls = []
            stdout = io.StringIO()

            with patch.dict("os.environ", {"OPENAI_API_KEY": "api-secret"}), redirect_stdout(
                stdout
            ):
                exit_code = main(
                    ["backfill-daily", "--config", str(config)],
                    ai_opener=lambda *args, **kwargs: calls.append(args),
                )

            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, [])
            self.assertEqual(report["service"], "backfill-daily")
            self.assertEqual(report["status"], "waiting_for_approval")
            self.assertFalse(report["ai_called"])
            self.assertTrue((root / "plan.json").is_file())
            self.assertTrue((root / "rattrapage-sample.csv").is_file())
            self.assertEqual(report["plan"]["sample_size"], 1)

    @staticmethod
    def _seed_candidate(database, root):
        store = Store(database)
        try:
            message = ParsedMessage(
                identity="message:approved-rattrapage",
                subject="Ancienne newsletter",
                sender="alerts@example.org",
                publications=(
                    PublicationCandidate(
                        identity="doi:10.1234/norms",
                        doi="10.1234/norms",
                        title="Social norms and household behavior",
                        url="https://doi.org/10.1234/norms",
                    ),
                ),
            )
            store.add_message(
                message,
                root / "archive.mbox#1",
                delivery_eligible=False,
            )
            store.save_metadata(
                "doi:10.1234/norms",
                WorkMetadata(
                    title="Social norms and household behavior",
                    abstract="A field experiment studies behavioral change.",
                    journal="Behavioral Science",
                    published_date="2025",
                    authors=("A. Martin",),
                    url="https://doi.org/10.1234/norms",
                ),
            )
        finally:
            store.close()




if __name__ == "__main__":
    unittest.main()
