"""PostgreSQL-backed literature repository.

Requires QIYAN_STATE_BACKEND="postgresql", the optional ``postgresql``
dependency group, and a running PostgreSQL/pgvector instance.
"""

import json
import os
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.repositories.literature import normalize_literature_item_payload
from app.repositories.postgres_common import create_postgres_pool, ensure_postgres_schema
from app.schemas.literature import LiteratureItem, PdfParseResult

_POSTGRES_DSN_ENV = "QIYAN_POSTGRES_DSN"
_DEFAULT_DSN = "postgresql://qiyan_dev:qiyan_dev_pass@localhost:5432/qiyan_nexus"
_JSONB_COLUMNS = frozenset(
    {"authors", "keywords", "evidence_tags", "related_entity_ids", "pdf_parse_result"}
)
_LITERATURE_COLUMNS = [
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


def _get_dsn() -> str:
    """Get PostgreSQL connection string from environment or use default."""
    return os.getenv(_POSTGRES_DSN_ENV, _DEFAULT_DSN)


def _as_jsonb(value: Any, fallback: Any) -> Jsonb:
    """Wrap a Python value for JSONB binding, filling missing list defaults."""
    if value is None:
        value = fallback
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, PdfParseResult):
        value = value.model_dump()
    return Jsonb(value)


def _prepare_value(column: str, value: Any) -> Any:
    if column == "pdf_parse_result":
        return _as_jsonb(value, None) if value is not None else None
    if column in _JSONB_COLUMNS:
        return _as_jsonb(value, [])
    return value


def _row_to_item(row: dict[str, Any]) -> LiteratureItem:
    """Convert a database row dict to a LiteratureItem."""
    row.pop("created_at", None)
    row.pop("updated_at", None)
    for ts_field in ["pdf_parse_started_at", "pdf_parse_finished_at"]:
        if row.get(ts_field) is not None and not isinstance(row[ts_field], str):
            row[ts_field] = row[ts_field].isoformat()

    if row.get("pdf_parse_result") is not None:
        if isinstance(row["pdf_parse_result"], str):
            row["pdf_parse_result"] = json.loads(row["pdf_parse_result"])
        row["pdf_parse_result"] = PdfParseResult(**row["pdf_parse_result"])

    return LiteratureItem(**normalize_literature_item_payload(row))


def bootstrap_literature_seed_if_empty(pool: ConnectionPool[Any], seed_path: Path | None) -> None:
    """Load literature seed JSON into PostgreSQL if the table has no rows."""
    with pool.connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM literature").fetchone()
        if count is not None and count[0] > 0:
            return
        if seed_path is None:
            from app.repositories.runtime_storage import resolve_literature_storage_path

            seed_path = resolve_literature_storage_path()
        raw_items: list[dict[str, Any]] = json.loads(seed_path.read_text(encoding="utf-8"))
        columns = ", ".join(_LITERATURE_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_LITERATURE_COLUMNS))
        with conn.cursor() as cur:
            for item in raw_items:
                values = [
                    _prepare_value(column, item.get(column)) for column in _LITERATURE_COLUMNS
                ]
                cur.execute(
                    f"INSERT INTO literature ({columns}) VALUES ({placeholders})",
                    values,
                )
        conn.commit()


