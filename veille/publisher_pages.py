import json
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

from . import __version__
from .elsevier import pii_from_sciencedirect_url
from .europepmc import EuropePmcError
from .openalex import OpenAlexError
from .mail_diagnostics import create_tls_context
from .models import WorkMetadata


class PublisherPageError(RuntimeError):
    pass


class _PublisherMetadataParser(HTMLParser):
    ABSTRACT_NAMES = (
        "citation_abstract",
        "dc.description",
        "dcterms.abstract",
        "description",
        "og:description",
    )

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.values = {}
        self.authors = []
        self._json_ld = False
        self._json_chunks = []
        self.json_documents = []

    def handle_starttag(self, tag, attrs):
        attributes = {name.casefold(): value for name, value in attrs if value}
        if tag.casefold() == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").casefold()
            content = attributes.get("content")
            if name and content:
                if name == "citation_author":
                    self.authors.append(content.strip())
                elif name not in self.values:
                    self.values[name] = content.strip()
        if tag.casefold() == "script" and attributes.get("type", "").casefold() == "application/ld+json":
            self._json_ld = True
            self._json_chunks = []

    def handle_data(self, data):
        if self._json_ld:
            self._json_chunks.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() == "script" and self._json_ld:
            self._json_ld = False
            raw = "".join(self._json_chunks).strip()
            if raw:
                try:
                    self.json_documents.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass

    def first(self, *names):
        for name in names:
            value = self.values.get(name.casefold())
            if value:
                return " ".join(value.split())
        return None

    def json_article(self):
        queue = list(self.json_documents)
        while queue:
            value = queue.pop(0)
            if isinstance(value, list):
                queue.extend(value)
                continue
            if not isinstance(value, dict):
                continue
            graph = value.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
            article_type = value.get("@type")
            if isinstance(article_type, list):
                types = {str(item).casefold() for item in article_type}
            else:
                types = {str(article_type).casefold()}
            if types.intersection({"article", "scholarlyarticle", "medicalscholarlyarticle"}):
                return value
        return {}


def _json_authors(article):
    authors = article.get("author") or []
    if isinstance(authors, (str, dict)):
        authors = [authors]
    names = []
    for author in authors:
        if isinstance(author, str):
            name = author.strip()
        elif isinstance(author, dict):
            name = str(author.get("name") or "").strip()
        else:
            name = ""
        if name:
            names.append(name)
    return tuple(names)


class PublisherPageClient:
    def __init__(self, timeout=10, max_bytes=2000000, opener=None):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.opener = opener or urlopen

    def fetch_by_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise PublisherPageError("URL éditeur non HTTP(S).")
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "veille-scientifique/{} "
                    "(+https://github.com/DimitriNaczaj/veille-scientifique)"
                ).format(__version__),
            },
        )
        try:
            try:
                response_context = self.opener(
                    request, timeout=self.timeout, context=create_tls_context()
                )
            except TypeError:
                response_context = self.opener(request, timeout=self.timeout)
            with response_context as response:
                payload = response.read(self.max_bytes + 1)
        except HTTPError as error:
            if error.code in (401, 403, 404, 410):
                return None
            raise PublisherPageError("Page éditeur HTTP {}".format(error.code)) from error
        except URLError as error:
            raise PublisherPageError(
                "Page éditeur indisponible : {}".format(error.reason)
            ) from error
        if len(payload) > self.max_bytes:
            raise PublisherPageError("Page éditeur trop volumineuse.")
        parser = _PublisherMetadataParser()
        try:
            parser.feed(payload.decode("utf-8", errors="replace"))
        except Exception as error:
            raise PublisherPageError("Métadonnées éditeur invalides.") from error
        article = parser.json_article()
        abstract = parser.first(*parser.ABSTRACT_NAMES)
        if not abstract:
            value = article.get("description")
            abstract = " ".join(str(value).split()) if value else None
        title = parser.first("citation_title", "dc.title", "og:title")
        if not title:
            value = article.get("headline") or article.get("name")
            title = " ".join(str(value).split()) if value else None
        journal = parser.first("citation_journal_title", "dc.source")
        date = parser.first("citation_publication_date", "dc.date", "article:published_time")
        authors = tuple(value for value in parser.authors if value) or _json_authors(article)
        if not any((title, abstract, journal, date, authors)):
            return None
        return WorkMetadata(
            title=title,
            abstract=abstract,
            journal=journal,
            published_date=date,
            authors=authors,
            url=url,
        )


