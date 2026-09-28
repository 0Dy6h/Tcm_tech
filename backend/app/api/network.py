import json
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import UploadFile

from app.core.reviewer_identity import require_reviewer_id
from app.schemas.network import (
    AnalysisType,
    EvidencePolicy,
    NetworkAdjudicationRequest,
    NetworkAnalyzeAccepted,
    NetworkAnalyzeRequest,
    NetworkAssemblyConsumeAccepted,
    NetworkAssemblyConsumeRequest,
    NetworkAssemblyPlan,
    NetworkAssemblyPlanAuditView,
    NetworkCompoundTargetVerifyMetadata,
    NetworkDiseaseTargetVerifyMetadata,
    NetworkResultResponse,
    NetworkTargetAdjudicationRecord,
    NetworkTaskListResponse,
)
from app.schemas.network_entities import NetworkEntitiesResponse
from app.schemas.omics import OmicsImportAccepted, OmicsTranscriptomicsManifestV1
from app.services.network_adjudication import submit_network_target_adjudication
from app.services.network_assembly import (
    build_network_assembly_plan_audit_view,
    consume_network_assembly_plan,
    seal_network_assembly_plan,
)
from app.services.network_lineage import build_network_report_markdown
from app.services.network_omics import (
    OmicsSnapshotConflictError,
    OmicsVerificationBlockedError,
    compute_omics_deg_projection,
    import_verified_omics_artifact,
)
from app.services.network_queries import (
    get_network_analysis_result,
    get_network_analysis_task,
    list_all_entities,
    list_network_analysis_tasks,
)
from app.services.network_tasks import (
    create_network_analysis_task,
    create_verified_compound_network_analysis_task,
    create_verified_network_analysis_task,
)

router = APIRouter(prefix="/api/network", tags=["network"])
_MAX_RAW_ARTIFACT_BYTES = 5 * 1024 * 1024
_MAX_VERIFY_REQUEST_BYTES = _MAX_RAW_ARTIFACT_BYTES + 256 * 1024
_MAX_OMICS_RAW_ARTIFACT_BYTES = 32 * 1024 * 1024
_MAX_OMICS_VERIFY_REQUEST_BYTES = _MAX_OMICS_RAW_ARTIFACT_BYTES + 256 * 1024
_OMICS_MANIFEST_FIELD_MAX_BYTES = 256 * 1024
_ANALYSIS_TYPE_ADAPTER: TypeAdapter[AnalysisType] = TypeAdapter(AnalysisType)
_EVIDENCE_POLICY_ADAPTER: TypeAdapter[EvidencePolicy] = TypeAdapter(EvidencePolicy)


@router.post(
    "/analyze", response_model=NetworkAnalyzeAccepted, status_code=status.HTTP_202_ACCEPTED
)
def analyze_network_endpoint(
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
    request: NetworkAnalyzeRequest = Body(),
) -> NetworkAnalyzeAccepted:
    return create_network_analysis_task(
        request.query,
        request.analysis_type,
        reviewer_id,
        request.research_protocol,
        request.disease_target_import,
    )


