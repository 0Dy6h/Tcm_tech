"""Assembly plan sealing, writer consumption primitive, and audit projections."""

import os
from typing import Any

from app.core.canonical_json import canonical_json_sha256
from app.schemas.network import (
    NetworkAssemblyConsumeAccepted,
    NetworkAssemblyConsumeRequest,
    NetworkAssemblyConsumptionProjection,
    NetworkAssemblyConsumptionRecord,
    NetworkAssemblyGateBlocker,
    NetworkAssemblyGateProjection,
    NetworkAssemblyOutput,
    NetworkAssemblyPlan,
    NetworkAssemblyPlanAuditView,
    NetworkAssemblyPlanSummary,
    NetworkAssemblySelectedIntersection,
    NetworkChain,
    NetworkTargetLineageRow,
    NetworkTaskRecord,
)
from app.services.network_common import _canonical_sha256, _now_iso
from app.services.rag import DISCLAIMER


def _assembly_plan_summary(
    plan: NetworkAssemblyPlan,
    *,
    consumed_plan_ids: set[str] | None = None,
) -> NetworkAssemblyPlanSummary:
    return NetworkAssemblyPlanSummary(
        plan_id=plan.plan_id,
        canonical_plan_input_sha256=plan.canonical_plan_input_sha256,
        selected_intersection_count=len(plan.selected_intersections),
        created_at=plan.created_at,
        is_consumed=consumed_plan_ids is not None and plan.plan_id in consumed_plan_ids,
    )


def _assembly_gate_blockers(
    record: NetworkTaskRecord,
    parent: NetworkTaskRecord | None,
) -> tuple[list[NetworkAssemblyGateBlocker], list[NetworkAssemblySelectedIntersection]]:
    from app.services import network as _facade

    blockers: list[NetworkAssemblyGateBlocker] = []
    result = record.result
    if record.status != "completed" or result is None:
        blockers.append(NetworkAssemblyGateBlocker(code="task_not_completed"))
        return blockers, []
    if record.source_task_id is None or record.compound_target_import is None:
        blockers.append(NetworkAssemblyGateBlocker(code="not_compound_child"))
    if parent is None or parent.source_task_id is not None or parent.status != "completed":
        blockers.append(NetworkAssemblyGateBlocker(code="broken_parent_link"))
    elif (
        parent.research_protocol is None
        or record.research_protocol is None
        or _canonical_sha256(parent.research_protocol.model_dump(mode="json"))
        != _canonical_sha256(record.research_protocol.model_dump(mode="json"))
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="protocol_mismatch"))

    lineage = result.target_lineage
    disease_provenance = lineage.disease_import_provenance
    compound_provenance = lineage.compound_import_provenance
    if (
        disease_provenance is None
        or disease_provenance.provenance_verification_status != "server_verified_raw_artifact"
        or not disease_provenance.source_artifact_sha256
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="disease_provenance_unverified"))
    if (
        compound_provenance is None
        or compound_provenance.provenance_verification_status != "server_verified_raw_artifact"
        or not compound_provenance.source_artifact_sha256
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="compound_provenance_unverified"))
    if (
        result.chains
        or result.enrichment is not None
        or result.ppi_edges
        or result.data_sources
        or result.pipeline_steps
    ):
        blockers.append(NetworkAssemblyGateBlocker(code="snapshot_only_boundary_violated"))

    row_ids = _facade._lineage_row_ids(result)
    if len(row_ids) > 10_000 or len(record.adjudications) > 100_000:
        blockers.append(NetworkAssemblyGateBlocker(code="assembly_input_capacity_exceeded"))
        return sorted(blockers, key=lambda item: item.code), []
    latest = _facade._latest_adjudications(record)
    incomplete = sorted(
        row_id
        for row_id in row_ids
        if row_id not in latest or latest[row_id].decision == "needs_review"
    )
    if incomplete:
        blockers.append(
            NetworkAssemblyGateBlocker(code="adjudication_incomplete", row_ids=incomplete)
        )

    included_disease = {
        row_id
        for row_id in (row.lineage_row_id for row in lineage.disease_targets if row.lineage_row_id)
        if row_id in latest and latest[row_id].decision == "included"
    }
    included_compound = {
        row_id
        for row_id in (row.lineage_row_id for row in lineage.compound_targets if row.lineage_row_id)
        if row_id in latest and latest[row_id].decision == "included"
    }
    selected: list[NetworkAssemblySelectedIntersection] = []
    missing_backing: list[str] = []
    for row in sorted(lineage.intersection_targets, key=lambda item: item.lineage_row_id):
        decision = latest.get(row.lineage_row_id)
        if decision is None or decision.decision != "included":
            continue
        selected_disease = sorted(set(row.disease_lineage_row_ids) & included_disease)
        selected_compound = sorted(set(row.compound_lineage_row_ids) & included_compound)
        if not selected_disease or not selected_compound:
            missing_backing.append(row.lineage_row_id)
            continue
        selected.append(
            NetworkAssemblySelectedIntersection(
                lineage_row_id=row.lineage_row_id,
                canonical_symbol=row.canonical_symbol,
                frozen_disease_lineage_row_ids=sorted(row.disease_lineage_row_ids),
                frozen_compound_lineage_row_ids=sorted(row.compound_lineage_row_ids),
                selected_disease_lineage_row_ids=selected_disease,
                selected_compound_lineage_row_ids=selected_compound,
            )
        )
    if missing_backing:
        blockers.append(
            NetworkAssemblyGateBlocker(
                code="included_intersection_missing_backing",
                row_ids=sorted(missing_backing),
            )
        )
    if not selected:
        blockers.append(NetworkAssemblyGateBlocker(code="no_included_intersection"))
    return sorted(blockers, key=lambda item: item.code), selected


