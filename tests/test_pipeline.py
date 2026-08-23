import base64
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote, urlencode

from veille.mail_parser import normalize_doi, parse_message
from veille.digest import render_digest
from veille.models import NewPublication, PublicationPriority
from veille.pipeline import run_pipeline
from veille.storage import Store


def write_email(path, message_id, subject, plain=None, markup=None):
    message = EmailMessage()
    message["Message-ID"] = message_id
    message["From"] = "éditeur@example.org"
    message["To"] = "veille@bellegarde.example"
    message["Subject"] = subject
    message.set_content(plain or "Version HTML disponible.")
    if markup:
        message.add_alternative(markup, subtype="html")
    Path(path).write_bytes(message.as_bytes())


class NormalizeDoiTests(unittest.TestCase):
    def test_normalizes_url_case_and_trailing_punctuation(self):
        self.assertEqual(
            normalize_doi("https://doi.org/10.1234/ABC.Def."),
            "10.1234/abc.def",
        )

    def test_preserves_balanced_delimiters_in_historical_doi(self):
        self.assertEqual(
            normalize_doi(
                "10.1002/(SICI)1099-0844(199912)17:4<290::AID-CBF849>3.0.CO;2-P"
            ),
            "10.1002/(sici)1099-0844(199912)17:4<290::aid-cbf849>3.0.co;2-p",
        )

    def test_preserves_extended_suffix_characters(self):
        self.assertEqual(
            normalize_doi("10.1234/a&b=c@d%25{e}[f]?"),
            "10.1234/a&b=c@d%{e}[f]?",
        )


