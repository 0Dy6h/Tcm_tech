"""Network pharmacology service façade (compatibility re-exports).

The implementation lives in focused sibling modules: network_common,
network_imports, network_lineage, network_tasks, network_assembly,
network_adjudication and network_queries.  Every historical symbol is
re-exported here so ``app.api.network`` and the test suite keep working.

Tests monkeypatch attributes on THIS module (``_get_repository``,
``uuid4``, ``select_network_provider``).  The sibling modules therefore
resolve those names through this façade at call time (function-body
``from app.services import network as _facade`` late binding) instead of
binding the original objects at import time — a module-level import would
silently defeat the monkeypatches.

Convention, enforced by ``tests/test_network_facade_late_binding.py``:

- No sibling imports this façade at module level (import cycle plus
  monkeypatch bypass).
- The patchable names are never called bare in a sibling; they are always
  resolved as ``_facade.<name>``.
- Cross-references between split siblings also go through ``_facade.``
  (even for names outside the monkeypatch surface) so the whole call graph
  stays monkeypatch-transparent.  The one module-level exception is
  network_common: dependency-light primitives that import no sibling and
  are outside the monkeypatch surface.
"""

from typing import TYPE_CHECKING
from uuid import uuid4

from app.repositories.runtime_storage import get_network_task_repository
from app.services.network_adjudication import (
    _adjudication_summary,
    _build_adjudication_id,
    _latest_adjudications,
    _lineage_row_ids,
    _verify_omics_confirmation,
    submit_network_target_adjudication,
)
from app.services.network_assembly import (
    _ASSEMBLY_ENRICHMENT_WARNING,
    _ASSEMBLY_HERB_FORMULA_WARNING,
    _CONSUMPTION_RECORD_LIMIT_ENV,
    _DEFAULT_CONSUMPTION_RECORD_LIMIT,
    _DISEASE_SCOPE_LABELS,
    _JSON_PREVIEW_BOUNDARIES,
    _adjudication_latest_snapshot,
    _assemble_chains_from_plan,
    _assembly_gate_blockers,
    _assembly_gate_projection,
    _assembly_plan_summary,
    _build_assembly_output,
    _build_assembly_plan,
    _build_consumption_record,
    _consumption_projection,
    _consumption_record_limit,
    _normalize_assembly_score,
    _state_backend_fidelity,
    build_network_assembly_plan_audit_view,
    consume_network_assembly_plan,
    seal_network_assembly_plan,
)
from app.services.network_common import (
    _IMPORTED_COMPOUND_SNAPSHOT_BLOCKER,
    _MAX_CHAINS_PER_QUERY,
    _UNLINKED_COMPOUND_CHILD_ERROR,
    _canonical_sha256,
    _now_iso,
)
from app.services.network_imports import (
    _build_import_snapshot,
    _persist_verified_raw_artifact,
    build_verified_compound_import_snapshot,
    build_verified_disease_import_snapshot,
)
from app.services.network_lineage import (
    _EVIDENCE_LEVEL_LABELS,
    _EVIDENCE_LEVEL_ORDER,
    _analysis_type_label,
    _append_target_lineage_table,
    _build_intersection_row,
    _build_lineage_row_id,
    _escape_table_cell,
    _evidence_level_label,
    _format_entity_ids,
    _format_score,
    _target_evidence_type_label,
    assess_network_research_readiness,
    build_network_report_markdown,
    build_target_lineage,
    derive_chain_evidence_level,
    grade_chains_evidence,
)
from app.services.network_providers import select_network_provider
from app.services.network_queries import (
    _has_unlinked_compound_child,
    _result_response,
    _task_summary,
    _unlinked_compound_child_response,
    _with_omics_evidence_overlay,
    get_network_analysis_result,
    get_network_analysis_task,
    list_all_entities,
    list_network_analysis_tasks,
)
from app.services.network_tasks import (
    _advance_record,
    _build_chains_from_seed,
    _complete_imported_compound_snapshot,
    _create_queued_network_task,
    _load_go_terms,
    _load_kegg_pathways,
    _select_data_mode,
    create_network_analysis_task,
    create_verified_compound_network_analysis_task,
    create_verified_network_analysis_task,
)

if TYPE_CHECKING:
    from app.repositories.protocols import NetworkTaskRepositoryProtocol

__all__ = [
    "_ASSEMBLY_ENRICHMENT_WARNING",
    "_ASSEMBLY_HERB_FORMULA_WARNING",
    "_CONSUMPTION_RECORD_LIMIT_ENV",
    "_DEFAULT_CONSUMPTION_RECORD_LIMIT",
    "_DISEASE_SCOPE_LABELS",
    "_EVIDENCE_LEVEL_LABELS",
    "_EVIDENCE_LEVEL_ORDER",
    "_IMPORTED_COMPOUND_SNAPSHOT_BLOCKER",
    "_JSON_PREVIEW_BOUNDARIES",
    "_MAX_CHAINS_PER_QUERY",
    "_UNLINKED_COMPOUND_CHILD_ERROR",
    "_adjudication_latest_snapshot",
    "_adjudication_summary",
    "_advance_record",
    "_analysis_type_label",
    "_append_target_lineage_table",
    "_assemble_chains_from_plan",
    "_assembly_gate_blockers",
    "_assembly_gate_projection",
    "_assembly_plan_summary",
    "_build_adjudication_id",
    "_build_assembly_output",
    "_build_assembly_plan",
    "_build_chains_from_seed",
    "_build_consumption_record",
    "_build_import_snapshot",
    "_build_intersection_row",
    "_build_lineage_row_id",
    "_canonical_sha256",
    "_complete_imported_compound_snapshot",
    "_consumption_projection",
    "_consumption_record_limit",
    "_create_queued_network_task",
    "_escape_table_cell",
    "_evidence_level_label",
    "_format_entity_ids",
    "_format_score",
    "_get_repository",
    "_has_unlinked_compound_child",
    "_latest_adjudications",
    "_lineage_row_ids",
    "_load_go_terms",
    "_load_kegg_pathways",
    "_normalize_assembly_score",
    "_now_iso",
    "_persist_verified_raw_artifact",
    "_result_response",
    "_select_data_mode",
    "_state_backend_fidelity",
    "_target_evidence_type_label",
    "_task_summary",
    "_unlinked_compound_child_response",
    "_verify_omics_confirmation",
    "_with_omics_evidence_overlay",
    "assess_network_research_readiness",
    "build_network_assembly_plan_audit_view",
    "build_network_report_markdown",
    "build_target_lineage",
    "build_verified_compound_import_snapshot",
    "build_verified_disease_import_snapshot",
    "consume_network_assembly_plan",
    "create_network_analysis_task",
    "create_verified_compound_network_analysis_task",
    "create_verified_network_analysis_task",
    "derive_chain_evidence_level",
    "get_network_analysis_result",
    "get_network_analysis_task",
    "grade_chains_evidence",
    "list_all_entities",
    "list_network_analysis_tasks",
    "seal_network_assembly_plan",
    "select_network_provider",
    "submit_network_target_adjudication",
    "uuid4",
]


def _get_repository() -> "NetworkTaskRepositoryProtocol":
    return get_network_task_repository()