def _assembly_gate_projection(record: NetworkTaskRecord) -> NetworkAssemblyGateProjection:
    from app.services import network as _facade

    repo = _facade._get_repository()
    parent = (
        repo.get_owned(record.source_task_id, record.owner_id)
        if record.source_task_id is not None and record.owner_id is not None
        else None
    )
    blockers, _ = _assembly_gate_blockers(record, parent)
    plans = (
        repo.list_assembly_plans(record.task_id, record.owner_id)
        if record.owner_id is not None
        else []
    )
    latest = max(plans, key=lambda item: item.plan_sequence) if plans else None
    consumed_plan_ids = (
        {item.plan_id for item in repo.list_assembly_consumptions(record.task_id, record.owner_id)}
        if record.owner_id is not None and plans
        else set()
    )
    return NetworkAssemblyGateProjection(
        state="blocked" if blockers else "assembly_input_ready",
        blockers=blockers,
        latest_plan=(
            _assembly_plan_summary(latest, consumed_plan_ids=consumed_plan_ids)
            if latest is not None
            else None
        ),
    )


def _adjudication_latest_snapshot(
    record: NetworkTaskRecord,
) -> list[dict[str, Any]]:
    """Deterministic latest-wins adjudication snapshot bound into plan hashes.

    Sorted by lineage row id; every entry carries its adjudication_id (whose
    derivation contains a random nonce), so any adjudication append changes
    the snapshot hash — that is the R6 binding of the consumption contract.
    """
    from app.services import network as _facade

    latest = _facade._latest_adjudications(record)
    return [
        {
            "adjudication_id": item.adjudication_id,
            "lineage_row_id": row_id,
            "decision": item.decision,
            "reason": item.reason,
            "decided_at": item.decided_at,
        }
        for row_id, item in sorted(latest.items())
    ]


def _build_assembly_plan(
    record: NetworkTaskRecord,
    parent: NetworkTaskRecord,
    selected: list[NetworkAssemblySelectedIntersection],
) -> NetworkAssemblyPlan:
    if record.result is None or record.source_task_id is None:
        raise ValueError("assembly plan requires a linked frozen result")
    if record.research_protocol is None or parent.research_protocol is None:
        raise ValueError("assembly plan requires matching protocols")
    lineage = record.result.target_lineage
    disease_provenance = lineage.disease_import_provenance
    compound_provenance = lineage.compound_import_provenance
    if (
        disease_provenance is None
        or compound_provenance is None
        or disease_provenance.source_artifact_sha256 is None
        or compound_provenance.source_artifact_sha256 is None
    ):
        raise ValueError("assembly plan requires verified source artifacts")
    adjudication_snapshot = _adjudication_latest_snapshot(record)
    parent_protocol_hash = _canonical_sha256(parent.research_protocol.model_dump(mode="json"))
    child_protocol_hash = _canonical_sha256(record.research_protocol.model_dump(mode="json"))
    plan_input = {
        "policy_id": "source_bound_network_assembly_v1",
        "canonicalization_id": "qiyan_canonical_json_v1",
        "task_id": record.task_id,
        "source_task_id": record.source_task_id,
        "parent_protocol_sha256": parent_protocol_hash,
        "child_protocol_sha256": child_protocol_hash,
        "disease_source_artifact_sha256": disease_provenance.source_artifact_sha256,
        "compound_source_artifact_sha256": compound_provenance.source_artifact_sha256,
        "disease_import_payload_sha256": disease_provenance.import_payload_sha256,
        "compound_import_payload_sha256": compound_provenance.import_payload_sha256,
        "target_lineage_sha256": _canonical_sha256(lineage.model_dump(mode="json")),
        "adjudication_selection_sha256": _canonical_sha256(adjudication_snapshot),
        "selected_intersections": [item.model_dump(mode="json") for item in selected],
    }
    input_hash = _canonical_sha256(plan_input)
    return NetworkAssemblyPlan.model_validate(
        {
            "plan_id": f"assembly-plan-{input_hash}",
            **plan_input,
            "canonical_plan_input_sha256": input_hash,
            "plan_sequence": 1,
            "created_at": _now_iso(),
        }
    )


