"""Historique lisible des digests envoyés.

Le tri n’est pas reproductible : une requalification ultérieure réécrit le
verdict courant d’un article. L’historique conserve donc la catégorie et la
note telles qu’elles étaient le jour de l’envoi, ce qui permet de relire une
campagne sans la rejouer.
"""
import csv
from html import escape

from .atomic import atomic_open
from .storage import Store


_PRIORITY_LABELS = {
    "high": "Pépite",
    "watch": "Éventuellement",
    "excluded": "Écarté",
}
_PRIORITY_ORDER = ("high", "watch", "excluded")

CSV_FIELDNAMES = (
    "run_id",
    "kind",
    "sent_at",
    "sent",
    "recipient",
    "position",
    "priority",
    "interest_score",
    "title",
    "journal",
    "published_date",
    "doi",
)


def _label(priority):
    return _PRIORITY_LABELS.get(priority, priority or "—")


def collect_history(database, limit=200):
    store = Store(database)
    try:
        runs = store.digest_history_runs(limit)
        articles = store.digest_history_articles([row[0] for row in runs])
    finally:
        store.close()
    by_run = {}
    for run_id, priority, score, position, title, doi, journal, date in articles:
        by_run.setdefault(run_id, []).append(
            {
                "priority": priority,
                "interest_score": score,
                "position": position,
                "title": title,
                "doi": doi,
                "journal": journal,
                "published_date": date,
            }
        )
    return [
        {
            "run_id": run[0],
            "kind": run[1],
            "subject": run[2],
            "recipient": run[3],
            "sent": bool(run[4]),
            "retained_count": run[5],
            "total_count": run[6],
            "sent_at": run[7],
            "articles": by_run.get(run[0], []),
        }
        for run in runs
    ]


def _csv_rows(history):
    for run in history:
        for article in run["articles"]:
            yield {
                "run_id": run["run_id"],
                "kind": run["kind"],
                "sent_at": run["sent_at"],
                "sent": "oui" if run["sent"] else "non",
                "recipient": run["recipient"],
                "position": article["position"],
                "priority": article["priority"],
                "interest_score": article["interest_score"],
                "title": article["title"] or "",
                "journal": article["journal"] or "",
                "published_date": article["published_date"] or "",
                "doi": article["doi"] or "",
            }


def write_history_csv(path, history):
    with atomic_open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(_csv_rows(history))


def _article_html(article):
    doi = article["doi"]
    title = escape(article["title"] or "Publication sans titre")
    if doi:
        title = '<a href="https://doi.org/{}">{}</a>'.format(
            escape(doi, quote=True), title
        )
    details = " – ".join(
        escape(value)
        for value in (article["journal"], article["published_date"])
        if value
    )
    return (
        '<tr><td class="pos">{position}</td>'
        '<td><span class="tag {priority}">{label}</span></td>'
        '<td class="score">{score}</td>'
        '<td class="title">{title}{details}</td></tr>'
    ).format(
        position=article["position"],
        priority=escape(article["priority"]),
        label=escape(_label(article["priority"])),
        score=article["interest_score"] or "—",
        title=title,
        details=(
            '<span class="details">{}</span>'.format(details) if details else ""
        ),
    )


def _run_html(run):
    counts = {}
    for article in run["articles"]:
        counts[article["priority"]] = counts.get(article["priority"], 0) + 1
    summary = " · ".join(
        "{} {}".format(counts[priority], _label(priority).lower())
        for priority in _PRIORITY_ORDER
        if counts.get(priority)
    )
    return """
  <section class="run">
    <header>
      <div class="meta"><span class="kind">{kind}</span><span>{sent_at}</span>{state}</div>
      <h2>{count} article{plural}{summary}</h2>
      {recipient}
    </header>
    <table><tbody>{rows}</tbody></table>
  </section>""".format(
        kind=escape(run["kind"]),
        sent_at=escape(run["sent_at"]),
        state=(
            ""
            if run["sent"]
            else '<span class="warn">non envoyé</span>'
        ),
        count=run["retained_count"],
        plural="s" if run["retained_count"] > 1 else "",
        summary=" — " + escape(summary) if summary else "",
        recipient=(
            '<p class="to">vers {}</p>'.format(escape(run["recipient"]))
            if run["recipient"]
            else ""
        ),
        rows="".join(_article_html(a) for a in run["articles"]),
    )


