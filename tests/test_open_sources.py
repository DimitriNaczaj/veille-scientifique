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