class PipelineTests(unittest.TestCase):
    def test_extracts_canonical_nature_url_from_legacy_aws_tracking_link(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-nature.eml"
            payload = urlencode(
                {
                    "scenario": "alert",
                    "target": "https://www.nature.com/articles/behavior-2025",
                }
            ).encode("utf-8")
            encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii")
            intermediary = "https://smc-link.example/?{}".format(
                urlencode({"_L54AD1F204_": encoded_payload})
            )
            tracking_url = (
                "https://token.r.eu-west-1.awstrack.me/L0/{}/1/tracking"
            ).format(quote(intermediary, safe=""))
            write_email(
                path,
                "<legacy-nature@example.org>",
                "Legacy Nature alert",
                markup=(
                    '<a href="{}">How stress changes habitual decision making</a>'
                ).format(tracking_url),
            )

            parsed = parse_message(path)

            self.assertEqual(len(parsed.publications), 1)
            self.assertEqual(
                parsed.publications[0].url,
                "https://www.nature.com/articles/behavior-2025",
            )

    def test_extracts_wiley_article_titles_from_tracking_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wiley.eml"
            write_email(
                path,
                "<wiley@example.org>",
                "Wiley article alert",
                markup=(
                    '<a href="https://el.wiley.com/ls/click?upn=opaque-token">'
                    "How uncertainty messages influence consumer decisions"
                    "</a>"
                    '<a href="https://el.wiley.com/ls/click?upn=navigation-token">'
                    "View latest articles"
                    "</a>"
                ),
            )

            parsed = parse_message(path)

            self.assertEqual(len(parsed.publications), 1)
            self.assertEqual(
                parsed.publications[0].title,
                "How uncertainty messages influence consumer decisions",
            )

    def test_extracts_taylor_and_francis_titles_from_tracking_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "taylor-francis.eml"
            write_email(
                path,
                "<taylor-francis@example.org>",
                "Taylor & Francis article alert",
                markup=(
                    '<a href="https://url6649.tandfonline.com/ls/click?upn=opaque-token">'
                    "Social norms and preventive behavior across communities"
                    "</a>"
                ),
            )

            parsed = parse_message(path)

            self.assertEqual(len(parsed.publications), 1)
            self.assertEqual(
                parsed.publications[0].title,
                "Social norms and preventive behavior across communities",
            )

    def test_ignores_apa_journal_heading_that_matches_subject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "apa.eml",
                "<apa-heading@example.org>",
                "APA PsycAlert - Journal of Behavioral Science",
                markup=(
                    '<a href="https://click.info.apa.org/journal">'
                    "Journal of Behavioral Science"
                    "</a>"
                    '<a href="https://click.info.apa.org/article">'
                    "Social norms shape household conservation decisions"
                    "</a>"
                ),
            )

            report = run_pipeline(inbox, root / "data" / "veille.sqlite", digest)

            self.assertEqual(report.publications_detected, 1)
            html = digest.read_text(encoding="utf-8")
            self.assertIn("Social norms shape household conservation decisions", html)
            self.assertNotIn(">Journal of Behavioral Science</a>", html)

    def test_ignores_mdpi_promotional_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "mdpi-promotions.eml",
                "<mdpi-promotions@example.org>",
                "Sommaire et annonces",
                markup=(
                    '<a href="https://www.mdpi.com/journal/sustainability/special_issues/example">'
                    "Behavioral pathways for sustainable cities"
                    "</a>"
                    '<a href="https://www.mdpi.com/journal/sustainability/events/12345">'
                    "International conference on sustainable behavior"
                    "</a>"
                ),
            )

            report = run_pipeline(inbox, root / "data" / "veille.sqlite", digest)

            self.assertEqual(report.publications_detected, 0)
            self.assertEqual(report.publications_new, 0)

    def test_ignores_elsevier_issue_navigation_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "elsevier-navigation.eml",
                "<elsevier-navigation@example.org>",
                "Alerte de revue",
                markup=(
                    '<a href="https://click.notification.elsevier.com/CL0/'
                    'https%3A%2F%2Fwww.sciencedirect.com%2Fjournal%2Fexample%2Fvol%2F9%2Fissue%2F8/1/1">'
                    "Volume 9, Issue 8, 21 August 2026"
                    "</a>"
                    '<a href="https://click.notification.elsevier.com/CL0/'
                    'https%3A%2F%2Fwww.sciencedirect.com%2Fscience%2Fjournal%2Faip%2F12345678/1/1">'
                    "New Articles in Press, 21 August"
                    "</a>"
                    '<a href="https://click.notification.elsevier.com/CL0/'
                    'https%3A%2F%2Fwww.sciencedirect.com%2Fscience%3F_piikey%3DS123456789/1/1">'
                    "How social norms shape sustainable household choices"
                    "</a>"
                ),
            )

            report = run_pipeline(inbox, root / "data" / "veille.sqlite", digest)

            self.assertEqual(report.publications_detected, 1)
            self.assertEqual(report.publications_new, 1)
            self.assertIn(
                "How social norms shape sustainable household choices",
                digest.read_text(encoding="utf-8"),
            )

    def test_processes_article_title_link_when_newsletter_has_no_doi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "apa.eml",
                "<apa-link@example.org>",
                "Alerte bibliographique",
                markup=(
                    '<a href="https://click.info.apa.org/article/example">'
                    "How policy messages shape household decisions across multiple settings"
                    "</a>"
                ),
            )

            report = run_pipeline(inbox, root / "data" / "veille.sqlite", digest)

            self.assertEqual(report.publications_new, 1)
            html = digest.read_text(encoding="utf-8")
            self.assertIn(
                "How policy messages shape household decisions across multiple settings", html
            )
            self.assertIn("https://click.info.apa.org/article/example", html)

    def test_merges_title_and_doi_links_for_same_article(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            article_url = "https://www.mdpi.com/2071-1050/18/15/7547"
            write_email(
                inbox / "mdpi.eml",
                "<mdpi-links@example.org>",
                "Sommaire",
                markup=(
                    '<a href="{url}">A behavioral study of household energy decisions</a>'
                    '<a href="{url}">DOI: 10.3390/su18157547</a>'
                ).format(url=article_url),
            )

            report = run_pipeline(
                inbox,
                root / "data" / "veille.sqlite",
                digest,
                deliver_unenriched=True,
            )

            self.assertEqual(report.publications_new, 1)
            html = digest.read_text(encoding="utf-8")
            self.assertIn("A behavioral study of household energy decisions", html)
            self.assertIn("10.3390/su18157547", html)

    def test_pairs_ordered_titles_and_dois_when_counts_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "nature.eml",
                "<nature-order@example.org>",
                "Sommaire",
                markup=(
                    '<a href="https://links.springernature.com/f/a/first">'
                    "How shared norms influence sustainable household choices"
                    "</a><p>First Author</p><p>| doi:10.1038/example-001</p>"
                    '<a href="https://links.springernature.com/f/a/second">'
                    "Testing behavioral interventions in public organizations"
                    "</a><p>Second Author</p><p>| doi:10.1038/example-002</p>"
                ),
            )

            report = run_pipeline(
                inbox,
                root / "data" / "veille.sqlite",
                digest,
                deliver_unenriched=True,
            )

            self.assertEqual(report.publications_new, 2)
            html = digest.read_text(encoding="utf-8")
            self.assertIn("How shared norms influence sustainable household choices", html)
            self.assertIn("10.1038/example-001", html)
            self.assertIn(
                "Testing behavioral interventions in public organizations", html
            )
            self.assertIn("10.1038/example-002", html)

    def test_digest_url_encodes_reserved_doi_characters(self):
        publication = NewPublication(
            identity="doi:10.1234/a&b=c@d%{e}[f]?",
            doi="10.1234/a&b=c@d%{e}[f]?",
            title="DOI étendu",
            url=None,
            source_subject="Newsletter",
            source_sender="éditeur@example.org",
        )

        digest = render_digest((publication,))

        self.assertIn(
            'href="https://doi.org/10.1234/a%26b%3Dc%40d%25%7Be%7D%5Bf%5D%3F"',
            digest,
        )

    def test_digest_uses_adaptive_email_safe_bellegarde_design(self):
        publication = NewPublication(
            identity="doi:10.1234/design",
            doi="10.1234/design",
            title="How social norms shape sustainable choices",
            url="https://doi.org/10.1234/design",
            source_subject="Alerte scientifique",
            source_sender="éditeur@example.org",
            abstract="An abstract about social norms.",
            journal="Journal of Behaviour",
            published_date="2026-08-22",
            authors=("Alice Martin", "Bob Dupont", "Claire Durand", "David Leroy"),
            relevance_reasons=("normes sociales", "intervention"),
            priority=PublicationPriority.HIGH,
            summary_fr="Les normes sociales influencent les choix durables.",
            bellegarde_value="Un résultat directement mobilisable en mission.",
            applications=("Concevoir un message", "Tester sur le terrain"),
            themes=("Normes sociales", "Transition écologique"),
        )

        digest = render_digest((publication,), total_count=2, excluded_count=1)

        self.assertIn('<meta name="color-scheme" content="light dark">', digest)
        self.assertIn("@media (prefers-color-scheme:dark)", digest)
        self.assertIn('role="presentation"', digest)
        self.assertIn("background:#E9E7E5", digest)
        self.assertIn("background:#1A181C !important", digest)
        self.assertIn(">Veille scientifique</h1>", digest)
        self.assertIn('class="digest-meta ink-3"', digest)
        self.assertIn(
            '&nbsp;&nbsp;–&nbsp;&nbsp;<span class="ink-2" '
            'style="color:#57555A;">1 article retenu sur 2 publiés.</span>',
            digest,
        )
        self.assertIn(
            'class="header-pad pad" style="padding:6px 40px 0 34px;',
            digest,
        )
        self.assertIn(
            ".header-pad{padding-left:14px !important;}",
            digest,
        )
        self.assertIn("font-size:34px", digest)
        self.assertIn("font-size:24px", digest)
        self.assertIn(
            ".shell,.card{width:100% !important;max-width:100% !important;}",
            digest,
        )
        self.assertIn(
            ".article-title{font-size:26px !important;line-height:34px !important;}",
            digest,
        )
        self.assertIn(
            ".article-summary,.article-interest,.application-list,.article-detail{font-size:18px !important;line-height:29px !important;}",
            digest,
        )
        self.assertIn(
            ".digest-meta{font-size:17px !important;line-height:26px !important;}",
            digest,
        )
        self.assertIn(
            ".article-kicker,.article-authors,.doi,.article-metadata{font-size:16px !important;line-height:24px !important;}",
            digest,
        )
        self.assertIn("width:11px", digest)
        self.assertIn("Pépites", digest)
        self.assertIn("Intérêts", digest)
        self.assertIn("Ouvrir l’étude", digest)
        self.assertNotIn("Ouvrir l’étude&nbsp;&nbsp;→", digest)
        self.assertNotIn("En bref :", digest)
        self.assertNotIn(">bellegarde</td>", digest)
        self.assertNotIn("Veille scientifique Bellegarde", digest)
        self.assertIn("#6FCF97", digest)
        self.assertIn("#E2F5EA", digest)
        self.assertIn("#2C4A39", digest)
        self.assertNotIn("#5DADE2", digest)
        self.assertIn('<ul class="application-list ink-2"', digest)
        self.assertIn("<li>Concevoir un message</li>", digest)
        self.assertIn("<li>Tester sur le terrain</li>", digest)
        self.assertIn(
            'class="chip" style="display:inline-block;line-height:18px;'
            'margin:0 0 8px 0;',
            digest,
        )
        self.assertIn('src="cid:bellegarde-logo-black"', digest)
        self.assertIn('src="cid:bellegarde-logo-white"', digest)
        self.assertIn('alt="Bellegarde – we change behaviour"', digest)
        self.assertNotIn("12 rue de la Science", digest)
        self.assertNotIn("lorsqu’elles sont disponibles", digest)
        self.assertNotIn("(s)", digest)
        self.assertIn("Alice Martin, Bob Dupont, Claire Durand et al.", digest)
        self.assertNotIn("David Leroy", digest)
        authors_position = digest.index(
            "Alice Martin, Bob Dupont, Claire Durand et al."
        )
        doi_position = digest.index('class="doi ink-3"')
        summary_position = digest.index(
            "Les normes sociales influencent les choix durables.", doi_position
        )
        self.assertLess(authors_position, doi_position)
        self.assertLess(doi_position, summary_position)
        self.assertIn(
            'href="https://doi.org/10.1234/design"',
            digest[doi_position:summary_position],
        )
        self.assertIn("An abstract about social norms.", digest)
        self.assertRegex(
            digest,
            r"Généré le \d{1,2} [a-zéû]+ \d{4} à \d{2}:\d{2}\.",
        )
        self.assertNotIn("Digest généré automatiquement", digest)
        self.assertNotIn("Métadonnées enrichies via Crossref", digest)
        self.assertNotIn("Bellegarde – veille interne", digest)
        self.assertNotIn("Bellegarde - veille interne", digest)
        self.assertNotIn("—", digest)

        class FixedUtcDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                instant = datetime(2026, 8, 23, 12, 5, tzinfo=timezone.utc)
                return instant.astimezone(tz) if tz else instant

        with patch("veille.digest.datetime", FixedUtcDateTime):
            paris_digest = render_digest((publication,))
        self.assertIn("Généré le 23 août 2026 à 14:05.", paris_digest)

        watch_summary = "Résumé IA à conserver dans Éventuellement."
        watch_abstract = "Abstract brut à masquer dans Éventuellement."
        watch_digest = render_digest(
            (
                NewPublication(
                    identity="doi:10.1234/watch",
                    doi="10.1234/watch",
                    title="A signal worth watching",
                    url=None,
                    source_subject="Alerte scientifique",
                    source_sender="éditeur@example.org",
                    abstract=watch_abstract,
                    priority=PublicationPriority.WATCH,
                    summary_fr=watch_summary,
                ),
            )
        )
        self.assertIn("Éventuellement", watch_digest)
        self.assertNotIn("À surveiller", watch_digest)
        self.assertIn(watch_summary, watch_digest)
        self.assertNotIn(watch_abstract, watch_digest)
        self.assertNotIn(">Abstract</p>", watch_digest)

    def test_digest_uses_natural_french_agreements_for_counts(self):
        publication = NewPublication(
            identity="doi:10.1234/agreements",
            doi="10.1234/agreements",
            title="Accords grammaticaux",
            url=None,
            source_subject="Newsletter",
            source_sender="éditeur@example.org",
            priority=PublicationPriority.HIGH,
        )

        none_retained = render_digest((), total_count=2, excluded_count=2)
        one_retained = render_digest(
            (publication,), total_count=1, excluded_count=0
        )
        several_retained = render_digest(
            (publication, publication), total_count=3, excluded_count=1
        )

        self.assertIn(
            "0 articles retenus sur 2 publiés.",
            none_retained,
        )
        self.assertIn(
            "1 article retenu sur 1 publié.",
            one_retained,
        )
        self.assertIn(
            "2 articles retenus sur 3 publiés.",
            several_retained,
        )

    def test_extracts_html_links_deduplicates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            database = root / "data" / "veille.sqlite"
            digest = root / "out" / "digest.html"

            write_email(
                inbox / "newsletter-1.eml",
                "<newsletter-1@example.org>",
                "Nouvelles publications — revue A",
                plain=(
                    "Choice architecture in public services\n"
                    "DOI: 10.1234/BEHAV.2026.001\n\n"
                    "Social norms and energy use\n"
                    "https://doi.org/10.5555/norms.42\n"
                ),
            )
            write_email(
                inbox / "newsletter-2.eml",
                "<newsletter-2@example.org>",
                "Sommaire — revue B",
                markup=(
                    "<h2>Article déjà signalé</h2>"
                    '<a href="https://doi.org/10.1234/behav.2026.001">Consulter</a>'
                    "<h2>Defaults and mobility</h2>"
                    '<a href="https://doi.org/10.9999/mobility-7">Consulter</a>'
                ),
            )

            first = run_pipeline(
                inbox, database, digest, deliver_unenriched=True
            )
            self.assertEqual(first.messages_processed, 2)
            self.assertEqual(first.messages_skipped, 0)
            self.assertEqual(first.publications_detected, 4)
            self.assertEqual(first.publications_new, 3)
            self.assertEqual(first.errors, ())

            connection = sqlite3.connect(str(database))
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM publications").fetchone()[0], 3
                )
            finally:
                connection.close()

            html = digest.read_text(encoding="utf-8")
            self.assertIn("3 nouvelles publications détectées", html)
            self.assertIn("Choice architecture in public services", html)
            self.assertIn("10.9999/mobility-7", html)

            second = run_pipeline(
                inbox, database, digest, deliver_unenriched=True
            )
            self.assertEqual(second.messages_processed, 0)
            self.assertEqual(second.messages_skipped, 2)
            self.assertEqual(second.publications_new, 0)
            self.assertIn(
                "Aucune nouvelle publication détectée",
                digest.read_text(encoding="utf-8"),
            )

    def test_retries_pending_publications_when_digest_write_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            database = root / "data" / "veille.sqlite"
            digest = root / "out" / "digest.html"
            write_email(
                inbox / "newsletter.eml",
                "<retry@example.org>",
                "Newsletter à reprendre",
                plain="Article à conserver\n10.1234/retry.1",
            )

            with patch("veille.pipeline.write_digest", side_effect=OSError("volume plein")):
                with self.assertRaises(OSError):
                    run_pipeline(
                        inbox, database, digest, deliver_unenriched=True
                    )

            retry = run_pipeline(
                inbox, database, digest, deliver_unenriched=True
            )
            self.assertEqual(retry.messages_processed, 0)
            self.assertEqual(retry.messages_skipped, 1)
            self.assertEqual(retry.publications_new, 0)
            self.assertEqual(retry.publications_delivered, 1)
            self.assertIn("10.1234/retry.1", digest.read_text(encoding="utf-8"))

            connection = sqlite3.connect(str(database))
            try:
                delivered_at = connection.execute(
                    "SELECT delivered_at FROM publications WHERE doi = ?",
                    ("10.1234/retry.1",),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertIsNotNone(delivered_at)

    def test_migrates_database_created_by_initial_version(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite"
            connection = sqlite3.connect(str(database))
            try:
                connection.executescript(
                    """
                    CREATE TABLE messages (
                        identity TEXT PRIMARY KEY,
                        subject TEXT NOT NULL,
                        sender TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        processed_at TEXT NOT NULL
                    );
                    CREATE TABLE publications (
                        doi TEXT PRIMARY KEY,
                        title TEXT,
                        first_seen_at TEXT NOT NULL
                    );
                    CREATE TABLE message_publications (
                        message_identity TEXT NOT NULL REFERENCES messages(identity),
                        publication_doi TEXT NOT NULL REFERENCES publications(doi),
                        PRIMARY KEY (message_identity, publication_doi)
                    );
                    INSERT INTO messages VALUES (
                        'legacy-message', 'Ancienne newsletter', 'éditeur@example.org',
                        'legacy.eml', '2026-08-21T00:00:00+00:00'
                    );
                    INSERT INTO publications VALUES (
                        '10.1234/legacy.1', 'Article historique',
                        '2026-08-21T00:00:00+00:00'
                    );
                    INSERT INTO message_publications VALUES (
                        'legacy-message', '10.1234/legacy.1'
                    );
                    """
                )
                connection.commit()
            finally:
                connection.close()

            store = Store(database)
            try:
                pending = store.pending_publications()
            finally:
                store.close()

            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].doi, "10.1234/legacy.1")

    def test_uses_content_hash_when_message_id_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "message.eml"
            message = EmailMessage()
            message["From"] = "éditeur@example.org"
            message["Subject"] = "Sans identifiant"
            message.set_content("Article\n10.1111/example.1")
            path.write_bytes(message.as_bytes())

            parsed = parse_message(path)
            self.assertTrue(parsed.identity.startswith("sha256:"))
            self.assertEqual(parsed.publications[0].doi, "10.1111/example.1")

    def test_extracts_doi_with_extended_suffix_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "message.eml"
            write_email(
                path,
                "<extended-doi@example.org>",
                "DOI étendu",
                plain="Article historique\n10.1234/a&b=c@d%25{e}[f]?",
            )

            parsed = parse_message(path)
            self.assertEqual(parsed.publications[0].doi, "10.1234/a&b=c@d%{e}[f]?")


if __name__ == "__main__":
    unittest.main()
