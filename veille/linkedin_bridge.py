"""Demande signée de préparation d’un article pour LinkedIn."""
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import urlencode

from .mail_diagnostics import _load_config, _secret


LINKEDIN_REQUEST_MARKER = "VEILLE-LINKEDIN/1"
LINKEDIN_REQUEST_SUBJECT = "[Veille vers LinkedIn]"
_TOKEN_PURPOSE = "linkedin-draft"


@dataclass(frozen=True)
class LinkedinBridgeSettings:
    enabled: bool
    recipient: str
    token_secret: str
    authorized_sender: str = ""
    folder: str = "INBOX"
    inbox: str = ""
    output: str = ""
    sync_limit: int = 50
    download_pdf: bool = True
    max_pdf_mb: int = 30


def load_linkedin_settings(path):
    config = _load_config(path)
    if not config.has_section("linkedin"):
        return None
    try:
        enabled = config.getboolean("linkedin", "enabled", fallback=False)
    except ValueError:
        raise ValueError("Option linkedin.enabled invalide.") from None
    if not enabled:
        return None
    recipient = config.get("linkedin", "recipient", fallback="").strip()
    if not recipient:
        recipient = config.get("imap", "username", fallback="").strip()
    if not recipient:
        raise ValueError("Option linkedin.recipient absente de la configuration.")
    authorized_sender = config.get(
        "linkedin", "authorized_sender", fallback=""
    ).strip()
    if not authorized_sender:
        authorized_sender = config.get("digest", "recipient", fallback="").strip()
    folder = config.get("linkedin", "folder", fallback="INBOX").strip() or "INBOX"
    inbox = config.get("linkedin", "inbox", fallback="").strip()
    if not inbox and config.has_section("feedback"):
        inbox = config.get("feedback", "inbox", fallback="").strip()
    output = config.get("linkedin", "output", fallback="").strip()
    try:
        sync_limit = config.getint("linkedin", "sync_limit", fallback=50)
    except ValueError:
        raise ValueError("Option linkedin.sync_limit invalide.") from None
    if sync_limit < 1 or sync_limit > 1000:
        raise ValueError("La limite LinkedIn doit être comprise entre 1 et 1000.")
    try:
        download_pdf = config.getboolean("linkedin", "download_pdf", fallback=True)
    except ValueError:
        raise ValueError("Option linkedin.download_pdf invalide.") from None
    try:
        max_pdf_mb = config.getint("linkedin", "max_pdf_mb", fallback=30)
    except ValueError:
        raise ValueError("Option linkedin.max_pdf_mb invalide.") from None
    if max_pdf_mb < 1 or max_pdf_mb > 200:
        raise ValueError("La taille PDF maximale doit être comprise entre 1 et 200 Mo.")
    return LinkedinBridgeSettings(
        enabled=True,
        recipient=recipient,
        token_secret=_secret(config, "linkedin", "token_secret"),
        authorized_sender=authorized_sender,
        folder=folder,
        inbox=inbox,
        output=output,
        sync_limit=sync_limit,
        download_pdf=download_pdf,
        max_pdf_mb=max_pdf_mb,
    )


def create_linkedin_request_token(publication_identity, secret):
    if not publication_identity or not secret:
        raise ValueError("L’identité et le secret LinkedIn sont obligatoires.")
    data = {
        "publication_identity": publication_identity,
        "purpose": _TOKEN_PURPOSE,
        "v": 1,
    }
    serialized = json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    payload = base64.urlsafe_b64encode(serialized.encode("utf-8")).decode(
        "ascii"
    ).rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return "{}.{}".format(payload, signature)


def linkedin_request_identity(token, secret):
    try:
        payload, supplied_signature = token.rsplit(".", 1)
    except (AttributeError, ValueError):
        raise ValueError("Jeton LinkedIn invalide.") from None
    expected_signature = hmac.new(
        secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise ValueError("Signature du jeton LinkedIn invalide.")
    try:
        padding = "=" * (-len(payload) % 4)
        data = json.loads(
            base64.urlsafe_b64decode(payload + padding).decode("utf-8")
        )
    except (ValueError, UnicodeError):
        raise ValueError("Contenu du jeton LinkedIn invalide.") from None
    if (
        not isinstance(data, dict)
        or data.get("v") != 1
        or data.get("purpose") != _TOKEN_PURPOSE
        or not data.get("publication_identity")
    ):
        raise ValueError("Contenu du jeton LinkedIn invalide.")
    return data["publication_identity"]


def linkedin_request_mailto(publication_identity, title, recipient, secret):
    if not recipient:
        raise ValueError("Le destinataire LinkedIn est obligatoire.")
    display_title = (title or publication_identity).strip()
    if len(display_title) > 80:
        display_title = display_title[:77] + "…"
    subject = "{} {}".format(LINKEDIN_REQUEST_SUBJECT, display_title)
    body = "\n".join(
        (
            "Je demande la préparation de cet article pour LinkedIn.",
            "",
            "Envoyez ce message sans modifier la ligne technique ci-dessous.",
            LINKEDIN_REQUEST_MARKER,
            "token={}".format(
                create_linkedin_request_token(publication_identity, secret)
            ),
            "",
        )
    )
    return "mailto:{}?{}".format(
        recipient,
        urlencode({"subject": subject, "body": body}),
    )
