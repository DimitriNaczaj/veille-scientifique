import os
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path


def _publication_html(publication):
    title = escape(publication.title or publication.doi)
    doi = escape(publication.doi)
    source_subject = escape(publication.source_subject)
    source_sender = escape(publication.source_sender)
    url = "https://doi.org/" + doi
    return (
        "<article>"
        '<h2><a href="{url}">{title}</a></h2>'
        "<p><strong>DOI :</strong> {doi}</p>"
        '<p class="source">Signalé dans « {subject} » — {sender}</p>'
        "</article>"
    ).format(
        url=url,
        title=title,
        doi=doi,
        subject=source_subject,
        sender=source_sender,
    )


def render_digest(publications):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if publications:
        body = "".join(_publication_html(publication) for publication in publications)
        summary = "{} nouvelle(s) publication(s) détectée(s).".format(len(publications))
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
    a {{ color: #8c462d; }}
    article {{ background: white; border-radius: 8px; margin: 0 0 18px; padding: 22px; }}
    article p {{ margin: 6px 0; }}
    .source, footer {{ color: #65716d; font-size: 14px; }}
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
  <footer>Digest généré automatiquement le {now}. Premier incrément : métadonnées issues des newsletters, à confirmer par Crossref.</footer>
</main>
</body>
</html>
""".format(summary=escape(summary), body=body, now=escape(now))


def write_digest(path, publications):
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
            temporary.write(render_digest(publications))
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
