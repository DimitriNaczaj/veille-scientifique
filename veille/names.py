"""Présentation des noms d’auteurs selon les règles APA utilisées par le digest."""
import re


_COLLECTIVE_TERMS = re.compile(
    r"\b(?:association|centre|center|collaboration|committee|consortium|"
    r"department|group|institute|institut|network|organisation|organization|"
    r"society|team|université|university)\b",
    re.IGNORECASE,
)
_PARTICLES = {
    "da",
    "de",
    "del",
    "della",
    "den",
    "der",
    "di",
    "dos",
    "du",
    "la",
    "le",
    "van",
    "von",
}
_SUFFIXES = {
    "jr": "Jr.",
    "sr": "Sr.",
    "ii": "II",
    "iii": "III",
    "iv": "IV",
    "v": "V",
}


def _clean(value):
    return " ".join(str(value or "").split())


def _suffix(value):
    return _SUFFIXES.get(value.casefold().rstrip("."))


def _looks_like_initials(value):
    compact = value.replace(".", "").replace("-", "")
    return bool(compact) and compact.isalpha() and (
        len(compact) == 1
        or ("." in value and len(compact) <= 4 and compact.isupper())
    )


def _split_author(value):
    name = _clean(value)
    if not name or _COLLECTIVE_TERMS.search(name):
        return "", "", "", name

    comma_parts = [part.strip() for part in name.split(",")]
    if len(comma_parts) >= 2:
        family = comma_parts[0]
        given = comma_parts[1]
        suffix = _suffix(comma_parts[2]) if len(comma_parts) >= 3 else ""
        return family, given, suffix or "", ""

    tokens = name.split()
    suffix = ""
    if len(tokens) > 1 and _suffix(tokens[-1]):
        suffix = _suffix(tokens.pop()) or ""
    if len(tokens) == 1:
        return tokens[0], "", suffix, ""

    initial_start = len(tokens)
    while initial_start > 1 and _looks_like_initials(tokens[initial_start - 1]):
        initial_start -= 1
    if initial_start < len(tokens):
        family = " ".join(tokens[:initial_start])
        given = " ".join(tokens[initial_start:])
        return family, given, suffix, ""

    family_start = len(tokens) - 1
    while family_start > 0:
        candidate = tokens[family_start - 1].casefold().strip(".'’")
        if candidate not in _PARTICLES:
            break
        family_start -= 1
    if len(tokens) > 2 and family_start == len(tokens) - 1 and not suffix:
        return "", "", "", name
    family = " ".join(tokens[family_start:])
    given = " ".join(tokens[:family_start])
    return family, given, suffix, ""


def _initials(given):
    initialized = []
    for token in given.split():
        pieces = []
        for part in token.split("-"):
            letters = [character for character in part if character.isalpha()]
            if not letters:
                continue
            if (
                len(letters) > 1
                and "." in part
                and part.replace(".", "").isupper()
            ):
                pieces.append(". ".join(letters) + ".")
            else:
                pieces.append(letters[0].upper() + ".")
        if pieces:
            initialized.append("-".join(pieces))
    return " ".join(initialized)


def format_apa_author(author):
    family, given, suffix, literal = _split_author(author)
    if literal:
        return literal
    result = family
    initials = _initials(given)
    if initials:
        result += ", " + initials
    if suffix:
        result += ", " + suffix
    return result


def format_apa_in_text_citation(authors, published_date):
    """Render the parenthetical author-date form defined by styles/apa.csl."""
    short_names = []
    for author in authors or ():
        family, _given, _suffix_value, literal = _split_author(author)
        short_name = literal or family
        if short_name:
            short_names.append(short_name)
    if not short_names:
        return ""
    if len(short_names) == 1:
        author_text = short_names[0]
    elif len(short_names) == 2:
        author_text = short_names[0] + " & " + short_names[1]
    else:
        author_text = short_names[0] + " et al."
    year_match = re.search(r"(?<!\d)(\d{4})(?!\d)", str(published_date or ""))
    year = year_match.group(1) if year_match else "s. d."
    return "({}, {})".format(author_text, year)


def format_ris_author(author):
    family, given, suffix, literal = _split_author(author)
    if literal:
        return literal
    result = family
    if given:
        result += ", " + given
    if suffix:
        result += ", " + suffix
    return result
