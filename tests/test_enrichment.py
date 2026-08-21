import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.test_pipeline import write_email
from veille.crossref import CrossrefClient
from veille.filtering import BehavioralScienceFilter
from veille.__main__ import main
from veille.models import WorkMetadata
from veille.pipeline import run_pipeline


class StaticMetadataProvider:
    def fetch_by_doi(self, doi):
        return WorkMetadata(
            title="Social norms and household energy conservation",
            abstract=(
                "A randomized field experiment tests how descriptive and injunctive "
                "social norms influence household energy decisions."
            ),
            journal="Journal of Behavioral Public Policy",
            published_date="2026-08-20",
            authors=("Amina Martin", "Louis Bernard"),
            url="https://doi.org/10.1234/behavior.1",
        )


class UnavailableMetadataProvider:
    def fetch_by_doi(self, doi):
        raise RuntimeError("service indisponible")


class IrrelevantMetadataProvider:
    def fetch_by_doi(self, doi):
        return WorkMetadata(
            title="Catalytic conversion of industrial polymer waste",
            abstract="The catalyst improved thermal conversion yield in a laboratory reactor.",
            journal="Industrial Chemistry Letters",
            published_date="2026-08-20",
            authors=("Marie Example",),
            url="https://doi.org/10.1234/chemistry.1",
        )


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class CrossrefClientTests(unittest.TestCase):
    def test_retrieves_and_normalizes_crossref_work(self):
        requests = []

        def open_request(request, timeout):
            requests.append((request, timeout))
            return StubResponse(
                {
                    "message": {
                        "title": ["Canonical behavioral article title"],
                        "abstract": (
                            "<jats:p>Participants changed their "
                            "<jats:italic>energy choices</jats:italic>.</jats:p>"
                        ),
                        "container-title": ["Behavioral Science"],
                        "published": {"date-parts": [[2026, 8, 20]]},
                        "author": [
                            {"given": "Amina", "family": "Martin"},
                            {"name": "Bellegarde Research Group"},
                        ],
                        "URL": "https://doi.org/10.1234/a&b",
                    }
                }
            )

        client = CrossrefClient(
            contact_email="veille@example.org",
            opener=open_request,
            timeout=7,
        )

        metadata = client.fetch_by_doi("10.1234/a&b")

        self.assertEqual(metadata.title, "Canonical behavioral article title")
        self.assertEqual(
            metadata.abstract, "Participants changed their energy choices."
        )
        self.assertEqual(metadata.journal, "Behavioral Science")
        self.assertEqual(metadata.published_date, "2026-08-20")
        self.assertEqual(
            metadata.authors, ("Amina Martin", "Bellegarde Research Group")
        )
        self.assertIn("10.1234%2Fa%26b", requests[0][0].full_url)
        self.assertIn("mailto=veille%40example.org", requests[0][0].full_url)
        self.assertEqual(requests[0][1], 7)