class PostgresLiteratureRepository:
    """PostgreSQL-backed literature repository using psycopg (psycopg3)."""

    def __init__(self, dsn: str | None = None, seed_path: Path | None = None) -> None:
        """Initialize repository with connection pool."""
        self._dsn = dsn or _get_dsn()
        self._seed_path = seed_path
        self._pool: ConnectionPool[Any] | None = None
        self._bootstrapped = False

    def _get_pool(self) -> ConnectionPool[Any]:
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = create_postgres_pool(self._dsn)
            ensure_postgres_schema(self._pool)
        if not self._bootstrapped:
            self._bootstrap_from_seed_if_empty()
            self._bootstrapped = True
        return self._pool

    def _bootstrap_from_seed_if_empty(self) -> None:
        """Load the runtime/seed JSON into PostgreSQL when the table is empty."""
        if self._pool is None:
            return
        bootstrap_literature_seed_if_empty(self._pool, self._seed_path)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def list_items(self) -> list[LiteratureItem]:
        """List all literature items."""
        with self._get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM literature ORDER BY year DESC, id")
                rows = cur.fetchall()
                return [_row_to_item(dict(row)) for row in rows]

    def get_item_by_id(self, item_id: str) -> LiteratureItem | None:
        """Get a single literature item by ID."""
        with self._get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM literature WHERE id = %s", (item_id,))
                row = cur.fetchone()
                return _row_to_item(dict(row)) if row else None

    def update_pdf_metadata(
        self,
        literature_id: str,
        pdf_upload_id: str,
        pdf_file_name: str,
        pdf_parse_status: str,
    ) -> LiteratureItem | None:
        """Update PDF metadata for a literature item."""
        with self._get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE literature
                    SET pdf_upload_id = %s,
                        pdf_file_name = %s,
                        pdf_parse_status = %s,
                        pdf_parse_message = NULL,
                        pdf_parse_started_at = NULL,
                        pdf_parse_finished_at = NULL,
                        pdf_parse_result = NULL,
                        last_parse_trigger = NULL,
                        parse_attempt_count = 0
                    WHERE id = %s
                    RETURNING *
                    """,
                    (pdf_upload_id, pdf_file_name, pdf_parse_status, literature_id),
                )
                row = cur.fetchone()
                conn.commit()
                return _row_to_item(dict(row)) if row else None

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
        """Update PDF parse status and related fields."""
        with self._get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT pdf_upload_id, pdf_file_name
                    FROM literature
                    WHERE id = %s
                    """,
                    (literature_id,),
                )
                existing = cur.fetchone()
                if (
                    existing is None
                    or existing["pdf_upload_id"] is None
                    or existing["pdf_file_name"] is None
                ):
                    return None
                if (
                    expected_pdf_upload_id is not None
                    and existing["pdf_upload_id"] != expected_pdf_upload_id
                ):
                    return None

                cur.execute(
                    """
                    UPDATE literature
                    SET pdf_parse_status = %s,
                        pdf_parse_message = %s,
                        pdf_parse_started_at = %s,
                        pdf_parse_finished_at = %s,
                        pdf_parse_result = %s,
                        last_parse_trigger = %s,
                        parse_attempt_count = COALESCE(parse_attempt_count, 0) + 1
                    WHERE id = %s AND pdf_upload_id = %s AND pdf_file_name = %s
                    RETURNING *
                    """,
                    (
                        pdf_parse_status,
                        pdf_parse_message,
                        pdf_parse_started_at,
                        pdf_parse_finished_at,
                        Jsonb(pdf_parse_result.model_dump()) if pdf_parse_result else None,
                        last_parse_trigger,
                        literature_id,
                        existing["pdf_upload_id"],
                        existing["pdf_file_name"],
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return _row_to_item(dict(row)) if row else None

    def bulk_upsert_pubmed_items(self, incoming_items: list[dict[str, Any]]) -> tuple[int, int]:
        """Bulk upsert PubMed literature items.

        Returns (created_count, updated_count).
        """
        if not incoming_items:
            return (0, 0)

        created = 0
        updated = 0

        with self._get_pool().connection() as conn:
            with conn.cursor() as cur:
                for item in incoming_items:
                    cur.execute("SELECT id FROM literature WHERE id = %s", (item["id"],))
                    exists = cur.fetchone() is not None

                    if exists:
                        set_clauses: list[str] = []
                        values: list[Any] = []
                        for field_name, value in item.items():
                            if field_name in _PUBMED_FIELDS and field_name != "id":
                                set_clauses.append(f"{field_name} = %s")
                                values.append(_prepare_value(field_name, value))
                        if not set_clauses:
                            updated += 1
                            continue
                        values.append(item["id"])
                        cur.execute(
                            f"UPDATE literature SET {', '.join(set_clauses)} WHERE id = %s",
                            values,
                        )
                        updated += 1
                    else:
                        columns = ", ".join(_LITERATURE_COLUMNS)
                        placeholders = ", ".join(["%s"] * len(_LITERATURE_COLUMNS))
                        values = [
                            _prepare_value(column, item.get(column))
                            for column in _LITERATURE_COLUMNS
                        ]
                        cur.execute(
                            f"INSERT INTO literature ({columns}) VALUES ({placeholders})",
                            values,
                        )
                        created += 1

                conn.commit()

        return (created, updated)
