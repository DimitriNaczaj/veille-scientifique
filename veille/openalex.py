import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import __version__
from .models import WorkMetadata
from .titles import same_work, searchable


class OpenAlexError(RuntimeError):
    pass


class OpenAlexBudgetError(OpenAlexError):
    """Budget quotidien de recherche épuisé ; il repart à minuit UTC."""


def openalex_client_from_config(config, opener=None):
    if config.has_section("openalex") and not config.getboolean(
        "openalex", "enabled", fallback=True
    ):
        return None
    contact_email = config.get("app", "crossref_email", fallback="").strip()
    if not contact_email:
        contact_email = config.get("imap", "username", fallback="").strip() or None
    return OpenAlexClient(contact_email=contact_email, opener=opener)


def _abstract(work):
    """Reconstitue le résumé depuis l’index inversé ``mot -> positions``.

    OpenAlex ne redistribue pas les résumés en texte continu ; il publie les
    positions de chaque mot, qu’il suffit de réordonner.
    """
    index = work.get("abstract_inverted_index")
    if not isinstance(index, dict) or not index:
        return None
    words = {}
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                words[position] = word
    if not words:
        return None
    text = " ".join(words[position] for position in sorted(words))
    return " ".join(text.split()) or None


def _authors(work):
    names = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        name = (author or {}).get("display_name") if isinstance(author, dict) else None
        if name:
            names.append(" ".join(str(name).split()))
    return tuple(names)


def _journal(work):
    location = work.get("primary_location")
    source = (location or {}).get("source") if isinstance(location, dict) else None
    name = (source or {}).get("display_name") if isinstance(source, dict) else None
    return " ".join(str(name).split()) if name else None


class OpenAlexClient:
    BASE_URL = "https://api.openalex.org/works/doi:"
    SEARCH_URL = "https://api.openalex.org/works"

    def __init__(self, contact_email=None, timeout=10, opener=None):
        self.contact_email = contact_email
        self.timeout = timeout
        self.opener = opener or urlopen
        # Les recherches par titre consomment un budget quotidien. Une fois
        # épuisé, il ne se reconstitue qu’à minuit UTC : inutile de réessayer
        # pendant l’exécution, on cesse simplement d’en faire.
        self.search_budget_exhausted = False

    def fetch_by_title(self, title):
        """Cherche une publication par son titre, à défaut de DOI.

        Une recherche coûte dix crédits sur un budget quotidien de mille,
        soit cent recherches par jour. La consultation par DOI, elle, reste
        gratuite. Cette méthode est donc un complément, pas un pilier.
        """
        if self.search_budget_exhausted:
            return None
        # Le filtre OpenAlex a sa propre syntaxe : la ponctuation y provoque
        # des refus HTTP 400. On ne transmet que les mots.
        needle = searchable(title)
        if not needle:
            return None
        query = {"filter": "title.search:" + needle, "per-page": "1"}
        if self.contact_email:
            query["mailto"] = self.contact_email
        try:
            payload = self._get(self.SEARCH_URL + "?" + urlencode(query))
        except OpenAlexBudgetError:
            self.search_budget_exhausted = True
            return None
        if payload is None:
            return None
        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            return None
        work = results[0]
        if not isinstance(work, dict) or not same_work(
            title, work.get("display_name") or work.get("title")
        ):
            return None
        return self._metadata(work)

    def _get(self, url):
        agent = (
            "veille-scientifique/{} "
            "(+https://github.com/DimitriNaczaj/veille-scientifique)"
        ).format(__version__)
        if self.contact_email:
            agent += " mailto:{}".format(self.contact_email)
        request = Request(
            url, headers={"Accept": "application/json", "User-Agent": agent}
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:
                raise OpenAlexBudgetError(
                    "Budget de recherche OpenAlex épuisé jusqu’à minuit UTC"
                ) from error
            raise OpenAlexError("OpenAlex HTTP {}".format(error.code)) from error
        except URLError as error:
            raise OpenAlexError(
                "OpenAlex indisponible : {}".format(error.reason)
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenAlexError("Réponse OpenAlex invalide") from error

    def _metadata(self, work):
        title = work.get("display_name") or work.get("title")
        return WorkMetadata(
            title=" ".join(str(title).split()) if title else None,
            abstract=_abstract(work),
            journal=_journal(work),
            published_date=work.get("publication_date") or None,
            authors=_authors(work),
            url=work.get("doi") or None,
        )

    def fetch_by_doi(self, doi):
        if not doi or not doi.strip():
            return None
        url = self.BASE_URL + quote(doi.strip(), safe="/")
        if self.contact_email:
            # Le « polite pool » d’OpenAlex demande une adresse de contact et
            # accorde en échange un débit nettement plus stable.
            url += "?" + urlencode({"mailto": self.contact_email})
        work = self._get(url)
        if work is None:
            return None
        if not isinstance(work, dict) or not work.get("id"):
            raise OpenAlexError("Réponse OpenAlex sans métadonnées")
        return self._metadata(work)