def seal_network_assembly_plan(
    task_id: str,
    reviewer_id: str,
) -> tuple[str, NetworkAssemblyPlan | NetworkAssemblyGateProjection | None]:
    from app.services import network as _facade

    repo = _facade._get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return "not_found", None
    parent = (
        repo.get_owned(record.source_task_id, reviewer_id)
        if record.source_task_id is not None
        else None
    )
    blockers, selected = _assembly_gate_blockers(record, parent)
    if blockers:
        return "blocked", NetworkAssemblyGateProjection(state="blocked", blockers=blockers)
    if parent is None:
        return "blocked", NetworkAssemblyGateProjection(
            state="blocked", blockers=[NetworkAssemblyGateBlocker(code="broken_parent_link")]
        )
    plan = _build_assembly_plan(record, parent, selected)
    expected_ids = tuple(item.adjudication_id for item in record.adjudications)
    state, persisted = repo.seal_assembly_plan(task_id, reviewer_id, expected_ids, plan)
    return state, persisted


_CONSUMPTION_RECORD_LIMIT_ENV = "QIYAN_CONSUMPTION_RECORD_LIMIT"
_DEFAULT_CONSUMPTION_RECORD_LIMIT = 1000
_JSON_PREVIEW_BOUNDARIES = [
    "JSON 后端仅支持同进程、同实例 writer（preview 语义），不保证跨进程 exactly-once。",
    "多进程 writer 必须切换到 SQLite 后端。",
]


def _consumption_record_limit() -> int:
    """D8 capacity guard: per-task consumption record limit from env."""
    raw = os.environ.get(_CONSUMPTION_RECORD_LIMIT_ENV)
    if raw is None:
        return _DEFAULT_CONSUMPTION_RECORD_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_CONSUMPTION_RECORD_LIMIT
    return parsed if parsed >= 1 else _DEFAULT_CONSUMPTION_RECORD_LIMIT


def _state_backend_fidelity() -> tuple[str, list[str]]:
    backend = os.environ.get("QIYAN_STATE_BACKEND", "json")
    if backend == "json":
        return "preview", list(_JSON_PREVIEW_BOUNDARIES)
    return "production", []


def _consumption_projection(
    record: NetworkAssemblyConsumptionRecord,
) -> NetworkAssemblyConsumptionProjection:
    return NetworkAssemblyConsumptionProjection(
        consumption_id=record.consumption_id,
        plan_id=record.plan_id,
        plan_sequence=record.plan_sequence,
        canonical_plan_input_sha256=record.canonical_plan_input_sha256,
        output_id=record.output_id,
        output_sha256=record.output_sha256,
        writer_id=record.writer_id,
        consumed_at=record.consumed_at,
    )


_DISEASE_SCOPE_LABELS: dict[str, str] = {"atopic_dermatitis": "Atopic dermatitis"}

_ASSEMBLY_HERB_FORMULA_WARNING = (
    "冻结协议与装配计划不携带药材/复方信息，装配链的 herb/formula 层诚实留空。"
)
_ASSEMBLY_ENRICHMENT_WARNING = (
    "装配切片不执行富集分析（研究者拍板：既有 mock 超几何结果不构成科研结论）。"
)


def _normalize_assembly_score(row: NetworkTargetLineageRow) -> float:
    """Clamp a frozen lineage row score into the chain score domain [0, 1].

    ChEMBL verified rows carry the raw pChEMBL value in ``source_score``; the
    /10 normalization mirrors ``network_connectors._pchembl_to_score`` so the
    assembled chain keeps the same 0-1口径 as provider-derived chains.
    """
    if row.source_score is None:
        return 0.0
    if row.score_name == "pchembl_value":
        return max(0.0, min(row.source_score / 10, 1.0))
    return max(0.0, min(row.source_score, 1.0))


