"""SQLite-backed network task repository.

Uses only the Python standard library ``sqlite3`` module — zero new
dependencies.  The database file is shared with other repositories
(literature, chunk) via ``resolve_sqlite_db_path()``; each repository
creates its own table with ``CREATE TABLE IF NOT EXISTS``.
"""

import json
import sqlite3
from _thread import RLock as RLockType
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import TypeAdapter

from app.core.canonical_json import canonical_json_sha256
from app.repositories.protocols import _tag_with_audit_hmac
from app.schemas.network import (
    AnalysisType,
    DataMode,
    NetworkAnalysisResult,
    NetworkAssemblyConsumptionRecord,
    NetworkAssemblyOutput,
    NetworkAssemblyPlan,
    NetworkCompoundTargetSnapshot,
    NetworkDiseaseTargetSnapshot,
    NetworkResearchProtocol,
    NetworkTargetAdjudication,
    NetworkTaskRecord,
    TaskStatus,
)

_DISEASE_TARGET_SNAPSHOT_ADAPTER: TypeAdapter[NetworkDiseaseTargetSnapshot] = TypeAdapter(
    NetworkDiseaseTargetSnapshot
)
_COMPOUND_TARGET_SNAPSHOT_ADAPTER: TypeAdapter[NetworkCompoundTargetSnapshot] = TypeAdapter(
    NetworkCompoundTargetSnapshot
)
_ADJUDICATION_LIST_ADAPTER: TypeAdapter[list[NetworkTargetAdjudication]] = TypeAdapter(
    list[NetworkTargetAdjudication]
)
_CONSUMPTION_LIST_ADAPTER: TypeAdapter[list[NetworkAssemblyConsumptionRecord]] = TypeAdapter(
    list[NetworkAssemblyConsumptionRecord]
)

_CREATE_ASSEMBLY_PLAN_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS network_assembly_plan (
    plan_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    canonical_plan_input_sha256 TEXT NOT NULL,
    plan_sequence INTEGER NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (task_id, owner_id, canonical_plan_input_sha256),
    UNIQUE (task_id, owner_id, plan_sequence)
)
"""

_CREATE_ASSEMBLY_OUTPUT_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS network_assembly_output (
    output_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    output_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (task_id, owner_id, plan_id)
)
"""

_CREATE_ASSEMBLY_CONSUMPTION_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS network_assembly_consumption (
    consumption_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    output_id TEXT NOT NULL,
    consumption_json TEXT NOT NULL,
    consumed_at TEXT NOT NULL,
    UNIQUE (task_id, owner_id, plan_id)
)
"""

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS network_task (
    task_id        TEXT PRIMARY KEY,
    source_task_id TEXT,
    owner_id       TEXT,
    query          TEXT NOT NULL,
    analysis_type  TEXT NOT NULL,
    research_protocol TEXT,
    disease_target_import TEXT,
    compound_target_import TEXT,
    status         TEXT NOT NULL,
    progress       INTEGER NOT NULL,
    poll_count     INTEGER NOT NULL,
    data_mode      TEXT NOT NULL DEFAULT 'mock',
    result         TEXT,
    error          TEXT,
    warnings       TEXT NOT NULL DEFAULT '[]',
    adjudications  TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL
)
"""

# Allowed column names for SQL query construction (security: prevent injection)
_ALLOWED_COLUMNS = frozenset(
    {
        "task_id",
        "source_task_id",
        "owner_id",
        "query",
        "analysis_type",
        "research_protocol",
        "disease_target_import",
        "compound_target_import",
        "status",
        "progress",
        "poll_count",
        "data_mode",
        "result",
        "error",
        "warnings",
        "adjudications",
        "created_at",
    }
)

_PATH_LOCKS_GUARD = RLock()
_PATH_LOCKS: dict[Path, tuple[RLockType, int]] = {}


