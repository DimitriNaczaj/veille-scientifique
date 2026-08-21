from dataclasses import dataclass
from typing import Optional, Tuple


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
class NewPublication:
    identity: str
    doi: Optional[str]
    title: Optional[str]
    url: Optional[str]
    source_subject: str
    source_sender: str


@dataclass(frozen=True)
class RunReport:
    messages_processed: int
    messages_skipped: int
    publications_detected: int
    publications_new: int
    errors: Tuple[str, ...]

    def as_dict(self):
        return {
            "messages_processed": self.messages_processed,
            "messages_skipped": self.messages_skipped,
            "publications_detected": self.publications_detected,
            "publications_new": self.publications_new,
            "errors": list(self.errors),
        }
