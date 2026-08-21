import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .mail_parser import publication_identity_from_title
from .models import NewPublication, PublicationCandidate


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

CREATE TABLE IF NOT EXISTS publication_title_aliases (
    title_identity TEXT PRIMARY KEY,
    publication_identity TEXT NOT NULL REFERENCES publications(identity)
);

CREATE TABLE IF NOT EXISTS message_publications (
    message_identity TEXT NOT NULL REFERENCES messages(identity),
    publication_identity TEXT NOT NULL REFERENCES publications(identity),
    PRIMARY KEY (message_identity, publication_identity)
);

CREATE TABLE IF NOT EXISTS publication_metadata (
    publication_identity TEXT PRIMARY KEY REFERENCES publications(identity),
    status TEXT NOT NULL,
    title TEXT,
    abstract TEXT,
    journal TEXT,
    published_date TEXT,
    authors_json TEXT NOT NULL DEFAULT '[]',
    url TEXT,
    checked_at TEXT NOT NULL
);
"""
SCHEMA_VERSION = 3


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
        schema_version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        table_exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'publications'"
        ).fetchone()
        if table_exists is None:
            self.connection.executescript(SCHEMA)
            self.connection.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
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
        self.connection.executescript(SCHEMA)
        if schema_version < SCHEMA_VERSION:
            self._backfill_title_aliases()
            self.connection.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))

    def _backfill_title_aliases(self):
        with self.connection:
            canonical_rows = self.connection.execute(
                "SELECT p.identity, p.doi, p.title, pm.title, "
                "COALESCE(pm.url, p.url) FROM publications p "
                "LEFT JOIN publication_metadata pm "
                "ON pm.publication_identity = p.identity "
                "WHERE p.doi IS NOT NULL "
                "ORDER BY p.first_seen_at, p.identity"
            ).fetchall()
            for identity, doi, publication_title, metadata_title, url in canonical_rows:
                for title in (publication_title, metadata_title):
                    if title:
                        self.connection.execute(
                            "INSERT OR IGNORE INTO publication_title_aliases("
                            "title_identity, publication_identity) VALUES (?, ?)",
                            (publication_identity_from_title(title), identity),
                        )

            provisional_rows = self.connection.execute(
                "SELECT p.identity, p.title, pm.title FROM publications p "
                "LEFT JOIN publication_metadata pm "
                "ON pm.publication_identity = p.identity "
                "WHERE p.doi IS NULL "
                "ORDER BY p.first_seen_at, p.identity"
            ).fetchall()
            for provisional_identity, publication_title, metadata_title in provisional_rows:
                titles = tuple(
                    title for title in (publication_title, metadata_title) if title
                )
                alias = None
                for title in titles:
                    alias = self.connection.execute(
                        "SELECT p.identity, p.doi, p.title, p.url "
                        "FROM publication_title_aliases a "
                        "JOIN publications p "
                        "ON p.identity = a.publication_identity "
                        "WHERE a.title_identity = ? AND p.doi IS NOT NULL",
                        (publication_identity_from_title(title),),
                    ).fetchone()
                    if alias is not None:
                        break
                if alias is not None and alias[1] is not None:
                    self._merge_publication(
                        provisional_identity,
                        PublicationCandidate(
                            identity=alias[0],
                            doi=alias[1],
                            title=alias[2],
                            url=alias[3],
                        ),
                    )
                else:
                    for title in titles:
                        self.connection.execute(
                            "INSERT OR IGNORE INTO publication_title_aliases("
                            "title_identity, publication_identity) VALUES (?, ?)",
                            (
                                publication_identity_from_title(title),
                                provisional_identity,
                            ),
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
        publications_added = 0
        with self.connection:
            self.connection.execute(
                "INSERT INTO messages(identity, subject, sender, source_path, processed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (message.identity, message.subject, message.sender, str(source_path), now),
            )
            for candidate in message.publications:
                publication_identity = self._resolve_publication_identity(candidate)
                exists = self.connection.execute(
                    "SELECT title, url FROM publications WHERE identity = ?",
                    (publication_identity,),
                ).fetchone()
                if exists is None:
                    self.connection.execute(
                        "INSERT INTO publications(identity, doi, title, url, first_seen_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            publication_identity,
                            candidate.doi,
                            candidate.title,
                            candidate.url,
                            now,
                        ),
                    )
                    publications_added += 1
                elif not exists[0] and candidate.title:
                    self.connection.execute(
                        "UPDATE publications SET title = ? WHERE identity = ?",
                        (candidate.title, publication_identity),
                    )
                if exists is not None and not exists[1] and candidate.url:
                    self.connection.execute(
                        "UPDATE publications SET url = ? WHERE identity = ?",
                        (candidate.url, publication_identity),
                    )
                if candidate.title:
                    self.connection.execute(
                        "INSERT OR IGNORE INTO publication_title_aliases("
                        "title_identity, publication_identity) VALUES (?, ?)",
                        (
                            publication_identity_from_title(candidate.title),
                            publication_identity,
                        ),
                    )
                self.connection.execute(
                    "INSERT OR IGNORE INTO message_publications("
                    "message_identity, publication_identity) "
                    "VALUES (?, ?)",
                    (message.identity, publication_identity),
                )
        return publications_added

    def _resolve_publication_identity(self, candidate):
        if not candidate.title:
            return candidate.identity
        title_identity = publication_identity_from_title(candidate.title)
        alias = self.connection.execute(
            "SELECT p.identity, p.doi FROM publication_title_aliases a "
            "JOIN publications p ON p.identity = a.publication_identity "
            "WHERE a.title_identity = ?",
            (title_identity,),
        ).fetchone()
        if alias is None:
            return candidate.identity
        aliased_identity, aliased_doi = alias
        if candidate.doi:
            if aliased_identity != candidate.identity and aliased_doi is None:
                self._merge_publication(aliased_identity, candidate)
            return candidate.identity
        return aliased_identity

    def _merge_publication(self, provisional_identity, candidate):
        provisional = self.connection.execute(
            "SELECT title, url, first_seen_at, delivered_at "
            "FROM publications WHERE identity = ?",
            (provisional_identity,),
        ).fetchone()
        if provisional is None:
            return

        canonical = self.connection.execute(
            "SELECT title, url, first_seen_at, delivered_at "
            "FROM publications WHERE identity = ?",
            (candidate.identity,),
        ).fetchone()
        if canonical is None:
            self.connection.execute(
                "INSERT INTO publications("
                "identity, doi, title, url, first_seen_at, delivered_at"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    candidate.identity,
                    candidate.doi,
                    candidate.title or provisional[0],
                    candidate.url or provisional[1],
                    provisional[2],
                    provisional[3],
                ),
            )
        else:
            self.connection.execute(
                "UPDATE publications SET title = ?, url = ?, first_seen_at = ?, "
                "delivered_at = ? WHERE identity = ?",
                (
                    canonical[0] or candidate.title or provisional[0],
                    canonical[1] or candidate.url or provisional[1],
                    min(canonical[2], provisional[2]),
                    canonical[3] or provisional[3],
                    candidate.identity,
                ),
            )

        self.connection.execute(
            "INSERT OR IGNORE INTO message_publications("
            "message_identity, publication_identity"
            ") SELECT message_identity, ? FROM message_publications "
            "WHERE publication_identity = ?",
            (candidate.identity, provisional_identity),
        )
        self.connection.execute(
            "DELETE FROM message_publications WHERE publication_identity = ?",
            (provisional_identity,),
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO publication_metadata("
            "publication_identity, status, title, abstract, journal, "
            "published_date, authors_json, url, checked_at"
            ") SELECT ?, status, title, abstract, journal, published_date, "
            "authors_json, url, checked_at FROM publication_metadata "
            "WHERE publication_identity = ?",
            (candidate.identity, provisional_identity),
        )
        self.connection.execute(
            "DELETE FROM publication_metadata WHERE publication_identity = ?",
            (provisional_identity,),
        )
        self.connection.execute(
            "UPDATE publication_title_aliases SET publication_identity = ? "
            "WHERE publication_identity = ?",
            (candidate.identity, provisional_identity),
        )
        if candidate.title:
            self.connection.execute(
                "INSERT OR IGNORE INTO publication_title_aliases("
                "title_identity, publication_identity) VALUES (?, ?)",
                (
                    publication_identity_from_title(candidate.title),
                    candidate.identity,
                ),
            )
        self.connection.execute(
            "DELETE FROM publications WHERE identity = ?", (provisional_identity,)
        )

    def publications_to_enrich(self, limit):
        return tuple(
            self.connection.execute(
                "SELECT p.identity, p.doi "
                "FROM publications p "
                "LEFT JOIN publication_metadata pm "
                "ON pm.publication_identity = p.identity "
                "WHERE p.delivered_at IS NULL AND p.doi IS NOT NULL "
                "AND pm.publication_identity IS NULL "
                "ORDER BY p.first_seen_at, p.doi LIMIT ?",
                (limit,),
            ).fetchall()
        )

    def save_metadata(self, identity, metadata):
        with self.connection:
            publication = self.connection.execute(
                "SELECT doi, title, url FROM publications WHERE identity = ?",
                (identity,),
            ).fetchone()
            if publication is not None and publication[0] and metadata.title:
                candidate = PublicationCandidate(
                    identity=identity,
                    doi=publication[0],
                    title=metadata.title,
                    url=metadata.url or publication[2],
                )
                self._resolve_publication_identity(candidate)
                self.connection.execute(
                    "UPDATE publications SET title = COALESCE(title, ?), "
                    "url = COALESCE(url, ?) WHERE identity = ?",
                    (metadata.title, metadata.url, identity),
                )
                self.connection.execute(
                    "INSERT OR IGNORE INTO publication_title_aliases("
                    "title_identity, publication_identity) VALUES (?, ?)",
                    (publication_identity_from_title(metadata.title), identity),
                )
            self.connection.execute(
                "INSERT OR REPLACE INTO publication_metadata("
                "publication_identity, status, title, abstract, journal, "
                "published_date, authors_json, url, checked_at"
                ") VALUES (?, 'success', ?, ?, ?, ?, ?, ?, ?)",
                (
                    identity,
                    metadata.title,
                    metadata.abstract,
                    metadata.journal,
                    metadata.published_date,
                    json.dumps(metadata.authors, ensure_ascii=False),
                    metadata.url,
                    _utc_now(),
                ),
            )

    def save_metadata_not_found(self, identity):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO publication_metadata("
                "publication_identity, status, checked_at"
                ") VALUES (?, 'not_found', ?)",
                (identity, _utc_now()),
            )

    def _load_publications(self, require_metadata, pending_only):
        conditions = []
        if pending_only:
            conditions.append("p.delivered_at IS NULL")
        if require_metadata:
            conditions.append(
                "(p.doi IS NULL OR pm.publication_identity IS NOT NULL)"
            )
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions) + " "
        rows = self.connection.execute(
            "SELECT p.identity, p.doi, COALESCE(pm.title, p.title), "
            "COALESCE(pm.url, p.url), m.subject, m.sender, pm.abstract, "
            "pm.journal, pm.published_date, pm.authors_json, pm.status "
            "FROM publications p "
            "LEFT JOIN publication_metadata pm "
            "ON pm.publication_identity = p.identity "
            "JOIN message_publications mp ON mp.rowid = ("
            "  SELECT MIN(mp2.rowid) FROM message_publications mp2 "
            "  WHERE mp2.publication_identity = p.identity"
            ") "
            "JOIN messages m ON m.identity = mp.message_identity "
            + where_clause
            + "ORDER BY p.first_seen_at, p.doi"
        ).fetchall()
        return tuple(
            NewPublication(
                identity=row[0],
                doi=row[1],
                title=row[2],
                url=row[3],
                source_subject=row[4],
                source_sender=row[5],
                abstract=row[6],
                journal=row[7],
                published_date=row[8],
                authors=tuple(json.loads(row[9] or "[]")),
                metadata_status=row[10],
            )
            for row in rows
        )

    def pending_publications(self, require_metadata=False):
        return self._load_publications(require_metadata, pending_only=True)

    def catalog_publications(self):
        return self._load_publications(require_metadata=False, pending_only=False)

    def pending_count(self):
        return self.connection.execute(
            "SELECT COUNT(*) FROM publications WHERE delivered_at IS NULL"
        ).fetchone()[0]

    def publication_count(self):
        return self.connection.execute(
            "SELECT COUNT(*) FROM publications"
        ).fetchone()[0]

    def mark_delivered(self, publications):
        now = _utc_now()
        with self.connection:
            self.connection.executemany(
                "UPDATE publications SET delivered_at = ? WHERE identity = ?",
                ((now, publication.identity) for publication in publications),
            )
