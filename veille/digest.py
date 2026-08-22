from datetime import datetime
from html import escape
from urllib.parse import quote

from .atomic import atomic_open
from .models import PublicationPriority


_MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _publication_url(publication):
    if publication.doi:
        return "https://doi.org/" + quote(publication.doi, safe="/")
    return publication.url or ""


def _text_row(label, value, css_class="ink", padding="20px 34px 0 34px"):
    if not value:
        return ""
    return """
        <tr>
          <td class="pad" style="padding:{padding};font-family:Arial,Helvetica,sans-serif;">
            <p class="{css_class}" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:25px;mso-line-height-rule:exactly;color:#1D1D1F;">
              <span style="font-weight:bold;">{label} :</span> {value}
            </p>
          </td>
        </tr>""".format(
        padding=padding,
        css_class=css_class,
        label=escape(label),
        value=value,
    )


def _labelled_block(label, value):
    if not value:
        return ""
    return """
        <tr>
          <td class="pad" style="padding:24px 34px 0 34px;font-family:Arial,Helvetica,sans-serif;">
            <p class="ink-3" style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:14px;mso-line-height-rule:exactly;letter-spacing:1.4px;color:#7A777D;text-transform:uppercase;">{label}</p>
            <p class="ink-2" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:24px;mso-line-height-rule:exactly;color:#57555A;">{value}</p>
          </td>
        </tr>""".format(label=escape(label), value=value)