def _assemble_chains_from_plan(
    record: NetworkTaskRecord,
    plan: NetworkAssemblyPlan,
) -> tuple[list[NetworkChain], list[str]]:
    """Deterministically derive compound×target chains from a sealed plan (2026-09-11 拍板).

    One chain per (compound lineage row × selected intersection symbol); rows
    of the same canonical symbol are never merged. Selected rows must resolve
    against the frozen lineage (hash-bound by the plan) — an unresolvable id is
    a persisted-state contradiction and raises for the integrity bucket.
    """
    from app.services import network as _facade

    result = record.result
    if result is None or record.research_protocol is None:
        raise ValueError("assembly input is missing the task result or protocol")
    lineage = result.target_lineage
    disease_rows = {
        row.lineage_row_id: row for row in lineage.disease_targets if row.lineage_row_id is not None
    }
    compound_rows = {
        row.lineage_row_id: row
        for row in lineage.compound_targets
        if row.lineage_row_id is not None
    }
    pathway_by_symbol: dict[str, str] = {}
    for pathway in _facade._load_kegg_pathways():
        if not isinstance(pathway, dict):
            continue
        name = str(pathway.get("name") or "")
        genes = pathway.get("genes")
        if not name or not isinstance(genes, list):
            continue
        for gene in genes:
            pathway_by_symbol.setdefault(str(gene), name)

    disease_label = _DISEASE_SCOPE_LABELS.get(
        record.research_protocol.disease, record.research_protocol.disease
    )

    def _resolve_selection(
        selection: NetworkAssemblySelectedIntersection,
    ) -> tuple[list[NetworkTargetLineageRow], list[NetworkTargetLineageRow]]:
        """Resolve + validate one selection's backing rows against the frozen lineage."""
        try:
            disease = [
                disease_rows[row_id] for row_id in selection.selected_disease_lineage_row_ids
            ]
            compound = [
                compound_rows[row_id] for row_id in selection.selected_compound_lineage_row_ids
            ]
        except KeyError as exc:
            raise ValueError(
                f"selected lineage row cannot be resolved for {selection.lineage_row_id}: {exc}"
            ) from exc
        for row in compound:
            if row.canonical_symbol != selection.canonical_symbol:
                raise ValueError(
                    f"compound lineage row {row.lineage_row_id} does not match "
                    f"selected symbol {selection.canonical_symbol}"
                )
        return disease, compound

    resolved = [
        (selection, *_resolve_selection(selection)) for selection in plan.selected_intersections
    ]
    # 防御分支：mock 行无法通过装配门禁（双侧 verified provenance 才可 seal），
    # 但任何 mock 行都把整批装配链压回 mock 档，宁低不高。
    uses_mock_rows = any(
        row.evidence_origin == "mock"
        for _, disease, compound in resolved
        for row in [*disease, *compound]
    )
    chains: list[NetworkChain] = []
    missing_pathway_count = 0
    for selection, _disease, compound in resolved:
        for compound_row in compound:
            pathway = pathway_by_symbol.get(selection.canonical_symbol, "")
            if not pathway:
                missing_pathway_count += 1
            chains.append(
                NetworkChain(
                    herb="",
                    formula=None,
                    compound=compound_row.raw_identifier,
                    target=selection.canonical_symbol,
                    pathway=pathway,
                    disease=disease_label,
                    score=_normalize_assembly_score(compound_row),
                    related_entity_ids=[
                        selection.lineage_row_id,
                        *selection.selected_disease_lineage_row_ids,
                        compound_row.lineage_row_id or "",
                    ],
                    evidence_refs=[],
                    # 拍板规则 2（宁低不高）：ChEMBL known_activity 行也不上浮 experimental，
                    # 无文献引用的装配链一律压为 predicted；mock 行保持 mock 档。
                    target_evidence_type="mock" if uses_mock_rows else "predicted",
                )
            )
    # 证据分级按行 provenance 而非任务 data_mode：verified 导入任务的 data_mode 只是
    # provider 开关（默认仍为 mock），行的真实性由封存快照决定；mock 行走 ADR-0015
    # 原口径恒 mock_inferred。
    graded = _facade.grade_chains_evidence(
        chains,
        data_mode="live" if not uses_mock_rows else record.data_mode,
    )
    warnings = [_ASSEMBLY_HERB_FORMULA_WARNING, _ASSEMBLY_ENRICHMENT_WARNING]
    if missing_pathway_count:
        warnings.append(
            f"{missing_pathway_count}/{len(graded)} 条装配链未命中本地通路字典，pathway 留空。"
        )
    return graded, warnings


