import io
import json
import sys
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veille.elsevier import ElsevierClient, ElsevierError


META_PAYLOAD = {
    "abstracts-retrieval-response": {
        "coredata": {
            "dc:title": "Citizen engagement in climate adaptation",
            "prism:publicationName": "Journal of Environmental Management",
            "prism:coverDate": "2026-08-15",
            "prism:doi": "10.1016/j.jenvman.2026.130563",
            "dc:creator": {"author": [{"ce:indexed-name": "Yu H."}]},
        }
    }
}

META_ABS_PAYLOAD = json.loads(json.dumps(META_PAYLOAD))
META_ABS_PAYLOAD["abstracts-retrieval-response"]["coredata"]["dc:description"] = (
    "Un résumé fourni par Elsevier."
)


def _http_error(code, status_code):
    body = json.dumps(
        {"service-error": {"status": {"statusCode": status_code}}}
    ).encode("utf-8")
    return HTTPError(
        "https://api.elsevier.com/", code, "Unauthorized", Message(), io.BytesIO(body)
    )


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _Opener:
    """Refuse ``META_ABS`` comme le fait une clé sans abonnement."""

    def __init__(self, allowed_views=("META",)):
        self.allowed_views = allowed_views
        self.views = []

    def __call__(self, request, timeout=None):
        view = request.full_url.rsplit("view=", 1)[-1]
        self.views.append(view)
        if view not in self.allowed_views:
            raise _http_error(401, "AUTHORIZATION_ERROR")
        payload = META_ABS_PAYLOAD if view == "META_ABS" else META_PAYLOAD
        return _Response(payload)


class ElsevierViewFallbackTests(unittest.TestCase):
    def test_entitled_key_keeps_meta_abs_and_returns_abstract(self):
        opener = _Opener(allowed_views=("META_ABS", "META"))
        client = ElsevierClient("clé", opener=opener)

        metadata = client.fetch_by_pii("S0301479726020232")

        self.assertEqual(opener.views, ["META_ABS"])
        self.assertEqual(metadata.abstract, "Un résumé fourni par Elsevier.")
        self.assertIsNone(client.entitlement_notice)

    def test_view_refusal_degrades_to_meta_instead_of_failing(self):
        opener = _Opener()
        client = ElsevierClient("clé", opener=opener)

        metadata = client.fetch_by_pii("S0301479726020232")

        self.assertEqual(opener.views, ["META_ABS", "META"])
        self.assertIsNone(metadata.abstract)
        self.assertEqual(metadata.authors, ("Yu H.",))
        self.assertEqual(
            metadata.title, "Citizen engagement in climate adaptation"
        )
        self.assertIsNotNone(client.entitlement_notice)

    def test_degraded_view_is_latched_for_later_calls(self):
        opener = _Opener()
        client = ElsevierClient("clé", opener=opener)

        client.fetch_by_pii("S0301479726020232")
        client.fetch_by_pii("S0301479726020233")

        self.assertEqual(opener.views, ["META_ABS", "META", "META"])

    def test_rejected_key_still_raises(self):
        def opener(request, timeout=None):
            raise _http_error(401, "AUTHENTICATION_ERROR")

        client = ElsevierClient("clé", opener=opener)

        with self.assertRaises(ElsevierError) as caught:
            client.fetch_by_pii("S0301479726020232")
        self.assertIn("clé API refusée", str(caught.exception))

    def test_missing_article_returns_none(self):
        def opener(request, timeout=None):
            raise _http_error(404, "RESOURCE_NOT_FOUND")

        client = ElsevierClient("clé", opener=opener)

        self.assertIsNone(client.fetch_by_pii("S0301479726020232"))


if __name__ == "__main__":
    unittest.main()
