import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import __version__
from .models import WorkMetadata


class EuropePmcError(RuntimeError):
    pass


def europepmc_client_from_config(config, opener=None):
    if config.has_section("europepmc") and not config.getboolean(
        "europepmc", "enabled", fallback=True
    ):
        return None
    return EuropePmcClient(opener=opener)


def _authors(result):
    collection = result.get("authorList")
    authors = collection.get("author") if isinstance(collection, dict) else None
    names = []
    for author in authors or []:
        if not isinstance(author, dict):
            continue
        name = author.get("fullName") or author.get("collectiveName")
        if not name:
            initials = author.get("initials") or ""
            surname = author.get("lastName") or ""
            name = "{} {}".format(surname, initials).strip()
        if name:
            names.append(" ".join(str(name).split()))
    return tuple(names)


def _published_date(result):
    for field in ("firstPublicationDate", "electronicPublicationDate"):
        value = result.get(field)
        if value:
            return str(value).strip()
    year = result.get("pubYear")
    return str(year).strip() if year else None


class EuropePmcClient:
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, timeout=10, opener=None):
        self.timeout = timeout
        self.opener = opener or urlopen

    def fetch_by_doi(self, doi):
        if not doi or not doi.strip():
            return None
        query = urlencode(
            {
                "query": 'DOI:"{}"'.format(doi.strip()),
                "resultType": "core",
                "format": "json",
                "pageSize": "1",
            }
        )
        request = Request(
            self.BASE_URL + "?" + query,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "veille-scientifique/{} "
                    "(+https://github.com/DimitriNaczaj/veille-scientifique)"
                ).format(__version__),
            },
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise EuropePmcError("Europe PMC HTTP {}".format(error.code)) from error
        except URLError as error:
            raise EuropePmcError(
                "Europe PMC indisponible : {}".format(error.reason)
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EuropePmcError("Réponse Europe PMC invalide") from error

        collection = payload.get("resultList")
        results = collection.get("result") if isinstance(collection, dict) else None
        if not results:
            return None
        result = results[0]
        if not isinstance(result, dict):
            raise EuropePmcError("Réponse Europe PMC sans métadonnées")
        # La recherche par DOI reste une recherche : on écarte tout résultat
        # dont le DOI ne correspond pas exactement à celui demandé.
        found = str(result.get("doi") or "").strip().casefold()
        if found and found != doi.strip().casefold():
            return None
        abstract = result.get("abstractText")
        title = result.get("title")
        return WorkMetadata(
            title=" ".join(str(title).split()) if title else None,
            abstract=" ".join(str(abstract).split()) if abstract else None,
            journal=(
                " ".join(str(result.get("journalTitle")).split())
                if result.get("journalTitle")
                else None
            ),
            published_date=_published_date(result),
            authors=_authors(result),
            url=(
                "https://doi.org/" + doi.strip()
                if result.get("doi")
                else None
            ),
        )
