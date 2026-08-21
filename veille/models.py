from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class PublicationPriority(Enum):
    UNFILTERED = ("unfiltered", None)
    HIGH = ("high", "Priorité élevée")
    WATCH = ("watch", "À surveiller")
    EXCLUDED = ("excluded", None)

    def __new__(cls, value, heading):
        member = object.__new__(cls)
        member._value_ = value
        member.heading = heading
        return member


@dataclass(frozen=True)
class PublicationCandidate:
    identity: str
    doi: Optional[str]
    title: Optional[str]
    url: Optional[str]


@dataclass(frozen=True)
class ParsedMessage:
    identity: str
    subject: str
    sender: str
    publications: Tuple[PublicationCandidate, ...]


@dataclass(frozen=True)
class WorkMetadata:
    title: Optional[str]
    abstract: Optional[str]
    journal: Optional[str]
    published_date: Optional[str]
    authors: Tuple[str, ...]
    url: Optional[str]


@dataclass(frozen=True)
class NewPublication:
    identity: str
    doi: Optional[str]
    title: Optional[str]
    url: Optional[str]
    source_subject: str
    source_sender: str
    abstract: Optional[str] = None
    journal: Optional[str] = None
    published_date: Optional[str] = None
    authors: Tuple[str, ...] = ()
    metadata_status: Optional[str] = None
    relevance_score: int = 0
    relevance_reasons: Tuple[str, ...] = ()
    priority: PublicationPriority = PublicationPriority.UNFILTERED


@dataclass(frozen=True)
class RunReport:
    messages_processed: int
    messages_skipped: int
    publications_detected: int
    publications_new: int
    publications_delivered: int
    publications_enriched: int
    publications_relevant: int
    publications_excluded: int
    publications_pending: int
    warnings: Tuple[str, ...]
    errors: Tuple[str, ...]

    def as_dict(self):
        return {
            "messages_processed": self.messages_processed,
            "messages_skipped": self.messages_skipped,
            "publications_detected": self.publications_detected,
            "publications_new": self.publications_new,
            "publications_delivered": self.publications_delivered,
            "publications_enriched": self.publications_enriched,
            "publications_relevant": self.publications_relevant,
            "publications_excluded": self.publications_excluded,
            "publications_pending": self.publications_pending,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
