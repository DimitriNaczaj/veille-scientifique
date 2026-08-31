import base64
import csv
import hashlib
import hmac
import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlencode

from .atomic import atomic_open
from .mail_diagnostics import _load_config, _secret
from .models import PublicationPriority
from .storage import Store


FEEDBACK_MARKER = "VEILLE-FEEDBACK/1"
FEEDBACK_SUBJECT = "[Veille feedback]"
FEEDBACK_PRIORITIES = (
    PublicationPriority.HIGH,
    PublicationPriority.WATCH,
    PublicationPriority.EXCLUDED,
)
_PRIORITY_LABELS = {
    PublicationPriority.HIGH: "Pépite",
    PublicationPriority.WATCH: "Éventuellement",
    PublicationPriority.EXCLUDED: "Écarté",
}


@dataclass(frozen=True)
class FeedbackSettings:
    enabled: bool
    recipient: str
    authorized_sender: str
    folder: str
    inbox: str
    token_secret: str
    sync_limit: int


@dataclass(frozen=True)
class FeedbackImportReport:
    accepted: int
    rejected: int
    ignored: int
    already_processed: int
    warnings: tuple

    def as_dict(self):
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "ignored": self.ignored,
            "already_processed": self.already_processed,
            "warnings": list(self.warnings),
        }


def load_feedback_settings(path):
    config = _load_config(path)
    if not config.has_section("feedback"):
        return None
    try:
        enabled = config.getboolean("feedback", "enabled", fallback=False)
    except ValueError:
        raise ValueError("Option feedback.enabled invalide.") from None
    if not enabled:
        return None
    recipient = config.get("feedback", "recipient", fallback="").strip()
    if not recipient:
        recipient = config.get("imap", "username", fallback="").strip()
    authorized_sender = config.get(
        "feedback", "authorized_sender", fallback=""
    ).strip()
    if not authorized_sender:
        authorized_sender = config.get("digest", "recipient", fallback="").strip()
    folder = config.get("feedback", "folder", fallback="INBOX").strip() or "INBOX"
    inbox = config.get("feedback", "inbox", fallback="").strip()
    if not recipient:
        raise ValueError("Option feedback.recipient absente de la configuration.")
    if not authorized_sender:
        raise ValueError(
            "Option feedback.authorized_sender absente de la configuration."
        )
    if not inbox:
        raise ValueError("Option feedback.inbox absente de la configuration.")
    try:
        sync_limit = config.getint("feedback", "sync_limit", fallback=50)
    except ValueError:
        raise ValueError("Option feedback.sync_limit invalide.") from None
    if sync_limit < 1 or sync_limit > 1000:
        raise ValueError("La limite feedback doit être comprise entre 1 et 1000.")
    return FeedbackSettings(
        enabled=True,
        recipient=recipient,
        authorized_sender=authorized_sender,
        folder=folder,
        inbox=inbox,
        token_secret=_secret(config, "feedback", "token_secret"),
        sync_limit=sync_limit,
    )


