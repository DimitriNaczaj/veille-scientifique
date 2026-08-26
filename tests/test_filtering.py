import unittest

from veille.filtering import BehavioralScienceFilter
from veille.models import NewPublication, PublicationPriority


def publication(title, abstract=None):
    return NewPublication(
        identity="title:test",
        doi=None,
        title=title,
        url=None,
        source_subject="Newsletter scientifique",
        source_sender="alerts@example.org",
        abstract=abstract,
    )


class BehavioralScienceFilterTests(unittest.TestCase):
    def test_excludes_corrections_even_when_the_title_contains_behavioral_terms(self):
        assessed = BehavioralScienceFilter().assess(
            publication(
                "Author Correction: A meta-analysis of correction effects "
                "in science-relevant misinformation"
            )
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("correction éditoriale", assessed.relevance_reasons)

    def test_excludes_corrigendum_without_colon(self):
        assessed = BehavioralScienceFilter().assess(
            publication(
                "Corrigendum to Digital engagement and its association "
                "with psychiatric symptoms"
            )
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("correction éditoriale", assessed.relevance_reasons)

    def test_excludes_journal_issue_headings_mistaken_for_articles(self):
        assessed = BehavioralScienceFilter().assess(
            publication("Ethics & Behavior, Volume 35, Issue 6, August 2025")
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("sommaire de revue", assessed.relevance_reasons)

    def test_excludes_material_behavior_false_positive(self):
        assessed = BehavioralScienceFilter().assess(
            publication(
                "Mechanical and flexural behaviour of hybrid plastic waste "
                "polymer mortar"
            )
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("comportement non humain", assessed.relevance_reasons)

    def test_excludes_machine_behavior_false_positive(self):
        assessed = BehavioralScienceFilter().assess(
            publication(
                "State media control shapes LLM behaviour by influencing training data"
            )
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("comportement non humain", assessed.relevance_reasons)

    def test_excludes_biomedical_behavior_false_positive(self):
        assessed = BehavioralScienceFilter().assess(
            publication(
                "Liver disease alters brain function and behavior: "
                "Insights from liver-targeted siRNA therapy"
            )
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("travail biomédical", assessed.relevance_reasons)

    def test_excludes_intervention_without_human_or_behavioral_context(self):
        assessed = BehavioralScienceFilter().assess(
            publication(
                "Food and beverage plastics dominate global shorelines: "
                "A harmonized assessment to guide interventions"
            )
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("intervention non comportementale", assessed.relevance_reasons)

    def test_excludes_biological_pathway_choice_false_positive(self):
        assessed = BehavioralScienceFilter().assess(
            publication(
                "CTC1-STN1-TEN1 controls DNA break repair pathway choice "
                "via DNA end resection blockade"
            )
        )

        self.assertEqual(assessed.relevance_score, 0)
        self.assertIs(assessed.priority, PublicationPriority.EXCLUDED)
        self.assertIn("décision non humaine", assessed.relevance_reasons)

    def test_preserves_low_scoring_behavioral_studies_for_ai_review(self):
        titles = (
            "Habit-based interventions for maintaining reduction in disposable cutlery usage",
            "Episodic memory facilitates flexible decision-making via access to detailed events",
            "Human-machine collaboration and algorithmic decision-making in organizations",
            "How structural homophobia is spreading HIV-risk sexual behaviours",
        )

        for title in titles:
            with self.subTest(title=title):
                assessed = BehavioralScienceFilter().assess(publication(title))
                self.assertGreaterEqual(assessed.relevance_score, 2)
                self.assertIsNot(assessed.priority, PublicationPriority.EXCLUDED)


if __name__ == "__main__":
    unittest.main()
