import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from veille.names import (
    format_apa_author,
    format_apa_in_text_citation,
    format_ris_author,
)


class ApaNameTests(unittest.TestCase):
    def test_formats_full_and_indexed_names(self):
        self.assertEqual(format_apa_author("Alice Martin"), "Martin, A.")
        self.assertEqual(format_apa_author("Dupont A."), "Dupont, A.")
        self.assertEqual(format_apa_author("Martin, Alice Béatrice"), "Martin, A. B.")
        self.assertEqual(
            format_apa_author("García Márquez, Amina"),
            "García Márquez, A.",
        )

    def test_keeps_particles_hyphens_and_suffixes(self):
        self.assertEqual(
            format_apa_author("Jean-Pierre de la Cruz"),
            "de la Cruz, J.-P.",
        )
        self.assertEqual(format_apa_author("John Smith Jr."), "Smith, J., Jr.")

    def test_recognizes_an_uppercase_family_name(self):
        self.assertEqual(format_apa_author("Yuan LI"), "LI, Y.")
        self.assertEqual(format_ris_author("Yuan LI"), "LI, Yuan")
        self.assertEqual(format_apa_author("LI, YUAN"), "LI, Y.")
        self.assertEqual(format_ris_author("LI, YUAN"), "LI, YUAN")

    def test_preserves_an_ambiguous_unstructured_compound_name(self):
        self.assertEqual(
            format_apa_author("Amina García Márquez"),
            "Amina García Márquez",
        )
        self.assertEqual(
            format_ris_author("Amina García Márquez"),
            "Amina García Márquez",
        )

    def test_formats_a_structured_compound_family_name(self):
        self.assertEqual(
            format_apa_author("Martínez Sánchez, Graciela"),
            "Martínez Sánchez, G.",
        )
        self.assertEqual(
            format_apa_author("Askari Lasaki, Behnam"),
            "Askari Lasaki, B.",
        )

    def test_formats_parenthetical_apa_in_text_citations(self):
        self.assertEqual(
            format_apa_in_text_citation(("Hossain, I.",), "2026-09-01"),
            "(Hossain, 2026)",
        )
        self.assertEqual(
            format_apa_in_text_citation(
                ("Chebolu-Subramanian, V.", "Quinlan, Jennifer J."),
                "2026",
            ),
            "(Chebolu-Subramanian & Quinlan, 2026)",
        )
        self.assertEqual(
            format_apa_in_text_citation(
                ("Guan, Y.", "Wang, Y.", "Li, R."),
                "2026-10-01",
            ),
            "(Guan et al., 2026)",
        )
        self.assertEqual(
            format_apa_in_text_citation(("Hossain, I.",), None),
            "(Hossain, s. d.)",
        )

    def test_keeps_collective_authors_as_literals(self):
        self.assertEqual(
            format_apa_author("Bellegarde Research Group"),
            "Bellegarde Research Group",
        )

    def test_normalizes_ris_without_discarding_given_names(self):
        self.assertEqual(format_ris_author("Alice Martin"), "Martin, Alice")
        self.assertEqual(format_ris_author("Yu H."), "Yu, H.")

    def test_bundles_the_apa_seventh_edition_csl_style(self):
        path = Path(__file__).resolve().parents[1] / "styles" / "apa.csl"
        root = ElementTree.parse(path).getroot()
        namespace = {"csl": "http://purl.org/net/xbiblio/csl"}

        self.assertEqual(root.attrib["version"], "1.0")
        self.assertEqual(
            root.findtext("csl:info/csl:id", namespaces=namespace),
            "http://www.zotero.org/styles/apa",
        )
        citation = root.find("csl:citation", namespaces=namespace)
        self.assertEqual(citation.attrib["et-al-min"], "3")
        self.assertEqual(citation.attrib["et-al-use-first"], "1")
        layout = citation.find("csl:layout", namespaces=namespace)
        self.assertEqual(layout.attrib["prefix"], "(")
        self.assertEqual(layout.attrib["suffix"], ")")


if __name__ == "__main__":
    unittest.main()
