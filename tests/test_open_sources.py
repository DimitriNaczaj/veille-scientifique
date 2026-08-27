import io
import json
import sys
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille.crossref import CrossrefClient
from veille.europepmc import EuropePmcClient, EuropePmcError
from veille.models import WorkMetadata
from veille.openalex import OpenAlexClient, OpenAlexError
from veille.publisher_pages import MetadataCascade


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


OPENALEX_WORK = {
    "id": "https://openalex.org/W123",
    "display_name": "Citizen engagement in climate adaptation",
    "doi": "https://doi.org/10.1016/j.jenvman.2026.130563",
    "publication_date": "2026-08-15",
    "primary_location": {"source": {"display_name": "Journal of Environmental Management"}},
    "authorships": [{"author": {"display_name": "Haoran Yu"}}],
    "abstract_inverted_index": {
        "Sustainable": [0],
        "stormwater": [1],
        "management": [2],
        "matters": [3],
    },
}

EUROPEPMC_PAYLOAD = {
    "resultList": {
        "result": [
            {
                "doi": "10.1016/j.jenvman.2026.130563",
                "title": "Citizen engagement in climate adaptation",
                "abstractText": "In recent years, the impacts of climate change ...",
                "journalTitle": "Journal of Environmental Management",
                "firstPublicationDate": "2026-08-15",
                "authorList": {"author": [{"fullName": "Yu H"}]},
            }
        ]
    }
}


class OpenAlexClientTests(unittest.TestCase):
    def test_inverted_index_is_rebuilt_in_reading_order(self):
        client = OpenAlexClient(opener=lambda r, timeout=None: _Response(OPENALEX_WORK))

        metadata = client.fetch_by_doi("10.1016/j.jenvman.2026.130563")

        self.assertEqual(metadata.abstract, "Sustainable stormwater management matters")
        self.assertEqual(metadata.journal, "Journal of Environmental Management")
        self.assertEqual(metadata.authors, ("Haoran Yu",))
        self.assertEqual(metadata.published_date, "2026-08-15")

    def test_work_without_abstract_yields_none(self):
        work = dict(OPENALEX_WORK)
        work.pop("abstract_inverted_index")
        client = OpenAlexClient(opener=lambda r, timeout=None: _Response(work))

        self.assertIsNone(client.fetch_by_doi("10.1016/x").abstract)

    def test_contact_email_joins_the_polite_pool(self):
        seen = {}

        def opener(request, timeout=None):
            seen["url"] = request.full_url
            return _Response(OPENALEX_WORK)

        OpenAlexClient(contact_email="a@b.co", opener=opener).fetch_by_doi("10.1016/x")

        self.assertIn("mailto=a%40b.co", seen["url"])

    def test_unknown_doi_returns_none(self):
        def opener(request, timeout=None):
            raise HTTPError("u", 404, "Not Found", Message(), io.BytesIO(b""))

        self.assertIsNone(OpenAlexClient(opener=opener).fetch_by_doi("10.1016/x"))


class EuropePmcClientTests(unittest.TestCase):
    def test_abstract_is_returned(self):
        client = EuropePmcClient(
            opener=lambda r, timeout=None: _Response(EUROPEPMC_PAYLOAD)
        )

        metadata = client.fetch_by_doi("10.1016/j.jenvman.2026.130563")

        self.assertTrue(metadata.abstract.startswith("In recent years"))
        self.assertEqual(metadata.authors, ("Yu H",))

    def test_result_for_another_doi_is_rejected(self):
        payload = json.loads(json.dumps(EUROPEPMC_PAYLOAD))
        payload["resultList"]["result"][0]["doi"] = "10.1016/autre"
        client = EuropePmcClient(opener=lambda r, timeout=None: _Response(payload))

        self.assertIsNone(client.fetch_by_doi("10.1016/j.jenvman.2026.130563"))

    def test_empty_result_returns_none(self):
        client = EuropePmcClient(
            opener=lambda r, timeout=None: _Response({"resultList": {"result": []}})
        )

        self.assertIsNone(client.fetch_by_doi("10.1016/x"))


class _Client:
    def __init__(self, metadata=None, error=None):
        self.metadata = metadata
        self.error = error
        self.calls = 0

    def fetch_by_doi(self, doi):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.metadata

    def fetch_by_url(self, url):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.metadata


def _metadata(abstract=None, title="Titre"):
    return WorkMetadata(
        title=title,
        abstract=abstract,
        journal=None,
        published_date=None,
        authors=(),
        url=None,
    )


