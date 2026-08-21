import base64
import hashlib
import html
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import List
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

from .models import ParsedMessage, PublicationCandidate


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"'»›]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,\"'»›"
BALANCED_DELIMITERS = (("(", ")"), ("[", "]"), ("{", "}"), ("<", ">"))
ARTICLE_LINK_DOMAINS = {
    "click.aaas.sciencepubs.org",
    "click.info.apa.org",
    "click.notification.elsevier.com",
    "el.wiley.com",
    "links.springernature.com",
    "url6649.tandfonline.com",
    "www.mdpi.com",
}
NON_ARTICLE_TEXT = (
    "cookie",
    "manage my",
    "membership",
    "privacy",
    "table of contents",
    "terms and conditions",
    "unsubscribe",
    "view latest articles",
    "view this email",
)


class _NewsletterHTMLParser(HTMLParser):
    BLOCK_TAGS = {
        "article",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "p",
        "section",
        "td",
        "tr",
    }

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self._chunks = []  # type: List[str]
        self._link_href = None
        self._link_chunks = []  # type: List[str]
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCK_TAGS:
            self._chunks.append("\n")
        if tag.lower() == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self._link_href = value
                    self._link_chunks = []

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._link_href:
            text = " ".join("".join(self._link_chunks).split())
            self.links.append((self._link_href, text))
            self._link_href = None
            self._link_chunks = []
        if tag.lower() in self.BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        self._chunks.append(data)
        if self._link_href:
            self._link_chunks.append(data)

    def visible_lines(self):
        text = "".join(self._chunks)
        return tuple(line.strip() for line in text.splitlines() if line.strip())


def normalize_doi(raw):
    value = html.unescape(unquote(raw)).strip()
    lowered = value.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.strip().rstrip(TRAILING_PUNCTUATION)
    for opening, closing in BALANCED_DELIMITERS:
        while value.endswith(closing) and value.count(opening) < value.count(closing):
            value = value[:-1]
    return value.lower()


def _extract_dois(value):
    decoded = html.unescape(unquote(value))
    dois = []
    for match in DOI_PATTERN.finditer(decoded):
        candidate = match.group(0)
        if "?" in candidate:
            doi_part, possible_query = candidate.split("?", 1)
            if "=" in possible_query or possible_query.lower().startswith("utm_"):
                candidate = doi_part
        dois.append(normalize_doi(candidate))
    return tuple(dois)


def _candidate_title(lines, line_index):
    if line_index <= 0:
        return None
    previous = lines[line_index - 1].strip()
    if not previous or len(previous) > 300:
        return None
    if previous.lower().startswith(("http://", "https://", "doi:")):
        return None
    return previous


def _extract_from_lines(lines):
    candidates = []  # type: List[PublicationCandidate]
    for index, line in enumerate(lines):
        title = _candidate_title(lines, index)
        for doi in _extract_dois(line):
            candidates.append(_doi_candidate(doi, title=title))
    return candidates


def _normalized_title(title):
    return " ".join(re.sub(r"[^\w]+", " ", title.casefold()).split())


def publication_identity_from_title(title):
    normalized = _normalized_title(title)
    return "title:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _publication_title(title):
    cleaned = " ".join(title.split()).strip()
    lowered = cleaned.casefold()
    if len(cleaned) < 20 or len(cleaned) > 300:
        return None
    if len(cleaned.split()) < 3:
        return None
    if any(fragment in lowered for fragment in NON_ARTICLE_TEXT):
        return None
    if cleaned.startswith("©"):
        return None
    return cleaned


def _canonical_article_url(raw_url):
    decoded = html.unescape(raw_url.strip())
    parsed = urlsplit(decoded)
    if parsed.netloc.casefold().endswith(".awstrack.me"):
        segments = parsed.path.split("/")
        if len(segments) > 2 and segments[1] == "L0":
            intermediary = urlsplit(unquote(segments[2]))
            encoded_values = parse_qs(intermediary.query).get("_L54AD1F204_", ())
            if encoded_values:
                encoded = encoded_values[0]
                try:
                    padding = "=" * (-len(encoded) % 4)
                    payload = base64.urlsafe_b64decode(encoded + padding).decode(
                        "utf-8"
                    )
                    targets = parse_qs(payload).get("target", ())
                    if targets:
                        target = targets[0]
                        for _ in range(3):
                            unquoted = unquote(target)
                            if unquoted == target:
                                break
                            target = unquoted
                        canonical = urlsplit(target)
                        if (
                            canonical.scheme in ("http", "https")
                            and canonical.netloc.casefold()
                            in ("nature.com", "www.nature.com")
                            and canonical.path.casefold().startswith("/articles/")
                        ):
                            return urlunsplit(
                                (
                                    canonical.scheme,
                                    canonical.netloc,
                                    canonical.path,
                                    "",
                                    "",
                                )
                            )
                except (ValueError, UnicodeDecodeError):
                    pass
    if parsed.netloc.casefold() == "click.notification.elsevier.com":
        segments = parsed.path.split("/")
        if len(segments) > 2 and segments[1] == "CL0":
            target = unquote(segments[2])
            if target.startswith(("http://", "https://")):
                return target
    if parsed.netloc.casefold() == "www.mdpi.com":
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return decoded


