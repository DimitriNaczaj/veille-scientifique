import os
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

from .models import PublicationPriority


def _publication_html(publication):
    title = escape(publication.title or publication.doi or "Publication sans titre")
    source_subject = escape(publication.source_subject)
    source_sender = escape(publication.source_sender)
    details = []
    if publication.journal:
        details.append(escape(publication.journal))
    if publication.published_date:
        details.append(escape(publication.published_date))
    bibliographic = ""
    if details:
        bibliographic = '<p class="bibliographic">{}</p>'.format(" — ".join(details))
    authors = ""
    if publication.authors:
        authors = '<p class="authors">{}</p>'.format(
            escape(", ".join(publication.authors))
        )
    abstract = ""
    if publication.abstract:
        abstract = '<p class="abstract"><strong>Abstract :</strong> {}</p>'.format(
            escape(publication.abstract)
        )
    relevance = ""
    if publication.relevance_reasons:
        relevance = '<p class="relevance"><strong>Repéré pour :</strong> {}</p>'.format(
            escape(", ".join(publication.relevance_reasons))
        )
    if publication.doi:
        doi = escape(publication.doi)
        url = escape(
            "https://doi.org/" + quote(publication.doi, safe="/"), quote=True
        )
        metadata = "<p><strong>DOI :</strong> {}</p>".format(doi)
    else:
        url = escape(publication.url or "#", quote=True)
        metadata = (
            '<p class="provisional">Référence extraite sans DOI — enrichissement requis.</p>'
        )
    return (
        "<article>"
        '<h2><a href="{url}">{title}</a></h2>'
        "{bibliographic}"
        "{authors}"
        "{abstract}"
        "{relevance}"
        "{metadata}"
        '<p class="source">Signalé dans « {subject} » — {sender}</p>'
        "</article>"
    ).format(
        url=url,
        title=title,
        bibliographic=bibliographic,
        authors=authors,
        abstract=abstract,
        relevance=relevance,
        metadata=metadata,
        subject=source_subject,
        sender=source_sender,
    )


def render_digest(publications, total_count=None, excluded_count=0):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if total_count is None:
        total_count = len(publications)
    filtered = excluded_count > 0 or any(
        publication.priority is not PublicationPriority.UNFILTERED
        for publication in publications
    )
    if publications:
        if filtered:
            sections = []
            for priority in (
                PublicationPriority.HIGH,
                PublicationPriority.WATCH,
            ):
                articles = tuple(
                    publication
                    for publication in publications
                    if publication.priority == priority
                )
                if articles:
                    sections.append(
                        '<section><h2 class="section-title">{}</h2>{}</section>'.format(
                            priority.heading,
                            "".join(_publication_html(article) for article in articles),
                        )
                    )
            body = "".join(sections)
        else:
            body = "".join(_publication_html(publication) for publication in publications)
        if filtered:
            summary = (
                "{} publication(s) retenue(s) sur {} analysée(s) ; {} écartée(s)."
            ).format(len(publications), total_count, excluded_count)
        else:
            summary = "{} nouvelle(s) publication(s) détectée(s).".format(
                len(publications)
            )
    else:
        if excluded_count:
            body = (
                '<p class="empty">Aucune publication pertinente retenue pour cette édition.</p>'
            )
            summary = "0 publication retenue sur {} analysée(s) ; {} écartée(s).".format(
                total_count, excluded_count
            )
        else:
            body = '<p class="empty">Aucune nouvelle publication détectée.</p>'
            summary = "Aucune nouvelle publication."

    return """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Veille scientifique Bellegarde</title>
  <style>
    body {{ margin: 0; background: #f4f1eb; color: #1d2a26; font: 16px/1.55 Arial, sans-serif; }}
    main {{ max-width: 720px; margin: 0 auto; padding: 40px 24px 64px; }}
    header {{ border-bottom: 3px solid #b76e3f; margin-bottom: 28px; padding-bottom: 18px; }}
    h1 {{ margin: 0 0 8px; font-family: Georgia, serif; font-size: 32px; }}
    h2 {{ font: 700 20px/1.3 Georgia, serif; margin: 0 0 12px; }}
    .section-title {{ font-size: 24px; margin: 30px 0 14px; }}
    a {{ color: #8c462d; }}
    article {{ background: white; border-radius: 8px; margin: 0 0 18px; padding: 22px; }}
    article p {{ margin: 6px 0; }}
    .source, footer {{ color: #65716d; font-size: 14px; }}
    .provisional {{ color: #8c6a22; font-size: 14px; }}
    .bibliographic, .authors, .relevance {{ color: #4f5d58; font-size: 14px; }}
    .abstract {{ margin-top: 14px; }}
    .empty {{ background: white; border-radius: 8px; padding: 22px; }}
    footer {{ margin-top: 30px; }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Veille scientifique Bellegarde</h1>
    <p>{summary}</p>
  </header>
  {body}
  <footer>Digest généré automatiquement le {now}. Métadonnées enrichies via Crossref lorsqu’elles sont disponibles.</footer>
</main>
</body>
</html>
""".format(summary=escape(summary), body=body, now=escape(now))


def write_digest(path, publications, total_count=None, excluded_count=0):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix="." + destination.name + ".",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(
                render_digest(
                    publications,
                    total_count=total_count,
                    excluded_count=excluded_count,
                )
            )
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(str(temporary_path), str(destination))
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
        raise
