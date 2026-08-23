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

_SECTION_HEADINGS = {
    PublicationPriority.HIGH: "Pépites",
    PublicationPriority.WATCH: "Éventuellement",
}


def _counted_articles(count, singular, plural):
    if count == 1:
        return "1 article {}".format(singular)
    return "{} articles {}".format(count, plural)


def _filtered_summary(retained_count, total_count):
    retained = _counted_articles(retained_count, "retenu", "retenus")
    published = "{} publié{}".format(total_count, "" if total_count == 1 else "s")
    return "{} sur {}.".format(retained.capitalize(), published)


def _new_publications_summary(count):
    if count == 1:
        return "1 nouvelle publication détectée."
    return "{} nouvelles publications détectées.".format(count)


def _publication_url(publication):
    if publication.doi:
        return "https://doi.org/" + quote(publication.doi, safe="/")
    return publication.url or ""


def _summary_row(value):
    if not value:
        return ""
    return """
        <tr>
          <td class="pad" style="padding:20px 34px 0 34px;font-family:Arial,Helvetica,sans-serif;">
            <p class="article-summary ink" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:25px;mso-line-height-rule:exactly;color:#1D1D1F;">{}</p>
          </td>
        </tr>""".format(value)


def _labelled_block(label, value):
    if not value:
        return ""
    return """
        <tr>
          <td class="pad" style="padding:24px 34px 0 34px;font-family:Arial,Helvetica,sans-serif;">
            <p class="article-label ink-3" style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:14px;mso-line-height-rule:exactly;letter-spacing:1.4px;color:#7A777D;text-transform:uppercase;">{label}</p>
            <p class="article-detail ink-2" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:24px;mso-line-height-rule:exactly;color:#57555A;">{value}</p>
          </td>
        </tr>""".format(label=escape(label), value=value)


def _applications_block(applications):
    if not applications:
        return ""
    items = "".join("<li>{}</li>".format(escape(item)) for item in applications)
    return """
        <tr>
          <td class="pad" style="padding:24px 34px 0 34px;font-family:Arial,Helvetica,sans-serif;">
            <p class="article-label ink-3" style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:14px;mso-line-height-rule:exactly;letter-spacing:1.4px;color:#7A777D;text-transform:uppercase;">Applications</p>
            <ul class="application-list ink-2" style="margin:0;padding:0 0 0 20px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:24px;mso-line-height-rule:exactly;color:#57555A;">{}</ul>
          </td>
        </tr>""".format(items)


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
            <p class="article-authors ink-2" style="margin:16px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:20px;mso-line-height-rule:exactly;color:#57555A;">{}</p>""".format(
            escape(", ".join(publication.authors))
        )

    doi = ""
    if publication.doi:
        doi = """
            <p class="doi ink-3" style="margin:8px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;mso-line-height-rule:exactly;color:#7A777D;">DOI : <a class="ink-3" href="{url}" style="color:#7A777D;text-decoration:underline;">{value}</a></p>""".format(
            url=escaped_url,
            value=escape(publication.doi),
        )

    summary = _summary_row(
        escape(publication.summary_fr) if publication.summary_fr else ""
    )

    bellegarde_value = ""
    if publication.bellegarde_value:
        bellegarde_value = """
        <tr>
          <td class="pad" style="padding:22px 34px 0 34px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" class="inset" style="width:100%;border-collapse:collapse;background:#F1F1F1;border-radius:12px;">
              <tr>
                <td style="padding:20px 22px;font-family:Arial,Helvetica,sans-serif;">
                  <p class="article-interest ink" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:25px;mso-line-height-rule:exactly;color:#1D1D1F;"><span style="font-weight:bold;">Intérêts :</span> {}</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>""".format(escape(publication.bellegarde_value))

    applications = _applications_block(publication.applications)

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
    if (
        publication.abstract
        and publication.priority is not PublicationPriority.WATCH
    ):
        abstract = """
        <tr>
          <td class="pad" style="padding:26px 34px 0 34px;font-family:Arial,Helvetica,sans-serif;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
              <tr><td class="rule" height="1" style="height:1px;line-height:1px;font-size:0;background:#E4E1DE;">&nbsp;</td></tr>
            </table>
            <p class="article-label ink-3" style="margin:20px 0 10px 0;font-family:Arial,Helvetica,sans-serif;font-size:11px;line-height:14px;mso-line-height-rule:exactly;letter-spacing:1.4px;color:#7A777D;text-transform:uppercase;">Abstract</p>
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
                  <a href="{url}" style="display:block;padding:14px 26px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:18px;mso-line-height-rule:exactly;font-weight:bold;color:#FFFFFF;text-decoration:none;">Ouvrir l’étude</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>""".format(url=escaped_url)

    metadata = []
    if not publication.doi:
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
        '<p class="article-metadata ink-3" style="margin:0 0 4px 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;mso-line-height-rule:exactly;color:#7A777D;">{}</p>'.format(
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
            <p class="article-title" style="margin:0 0 12px 0;font-family:Arial,Helvetica,sans-serif;font-size:20px;line-height:28px;mso-line-height-rule:exactly;font-weight:bold;color:#1D1D1F;">{title}</p>
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;"><tr><td width="44" height="3" style="width:44px;height:3px;background:#6FCF97;line-height:3px;font-size:0;">&nbsp;</td></tr></table>
            {authors}
            {doi}
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
            '<p class="article-kicker ink-3" style="margin:0 0 10px 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:16px;mso-line-height-rule:exactly;color:#7A777D;">{}</p>'.format(
                bibliographic
            )
            if bibliographic
            else ""
        ),
        title=title_markup,
        authors=authors,
        doi=doi,
        summary=summary,
        bellegarde_value=bellegarde_value,
        applications=applications,
        themes=themes,
        abstract=abstract,
        cta=cta,
        metadata=metadata_markup,
    )


