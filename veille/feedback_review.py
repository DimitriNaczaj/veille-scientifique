"""Analyse des requalifications, en vue de réviser la consigne de tri.

Constater qu’un tri se trompe ne suffit pas à le corriger : encore faut-il
savoir *où*. Ce module confronte le verdict du modèle à celui du consultant,
puis compare les notes par critère selon que la requalification a durci ou
assoupli le classement. Un critère dont la note ne bouge pas entre les deux
sens d’erreur ne discrimine rien et doit être revu dans la consigne.
"""
import csv
from html import escape

from .atomic import atomic_open
from .storage import Store


PRIORITY_ORDER = ("high", "watch", "excluded")
_RANK = {"excluded": 0, "watch": 1, "high": 2}
_LABELS = {"high": "Pépite", "watch": "Éventuellement", "excluded": "Écarté"}
CRITERIA = (
    ("mission_fit_score", "Adéquation à la mission"),
    ("scientific_robustness_score", "Robustesse scientifique"),
    ("actionability_score", "Actionnabilité"),
    ("generalizability_score", "Généralisation"),
    ("novelty_score", "Nouveauté"),
)
MINIMUM_FOR_TREND = 3


def _label(priority):
    return _LABELS.get(priority, priority or "—")


def _direction(row):
    ai, user = _RANK.get(row["ai_priority"]), _RANK.get(row["user_priority"])
    if ai is None or user is None:
        return "inconnu"
    if user > ai:
        return "remonté"
    if user < ai:
        return "abaissé"
    return "confirmé"


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def analyse_feedback(database):
    store = Store(database)
    try:
        rows = list(store.feedback_review_rows())
    finally:
        store.close()
    for row in rows:
        row["direction"] = _direction(row)

    matrix = {}
    for row in rows:
        key = (row["ai_priority"] or "—", row["user_priority"] or "—")
        matrix[key] = matrix.get(key, 0) + 1

    counts = {"confirmé": 0, "remonté": 0, "abaissé": 0, "inconnu": 0}
    for row in rows:
        counts[row["direction"]] = counts.get(row["direction"], 0) + 1

    criteria = []
    for field, label in CRITERIA:
        up = _mean([r[field] for r in rows if r["direction"] == "remonté"])
        down = _mean([r[field] for r in rows if r["direction"] == "abaissé"])
        kept = _mean([r[field] for r in rows if r["direction"] == "confirmé"])
        gap = None if up is None or down is None else up - down
        criteria.append(
            {
                "field": field,
                "label": label,
                "raised": up,
                "lowered": down,
                "confirmed": kept,
                "gap": gap,
            }
        )

    corrected = [r for r in rows if r["direction"] in ("remonté", "abaissé")]
    agreement = (
        (counts["confirmé"] / len(rows)) if rows else None
    )
    enough = len(corrected) >= MINIMUM_FOR_TREND
    return {
        "rows": rows,
        "corrected": corrected,
        "matrix": matrix,
        "counts": counts,
        "criteria": criteria,
        "agreement": agreement,
        "total": len(rows),
        "sufficient": enough,
    }


CSV_FIELDNAMES = (
    "feedback_id",
    "direction",
    "ai_priority",
    "user_priority",
    "prompt_version",
    "interest_score",
    "mission_fit_score",
    "scientific_robustness_score",
    "actionability_score",
    "generalizability_score",
    "novelty_score",
    "evidence_quality",
    "title",
    "journal",
    "classification_reason",
    "recorded_at",
)


def write_review_csv(path, analysis):
    with atomic_open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=CSV_FIELDNAMES, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(analysis["rows"])


def _matrix_html(matrix):
    if not matrix:
        return '<p class="empty">Aucune requalification enregistrée.</p>'
    header = "".join(
        "<th>{}</th>".format(escape(_label(p))) for p in PRIORITY_ORDER
    )
    body = []
    for ai in PRIORITY_ORDER:
        cells = []
        for user in PRIORITY_ORDER:
            count = matrix.get((ai, user), 0)
            # Une case vide reste neutre : colorer une diagonale à zéro
            # laisserait croire à un accord qui n’a pas eu lieu.
            if not count:
                klass = "zero"
            else:
                klass = "diag" if ai == user else "cell"
            cells.append('<td class="{}">{}</td>'.format(klass, count or "·"))
        body.append(
            "<tr><th scope=\"row\">{}</th>{}</tr>".format(
                escape(_label(ai)), "".join(cells)
            )
        )
    return (
        '<table class="matrix"><thead><tr><th></th>'
        '<th colspan="3">Verdict du consultant</th></tr>'
        "<tr><th>Verdict du modèle</th>{}</tr></thead>"
        "<tbody>{}</tbody></table>"
    ).format(header, "".join(body))


