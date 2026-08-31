import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille.citations import RIS_FILENAME, render_ris
from veille.feedback_review import analyse_feedback, export_feedback_review, render_review
from veille.history import collect_history, export_digest_history, render_history
from veille.models import NewPublication, PublicationPriority
from veille.storage import Store


def _publication(identity="pub-1", priority=PublicationPriority.HIGH, **kwargs):
    fields = dict(
        identity=identity,
        doi="10.1016/j.test.2026.1",
        title="Un titre d’article",
        url=None,
        source_subject="sujet",
        source_sender="source@example.org",
        abstract="Un résumé.",
        journal="Revue de test",
        published_date="2026-05-01",
        authors=("Dupont A.", "Martin B."),
        priority=priority,
        themes=("normes", "énergie"),
        interest_score=7,
    )
    fields.update(kwargs)
    return NewPublication(**fields)


class RisTests(unittest.TestCase):
    def test_record_carries_the_bibliographic_fields(self):
        text = render_ris([_publication()])

        self.assertTrue(text.startswith("TY  - JOUR"))
        self.assertIn("TI  - Un titre d’article", text)
        self.assertIn("AU  - Dupont A.", text)
        self.assertIn("AU  - Martin B.", text)
        self.assertIn("JO  - Revue de test", text)
        self.assertIn("PY  - 2026", text)
        self.assertIn("DO  - 10.1016/j.test.2026.1", text)
        self.assertIn("UR  - https://doi.org/10.1016/j.test.2026.1", text)
        self.assertTrue(text.rstrip().endswith("ER  -"))

    def test_newlines_never_break_a_field(self):
        text = render_ris([_publication(abstract="Une ligne.\nUne autre.")])

        self.assertIn("AB  - Une ligne. Une autre.", text)
        for line in text.splitlines():
            self.assertTrue(not line or line[2:6] == "  - " or line.startswith("ER"))

    def test_a_publication_without_doi_falls_back_to_its_url(self):
        text = render_ris([_publication(doi=None, url="https://example.org/a")])

        self.assertIn("UR  - https://example.org/a", text)
        self.assertNotIn("DO  -", text)

    def test_an_empty_selection_produces_no_file(self):
        self.assertEqual(render_ris([]), "")

    def test_the_veille_verdict_travels_with_the_reference(self):
        self.assertIn("N1  - Veille Bellegarde : high", render_ris([_publication()]))


class _Fixture:
    def __init__(self, tmp):
        self.database = str(Path(tmp) / "veille.sqlite")

    def store(self):
        return Store(self.database)

    def seed_publication(self, identity, title="Un titre d’article"):
        store = self.store()
        try:
            store.connection.execute(
                "INSERT OR IGNORE INTO publications(identity, doi, title, url, "
                "first_seen_at, delivery_eligible) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    identity,
                    "10.1016/" + identity,
                    title,
                    None,
                    "2026-01-01T00:00:00",
                    1,
                ),
            )
            store.connection.commit()
        finally:
            store.close()


class DigestHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture = _Fixture(self._tmp.name)

    def test_a_run_records_its_articles_in_order(self):
        self.fixture.seed_publication("pub-1")
        self.fixture.seed_publication("pub-2", "Second titre")
        store = self.fixture.store()
        try:
            store.record_digest_run(
                "quotidien",
                [
                    _publication("pub-1"),
                    _publication("pub-2", PublicationPriority.WATCH, title="Second titre"),
                ],
                recipient="consultant@example.org",
                sent=True,
                total_count=9,
            )
        finally:
            store.close()

        history = collect_history(self.fixture.database)

        self.assertEqual(len(history), 1)
        run = history[0]
        self.assertEqual(run["kind"], "quotidien")
        self.assertTrue(run["sent"])
        self.assertEqual(run["retained_count"], 2)
        self.assertEqual(run["total_count"], 9)
        self.assertEqual([a["position"] for a in run["articles"]], [1, 2])
        self.assertEqual(
            [a["priority"] for a in run["articles"]], ["high", "watch"]
        )

    def test_the_recorded_verdict_survives_a_later_requalification(self):
        """L’historique doit garder le classement du jour de l’envoi."""
        self.fixture.seed_publication("pub-1")
        store = self.fixture.store()
        try:
            store.record_digest_run("quotidien", [_publication("pub-1")], sent=True)
            store.connection.execute(
                "INSERT INTO publication_feedback_messages("
                "message_identity, source_path, sender, publication_identity, "
                "priority, status, recorded_at) VALUES (?,?,?,?,?,?,?)",
                ("m1", "/tmp/m.eml", "a@b.co", "pub-1", "excluded", "accepted", "2026-06-01"),
            )
            store.connection.commit()
        finally:
            store.close()

        run = collect_history(self.fixture.database)[0]

        self.assertEqual(run["articles"][0]["priority"], "high")

    def test_an_unsent_run_is_flagged(self):
        self.fixture.seed_publication("pub-1")
        store = self.fixture.store()
        try:
            store.record_digest_run("rattrapage", [_publication("pub-1")], sent=False)
        finally:
            store.close()

        html = render_history(collect_history(self.fixture.database))

        self.assertIn("non envoyé", html)

    def test_an_empty_history_still_renders(self):
        html = render_history([])

        self.assertIn("Aucun digest enregistré", html)
        self.assertIn("<title>Historique des digests</title>", html)

    def test_the_export_writes_both_files(self):
        self.fixture.seed_publication("pub-1")
        store = self.fixture.store()
        try:
            store.record_digest_run("quotidien", [_publication("pub-1")], sent=True)
        finally:
            store.close()
        html_path = Path(self._tmp.name) / "historique.html"
        csv_path = Path(self._tmp.name) / "historique.csv"

        report = export_digest_history(
            self.fixture.database, html_path, csv_output=csv_path
        )

        self.assertEqual(report["run_count"], 1)
        self.assertEqual(report["article_count"], 1)
        self.assertIn("Un titre d’article", html_path.read_text(encoding="utf-8"))
        self.assertIn("quotidien", csv_path.read_text(encoding="utf-8"))

    def test_an_absurd_limit_is_refused(self):
        with self.assertRaises(ValueError):
            export_digest_history(self.fixture.database, "x.html", limit=0)


class FeedbackReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture = _Fixture(self._tmp.name)

    def _seed(self, identity, ai_priority, user_priority, **scores):
        self.fixture.seed_publication(identity, "Titre " + identity)
        store = self.fixture.store()
        try:
            store.connection.execute(
                "INSERT INTO publication_ai_assessments("
                "publication_identity, model, prompt_version, relevant, priority, "
                "summary_fr, bellegarde_value, applications_json, themes_json, "
                "input_tokens, output_tokens, checked_at, mission_fit_score, "
                "scientific_robustness_score, actionability_score, "
                "generalizability_score, novelty_score, classification_reason"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity, "gpt-5.6-luna", "bellegarde-v5", 1, ai_priority,
                    "résumé", "valeur", "[]", "[]", 10, 5, "2026-06-01",
                    scores.get("mission_fit_score", 5),
                    scores.get("scientific_robustness_score", 5),
                    scores.get("actionability_score", 5),
                    scores.get("generalizability_score", 5),
                    scores.get("novelty_score", 5),
                    "motif de classement",
                ),
            )
            store.connection.execute(
                "INSERT INTO publication_feedback_messages("
                "message_identity, source_path, sender, publication_identity, "
                "priority, status, recorded_at) VALUES (?,?,?,?,?,?,?)",
                ("m-" + identity, "/tmp/m.eml", "a@b.co", identity,
                 user_priority, "accepted", "2026-06-02"),
            )
            store.connection.commit()
        finally:
            store.close()

    def test_directions_are_classified(self):
        self._seed("a", "watch", "high")
        self._seed("b", "high", "excluded")
        self._seed("c", "watch", "watch")

        analysis = analyse_feedback(self.fixture.database)

        self.assertEqual(analysis["counts"]["remonté"], 1)
        self.assertEqual(analysis["counts"]["abaissé"], 1)
        self.assertEqual(analysis["counts"]["confirmé"], 1)
        self.assertAlmostEqual(analysis["agreement"], 1 / 3)

    def test_a_criterion_that_separates_the_two_directions_is_flagged(self):
        self._seed("a", "watch", "high", actionability_score=9)
        self._seed("b", "watch", "high", actionability_score=8)
        self._seed("c", "high", "excluded", actionability_score=2)

        analysis = analyse_feedback(self.fixture.database)
        actionability = next(
            c for c in analysis["criteria"] if c["field"] == "actionability_score"
        )

        self.assertGreater(actionability["gap"], 1)
        self.assertIn("discrimine", render_review(analysis))

    def test_too_few_corrections_withholds_the_criteria_reading(self):
        self._seed("a", "watch", "high")

        analysis = analyse_feedback(self.fixture.database)

        self.assertFalse(analysis["sufficient"])
        self.assertIn("Trop peu de corrections", render_review(analysis))

    def test_an_empty_database_still_renders(self):
        html = render_review(analyse_feedback(self.fixture.database))

        self.assertIn("Aucune requalification", html)

    def test_the_export_writes_both_files(self):
        self._seed("a", "watch", "high")
        html_path = Path(self._tmp.name) / "revision.html"
        csv_path = Path(self._tmp.name) / "revision.csv"

        report = export_feedback_review(
            self.fixture.database, html_path, csv_output=csv_path
        )

        self.assertEqual(report["feedback_count"], 1)
        self.assertEqual(report["corrected_count"], 1)
        self.assertFalse(report["sufficient_for_revision"])
        self.assertIn("remonté", csv_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
