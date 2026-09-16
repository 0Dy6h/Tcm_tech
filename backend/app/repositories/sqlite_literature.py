"""SQLite-backed literature repository.

Uses only the Python standard library ``sqlite3`` module — zero new
dependencies.  The database file is created on first use and bootstrapped
from the same seed JSON that ``InMemoryLiteratureRepository`` reads.
"""

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from app.repositories.literature import normalize_literature_item_payload
from app.schemas.literature import LiteratureItem, PdfParseResult

# Columns stored as JSON TEXT (de/serialised with json.dumps / json.loads).
_JSON_COLUMNS = frozenset(
    {"authors", "keywords", "evidence_tags", "related_entity_ids", "pdf_parse_result"}
)

# PubMed-owned fields that bulk_upsert overwrites on existing rows.
_PUBMED_FIELDS = frozenset(
    {
        "title",
        "abstract",
        "authors",
        "year",
        "keywords",
        "source",
        "snippet",
        "citation_url",
        "doi",
        "pubmed_id",
        "language",
        "source_type",
        "evidence_tags",
    }
)

# Allowed column names for SQL query construction (security: prevent injection)
_ALLOWED_COLUMNS = frozenset(
    {
        "id",
        "title",
        "language",
        "source_type",
        "source",
        "year",
        "snippet",
        "authors",
        "keywords",
        "evidence_tags",
        "abstract",
        "citation_url",
        "pubmed_id",
        "doi",
        "pdf_upload_id",
        "pdf_file_name",
        "pdf_parse_status",
        "pdf_parse_message",
        "pdf_parse_started_at",
        "pdf_parse_finished_at",
        "pdf_parse_result",
        "last_parse_trigger",
        "parse_attempt_count",
        "related_entity_ids",
    }
)

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS literature (
    id                    TEXT PRIMARY KEY,
    title                 TEXT NOT NULL,
    language              TEXT NOT NULL,
    source_type           TEXT NOT NULL,
    source                TEXT NOT NULL,
    year                  INTEGER NOT NULL,
    snippet               TEXT NOT NULL,
    authors               TEXT NOT NULL DEFAULT '[]',
    keywords              TEXT NOT NULL DEFAULT '[]',
    evidence_tags         TEXT NOT NULL DEFAULT '[]',
    abstract              TEXT,
    citation_url          TEXT,
    pubmed_id             TEXT,
    doi                   TEXT,
    pdf_upload_id         TEXT,
    pdf_file_name         TEXT,
    pdf_parse_status      TEXT,
    pdf_parse_message     TEXT,
    pdf_parse_started_at  TEXT,
    pdf_parse_finished_at TEXT,
    pdf_parse_result      TEXT,
    last_parse_trigger    TEXT,
    parse_attempt_count   INTEGER,
    related_entity_ids    TEXT NOT NULL DEFAULT '[]'
)
"""


def _row_to_item(row: sqlite3.Row) -> LiteratureItem:
    """Convert a database row to a ``LiteratureItem``."""
    data: dict[str, Any] = dict(row)
    for col in _JSON_COLUMNS:
        val = data[col]
        if isinstance(val, str):
            data[col] = json.loads(val)
    # pdf_parse_result may be None → keep None
    if data.get("pdf_parse_result") is not None:
        data["pdf_parse_result"] = PdfParseResult(**data["pdf_parse_result"])
    return LiteratureItem(**normalize_literature_item_payload(data))


def _validate_column_names(columns: list[str]) -> None:
    """Validate that all column names are in the allowed whitelist.

    Raises ValueError if any column name is not in _ALLOWED_COLUMNS.
    This prevents potential SQL injection if column names ever come from external input.
    """
    for col in columns:
        if col not in _ALLOWED_COLUMNS:
            raise ValueError(
                f"Invalid column name: {col!r}. "
                f"Column names must be from the fixed whitelist defined in _ALLOWED_COLUMNS."
            )


class SqliteLiteratureRepository:
    """Literature repository backed by a local SQLite database."""

    def __init__(self, db_path: Path, seed_path: Path | None = None) -> None:
        self._db_path = db_path
        self._lock = RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._closed = False
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_TABLE_SQL)
            self._conn.commit()

            # Bootstrap from seed JSON if the table is empty.
            count = self._conn.execute("SELECT COUNT(*) FROM literature").fetchone()[0]
            if count == 0:
                self._bootstrap_from_seed(seed_path)

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def _bootstrap_from_seed(self, seed_path: Path | None = None) -> None:
        """Load seed data from the standard literature JSON file.

        If *seed_path* is provided, use it directly; otherwise fall back to
        ``resolve_literature_storage_path()``.
        """
        if seed_path is None:
            from app.repositories.runtime_storage import resolve_literature_storage_path

            seed_path = resolve_literature_storage_path()

        raw_items: list[dict[str, Any]] = json.loads(seed_path.read_text(encoding="utf-8"))
        with self._lock:
            for item in raw_items:
                self._insert_item(item)
            self._conn.commit()

    def _insert_item(self, item: dict[str, Any]) -> None:
        """Insert a single item dict into the database."""
        # Ensure list fields are JSON-encoded strings.
        for col in ("authors", "keywords", "evidence_tags", "related_entity_ids"):
            val = item.get(col, [])
            item[col] = json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val

        # pdf_parse_result: model or dict → JSON string
        pr = item.get("pdf_parse_result")
        if pr is not None:
            if isinstance(pr, PdfParseResult):
                pr = pr.model_dump()
            item["pdf_parse_result"] = json.dumps(pr, ensure_ascii=False)

        columns = [
            "id",
            "title",
            "language",
            "source_type",
            "source",
            "year",
            "snippet",
            "authors",
            "keywords",
            "evidence_tags",
            "abstract",
            "citation_url",
            "pubmed_id",
            "doi",
            "pdf_upload_id",
            "pdf_file_name",
            "pdf_parse_status",
            "pdf_parse_message",
            "pdf_parse_started_at",
            "pdf_parse_finished_at",
            "pdf_parse_result",
            "last_parse_trigger",
            "parse_attempt_count",
            "related_entity_ids",
        ]
        _validate_column_names(columns)  # Security: validate before SQL construction
        values = [item.get(c) for c in columns]
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(columns)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO literature ({col_names}) VALUES ({placeholders})",
                values,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection.

        Safe to call multiple times. The factory calls this when swapping a
        cached repository, and tests call it on teardown to avoid leaking
        connections / file locks on Windows.
        """
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __del__(self) -> None:
        self.close()

    def list_items(self) -> list[LiteratureItem]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM literature").fetchall()
            return [_row_to_item(row) for row in rows]

    def get_item_by_id(self, item_id: str) -> LiteratureItem | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM literature WHERE id = ?", (item_id,)).fetchone()
            return _row_to_item(row) if row else None

    def update_pdf_metadata(
        self,
        literature_id: str,
        pdf_upload_id: str,
        pdf_file_name: str,
        pdf_parse_status: str,
    ) -> LiteratureItem | None:
        with self._lock:
            self._conn.execute(
                """UPDATE literature
                   SET pdf_upload_id = ?,
                       pdf_file_name = ?,
                       pdf_parse_status = ?,
                       pdf_parse_message = NULL,
                       pdf_parse_started_at = NULL,
                       pdf_parse_finished_at = NULL,
                       pdf_parse_result = NULL,
                       last_parse_trigger = NULL,
                       parse_attempt_count = 0
                   WHERE id = ?""",
                (pdf_upload_id, pdf_file_name, pdf_parse_status, literature_id),
            )
            self._conn.commit()
            return self.get_item_by_id(literature_id)

    def update_pdf_parse_status(
        self,
        literature_id: str,
        pdf_parse_status: str,
        pdf_parse_message: str | None = None,
        pdf_parse_started_at: str | None = None,
        pdf_parse_finished_at: str | None = None,
        pdf_parse_result: PdfParseResult | None = None,
        last_parse_trigger: str | None = None,
        expected_pdf_upload_id: str | None = None,
    ) -> LiteratureItem | None:
        with self._lock:
            # Guard: must have pdf_upload_id and pdf_file_name
            row = self._conn.execute(
                "SELECT pdf_upload_id, pdf_file_name FROM literature WHERE id = ?",
                (literature_id,),
            ).fetchone()
            if row is None or row["pdf_upload_id"] is None or row["pdf_file_name"] is None:
                return None
            if (
                expected_pdf_upload_id is not None
                and row["pdf_upload_id"] != expected_pdf_upload_id
            ):
                return None

            pr_json: str | None = None
            if pdf_parse_result is not None:
                pr_json = json.dumps(pdf_parse_result.model_dump(), ensure_ascii=False)

            cursor = self._conn.execute(
                """UPDATE literature
                   SET pdf_parse_status = ?,
                       pdf_parse_message = ?,
                       pdf_parse_started_at = ?,
                       pdf_parse_finished_at = ?,
                       pdf_parse_result = ?,
                       last_parse_trigger = ?,
                       parse_attempt_count = COALESCE(parse_attempt_count, 0) + 1
                   WHERE id = ? AND pdf_upload_id = ? AND pdf_file_name = ?
                   RETURNING *""",
                (
                    pdf_parse_status,
                    pdf_parse_message,
                    pdf_parse_started_at,
                    pdf_parse_finished_at,
                    pr_json,
                    last_parse_trigger,
                    literature_id,
                    row["pdf_upload_id"],
                    row["pdf_file_name"],
                ),
            )
            updated = cursor.fetchone()
            self._conn.commit()
            return _row_to_item(updated) if updated is not None else None

    def bulk_upsert_pubmed_items(self, incoming_items: list[dict[str, Any]]) -> tuple[int, int]:
        with self._lock:
            created = 0
            updated = 0
            try:
                for incoming in incoming_items:
                    item_id = incoming["id"]
                    existing_row = self._conn.execute(
                        "SELECT id FROM literature WHERE id = ?", (item_id,)
                    ).fetchone()

                    if existing_row is not None:
                        # UPDATE: only overwrite PubMed-owned fields
                        set_clauses: list[str] = []
                        set_values: list[Any] = []
                        for field_name, value in incoming.items():
                            if field_name in _PUBMED_FIELDS and field_name != "id":
                                if field_name in _JSON_COLUMNS:
                                    value = json.dumps(value, ensure_ascii=False)
                                set_clauses.append(f"{field_name} = ?")
                                set_values.append(value)
                        if set_clauses:
                            self._conn.execute(
                                f"UPDATE literature SET {', '.join(set_clauses)} WHERE id = ?",
                                (*set_values, item_id),
                            )
                        updated += 1
                    else:
                        # INSERT new row
                        self._insert_item(dict(incoming))
                        created += 1

                self._conn.commit()
                return created, updated
            except Exception:
                self._conn.rollback()
                raise
