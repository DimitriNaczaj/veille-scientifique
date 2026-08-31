"""Export bibliographique des articles d’un digest.

Zotero n’expose aucun lien capable d’ajouter une référence depuis un
courriel : le connecteur travaille dans le navigateur, et l’API web exige une
clé personnelle et une requête POST. Le digest fournit donc les deux chemins
qui fonctionnent réellement — un fichier RIS joint, importable d’un seul geste
pour tout le lot, et un lien par article vers sa page, où le connecteur sait
enregistrer la référence.
"""
from .models import PublicationPriority


RIS_MEDIA_TYPE = ("application", "x-research-info-systems")
RIS_FILENAME = "veille-bellegarde.ris"

_TYPE_BY_PRIORITY = {
    PublicationPriority.HIGH: "JOUR",
    PublicationPriority.WATCH: "JOUR",
}


def _clean(value):
    """Une valeur RIS tient sur une ligne : les retours casseraient le format."""
    return " ".join(str(value).split()) if value else ""


def _year(published_date):
    text = _clean(published_date)
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _record(publication):
    lines = ["TY  - " + _TYPE_BY_PRIORITY.get(publication.priority, "JOUR")]
    title = _clean(publication.title)
    if title:
        lines.append("TI  - " + title)
    for author in publication.authors or ():
        author = _clean(author)
        if author:
            lines.append("AU  - " + author)
    journal = _clean(publication.journal)
    if journal:
        lines.append("JO  - " + journal)
    year = _year(publication.published_date)
    if year:
        lines.append("PY  - " + year)
    date = _clean(publication.published_date)
    if date and date != year:
        lines.append("DA  - " + date)
    abstract = _clean(publication.abstract)
    if abstract:
        lines.append("AB  - " + abstract)
    doi = _clean(publication.doi)
    if doi:
        lines.append("DO  - " + doi)
        lines.append("UR  - https://doi.org/" + doi)
    elif publication.url:
        lines.append("UR  - " + _clean(publication.url))
    for theme in publication.themes or ():
        theme = _clean(theme)
        if theme:
            lines.append("KW  - " + theme)
    # Le classement de la veille voyage avec la référence : il reste lisible
    # dans Zotero et permet de retrouver pourquoi l’article a été retenu.
    if publication.priority in _TYPE_BY_PRIORITY:
        lines.append("N1  - Veille Bellegarde : " + publication.priority.value)
    lines.append("ER  - ")
    return "\n".join(lines)


def render_ris(publications):
    records = [_record(publication) for publication in publications]
    return "\n\n".join(records) + "\n" if records else ""
