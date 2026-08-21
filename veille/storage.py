import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import NewPublication


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS messages (
    identity TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    source_path TEXT NOT NULL,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publications (
    doi TEXT PRIMARY KEY,
    title TEXT,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_publications (
    message_identity TEXT NOT NULL REFERENCES messages(identity),
    publication_doi TEXT NOT NULL REFERENCES publications(doi),
    PRIMARY KEY (message_identity, publication_doi)
);
"""


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)

    def close(self):
        self.connection.close()

    def has_message(self, identity):
        row = self.connection.execute(
            "SELECT 1 FROM messages WHERE identity = ?", (identity,)
        ).fetchone()
        return row is not None

    def add_message(self, message, source_path):
        now = _utc_now()
        new_publications = []
        with self.connection:
            self.connection.execute(
                "INSERT INTO messages(identity, subject, sender, source_path, processed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (message.identity, message.subject, message.sender, str(source_path), now),
            )
            for candidate in message.publications:
                exists = self.connection.execute(
                    "SELECT title FROM publications WHERE doi = ?", (candidate.doi,)
                ).fetchone()
                if exists is None:
                    self.connection.execute(
                        "INSERT INTO publications(doi, title, first_seen_at) VALUES (?, ?, ?)",
                        (candidate.doi, candidate.title, now),
                    )
                    new_publications.append(
                        NewPublication(
                            doi=candidate.doi,
                            title=candidate.title,
                            source_subject=message.subject,
                            source_sender=message.sender,
                        )
                    )
                elif not exists[0] and candidate.title:
                    self.connection.execute(
                        "UPDATE publications SET title = ? WHERE doi = ?",
                        (candidate.title, candidate.doi),
                    )
                self.connection.execute(
                    "INSERT OR IGNORE INTO message_publications(message_identity, publication_doi) "
                    "VALUES (?, ?)",
                    (message.identity, candidate.doi),
                )
        return tuple(new_publications)

    def publication_count(self):
        return self.connection.execute("SELECT COUNT(*) FROM publications").fetchone()[0]

    def message_count(self):
        return self.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
