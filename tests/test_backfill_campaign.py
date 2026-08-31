import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_digest_delivery import FakeSMTP
from veille.ai import OpenAIAnalyzer
from veille.backfill import build_backfill_plan
from veille.campaign import classify_backfill, dispatch_backfill
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


def v5_result(scores, quality, reason, summary, value, applications, themes):
    return {
        "scope": "in_scope",
        "scores": scores,
        "method_flags": {
            "opinion_editorial_or_nonempirical": False,
            "clinical_outcomes_without_behavior": False,
            "sample_below_25_per_condition": False,
            "non_systematic_review": False,
            "single_context_descriptive": False,
            "isolated_lab_experiment": False,
            "systematic_review_without_effect_sizes": False,
        },
        "evidence_quality": quality,
        "classification_reason": reason,
        "summary_fr": summary,
        "bellegarde_value": value,
        "applications": applications,
        "themes": themes,
    }


def write_config(path, root):
    path.write_text(
        """[imap]
host = mail.example.org
username = science-digest@example.org
password = mail-password

[smtp]
host = mail.example.org
test_recipient = science-digest@example.org

[digest]
recipient = consultant@example.org

[app]
database = {database}

[ai]
enabled = true
model = gpt-5.6-luna
api_key_env = OPENAI_API_KEY

[backfill]
enabled = true
plan = {plan}
output = {digest}
classification = {classification}
profile = standard
budget_usd = 1
daily_articles = 10
""".format(
            database=root / "veille.sqlite",
            plan=root / "plan.json",
            digest=root / "digest.html",
            classification=root / "classement.csv",
        ),
        encoding="utf-8",
    )


class CampaignFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.database = self.root / "veille.sqlite"
        self.plan = self.root / "plan.json"
        self.export = self.root / "classement.csv"
        self.digest = self.root / "digest.html"
        self.config = self.root / "veille.ini"
        write_config(self.config, self.root)
        candidates = (
            PublicationCandidate(
                identity="doi:10.1234/high",
                doi="10.1234/high",
                title="Social norms improve household energy conservation",
                url="https://doi.org/10.1234/high",
            ),
            PublicationCandidate(
                identity="doi:10.1234/title-only",
                doi="10.1234/title-only",
                title=(
                    "Leadership behavior and employee well-being in "
                    "organizational psychology"
                ),
                url="https://doi.org/10.1234/title-only",
            ),
            PublicationCandidate(
                identity="doi:10.1234/excluded",
                doi="10.1234/excluded",
                title="Behavioral intentions in a small exploratory survey",
                url="https://doi.org/10.1234/excluded",
            ),
            PublicationCandidate(
                identity="doi:10.1234/watch",
                doi="10.1234/watch",
                title="Choice architecture field intervention for public policy",
                url="https://doi.org/10.1234/watch",
            ),
        )
        store = Store(self.database)
        try:
            store.add_message(
                ParsedMessage(
                    identity="message:campaign",
                    subject="Anciennes publications",
                    sender="archive@example.org",
                    publications=candidates,
                ),
                self.root / "archive.mbox#1",
                delivery_eligible=False,
            )
            store.save_metadata(
                candidates[0].identity,
                WorkMetadata(
                    title=candidates[0].title,
                    abstract="A randomized field experiment measures energy use.",
                    journal="Behavioral Science",
                    published_date="2026-01-03",
                    authors=('=HYPERLINK("https://example.org")',),
                    url=candidates[0].url,
                ),
            )
            store.save_metadata(
                candidates[1].identity,
                WorkMetadata(
                    title=candidates[1].title,
                    abstract=None,
                    journal="Organization Studies",
                    published_date="2026-01-02",
                    authors=("B. Durand",),
                    url=candidates[1].url,
                ),
            )
            store.save_metadata(
                candidates[2].identity,
                WorkMetadata(
                    title=candidates[2].title,
                    abstract="An exploratory survey reports behavioral intentions.",
                    journal="Behavioral Science",
                    published_date="2026-01-01",
                    authors=("C. Bernard",),
                    url=candidates[2].url,
                ),
            )
            store.save_metadata(
                candidates[3].identity,
                WorkMetadata(
                    title=candidates[3].title,
                    abstract="A field study tests a choice architecture intervention.",
                    journal="Behavioral Public Policy",
                    published_date="2026-01-04",
                    authors=("D. Robert",),
                    url=candidates[3].url,
                ),
            )
        finally:
            store.close()
        build_backfill_plan(
            self.database,
            self.plan,
            sample_output=self.root / "sample.csv",
        )

    def ai_opener(self):
        calls = []

        def opener(request, timeout=None, context=None):
            payload = json.loads(request.data.decode("utf-8"))
            document = json.loads(payload["input"])
            title = document["title"]
            calls.append(title)
            if "Social norms" in title:
                result = v5_result(
                    {
                        "mission_fit": 25,
                        "scientific_robustness": 25,
                        "actionability": 25,
                        "generalizability": 15,
                        "novelty": 4,
                    },
                    "strong",
                    "Preuve robuste et directement actionnable.",
                    "Une expérience randomisée teste les normes sociales.",
                    "Intervention directement mobilisable.",
                    ["Concevoir des messages normatifs"],
                    ["normes sociales", "énergie"],
                )
            elif "Leadership" in title:
                result = v5_result(
                    {
                        "mission_fit": 20,
                        "scientific_robustness": 0,
                        "actionability": 20,
                        "generalizability": 12,
                        "novelty": 6,
                    },
                    "unknown",
                    "Sujet pertinent, abstract indisponible.",
                    (
                        "Abstract indisponible : classement thématique fondé "
                        "sur le titre."
                    ),
                    "Sujet potentiellement utile aux organisations.",
                    [],
                    ["leadership", "bien-être"],
                )
            elif "exploratory" in title:
                result = v5_result(
                    {
                        "mission_fit": 5,
                        "scientific_robustness": 5,
                        "actionability": 5,
                        "generalizability": 3,
                        "novelty": 0,
                    },
                    "weak",
                    "Étude exploratoire trop faible.",
                    "Enquête exploratoire de portée limitée.",
                    "",
                    [],
                    ["intentions"],
                )
            else:
                result = v5_result(
                    {
                        "mission_fit": 20,
                        "scientific_robustness": 15,
                        "actionability": 20,
                        "generalizability": 9,
                        "novelty": 10,
                    },
                    "moderate",
                    "Étude applicable mais preuve limitée.",
                    "Une étude de terrain teste une architecture de choix.",
                    "Piste applicable aux politiques publiques.",
                    ["Tester une architecture de choix"],
                    ["architecture de choix"],
                )
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
                    "usage": {"input_tokens": 300, "output_tokens": 100},
                }
            )

        return calls, opener


class BackfillCampaignTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            "os.environ", {"OPENAI_API_KEY": "api-secret"}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_classifies_without_delivering_and_exports_the_full_control_file(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            calls, opener = fixture.ai_opener()

            report = classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=opener,
            )

            self.assertEqual(len(calls), 4)
            self.assertEqual(report["publications_classified"], 4)
            self.assertEqual(report["classification_pending"], 0)
            self.assertEqual(report["digest_ready"], 2)
            self.assertEqual(report["withheld_without_abstract"], 1)
            self.assertEqual(report["publications_excluded"], 1)
            store = Store(fixture.database)
            try:
                self.assertEqual(len(store.backfill_publications()), 4)
                assessment = store.load_ai_assessment(
                    "doi:10.1234/high",
                    "gpt-5.6-luna",
                    OpenAIAnalyzer.prompt_version,
                )
                self.assertEqual(assessment.raw_interest_score, 94)
                self.assertEqual(assessment.mission_fit_score, 25)
                self.assertEqual(assessment.scientific_robustness_score, 25)
                self.assertEqual(assessment.actionability_score, 25)
                self.assertEqual(assessment.generalizability_score, 15)
                self.assertEqual(assessment.novelty_score, 4)
                self.assertEqual(assessment.classification_rules, ())
            finally:
                store.close()
            with fixture.export.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["status"], "pending")
            self.assertEqual(rows[0]["interest_score"], "94")
            self.assertEqual(rows[0]["raw_interest_score"], "94")
            self.assertEqual(rows[0]["mission_fit_score"], "25")
            self.assertEqual(rows[0]["scientific_robustness_score"], "25")
            self.assertEqual(rows[0]["actionability_score"], "25")
            self.assertEqual(rows[0]["generalizability_score"], "15")
            self.assertEqual(rows[0]["novelty_score"], "4")
            self.assertEqual(rows[0]["classification_rules"], "")
            self.assertTrue(rows[0]["authors"].startswith("'="))
            self.assertEqual(rows[1]["status"], "pending")
            self.assertEqual(rows[2]["status"], "withheld_without_abstract")
            self.assertEqual(rows[2]["has_abstract"], "no")
            self.assertEqual(rows[3]["status"], "excluded")

    def test_migrates_v4_assessment_storage_with_auditable_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite"
            store = Store(database)
            store.close()
            connection = sqlite3.connect(str(database))
            try:
                connection.executescript(
                    """
                    PRAGMA foreign_keys = OFF;
                    DROP TABLE publication_ai_assessments;
                    CREATE TABLE publication_ai_assessments (
                        publication_identity TEXT NOT NULL REFERENCES publications(identity),
                        model TEXT NOT NULL,
                        prompt_version TEXT NOT NULL,
                        relevant INTEGER NOT NULL,
                        priority TEXT NOT NULL,
                        interest_score INTEGER NOT NULL DEFAULT 0,
                        evidence_quality TEXT NOT NULL DEFAULT 'unknown',
                        classification_reason TEXT NOT NULL DEFAULT '',
                        summary_fr TEXT NOT NULL,
                        bellegarde_value TEXT NOT NULL,
                        applications_json TEXT NOT NULL,
                        themes_json TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL,
                        output_tokens INTEGER NOT NULL,
                        checked_at TEXT NOT NULL,
                        PRIMARY KEY (publication_identity, model, prompt_version)
                    );
                    PRAGMA user_version = 9;
                    """
                )
                connection.commit()
            finally:
                connection.close()

            migrated = Store(database)
            try:
                columns = {
                    row[1]
                    for row in migrated.connection.execute(
                        "PRAGMA table_info(publication_ai_assessments)"
                    )
                }
                self.assertTrue(
                    {
                        "raw_interest_score",
                        "mission_fit_score",
                        "scientific_robustness_score",
                        "actionability_score",
                        "generalizability_score",
                        "novelty_score",
                        "classification_rules_json",
                    }.issubset(columns)
                )
                self.assertEqual(
                    migrated.connection.execute("PRAGMA user_version").fetchone()[0],
                    12,
                )
            finally:
                migrated.close()

    def test_classification_resumes_without_paying_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            calls, opener = fixture.ai_opener()

            first = classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                batch_limit=1,
                ai_opener=opener,
            )
            backup = Path(str(fixture.database) + ".pre-classification.bak")
            self.assertTrue(backup.is_file())
            backup_database = sqlite3.connect(str(backup))
            try:
                self.assertEqual(
                    backup_database.execute("PRAGMA quick_check").fetchone()[0],
                    "ok",
                )
            finally:
                backup_database.close()
            backup_timestamp = backup.stat().st_mtime_ns
            second = classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=opener,
            )

            self.assertEqual(first["publications_classified"], 1)
            self.assertEqual(first["classification_pending"], 3)
            self.assertEqual(second["publications_classified"], 3)
            self.assertEqual(second["classification_pending"], 0)
            self.assertEqual(len(calls), 4)
            self.assertEqual(backup.stat().st_mtime_ns, backup_timestamp)

    def test_api_failure_is_isolated_and_the_control_file_is_still_written(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            calls, working_opener = fixture.ai_opener()
            attempts = []

            def intermittent_opener(request, timeout=None, context=None):
                attempts.append(request)
                if len(attempts) == 1:
                    raise OSError("connexion interrompue")
                return working_opener(request, timeout=timeout, context=context)

            report = classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=intermittent_opener,
            )

            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["publications_classified"], 3)
            self.assertEqual(report["classification_pending"], 1)
            self.assertEqual(report["unresolved_reservations"], 1)
            self.assertTrue(fixture.export.is_file())
            with fixture.export.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            unresolved = [row for row in rows if row["status"] == "needs_review"]
            self.assertEqual(len(unresolved), 1)
            self.assertTrue(unresolved[0]["reservation_id"])

            with self.assertRaisesRegex(ValueError, "vérifier"):
                dispatch_backfill(
                    fixture.config,
                    fixture.database,
                    fixture.plan,
                    fixture.digest,
                    smtp_factory=FakeSMTP,
                )

    def test_three_consecutive_api_failures_stop_the_campaign_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            attempts = []

            def failing_opener(request, timeout=None, context=None):
                attempts.append(request)
                raise OSError("connexion interrompue")

            report = classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=failing_opener,
            )

            self.assertEqual(len(attempts), 3)
            self.assertEqual(report["publications_classified"], 0)
            self.assertEqual(report["classification_pending"], 4)
            self.assertEqual(report["unresolved_reservations"], 3)
            self.assertIn(
                "Classement interrompu après trois erreurs consécutives.",
                report["warnings"],
            )
            self.assertTrue(fixture.export.is_file())

    def test_restart_closes_a_reservation_when_the_assessment_was_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            store = Store(fixture.database)
            try:
                reservation_id, status = store.reserve_backfill_budget(
                    "doi:10.1234/high",
                    "gpt-5.6-luna",
                    OpenAIAnalyzer.prompt_version,
                    0.01,
                    1,
                    0,
                )
                self.assertEqual(status, "reserved")
                store.save_ai_assessment(
                    "doi:10.1234/high",
                    AIAnalysis(
                        relevant=True,
                        priority=PublicationPriority.HIGH,
                        interest_score=94,
                        evidence_quality="strong",
                        classification_reason="Preuve robuste.",
                        summary_fr="Une expérience randomisée teste les normes.",
                        bellegarde_value="Intervention mobilisable.",
                        applications=("Concevoir des messages normatifs",),
                        themes=("normes sociales",),
                        input_tokens=300,
                        output_tokens=100,
                        model="gpt-5.6-luna",
                        prompt_version=OpenAIAnalyzer.prompt_version,
                    ),
                )
            finally:
                store.close()

            calls, opener = fixture.ai_opener()
            report = classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=opener,
            )

            self.assertEqual(len(calls), 3)
            self.assertEqual(report["classification_pending"], 0)
            store = Store(fixture.database)
            try:
                reservation = store.backfill_budget_reservation(
                    "doi:10.1234/high",
                    "gpt-5.6-luna",
                    OpenAIAnalyzer.prompt_version,
                )
            finally:
                store.close()
            self.assertEqual(reservation["id"], reservation_id)
            self.assertEqual(reservation["status"], "completed")

    def test_dispatch_waits_for_complete_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            _, opener = fixture.ai_opener()
            classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                batch_limit=1,
                ai_opener=opener,
            )

            with self.assertRaisesRegex(ValueError, "classement"):
                dispatch_backfill(
                    fixture.config,
                    fixture.database,
                    fixture.plan,
                    fixture.digest,
                    article_limit=10,
                    smtp_factory=FakeSMTP,
                )

    def test_dispatch_sends_only_relevant_articles_with_an_abstract(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            _, opener = fixture.ai_opener()
            classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=opener,
            )
            FakeSMTP.instances = []

            report = dispatch_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.digest,
                article_limit=10,
                smtp_factory=FakeSMTP,
            )

            self.assertTrue(report["email_sent"])
            self.assertEqual(report["publications_delivered"], 2)
            self.assertEqual(report["digest_remaining"], 0)
            self.assertEqual(report["withheld_without_abstract"], 1)
            self.assertIn("Social norms", fixture.digest.read_text(encoding="utf-8"))
            self.assertNotIn("Leadership", fixture.digest.read_text(encoding="utf-8"))
            store = Store(fixture.database)
            try:
                remaining = {item.identity for item in store.backfill_publications()}
            finally:
                store.close()
            self.assertNotIn("doi:10.1234/high", remaining)
            self.assertIn("doi:10.1234/title-only", remaining)
            self.assertIn("doi:10.1234/excluded", remaining)

    def test_preview_does_not_mark_articles_as_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            _, opener = fixture.ai_opener()
            classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=opener,
            )

            report = dispatch_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.digest,
                article_limit=10,
                no_send=True,
            )

            self.assertFalse(report["email_sent"])
            self.assertEqual(report["publications_delivered"], 0)
            store = Store(fixture.database)
            try:
                self.assertEqual(len(store.backfill_publications()), 4)
            finally:
                store.close()

    def test_dispatch_ranks_pepites_before_watch_articles(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            _, opener = fixture.ai_opener()
            classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=opener,
            )
            FakeSMTP.instances = []

            report = dispatch_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.digest,
                article_limit=1,
                smtp_factory=FakeSMTP,
            )

            html = fixture.digest.read_text(encoding="utf-8")
            self.assertEqual(report["publications_delivered"], 1)
            self.assertEqual(report["digest_remaining"], 1)
            self.assertIn("Social norms", html)
            self.assertNotIn("Choice architecture", html)

    def test_smtp_failure_leaves_the_selected_article_in_the_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = CampaignFixture(directory)
            _, opener = fixture.ai_opener()
            classify_backfill(
                fixture.config,
                fixture.database,
                fixture.plan,
                fixture.export,
                budget_usd=1,
                ai_opener=opener,
            )

            class FailingSMTP:
                def __init__(self, *args, **kwargs):
                    raise OSError("SMTP indisponible")

            with self.assertRaises(Exception):
                dispatch_backfill(
                    fixture.config,
                    fixture.database,
                    fixture.plan,
                    fixture.digest,
                    article_limit=1,
                    smtp_factory=FailingSMTP,
                )

            store = Store(fixture.database)
            try:
                remaining = {item.identity for item in store.backfill_publications()}
            finally:
                store.close()
            self.assertIn("doi:10.1234/high", remaining)


if __name__ == "__main__":
    unittest.main()