def _build_assembly_output(
    record: NetworkTaskRecord,
    plan: NetworkAssemblyPlan,
    request: NetworkAssemblyConsumeRequest,
    output_sha256: str,
    consumed_at: str,
    chains: list[NetworkChain],
    warnings: list[str],
) -> NetworkAssemblyOutput:
    output_id = "assembly-output-" + canonical_json_sha256(
        {
            "task_id": record.task_id,
            "source_task_id": record.source_task_id,
            "plan_id": plan.plan_id,
            "plan_sequence": plan.plan_sequence,
            "canonical_plan_input_sha256": plan.canonical_plan_input_sha256,
            "output_sha256": output_sha256,
        }
    )
    return NetworkAssemblyOutput(
        output_id=output_id,
        task_id=record.task_id,
        source_task_id=record.source_task_id or "",
        plan_id=plan.plan_id,
        plan_sequence=plan.plan_sequence,
        canonical_plan_input_sha256=plan.canonical_plan_input_sha256,
        output_sha256=output_sha256,
        writer_id=request.writer_id,
        consumed_at=consumed_at,
        chains=chains,
        warnings=warnings,
        disclaimer=DISCLAIMER,
    )


def _build_consumption_record(
    record: NetworkTaskRecord,
    plan: NetworkAssemblyPlan,
    output: NetworkAssemblyOutput,
    consumed_at: str,
) -> NetworkAssemblyConsumptionRecord:
    from app.services import network as _facade

    consumption_id = "assembly-consumption-" + canonical_json_sha256(
        {
            "task_id": record.task_id,
            "plan_id": plan.plan_id,
            "output_id": output.output_id,
            "consumed_at": consumed_at,
            "nonce": _facade.uuid4().hex,
        }
    )
    return NetworkAssemblyConsumptionRecord(
        consumption_id=consumption_id,
        task_id=record.task_id,
        owner_id=record.owner_id or "",
        plan_id=plan.plan_id,
        plan_sequence=plan.plan_sequence,
        canonical_plan_input_sha256=plan.canonical_plan_input_sha256,
        output_id=output.output_id,
        output_sha256=output.output_sha256,
        writer_id=output.writer_id,
        consumed_at=consumed_at,
    )