def _acquire_path_lock(db_path: Path) -> tuple[Path, RLockType]:
    """Return the process-wide lock for a canonical SQLite database path."""
    canonical_path = db_path.expanduser().resolve()
    with _PATH_LOCKS_GUARD:
        entry = _PATH_LOCKS.get(canonical_path)
        if entry is None:
            lock = RLock()
            _PATH_LOCKS[canonical_path] = (lock, 1)
            return canonical_path, lock
        lock, reference_count = entry
        _PATH_LOCKS[canonical_path] = (lock, reference_count + 1)
        return canonical_path, lock


def _release_path_lock(db_path: Path) -> None:
    """Release one repository reference and discard unused path locks."""
    with _PATH_LOCKS_GUARD:
        entry = _PATH_LOCKS.get(db_path)
        if entry is None:
            return
        lock, reference_count = entry
        if reference_count == 1:
            del _PATH_LOCKS[db_path]
        else:
            _PATH_LOCKS[db_path] = (lock, reference_count - 1)


def _row_to_record(row: sqlite3.Row) -> NetworkTaskRecord:
    """Convert a database row to a ``NetworkTaskRecord``."""
    data: dict[str, Any] = dict(row)
    # result is stored as JSON TEXT; None stays None
    if data.get("result") is not None:
        data["result"] = NetworkAnalysisResult.model_validate(json.loads(data["result"]))
    if data.get("research_protocol") is not None and isinstance(data["research_protocol"], str):
        data["research_protocol"] = NetworkResearchProtocol.model_validate_json(
            data["research_protocol"]
        )
    if data.get("disease_target_import") is not None and isinstance(
        data["disease_target_import"], str
    ):
        data["disease_target_import"] = _DISEASE_TARGET_SNAPSHOT_ADAPTER.validate_json(
            data["disease_target_import"]
        )
    if data.get("compound_target_import") is not None and isinstance(
        data["compound_target_import"], str
    ):
        data["compound_target_import"] = _COMPOUND_TARGET_SNAPSHOT_ADAPTER.validate_json(
            data["compound_target_import"]
        )
    if data.get("warnings") is not None and isinstance(data["warnings"], str):
        data["warnings"] = json.loads(data["warnings"])
    if data.get("adjudications") is not None and isinstance(data["adjudications"], str):
        data["adjudications"] = _ADJUDICATION_LIST_ADAPTER.validate_json(data["adjudications"])
    return NetworkTaskRecord.model_validate(data)


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


