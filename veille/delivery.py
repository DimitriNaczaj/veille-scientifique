import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

from .mail_diagnostics import (
    MailDiagnosticError,
    _load_config,
    _safe_error,
    create_tls_context,
    load_smtp_settings,
)


_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
_RELATED_IMAGES = (
    ("bellegarde-logo-black", "logo-baseline-black.png"),
    ("bellegarde-logo-white", "logo-baseline-white.png"),
)


@dataclass(frozen=True)
class DigestDeliverySettings:
    recipient: str
    from_address: str
    subject_prefix: str


def load_digest_delivery_settings(path):
    config = _load_config(path)
    if not config.has_section("digest"):
        raise ValueError("Section [digest] absente de la configuration.")
    recipient = config.get("digest", "recipient", fallback="").strip()
    if not recipient:
        raise ValueError("Option digest.recipient absente de la configuration.")
    smtp = load_smtp_settings(path)
    if recipient.casefold() == smtp.test_recipient.casefold():
        raise ValueError(
            "Le destinataire du digest doit être distinct du destinataire de test SMTP."
        )
    return DigestDeliverySettings(
        recipient=recipient,
        from_address=(
            config.get("digest", "from_address", fallback=smtp.from_address).strip()
            or smtp.from_address
        ),
        subject_prefix=(
            config.get(
                "digest",
                "subject_prefix",
                fallback="Veille scientifique Bellegarde",
            ).strip()
            or "Veille scientifique Bellegarde"
        ),
    )


def _publication_url(publication):
    if publication.doi:
        return "https://doi.org/" + quote(publication.doi, safe="/")
    return publication.url or ""


def _plain_digest(publications):
    lines = ["Veille quotidienne", ""]
    for publication in publications:
        lines.append(publication.title or publication.doi or "Publication sans titre")
        if publication.summary_fr:
            lines.append(publication.summary_fr)
        if publication.bellegarde_value:
            lines.append("Intérêts : " + publication.bellegarde_value)
        url = _publication_url(publication)
        if url:
            lines.append(url)
        lines.append("")
    return "\n".join(lines)


def _add_related_images(message, html):
    html_part = message.get_body(preferencelist=("html",))
    for content_id, filename in _RELATED_IMAGES:
        if "cid:" + content_id not in html:
            continue
        path = _ASSET_DIR / filename
        if not path.is_file():
            raise FileNotFoundError("Logo de newsletter absent : {}".format(filename))
        html_part.add_related(
            path.read_bytes(),
            maintype="image",
            subtype="png",
            cid="<{}>".format(content_id),
            filename=filename,
            disposition="inline",
        )


class SMTPDigestSender:
    def __init__(self, config_path, smtp_factory=None, subject_prefix=None):
        self.config_path = config_path
        self.smtp_factory = smtp_factory or smtplib.SMTP
        self.subject_prefix = subject_prefix
        self.sent = False
        self.recipient = None

    def send(self, digest_path, publications):
        publications = tuple(publications)
        if not publications:
            self.sent = False
            return
        smtp = load_smtp_settings(self.config_path)
        digest = load_digest_delivery_settings(self.config_path)
        html = Path(digest_path).read_text(encoding="utf-8")
        message = EmailMessage()
        message["From"] = digest.from_address
        message["To"] = digest.recipient
        article_count = (
            "1 article"
            if len(publications) == 1
            else "{} articles".format(len(publications))
        )
        message["Subject"] = "{} — {} — {}".format(
            self.subject_prefix or digest.subject_prefix,
            date.today().isoformat(),
            article_count,
        )
        message.set_content(_plain_digest(publications))
        message.add_alternative(html, subtype="html")
        _add_related_images(message, html)
        client = None
        try:
            client = self.smtp_factory(smtp.host, smtp.port, timeout=30)
            client.ehlo()
            client.starttls(context=create_tls_context())
            client.ehlo()
            client.login(smtp.username, smtp.password)
            client.send_message(message)
            self.sent = True
            self.recipient = digest.recipient
        except Exception as error:
            raise MailDiagnosticError(_safe_error(error, smtp.password)) from None
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    pass