class CascadeOpenSourceTests(unittest.TestCase):
    def test_openalex_supplies_the_abstract_crossref_lacks(self):
        publisher = _Client()
        cascade = MetadataCascade(
            _Client(_metadata()),
            publisher,
            openalex_client=_Client(_metadata(abstract="Résumé OpenAlex")),
            europepmc_client=_Client(_metadata(abstract="Résumé Europe PMC")),
        )

        metadata = cascade.fetch_by_doi("10.1016/x")

        self.assertEqual(metadata.abstract, "Résumé OpenAlex")
        self.assertEqual(publisher.calls, 0)

    def test_europepmc_is_used_when_openalex_has_no_abstract(self):
        europepmc = _Client(_metadata(abstract="Résumé Europe PMC"))
        cascade = MetadataCascade(
            _Client(_metadata()),
            _Client(),
            openalex_client=_Client(_metadata()),
            europepmc_client=europepmc,
        )

        self.assertEqual(cascade.fetch_by_doi("10.1016/x").abstract, "Résumé Europe PMC")
        self.assertEqual(europepmc.calls, 1)

    def test_open_sources_are_skipped_when_crossref_already_has_one(self):
        openalex = _Client(_metadata(abstract="jamais lu"))
        cascade = MetadataCascade(
            _Client(_metadata(abstract="Résumé Crossref")),
            _Client(),
            openalex_client=openalex,
        )

        self.assertEqual(cascade.fetch_by_doi("10.1016/x").abstract, "Résumé Crossref")
        self.assertEqual(openalex.calls, 0)

    def test_a_failing_source_does_not_interrupt_the_chain(self):
        europepmc = _Client(_metadata(abstract="Résumé Europe PMC"))
        cascade = MetadataCascade(
            _Client(_metadata()),
            _Client(),
            openalex_client=_Client(error=OpenAlexError("panne")),
            europepmc_client=europepmc,
        )

        metadata = cascade.fetch_by_doi("10.1016/x")

        self.assertEqual(metadata.abstract, "Résumé Europe PMC")
        self.assertEqual(cascade.source_failures, {"OpenAlex": 1})

    def test_all_sources_failing_still_reaches_the_publisher_page(self):
        publisher = _Client(_metadata(abstract="Résumé éditeur"))
        cascade = MetadataCascade(
            _Client(_metadata()),
            publisher,
            openalex_client=_Client(error=OpenAlexError("panne")),
            europepmc_client=_Client(error=EuropePmcError("panne")),
        )

        cascade.fetch_by_doi("10.1016/x")

        self.assertEqual(publisher.calls, 1)
        self.assertEqual(
            cascade.source_failures, {"OpenAlex": 1, "Europe PMC": 1}
        )


if __name__ == "__main__":
    unittest.main()


class _ElsevierStub:
    """Vue META : métadonnées et DOI, mais jamais de résumé."""

    def __init__(self, doi="10.1016/j.jenvman.2026.130563"):
        self.doi = doi
        self.calls = 0

    def fetch_by_pii(self, pii):
        self.calls += 1
        return WorkMetadata(
            title="Titre Elsevier",
            abstract=None,
            journal="Journal of Environmental Management",
            published_date="2026-08-15",
            authors=("Yu H.",),
            url="https://doi.org/" + self.doi,
        )


SD_URL = "https://www.sciencedirect.com/science/article/pii/S0301479726020232"


class CascadeByUrlTests(unittest.TestCase):
    def test_elsevier_doi_opens_the_way_to_open_sources(self):
        openalex = _Client(_metadata(abstract="Résumé OpenAlex"))
        publisher = _Client()
        cascade = MetadataCascade(
            _Client(),
            publisher,
            elsevier_client=_ElsevierStub(),
            openalex_client=openalex,
        )

        metadata = cascade.fetch_by_url(SD_URL)

        self.assertEqual(metadata.abstract, "Résumé OpenAlex")
        self.assertEqual(metadata.journal, "Journal of Environmental Management")
        self.assertEqual(openalex.calls, 1)
        self.assertEqual(publisher.calls, 0)

    def test_doi_is_passed_verbatim_to_the_open_sources(self):
        seen = []

        class _Recorder(_Client):
            def fetch_by_doi(self, doi):
                seen.append(doi)
                return None

        cascade = MetadataCascade(
            _Client(),
            _Client(),
            elsevier_client=_ElsevierStub(),
            openalex_client=_Recorder(),
        )
        cascade.fetch_by_url(SD_URL)

        self.assertEqual(seen, ["10.1016/j.jenvman.2026.130563"])

    def test_elsevier_metadata_survives_when_no_abstract_is_found(self):
        """Sans résumé, titre, revue et auteurs restent acquis."""
        cascade = MetadataCascade(
            _Client(),
            _Client(_metadata(abstract="jamais lu")),
            elsevier_client=_ElsevierStub(),
            openalex_client=_Client(),
            europepmc_client=_Client(),
        )

        metadata = cascade.fetch_by_url(SD_URL)

        self.assertIsNone(metadata.abstract)
        self.assertEqual(metadata.title, "Titre Elsevier")
        self.assertEqual(metadata.authors, ("Yu H.",))

    def test_non_sciencedirect_url_does_not_call_the_open_sources(self):
        openalex = _Client(_metadata(abstract="jamais lu"))
        publisher = _Client(_metadata(abstract="Résumé éditeur"))
        cascade = MetadataCascade(
            _Client(), publisher, openalex_client=openalex
        )

        cascade.fetch_by_url("https://example.org/article/1")

        self.assertEqual(openalex.calls, 0)


