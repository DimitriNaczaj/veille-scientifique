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
    identity TEXT PRIMARY KEY,
    doi TEXT UNIQUE,
    title TEXT,
    url TEXT,
    first_seen_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS message_publications (
    message_identity TEXT NOT NULL REFERENCES messages(identity),
    publication_identity TEXT NOT NULL REFERENCES publications(identity),
    PRIMARY KEY (message_identity, publication_identity)
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
        self._ensure_schema()

    def _ensure_schema(self):
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'publications'"
        ).fetchone()
        if table_exists is None:
            self.connection.executescript(SCHEMA)
            return

        columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(publications)")
        }
        if "identity" not in columns:
            delivered_value = "delivered_at" if "delivered_at" in columns else "NULL"
            self.connection.executescript(
                """
                PRAGMA foreign_keys = OFF;
                BEGIN;
                ALTER TABLE message_publications RENAME TO message_publications_v1;
                ALTER TABLE publications RENAME TO publications_v1;

                CREATE TABLE publications (
                    identity TEXT PRIMARY KEY,
                    doi TEXT UNIQUE,
                    title TEXT,
                    url TEXT,
                    first_seen_at TEXT NOT NULL,
                    delivered_at TEXT
                );
                CREATE TABLE message_publications (
                    message_identity TEXT NOT NULL REFERENCES messages(identity),
                    publication_identity TEXT NOT NULL REFERENCES publications(identity),
                    PRIMARY KEY (message_identity, publication_identity)
                );

                INSERT INTO publications(identity, doi, title, url, first_seen_at, delivered_at)
                SELECT 'doi:' || lower(doi), lower(doi), title, NULL, first_seen_at, {delivered}
                FROM publications_v1;
                INSERT INTO message_publications(message_identity, publication_identity)
                SELECT message_identity, 'doi:' || lower(publication_doi)
                FROM message_publications_v1;

                DROP TABLE message_publications_v1;
                DROP TABLE publications_v1;
                COMMIT;
                PRAGMA foreign_keys = ON;
                """.format(delivered=delivered_value)
            )
        else:
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
        with self.connection:
            self.connection.execute(
                "INSERT INTO messages(identity, subject, sender, source_path, processed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (message.identity, message.subject, message.sender, str(source_path), now),
            )
            for candidate in message.publications:
                exists = self.connection.execute(
                    "SELECT title, url FROM publications WHERE identity = ?",
                    (candidate.identity,),
                ).fetchone()
                if exists is None:
                    self.connection.execute(
                        "INSERT INTO publications(identity, doi, title, url, first_seen_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            candidate.identity,
                            candidate.doi,
                            candidate.title,
                            candidate.url,
                            now,
                        ),
                    )
                elif not exists[0] and candidate.title:
                    self.connection.execute(
                        "UPDATE publications SET title = ? WHERE identity = ?",
                        (candidate.title, candidate.identity),
                    )
                if exists is not None and not exists[1] and candidate.url:
                    self.connection.execute(
                        "UPDATE publications SET url = ? WHERE identity = ?",
                        (candidate.url, candidate.identity),
                    )
                self.connection.execute(
                    "INSERT OR IGNORE INTO message_publications("
                    "message_identity, publication_identity) "
                    "VALUES (?, ?)",
                    (message.identity, candidate.identity),
                )
    def pending_publications(self):
        rows = self.connection.execute(
            "SELECT p.identity, p.doi, p.title, p.url, m.subject, m.sender "
            "FROM publications p "
            "JOIN message_publications mp ON mp.rowid = ("
            "  SELECT MIN(mp2.rowid) FROM message_publications mp2 "
            "  WHERE mp2.publication_identity = p.identity"
            ") "
            "JOIN messages m ON m.identity = mp.message_identity "
            "WHERE p.delivered_at IS NULL "
            "ORDER BY p.first_seen_at, p.doi"
        ).fetchall()
        return tuple(
            NewPublication(
                identity=row[0],
                doi=row[1],
                title=row[2],
                url=row[3],
                source_subject=row[4],
                source_sender=row[5],
            )
            for row in rows
        )

    def mark_delivered(self, publications):
        now = _utc_now()
        with self.connection:
            self.connection.executemany(
                "UPDATE publications SET delivered_at = ? WHERE identity = ?",
                ((now, publication.identity) for publication in publications),
            )
