"""Append-only manual adjudication: submission, verification, projections."""

from typing import Any

from app.schemas.network import (
    ManualAdjudicationDecision,
    NetworkAdjudicationCounts,
    NetworkAdjudicationCurrentEntry,
    NetworkAdjudicationRequest,
    NetworkAdjudicationSummary,
    NetworkAnalysisResult,
    NetworkTargetAdjudication,
    NetworkTargetAdjudicationRecord,
    NetworkTaskRecord,
    OmicsAdjudicationContext,
)
from app.services.network_common import _canonical_sha256, _now_iso
from app.services.network_omics import (
    OmicsSnapshotConflictError,
    OmicsVerificationBlockedError,
    compute_omics_deg_projection,
)


def _lineage_row_ids(result: NetworkAnalysisResult) -> set[str]:
    """Collect every adjudicable lineage row id from the frozen target sets."""
    lineage = result.target_lineage
    row_ids: set[str] = set()
    for target_row in (*lineage.disease_targets, *lineage.compound_targets):
        if target_row.lineage_row_id is not None:
            row_ids.add(target_row.lineage_row_id)
    for intersection_row in lineage.intersection_targets:
        row_ids.add(intersection_row.lineage_row_id)
    return row_ids


def _adjudication_summary(record: NetworkTaskRecord) -> NetworkAdjudicationSummary:
    """Project append-only adjudications over the frozen lineage.

    Latest decision per lineage row wins; reviewer identity is intentionally
    dropped.  Pure projection: never mutates the record or its lineage.
    """
    row_ids = _lineage_row_ids(record.result) if record.result is not None else set()
    latest_by_row: dict[str, NetworkTargetAdjudication] = {}
    for adjudication in record.adjudications:
        if adjudication.lineage_row_id in row_ids:
            latest_by_row[adjudication.lineage_row_id] = adjudication
    counts = NetworkAdjudicationCounts(
        included=sum(1 for item in latest_by_row.values() if item.decision == "included"),
        excluded=sum(1 for item in latest_by_row.values() if item.decision == "excluded"),
        needs_review=sum(1 for item in latest_by_row.values() if item.decision == "needs_review"),
        omics_confirmed=sum(
            1 for item in latest_by_row.values() if item.decision == "omics_confirmed"
        ),
        pending=len(row_ids) - len(latest_by_row),
    )
    current = [
        NetworkAdjudicationCurrentEntry(
            lineage_row_id=row_id,
            decision=latest_by_row[row_id].decision,
            reason=latest_by_row[row_id].reason,
            decided_at=latest_by_row[row_id].decided_at,
        )
        for row_id in sorted(latest_by_row)
    ]
    return NetworkAdjudicationSummary(counts=counts, current=current)


def _latest_adjudications(
    record: NetworkTaskRecord,
) -> dict[str, NetworkTargetAdjudication]:
    row_ids = _lineage_row_ids(record.result) if record.result is not None else set()
    latest_by_row: dict[str, NetworkTargetAdjudication] = {}
    for adjudication in record.adjudications:
        if adjudication.lineage_row_id in row_ids:
            latest_by_row[adjudication.lineage_row_id] = adjudication
    return latest_by_row


def _build_adjudication_id(
    task_id: str,
    lineage_row_id: str,
    decision: ManualAdjudicationDecision,
    decided_at: str,
    sequence: int,
    nonce: str,
) -> str:
    """Derive the audit id for one adjudication event.

    ``sequence`` comes from a pre-write snapshot, so two concurrent submissions of
    the same decision on the same row can observe the same value; ``nonce`` keeps
    the id unique per event so it stays a stable handle into the audit trail.
    """
    identity_payload = {
        "task_id": task_id,
        "lineage_row_id": lineage_row_id,
        "decision": decision,
        "decided_at": decided_at,
        "sequence": sequence,
        "nonce": nonce,
    }
    return f"adjudication-{_canonical_sha256(identity_payload)}"


