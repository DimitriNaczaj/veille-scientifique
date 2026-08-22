from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple


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
class AIAnalysis:
    relevant: bool
    priority: PublicationPriority
    summary_fr: str
    bellegarde_value: str
    applications: Tuple[str, ...]
    themes: Tuple[str, ...]
    input_tokens: int
    output_tokens: int
    model: str
    prompt_version: str


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
    summary_fr: Optional[str] = None
    bellegarde_value: Optional[str] = None
    applications: Tuple[str, ...] = ()
    themes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RunReport:
    messages_processed: int
    messages_skipped: int
    publications_detected: int
    publications_new: int
    publications_delivered: int
    publications_enriched: int
    publications_ai_analyzed: int
    publications_relevant: int
    publications_excluded: int
    publications_pending: int
    ai_input_tokens: int
    ai_output_tokens: int
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
            "publications_ai_analyzed": self.publications_ai_analyzed,
            "publications_relevant": self.publications_relevant,
            "publications_excluded": self.publications_excluded,
            "publications_pending": self.publications_pending,
            "ai_input_tokens": self.ai_input_tokens,
            "ai_output_tokens": self.ai_output_tokens,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ImportReport:
    messages_total: int
    messages_processed: int
    messages_skipped: int
    messages_without_publication: int
    publications_detected: int
    publications_new: int
    publications_unique: int
    sender_domains: Dict[str, Dict[str, int]]
    errors: Tuple[str, ...]

    def as_dict(self):
        return {
            "messages_total": self.messages_total,
            "messages_processed": self.messages_processed,
            "messages_skipped": self.messages_skipped,
            "messages_without_publication": self.messages_without_publication,
            "publications_detected": self.publications_detected,
            "publications_new": self.publications_new,
            "publications_unique": self.publications_unique,
            "sender_domains": self.sender_domains,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class IMAPSyncReport:
    folder: str
    uidvalidity: str
    messages_available: int
    messages_downloaded: int
    messages_existing: int
    messages_skipped_on_initialization: int
    last_uid: int
    errors: Tuple[str, ...]

    def as_dict(self):
        return {
            "service": "imap-sync",
            "status": "ok" if not self.errors else "partial",
            "folder": self.folder,
            "uidvalidity": self.uidvalidity,
            "messages_available": self.messages_available,
            "messages_downloaded": self.messages_downloaded,
            "messages_existing": self.messages_existing,
            "messages_skipped_on_initialization": self.messages_skipped_on_initialization,
            "last_uid": self.last_uid,
            "errors": list(self.errors),
        }
