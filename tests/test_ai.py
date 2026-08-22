import json
import unittest

from veille.ai import OpenAIAnalyzer
from veille.models import NewPublication


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class OpenAIAnalyzerTests(unittest.TestCase):
    def test_requests_and_validates_structured_behavioral_analysis(self):
        requests = []
        result = {
            "relevant": True,
            "priority": "high",
            "summary_fr": "Les normes sociales réduisent la consommation d’énergie.",
            "bellegarde_value": "Une intervention testée avec un protocole robuste.",
            "applications": ["Messages normatifs", "Évaluation terrain"],
            "themes": ["normes sociales", "énergie"],
        }

        def open_request(request, timeout, context=None):
            requests.append((request, timeout, context))
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
                    "usage": {"input_tokens": 321, "output_tokens": 87},
                }
            )

        analyzer = OpenAIAnalyzer(
            api_key="api-secret",
            model="gpt-test",
            opener=open_request,
            timeout=12,
        )
        publication = NewPublication(
            identity="doi:10.1234/test",
            doi="10.1234/test",
            title="Social norms and household energy conservation",
            url="https://doi.org/10.1234/test",
            source_subject="Newsletter",
            source_sender="éditeur@example.org",
            abstract="A randomized field experiment measures behavioral change.",
            journal="Behavioral Science",
        )

        analysis = analyzer.analyze(publication)

        self.assertTrue(analysis.relevant)
        self.assertEqual(analysis.priority, "high")
        self.assertEqual(analysis.input_tokens, 321)
        self.assertEqual(analysis.output_tokens, 87)
        self.assertEqual(analysis.model, "gpt-test")
        request, timeout, context = requests[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(timeout, 12)
        self.assertIsNotNone(context)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertNotIn("api-secret", request.data.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