@router.post(
    "/disease-import/verify",
    response_model=NetworkAnalyzeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def verify_disease_import_endpoint(
    request: Request,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
) -> NetworkAnalyzeAccepted:
    if request.headers.get("transfer-encoding") is not None:
        raise HTTPException(status_code=411, detail="Content-Length is required")
    content_length = request.headers.get("content-length")
    if content_length is None:
        raise HTTPException(status_code=411, detail="Content-Length is required")
    try:
        declared_length = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid Content-Length") from exc
    if declared_length < 0:
        raise HTTPException(status_code=422, detail="invalid Content-Length")
    if declared_length > _MAX_VERIFY_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="Open Targets raw artifact is too large")
    form = await request.form(max_files=1, max_fields=5, max_part_size=_MAX_RAW_ARTIFACT_BYTES)
    submitted_fields = set(form.keys())
    allowed_fields = {"query", "metadata", "file", "analysis_type", "evidence_policy"}
    extra_fields = submitted_fields - allowed_fields
    if extra_fields:
        raise HTTPException(
            status_code=422,
            detail=f"unexpected multipart fields: {sorted(extra_fields)}",
        )
    repeated_or_missing_fields = sorted(
        [field for field in {"query", "metadata", "file"} if len(form.getlist(field)) != 1]
        + [field for field in {"analysis_type", "evidence_policy"} if len(form.getlist(field)) > 1]
    )
    if repeated_or_missing_fields:
        raise HTTPException(
            status_code=422,
            detail=f"multipart fields have invalid cardinality: {repeated_or_missing_fields}",
        )
    query_value = form.get("query")
    metadata_value = form.get("metadata")
    file_value = form.get("file")
    if not isinstance(query_value, str) or not query_value.strip():
        raise HTTPException(status_code=422, detail="query is required")
    if not isinstance(metadata_value, str):
        raise HTTPException(status_code=422, detail="metadata is required")
    if not isinstance(file_value, UploadFile):
        raise HTTPException(status_code=422, detail="Open Targets raw artifact file is required")
    try:
        analysis_type = _ANALYSIS_TYPE_ADAPTER.validate_python(form.get("analysis_type", "formula"))
        evidence_policy = _EVIDENCE_POLICY_ADAPTER.validate_python(
            form.get("evidence_policy", "direct_human_first")
        )
        metadata_payload = json.loads(metadata_value)
        verified_metadata = NetworkDiseaseTargetVerifyMetadata.model_validate(metadata_payload)
        raw_bytes = await file_value.read(_MAX_RAW_ARTIFACT_BYTES + 1)
        if len(raw_bytes) > _MAX_RAW_ARTIFACT_BYTES:
            raise HTTPException(status_code=413, detail="Open Targets raw artifact is too large")
        return create_verified_network_analysis_task(
            query=query_value,
            analysis_type=analysis_type,
            reviewer_id=reviewer_id,
            evidence_policy=evidence_policy,
            metadata=verified_metadata,
            raw_bytes=raw_bytes,
            source_artifact_filename=file_value.filename or "open-targets-associations.json",
            source_artifact_media_type=file_value.content_type or "application/octet-stream",
        )
    except HTTPException:
        raise
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/compound-import/verify",
    response_model=NetworkAnalyzeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def verify_compound_import_endpoint(
    request: Request,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
) -> NetworkAnalyzeAccepted:
    if request.headers.get("transfer-encoding") is not None:
        raise HTTPException(status_code=411, detail="Content-Length is required")
    content_length = request.headers.get("content-length")
    if content_length is None:
        raise HTTPException(status_code=411, detail="Content-Length is required")
    try:
        declared_length = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid Content-Length") from exc
    if declared_length < 0:
        raise HTTPException(status_code=422, detail="invalid Content-Length")
    if declared_length > _MAX_VERIFY_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="ChEMBL raw artifact is too large")
    form = await request.form(max_files=1, max_fields=3, max_part_size=_MAX_RAW_ARTIFACT_BYTES)
    submitted_fields = set(form.keys())
    allowed_fields = {"source_task_id", "metadata", "file"}
    extra_fields = submitted_fields - allowed_fields
    if extra_fields:
        raise HTTPException(
            status_code=422,
            detail=f"unexpected multipart fields: {sorted(extra_fields)}",
        )
    repeated_or_missing_fields = sorted(
        field for field in allowed_fields if len(form.getlist(field)) != 1
    )
    if repeated_or_missing_fields:
        raise HTTPException(
            status_code=422,
            detail=f"multipart fields must each appear exactly once: {repeated_or_missing_fields}",
        )
    source_task_id = form.get("source_task_id")
    metadata_value = form.get("metadata")
    file_value = form.get("file")
    if not isinstance(source_task_id, str) or not source_task_id.strip():
        raise HTTPException(status_code=422, detail="source_task_id is required")
    if not isinstance(metadata_value, str):
        raise HTTPException(status_code=422, detail="metadata is required")
    if not isinstance(file_value, UploadFile):
        raise HTTPException(status_code=422, detail="ChEMBL raw artifact file is required")
    try:
        metadata_payload = json.loads(metadata_value)
        verified_metadata = NetworkCompoundTargetVerifyMetadata.model_validate(metadata_payload)
        raw_bytes = await file_value.read(_MAX_RAW_ARTIFACT_BYTES + 1)
        if len(raw_bytes) > _MAX_RAW_ARTIFACT_BYTES:
            raise HTTPException(status_code=413, detail="ChEMBL raw artifact is too large")
        return create_verified_compound_network_analysis_task(
            source_task_id=source_task_id.strip(),
            reviewer_id=reviewer_id,
            metadata=verified_metadata,
            raw_bytes=raw_bytes,
            source_artifact_filename=file_value.filename or "chembl-known-activities.json",
            source_artifact_media_type=file_value.content_type or "application/octet-stream",
        )
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Network analysis task not found") from exc
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/omics-import/verify",
    response_model=OmicsImportAccepted,
    status_code=status.HTTP_201_CREATED,
)
async def verify_omics_import_endpoint(
    request: Request,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
    response: Response,
) -> OmicsImportAccepted:
    """Freeze an omics raw artifact as an immutable snapshot (ADR-0018 Gate 3).

    Opt-in only: nothing in the default offline profile calls this. Sealed
    fields (sha256/frozen_at/frozen_by/provenance) are server-computed; a
    client that submits them fails the schema validation.
    """
    if request.headers.get("transfer-encoding") is not None:
        raise HTTPException(status_code=411, detail="Content-Length is required")
    content_length = request.headers.get("content-length")
    if content_length is None:
        raise HTTPException(status_code=411, detail="Content-Length is required")
    try:
        declared_length = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid Content-Length") from exc
    if declared_length < 0:
        raise HTTPException(status_code=422, detail="invalid Content-Length")
    if declared_length > _MAX_OMICS_VERIFY_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="omics raw artifact is too large")
    form = await request.form(
        max_files=2, max_fields=3, max_part_size=_OMICS_MANIFEST_FIELD_MAX_BYTES
    )
    submitted_fields = set(form.keys())
    allowed_fields = {"manifest", "file", "annotation_file"}
    extra_fields = submitted_fields - allowed_fields
    if extra_fields:
        raise HTTPException(
            status_code=422,
            detail=f"unexpected multipart fields: {sorted(extra_fields)}",
        )
    invalid_cardinality = sorted(
        field for field in {"manifest", "file"} if len(form.getlist(field)) != 1
    ) + sorted(field for field in {"annotation_file"} if len(form.getlist(field)) > 1)
    if invalid_cardinality:
        raise HTTPException(
            status_code=422,
            detail=f"multipart fields have invalid cardinality: {invalid_cardinality}",
        )
    manifest_value = form.get("manifest")
    file_value = form.get("file")
    annotation_value = form.get("annotation_file")
    if not isinstance(manifest_value, str):
        raise HTTPException(status_code=422, detail="manifest is required")
    if not isinstance(file_value, UploadFile):
        raise HTTPException(status_code=422, detail="omics raw artifact file is required")
    if annotation_value is not None and not isinstance(annotation_value, UploadFile):
        raise HTTPException(status_code=422, detail="annotation_file must be a file")
    try:
        manifest_payload = json.loads(manifest_value)
        manifest = OmicsTranscriptomicsManifestV1.model_validate(manifest_payload)
        raw_bytes = await file_value.read(_MAX_OMICS_RAW_ARTIFACT_BYTES + 1)
        if len(raw_bytes) > _MAX_OMICS_RAW_ARTIFACT_BYTES:
            raise HTTPException(status_code=413, detail="omics raw artifact is too large")
        annotation_bytes: bytes | None = None
        if isinstance(annotation_value, UploadFile):
            annotation_bytes = await annotation_value.read(_MAX_OMICS_RAW_ARTIFACT_BYTES + 1)
            if len(annotation_bytes) > _MAX_OMICS_RAW_ARTIFACT_BYTES:
                raise HTTPException(
                    status_code=413, detail="omics platform annotation is too large"
                )
        outcome = import_verified_omics_artifact(
            raw_bytes,
            manifest=manifest,
            frozen_by=reviewer_id,
            annotation_bytes=annotation_bytes,
        )
    except OmicsSnapshotConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if outcome.idempotent:
        response.status_code = status.HTTP_200_OK
    return OmicsImportAccepted(
        snapshot_id=outcome.snapshot.snapshot_id,
        accession=outcome.snapshot.dataset.accession,
        idempotent=outcome.idempotent,
        snapshot=outcome.snapshot,
    )