class EnrichmentPipelineTests(unittest.TestCase):
    def test_keeps_doi_pending_without_metadata_provider_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            write_email(
                inbox / "newsletter.eml",
                "<safe-default@example.org>",
                "Nouvelles publications",
                plain="Behavioral publication\nDOI: 10.1234/pending.1",
            )

            report = run_pipeline(
                inbox,
                root / "veille.sqlite",
                root / "digest.html",
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(report.publications_new, 1)
            self.assertEqual(report.publications_delivered, 0)
            self.assertEqual(report.publications_pending, 1)

    def test_rejects_unsafe_enrichment_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            for invalid_limit in (-1, 1001):
                with self.subTest(enrichment_limit=invalid_limit):
                    with self.assertRaises(ValueError):
                        run_pipeline(
                            inbox,
                            root / "veille-{}.sqlite".format(invalid_limit),
                            root / "digest-{}.html".format(invalid_limit),
                            metadata_provider=StaticMetadataProvider(),
                            enrichment_limit=invalid_limit,
                        )

    def test_enriches_and_prioritizes_behavioral_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "newsletter.eml",
                "<enrichment@example.org>",
                "Nouvelles publications",
                plain="Nouvelle publication\nDOI: 10.1234/behavior.1",
            )

            report = run_pipeline(
                inbox,
                root / "data" / "veille.sqlite",
                digest,
                metadata_provider=StaticMetadataProvider(),
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(report.publications_enriched, 1)
            self.assertEqual(report.publications_relevant, 1)
            self.assertEqual(report.publications_excluded, 0)
            html = digest.read_text(encoding="utf-8")
            self.assertIn("Priorité élevée", html)
            self.assertIn("Social norms and household energy conservation", html)
            self.assertIn("Journal of Behavioral Public Policy", html)
            self.assertIn("A randomized field experiment", html)
            self.assertIn("Amina Martin", html)

    def test_reuses_cached_metadata_after_digest_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            database = root / "data" / "veille.sqlite"
            invalid_output = root / "existing-directory"
            invalid_output.mkdir()
            write_email(
                inbox / "newsletter.eml",
                "<cached@example.org>",
                "Nouvelles publications",
                plain="Nouvelle publication\nDOI: 10.1234/behavior.1",
            )

            with self.assertRaises(OSError):
                run_pipeline(
                    inbox,
                    database,
                    invalid_output,
                    metadata_provider=StaticMetadataProvider(),
                    relevance_filter=BehavioralScienceFilter(),
                )

            digest = root / "digest.html"
            retry = run_pipeline(
                inbox,
                database,
                digest,
                metadata_provider=UnavailableMetadataProvider(),
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(retry.messages_skipped, 1)
            self.assertEqual(retry.publications_new, 0)
            self.assertEqual(retry.publications_delivered, 1)
            self.assertEqual(retry.publications_enriched, 0)
            self.assertEqual(retry.warnings, ())
            self.assertIn(
                "Social norms and household energy conservation",
                digest.read_text(encoding="utf-8"),
            )

    def test_stops_enrichment_batch_after_repeated_service_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            references = []
            for index in range(5):
                references.append(
                    "Behavioral publication number {}\nDOI: 10.1234/failure.{}".format(
                        index, index
                    )
                )
            write_email(
                inbox / "newsletter.eml",
                "<failures@example.org>",
                "Nouvelles publications",
                plain="\n\n".join(references),
            )

            report = run_pipeline(
                inbox,
                root / "data" / "veille.sqlite",
                digest,
                metadata_provider=UnavailableMetadataProvider(),
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(report.publications_new, 5)
            self.assertEqual(report.publications_delivered, 0)
            self.assertEqual(report.publications_pending, 5)
            self.assertEqual(len(report.warnings), 4)
            self.assertIn("interrompu", report.warnings[-1])

    def test_reports_when_all_analyzed_publications_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "newsletter.eml",
                "<irrelevant@example.org>",
                "Nouvelles publications",
                plain="Nouvelle publication\nDOI: 10.1234/chemistry.1",
            )

            report = run_pipeline(
                inbox,
                root / "data" / "veille.sqlite",
                digest,
                metadata_provider=IrrelevantMetadataProvider(),
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(report.publications_relevant, 0)
            self.assertEqual(report.publications_excluded, 1)
            html = digest.read_text(encoding="utf-8")
            self.assertIn("Aucune publication pertinente retenue", html)
            self.assertNotIn("Catalytic conversion", html)


class CommandLineTests(unittest.TestCase):
    def test_disabled_crossref_keeps_doi_pending_for_later_enrichment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "digest.html"
            write_email(
                inbox / "newsletter.eml",
                "<offline@example.org>",
                "Nouvelles publications",
                plain=(
                    "Social norms shape household energy choices\n"
                    "DOI: 10.1234/offline.1"
                ),
            )
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "run",
                        "--inbox",
                        str(inbox),
                        "--database",
                        str(root / "veille.sqlite"),
                        "--output",
                        str(digest),
                        "--no-enrichment",
                    ]
                )

            self.assertEqual(exit_code, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["publications_new"], 1)
            self.assertEqual(report["publications_delivered"], 0)
            self.assertEqual(report["publications_pending"], 1)

            retry = run_pipeline(
                inbox,
                root / "veille.sqlite",
                digest,
                metadata_provider=StaticMetadataProvider(),
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(retry.publications_new, 0)
            self.assertEqual(retry.publications_delivered, 1)
            self.assertEqual(retry.publications_pending, 0)
            self.assertIn("Priorité élevée", digest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