def _doi_from_url(url):
    """Extrait le DOI d’une URL ``https://doi.org/...``."""
    if not url:
        return None
    parsed = urlsplit(str(url))
    if (parsed.hostname or "").casefold() not in ("doi.org", "dx.doi.org"):
        return None
    doi = unquote(parsed.path).lstrip("/").strip()
    return doi if doi.startswith("10.") else None


def _merge_metadata(primary, secondary):
    if primary is None:
        return secondary
    if secondary is None:
        return primary
    return WorkMetadata(
        title=primary.title or secondary.title,
        abstract=primary.abstract or secondary.abstract,
        journal=primary.journal or secondary.journal,
        published_date=primary.published_date or secondary.published_date,
        authors=primary.authors or secondary.authors,
        url=primary.url or secondary.url,
    )


class MetadataCascade:
    def __init__(
        self,
        crossref_client,
        publisher_client,
        elsevier_client=None,
        openalex_client=None,
        europepmc_client=None,
    ):
        self.crossref_client = crossref_client
        self.publisher_client = publisher_client
        self.elsevier_client = elsevier_client
        self.openalex_client = openalex_client
        self.europepmc_client = europepmc_client
        self.source_failures = {}

    def _open_sources(self):
        """Sources ouvertes interrogées par DOI, dans l’ordre de rendement."""
        return (
            ("OpenAlex", self.openalex_client, OpenAlexError),
            ("Europe PMC", self.europepmc_client, EuropePmcError),
        )

    def fetch_by_doi(self, doi, source_url=None):
        primary = self.fetch_primary_by_doi(doi)
        if primary is not None and primary.abstract:
            return primary
        primary = self.fetch_open_sources(doi, primary)
        if primary is not None and primary.abstract:
            return primary
        return self.fetch_publisher_fallback(
            doi,
            primary,
            source_url=source_url,
        )

    def fetch_open_sources(self, doi, primary=None):
        """Complète les métadonnées par les catalogues ouverts.

        Une panne d’un catalogue ne doit pas interrompre l’enrichissement :
        l’échec est comptabilisé et la chaîne continue sur la source suivante.
        """
        for name, client, failure in self._open_sources():
            if client is None:
                continue
            if primary is not None and primary.abstract:
                break
            try:
                candidate = client.fetch_by_doi(doi)
            except failure:
                self.source_failures[name] = self.source_failures.get(name, 0) + 1
                continue
            primary = _merge_metadata(primary, candidate)
        return primary

    def fetch_primary_by_doi(self, doi):
        return (
            self.crossref_client.fetch_by_doi(doi)
            if self.crossref_client is not None
            else None
        )

    def fetch_publisher_fallback(self, doi, primary=None, source_url=None):
        url = (
            source_url
            if source_url and pii_from_sciencedirect_url(source_url)
            else primary.url
            if primary is not None and primary.url
            else "https://doi.org/" + quote(doi, safe="/")
        )
        secondary = self.fetch_by_url(url)
        return _merge_metadata(primary, secondary)

    def fetch_by_url(self, url):
        primary = None
        pii = pii_from_sciencedirect_url(url)
        if pii and self.elsevier_client is not None:
            primary = self.elsevier_client.fetch_by_pii(pii)
            if primary is not None and primary.abstract:
                return primary
        # Sans résumé, la vue META d’Elsevier fournit tout de même le DOI.
        # C’est la seule clé d’entrée des catalogues ouverts, qui n’acceptent
        # pas les PII : sans ce relais, une publication connue par sa seule
        # URL ScienceDirect n’atteindrait jamais OpenAlex ni Europe PMC.
        doi = _doi_from_url(primary.url) if primary is not None else None
        if doi:
            primary = self.fetch_open_sources(doi, primary)
            if primary is not None and primary.abstract:
                return primary
        secondary = self.publisher_client.fetch_by_url(url)
        return _merge_metadata(primary, secondary)
