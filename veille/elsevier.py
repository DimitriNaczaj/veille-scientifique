import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

from . import __version__
from .models import WorkMetadata


class ElsevierError(RuntimeError):
    pass


def elsevier_client_from_config(config, opener=None):
    if not config.has_section("elsevier"):
        return None
    environment_name = config.get(
        "elsevier", "api_key_env", fallback="ELSEVIER_API_KEY"
    ).strip() or "ELSEVIER_API_KEY"
    api_key = os.environ.get(environment_name, "").strip()
    if not api_key:
        return None
    return ElsevierClient(api_key=api_key, opener=opener)


def pii_from_sciencedirect_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    if host not in ("sciencedirect.com", "www.sciencedirect.com"):
        return None
    query = {
        key.casefold(): values
        for key, values in parse_qs(parsed.query).items()
    }
    values = query.get("_piikey") or query.get("pii")
    candidate = values[0] if values else None
    if candidate is None:
        match = re.search(r"/pii/([A-Za-z0-9]+)(?:/|$)", parsed.path)
        candidate = match.group(1) if match else None
    if not candidate or not re.fullmatch(r"[A-Za-z0-9]+", candidate):
        return None
    return candidate


def _authors(payload):
    container = payload.get("authors") or {}
    authors = container.get("author") if isinstance(container, dict) else []
    if isinstance(authors, dict):
        authors = [authors]
    names = []
    for author in authors or []:
        if not isinstance(author, dict):
            continue
        name = author.get("ce:indexed-name") or author.get("indexed-name")
        if name:
            names.append(" ".join(str(name).split()))
    return tuple(names)


class ElsevierClient:
    BASE_URL = "https://api.elsevier.com/content/abstract/pii/"

    def __init__(self, api_key, timeout=10, opener=None):
        if not api_key or not api_key.strip():
            raise ValueError("La clé API Elsevier est vide.")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.opener = opener or urlopen

    def fetch_by_pii(self, pii):
        if not re.fullmatch(r"[A-Za-z0-9]+", pii or ""):
            raise ValueError("PII Elsevier invalide.")
        url = self.BASE_URL + quote(pii, safe="") + "?view=META_ABS"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "veille-scientifique/{} "
                    "(+https://github.com/DimitriNaczaj/veille-scientifique)"
                ).format(__version__),
                "X-ELS-APIKey": self.api_key,
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise ElsevierError("Elsevier HTTP {}".format(error.code)) from error
        except URLError as error:
            raise ElsevierError(
                "Elsevier indisponible : {}".format(error.reason)
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ElsevierError("Réponse Elsevier invalide") from error

        root = payload.get("abstracts-retrieval-response")
        if not isinstance(root, dict):
            raise ElsevierError("Réponse Elsevier sans métadonnées")
        core = root.get("coredata") or {}
        if not isinstance(core, dict):
            raise ElsevierError("Réponse Elsevier sans métadonnées")
        doi = core.get("prism:doi")
        abstract = core.get("dc:description")
        return WorkMetadata(
            title=_normalized(core.get("dc:title")),
            abstract=_normalized(abstract),
            journal=_normalized(core.get("prism:publicationName")),
            published_date=_normalized(core.get("prism:coverDate")),
            authors=_authors(root),
            url=(
                "https://doi.org/" + str(doi).strip()
                if doi
                else "https://www.sciencedirect.com/science/article/pii/" + pii
            ),
        )


def _normalized(value):
    return " ".join(str(value).split()) if value else None
