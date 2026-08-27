import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille.models import WorkMetadata
from veille.refresh import refresh_missing_abstracts
from veille.reporting import format_refresh_report
from veille.storage import Store

CONFIG = """[app]
crossref_email = veille@example.org

[openalex]
enabled = true

[europepmc]
enabled = true
"""


def _metadata(abstract=None):
    return WorkMetadata(
        title="Titre",
        abstract=abstract,
        journal="Revue",
        published_date="2026-01-01",
        authors=("A. Autrice",),
        url="https://doi.org/10.1016/x",
    )


class _Fixture:
    def __init__(self, tmp):
        self.database = str(Path(tmp) / "veille.sqlite")
        self.config = str(Path(tmp) / "config.ini")
        Path(self.config).write_text(CONFIG, encoding="utf-8")

    def seed(self, identity, doi, abstract=None, status="not_found"):
        store = Store(self.database)
        try:
            store.connection.execute(
                "INSERT INTO publications(identity, doi, title, url, "
                "first_seen_at, delivery_eligible) VALUES (?, ?, ?, ?, ?, ?)",
                (identity, doi, "Titre", None, "2026-01-01T00:00:00", 0),
            )
            if abstract is None:
                store.save_metadata_not_found(identity, status=status)
            else:
                store.save_metadata(identity, _metadata(abstract))
        finally:
            store.close()

    def abstract(self, identity):
        store = Store(self.database)
        try:
            row = store.connection.execute(
                "SELECT abstract FROM publication_metadata "
                "WHERE publication_identity = ?",
                (identity,),
            ).fetchone()
        finally:
            store.close()
        return row[0] if row else None


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fixture = _Fixture(self._tmp.name)

    def _opener_for(self, abstract):
        """Un ouvreur qui ne répond qu’à OpenAlex, comme en production."""
        import io
        import json as jsonlib
        from email.message import Message
        from urllib.error import HTTPError

        class _Response:
            def __init__(self, payload):
                self._payload = jsonlib.dumps(payload).encode("utf-8")

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(request, timeout=None):
            url = request.full_url
            if "openalex.org" in url and abstract is not None:
                return _Response(
                    {
                        "id": "https://openalex.org/W1",
                        "display_name": "Titre",
                        "doi": "https://doi.org/10.1016/x",
                        "abstract_inverted_index": {
                            word: [i] for i, word in enumerate(abstract.split())
                        },
                    }
                )
            raise HTTPError(url, 404, "Not Found", Message(), io.BytesIO(b""))

        return opener

    def test_a_recovered_abstract_is_written_back(self):
        self.fixture.seed("pub-1", "10.1016/x")

        report = refresh_missing_abstracts(
            self.fixture.database,
            self.fixture.config,
            limit=10,
            http_opener=self._opener_for("Un résumé retrouvé"),
        )

        self.assertEqual(report["recovered"], 1)
        self.assertEqual(report["pending_before"], 1)
        self.assertEqual(report["remaining"], 0)
        self.assertEqual(self.fixture.abstract("pub-1"), "Un résumé retrouvé")

    def test_entries_that_stay_empty_are_left_untouched(self):
        self.fixture.seed("pub-1", "10.1016/x")

        report = refresh_missing_abstracts(
            self.fixture.database,
            self.fixture.config,
            limit=10,
            http_opener=self._opener_for(None),
        )

        self.assertEqual(report["recovered"], 0)
        self.assertEqual(report["remaining"], 1)
        self.assertIsNone(self.fixture.abstract("pub-1"))

    def test_entries_that_already_have_an_abstract_are_never_selected(self):
        self.fixture.seed("pub-1", "10.1016/x", abstract="Déjà présent")

        report = refresh_missing_abstracts(
            self.fixture.database,
            self.fixture.config,
            limit=10,
            http_opener=self._opener_for("jamais lu"),
        )

        self.assertEqual(report["pending_before"], 0)
        self.assertEqual(report["attempted"], 0)
        self.assertEqual(self.fixture.abstract("pub-1"), "Déjà présent")

    def test_the_limit_bounds_the_batch(self):
        for index in range(5):
            self.fixture.seed("pub-{}".format(index), "10.1016/x{}".format(index))

        report = refresh_missing_abstracts(
            self.fixture.database,
            self.fixture.config,
            limit=2,
            http_opener=self._opener_for("Un résumé retrouvé"),
        )

        self.assertEqual(report["attempted"], 2)
        self.assertEqual(report["recovered"], 2)
        self.assertEqual(report["remaining"], 3)

    def test_an_absurd_limit_is_refused(self):
        with self.assertRaises(ValueError):
            refresh_missing_abstracts(
                self.fixture.database, self.fixture.config, limit=5000
            )

    def test_the_human_report_states_the_counts(self):
        text = format_refresh_report(
            {
                "pending_before": 1848,
                "attempted": 100,
                "recovered": 62,
                "remaining": 1786,
                "warnings": [],
            }
        )

        self.assertIn("1848", text)
        self.assertIn("62", text)
        self.assertIn("aucun", text)


if __name__ == "__main__":
    unittest.main()


class QueueProgressTests(RefreshTests):
    def test_two_runs_cover_different_entries(self):
        """Sans avancement de la file, le second lot rejouerait le premier."""
        for index in range(4):
            self.fixture.seed("pub-{}".format(index), "10.1016/x{}".format(index))
        # Horodatages distincts : la seconde près, l’ensemencement les
        # rendrait égaux et masquerait l’ordre de la file.
        store = Store(self.fixture.database)
        try:
            for index in range(4):
                store.connection.execute(
                    "UPDATE publication_metadata SET checked_at = ? "
                    "WHERE publication_identity = ?",
                    ("2026-01-0{}T00:00:00+00:00".format(index + 1),
                     "pub-{}".format(index)),
                )
            store.connection.commit()
        finally:
            store.close()

        seen = []

        def opener(request, timeout=None):
            import io
            from email.message import Message
            from urllib.error import HTTPError

            url = request.full_url
            if "openalex.org" in url:
                seen.append(url)
            raise HTTPError(url, 404, "Not Found", Message(), io.BytesIO(b""))

        for _ in range(2):
            refresh_missing_abstracts(
                self.fixture.database,
                self.fixture.config,
                limit=2,
                http_opener=opener,
            )

        first, second = seen[:2], seen[2:4]
        self.assertEqual(len(set(first + second)), 4)
        self.assertEqual(set(first) & set(second), set())

    def test_a_failed_entry_keeps_its_status_and_stays_empty(self):
        self.fixture.seed("pub-1", "10.1016/x")

        refresh_missing_abstracts(
            self.fixture.database,
            self.fixture.config,
            limit=10,
            http_opener=self._opener_for(None),
        )

        store = Store(self.fixture.database)
        try:
            status, abstract = store.connection.execute(
                "SELECT status, abstract FROM publication_metadata "
                "WHERE publication_identity = ?",
                ("pub-1",),
            ).fetchone()
        finally:
            store.close()
        self.assertEqual(status, "not_found")
        self.assertIsNone(abstract)