def submit_network_target_adjudication(
    task_id: str,
    reviewer_id: str,
    request: NetworkAdjudicationRequest,
) -> tuple[str, NetworkTargetAdjudicationRecord | None]:
    """Append one manual adjudication to a frozen completed task.

    Fail closed: unknown/foreign/legacy-ownerless tasks are ``not_found``;
    only a ``completed`` task with a frozen result may be adjudicated;
    ``lineage_row_id`` must exist in the frozen target lineage.  The
    reviewer identity is persisted for audit but never projected back.
    """
    from app.services import network as _facade

    repo = _facade._get_repository()
    record = repo.get_owned(task_id, reviewer_id)
    if record is None:
        return "not_found", None
    if record.status != "completed" or record.result is None:
        return "not_completed", None
    if request.lineage_row_id not in _lineage_row_ids(record.result):
        return "unknown_row", None
    omics_fields: dict[str, Any] = {}
    if request.decision == "omics_confirmed":
        assert request.omics is not None  # guaranteed by the request validator
        state, omics_fields = _verify_omics_confirmation(
            record, request.lineage_row_id, request.omics
        )
        if state != "ok":
            return state, None
    decided_at = _now_iso()
    adjudication = NetworkTargetAdjudication(
        adjudication_id=_build_adjudication_id(
            task_id,
            request.lineage_row_id,
            request.decision,
            decided_at,
            len(record.adjudications),
            _facade.uuid4().hex,
        ),
        lineage_row_id=request.lineage_row_id,
        decision=request.decision,
        reason=request.reason,
        decided_at=decided_at,
        reviewer_id=reviewer_id,
        **omics_fields,
    )
    updated = repo.append_adjudication(task_id, reviewer_id, adjudication)
    if updated is None:
        return "not_found", None
    return "ok", NetworkTargetAdjudicationRecord(
        adjudication_id=adjudication.adjudication_id,
        lineage_row_id=adjudication.lineage_row_id,
        decision=adjudication.decision,
        reason=adjudication.reason,
        decided_at=adjudication.decided_at,
        omics_accession=adjudication.omics_accession,
        omics_canonical_symbol=adjudication.omics_canonical_symbol,
        omics_log2fc=adjudication.omics_log2fc,
        omics_adj_p_value=adjudication.omics_adj_p_value,
    )


def _verify_omics_confirmation(
    record: NetworkTaskRecord,
    lineage_row_id: str,
    context: OmicsAdjudicationContext,
) -> tuple[str, dict[str, Any]]:
    """Re-verify every machine omics condition at adjudication time (ADR-0018
    Gate 3). The 6th condition — the human confirmation — is the request
    itself. Returns (state, sealed_fields); state is "ok" only when all
    machine conditions hold against the frozen snapshot, freshly recomputed.
    """
    result = record.result
    assert result is not None
    disease_row = next(
        (
            row
            for row in result.target_lineage.disease_targets
            if row.lineage_row_id == lineage_row_id
        ),
        None,
    )
    if disease_row is None or disease_row.canonical_symbol != context.canonical_symbol:
        return "omics_row_symbol_mismatch", {}
    try:
        projection = compute_omics_deg_projection(result, accession=context.accession)
    except OmicsSnapshotConflictError:
        return "omics_snapshot_missing", {}
    except (OmicsVerificationBlockedError, ValueError):
        return "omics_unverified", {}
    candidate = next(
        (
            item
            for item in projection.candidates
            if item.canonical_symbol == context.canonical_symbol
        ),
        None,
    )
    # Candidate presence already implies the frozen thresholds hold and the
    # dataset conditions (Homo sapiens + atopic dermatitis) matched; the row
    # binding check proves this task's frozen lineage backs the edge.
    if candidate is None or lineage_row_id not in candidate.lineage_row_ids:
        return "omics_not_confirmed", {}
    return "ok", {
        "omics_accession": context.accession,
        "omics_canonical_symbol": context.canonical_symbol,
        "omics_log2fc": candidate.log2fc,
        "omics_adj_p_value": candidate.adj_p_value,
    }