def _publication_html(publication):
    title = escape(publication.title or publication.doi or "Publication sans titre")
    url = _publication_url(publication)
    escaped_url = escape(url, quote=True)
    if escaped_url:
        title_markup = (
            '<a class="ink" href="{}" '
            'style="color:#1D1D1F;text-decoration:none;">{}</a>'
        ).format(escaped_url, title)
    else:
        title_markup = title

    details = []
    if publication.journal:
        details.append(escape(publication.journal))
    if publication.published_date:
        details.append(escape(publication.published_date))
    bibliographic = " — ".join(details)

    authors = ""
    if publication.authors:
        authors = """
            <p class="ink-2" style="margin:16px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:20px;mso-line-height-rule:exactly;color:#57555A;">{}</p>""".format(
            escape(", ".join(publication.authors))
        )

    summary = _text_row(
        "En bref",
        escape(publication.summary_fr) if publication.summary_fr else "",
    )

    bellegarde_value = ""
    if publication.bellegarde_value:
        bellegarde_value = """
        <tr>
          <td class="pad" style="padding:22px 34px 0 34px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" class="inset" style="width:100%;border-collapse:collapse;background:#F1F1F1;border-radius:12px;">
              <tr>
                <td style="padding:20px 22px;font-family:Arial,Helvetica,sans-serif;">
                  <p class="ink" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:25px;mso-line-height-rule:exactly;color:#1D1D1F;"><span style="font-weight:bold;">Intérêt pour Bellegarde :</span> {}</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>""".format(escape(publication.bellegarde_value))

    applications = ""
    if publication.applications:
        applications = _labelled_block(
            "Applications",
            "<br>· ".join(escape(item) for item in publication.applications),
        )

    themes = ""
    if publication.themes:
        chips = "&nbsp; ".join(
            '<span class="chip" style="border:1px solid #DEDBD8;border-radius:20px;padding:4px 11px;white-space:nowrap;">{}</span>'.format(
                escape(theme)
            )
            for theme in publication.themes
        )
        themes = _labelled_block("Thèmes", chips)

    abstract = ""
    if publication.abstract:
        abstract = """
        <tr>
          <td class="pad" style="padding:26px 34px 0 34px;font-family:Arial,Helvetica,sans-serif;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
              <tr><td class="rule" height="1" style="height:1px;line-height:1px;font-size:0;background:#E4E1DE;">&nbsp;</td></tr>
            </table>
            <p class="ink-3" style="margin:20px 0 10px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:14px;mso-line-height-rule:exactly;letter-spacing:1.4px;color:#7A777D;text-transform:uppercase;">Abstract</p>
            <p class="ink-2 abstract" style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:15px;line-height:27px;mso-line-height-rule:exactly;color:#57555A;">{}</p>
          </td>
        </tr>""".format(escape(publication.abstract))

    cta = ""
    if escaped_url:
        cta = """
        <tr>
          <td class="pad" align="left" style="padding:28px 34px 0 34px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
              <tr>
                <td class="btn" bgcolor="#1D1D1F" style="background:#1D1D1F;border-radius:999px;">
                  <a href="{url}" style="display:block;padding:14px 26px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:18px;mso-line-height-rule:exactly;font-weight:bold;color:#FFFFFF;text-decoration:none;">Ouvrir l’étude&nbsp;&nbsp;→</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>""".format(url=escaped_url)

    metadata = []
    if publication.doi:
        metadata.append(
            '<span style="font-weight:bold;color:#57555A;">DOI :</span> {}'.format(
                escape(publication.doi)
            )
        )
    else:
        metadata.append("Référence extraite sans DOI — enrichissement requis.")
    if publication.relevance_reasons:
        metadata.append(
            '<span style="font-weight:bold;color:#57555A;">Repéré pour :</span> {}'.format(
                escape(", ".join(publication.relevance_reasons))
            )
        )
    metadata.append(
        "Signalé dans «&nbsp;{}&nbsp;» — {}".format(
            escape(publication.source_subject),
            escape(publication.source_sender),
        )
    )
    metadata_markup = "".join(
        '<p class="ink-3" style="margin:0 0 4px 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;mso-line-height-rule:exactly;color:#7A777D;">{}</p>'.format(
            line
        )
        for line in metadata
    )

    return """
  <tr>
    <td style="padding:0;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" class="card" style="width:600px;max-width:600px;border-collapse:separate;background:#FFFFFF;border:1px solid #DEDBD8;border-radius:16px;">
        <tr>
          <td class="pad" style="padding:30px 34px 8px 34px;font-family:Arial,Helvetica,sans-serif;">
            {bibliographic}
            <p style="margin:0 0 12px 0;font-family:Arial,Helvetica,sans-serif;font-size:20px;line-height:28px;mso-line-height-rule:exactly;font-weight:bold;color:#1D1D1F;">{title}</p>
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;"><tr><td width="44" height="3" style="width:44px;height:3px;background:#5DADE2;line-height:3px;font-size:0;">&nbsp;</td></tr></table>
            {authors}
          </td>
        </tr>
        {summary}
        {bellegarde_value}
        {applications}
        {themes}
        {abstract}
        {cta}
        <tr>
          <td class="pad" style="padding:24px 34px 30px 34px;font-family:Arial,Helvetica,sans-serif;">
            {metadata}
          </td>
        </tr>
      </table>
    </td>
  </tr>
  <tr><td height="16" style="height:16px;line-height:16px;font-size:0;">&nbsp;</td></tr>""".format(
        bibliographic=(
            '<p class="ink-3" style="margin:0 0 10px 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:16px;mso-line-height-rule:exactly;color:#7A777D;">{}</p>'.format(
                bibliographic
            )
            if bibliographic
            else ""
        ),
        title=title_markup,
        authors=authors,
        summary=summary,
        bellegarde_value=bellegarde_value,
        applications=applications,
        themes=themes,
        abstract=abstract,
        cta=cta,
        metadata=metadata_markup,
    )


def _section_html(priority, publications):
    dot = "#5DADE2" if priority is PublicationPriority.HIGH else "#7A777D"
    return """
  <tr>
    <td class="pad" style="padding:18px 40px 12px 40px;font-family:Arial,Helvetica,sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
        <tr>
          <td width="8" style="width:8px;padding:0 10px 0 0;line-height:0;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="8" style="width:8px;border-collapse:collapse;"><tr><td width="8" height="8" style="width:8px;height:8px;background:{dot};border-radius:8px;line-height:8px;font-size:0;">&nbsp;</td></tr></table>
          </td>
          <td class="ink" style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:14px;mso-line-height-rule:exactly;letter-spacing:1.6px;font-weight:bold;color:#1D1D1F;text-transform:uppercase;">{heading}</td>
        </tr>
      </table>
    </td>
  </tr>
  {articles}""".format(
        dot=dot,
        heading=escape(priority.heading or "Publications"),
        articles="".join(_publication_html(publication) for publication in publications),
    )