def _doi_candidate(doi, title=None, url=None):
    useful_title = _publication_title(title) if title else None
    return PublicationCandidate(
        identity="doi:" + doi,
        doi=doi,
        title=useful_title,
        url=url,
    )


def _link_candidate(title, url):
    useful_title = _publication_title(title)
    if useful_title is None:
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return None
    outer_host = parsed.netloc.casefold()
    if (
        outer_host not in ARTICLE_LINK_DOMAINS
        and not outer_host.endswith(".awstrack.me")
    ):
        return None
    canonical_url = _canonical_article_url(url)
    canonical = urlsplit(canonical_url)
    canonical_host = canonical.netloc.casefold()
    canonical_path = canonical.path.casefold()
    if outer_host.endswith(".awstrack.me") and not (
        canonical_host in ("nature.com", "www.nature.com")
        and canonical_path.startswith("/articles/")
    ):
        return None
    if canonical_host == "www.mdpi.com" and (
        "/special_issues/" in canonical_path or "/events/" in canonical_path
    ):
        return None
    if canonical_host == "www.sciencedirect.com" and (
        canonical_path.startswith("/journal/")
        or canonical_path.startswith("/science/journal/aip/")
    ):
        return None
    return PublicationCandidate(
        identity=publication_identity_from_title(useful_title),
        doi=None,
        title=useful_title,
        url=canonical_url,
    )


def _text_parts(message, content_type):
    parts = []  # type: List[str]
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == content_type:
                parts.append(part.get_content())
    elif message.get_content_type() == content_type:
        parts.append(message.get_content())
    return parts


def _deduplicate_candidates(candidates):
    by_identity = {}
    order = []
    for candidate in candidates:
        existing = by_identity.get(candidate.identity)
        if existing is None:
            by_identity[candidate.identity] = candidate
            order.append(candidate.identity)
        elif not existing.title and candidate.title:
            by_identity[candidate.identity] = candidate
    return tuple(by_identity[identity] for identity in order)


def _without_newsletter_heading(candidates, subject):
    prefix = "APA PsycAlert - "
    if not subject.casefold().startswith(prefix.casefold()):
        return candidates
    journal_title = subject[len(prefix) :]
    normalized_journal = _normalized_title(journal_title)
    return tuple(
        candidate
        for candidate in candidates
        if candidate.doi
        or not candidate.title
        or _normalized_title(candidate.title) != normalized_journal
    )


def parse_message_bytes(raw):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    message_id = str(message.get("Message-ID", "")).strip()
    identity = message_id if message_id else "sha256:" + hashlib.sha256(raw).hexdigest()
    subject = str(message.get("Subject", "(sans objet)"))

    candidates = []  # type: List[PublicationCandidate]
    for text in _text_parts(message, "text/plain"):
        lines = tuple(line.strip() for line in text.splitlines() if line.strip())
        candidates.extend(_extract_from_lines(lines))

    for markup in _text_parts(message, "text/html"):
        parser = _NewsletterHTMLParser()
        parser.feed(markup)
        line_doi_candidates = list(_extract_from_lines(parser.visible_lines()))

        titles_by_url = {}
        dois_by_url = {}
        for link, link_text in parser.links:
            canonical_url = _canonical_article_url(link)
            useful_title = _publication_title(link_text)
            if useful_title:
                titles_by_url.setdefault(canonical_url, useful_title)
            linked_dois = _extract_dois(link) + _extract_dois(link_text)
            if linked_dois:
                dois_by_url.setdefault(canonical_url, []).extend(linked_dois)

        linked_doi_candidates = []
        for canonical_url, dois in dois_by_url.items():
            for doi in dois:
                linked_doi_candidates.append(
                    _doi_candidate(
                        doi,
                        title=titles_by_url.get(canonical_url),
                        url=canonical_url,
                    )
                )

        unlinked_candidates = []
        for link, link_text in parser.links:
            canonical_url = _canonical_article_url(link)
            if canonical_url not in dois_by_url:
                candidate = _link_candidate(link_text, link)
                if candidate is not None:
                    unlinked_candidates.append(candidate)

        if (
            not linked_doi_candidates
            and len(line_doi_candidates) >= 2
            and len(line_doi_candidates) == len(unlinked_candidates)
        ):
            for doi_candidate, link_candidate in zip(
                line_doi_candidates, unlinked_candidates
            ):
                candidates.append(
                    _doi_candidate(
                        doi_candidate.doi,
                        title=link_candidate.title,
                        url=link_candidate.url,
                    )
                )
        else:
            candidates.extend(line_doi_candidates)
            candidates.extend(linked_doi_candidates)
            candidates.extend(unlinked_candidates)

    return ParsedMessage(
        identity=identity,
        subject=subject,
        sender=str(message.get("From", "(expéditeur inconnu)")),
        publications=_without_newsletter_heading(
            _deduplicate_candidates(candidates), subject
        ),
    )


def parse_message(path):
    return parse_message_bytes(Path(path).read_bytes())