@router.get("/tasks", response_model=NetworkTaskListResponse)
def network_task_list_endpoint(
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
) -> NetworkTaskListResponse:
    return list_network_analysis_tasks(reviewer_id)


@router.get("/result/{task_id}", response_model=NetworkResultResponse)
def network_result_endpoint(
    task_id: str,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
    omics_verification: bool = False,
    omics_accession: str | None = None,
) -> NetworkResultResponse:
    state, payload = get_network_analysis_result(task_id, reviewer_id)
    if state == "not_found" or payload is None:
        raise HTTPException(status_code=404, detail="Network analysis task not found")
    if omics_verification:
        # ADR-0018 Gate 3 explicit opt-in: the default result path never
        # computes omics projections.
        if not omics_accession:
            raise HTTPException(
                status_code=422, detail="omics_accession is required for omics verification"
            )
        if payload.result is None:
            raise HTTPException(
                status_code=409,
                detail="omics verification requires a completed network analysis task",
            )
        try:
            payload.omics_verification = compute_omics_deg_projection(
                payload.result, accession=omics_accession
            )
        except OmicsSnapshotConflictError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OmicsVerificationBlockedError as exc:
            raise HTTPException(status_code=422, detail=exc.issues) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return payload


@router.post(
    "/result/{task_id}/adjudications",
    response_model=NetworkTargetAdjudicationRecord,
    status_code=status.HTTP_201_CREATED,
)
def submit_network_adjudication_endpoint(
    task_id: str,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
    request: NetworkAdjudicationRequest = Body(),
) -> NetworkTargetAdjudicationRecord:
    state, payload = submit_network_target_adjudication(task_id, reviewer_id, request)
    if state == "not_completed":
        raise HTTPException(
            status_code=409,
            detail="Only a completed network analysis task can be adjudicated",
        )
    if state == "unknown_row":
        raise HTTPException(
            status_code=422,
            detail="lineage_row_id does not exist in the task target lineage",
        )
    if state == "omics_row_symbol_mismatch":
        raise HTTPException(
            status_code=422,
            detail="lineage_row_id does not belong to the requested canonical symbol",
        )
    if state == "omics_snapshot_missing":
        raise HTTPException(
            status_code=404,
            detail="no frozen omics snapshot is sealed for the requested accession",
        )
    if state == "omics_unverified" or state == "omics_not_confirmed":
        raise HTTPException(
            status_code=422,
            detail=(
                "omics confirmation refused: the candidate does not exist in the freshly "
                "recomputed frozen DEG projection, or a frozen machine condition failed"
            ),
        )
    if state == "not_found" or payload is None:
        raise HTTPException(status_code=404, detail="Network analysis task not found")
    return payload