def _empty_html(message):
    return """
  <tr>
    <td style="padding:18px 0 0 0;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" class="card" style="width:600px;max-width:600px;border-collapse:separate;background:#FFFFFF;border:1px solid #DEDBD8;border-radius:16px;">
        <tr><td class="pad ink" style="padding:30px 34px;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:25px;color:#1D1D1F;">{}</td></tr>
      </table>
    </td>
  </tr>""".format(escape(message))


def render_digest(publications, total_count=None, excluded_count=0):
    publications = tuple(publications)
    now = datetime.now().astimezone().replace(microsecond=0)
    now_iso = now.isoformat()
    date_label = "{} {} {}".format(now.day, _MONTHS_FR[now.month - 1], now.year)
    if total_count is None:
        total_count = len(publications)
    filtered = excluded_count > 0 or any(
        publication.priority is not PublicationPriority.UNFILTERED
        for publication in publications
    )

    if publications:
        if filtered:
            sections = []
            for priority in (PublicationPriority.HIGH, PublicationPriority.WATCH):
                articles = tuple(
                    publication
                    for publication in publications
                    if publication.priority is priority
                )
                if articles:
                    sections.append(_section_html(priority, articles))
            body = "".join(sections)
        else:
            body = '<tr><td height="18" style="height:18px;line-height:18px;font-size:0;">&nbsp;</td></tr>'
            body += "".join(_publication_html(publication) for publication in publications)
        if filtered:
            summary = (
                "{} publication(s) retenue(s) sur {} analysée(s) ; {} écartée(s)."
            ).format(len(publications), total_count, excluded_count)
        else:
            summary = "{} nouvelle(s) publication(s) détectée(s).".format(
                len(publications)
            )
        preheader = publications[0].summary_fr or summary
    else:
        if excluded_count:
            summary = "0 publication retenue sur {} analysée(s) ; {} écartée(s).".format(
                total_count, excluded_count
            )
            body = _empty_html(
                "Aucune publication pertinente retenue pour cette édition."
            )
        else:
            summary = "Aucune nouvelle publication."
            body = _empty_html("Aucune nouvelle publication détectée.")
        preheader = summary
    if len(preheader) > 180:
        preheader = preheader[:177].rstrip() + "…"

    return """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>Veille scientifique Bellegarde — {date_iso}</title>
<!--[if mso]>
<style>body,table,td,p,a,span{{font-family:Arial,Helvetica,sans-serif !important;}}</style>
<![endif]-->
<style>
  a[x-apple-data-detectors]{{color:inherit !important;text-decoration:none !important;}}
  @media only screen and (max-width:620px){{
    .pad{{padding-left:20px !important;padding-right:20px !important;}}
    .h1{{font-size:27px !important;line-height:32px !important;}}
    .stack{{display:block !important;width:100% !important;text-align:left !important;}}
  }}
  @media (prefers-color-scheme:dark){{
    .bg{{background:#1A181C !important;}}
    .desk{{background:#1A181C !important;}}
    .card{{background:#2A282D !important;border-color:#3D3B41 !important;}}
    .inset{{background:#232126 !important;}}
    .ink,.ink a{{color:#F1F1F1 !important;}}
    .ink-2{{color:#B4B1B6 !important;}}
    .ink-3{{color:#8E8B92 !important;}}
    .rule{{background:#3D3B41 !important;}}
    .rule td{{background:#3D3B41 !important;}}
    .btn{{background:#F1F1F1 !important;}}
    .btn a{{color:#1D1D1F !important;}}
    .mark{{background:#2E4657 !important;color:#DCEBF5 !important;}}
    .chip{{border-color:#3D3B41 !important;color:#B4B1B6 !important;}}
  }}
</style>
</head>
<body class="bg" style="margin:0;padding:0;background:#E9E7E5;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">

<span class="ink-3" style="display:none !important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;">{preheader}</span>

<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" class="desk" style="background:#E9E7E5;width:100%;border-collapse:collapse;">
<tr>
<td align="center" style="padding:32px 12px 48px 12px;">

<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="width:600px;max-width:600px;border-collapse:collapse;">
  <tr>
    <td class="pad" style="padding:0 40px 22px 40px;font-family:Arial,Helvetica,sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
        <tr>
          <td class="ink stack" align="left" width="300" style="width:300px;font-family:Arial,Helvetica,sans-serif;font-size:17px;line-height:20px;mso-line-height-rule:exactly;font-weight:bold;letter-spacing:0.4px;color:#1D1D1F;">bellegarde</td>
          <td class="ink-3 stack" align="right" width="220" style="width:220px;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:20px;mso-line-height-rule:exactly;letter-spacing:1.1px;color:#7A777D;text-transform:uppercase;">we change behaviour</td>
        </tr>
      </table>
    </td>
  </tr>
  <tr>
    <td class="pad" style="padding:0 40px;font-family:Arial,Helvetica,sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
        <tr><td class="rule" height="1" style="height:1px;line-height:1px;font-size:0;background:#1D1D1F;">&nbsp;</td></tr>
      </table>
    </td>
  </tr>
  <tr>
    <td class="pad" style="padding:26px 40px 16px 40px;font-family:Arial,Helvetica,sans-serif;">
      <p class="ink-3" style="margin:0 0 14px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:14px;mso-line-height-rule:exactly;letter-spacing:1.4px;color:#7A777D;text-transform:uppercase;">Veille quotidienne &nbsp;·&nbsp; {date_label}</p>
      <h1 class="h1 ink" style="margin:0 0 12px 0;font-family:Arial,Helvetica,sans-serif;font-size:34px;line-height:40px;mso-line-height-rule:exactly;font-weight:bold;letter-spacing:-0.6px;color:#1D1D1F;">Veille scientifique Bellegarde</h1>
      <p class="ink" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:26px;mso-line-height-rule:exactly;color:#1D1D1F;font-weight:bold;">{summary}</p>
    </td>
  </tr>
  {body}
  <tr>
    <td class="pad" style="padding:20px 40px 0 40px;font-family:Arial,Helvetica,sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
        <tr><td class="rule" height="1" style="height:1px;line-height:1px;font-size:0;background:#D6D3D0;">&nbsp;</td></tr>
      </table>
      <p class="ink-3" style="margin:18px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;mso-line-height-rule:exactly;color:#7A777D;">Digest généré automatiquement le {now}. Métadonnées enrichies via Crossref lorsqu’elles sont disponibles.</p>
      <p class="ink-3" style="margin:12px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;mso-line-height-rule:exactly;color:#7A777D;">Bellegarde — veille interne. <a class="ink-2" href="mailto:science-digest@bellegarde.co?subject=Pr%C3%A9f%C3%A9rences%20veille" style="color:#57555A;text-decoration:underline;">Gérer la réception</a> · <a class="ink-2" href="mailto:science-digest@bellegarde.co?subject=D%C3%A9sabonnement%20veille" style="color:#57555A;text-decoration:underline;">Se désabonner</a></p>
    </td>
  </tr>
</table>

</td>
</tr>
</table>
</body>
</html>
""".format(
        date_iso=escape(now.date().isoformat()),
        date_label=escape(date_label),
        preheader=escape(preheader),
        summary=escape(summary),
        body=body,
        now=escape(now_iso),
    )


def write_digest(path, publications, total_count=None, excluded_count=0):
    with atomic_open(path, "w", encoding="utf-8") as stream:
        stream.write(
            render_digest(
                publications,
                total_count=total_count,
                excluded_count=excluded_count,
            )
        )
