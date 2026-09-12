"""Récupération prudente d'un PDF scientifique en accès ouvert."""
import hashlib
import ipaddress
import json
import os
import socket
import tempfile
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__


class PdfUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PdfRetrieval:
    source_url: str
    license: object
    sha256: str
    size_bytes: int


def _public_https_url(value):
    try:
        parsed = urlparse(value)
    except (TypeError, ValueError):
        return None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        return None
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None
    return parsed.geturl()


def _require_public_network_url(value):
    url = _public_https_url(value)
    if not url:
        raise PdfUnavailableError("Adresse PDF refusée.")
    hostname = urlparse(url).hostname
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise PdfUnavailableError("Adresse PDF introuvable.") from error
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in addresses
    ):
        raise PdfUnavailableError("Adresse PDF non publique refusée.")
    return url


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_public_network_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class OpenAccessPdfFetcher:
    UNPAYWALL_URL = "https://api.unpaywall.org/v2/"

    def __init__(self, contact_email, timeout=30, max_bytes=30 * 1024 * 1024, opener=None):
        if not str(contact_email or "").strip():
            raise ValueError("Une adresse de contact est requise pour Unpaywall.")
        if max_bytes < 1024:
            raise ValueError("La taille PDF maximale est trop faible.")
        self.contact_email = str(contact_email).strip()
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.opener = opener or build_opener(_PublicRedirectHandler()).open
        self._validate_network = opener is None

    def _open(self, request):
        return self.opener(request, timeout=self.timeout)

    def _metadata(self, doi):
        url = self.UNPAYWALL_URL + quote(doi.strip(), safe="")
        url += "?" + urlencode({"email": self.contact_email})
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "veille-scientifique/{}".format(__version__),
            },
        )
        try:
            with self._open(request) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as error:
            if error.code == 404:
                return {}
            raise PdfUnavailableError("Unpaywall HTTP {}".format(error.code)) from None
        except URLError as error:
            raise PdfUnavailableError(
                "Unpaywall indisponible : {}".format(error.reason)
            ) from None
        if len(raw) > 2 * 1024 * 1024:
            raise PdfUnavailableError("Réponse Unpaywall trop volumineuse.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PdfUnavailableError("Réponse Unpaywall invalide.") from None
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _locations(metadata):
        ordered = []
        best = metadata.get("best_oa_location")
        if isinstance(best, dict):
            ordered.append(best)
        for location in metadata.get("oa_locations") or ():
            if isinstance(location, dict) and location not in ordered:
                ordered.append(location)
        return ordered

    def _download(self, url):
        if self._validate_network:
            url = _require_public_network_url(url)
        request = Request(
            url,
            headers={
                "Accept": "application/pdf,application/octet-stream;q=0.8",
                "User-Agent": "veille-scientifique/{}".format(__version__),
            },
        )
        try:
            with self._open(request) as response:
                final_url = _public_https_url(
                    response.geturl() if hasattr(response, "geturl") else url
                )
                if not final_url:
                    raise PdfUnavailableError(
                        "Le téléchargement PDF a été redirigé vers une adresse refusée."
                    )
                content = response.read(self.max_bytes + 1)
        except HTTPError as error:
            raise PdfUnavailableError("Téléchargement PDF HTTP {}".format(error.code)) from None
        except URLError as error:
            raise PdfUnavailableError(
                "Téléchargement PDF indisponible : {}".format(error.reason)
            ) from None
        if len(content) > self.max_bytes:
            raise PdfUnavailableError("Le PDF dépasse la taille maximale autorisée.")
        if b"%PDF-" not in content[:1024]:
            raise PdfUnavailableError("La ressource reçue n'est pas un PDF valide.")
        return content, final_url

    def fetch(self, doi, destination):
        if not str(doi or "").strip():
            raise PdfUnavailableError("Aucun DOI n'est disponible pour récupérer le PDF.")
        destination = os.fspath(destination)
        parent = os.path.dirname(destination)
        if os.path.islink(destination) or os.path.islink(parent):
            raise PdfUnavailableError("La destination PDF ne peut pas être symbolique.")
        os.makedirs(parent, exist_ok=True)
        metadata = self._metadata(str(doi))
        errors = []
        for location in self._locations(metadata):
            source_url = _public_https_url(location.get("url_for_pdf"))
            if not source_url:
                continue
            try:
                content, final_url = self._download(source_url)
            except PdfUnavailableError as error:
                errors.append(str(error))
                continue
            descriptor, temporary = tempfile.mkstemp(prefix=".article-", dir=parent)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
            return PdfRetrieval(
                source_url=final_url,
                license=location.get("license"),
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
            )
        if errors:
            raise PdfUnavailableError(errors[-1])
        raise PdfUnavailableError(
            "Aucune version PDF accessible légalement n'a été trouvée pour ce DOI."
        )
