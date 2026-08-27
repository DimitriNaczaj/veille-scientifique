import json
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import __version__
from .models import WorkMetadata


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


class CrossrefClient:
    BASE_URL = "https://api.crossref.org/works/"

    def __init__(self, contact_email=None, timeout=10, opener=None):
        self.contact_email = contact_email
        self.timeout = timeout
        self.opener = opener or urlopen

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
        return WorkMetadata(
            title=_first_string(message.get("title")),
            abstract=_plain_text(message.get("abstract")),
            journal=_first_string(message.get("container-title")),
            published_date=_published_date(message),
            authors=_authors(message),
            url=_first_string(message.get("URL")),
        )
