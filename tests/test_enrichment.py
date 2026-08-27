import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from urllib.error import HTTPError

from tests.test_pipeline import write_email
from veille.crossref import CrossrefClient
from veille.elsevier import ElsevierClient
from veille.filtering import BehavioralScienceFilter
from veille.publisher_pages import MetadataCascade, PublisherPageClient
from veille.__main__ import main
from veille.models import AIAnalysis, PublicationPriority, WorkMetadata
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


class StaticAIAnalyzer:
    model = "test-model"
    prompt_version = "test-v1"

    def __init__(self):
        self.calls = []

    def analyze(self, publication):
        self.calls.append(publication.identity)
        return AIAnalysis(
            relevant=True,
            priority=PublicationPriority.HIGH,
            summary_fr=(
                "Une expérimentation randomisée montre que les normes sociales "
                "réduisent durablement la consommation d’énergie."
            ),
            bellegarde_value=(
                "Résultat directement mobilisable pour concevoir et évaluer "
                "des interventions comportementales."
            ),
            applications=("Conception de messages normatifs", "Évaluation terrain"),
            themes=("normes sociales", "énergie"),
            input_tokens=240,
            output_tokens=95,
            model=self.model,
            prompt_version=self.prompt_version,
        )


class FailingDelivery:
    def send(self, digest_path, publications):
        raise RuntimeError("SMTP indisponible")


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class StubHTMLResponse:
    def __init__(self, html):
        self.html = html

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit=None):
        return self.html.encode("utf-8")