class SqliteNetworkTaskRepository:
    """Network task repository backed by a local SQLite database."""

    def __init__(self, db_path: Path, seed_path: Path | None = None) -> None:
        self._db_path, self._lock = _acquire_path_lock(db_path)
        self._path_lock_registered = True
        self._closed = True
        try:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._closed = False
            with self._lock:
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute(_CREATE_TABLE_SQL)
                self._conn.execute(_CREATE_ASSEMBLY_PLAN_TABLE_SQL)
                self._conn.execute(_CREATE_ASSEMBLY_OUTPUT_TABLE_SQL)
                self._conn.execute(_CREATE_ASSEMBLY_CONSUMPTION_TABLE_SQL)
                self._ensure_columns()
                self._conn.commit()

                # Bootstrap from seed JSON if the table is empty.
                # Network tasks are mutation-only — seed is typically an empty list.
                count = self._conn.execute("SELECT COUNT(*) FROM network_task").fetchone()[0]
                if count == 0:
                    self._bootstrap_from_seed(seed_path)
        except BaseException:
            with self._lock:
                if not self._closed:
                    self._conn.close()
                    self._closed = True
                self._path_lock_registered = False
                _release_path_lock(self._db_path)
            raise

    def _ensure_columns(self) -> None:
        """Add columns introduced after the first SQLite spike."""
        with self._lock:
            rows = self._conn.execute("PRAGMA table_info(network_task)").fetchall()
            existing = {row["name"] for row in rows}
            if "source_task_id" not in existing:
                self._conn.execute("ALTER TABLE network_task ADD COLUMN source_task_id TEXT")
            if "owner_id" not in existing:
                self._conn.execute("ALTER TABLE network_task ADD COLUMN owner_id TEXT")
            if "research_protocol" not in existing:
                self._conn.execute("ALTER TABLE network_task ADD COLUMN research_protocol TEXT")
            if "disease_target_import" not in existing:
                self._conn.execute("ALTER TABLE network_task ADD COLUMN disease_target_import TEXT")
            if "compound_target_import" not in existing:
                self._conn.execute(
                    "ALTER TABLE network_task ADD COLUMN compound_target_import TEXT"
                )
            if "data_mode" not in existing:
                self._conn.execute(
                    "ALTER TABLE network_task ADD COLUMN data_mode TEXT NOT NULL DEFAULT 'mock'"
                )
            if "error" not in existing:
                self._conn.execute("ALTER TABLE network_task ADD COLUMN error TEXT")
            if "warnings" not in existing:
                self._conn.execute(
                    "ALTER TABLE network_task ADD COLUMN warnings TEXT NOT NULL DEFAULT '[]'"
                )
            if "adjudications" not in existing:
                self._conn.execute(
                    "ALTER TABLE network_task ADD COLUMN adjudications TEXT NOT NULL DEFAULT '[]'"
                )

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def _bootstrap_from_seed(self, seed_path: Path | None = None) -> None:
        """Load seed data from the standard network tasks JSON file.

        If *seed_path* is provided, use it directly; otherwise fall back to
        ``resolve_network_tasks_storage_path()``.
        """
        if seed_path is None:
            from app.repositories.runtime_storage import resolve_network_tasks_storage_path

            seed_path = resolve_network_tasks_storage_path()

        raw_items: list[dict[str, Any]] = json.loads(seed_path.read_text(encoding="utf-8"))
        with self._lock:
            for item in raw_items:
                self._insert_item(item)
            self._conn.commit()

    def _insert_item(self, item: dict[str, Any]) -> None:
        """Insert a single item dict into the database."""
        result_val = item.get("result")
        if result_val is not None:
            if isinstance(result_val, NetworkAnalysisResult):
                result_val = result_val.model_dump()
            item["result"] = json.dumps(result_val, ensure_ascii=False)

        columns = [
            "task_id",
            "source_task_id",
            "owner_id",
            "query",
            "analysis_type",
            "research_protocol",
            "disease_target_import",
            "compound_target_import",
            "status",
            "progress",
            "poll_count",
            "data_mode",
            "result",
            "error",
            "warnings",
            "adjudications",
            "created_at",
        ]
        if item.get("data_mode") is None:
            item["data_mode"] = "mock"
        protocol_value = item.get("research_protocol")
        if isinstance(protocol_value, NetworkResearchProtocol):
            item["research_protocol"] = protocol_value.model_dump_json()
        elif protocol_value is not None and not isinstance(protocol_value, str):
            item["research_protocol"] = json.dumps(protocol_value, ensure_ascii=False)
        disease_import_value = item.get("disease_target_import")
        if disease_import_value is not None and not isinstance(disease_import_value, str):
            parsed_import = _DISEASE_TARGET_SNAPSHOT_ADAPTER.validate_python(disease_import_value)
            item["disease_target_import"] = parsed_import.model_dump_json()
        compound_import_value = item.get("compound_target_import")
        if compound_import_value is not None and not isinstance(compound_import_value, str):
            parsed_compound_import = _COMPOUND_TARGET_SNAPSHOT_ADAPTER.validate_python(
                compound_import_value
            )
            item["compound_target_import"] = parsed_compound_import.model_dump_json()
        if item.get("warnings") is None:
            item["warnings"] = []
        if not isinstance(item.get("warnings"), str):
            item["warnings"] = json.dumps(item.get("warnings", []), ensure_ascii=False)
        if item.get("adjudications") is None:
            item["adjudications"] = []
        if not isinstance(item.get("adjudications"), str):
            item["adjudications"] = json.dumps(item.get("adjudications", []), ensure_ascii=False)
        _validate_column_names(columns)  # Security: validate before SQL construction
        values = [item.get(c) for c in columns]
        placeholders = ", ".join("?" for _ in columns)
        col_names = ", ".join(columns)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO network_task ({col_names}) VALUES ({placeholders})",
                values,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection. Safe to call repeatedly."""
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True
                if self._path_lock_registered:
                    self._path_lock_registered = False
                    _release_path_lock(self._db_path)

    def __del__(self) -> None:
        if not getattr(self, "_closed", True):
            self.close()

    def read_all(self) -> list[NetworkTaskRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM network_task").fetchall()
            return [_row_to_record(row) for row in rows]

    def create(self, record: NetworkTaskRecord) -> bool:
        with self._lock:
            try:
                self._insert_item(record.model_dump(mode="json"))
                self._conn.commit()
            except sqlite3.IntegrityError:
                self._conn.rollback()
                return False
            return True

    def get(self, task_id: str) -> NetworkTaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM network_task WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _row_to_record(row) if row else None

    def get_owned(self, task_id: str, owner_id: str) -> NetworkTaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM network_task WHERE task_id = ? AND owner_id = ?",
                (task_id, owner_id),
            ).fetchone()
            return _row_to_record(row) if row else None

    def list_records_for_owner(self, owner_id: str) -> list[NetworkTaskRecord]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM network_task
                   WHERE owner_id = ?
                   ORDER BY created_at DESC, task_id DESC""",
                (owner_id,),
            ).fetchall()
            return [_row_to_record(row) for row in rows]

    def advance(
        self,
        task_id: str,
        owner_id: str,
        transition: Callable[[NetworkTaskRecord], NetworkTaskRecord],
    ) -> NetworkTaskRecord | None:
        while True:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM network_task WHERE task_id = ? AND owner_id = ?",
                    (task_id, owner_id),
                ).fetchone()
                if row is None:
                    return None
                record = _row_to_record(row)
                next_record = transition(record)
                result_json = (
                    json.dumps(next_record.result.model_dump(mode="json"), ensure_ascii=False)
                    if next_record.result is not None
                    else None
                )
                warnings_json = json.dumps(next_record.warnings, ensure_ascii=False)
                cursor = self._conn.execute(
                    """UPDATE network_task
                       SET query = ?,
                           analysis_type = ?,
                           status = ?,
                           progress = ?,
                           poll_count = ?,
                           data_mode = ?,
                           result = ?,
                           error = ?,
                           warnings = ?,
                           created_at = ?
                       WHERE task_id = ? AND owner_id = ? AND poll_count = ?""",
                    (
                        next_record.query,
                        next_record.analysis_type,
                        next_record.status,
                        next_record.progress,
                        next_record.poll_count,
                        next_record.data_mode,
                        result_json,
                        next_record.error,
                        warnings_json,
                        next_record.created_at,
                        task_id,
                        owner_id,
                        record.poll_count,
                    ),
                )
                if cursor.rowcount == 0:
                    self._conn.rollback()
                    continue
                self._conn.commit()
                updated = self._conn.execute(
                    "SELECT * FROM network_task WHERE task_id = ? AND owner_id = ?",
                    (task_id, owner_id),
                ).fetchone()
                return _row_to_record(updated)

    def append_adjudication(
        self,
        task_id: str,
        owner_id: str,
        adjudication: NetworkTargetAdjudication,
    ) -> NetworkTaskRecord | None:
        # ``self._lock`` only serializes writers inside this process, so the write is
        # guarded by a compare-and-set on the adjudications column and retried on
        # conflict — otherwise a second process could clobber an appended decision.
        # Same pattern as ``advance``, which guards on ``poll_count``.
        while True:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM network_task WHERE task_id = ? AND owner_id = ?",
                    (task_id, owner_id),
                ).fetchone()
                if row is None:
                    return None
                record = _row_to_record(row)
                observed_adjudications = row["adjudications"]
                # Audit tag derivation sits inside the CAS retry loop so the
                # chain links to the adjudications column version this write
                # actually lands on, not to a snapshot a concurrent writer
                # already extended.
                adjudication = _tag_with_audit_hmac(task_id, record.adjudications, adjudication)
                adjudications_json = json.dumps(
                    [
                        item.model_dump(mode="json")
                        for item in (*record.adjudications, adjudication)
                    ],
                    ensure_ascii=False,
                )
                cursor = self._conn.execute(
                    """UPDATE network_task
                       SET adjudications = ?
                       WHERE task_id = ?
                         AND owner_id = ?
                         AND adjudications IS ?""",
                    (adjudications_json, task_id, owner_id, observed_adjudications),
                )
                if cursor.rowcount == 0:
                    self._conn.rollback()
                    continue
                self._conn.commit()
                updated = self._conn.execute(
                    "SELECT * FROM network_task WHERE task_id = ? AND owner_id = ?",
                    (task_id, owner_id),
                ).fetchone()
                return _row_to_record(updated) if updated else None

    def list_assembly_plans(self, task_id: str, owner_id: str) -> list[NetworkAssemblyPlan]:
        with self._lock:
            owned = self._conn.execute(
                "SELECT 1 FROM network_task WHERE task_id = ? AND owner_id = ?",
                (task_id, owner_id),
            ).fetchone()
            if owned is None:
                return []
            rows = self._conn.execute(
                """SELECT plan_json FROM network_assembly_plan
                   WHERE task_id = ? AND owner_id = ?
                   ORDER BY plan_sequence""",
                (task_id, owner_id),
            ).fetchall()
            return [NetworkAssemblyPlan.model_validate_json(row["plan_json"]) for row in rows]

    def get_assembly_plan(
        self, task_id: str, owner_id: str, plan_id: str
    ) -> NetworkAssemblyPlan | None:
        with self._lock:
            row = self._conn.execute(
                """SELECT plan_json FROM network_assembly_plan
                   WHERE task_id = ? AND owner_id = ? AND plan_id = ?""",
                (task_id, owner_id, plan_id),
            ).fetchone()
            return NetworkAssemblyPlan.model_validate_json(row["plan_json"]) if row else None

    def seal_assembly_plan(
        self,
        task_id: str,
        owner_id: str,
        expected_adjudication_ids: tuple[str, ...],
        plan: NetworkAssemblyPlan,
    ) -> tuple[str, NetworkAssemblyPlan | None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT adjudications FROM network_task WHERE task_id = ? AND owner_id = ?",
                    (task_id, owner_id),
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    return "not_found", None
                current = _ADJUDICATION_LIST_ADAPTER.validate_json(row["adjudications"])
                if tuple(item.adjudication_id for item in current) != expected_adjudication_ids:
                    self._conn.rollback()
                    return "conflict", None
                existing = self._conn.execute(
                    """SELECT plan_json FROM network_assembly_plan
                       WHERE task_id = ? AND owner_id = ?
                         AND canonical_plan_input_sha256 = ?""",
                    (task_id, owner_id, plan.canonical_plan_input_sha256),
                ).fetchone()
                if existing is not None:
                    self._conn.rollback()
                    return "existing", NetworkAssemblyPlan.model_validate_json(
                        existing["plan_json"]
                    )
                sequence_row = self._conn.execute(
                    """SELECT COALESCE(MAX(plan_sequence), 0) + 1 AS next_sequence
                       FROM network_assembly_plan WHERE task_id = ? AND owner_id = ?""",
                    (task_id, owner_id),
                ).fetchone()
                persisted = plan.model_copy(
                    update={"plan_sequence": int(sequence_row["next_sequence"])}
                )
                self._conn.execute(
                    """INSERT INTO network_assembly_plan
                       (plan_id, task_id, owner_id, canonical_plan_input_sha256,
                        plan_sequence, plan_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        persisted.plan_id,
                        task_id,
                        owner_id,
                        persisted.canonical_plan_input_sha256,
                        persisted.plan_sequence,
                        persisted.model_dump_json(),
                        persisted.created_at,
                    ),
                )
                self._conn.commit()
                return "created", persisted
            except BaseException:
                self._conn.rollback()
                raise

    def list_assembly_consumptions(
        self, task_id: str, owner_id: str
    ) -> list[NetworkAssemblyConsumptionRecord]:
        with self._lock:
            owned = self._conn.execute(
                "SELECT 1 FROM network_task WHERE task_id = ? AND owner_id = ?",
                (task_id, owner_id),
            ).fetchone()
            if owned is None:
                return []
            rows = self._conn.execute(
                """SELECT consumption_json FROM network_assembly_consumption
                   WHERE task_id = ? AND owner_id = ?
                   ORDER BY consumed_at, consumption_id""",
                (task_id, owner_id),
            ).fetchall()
            return [
                NetworkAssemblyConsumptionRecord.model_validate_json(row["consumption_json"])
                for row in rows
            ]

    def consume_assembly_plan(
        self,
        task_id: str,
        owner_id: str,
        writer_id: str,
        plan_id: str,
        expected_adjudication_ids: tuple[str, ...],
        output: NetworkAssemblyOutput,
        consumption: NetworkAssemblyConsumptionRecord,
        record_limit: int,
    ) -> tuple[str, NetworkAssemblyOutput | None, NetworkAssemblyConsumptionRecord | None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                task_row = self._conn.execute(
                    """SELECT adjudications, result FROM network_task
                       WHERE task_id = ? AND owner_id = ?""",
                    (task_id, owner_id),
                ).fetchone()
                if task_row is None:
                    self._conn.rollback()
                    return "not_found", None, None
                plan_row = self._conn.execute(
                    """SELECT plan_json FROM network_assembly_plan
                       WHERE task_id = ? AND owner_id = ? AND plan_id = ?""",
                    (task_id, owner_id, plan_id),
                ).fetchone()
                if plan_row is None:
                    self._conn.rollback()
                    return "not_found", None, None
                plan = NetworkAssemblyPlan.model_validate_json(plan_row["plan_json"])
                # R3: exactly-once with D5 idempotent replay keyed on the
                # writer identity and the output content hash.
                existing_row = self._conn.execute(
                    """SELECT consumption_json FROM network_assembly_consumption
                       WHERE task_id = ? AND owner_id = ? AND plan_id = ?""",
                    (task_id, owner_id, plan_id),
                ).fetchone()
                if existing_row is not None:
                    existing = NetworkAssemblyConsumptionRecord.model_validate_json(
                        existing_row["consumption_json"]
                    )
                    if (
                        existing.writer_id == writer_id
                        and existing.output_sha256 == output.output_sha256
                    ):
                        stored_output_row = self._conn.execute(
                            "SELECT output_json FROM network_assembly_output WHERE output_id = ?",
                            (existing.output_id,),
                        ).fetchone()
                        stored_output = (
                            NetworkAssemblyOutput.model_validate_json(
                                stored_output_row["output_json"]
                            )
                            if stored_output_row is not None
                            else None
                        )
                        self._conn.rollback()
                        return "existing", stored_output, existing
                    self._conn.rollback()
                    return "already_consumed", None, None
                # R4: the plan must still be the latest revision.
                sequence_row = self._conn.execute(
                    """SELECT COALESCE(MAX(plan_sequence), 0) AS max_sequence
                       FROM network_assembly_plan WHERE task_id = ? AND owner_id = ?""",
                    (task_id, owner_id),
                ).fetchone()
                if plan.plan_sequence != int(sequence_row["max_sequence"]):
                    self._conn.rollback()
                    return "superseded", None, None
                # R6 gap guard: the adjudication stream must be unchanged since
                # the service read it.
                current = _ADJUDICATION_LIST_ADAPTER.validate_json(task_row["adjudications"])
                if tuple(item.adjudication_id for item in current) != expected_adjudication_ids:
                    self._conn.rollback()
                    return "conflict", None, None
                # R5 recomputed inside the write transaction: the frozen
                # lineage must still hash to the plan binding.
                if task_row["result"] is None:
                    self._conn.rollback()
                    return "integrity_failed", None, None
                stored_result = NetworkAnalysisResult.model_validate_json(task_row["result"])
                if (
                    canonical_json_sha256(stored_result.target_lineage.model_dump(mode="json"))
                    != plan.target_lineage_sha256
                ):
                    self._conn.rollback()
                    return "integrity_failed", None, None
                capacity_row = self._conn.execute(
                    """SELECT COUNT(*) AS total FROM network_assembly_consumption
                       WHERE task_id = ? AND owner_id = ?""",
                    (task_id, owner_id),
                ).fetchone()
                if int(capacity_row["total"]) >= record_limit:
                    self._conn.rollback()
                    return "capacity_exceeded", None, None
                self._conn.execute(
                    """INSERT INTO network_assembly_output
                       (output_id, task_id, owner_id, plan_id, output_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        output.output_id,
                        task_id,
                        owner_id,
                        plan_id,
                        output.model_dump_json(),
                        output.consumed_at,
                    ),
                )
                self._conn.execute(
                    """INSERT INTO network_assembly_consumption
                       (consumption_id, task_id, owner_id, plan_id, output_id,
                        consumption_json, consumed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        consumption.consumption_id,
                        task_id,
                        owner_id,
                        plan_id,
                        output.output_id,
                        consumption.model_dump_json(),
                        consumption.consumed_at,
                    ),
                )
                self._conn.commit()
                return "created", output, consumption
            except BaseException:
                self._conn.rollback()
                raise

    def upsert(
        self,
        task_id: str,
        query: str,
        analysis_type: AnalysisType,
        status: TaskStatus,
        progress: int,
        poll_count: int,
        result: NetworkAnalysisResult | None,
        created_at: str,
        research_protocol: NetworkResearchProtocol | None = None,
        disease_target_import: NetworkDiseaseTargetSnapshot | None = None,
        compound_target_import: NetworkCompoundTargetSnapshot | None = None,
        source_task_id: str | None = None,
        owner_id: str = "local-preview",
        data_mode: DataMode = "mock",
        error: str | None = None,
        warnings: list[str] | None = None,
    ) -> NetworkTaskRecord:
        result_json: str | None = None
        if result is not None:
            result_json = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        warnings_json = json.dumps(warnings or [], ensure_ascii=False)
        research_protocol_json = (
            research_protocol.model_dump_json() if research_protocol is not None else None
        )
        disease_target_import_json = (
            disease_target_import.model_dump_json() if disease_target_import is not None else None
        )
        compound_target_import_json = (
            compound_target_import.model_dump_json() if compound_target_import is not None else None
        )

        with self._lock:
            existing = self._conn.execute(
                "SELECT task_id FROM network_task WHERE task_id = ?",
                (task_id,),
            ).fetchone()

            if existing is not None:
                self._conn.execute(
                    """UPDATE network_task
                       SET query = ?,
                           analysis_type = ?,
                           status = ?,
                           progress = ?,
                           poll_count = ?,
                           data_mode = ?,
                           result = ?,
                           error = ?,
                           warnings = ?,
                           created_at = ?
                       WHERE task_id = ?""",
                    (
                        query,
                        analysis_type,
                        status,
                        progress,
                        poll_count,
                        data_mode,
                        result_json,
                        error,
                        warnings_json,
                        created_at,
                        task_id,
                    ),
                )
            else:
                self._conn.execute(
                    """INSERT INTO network_task
                       (task_id, source_task_id, owner_id, query, analysis_type, research_protocol,
                        disease_target_import, compound_target_import, status, progress, poll_count,
                        data_mode, result, error, warnings, adjudications, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        task_id,
                        source_task_id,
                        owner_id,
                        query,
                        analysis_type,
                        research_protocol_json,
                        disease_target_import_json,
                        compound_target_import_json,
                        status,
                        progress,
                        poll_count,
                        data_mode,
                        result_json,
                        error,
                        warnings_json,
                        "[]",
                        created_at,
                    ),
                )
            self._conn.commit()

            row = self._conn.execute(
                "SELECT * FROM network_task WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return _row_to_record(row)