def consume_network_assembly_plan(
    task_id: str,
    plan_id: str,
    reviewer_id: str,
    request: NetworkAssemblyConsumeRequest,
) -> tuple[str, NetworkAssemblyConsumeAccepted | list[str] | None]:
    """Writer consumption primitive: atomic write-time validation + exactly-once consume.

    Service pre-checks run in the contract's deterministic failure-code
    priority (D3: 404 → 422 → R3 → R4 → R6 → R7 → 500 integrity); the
    repository primitive then re-validates the mutable channels inside the
    same critical section that appends the output and the consumption record,
    so there is never a check-then-write gap.
    """
    from app.services import network as _facade

    repo = _facade._get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return "not_found", None
    plan = repo.get_assembly_plan(task_id, reviewer_id, plan_id)
    if plan is None:
        return "not_found", None
    # 422: a presented plan-input hash that contradicts the stored plan is a
    # malformed (or forged) writer request.
    if (
        request.canonical_plan_input_sha256 is not None
        and request.canonical_plan_input_sha256 != plan.canonical_plan_input_sha256
    ):
        return "invalid_request", ["canonical_plan_input_sha256_mismatch"]
    # R3 pre-check: an already-consumed plan is reported first (D3), whatever
    # happened to the revision afterwards; the repository turns a matching
    # writer + output hash into an idempotent ``existing`` replay.
    plan_consumption = next(
        (
            item
            for item in repo.list_assembly_consumptions(task_id, reviewer_id)
            if item.plan_id == plan_id
        ),
        None,
    )
    if plan_consumption is None:
        # R4 pre-check: the plan must still be the latest revision.
        plans = repo.list_assembly_plans(task_id, reviewer_id)
        latest_sequence = max(item.plan_sequence for item in plans) if plans else 0
        if plan.plan_sequence != latest_sequence:
            return "superseded", None
        # R6 pre-check: recompute the latest-wins adjudication snapshot
        # against the plan binding. The repository re-checks the read-to-lock
        # gap atomically.
        if canonical_json_sha256(_adjudication_latest_snapshot(record)) != (
            plan.adjudication_selection_sha256
        ):
            return "conflict", None
    # R7: parent link must still resolve to a completed root task (409).
    parent = (
        repo.get_owned(record.source_task_id, reviewer_id)
        if record.source_task_id is not None
        else None
    )
    if parent is None or parent.source_task_id is not None or parent.status != "completed":
        return "broken_parent_link", None
    # 500 bucket: persisted-state contradictions, reported with every failed
    # check (R9 plan self-consistency, R1 contradiction, R5/R8 lineage and
    # protocol bindings).
    failed_checks: list[str] = []
    if plan.plan_id != f"assembly-plan-{plan.canonical_plan_input_sha256}":
        failed_checks.append("plan_id_derivation")
    if plan.assembly_input_ready is not True:
        failed_checks.append("assembly_input_ready")
    if plan.formal_network_ready is not False:
        failed_checks.append("formal_network_ready")
    if record.status != "completed" or record.result is None:
        failed_checks.append("task_not_completed")
    if failed_checks:
        return "integrity_failed", failed_checks
    if record.result is not None:
        lineage_hash = canonical_json_sha256(record.result.target_lineage.model_dump(mode="json"))
        if lineage_hash != plan.target_lineage_sha256:
            failed_checks.append("target_lineage_binding")
    if parent.research_protocol is None or record.research_protocol is None:
        failed_checks.append("protocol_missing")
    else:
        parent_protocol_hash = canonical_json_sha256(
            parent.research_protocol.model_dump(mode="json")
        )
        child_protocol_hash = canonical_json_sha256(
            record.research_protocol.model_dump(mode="json")
        )
        if parent_protocol_hash != plan.parent_protocol_sha256:
            failed_checks.append("parent_protocol_binding")
        if child_protocol_hash != plan.child_protocol_sha256:
            failed_checks.append("child_protocol_binding")
    if failed_checks:
        return "integrity_failed", failed_checks
    output_sha256 = canonical_json_sha256(request.output_payload)
    consumed_at = _now_iso()
    try:
        chains, assembly_warnings = _assemble_chains_from_plan(record, plan)
    except ValueError:
        # Selected rows are hash-bound to the frozen lineage; an unresolvable
        # row here is a persisted-state contradiction (500 integrity bucket).
        return "integrity_failed", ["assembly_input_unresolvable"]
    output = _build_assembly_output(
        record, plan, request, output_sha256, consumed_at, chains, assembly_warnings
    )
    consumption = _build_consumption_record(record, plan, output, consumed_at)
    current_adjudication_ids = tuple(item.adjudication_id for item in record.adjudications)
    state, stored_output, stored_consumption = repo.consume_assembly_plan(
        task_id,
        reviewer_id,
        request.writer_id,
        plan_id,
        current_adjudication_ids,
        output,
        consumption,
        _consumption_record_limit(),
    )
    if state not in {"created", "existing"} or stored_output is None or stored_consumption is None:
        return state, None
    fidelity, boundaries = _state_backend_fidelity()
    accepted = NetworkAssemblyConsumeAccepted(
        state="created" if state == "created" else "existing",
        backend_fidelity="preview" if fidelity == "preview" else "production",
        output=stored_output,
        consumption=_consumption_projection(stored_consumption),
        preview_boundaries=boundaries,
    )
    return state, accepted


def build_network_assembly_plan_audit_view(
    task_id: str,
    plan_id: str,
    reviewer_id: str,
) -> NetworkAssemblyPlanAuditView | None:
    """D6 read-only audit projection: readable is not consumable."""
    from app.services import network as _facade

    repo = _facade._get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return None
    plan = repo.get_assembly_plan(task_id, reviewer_id, plan_id)
    if plan is None:
        return None
    plans = repo.list_assembly_plans(task_id, reviewer_id)
    latest = max(plans, key=lambda item: item.plan_sequence) if plans else None
    consumptions = {
        item.plan_id: item for item in repo.list_assembly_consumptions(task_id, reviewer_id)
    }
    consumption = consumptions.get(plan.plan_id)
    is_latest = latest is not None and latest.plan_id == plan.plan_id
    return NetworkAssemblyPlanAuditView(
        plan=plan,
        is_latest_plan=is_latest,
        is_consumed=consumption is not None,
        is_superseded_by=None if is_latest or latest is None else latest.plan_id,
        consumption=(_consumption_projection(consumption) if consumption is not None else None),
    )