@router.post(
    "/result/{task_id}/assembly-plans",
    response_model=NetworkAssemblyPlan,
    status_code=status.HTTP_201_CREATED,
)
def seal_network_assembly_plan_endpoint(
    task_id: str,
    response: Response,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
) -> NetworkAssemblyPlan:
    state, payload = seal_network_assembly_plan(task_id, reviewer_id)
    if state == "not_found" or payload is None:
        raise HTTPException(status_code=404, detail="Network analysis task not found")
    if state == "blocked":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "assembly_gate_blocked",
                "gate": payload.model_dump(mode="json"),
            },
        )
    if state == "conflict":
        raise HTTPException(
            status_code=409,
            detail={"code": "gate_input_changed"},
        )
    if not isinstance(payload, NetworkAssemblyPlan):
        raise HTTPException(status_code=500, detail="Assembly plan persistence failed")
    if state == "existing":
        response.status_code = status.HTTP_200_OK
    return payload


@router.get(
    "/result/{task_id}/assembly-plans/{plan_id}",
    response_model=NetworkAssemblyPlanAuditView,
)
def get_network_assembly_plan_endpoint(
    task_id: str,
    plan_id: str,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
) -> NetworkAssemblyPlanAuditView:
    view = build_network_assembly_plan_audit_view(task_id, plan_id, reviewer_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Network assembly plan not found")
    return view


@router.post(
    "/result/{task_id}/assembly-plans/{plan_id}/consume",
    response_model=NetworkAssemblyConsumeAccepted,
    status_code=status.HTTP_201_CREATED,
)
def consume_network_assembly_plan_endpoint(
    task_id: str,
    plan_id: str,
    response: Response,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
    request: NetworkAssemblyConsumeRequest = Body(),
) -> NetworkAssemblyConsumeAccepted:
    """Writer consumption primitive (writer consumption contract, D1-D9 approved).

    Atomically proves the plan is still the latest revision, then appends the
    immutable output envelope and the exactly-once consumption record. A
    successful consume authorizes nothing scientific: ``formal_network_ready``
    stays false.
    """
    state, payload = consume_network_assembly_plan(task_id, plan_id, reviewer_id, request)
    if state == "not_found":
        raise HTTPException(status_code=404, detail="Network assembly plan not found")
    if state == "invalid_request":
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_consume_request", "checks": payload or []},
        )
    if state == "integrity_failed":
        raise HTTPException(
            status_code=500,
            detail={"code": "assembly_integrity_failed", "checks": payload or []},
        )
    if state == "broken_parent_link":
        raise HTTPException(status_code=409, detail={"code": "broken_parent_link"})
    if state == "already_consumed":
        raise HTTPException(status_code=409, detail={"code": "plan_already_consumed"})
    if state == "superseded":
        raise HTTPException(status_code=409, detail={"code": "plan_superseded"})
    if state == "conflict":
        raise HTTPException(status_code=409, detail={"code": "adjudication_changed"})
    if state == "capacity_exceeded":
        raise HTTPException(status_code=429, detail={"code": "consumption_limit_reached"})
    if state == "multi_process_blocked":
        raise HTTPException(
            status_code=409,
            detail={"code": "json_backend_multi_process_blocked"},
        )
    if not isinstance(payload, NetworkAssemblyConsumeAccepted):
        raise HTTPException(status_code=500, detail="Assembly consumption persistence failed")
    if state == "existing":
        response.status_code = status.HTTP_200_OK
    return payload


@router.get("/result/{task_id}/report", response_class=PlainTextResponse)
def network_report_endpoint(
    task_id: str,
    reviewer_id: Annotated[str, Depends(require_reviewer_id)],
) -> PlainTextResponse:
    state, payload = get_network_analysis_task(task_id, reviewer_id)
    if state == "not_found" or payload is None:
        raise HTTPException(status_code=404, detail="Network analysis task not found")
    if payload.status == "failed":
        raise HTTPException(status_code=409, detail=payload.error or "Network analysis task failed")
    if payload.status != "completed":
        raise HTTPException(status_code=202, detail="Network analysis task is still running")
    if payload.result is None:
        raise HTTPException(status_code=500, detail="Task completed but result is missing")
    markdown = build_network_report_markdown(
        payload.result,
        adjudication=payload.adjudication,
        assembly_gate=payload.assembly_gate,
    )
    return PlainTextResponse(content=markdown, media_type="text/plain; charset=utf-8")


@router.get("/entities", response_model=NetworkEntitiesResponse)
def network_entities_endpoint() -> NetworkEntitiesResponse:
    return list_all_entities()
