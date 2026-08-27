import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import __version__
from .models import WorkMetadata


class OpenAlexError(RuntimeError):
    pass


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

    def __init__(self, contact_email=None, timeout=10, opener=None):
        self.contact_email = contact_email
        self.timeout = timeout
        self.opener = opener or urlopen

    def fetch_by_doi(self, doi):
        if not doi or not doi.strip():
            return None
        url = self.BASE_URL + quote(doi.strip(), safe="/")
        agent = (
            "veille-scientifique/{} "
            "(+https://github.com/DimitriNaczaj/veille-scientifique)"
        ).format(__version__)
        if self.contact_email:
            # Le « polite pool » d’OpenAlex demande une adresse de contact et
            # accorde en échange un débit nettement plus stable.
            url += "?" + urlencode({"mailto": self.contact_email})
            agent += " mailto:{}".format(self.contact_email)
        request = Request(
            url, headers={"Accept": "application/json", "User-Agent": agent}
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                work = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise OpenAlexError("OpenAlex HTTP {}".format(error.code)) from error
        except URLError as error:
            raise OpenAlexError(
                "OpenAlex indisponible : {}".format(error.reason)
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenAlexError("Réponse OpenAlex invalide") from error

        if not isinstance(work, dict) or not work.get("id"):
            raise OpenAlexError("Réponse OpenAlex sans métadonnées")
        title = work.get("display_name") or work.get("title")
        return WorkMetadata(
            title=" ".join(str(title).split()) if title else None,
            abstract=_abstract(work),
            journal=_journal(work),
            published_date=work.get("publication_date") or None,
            authors=_authors(work),
            url=work.get("doi") or None,
        )
