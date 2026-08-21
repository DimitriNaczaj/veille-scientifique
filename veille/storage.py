import sqlite3
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
    first_seen_at TEXT NOT NULL,
    delivered_at TEXT
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
        columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(publications)")
        }
        if "delivered_at" not in columns:
            with self.connection:
                self.connection.execute(
                    "ALTER TABLE publications ADD COLUMN delivered_at TEXT"
                )

    def close(self):
        self.connection.close()

    def has_message(self, identity):
        row = self.connection.execute(
            "SELECT 1 FROM messages WHERE identity = ?", (identity,)
        ).fetchone()
        return row is not None

    def add_message(self, message, source_path):
        now = _utc_now()
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
    def pending_publications(self):
        rows = self.connection.execute(
            "SELECT p.doi, p.title, m.subject, m.sender "
            "FROM publications p "
            "JOIN message_publications mp ON mp.rowid = ("
            "  SELECT MIN(mp2.rowid) FROM message_publications mp2 "
            "  WHERE mp2.publication_doi = p.doi"
            ") "
            "JOIN messages m ON m.identity = mp.message_identity "
            "WHERE p.delivered_at IS NULL "
            "ORDER BY p.first_seen_at, p.doi"
        ).fetchall()
        return tuple(
            NewPublication(
                doi=row[0],
                title=row[1],
                source_subject=row[2],
                source_sender=row[3],
            )
            for row in rows
        )

    def mark_delivered(self, publications):
        now = _utc_now()
        with self.connection:
            self.connection.executemany(
                "UPDATE publications SET delivered_at = ? WHERE doi = ?",
                ((now, publication.doi) for publication in publications),
            )
