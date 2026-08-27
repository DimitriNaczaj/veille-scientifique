import json
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import __version__
from .models import WorkMetadata
from .titles import same_work, searchable


class CrossrefError(RuntimeError):
    pass


class _MarkupTextParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.chunks = []

    def handle_data(self, data):
        self.chunks.append(data)

    def text(self):
        return " ".join("".join(self.chunks).split())


def _first_string(value):
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0].strip() or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _plain_text(markup):
    if not markup:
        return None
    parser = _MarkupTextParser()
    parser.feed(markup)
    return parser.text() or None


def _published_date(message):
    date_parts = (message.get("published") or {}).get("date-parts") or []
    if not date_parts or not date_parts[0]:
        return None
    parts = date_parts[0]
    if not all(isinstance(part, int) for part in parts[:3]):
        return None
    if len(parts) >= 3:
        return "{:04d}-{:02d}-{:02d}".format(parts[0], parts[1], parts[2])
    if len(parts) == 2:
        return "{:04d}-{:02d}".format(parts[0], parts[1])
    return "{:04d}".format(parts[0])


def _authors(message):
    names = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        literal = author.get("name")
        if literal:
            name = str(literal).strip()
        else:
            name = " ".join(
                str(author.get(field, "")).strip()
                for field in ("given", "family")
                if author.get(field)
            )
        if name:
            names.append(name)
    return tuple(names)


def _metadata_from_message(message):
    doi = _first_string(message.get("DOI"))
    return WorkMetadata(
        title=_first_string(message.get("title")),
        abstract=_plain_text(message.get("abstract")),
        journal=_first_string(message.get("container-title")),
        published_date=_published_date(message),
        authors=_authors(message),
        url=_first_string(message.get("URL"))
        or ("https://doi.org/" + doi if doi else None),
    )


class CrossrefClient:
    BASE_URL = "https://api.crossref.org/works/"

    def __init__(self, contact_email=None, timeout=10, opener=None):
        self.contact_email = contact_email
        self.timeout = timeout
        self.opener = opener or urlopen

    SEARCH_URL = "https://api.crossref.org/works"

    def _request(self, url):
        agent = (
            "veille-scientifique/{} "
            "(+https://github.com/DimitriNaczaj/veille-scientifique)"
        ).format(__version__)
        if self.contact_email:
            agent += " mailto:{}".format(self.contact_email)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": agent})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise CrossrefError("Crossref HTTP {}".format(error.code)) from error
        except URLError as error:
            raise CrossrefError("Crossref indisponible : {}".format(error.reason)) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CrossrefError("Réponse Crossref invalide") from error

    def fetch_by_title(self, title):
        """Retrouve une publication par son titre.

        Crossref n’impose pas de budget : c’est la voie utilisable à grande
        échelle quand une publication n’est connue que par son titre et un
        lien de traçage devenu inexploitable. Le résultat n’est retenu que si
        son titre correspond réellement à celui demandé.
        """
        needle = searchable(title)
        if not needle:
            return None
        query = {"query.bibliographic": needle, "rows": "1"}
        if self.contact_email:
            query["mailto"] = self.contact_email
        payload = self._request(self.SEARCH_URL + "?" + urlencode(query))
        items = ((payload or {}).get("message") or {}).get("items") or []
        if not items or not isinstance(items[0], dict):
            return None
        message = items[0]
        if not same_work(title, _first_string(message.get("title"))):
            return None
        return _metadata_from_message(message)

    def fetch_by_doi(self, doi):
        url = self.BASE_URL + quote(doi, safe="")
        if self.contact_email:
            url += "?" + urlencode({"mailto": self.contact_email})
        agent = (
            "veille-scientifique/{} "
            "(+https://github.com/DimitriNaczaj/veille-scientifique)"
        ).format(__version__)
        if self.contact_email:
            agent += " mailto:{}".format(self.contact_email)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": agent})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise CrossrefError("Crossref HTTP {}".format(error.code)) from error
        except URLError as error:
            raise CrossrefError("Crossref indisponible : {}".format(error.reason)) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CrossrefError("Réponse Crossref invalide") from error

        message = payload.get("message")
        if not isinstance(message, dict):
            raise CrossrefError("Réponse Crossref sans métadonnées")
        return _metadata_from_message(message)
