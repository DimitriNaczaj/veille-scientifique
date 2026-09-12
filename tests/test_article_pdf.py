import io
import json
import tempfile
import unittest
from pathlib import Path

from veille.article_pdf import OpenAccessPdfFetcher, PdfUnavailableError


class FakeResponse(io.BytesIO):
    def __init__(self, content, url, content_type="application/json"):
        super().__init__(content)
        self.url = url
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def geturl(self):
        return self.url


class SequencedOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=0, **_kwargs):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


class ArticlePdfTests(unittest.TestCase):
    def test_downloads_and_verifies_an_open_access_pdf(self):
        metadata = {
            "best_oa_location": {
                "url_for_pdf": "https://repository.example/article.pdf",
                "license": "cc-by",
            },
            "oa_locations": [],
        }
        opener = SequencedOpener(
            [
                FakeResponse(
                    json.dumps(metadata).encode(),
                    "https://api.unpaywall.org/v2/10.1234%2Fpaper",
                ),
                FakeResponse(
                    b"%PDF-1.7\nverified article",
                    "https://repository.example/article.pdf",
                    "application/pdf",
                ),
            ]
        )
        fetcher = OpenAccessPdfFetcher("science@example.org", opener=opener)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "article.pdf"
            result = fetcher.fetch("10.1234/paper", destination)

            self.assertEqual(destination.read_bytes(), b"%PDF-1.7\nverified article")
            self.assertEqual(result.source_url, "https://repository.example/article.pdf")
            self.assertEqual(result.license, "cc-by")
            self.assertGreater(result.size_bytes, 0)

    def test_rejects_an_html_page_returned_as_a_pdf(self):
        metadata = {
            "best_oa_location": {
                "url_for_pdf": "https://repository.example/article.pdf",
                "license": None,
            },
            "oa_locations": [],
        }
        opener = SequencedOpener(
            [
                FakeResponse(json.dumps(metadata).encode(), "https://api.unpaywall.org"),
                FakeResponse(
                    b"<html>not a pdf</html>",
                    "https://repository.example/article.pdf",
                    "text/html",
                ),
            ]
        )
        fetcher = OpenAccessPdfFetcher("science@example.org", opener=opener)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "article.pdf"
            with self.assertRaisesRegex(PdfUnavailableError, "PDF valide"):
                fetcher.fetch("10.1234/paper", destination)
            self.assertFalse(destination.exists())

    def test_rejects_private_or_unencrypted_pdf_locations(self):
        for url in (
            "http://repository.example/article.pdf",
            "https://127.0.0.1/article.pdf",
        ):
            metadata = {
                "best_oa_location": {"url_for_pdf": url, "license": None},
                "oa_locations": [],
            }
            opener = SequencedOpener(
                [FakeResponse(json.dumps(metadata).encode(), "https://api.unpaywall.org")]
            )
            fetcher = OpenAccessPdfFetcher("science@example.org", opener=opener)

            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(PdfUnavailableError, "accessible"):
                    fetcher.fetch("10.1234/paper", Path(directory) / "article.pdf")


if __name__ == "__main__":
    unittest.main()