class SciencedirectPageSkipTests(unittest.TestCase):
    def test_sciencedirect_page_is_never_fetched(self):
        publisher = _Client(_metadata(abstract="jamais lu"))
        cascade = MetadataCascade(
            _Client(),
            publisher,
            elsevier_client=_ElsevierStub(),
            openalex_client=_Client(),
            europepmc_client=_Client(),
        )

        metadata = cascade.fetch_by_url(SD_URL)

        self.assertEqual(publisher.calls, 0)
        self.assertEqual(metadata.journal, "Journal of Environmental Management")

    def test_other_publishers_are_still_fetched(self):
        publisher = _Client(_metadata(abstract="Résumé éditeur"))
        cascade = MetadataCascade(_Client(), publisher)

        cascade.fetch_by_url("https://click.info.apa.org/xyz")

        self.assertEqual(publisher.calls, 1)


class _TitleClient(_Client):
    def __init__(self, metadata=None, error=None):
        _Client.__init__(self, metadata, error)
        self.titles = []

    def fetch_by_title(self, title):
        self.titles.append(title)
        if self.error is not None:
            raise self.error
        return self.metadata


class TitleFallbackTests(unittest.TestCase):
    def test_title_is_used_when_the_link_leads_nowhere(self):
        openalex = _TitleClient(_metadata(abstract="Résumé par titre"))
        cascade = MetadataCascade(
            _Client(), _Client(), openalex_client=openalex
        )

        metadata = cascade.fetch_by_url(
            "https://click.info.apa.org/xyz", title="Un titre assez long pour compter"
        )

        self.assertEqual(metadata.abstract, "Résumé par titre")
        self.assertEqual(openalex.titles, ["Un titre assez long pour compter"])

    def test_title_search_is_skipped_when_an_abstract_exists(self):
        openalex = _TitleClient(_metadata(abstract="jamais lu"))
        cascade = MetadataCascade(
            _Client(),
            _Client(_metadata(abstract="Résumé éditeur")),
            openalex_client=openalex,
        )

        cascade.fetch_by_url("https://example.org/a", title="Un titre assez long")

        self.assertEqual(openalex.titles, [])

    def test_sciencedirect_without_abstract_falls_back_to_the_title(self):
        openalex = _TitleClient(_metadata(abstract="Résumé par titre"))
        cascade = MetadataCascade(
            _Client(),
            _Client(),
            elsevier_client=_ElsevierStub(),
            openalex_client=openalex,
        )

        metadata = cascade.fetch_by_url(SD_URL, title="Un titre assez long pour compter")

        self.assertEqual(metadata.abstract, "Résumé par titre")
        self.assertEqual(metadata.title, "Titre Elsevier")

    def test_a_failing_title_search_is_counted_not_raised(self):
        cascade = MetadataCascade(
            _Client(),
            _Client(),
            openalex_client=_TitleClient(error=OpenAlexError("panne")),
        )

        metadata = cascade.fetch_by_url("https://example.org/a", title="Un titre assez long")

        self.assertIsNone(metadata)
        self.assertEqual(cascade.source_failures, {"OpenAlex": 1})


