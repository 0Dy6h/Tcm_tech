"""Protocol definitions for repository interfaces.

These protocols enable dependency inversion: services depend on the
abstract interface, not the concrete InMemory/SQLite implementation.  The
module also hosts repository-layer shared helpers (currently
``_tag_with_audit_hmac``) whose behaviour must stay identical across
backends.
"""

from collections.abc import Callable
from typing import Any, Protocol

from app.core.audit_hmac import derive_adjudication_audit_hmac, load_audit_key
from app.schemas.chunk import LiteratureChunk
from app.schemas.literature import LiteratureItem, PdfParseResult
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


def _tag_with_audit_hmac(
    task_id: str,
    prior_events: list[NetworkTargetAdjudication],
    adjudication: NetworkTargetAdjudication,
) -> NetworkTargetAdjudication:
    """Attach the server-private audit chain tag when the operator key is set.

    Shared by every backend so the chain rule cannot drift between them. Must
    run inside the caller's critical section: ``prev`` is the tag of the state
    the append actually lands on (SQLite recomputes it inside the CAS retry
    loop, JSON holds the instance lock across the whole write).
    """
    key = load_audit_key()
    if key is None:
        return adjudication
    return adjudication.model_copy(
        update={
            "audit_hmac": derive_adjudication_audit_hmac(
                key,
                task_id,
                len(prior_events),
                prior_events[-1].audit_hmac if prior_events else None,
                adjudication.model_dump(mode="json", exclude={"audit_hmac"}),
            )
        }
    )


class LiteratureRepository(Protocol):
    def list_items(self) -> list[LiteratureItem]: ...

    def get_item_by_id(self, item_id: str) -> LiteratureItem | None: ...

    def update_pdf_metadata(
        self,
        literature_id: str,
        pdf_upload_id: str,
        pdf_file_name: str,
        pdf_parse_status: str,
    ) -> LiteratureItem | None: ...

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
    ) -> LiteratureItem | None: ...

    def bulk_upsert_pubmed_items(self, incoming_items: list[dict[str, Any]]) -> tuple[int, int]: ...


class ChunkRepository(Protocol):
    def list_chunks(self) -> list[LiteratureChunk]: ...

    def list_chunks_by_literature_id(self, literature_id: str) -> list[LiteratureChunk]: ...

    def get_chunk_by_id(self, chunk_id: str) -> LiteratureChunk | None: ...

    def upsert_uploaded_pdf_chunk(
        self,
        chunk_id: str,
        literature_id: str,
        pdf_upload_id: str,
        text: str,
        source_quote: str,
        evidence_tags: list[str],
        related_entity_ids: list[str] | None = None,
    ) -> LiteratureChunk: ...


class NetworkTaskRepositoryProtocol(Protocol):
    def read_all(self) -> list[NetworkTaskRecord]: ...

    def create(self, record: NetworkTaskRecord) -> bool: ...

    def get(self, task_id: str) -> NetworkTaskRecord | None: ...

    def get_owned(self, task_id: str, owner_id: str) -> NetworkTaskRecord | None: ...

    def list_records_for_owner(self, owner_id: str) -> list[NetworkTaskRecord]:
        """Return records owned by ``owner_id``, newest first.

        Legacy ownerless records (``owner_id is None``) never match — listing
        fails closed just like ``get_owned``. Ordering is deterministic:
        ``created_at`` descending, ties broken by ``task_id`` descending.
        """
        ...

    def advance(
        self,
        task_id: str,
        owner_id: str,
        transition: Callable[[NetworkTaskRecord], NetworkTaskRecord],
    ) -> NetworkTaskRecord | None: ...

    def append_adjudication(
        self,
        task_id: str,
        owner_id: str,
        adjudication: NetworkTargetAdjudication,
    ) -> NetworkTaskRecord | None:
        """Append one adjudication to the owned task and return the record.

        Append-only: existing adjudications are never reordered, updated, or
        removed.  Fails closed (returns ``None``) for unknown, foreign, or
        legacy ownerless records, mirroring ``get_owned``/``advance``.
        """
        ...

    def list_assembly_plans(self, task_id: str, owner_id: str) -> list[NetworkAssemblyPlan]: ...

    def get_assembly_plan(
        self, task_id: str, owner_id: str, plan_id: str
    ) -> NetworkAssemblyPlan | None: ...

    def seal_assembly_plan(
        self,
        task_id: str,
        owner_id: str,
        expected_adjudication_ids: tuple[str, ...],
        plan: NetworkAssemblyPlan,
    ) -> tuple[str, NetworkAssemblyPlan | None]:
        """Atomically seal a plan if the adjudication stream is unchanged.

        Returns ``created``, ``existing``, ``conflict``, or ``not_found``.
        """
        ...

    def list_assembly_consumptions(
        self, task_id: str, owner_id: str
    ) -> list[NetworkAssemblyConsumptionRecord]:
        """Return all consumption records of one owned task (read-only audit)."""
        ...

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
        """Atomically consume one plan: re-validate then write output + record.

        Everything happens in the same critical section/transaction: the task
        must still exist and belong to ``owner_id``, the plan must still be the
        latest revision (max ``plan_sequence``), the adjudication stream must
        still match ``expected_adjudication_ids``, the frozen target lineage
        must still hash to the plan binding, and no consumption record may
        exist for ``(task_id, owner_id, plan_id)`` unless it is an idempotent
        replay (same writer and same ``output_sha256``).

        Returns one of ``created`` / ``existing`` / ``already_consumed`` /
        ``superseded`` / ``conflict`` / ``integrity_failed`` /
        ``capacity_exceeded`` / ``multi_process_blocked`` / ``not_found``;
        the persisted output and consumption record are only returned for
        ``created`` and ``existing``.
        """
        ...

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
    ) -> NetworkTaskRecord: ...
