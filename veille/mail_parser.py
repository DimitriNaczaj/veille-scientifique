import hashlib
import html
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote

from .models import ParsedMessage, PublicationCandidate


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?\"'»›]}"


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
        self.links = []  # type: List[str]

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCK_TAGS:
            self._chunks.append("\n")
        if tag.lower() == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self.links.append(value)

    def handle_endtag(self, tag):
        if tag.lower() in self.BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        self._chunks.append(data)

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
    while value.endswith(")") and value.count("(") < value.count(")"):
        value = value[:-1]
    return value.lower()


def _extract_dois(value):
    decoded = html.unescape(unquote(value))
    return tuple(normalize_doi(match.group(0)) for match in DOI_PATTERN.finditer(decoded))


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
            candidates.append(PublicationCandidate(doi=doi, title=title))
    return candidates


def _plain_text_parts(message):
    parts = []  # type: List[str]
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                parts.append(part.get_content())
    elif message.get_content_type() == "text/plain":
        parts.append(message.get_content())
    return parts


def _html_parts(message):
    parts = []  # type: List[str]
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/html":
                parts.append(part.get_content())
    elif message.get_content_type() == "text/html":
        parts.append(message.get_content())
    return parts


def _deduplicate_candidates(candidates):
    by_doi = {}
    order = []
    for candidate in candidates:
        existing = by_doi.get(candidate.doi)
        if existing is None:
            by_doi[candidate.doi] = candidate
            order.append(candidate.doi)
        elif not existing.title and candidate.title:
            by_doi[candidate.doi] = candidate
    return tuple(by_doi[doi] for doi in order)


def parse_message(path):
    raw = Path(path).read_bytes()
    message = BytesParser(policy=policy.default).parsebytes(raw)
    message_id = str(message.get("Message-ID", "")).strip()
    identity = message_id if message_id else "sha256:" + hashlib.sha256(raw).hexdigest()

    candidates = []  # type: List[PublicationCandidate]
    for text in _plain_text_parts(message):
        lines = tuple(line.strip() for line in text.splitlines() if line.strip())
        candidates.extend(_extract_from_lines(lines))

    for markup in _html_parts(message):
        parser = _NewsletterHTMLParser()
        parser.feed(markup)
        candidates.extend(_extract_from_lines(parser.visible_lines()))
        for link in parser.links:
            for doi in _extract_dois(link):
                candidates.append(PublicationCandidate(doi=doi, title=None))

    return ParsedMessage(
        identity=identity,
        subject=str(message.get("Subject", "(sans objet)")),
        sender=str(message.get("From", "(expéditeur inconnu)")),
        publications=_deduplicate_candidates(candidates),
    )