def _criteria_html(analysis):
    if not analysis["sufficient"]:
        return (
            '<p class="empty">Moins de {} requalifications : les moyennes par '
            "critère ne seraient pas interprétables.</p>".format(MINIMUM_FOR_TREND)
        )
    rows = []
    for item in sorted(
        analysis["criteria"],
        key=lambda c: (c["gap"] is None, -abs(c["gap"] or 0)),
    ):
        fmt = lambda v: "—" if v is None else "{:.1f}".format(v)
        gap = item["gap"]
        verdict = (
            "—"
            if gap is None
            else ("discrimine" if abs(gap) >= 1 else "ne discrimine pas")
        )
        rows.append(
            "<tr><td>{label}</td><td class=\"n\">{raised}</td>"
            "<td class=\"n\">{lowered}</td><td class=\"n\">{gap}</td>"
            "<td class=\"{klass}\">{verdict}</td></tr>".format(
                label=escape(item["label"]),
                raised=fmt(item["raised"]),
                lowered=fmt(item["lowered"]),
                gap="—" if gap is None else "{:+.1f}".format(gap),
                klass="ok" if verdict == "discrimine" else "warn",
                verdict=verdict,
            )
        )
    return (
        "<table><thead><tr><th>Critère</th><th>Note moyenne si remonté</th>"
        "<th>si abaissé</th><th>Écart</th><th>Lecture</th></tr></thead>"
        "<tbody>{}</tbody></table>"
    ).format("".join(rows))


def _cases_html(analysis):
    if not analysis["corrected"]:
        return '<p class="empty">Aucune correction : le modèle n’a jamais été repris.</p>'
    items = []
    for row in analysis["corrected"]:
        items.append(
            """<article class="case">
      <div class="meta"><span class="dir {dirklass}">{direction}</span>
        <span>{ai} → {user}</span><span>{version}</span></div>
      <h3>{title}</h3>
      {journal}
      {reason}
    </article>""".format(
                direction=escape(row["direction"]),
                dirklass=escape(row["direction"]),
                ai=escape(_label(row["ai_priority"])),
                user=escape(_label(row["user_priority"])),
                version=escape(row["prompt_version"] or "—"),
                title=escape(row["title"] or row["publication_identity"]),
                journal=(
                    '<p class="journal">{}</p>'.format(escape(row["journal"]))
                    if row["journal"]
                    else ""
                ),
                reason=(
                    '<p class="reason">{}</p>'.format(
                        escape(row["classification_reason"])
                    )
                    if row["classification_reason"]
                    else ""
                ),
            )
        )
    return "".join(items)