def _section_html(priority, publications):
    dot = "#6FCF97" if priority is PublicationPriority.HIGH else "#7A777D"
    return """
  <tr>
    <td class="pad" style="padding:34px 40px 12px 40px;font-family:Arial,Helvetica,sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
        <tr>
          <td width="11" style="width:11px;padding:0 12px 0 0;line-height:0;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="11" style="width:11px;border-collapse:collapse;"><tr><td width="11" height="11" style="width:11px;height:11px;background:{dot};border-radius:11px;line-height:11px;font-size:0;">&nbsp;</td></tr></table>
          </td>
          <td class="ink" style="font-family:Arial,Helvetica,sans-serif;font-size:24px;line-height:30px;mso-line-height-rule:exactly;font-weight:bold;color:#1D1D1F;">{heading}</td>
        </tr>
      </table>
    </td>
  </tr>
  {articles}""".format(
        dot=dot,
        heading=escape(_SECTION_HEADINGS.get(priority, "Publications")),
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
            summary = _filtered_summary(len(publications), total_count)
        else:
            summary = _new_publications_summary(len(publications))
        preheader = publications[0].summary_fr or summary
    else:
        if excluded_count:
            summary = _filtered_summary(0, total_count)
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
<title>Veille quotidienne — {date_iso}</title>
<!--[if mso]>
<style>body,table,td,p,a,span{{font-family:Arial,Helvetica,sans-serif !important;}}</style>
<![endif]-->
<style>
  a[x-apple-data-detectors]{{color:inherit !important;text-decoration:none !important;}}
  .mark{{background:#E2F5EA;color:#1D1D1F;}}
  .logo-light{{display:block !important;}}
  .logo-dark{{display:none !important;max-height:0 !important;overflow:hidden !important;mso-hide:all;}}
  @media only screen and (max-width:620px){{
    .pad{{padding-left:20px !important;padding-right:20px !important;}}
    .h1{{font-size:27px !important;line-height:32px !important;}}
    .digest-meta{{font-size:15px !important;line-height:22px !important;}}
    .article-kicker,.article-authors,.doi,.article-metadata{{font-size:14px !important;line-height:22px !important;}}
    .article-title{{font-size:22px !important;line-height:30px !important;}}
    .article-summary,.article-interest,.application-list,.article-detail{{font-size:16px !important;line-height:26px !important;}}
    .abstract{{font-size:16px !important;line-height:29px !important;}}
    .article-label{{font-size:12px !important;line-height:16px !important;}}
    .btn a{{font-size:16px !important;line-height:20px !important;}}
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
    .mark{{background:#2C4A39 !important;color:#DCEFE2 !important;}}
    .chip{{border-color:#3D3B41 !important;color:#B4B1B6 !important;}}
    .logo-light{{display:none !important;mso-hide:all !important;}}
    .logo-dark{{display:block !important;max-height:none !important;overflow:visible !important;mso-hide:none !important;}}
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
    <td class="pad" style="padding:6px 40px 0 40px;font-family:Arial,Helvetica,sans-serif;">
      <h1 class="h1 ink" style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;font-size:34px;line-height:40px;mso-line-height-rule:exactly;color:#1D1D1F;font-weight:bold;">Veille scientifique</h1>
      <p class="digest-meta ink-3" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:20px;mso-line-height-rule:exactly;color:#7A777D;">{date_label}&nbsp;–&nbsp; <span class="ink-2" style="color:#57555A;">{summary}</span></p>
    </td>
  </tr>
  {body}
  <tr>
    <td class="pad" align="left" style="padding:40px 40px 0 40px;font-family:Arial,Helvetica,sans-serif;">
      <img class="logo-light" src="cid:bellegarde-logo-black" width="250" height="49" alt="Bellegarde — we change behaviour" style="display:block;width:250px;max-width:100%;height:auto;border:0;">
      <img class="logo-dark" src="cid:bellegarde-logo-white" width="250" height="49" alt="" aria-hidden="true" style="display:none;width:250px;max-width:100%;height:auto;border:0;max-height:0;overflow:hidden;mso-hide:all;">
    </td>
  </tr>
  <tr>
    <td class="pad" style="padding:28px 40px 0 40px;font-family:Arial,Helvetica,sans-serif;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
        <tr><td class="rule" height="1" style="height:1px;line-height:1px;font-size:0;background:#D6D3D0;">&nbsp;</td></tr>
      </table>
      <p class="ink-3" style="margin:18px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;mso-line-height-rule:exactly;color:#7A777D;">Digest généré automatiquement le {now}. Métadonnées enrichies via Crossref.</p>
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