class TitleMatchingTests(unittest.TestCase):
    def _client(self, returned_title, abstract="Résumé"):
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": returned_title,
                    "abstract_inverted_index": {
                        w: [i] for i, w in enumerate(abstract.split())
                    },
                }
            ]
        }
        return OpenAlexClient(opener=lambda r, timeout=None: _Response(payload))

    def test_a_close_title_is_accepted(self):
        client = self._client("Citizen engagement in climate adaptation")

        metadata = client.fetch_by_title("Citizen engagement in climate adaptation")

        self.assertIsNotNone(metadata)

    def test_a_different_article_is_rejected(self):
        client = self._client("Something else entirely about marine biology")

        self.assertIsNone(
            client.fetch_by_title("Citizen engagement in climate adaptation")
        )

    def test_a_short_title_is_not_searched(self):
        calls = []

        def opener(request, timeout=None):
            calls.append(request.full_url)
            return _Response({"results": []})

        OpenAlexClient(opener=opener).fetch_by_title("Trop court")

        self.assertEqual(calls, [])

    def test_only_words_reach_the_query(self):
        seen = {}

        def opener(request, timeout=None):
            seen["url"] = request.full_url
            return _Response({"results": []})

        OpenAlexClient(opener=opener).fetch_by_title(
            "Resilient by design? Attitudes, beliefs: children’s | part one"
        )

        needle = seen["url"].split("title.search%3A")[-1].split("&")[0]
        self.assertNotIn("%3F", needle)  # ?
        self.assertNotIn("%2C", needle)  # ,
        self.assertNotIn("%7C", needle)  # |
        self.assertNotIn("%E2%80%99", needle)  # apostrophe courbe

    def _rate_limited(self):
        def opener(request, timeout=None):
            import io
            from email.message import Message
            from urllib.error import HTTPError

            raise HTTPError(
                request.full_url, 429, "Too Many Requests", Message(), io.BytesIO(b"")
            )

        return OpenAlexClient(opener=opener)

    def test_an_exhausted_budget_returns_nothing_without_raising(self):
        client = self._rate_limited()

        self.assertIsNone(
            client.fetch_by_title("Citizen engagement in climate adaptation")
        )
        self.assertTrue(client.search_budget_exhausted)

    def test_no_further_search_is_attempted_once_the_budget_is_gone(self):
        calls = []

        def opener(request, timeout=None):
            import io
            from email.message import Message
            from urllib.error import HTTPError

            calls.append(request.full_url)
            raise HTTPError(
                request.full_url, 429, "Too Many Requests", Message(), io.BytesIO(b"")
            )

        client = OpenAlexClient(opener=opener)
        client.fetch_by_title("Citizen engagement in climate adaptation")
        client.fetch_by_title("Another title long enough to be searched for")

        self.assertEqual(len(calls), 1)

    def test_a_doi_lookup_still_works_after_the_search_budget_is_gone(self):
        """La consultation par DOI est gratuite : elle ne doit pas être bloquée."""
        client = OpenAlexClient(
            opener=lambda r, timeout=None: _Response(OPENALEX_WORK)
        )
        client.search_budget_exhausted = True

        self.assertIsNotNone(client.fetch_by_doi("10.1016/x"))


class CrossrefTitleChainTests(unittest.TestCase):
    """Crossref par titre rend un DOI, qui rouvre les catalogues gratuits."""

    def _crossref(self, abstract=None, doi="10.1016/j.jenvp.2026.103187"):
        client = _TitleClient(
            WorkMetadata(
                title="Un titre assez long pour être comparé",
                abstract=abstract,
                journal="Revue",
                published_date=None,
                authors=(),
                url="https://doi.org/" + doi,
            )
        )
        return client

    def test_crossref_is_tried_before_the_paid_openalex_search(self):
        crossref = self._crossref(abstract="Résumé Crossref")
        openalex = _TitleClient(_metadata(abstract="jamais lu"))
        cascade = MetadataCascade(crossref, _Client(), openalex_client=openalex)

        metadata = cascade.fetch_by_url(
            "https://click.info.apa.org/x", title="Un titre assez long pour être comparé"
        )

        self.assertEqual(metadata.abstract, "Résumé Crossref")
        self.assertEqual(openalex.titles, [])

    def test_the_doi_found_by_title_reaches_the_open_catalogues(self):
        openalex = _TitleClient(_metadata(abstract="Résumé OpenAlex par DOI"))
        cascade = MetadataCascade(
            self._crossref(), _Client(), openalex_client=openalex
        )

        metadata = cascade.fetch_by_url(
            "https://click.info.apa.org/x", title="Un titre assez long pour être comparé"
        )

        self.assertEqual(metadata.abstract, "Résumé OpenAlex par DOI")
        # Consulté par DOI (gratuit), jamais par titre (payant).
        self.assertEqual(openalex.calls, 1)
        self.assertEqual(openalex.titles, [])

    def test_openalex_title_search_is_the_last_resort(self):
        openalex = _TitleClient(_metadata(abstract="Résumé par titre"))
        openalex.metadata_by_doi = None
        cascade = MetadataCascade(
            _TitleClient(None), _Client(), openalex_client=openalex
        )

        metadata = cascade.fetch_by_url(
            "https://click.info.apa.org/x", title="Un titre assez long pour être comparé"
        )

        self.assertEqual(metadata.abstract, "Résumé par titre")
        self.assertEqual(len(openalex.titles), 1)