_STYLE = """
:root{--ground:#F4F2F1;--surface:#fff;--ink:#1D1D1F;--muted:#7A777D;--rule:#E4E1DE;
--high:#2C4A39;--high-bg:#E2F5EA;--watch:#57555A;--watch-bg:#F1F1F1;
--excluded:#8A3434;--excluded-bg:#FBEAEA;--warn:#8A6212}
@media (prefers-color-scheme:dark){:root{--ground:#161517;--surface:#1F1E21;--ink:#EDEBEC;
--muted:#98949A;--rule:#333136;--high:#7FD3AE;--high-bg:#17302A;--watch:#B4B0B8;--watch-bg:#26252A;
--excluded:#E29A9A;--excluded-bg:#33201F;--warn:#DFAE55}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
font-size:15px;line-height:1.55}
.wrap{max-width:900px;margin:0 auto;padding:40px 22px 80px}
h1{font-size:28px;line-height:1.15;margin:0 0 6px;letter-spacing:-.01em}
.lede{color:var(--muted);margin:0 0 30px}
.run{background:var(--surface);border:1px solid var(--rule);border-radius:12px;
padding:20px 22px;margin-bottom:18px}
.run header{border-bottom:1px solid var(--rule);padding-bottom:14px;margin-bottom:8px}
.meta{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:11px;
letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
.kind{color:var(--ink);font-weight:700}
.warn{color:var(--warn);font-weight:700}
.run h2{font-size:17px;margin:0;font-weight:600}
.to{margin:6px 0 0;font-size:13px;color:var(--muted)}
table{width:100%;border-collapse:collapse}
td{padding:9px 8px;border-bottom:1px solid var(--rule);vertical-align:top}
tr:last-child td{border-bottom:0}
.pos{width:28px;color:var(--muted);font-variant-numeric:tabular-nums;font-size:13px}
.score{width:44px;text-align:right;font-variant-numeric:tabular-nums;color:var(--muted);font-size:13px}
.tag{display:inline-block;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap}
.tag.high{background:var(--high-bg);color:var(--high)}
.tag.watch{background:var(--watch-bg);color:var(--watch)}
.tag.excluded{background:var(--excluded-bg);color:var(--excluded)}
.title a{color:inherit;text-decoration:none;border-bottom:1px solid var(--rule)}
.title a:hover{border-color:currentColor}
.details{display:block;color:var(--muted);font-size:12.5px;margin-top:2px}
.empty{background:var(--surface);border:1px solid var(--rule);border-radius:12px;
padding:28px;color:var(--muted)}
"""


def render_history(history):
    if history:
        body = "".join(_run_html(run) for run in history)
        total = sum(run["retained_count"] for run in history)
        lede = "{} envoi{} · {} article{} diffusé{}".format(
            len(history),
            "s" if len(history) > 1 else "",
            total,
            "s" if total > 1 else "",
            "s" if total > 1 else "",
        )
    else:
        body = '<p class="empty">Aucun digest enregistré pour l’instant.</p>'
        lede = "L’historique se remplit à partir du premier envoi."
    return """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Historique des digests</title>
<style>{style}</style>
</head>
<body>
<div class="wrap">
  <h1>Historique des digests</h1>
  <p class="lede">{lede}</p>
  {body}
</div>
</body>
</html>
""".format(style=_STYLE, lede=escape(lede), body=body)


def export_digest_history(database, output, limit=200, csv_output=None):
    if limit < 1 or limit > 5000:
        raise ValueError("La limite d’historique doit être comprise entre 1 et 5 000.")
    history = collect_history(database, limit)
    with atomic_open(output, "w", encoding="utf-8") as stream:
        stream.write(render_history(history))
    if csv_output:
        write_history_csv(csv_output, history)
    return {
        "service": "digest-history",
        "status": "ok",
        "run_count": len(history),
        "article_count": sum(run["retained_count"] for run in history),
        "output": str(output),
        "csv_output": str(csv_output) if csv_output else "",
        "warnings": [],
        "errors": [],
    }
