"""Importe les demandes signées du digest dans la préparation LinkedIn."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path

from .article_pdf import PdfUnavailableError
from .atomic import atomic_open
from .feedback import (
    _feedback_message_sort_key,
    _field,
    _message_identity,
    _plain_body,
)
from .linkedin_bridge import (
    LINKEDIN_REQUEST_MARKER,
    LINKEDIN_REQUEST_SUBJECT,
    linkedin_request_identity,
)
from .storage import Store


@dataclass(frozen=True)
class LinkedinImportReport:
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


def _slug(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")[:64] or "article"


def _single_line(value):
    return re.sub(r"\s+", " ", value or "").strip()


def _article_for_identity(store, identity):
    article = next(
        (item for item in store.catalog_publications() if item.identity == identity),
        None,
    )
    if article is None:
        raise ValueError("Publication inconnue : {}.".format(identity))
    return article, store.load_latest_ai_assessment(identity)


def _source_document(article, analysis):
    lines = [
        "# Article issu de la veille scientifique",
        "",
        "- Identité : `{}`".format(article.identity),
        "- Titre : {}".format(article.title or "Non renseigné"),
        "- DOI : {}".format(article.doi or "Non renseigné"),
        "- URL : {}".format(article.url or "Non renseignée"),
        "- Revue : {}".format(article.journal or "Non renseignée"),
        "- Date de publication : {}".format(
            article.published_date or "Non renseignée"
        ),
        "- Auteurs : {}".format(
            ", ".join(article.authors) or "Non renseignés"
        ),
        "- Auteurs JSON : {}".format(
            json.dumps(article.authors, ensure_ascii=False)
        ),
        "",
        "## Résumé scientifique",
        "",
        article.abstract or "Non renseigné.",
        "",
        "## Synthèse de la veille",
        "",
        analysis.summary_fr if analysis is not None else "Non renseignée.",
        "",
        "## Intérêt pour Bellegarde",
        "",
        analysis.bellegarde_value if analysis is not None else "Non renseigné.",
        "",
        "## Applications envisagées",
        "",
    ]
    applications = analysis.applications if analysis is not None else ()
    lines.extend("- {}".format(item) for item in applications)
    if not applications:
        lines.append("- Non renseignées.")
    lines.extend(("", "## Thèmes", ""))
    themes = analysis.themes if analysis is not None else ()
    lines.extend("- {}".format(item) for item in themes)
    if not themes:
        lines.append("- Non renseignés.")
    lines.extend(
        (
            "",
            "## Contrôle de la veille",
            "",
            "- Qualité des preuves : {}".format(
                analysis.evidence_quality if analysis is not None else "Non renseignée"
            ),
            "- Motif du classement : {}".format(
                analysis.classification_reason
                if analysis is not None
                else "Non renseigné"
            ),
            "",
        )
    )
    return "\n".join(lines)


def _brief_document(article):
    return "\n".join(
        (
            "# Brief LinkedIn",
            "",
            "Article proposé : {}".format(
                _single_line(article.title or article.identity)
            ),
            "",
            "## Direction",
            "",
            "Présenter les résultats principaux de l’article à partir de son texte "
            "intégral. Expliquer la méthode et les limites utiles à l’interprétation. "
            "Citer au maximum les trois premiers auteurs par leur nom. Ne demander "
            "un tag cliquable que si une identité LinkedIn a été vérifiée.",
            "",
            "## Paramètres",
            "",
            "- Canal : page",
            "- Langue : français",
            "- Format : texte",
            "- Date souhaitée : à définir",
            "- Objectif : relayer une actualité scientifique utile aux activités de Bellegarde",
            "",
            "## Garde-fous",
            "",
            "- Utiliser uniquement les informations présentes dans les sources.",
            "- Ne pas inventer de faits, de résultats ou de recommandations.",
            "- Ne rien publier avant le déplacement manuel vers « 02 - À PUBLIER ».",
            "",
        )
    )


def _write_text(path, content):
    with atomic_open(path, "w", encoding="utf-8") as stream:
        stream.write(content)


def _write_package(
    output,
    destination,
    article,
    analysis,
    raw_message,
    pdf_fetcher=None,
):
    if output.is_symlink():
        raise ValueError("Le dossier LinkedIn ne peut pas être un lien symbolique.")
    output.mkdir(parents=True, exist_ok=True)
    if destination.parent.resolve() != output.resolve():
        raise ValueError("La destination LinkedIn sort du dossier de préparation.")
    if destination.exists():
        source = destination / "sources" / "article-de-veille.md"
        if destination.is_dir() and source.is_file():
            if "`{}`".format(article.identity) in source.read_text(encoding="utf-8"):
                return destination, None
        raise ValueError(
            "Destination LinkedIn déjà occupée : {}.".format(destination.name)
        )
    temporary = Path(tempfile.mkdtemp(prefix=".import-", dir=str(output)))
    pdf_warning = None
    try:
        (temporary / "sources").mkdir()
        (temporary / "media").mkdir()
        _write_text(temporary / "brief.md", _brief_document(article))
        _write_text(
            temporary / "sources" / "article-de-veille.md",
            _source_document(article, analysis),
        )
        with atomic_open(temporary / "sources" / "demande.eml", "wb") as stream:
            stream.write(raw_message)
        if pdf_fetcher is not None:
            try:
                retrieval = pdf_fetcher.fetch(
                    article.doi,
                    temporary / "sources" / "article.pdf",
                )
                _write_text(
                    temporary / "sources" / "pdf-origin.json",
                    json.dumps(
                        {
                            "doi": article.doi,
                            "source_url": retrieval.source_url,
                            "license": retrieval.license,
                            "sha256": retrieval.sha256,
                            "size_bytes": retrieval.size_bytes,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(
                                timespec="seconds"
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                )
            except PdfUnavailableError as error:
                pdf_warning = str(error)
                _write_text(
                    temporary / "PDF-À-AJOUTER.md",
                    "# PDF nécessaire\n\n"
                    "Le texte intégral n’a pas pu être récupéré automatiquement. "
                    "Déposez une copie autorisée dans `sources/article.pdf`.\n\n"
                    "Motif : {}\n".format(pdf_warning),
                )
        os.replace(str(temporary), str(destination))
    except Exception:
        shutil.rmtree(str(temporary), ignore_errors=True)
        raise
    return destination, pdf_warning


def _quarantine_duplicate_packages(store, output):
    if output.is_symlink():
        raise ValueError("Le dossier LinkedIn ne peut pas être un lien symbolique.")
    for message_identity, destination_value, reason in (
        store.linkedin_duplicate_destinations()
    ):
        destination = Path(destination_value)
        if destination.parent.resolve() != output.resolve() or not destination.exists():
            continue
        errors = output.parent / "04 - ERREURS"
        if errors.is_symlink():
            raise ValueError("Le dossier d’erreurs LinkedIn est un lien symbolique.")
        errors.mkdir(parents=True, exist_ok=True)
        _write_text(
            destination / "error.md",
            "# Publication bloquée\n\n{}\n".format(
                reason or "Cet article existe déjà dans un autre dossier."
            ),
        )
        target = errors / destination.name
        suffix = 2
        while target.exists():
            target = errors / "{}-{}".format(destination.name, suffix)
            suffix += 1
        os.replace(str(destination), str(target))
        store.update_linkedin_request_destination(message_identity, target)


def run_linkedin_import(
    inbox,
    database,
    output,
    authorized_sender,
    token_secret,
    pdf_fetcher=None,
):
    inbox_path = Path(inbox)
    output_path = Path(output)
    if inbox_path.is_symlink() or not inbox_path.is_dir():
        raise ValueError("Le dossier de relève LinkedIn est absent ou symbolique.")
    if output_path.is_symlink():
        raise ValueError("Le dossier LinkedIn ne peut pas être un lien symbolique.")
    if not authorized_sender.strip():
        raise ValueError("L’expéditeur LinkedIn autorisé est absent.")
    if not token_secret:
        raise ValueError("Le secret LinkedIn est absent.")
    accepted = 0
    rejected = 0
    ignored = 0
    already_processed = 0
    warnings = []
    store = Store(database)
    try:
        _quarantine_duplicate_packages(store, output_path)
        for message_path in sorted(
            inbox_path.glob("*.eml"), key=_feedback_message_sort_key
        ):
            raw = b""
            identity = ""
            sender = ""
            publication_identity = None
            reserved = False
            try:
                raw = message_path.read_bytes()
                message = BytesParser(policy=policy.default).parsebytes(raw)
                identity = _message_identity(message, raw)
                state = store.linkedin_request(identity)
                if state is not None and state["status"] != "pending":
                    already_processed += 1
                    continue
                sender = parseaddr(str(message.get("From") or ""))[1].strip()
                subject = str(message.get("Subject") or "")
                body = _plain_body(message)
                is_request = (
                    LINKEDIN_REQUEST_MARKER in body
                    or LINKEDIN_REQUEST_SUBJECT in subject
                )
                if not is_request:
                    store.record_linkedin_request_message(
                        identity,
                        message_path,
                        sender,
                        "ignored",
                        "Message sans marqueur LinkedIn.",
                        received_at=str(message.get("Date") or "").strip() or None,
                    )
                    ignored += 1
                    continue
                if sender.casefold() != authorized_sender.strip().casefold():
                    raise ValueError(
                        "Expéditeur non autorisé : {}.".format(sender or "absent")
                    )
                publication_identity = linkedin_request_identity(
                    _field(body, "token"), token_secret
                )
                article, analysis = _article_for_identity(store, publication_identity)
                date = datetime.now(timezone.utc).date().isoformat()
                suffix = hashlib.sha256(
                    publication_identity.encode("utf-8")
                ).hexdigest()[:10]
                destination = output_path / "{}-{}-{}".format(
                    date,
                    _slug(article.title or article.identity),
                    suffix,
                )
                if state is not None and state["status"] == "pending":
                    if state["publication_identity"] != publication_identity:
                        raise ValueError(
                            "L’identité signée ne correspond plus à la demande réservée."
                        )
                    destination = Path(state["destination"])
                    if destination.parent.resolve() != output_path.resolve():
                        if destination.exists():
                            raise ValueError(
                                "La destination réservée sort du dossier LinkedIn actuel."
                            )
                        destination = output_path / "{}-{}-{}".format(
                            date,
                            _slug(article.title or article.identity),
                            suffix,
                        )
                        store.update_pending_linkedin_destination(
                            identity, destination
                        )
                status = store.reserve_linkedin_request(
                    identity,
                    message_path,
                    sender,
                    publication_identity,
                    destination,
                    received_at=str(message.get("Date") or "").strip() or None,
                )
                if status in ("accepted", "duplicate", "ignored", "rejected"):
                    already_processed += 1
                    continue
                reserved = True
                destination, pdf_warning = _write_package(
                    output_path,
                    destination,
                    article,
                    analysis,
                    raw,
                    pdf_fetcher=pdf_fetcher,
                )
                store.complete_linkedin_request(identity, destination)
                accepted += 1
                if pdf_warning:
                    warnings.append(
                        "{}: {}".format(message_path.name, pdf_warning)
                    )
            except Exception as error:
                if not identity:
                    identity = "sha256:" + hashlib.sha256(
                        raw or str(message_path).encode("utf-8")
                    ).hexdigest()
                reason = str(error)
                if reserved:
                    store.note_linkedin_request_error(identity, reason)
                else:
                    store.record_linkedin_request_message(
                        identity,
                        message_path,
                        sender,
                        "rejected",
                        reason,
                        publication_identity=publication_identity,
                    )
                rejected += 1
                warnings.append("{}: {}".format(message_path.name, reason))
    finally:
        store.close()
    return LinkedinImportReport(
        accepted=accepted,
        rejected=rejected,
        ignored=ignored,
        already_processed=already_processed,
        warnings=tuple(warnings),
    )
