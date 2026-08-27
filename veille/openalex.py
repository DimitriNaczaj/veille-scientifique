import json
import re
import time
from difflib import SequenceMatcher
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


def _comparable(title):
    """Réduit un titre à ses mots, pour comparer deux graphies."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(title).casefold()).split())


def _same_work(wanted, found):
    if not wanted or not found:
        return False
    return SequenceMatcher(None, _comparable(wanted), _comparable(found)).ratio() >= 0.90


class OpenAlexClient:
    BASE_URL = "https://api.openalex.org/works/doi:"
    SEARCH_URL = "https://api.openalex.org/works"
    # OpenAlex renvoie 429 quand les appels se succèdent trop vite. Une
    # courte pause suffit : le refus est temporaire, pas définitif.
    RETRY_DELAY = 5.0

    def __init__(self, contact_email=None, timeout=10, opener=None):
        self.contact_email = contact_email
        self.timeout = timeout
        self.opener = opener or urlopen

    def fetch_by_title(self, title):
        """Cherche une publication par son titre, à défaut de DOI.

        Une recherche peut renvoyer un article voisin : le titre trouvé est
        donc recomparé au titre demandé, et tout écart notable fait rejeter
        le résultat. Rattacher le résumé d’un autre article serait pire que
        n’en rattacher aucun.
        """
        if not title or len(title.strip()) < 25:
            return None
        # Le filtre OpenAlex a sa propre syntaxe : virgule, barre verticale
        # et deux-points y séparent les termes, et la ponctuation restante
        # provoque des refus HTTP 400. On ne garde donc que les mots.
        needle = " ".join(_comparable(title).split()[:24])
        if not needle:
            return None
        query = {"filter": "title.search:" + needle, "per-page": "1"}
        if self.contact_email:
            query["mailto"] = self.contact_email
        payload = self._get(self.SEARCH_URL + "?" + urlencode(query))
        if payload is None:
            return None
        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            return None
        work = results[0]
        if not isinstance(work, dict) or not _same_work(
            title, work.get("display_name") or work.get("title")
        ):
            return None
        return self._metadata(work)

    def _get(self, url, retried=False):
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
            if error.code == 429 and not retried:
                time.sleep(self.RETRY_DELAY)
                return self._get(url, retried=True)
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
