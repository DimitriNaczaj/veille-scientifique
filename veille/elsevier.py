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


class ElsevierEntitlementError(ElsevierError):
    """La clé est valide mais la vue demandée n’est pas couverte."""


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
    core = payload.get("coredata") or {}
    creator = core.get("dc:creator") if isinstance(core, dict) else {}
    container = payload.get("authors") or creator or {}
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
    PREFERRED_VIEW = "META_ABS"
    FALLBACK_VIEW = "META"

    def __init__(self, api_key, timeout=10, opener=None):
        if not api_key or not api_key.strip():
            raise ValueError("La clé API Elsevier est vide.")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.opener = opener or urlopen
        self.view = self.PREFERRED_VIEW
        self.entitlement_notice = None

    def _request(self, pii, view):
        url = "{}{}?view={}".format(self.BASE_URL, quote(pii, safe=""), view)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "veille-scientifique/{} "
                    "(+https://github.com/DimitriNaczaj/veille-scientifique)"
                ).format(__version__),
            },
        )
        request.headers["X-ELS-APIKey"] = self.api_key
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            status = _error_status(error)
            if status == "AUTHORIZATION_ERROR":
                raise ElsevierEntitlementError(
                    "Elsevier HTTP {} : vue {} non couverte par la clé".format(
                        error.code, view
                    )
                ) from error
            if status == "AUTHENTICATION_ERROR":
                raise ElsevierError(
                    "Elsevier HTTP {} : clé API refusée".format(error.code)
                ) from error
            raise ElsevierError("Elsevier HTTP {}".format(error.code)) from error
        except URLError as error:
            raise ElsevierError(
                "Elsevier indisponible : {}".format(error.reason)
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ElsevierError("Réponse Elsevier invalide") from error

    def fetch_by_pii(self, pii):
        if not re.fullmatch(r"[A-Za-z0-9]+", pii or ""):
            raise ValueError("PII Elsevier invalide.")
        try:
            payload = self._request(pii, self.view)
        except ElsevierEntitlementError:
            if self.view == self.FALLBACK_VIEW:
                raise
            # La clé est reconnue mais l’abonnement ne couvre pas la vue
            # enrichie. On rétrograde une fois pour toutes vers ``META`` :
            # sans résumé, mais avec titre, revue, date et auteurs, ce qui
            # laisse la cascade chercher le résumé sur la page éditeur.
            self.view = self.FALLBACK_VIEW
            self.entitlement_notice = (
                "Clé Elsevier sans droit sur la vue {} : enrichissement "
                "limité à {} (aucun résumé fourni par l’API)."
            ).format(self.PREFERRED_VIEW, self.FALLBACK_VIEW)
            payload = self._request(pii, self.view)
        if payload is None:
            return None

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


def _error_status(error):
    """Lit ``statusCode`` dans le corps JSON d’une erreur Elsevier."""
    try:
        body = error.read()
    except Exception:
        return None
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, ValueError):
        return None
    status = ((payload.get("service-error") or {}).get("status") or {})
    code = status.get("statusCode") if isinstance(status, dict) else None
    return str(code).strip().upper() if code else None