_STYLE = """
:root{--ground:#F4F2F1;--surface:#fff;--ink:#1D1D1F;--muted:#7A777D;--rule:#E4E1DE;
--ok:#2C4A39;--ok-bg:#E2F5EA;--warn:#8A6212;--warn-bg:#F5ECDA;--down:#8A3434;--down-bg:#FBEAEA;
--accent:#3B3560;--accent-bg:#EDEBF5}
@media (prefers-color-scheme:dark){:root{--ground:#161517;--surface:#1F1E21;--ink:#EDEBEC;
--muted:#98949A;--rule:#333136;--ok:#7FD3AE;--ok-bg:#17302A;--warn:#DFAE55;--warn-bg:#33270F;
--down:#E29A9A;--down-bg:#33201F;--accent:#B8AEE8;--accent-bg:#26233A}}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
font-size:15px;line-height:1.55}
.wrap{max-width:880px;margin:0 auto;padding:40px 22px 80px}
h1{font-size:28px;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:19px;margin:36px 0 12px}
.lede{color:var(--muted);margin:0;max-width:62ch}
.panel{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:20px 22px}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:9px 10px;border-bottom:1px solid var(--rule);text-align:left}
thead th{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.matrix td{text-align:center;font-variant-numeric:tabular-nums}
.matrix .diag{background:var(--ok-bg);color:var(--ok);font-weight:700}
.matrix .cell{background:var(--warn-bg);color:var(--warn);font-weight:700}
.matrix .zero{color:var(--muted)}
td.ok{color:var(--ok);font-weight:600}
td.warn{color:var(--warn);font-weight:600}
.case{background:var(--surface);border:1px solid var(--rule);border-radius:10px;
padding:16px 18px;margin-bottom:12px}
.case h3{font-size:15.5px;margin:6px 0 0;font-weight:600;line-height:1.35}
.meta{display:flex;gap:10px;flex-wrap:wrap;align-items:center;font-size:11px;
letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.dir{padding:3px 9px;border-radius:20px;font-weight:700;letter-spacing:.04em}
.dir.remonté{background:var(--ok-bg);color:var(--ok)}
.dir.abaissé{background:var(--down-bg);color:var(--down)}
.journal{margin:4px 0 0;color:var(--muted);font-size:13px}
.reason{margin:8px 0 0;font-size:13.5px;color:var(--muted);
padding-left:12px;border-left:2px solid var(--rule)}
.stat{display:flex;gap:26px;flex-wrap:wrap;margin:0 0 4px}
.stat div{min-width:110px}
.stat b{display:block;font-size:26px;font-weight:600;line-height:1.1}
.stat span{font-size:12px;color:var(--muted)}
.empty{color:var(--muted);margin:0}
.note{background:var(--accent-bg);color:var(--accent);border-radius:10px;
padding:14px 16px;font-size:14px;margin:14px 0 0}
"""


def render_review(analysis):
    counts = analysis["counts"]
    agreement = analysis["agreement"]
    lede = (
        "Aucune requalification n’a encore été reçue. Le rapport se remplira "
        "à mesure que les boutons du digest seront utilisés."
        if not analysis["total"]
        else "Confrontation de {} requalification{} au verdict du modèle, "
        "pour préparer la révision suivante de la consigne.".format(
            analysis["total"], "s" if analysis["total"] > 1 else ""
        )
    )
    guidance = ""
    if analysis["total"] and not analysis["sufficient"]:
        guidance = (
            '<p class="note">Trop peu de corrections pour conclure. '
            "Attendez d’en réunir au moins {} avant de réécrire la consigne : "
            "une révision réglée sur deux ou trois cas apprend ces cas, pas la "
            "règle qui les gouverne.</p>".format(MINIMUM_FOR_TREND)
        )
    return """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Révision de la consigne</title>
<style>{style}</style>
</head>
<body>
<div class="wrap">
  <h1>Révision de la consigne</h1>
  <p class="lede">{lede}</p>
  {guidance}

  <h2>Accord global</h2>
  <div class="panel">
    <div class="stat">
      <div><b>{agreement}</b><span>verdicts confirmés</span></div>
      <div><b>{raised}</b><span>remontés</span></div>
      <div><b>{lowered}</b><span>abaissés</span></div>
      <div><b>{total}</b><span>requalifications</span></div>
    </div>
  </div>

  <h2>Où le modèle se trompe</h2>
  <div class="panel">{matrix}</div>

  <h2>Quels critères discriminent</h2>
  <div class="panel">{criteria}</div>

  <h2>Les cas à relire</h2>
  {cases}
</div>
</body>
</html>
""".format(
        style=_STYLE,
        lede=escape(lede),
        guidance=guidance,
        agreement="—" if agreement is None else "{:.0f} %".format(100 * agreement),
        raised=counts.get("remonté", 0),
        lowered=counts.get("abaissé", 0),
        total=analysis["total"],
        matrix=_matrix_html(analysis["matrix"]),
        criteria=_criteria_html(analysis),
        cases=_cases_html(analysis),
    )


def export_feedback_review(database, output, csv_output=None):
    analysis = analyse_feedback(database)
    with atomic_open(output, "w", encoding="utf-8") as stream:
        stream.write(render_review(analysis))
    if csv_output:
        write_review_csv(csv_output, analysis)
    return {
        "service": "feedback-review",
        "status": "ok",
        "feedback_count": analysis["total"],
        "corrected_count": len(analysis["corrected"]),
        "agreement": (
            None if analysis["agreement"] is None else round(analysis["agreement"], 4)
        ),
        "sufficient_for_revision": analysis["sufficient"],
        "output": str(output),
        "csv_output": str(csv_output) if csv_output else "",
        "warnings": [],
        "errors": [],
    }