def create_feedback_token(publication_identity, secret):
    if not publication_identity or not secret:
        raise ValueError("L’identité et le secret feedback sont obligatoires.")
    payload = base64.urlsafe_b64encode(
        publication_identity.encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return "{}.{}".format(payload, signature)


def _identity_from_token(token, secret):
    try:
        payload, supplied_signature = token.rsplit(".", 1)
    except ValueError:
        raise ValueError("Jeton de feedback invalide.") from None
    expected_signature = hmac.new(
        secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise ValueError("Signature du feedback invalide.")
    try:
        padding = "=" * (-len(payload) % 4)
        identity = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
    except (ValueError, UnicodeError):
        raise ValueError("Identité du feedback invalide.") from None
    if not identity:
        raise ValueError("Identité du feedback vide.")
    return identity


def feedback_mailto(publication_identity, title, priority, settings):
    if priority not in FEEDBACK_PRIORITIES:
        raise ValueError("Qualification de feedback invalide.")
    label = _PRIORITY_LABELS[priority]
    display_title = (title or publication_identity).strip()
    if len(display_title) > 80:
        display_title = display_title[:77] + "…"
    subject = "{} {} — {}".format(FEEDBACK_SUBJECT, label, display_title)
    body = "\n".join(
        (
            "Je confirme la requalification de cet article en « {} ».".format(label),
            "",
            "Envoyez ce message sans modifier les lignes techniques ci-dessous.",
            FEEDBACK_MARKER,
            "choice={}".format(priority.value),
            "token={}".format(
                create_feedback_token(publication_identity, settings.token_secret)
            ),
            "",
        )
    )
    return "mailto:{}?{}".format(
        settings.recipient,
        urlencode({"subject": subject, "body": body}),
    )


def _plain_body(message):
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() != "text/plain":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            return part.get_content()
        return ""
    if message.get_content_type() != "text/plain":
        return ""
    return message.get_content()


def _field(body, name):
    match = re.search(r"^{}=([^\r\n]+)$".format(re.escape(name)), body, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _message_identity(message, raw):
    message_id = str(message.get("Message-ID") or "").strip()
    if message_id:
        return message_id
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def run_feedback_import(inbox, database, authorized_sender, token_secret):
    inbox_path = Path(inbox)
    if not inbox_path.exists() or not inbox_path.is_dir():
        raise ValueError("Le dossier feedback n’existe pas : {}".format(inbox_path))
    accepted = 0
    rejected = 0
    ignored = 0
    already_processed = 0
    warnings = []
    store = Store(database)
    try:
        for message_path in sorted(inbox_path.glob("*.eml")):
            raw = message_path.read_bytes()
            message = BytesParser(policy=policy.default).parsebytes(raw)
            identity = _message_identity(message, raw)
            if store.has_feedback_message(identity):
                already_processed += 1
                continue
            sender = parseaddr(str(message.get("From") or ""))[1].strip()
            body = _plain_body(message)
            subject = str(message.get("Subject") or "")
            is_feedback = FEEDBACK_MARKER in body or FEEDBACK_SUBJECT in subject
            if not is_feedback:
                store.record_feedback_message(
                    identity,
                    message_path,
                    sender,
                    status="ignored",
                    reason="Message sans marqueur feedback.",
                )
                ignored += 1
                continue
            try:
                if sender.casefold() != authorized_sender.casefold():
                    raise ValueError("Expéditeur non autorisé : {}.".format(sender or "absent"))
                choice = _field(body, "choice")
                if choice not in {priority.value for priority in FEEDBACK_PRIORITIES}:
                    raise ValueError("Qualification de feedback invalide.")
                token = _field(body, "token")
                publication_identity = _identity_from_token(token, token_secret)
                if not store.has_publication(publication_identity):
                    raise ValueError("Publication inconnue : {}.".format(publication_identity))
                store.record_feedback_message(
                    identity,
                    message_path,
                    sender,
                    status="accepted",
                    publication_identity=publication_identity,
                    priority=choice,
                    received_at=str(message.get("Date") or "").strip() or None,
                )
                accepted += 1
            except ValueError as error:
                reason = str(error)
                store.record_feedback_message(
                    identity,
                    message_path,
                    sender,
                    status="rejected",
                    reason=reason,
                    received_at=str(message.get("Date") or "").strip() or None,
                )
                rejected += 1
                warnings.append("{}: {}".format(message_path.name, reason))
    finally:
        store.close()
    return FeedbackImportReport(
        accepted=accepted,
        rejected=rejected,
        ignored=ignored,
        already_processed=already_processed,
        warnings=tuple(warnings),
    )


def export_feedback_csv(database, output):
    store = Store(database)
    try:
        rows = store.feedback_export_rows()
    finally:
        store.close()
    fieldnames = (
        "feedback_id",
        "publication_identity",
        "title",
        "abstract",
        "ai_priority",
        "ai_model",
        "ai_prompt_version",
        "ai_interest_score",
        "ai_classification_reason",
        "user_priority",
        "sender",
        "received_at",
        "recorded_at",
    )
    with atomic_open(output, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return {
        "service": "feedback-export",
        "status": "ok",
        "feedback_count": len(rows),
        "output": str(output),
        "warnings": [],
        "errors": [],
    }
