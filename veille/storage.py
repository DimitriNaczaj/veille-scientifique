import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .mail_parser import publication_identity_from_title
from .models import (
    AIAnalysis,
    NewPublication,
    PublicationCandidate,
    PublicationPriority,
    WorkMetadata,
)


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
    delivery_eligible INTEGER NOT NULL DEFAULT 1,
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

CREATE INDEX IF NOT EXISTS idx_message_publications_publication_identity
ON message_publications(publication_identity);

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

CREATE TABLE IF NOT EXISTS imap_sync_state (
    account TEXT NOT NULL,
    folder TEXT NOT NULL,
    uidvalidity TEXT NOT NULL,
    last_uid INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account, folder, uidvalidity)
);

CREATE TABLE IF NOT EXISTS publication_ai_assessments (
    publication_identity TEXT NOT NULL REFERENCES publications(identity),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    relevant INTEGER NOT NULL,
    priority TEXT NOT NULL,
    summary_fr TEXT NOT NULL,
    bellegarde_value TEXT NOT NULL,
    applications_json TEXT NOT NULL,
    themes_json TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (publication_identity, model, prompt_version)
);

CREATE TABLE IF NOT EXISTS backfill_budget_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_identity TEXT NOT NULL REFERENCES publications(identity),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    cost_upper_bound_usd REAL NOT NULL,
    releasable_cost_usd REAL NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(publication_identity, model, prompt_version)
);
"""
SCHEMA_VERSION = 8


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
        columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(publications)")
        }
        if "delivery_eligible" not in columns:
            self.connection.execute(
                "ALTER TABLE publications ADD COLUMN delivery_eligible "
                "INTEGER NOT NULL DEFAULT 1"
            )
            self.connection.execute(
                "UPDATE publications SET delivery_eligible = 0 "
                "WHERE EXISTS ("
                " SELECT 1 FROM message_publications mp "
                " JOIN messages m ON m.identity = mp.message_identity "
                " WHERE mp.publication_identity = publications.identity"
                ") AND NOT EXISTS ("
                " SELECT 1 FROM message_publications mp "
                " JOIN messages m ON m.identity = mp.message_identity "
                " WHERE mp.publication_identity = publications.identity "
                " AND m.source_path NOT GLOB '*#[0-9][0-9][0-9][0-9][0-9][0-9]'"
                ")"
            )
        reservation_columns = {
            row[1]
            for row in self.connection.execute(
                "PRAGMA table_info(backfill_budget_reservations)"
            )
        }
        if "releasable_cost_usd" not in reservation_columns:
            self.connection.execute(
                "ALTER TABLE backfill_budget_reservations ADD COLUMN "
                "releasable_cost_usd REAL NOT NULL DEFAULT 0"
            )
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

    def imap_last_uid(self, account, folder, uidvalidity):
        row = self.connection.execute(
            "SELECT last_uid FROM imap_sync_state "
            "WHERE account = ? AND folder = ? AND uidvalidity = ?",
            (account, folder, uidvalidity),
        ).fetchone()
        return row[0] if row is not None else None

    def save_imap_last_uid(self, account, folder, uidvalidity, last_uid):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO imap_sync_state("
                "account, folder, uidvalidity, last_uid, updated_at"
                ") VALUES (?, ?, ?, ?, ?)",
                (account, folder, uidvalidity, last_uid, _utc_now()),
            )

    def imap_uidvalidities(self, account, folder):
        return tuple(
            row[0]
            for row in self.connection.execute(
                "SELECT uidvalidity FROM imap_sync_state "
                "WHERE account = ? AND folder = ? ORDER BY updated_at",
                (account, folder),
            ).fetchall()
        )

    def has_message(self, identity):
        row = self.connection.execute(
            "SELECT 1 FROM messages WHERE identity = ?", (identity,)
        ).fetchone()
        return row is not None

    def add_message(self, message, source_path, delivery_eligible=True):
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
                        "INSERT INTO publications(identity, doi, title, url, first_seen_at, "
                        "delivery_eligible) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            publication_identity,
                            candidate.doi,
                            candidate.title,
                            candidate.url,
                            now,
                            1 if delivery_eligible else 0,
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
            "SELECT title, url, first_seen_at, delivered_at, delivery_eligible "
            "FROM publications WHERE identity = ?",
            (provisional_identity,),
        ).fetchone()
        if provisional is None:
            return

        canonical = self.connection.execute(
            "SELECT title, url, first_seen_at, delivered_at, delivery_eligible "
            "FROM publications WHERE identity = ?",
            (candidate.identity,),
        ).fetchone()
        if canonical is None:
            self.connection.execute(
                "INSERT INTO publications("
                "identity, doi, title, url, first_seen_at, delivery_eligible, delivered_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.identity,
                    candidate.doi,
                    candidate.title or provisional[0],
                    candidate.url or provisional[1],
                    provisional[2],
                    provisional[4],
                    provisional[3],
                ),
            )
        else:
            self.connection.execute(
                "UPDATE publications SET title = ?, url = ?, first_seen_at = ?, "
                "delivered_at = ?, delivery_eligible = ? WHERE identity = ?",
                (
                    canonical[0] or candidate.title or provisional[0],
                    canonical[1] or candidate.url or provisional[1],
                    min(canonical[2], provisional[2]),
                    canonical[3] or provisional[3],
                    max(canonical[4], provisional[4]),
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
            "INSERT OR IGNORE INTO publication_ai_assessments("
            "publication_identity, model, prompt_version, relevant, priority, "
            "summary_fr, bellegarde_value, applications_json, themes_json, "
            "input_tokens, output_tokens, checked_at"
            ") SELECT ?, model, prompt_version, relevant, priority, summary_fr, "
            "bellegarde_value, applications_json, themes_json, input_tokens, "
            "output_tokens, checked_at FROM publication_ai_assessments "
            "WHERE publication_identity = ?",
            (candidate.identity, provisional_identity),
        )
        self.connection.execute(
            "DELETE FROM publication_ai_assessments WHERE publication_identity = ?",
            (provisional_identity,),
        )
        reservations = self.connection.execute(
            "SELECT id, model, prompt_version, cost_upper_bound_usd, "
            "releasable_cost_usd, "
            "input_tokens, output_tokens, status, created_at, updated_at "
            "FROM backfill_budget_reservations WHERE publication_identity = ?",
            (provisional_identity,),
        ).fetchall()
        for reservation in reservations:
            existing = self.connection.execute(
                "SELECT id, cost_upper_bound_usd, releasable_cost_usd, "
                "input_tokens, output_tokens, status "
                "FROM backfill_budget_reservations "
                "WHERE publication_identity = ? AND model = ? "
                "AND prompt_version = ?",
                (candidate.identity, reservation[1], reservation[2]),
            ).fetchone()
            if existing is None:
                self.connection.execute(
                    "UPDATE backfill_budget_reservations "
                    "SET publication_identity = ? WHERE id = ?",
                    (candidate.identity, reservation[0]),
                )
            else:
                merged_releasable_cost = existing[2] + reservation[4]
                statuses = {existing[5], reservation[7]}
                if merged_releasable_cost > 0:
                    merged_status = "reserved"
                elif "completed" in statuses:
                    merged_status = "completed"
                else:
                    merged_status = "released"
                self.connection.execute(
                    "UPDATE backfill_budget_reservations SET "
                    "cost_upper_bound_usd = ?, releasable_cost_usd = ?, "
                    "input_tokens = ?, output_tokens = ?, status = ?, "
                    "updated_at = ? "
                    "WHERE id = ?",
                    (
                        existing[1] + reservation[3],
                        merged_releasable_cost,
                        existing[3] + reservation[5],
                        existing[4] + reservation[6],
                        merged_status,
                        max(reservation[9], _utc_now()),
                        existing[0],
                    ),
                )
                self.connection.execute(
                    "DELETE FROM backfill_budget_reservations WHERE id = ?",
                    (reservation[0],),
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
                "SELECT p.identity, p.doi, p.url "
                "FROM publications p "
                "LEFT JOIN publication_metadata pm "
                "ON pm.publication_identity = p.identity "
                "WHERE p.delivery_eligible = 1 AND p.delivered_at IS NULL "
                "AND (p.doi IS NOT NULL OR p.url IS NOT NULL) "
                "AND (pm.publication_identity IS NULL "
                "OR pm.status = 'crossref_incomplete' "
                "OR pm.status = 'crossref_not_found' "
                "OR (pm.status = 'success' AND pm.abstract IS NULL)) "
                "ORDER BY p.first_seen_at, p.identity LIMIT ?",
                (limit,),
            ).fetchall()
        )

    def backfill_publications_to_enrich(self, limit):
        return tuple(
            self.connection.execute(
                "SELECT p.identity, p.doi, p.url "
                "FROM publications p "
                "LEFT JOIN publication_metadata pm "
                "ON pm.publication_identity = p.identity "
                "WHERE p.delivery_eligible = 0 AND p.delivered_at IS NULL "
                "AND (p.doi IS NOT NULL OR p.url IS NOT NULL) "
                "AND pm.publication_identity IS NULL "
                "ORDER BY p.first_seen_at, p.identity LIMIT ?",
                (limit,),
            ).fetchall()
        )

    def metadata_without_abstract(self, limit):
        """Entrées déjà enrichies mais sans résumé, réinterrogeables par DOI.

        La sélection automatique ignore volontairement les publications déjà
        pourvues d’une ligne de métadonnées : sans cela, un article
        définitivement sans résumé serait réinterrogé à chaque exécution et
        épuiserait le quota au détriment des nouveautés. Cette reprise est
        donc explicite et bornée.
        """
        return tuple(
            self.connection.execute(
                "SELECT p.identity, p.doi, p.url "
                "FROM publication_metadata pm "
                "JOIN publications p ON p.identity = pm.publication_identity "
                "WHERE pm.abstract IS NULL "
                "AND (p.doi IS NOT NULL OR p.url IS NOT NULL) "
                "ORDER BY pm.checked_at, p.identity LIMIT ?",
                (limit,),
            ).fetchall()
        )

    def metadata_without_abstract_count(self):
        return self.connection.execute(
            "SELECT COUNT(*) FROM publication_metadata pm "
            "JOIN publications p ON p.identity = pm.publication_identity "
            "WHERE pm.abstract IS NULL "
            "AND (p.doi IS NOT NULL OR p.url IS NOT NULL)"
        ).fetchone()[0]

    def backfill_enrichment_pending_count(self):
        return self.connection.execute(
            "SELECT COUNT(*) FROM publications p "
            "LEFT JOIN publication_metadata pm "
            "ON pm.publication_identity = p.identity "
            "WHERE p.delivery_eligible = 0 AND p.delivered_at IS NULL "
            "AND (p.doi IS NOT NULL OR p.url IS NOT NULL) "
            "AND pm.publication_identity IS NULL"
        ).fetchone()[0]

    def backfill_metadata_identities(self):
        return {
            row[0]
            for row in self.connection.execute(
                "SELECT pm.publication_identity FROM publication_metadata pm "
                "JOIN publications p ON p.identity = pm.publication_identity "
                "WHERE p.delivery_eligible = 0 AND p.delivered_at IS NULL"
            ).fetchall()
        }

    def backfill_metadata_statuses(self):
        return dict(
            self.connection.execute(
                "SELECT pm.publication_identity, pm.status "
                "FROM publication_metadata pm "
                "JOIN publications p ON p.identity = pm.publication_identity "
                "WHERE p.delivery_eligible = 0 AND p.delivered_at IS NULL"
            ).fetchall()
        )

    def load_metadata(self, identity):
        row = self.connection.execute(
            "SELECT title, abstract, journal, published_date, authors_json, url "
            "FROM publication_metadata WHERE publication_identity = ?",
            (identity,),
        ).fetchone()
        if row is None:
            return None
        return WorkMetadata(
            title=row[0],
            abstract=row[1],
            journal=row[2],
            published_date=row[3],
            authors=tuple(json.loads(row[4] or "[]")),
            url=row[5],
        )

    def metadata_status(self, identity):
        row = self.connection.execute(
            "SELECT status FROM publication_metadata WHERE publication_identity = ?",
            (identity,),
        ).fetchone()
        return row[0] if row is not None else None

    def save_metadata(self, identity, metadata, status=None):
        status = status or ("success" if metadata.abstract else "incomplete")
        if status not in ("success", "incomplete", "crossref_incomplete"):
            raise ValueError("Statut de métadonnées invalide.")
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
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identity,
                    status,
                    metadata.title,
                    metadata.abstract,
                    metadata.journal,
                    metadata.published_date,
                    json.dumps(metadata.authors, ensure_ascii=False),
                    metadata.url,
                    _utc_now(),
                ),
            )

    def save_metadata_not_found(self, identity, status="not_found"):
        if status not in (
            "not_found",
            "crossref_not_found",
            "elsevier_not_found",
        ):
            raise ValueError("Statut de métadonnées introuvables invalide.")
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO publication_metadata("
                "publication_identity, status, checked_at"
                ") VALUES (?, ?, ?)",
                (identity, status, _utc_now()),
            )

    def load_ai_assessment(self, identity, model, prompt_version):
        row = self.connection.execute(
            "SELECT relevant, priority, summary_fr, bellegarde_value, "
            "applications_json, themes_json, input_tokens, output_tokens "
            "FROM publication_ai_assessments WHERE publication_identity = ? "
            "AND model = ? AND prompt_version = ?",
            (identity, model, prompt_version),
        ).fetchone()
        if row is None:
            return None
        return AIAnalysis(
            relevant=bool(row[0]),
            priority=PublicationPriority(row[1]),
            summary_fr=row[2],
            bellegarde_value=row[3],
            applications=tuple(json.loads(row[4])),
            themes=tuple(json.loads(row[5])),
            input_tokens=row[6],
            output_tokens=row[7],
            model=model,
            prompt_version=prompt_version,
        )

    def save_ai_assessment(self, identity, analysis):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO publication_ai_assessments("
                "publication_identity, model, prompt_version, relevant, priority, "
                "summary_fr, bellegarde_value, applications_json, themes_json, "
                "input_tokens, output_tokens, checked_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identity,
                    analysis.model,
                    analysis.prompt_version,
                    1 if analysis.relevant else 0,
                    analysis.priority.value,
                    analysis.summary_fr,
                    analysis.bellegarde_value,
                    json.dumps(analysis.applications, ensure_ascii=False),
                    json.dumps(analysis.themes, ensure_ascii=False),
                    analysis.input_tokens,
                    analysis.output_tokens,
                    _utc_now(),
                ),
            )

    def backfill_unreserved_ai_usage(self):
        row = self.connection.execute(
            "SELECT COALESCE(SUM(a.input_tokens), 0), "
            "COALESCE(SUM(a.output_tokens), 0) "
            "FROM publication_ai_assessments a "
            "JOIN publications p ON p.identity = a.publication_identity "
            "LEFT JOIN backfill_budget_reservations r "
            "ON r.publication_identity = a.publication_identity "
            "AND r.model = a.model AND r.prompt_version = a.prompt_version "
            "WHERE p.delivery_eligible = 0 AND r.id IS NULL",
        ).fetchone()
        return int(row[0]), int(row[1])

    def backfill_budget_usage(self):
        row = self.connection.execute(
            "SELECT COALESCE(SUM(cost_upper_bound_usd), 0), "
            "COALESCE(SUM(input_tokens), 0), "
            "COALESCE(SUM(output_tokens), 0) "
            "FROM backfill_budget_reservations"
        ).fetchone()
        return float(row[0]), int(row[1]), int(row[2])

    def reserve_backfill_budget(
        self,
        publication_identity,
        model,
        prompt_version,
        maximum_cost_usd,
        total_budget_usd,
        legacy_cost_usd,
    ):
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT id, status FROM backfill_budget_reservations "
                "WHERE publication_identity = ? AND model = ? "
                "AND prompt_version = ?",
                (publication_identity, model, prompt_version),
            ).fetchone()
            reserved = float(
                self.connection.execute(
                    "SELECT COALESCE(SUM(cost_upper_bound_usd), 0) "
                    "FROM backfill_budget_reservations"
                ).fetchone()[0]
            )
            if existing is not None:
                if existing[1] == "released":
                    if (
                        reserved + legacy_cost_usd + maximum_cost_usd
                        > total_budget_usd
                    ):
                        self.connection.commit()
                        return None, "budget"
                    now = _utc_now()
                    self.connection.execute(
                        "UPDATE backfill_budget_reservations SET "
                        "cost_upper_bound_usd = ?, releasable_cost_usd = ?, "
                        "input_tokens = 0, output_tokens = 0, "
                        "status = 'reserved', "
                        "updated_at = ? WHERE id = ?",
                        (maximum_cost_usd, maximum_cost_usd, now, existing[0]),
                    )
                    self.connection.commit()
                    return existing[0], "reserved"
                self.connection.commit()
                return existing[0], "existing"
            if reserved + legacy_cost_usd + maximum_cost_usd > total_budget_usd:
                self.connection.commit()
                return None, "budget"
            now = _utc_now()
            cursor = self.connection.execute(
                "INSERT INTO backfill_budget_reservations("
                "publication_identity, model, prompt_version, "
                "cost_upper_bound_usd, releasable_cost_usd, status, "
                "created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?)",
                (
                    publication_identity,
                    model,
                    prompt_version,
                    maximum_cost_usd,
                    maximum_cost_usd,
                    now,
                    now,
                ),
            )
            self.connection.commit()
            return cursor.lastrowid, "reserved"
        except Exception:
            self.connection.rollback()
            raise

    def release_backfill_budget_reservation(self, reservation_id):
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            reservation = self.connection.execute(
                "SELECT publication_identity, cost_upper_bound_usd, "
                "releasable_cost_usd, status "
                "FROM backfill_budget_reservations WHERE id = ?",
                (reservation_id,),
            ).fetchone()
            if reservation is None or reservation[3] != "reserved":
                self.connection.commit()
                return None
            retained_cost = max(0.0, reservation[1] - reservation[2])
            status = "completed" if retained_cost > 0 else "released"
            self.connection.execute(
                "UPDATE backfill_budget_reservations SET "
                "cost_upper_bound_usd = ?, releasable_cost_usd = 0, "
                "status = ?, updated_at = ? WHERE id = ?",
                (retained_cost, status, _utc_now(), reservation_id),
            )
            self.connection.commit()
            return reservation[0]
        except Exception:
            self.connection.rollback()
            raise

    def complete_backfill_budget_reservation(
        self,
        reservation_id,
        cost_upper_bound_usd,
        input_tokens,
        output_tokens,
    ):
        with self.connection:
            self.connection.execute(
                "UPDATE backfill_budget_reservations SET "
                "cost_upper_bound_usd = ?, releasable_cost_usd = 0, "
                "input_tokens = ?, output_tokens = ?, status = 'completed', "
                "updated_at = ? WHERE id = ?",
                (
                    cost_upper_bound_usd,
                    input_tokens,
                    output_tokens,
                    _utc_now(),
                    reservation_id,
                ),
            )

    def _load_publications(self, require_metadata, pending_only, backfill_only=False):
        conditions = []
        if pending_only:
            conditions.append("p.delivery_eligible = 1 AND p.delivered_at IS NULL")
        if backfill_only:
            conditions.append("p.delivery_eligible = 0 AND p.delivered_at IS NULL")
        if require_metadata:
            conditions.append(
                "(p.doi IS NULL OR (pm.publication_identity IS NOT NULL "
                "AND pm.status NOT IN ('crossref_incomplete', "
                "'crossref_not_found')))"
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

    def backfill_publications(self):
        return self._load_publications(
            require_metadata=False,
            pending_only=False,
            backfill_only=True,
        )

    def pending_count(self):
        return self.connection.execute(
            "SELECT COUNT(*) FROM publications "
            "WHERE delivery_eligible = 1 AND delivered_at IS NULL"
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