class CrossrefClientTests(unittest.TestCase):
    def test_doi_fallback_preserves_source_sciencedirect_pii(self):
        class CrossrefWithoutAbstract:
            def fetch_by_doi(self, doi):
                return WorkMetadata(
                    title="Behavioral choices",
                    abstract=None,
                    journal="Journal of Behavioral Research",
                    published_date="2026-08-26",
                    authors=(),
                    url="https://doi.org/" + doi,
                )

        pii_calls = []

        class ElsevierWithAbstract:
            def fetch_by_pii(self, pii):
                pii_calls.append(pii)
                return WorkMetadata(
                    title="Behavioral choices",
                    abstract="A large experiment tests behavioral choices.",
                    journal="Journal of Behavioral Research",
                    published_date="2026-08-26",
                    authors=(),
                    url="https://doi.org/10.1016/j.jbr.2026.100001",
                )

        class PublisherMustNotBeCalled:
            def fetch_by_url(self, url):
                raise AssertionError("Le repli HTML ne doit pas être appelé.")

        provider = MetadataCascade(
            CrossrefWithoutAbstract(),
            PublisherMustNotBeCalled(),
            elsevier_client=ElsevierWithAbstract(),
        )

        metadata = provider.fetch_by_doi(
            "10.1016/j.jbr.2026.100001",
            source_url=(
                "https://www.sciencedirect.com/science/article/pii/"
                "S0167487026000413"
            ),
        )

        self.assertEqual(
            metadata.abstract,
            "A large experiment tests behavioral choices.",
        )
        self.assertEqual(pii_calls, ["S0167487026000413"])

    def test_sciencedirect_page_is_not_fetched_after_elsevier(self):
        class ElsevierWithoutAbstract:
            def fetch_by_pii(self, pii):
                return WorkMetadata(
                    title="Behavioral choices from Elsevier",
                    abstract=None,
                    journal="Journal of Behavioral Research",
                    published_date="2026-08-26",
                    authors=("Martin, A.",),
                    url="https://doi.org/10.1016/j.jbr.2026.100001",
                )

        publisher_calls = []

        class PublisherWithAbstract:
            def fetch_by_url(self, url):
                publisher_calls.append(url)
                return WorkMetadata(
                    title=None,
                    abstract="A field experiment tests behavioral choices.",
                    journal=None,
                    published_date=None,
                    authors=(),
                    url=url,
                )

        source_url = (
            "https://www.sciencedirect.com/science/article/pii/"
            "S0167487026000413"
        )
        provider = MetadataCascade(
            None,
            PublisherWithAbstract(),
            elsevier_client=ElsevierWithoutAbstract(),
        )

        metadata = provider.fetch_by_url(source_url)

        # ScienceDirect bloque toute lecture automatisée : la tenter coûtait
        # le délai d’attente complet par article, sans jamais aboutir.
        self.assertEqual(publisher_calls, [])
        self.assertIsNone(metadata.abstract)
        self.assertEqual(metadata.title, "Behavioral choices from Elsevier")
        self.assertEqual(metadata.journal, "Journal of Behavioral Research")

    def test_sciencedirect_url_uses_elsevier_pii_api_for_abstract(self):
        requests = []

        def open_request(request, timeout):
            requests.append((request, timeout))
            headers = dict(request.header_items())
            if headers.get("X-ELS-APIKey") != "elsevier-secret":
                raise HTTPError(
                    request.full_url,
                    401,
                    "Invalid API Key",
                    {},
                    None,
                )
            return StubResponse(
                {
                    "abstracts-retrieval-response": {
                        "coredata": {
                            "dc:title": "Self-efficacy boosts recycling interventions",
                            "dc:description": (
                                "A meta-analysis tests the effectiveness of "
                                "self-efficacy interventions."
                            ),
                            "prism:publicationName": "Journal of Economic Psychology",
                            "prism:coverDate": "2026-08-26",
                            "prism:doi": "10.1016/j.joep.2026.102999",
                            "dc:creator": {
                                "author": [
                                    {"ce:indexed-name": "Martin, A."},
                                    {"ce:indexed-name": "Bernard, L."},
                                ]
                            },
                        },
                    }
                }
            )

        class PublisherMustNotBeCalled:
            def fetch_by_url(self, url):
                raise AssertionError("La page HTML ne doit pas être appelée.")

        provider = MetadataCascade(
            None,
            PublisherMustNotBeCalled(),
            elsevier_client=ElsevierClient(
                api_key="elsevier-secret",
                opener=open_request,
                timeout=7,
            ),
        )

        metadata = provider.fetch_by_url(
            "https://www.sciencedirect.com/science?_ob=GatewayURL&"
            "_method=citationSearch&_piikey=S0167487026000413"
        )

        self.assertEqual(
            metadata.abstract,
            "A meta-analysis tests the effectiveness of self-efficacy interventions.",
        )
        self.assertEqual(metadata.authors, ("Martin, A.", "Bernard, L."))
        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        self.assertEqual(
            request.full_url,
            "https://api.elsevier.com/content/abstract/pii/"
            "S0167487026000413?view=META_ABS",
        )
        self.assertEqual(
            dict(request.header_items()).get("X-ELS-APIKey"),
            "elsevier-secret",
        )
        self.assertNotIn("elsevier-secret", request.full_url)
        self.assertEqual(timeout, 7)

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

    def test_falls_back_to_publisher_metadata_when_crossref_has_no_abstract(self):
        class CrossrefWithoutAbstract:
            def fetch_by_doi(self, doi):
                return WorkMetadata(
                    title="Behavioral spillovers from household energy feedback",
                    abstract=None,
                    journal="Journal of Environmental Psychology",
                    published_date="2026-08-21",
                    authors=("Amina Martin",),
                    url="https://publisher.example.org/article/42",
                )

        html = """<!doctype html><html><head>
        <meta name="citation_abstract" content="A field experiment finds durable behavioral spillovers.">
        <meta name="citation_title" content="Publisher title">
        </head><body>Paywalled body</body></html>"""
        requests = []

        def open_page(request, timeout):
            requests.append((request.full_url, timeout))
            return StubHTMLResponse(html)

        provider = MetadataCascade(
            CrossrefWithoutAbstract(),
            PublisherPageClient(opener=open_page, timeout=8),
        )

        metadata = provider.fetch_by_doi("10.1234/behavior.42")

        self.assertEqual(
            metadata.abstract,
            "A field experiment finds durable behavioral spillovers.",
        )
        self.assertEqual(
            metadata.title,
            "Behavioral spillovers from household energy feedback",
        )
        self.assertEqual(requests, [("https://publisher.example.org/article/42", 8)])

    def test_enriches_title_only_publication_from_publisher_page(self):
        html = """<html><head>
        <meta name="citation_title" content="Social norms and public participation">
        <meta name="citation_abstract" content="A randomized intervention changes civic engagement.">
        <meta name="citation_journal_title" content="Behavioral Public Policy">
        <meta name="citation_author" content="Amina Martin">
        </head></html>"""

        def open_page(request, timeout):
            return StubHTMLResponse(html)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            write_email(
                inbox / "newsletter.eml",
                "<publisher-page@example.org>",
                "Nouvelles publications",
                markup=(
                    '<a href="https://www.mdpi.com/2071-1050/18/1/42">'
                    "Social norms and public participation</a>"
                ),
            )

            report = run_pipeline(
                inbox,
                root / "veille.sqlite",
                root / "digest.html",
                metadata_provider=MetadataCascade(
                    None, PublisherPageClient(opener=open_page)
                ),
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(report.publications_enriched, 1)
            self.assertIn(
                "A randomized intervention changes civic engagement.",
                (root / "digest.html").read_text(encoding="utf-8"),
            )


class EnrichmentPipelineTests(unittest.TestCase):
    def test_pipeline_keeps_sciencedirect_pii_when_publication_has_a_doi(self):
        pii_calls = []

        class CrossrefWithoutAbstract:
            def fetch_by_doi(self, doi):
                return WorkMetadata(
                    title="Behavioral choices in household energy use",
                    abstract=None,
                    journal="Journal of Behavioral Research",
                    published_date="2026-08-26",
                    authors=(),
                    url="https://doi.org/" + doi,
                )

        class ElsevierWithAbstract:
            def fetch_by_pii(self, pii):
                pii_calls.append(pii)
                return WorkMetadata(
                    title="Behavioral choices in household energy use",
                    abstract="A large experiment tests household choices.",
                    journal="Journal of Behavioral Research",
                    published_date="2026-08-26",
                    authors=(),
                    url="https://doi.org/10.1016/j.jbr.2026.100001",
                )

        class PublisherMustNotBeCalled:
            def fetch_by_url(self, url):
                raise AssertionError("Le repli HTML ne doit pas être appelé.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            source_url = (
                "https://www.sciencedirect.com/science/article/pii/"
                "S0167487026000413"
            )
            write_email(
                inbox / "newsletter.eml",
                "<elsevier-doi@example.org>",
                "Nouvelles publications",
                markup=(
                    '<a href="{url}">Behavioral choices in household energy use</a>'
                    '<a href="{url}">DOI: 10.1016/j.jbr.2026.100001</a>'
                ).format(url=source_url),
            )

            report = run_pipeline(
                inbox,
                root / "veille.sqlite",
                root / "digest.html",
                metadata_provider=MetadataCascade(
                    CrossrefWithoutAbstract(),
                    PublisherMustNotBeCalled(),
                    elsevier_client=ElsevierWithAbstract(),
                ),
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(report.publications_enriched, 1)
            self.assertEqual(pii_calls, ["S0167487026000413"])

    def test_retries_publisher_after_crossref_not_found_without_repeating_crossref(self):
        crossref_calls = []
        publisher_calls = []

        class CrossrefNotFound:
            def fetch_by_doi(self, doi):
                crossref_calls.append(doi)
                return None

        class PublisherRetry:
            def fetch_by_url(self, url):
                publisher_calls.append(url)
                if len(publisher_calls) == 1:
                    from veille.publisher_pages import PublisherPageError

                    raise PublisherPageError("éditeur temporairement indisponible")
                return WorkMetadata(
                    title="Social norms and household choices",
                    abstract="A field experiment tests household choices.",
                    journal="Behavioral Science",
                    published_date="2026-08-21",
                    authors=(),
                    url=url,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            database = root / "veille.sqlite"
            write_email(
                inbox / "newsletter.eml",
                "<not-found-retry@example.org>",
                "Nouvelles publications",
                plain="Behavioral publication\nDOI: 10.1234/not-found.1",
            )
            provider = MetadataCascade(CrossrefNotFound(), PublisherRetry())

            first = run_pipeline(
                inbox,
                database,
                root / "first.html",
                metadata_provider=provider,
                relevance_filter=BehavioralScienceFilter(),
            )
            second = run_pipeline(
                inbox,
                database,
                root / "second.html",
                metadata_provider=provider,
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(first.publications_delivered, 0)
            self.assertEqual(second.publications_delivered, 1)
            self.assertEqual(crossref_calls, ["10.1234/not-found.1"])
            self.assertEqual(len(publisher_calls), 2)

    def test_retries_publisher_fallback_after_transient_failure(self):
        crossref_calls = []

        class CrossrefWithoutAbstract:
            def fetch_by_doi(self, doi):
                crossref_calls.append(doi)
                return WorkMetadata(
                    title="Behavioral spillovers from household feedback",
                    abstract=None,
                    journal="Behavioral Science",
                    published_date="2026-08-21",
                    authors=(),
                    url="https://publisher.example.org/article/42",
                )

        attempts = []

        class PublisherRetry:
            def fetch_by_url(self, url):
                attempts.append(url)
                if len(attempts) == 1:
                    from veille.publisher_pages import PublisherPageError

                    raise PublisherPageError("éditeur temporairement indisponible")
                return WorkMetadata(
                    title="Behavioral spillovers from household feedback",
                    abstract="A field experiment tests durable behavioral spillovers.",
                    journal="Behavioral Science",
                    published_date="2026-08-21",
                    authors=(),
                    url=url,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            database = root / "veille.sqlite"
            write_email(
                inbox / "newsletter.eml",
                "<publisher-retry@example.org>",
                "Nouvelles publications",
                plain="Behavioral publication\nDOI: 10.1234/retry.1",
            )
            provider = MetadataCascade(CrossrefWithoutAbstract(), PublisherRetry())

            first = run_pipeline(
                inbox,
                database,
                root / "first.html",
                metadata_provider=provider,
                relevance_filter=BehavioralScienceFilter(),
            )
            second = run_pipeline(
                inbox,
                database,
                root / "second.html",
                metadata_provider=provider,
                relevance_filter=BehavioralScienceFilter(),
            )

            self.assertEqual(first.publications_delivered, 0)
            self.assertEqual(first.publications_pending, 1)
            self.assertEqual(second.publications_enriched, 1)
            self.assertEqual(second.publications_delivered, 1)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(crossref_calls, ["10.1234/retry.1"])

    def test_delivery_failure_keeps_publication_pending_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            database = root / "veille.sqlite"
            write_email(
                inbox / "newsletter.eml",
                "<delivery-retry@example.org>",
                "Nouvelles publications",
                plain="Behavioral publication\nDOI: 10.1234/behavior.1",
            )

            with self.assertRaisesRegex(RuntimeError, "SMTP indisponible"):
                run_pipeline(
                    inbox,
                    database,
                    root / "digest.html",
                    metadata_provider=StaticMetadataProvider(),
                    relevance_filter=BehavioralScienceFilter(),
                    delivery_handler=FailingDelivery(),
                )

            retry = run_pipeline(
                inbox,
                database,
                root / "retry.html",
                metadata_provider=UnavailableMetadataProvider(),
                relevance_filter=BehavioralScienceFilter(),
            )
            self.assertEqual(retry.publications_delivered, 1)
            self.assertEqual(retry.publications_pending, 0)

    def test_adds_cached_structured_ai_analysis_to_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            write_email(
                inbox / "newsletter.eml",
                "<ai-analysis@example.org>",
                "Nouvelles publications",
                plain="Behavioral publication\nDOI: 10.1234/behavior.1",
            )
            analyzer = StaticAIAnalyzer()

            report = run_pipeline(
                inbox,
                root / "veille.sqlite",
                root / "digest.html",
                metadata_provider=StaticMetadataProvider(),
                relevance_filter=BehavioralScienceFilter(),
                analysis_provider=analyzer,
                ai_limit=10,
            )

            self.assertEqual(report.publications_ai_analyzed, 1)
            self.assertEqual(report.ai_input_tokens, 240)
            self.assertEqual(report.ai_output_tokens, 95)
            self.assertEqual(len(analyzer.calls), 1)
            html = (root / "digest.html").read_text(encoding="utf-8")
            self.assertIn("Une expérimentation randomisée", html)
            self.assertIn("Intérêts", html)
            self.assertIn("Conception de messages normatifs", html)

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
            self.assertIn("Pépites", html)
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
            self.assertIn("Pépites", digest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
