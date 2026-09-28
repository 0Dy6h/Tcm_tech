import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.schemas.network import (
    NetworkChain,
    NetworkCompoundTargetVerifyMetadata,
    NetworkDiseaseTargetImportSnapshot,
    NetworkDiseaseTargetVerifyMetadata,
    NetworkResearchProtocol,
)
from app.services.network_imports import (
    build_verified_compound_import_snapshot,
    build_verified_disease_import_snapshot,
)
from app.services.network_lineage import (
    assess_network_research_readiness,
    build_target_lineage,
)
from scripts.validate_network_target_lineage import validate


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _lineage_row_id(set_kind: str, row: dict[str, object]) -> str:
    identity = {
        "set_kind": set_kind,
        "source_database": row["source_database"],
        "database_version": row.get("database_version"),
        "source_query": row.get("source_query"),
        "query_date": row["query_date"],
        "retrieved_at": row.get("retrieved_at"),
        "species": row["species"],
        "source_record_ids": sorted(row["source_record_ids"]),
        "raw_identifier": row["raw_identifier"],
        "canonical_symbol": row["canonical_symbol"],
        "source_score": row.get("source_score"),
        "score_name": row.get("score_name"),
        "applied_threshold": row.get("applied_threshold"),
        "threshold_operator": row.get("threshold_operator"),
        "identifier_mapping": row["identifier_mapping"],
        "identifier_mapping_version": row.get("identifier_mapping_version"),
    }
    return f"{set_kind}-{_sha256(identity)}"


def _intersection_row_id(row: dict[str, object]) -> str:
    identity = {
        "derivation": "canonical_symbol_exact_match_v1",
        "canonical_symbol": row["canonical_symbol"],
        "disease_lineage_row_ids": sorted(row["disease_lineage_row_ids"]),
        "compound_lineage_row_ids": sorted(row["compound_lineage_row_ids"]),
    }
    return f"intersection-{_sha256(identity)}"


def _verified_dual_import_artifact() -> dict[str, object]:
    test_data = Path(__file__).parent / "data"
    disease_metadata = NetworkDiseaseTargetVerifyMetadata(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype="特应性皮炎伴 2 型炎症",
        species="Homo sapiens",
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatype": "overall"},
        query_date="2026-07-11",
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        usage_license_note="Open Targets Platform data; see platform terms.",
    )
    disease_snapshot = build_verified_disease_import_snapshot(
        (test_data / "open_targets_graphql_associations_25_06.json").read_bytes(),
        metadata=disease_metadata,
        source_artifact_filename="open-targets.json",
        source_artifact_media_type="application/json",
    )
    compound_metadata = NetworkCompoundTargetVerifyMetadata(
        source_profile="chembl_known_activity_v1",
        compound_id="CHEMBL1201587",
        compound_label="Quercetin",
        species="Homo sapiens",
        source_database="ChEMBL",
        database_version="34",
        source_query_id="CHEMBL1201587",
        source_query_label="Quercetin",
        source_query_parameters={
            "assay_organism": "Homo sapiens",
            "pchembl_value_min": 6.0,
        },
        query_date=disease_metadata.query_date,
        retrieved_at=disease_metadata.retrieved_at,
        score_name="pchembl_value",
        applied_threshold=6.0,
        threshold_operator="gte",
        identifier_mapping="ChEMBL target component gene symbol",
        identifier_mapping_version="34",
        usage_license_note="ChEMBL data; see database terms.",
    )
    compound_snapshot = build_verified_compound_import_snapshot(
        (test_data / "chembl_known_activities_34.json").read_bytes(),
        metadata=compound_metadata,
        source_artifact_filename="chembl-known-activities.json",
        source_artifact_media_type="application/json",
    )
    protocol = NetworkResearchProtocol(
        phenotype=disease_metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=disease_metadata.query_date,
    )
    lineage = build_target_lineage(
        [],
        protocol,
        "live",
        disease_snapshot,
        compound_target_import=compound_snapshot,
    )
    return {
        "task_id": "network-fedcba987654",
        "source_task_id": "network-0123456789ab",
        "chains": [],
        "enrichment": None,
        "ppi_edges": [],
        "data_sources": [],
        "pipeline_steps": [],
        "warnings": ["导入靶点尚未构建可复算的成分-靶点-通路网络闭环。"],
        "research_protocol": protocol.model_dump(mode="json"),
        "readiness": assess_network_research_readiness(
            protocol,
            "live",
            lineage,
        ).model_dump(mode="json"),
        "target_lineage": lineage.model_dump(mode="json"),
    }


def _set_invalid_numeric_value(
    artifact: dict[str, object],
    target: str,
    value: object,
) -> None:
    lineage = artifact["target_lineage"]
    assert isinstance(lineage, dict)
    disease_provenance = lineage["disease_import_provenance"]
    compound_provenance = lineage["compound_import_provenance"]
    disease_rows = lineage["disease_targets"]
    compound_rows = lineage["compound_targets"]
    assert isinstance(disease_provenance, dict)
    assert isinstance(compound_provenance, dict)
    assert isinstance(disease_rows, list) and disease_rows
    assert isinstance(compound_rows, list) and compound_rows
    assert isinstance(disease_rows[0], dict)
    assert isinstance(compound_rows[0], dict)

    if target == "disease_provenance_threshold":
        disease_provenance["applied_threshold"] = value
    elif target == "disease_row_score":
        disease_rows[0]["source_score"] = value
    elif target == "disease_row_threshold":
        disease_rows[0]["applied_threshold"] = value
    elif target == "compound_provenance_threshold":
        compound_provenance["applied_threshold"] = value
    elif target == "compound_query_threshold":
        query_parameters = compound_provenance["source_query_parameters"]
        assert isinstance(query_parameters, dict)
        query_parameters["pchembl_value_min"] = value
    elif target == "compound_row_score":
        compound_rows[0]["source_score"] = value
    elif target == "compound_row_threshold":
        compound_rows[0]["applied_threshold"] = value
    else:
        raise AssertionError(f"unsupported numeric mutation target: {target}")


@pytest.mark.parametrize(
    ("target", "expected_field", "upper_bound"),
    [
        ("disease_provenance_threshold", "disease import applied_threshold", 1),
        ("disease_row_score", "disease_targets[0].source_score", 1),
        ("disease_row_threshold", "disease_targets[0].applied_threshold", 1),
        ("compound_provenance_threshold", "compound import applied_threshold", 20),
        ("compound_query_threshold", "compound pchembl_value_min", 20),
        ("compound_row_score", "compound_targets[0].source_score", 20),
        ("compound_row_threshold", "compound_targets[0].applied_threshold", 20),
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [True, float("nan"), float("inf")],
    ids=["boolean", "nan", "infinity"],
)
def test_lineage_validator_rejects_non_finite_or_boolean_import_scores(
    target: str,
    expected_field: str,
    upper_bound: int,
    invalid_value: object,
) -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    _set_invalid_numeric_value(artifact, target, invalid_value)

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert (
        f"{expected_field} must be a finite numeric value in [0, {upper_bound}]" in output["issues"]
    )


@pytest.mark.parametrize(
    ("target", "expected_field", "out_of_range_value", "upper_bound"),
    [
        ("disease_provenance_threshold", "disease import applied_threshold", 1.01, 1),
        ("disease_row_score", "disease_targets[0].source_score", 1.01, 1),
        ("disease_row_threshold", "disease_targets[0].applied_threshold", 1.01, 1),
        ("compound_provenance_threshold", "compound import applied_threshold", 20.01, 20),
        ("compound_query_threshold", "compound pchembl_value_min", 20.01, 20),
        ("compound_row_score", "compound_targets[0].source_score", 20.01, 20),
        ("compound_row_threshold", "compound_targets[0].applied_threshold", 20.01, 20),
    ],
)
def test_lineage_validator_enforces_import_score_ranges(
    target: str,
    expected_field: str,
    out_of_range_value: float,
    upper_bound: int,
) -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    _set_invalid_numeric_value(artifact, target, out_of_range_value)

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert (
        f"{expected_field} must be a finite numeric value in [0, {upper_bound}]" in output["issues"]
    )


@pytest.mark.parametrize(
    ("provenance_key", "expected_issue"),
    [
        ("disease_import_provenance", "disease import record_count"),
        ("compound_import_provenance", "compound import record_count"),
    ],
)
def test_lineage_validator_rejects_boolean_import_record_counts(
    provenance_key: str,
    expected_issue: str,
) -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    lineage = artifact["target_lineage"]
    assert isinstance(lineage, dict)
    provenance = lineage[provenance_key]
    assert isinstance(provenance, dict)
    provenance["record_count"] = True

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert f"{expected_issue} must be a non-negative integer" in output["issues"]


@pytest.mark.parametrize("source_task_id", [None, "", "  ", "network-not-hex"])
def test_lineage_validator_requires_a_valid_compound_source_task_link(
    source_task_id: object,
) -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    artifact["source_task_id"] = source_task_id

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert "compound import result source_task_id is missing or invalid" in output["issues"]


def test_lineage_validator_rejects_a_compound_source_task_link_to_itself() -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    artifact["source_task_id"] = artifact["task_id"]

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert "compound import result source_task_id must not equal result.task_id" in output["issues"]


@pytest.mark.parametrize(
    ("field", "tampered_value", "expected_issue"),
    [
        ("chains", [{"target": "IL6"}], "compound import snapshot-only output requires chains=[]"),
        (
            "enrichment",
            {"terms": [{"term_id": "GO:0001"}]},
            "compound import snapshot-only output requires enrichment=null",
        ),
        (
            "ppi_edges",
            [{"source": "IL6", "target": "TNF"}],
            "compound import snapshot-only output requires ppi_edges=[]",
        ),
        (
            "data_sources",
            [{"name": "provider"}],
            "compound import snapshot-only output requires data_sources=[]",
        ),
        (
            "pipeline_steps",
            [{"name": "assembly"}],
            "compound import snapshot-only output requires pipeline_steps=[]",
        ),
    ],
)
def test_lineage_validator_rejects_provider_outputs_on_compound_snapshot(
    field: str,
    tampered_value: object,
    expected_issue: str,
) -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    artifact[field] = tampered_value

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert expected_issue in output["issues"]


def test_lineage_validator_requires_snapshot_only_readiness_blocker_and_warning() -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    readiness = artifact["readiness"]
    assert isinstance(readiness, dict)
    blocking_reasons = readiness["blocking_reasons"]
    assert isinstance(blocking_reasons, list)
    readiness["blocking_reasons"] = [
        reason for reason in blocking_reasons if "可复算的成分-靶点-通路网络闭环" not in reason
    ]
    artifact["warnings"] = []

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert "readiness must expose the snapshot-only network-assembly blocker" in output["issues"]
    assert (
        "compound import snapshot-only output must expose its network-assembly warning"
        in output["issues"]
    )


@pytest.mark.parametrize(
    ("set_name", "provenance_error"),
    [
        ("disease_targets", "disease target source_record_id values must be unique"),
        ("compound_targets", "compound target source_record_id values must be unique"),
    ],
)
def test_lineage_validator_rejects_reused_import_source_record_ids(
    set_name: str,
    provenance_error: str,
) -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    lineage = artifact["target_lineage"]
    assert isinstance(lineage, dict)
    rows = lineage[set_name]
    assert isinstance(rows, list) and len(rows) >= 2
    assert isinstance(rows[0], dict)
    assert isinstance(rows[1], dict)
    rows[1]["source_record_ids"] = [rows[0]["source_record_ids"][0]]

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert provenance_error in output["issues"]


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_issue"),
    [
        (
            "disease",
            "psoriasis",
            "research_protocol.disease must be atopic_dermatitis",
        ),
        (
            "phenotype",
            "   ",
            "research_protocol.phenotype must contain 4 to 200 non-whitespace characters",
        ),
        (
            "phenotype",
            "x" * 201,
            "research_protocol.phenotype must contain 4 to 200 non-whitespace characters",
        ),
        (
            "species",
            "Mus musculus",
            "research_protocol.species must be Homo sapiens",
        ),
        (
            "evidence_policy",
            "unsupported_policy",
            "research_protocol.evidence_policy is invalid",
        ),
        (
            "query_date",
            "not-a-date",
            "research_protocol.query_date must be an ISO date",
        ),
        (
            "query_date",
            "2999-01-01",
            "research_protocol.query_date cannot be in the future",
        ),
    ],
)
def test_lineage_validator_independently_validates_research_protocol(
    field: str,
    invalid_value: object,
    expected_issue: str,
) -> None:
    artifact = deepcopy(_verified_dual_import_artifact())
    protocol = artifact["research_protocol"]
    assert isinstance(protocol, dict)
    protocol[field] = invalid_value

    output = validate(artifact)

    assert output["artifact_consistency_pass"] is False
    assert expected_issue in output["issues"]


def test_lineage_validator_independently_recomputes_counts_and_intersection(tmp_path: Path) -> None:
    artifact_path = tmp_path / "network-result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "research_protocol": {
                    "disease": "atopic_dermatitis",
                    "phenotype": "特应性皮炎伴 2 型炎症",
                    "species": "Homo sapiens",
                    "evidence_policy": "direct_human_first",
                    "query_date": "2026-07-11",
                },
                "target_lineage": {
                    "observation_unit": "target_record",
                    "disease_targets": [],
                    "compound_targets": [
                        {
                            "canonical_symbol": "IL6",
                            "query_date": "2026-07-11",
                            "species": "Homo sapiens",
                        }
                    ],
                    "intersection_targets": [],
                    "disease_target_count": 0,
                    "compound_target_count": 1,
                    "intersection_target_count": 0,
                    "disease_lineage_row_count": 0,
                    "compound_lineage_row_count": 1,
                    "intersection_lineage_row_count": 0,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/validate_network_target_lineage.py", str(artifact_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["artifact_consistency_pass"] is True
    assert payload["recomputed"]["compound_target_count"] == 1
    assert payload["recomputed"]["intersection_target_count"] == 0


def test_lineage_validator_rejects_fabricated_intersection(tmp_path: Path) -> None:
    artifact_path = tmp_path / "fabricated-intersection.json"
    target_row = {
        "canonical_symbol": "IL6",
        "query_date": "2026-07-11",
        "species": "Homo sapiens",
    }
    artifact_path.write_text(
        json.dumps(
            {
                "research_protocol": {
                    "species": "Homo sapiens",
                    "query_date": "2026-07-11",
                },
                "target_lineage": {
                    "disease_targets": [],
                    "compound_targets": [target_row],
                    "intersection_targets": [target_row],
                    "disease_target_count": 0,
                    "compound_target_count": 1,
                    "intersection_target_count": 1,
                    "disease_lineage_row_count": 0,
                    "compound_lineage_row_count": 1,
                    "intersection_lineage_row_count": 1,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/validate_network_target_lineage.py", str(artifact_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["artifact_consistency_pass"] is False
    assert payload["declared_intersection_symbols"] == ["IL6"]
    assert payload["expected_intersection_symbols"] == []


def test_lineage_validator_rejects_fabricated_intersection_lineage_refs(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "fabricated-lineage-refs.json"
    disease_row: dict[str, object] = {
        "raw_identifier": "ENSG00000136244",
        "canonical_symbol": "IL6",
        "source_database": "Open Targets Platform",
        "database_version": "25.06",
        "source_query": "EFO_0000274",
        "query_date": "2026-07-11",
        "retrieved_at": "2026-07-11T08:30:00+00:00",
        "species": "Homo sapiens",
        "source_score": 0.91,
        "score_name": "association_score",
        "applied_threshold": 0.6,
        "threshold_operator": "gte",
        "identifier_mapping": "Ensembl target approvedSymbol",
        "identifier_mapping_version": "25.06",
        "source_record_ids": ["EFO_0000274:ENSG00000136244"],
        "automatic_status": "extracted",
        "adjudication_status": "pending",
        "reviewer_id": None,
        "reviewed_at": None,
        "decision": "unreviewed",
        "decision_rationale": None,
    }
    disease_row["lineage_row_id"] = _lineage_row_id("disease", disease_row)
    compound_row: dict[str, object] = {
        "raw_identifier": "IL6",
        "canonical_symbol": "IL6",
        "source_database": "qiyan_sample_network",
        "database_version": None,
        "source_query": None,
        "query_date": "2026-07-11",
        "retrieved_at": None,
        "species": "Homo sapiens",
        "source_score": 0.87,
        "score_name": None,
        "applied_threshold": None,
        "threshold_operator": None,
        "identifier_mapping": "identity_symbol",
        "identifier_mapping_version": None,
        "source_record_ids": ["target-il6"],
        "automatic_status": "extracted",
        "adjudication_status": "pending",
        "reviewer_id": None,
        "reviewed_at": None,
        "decision": "unreviewed",
        "decision_rationale": None,
    }
    compound_row["lineage_row_id"] = _lineage_row_id("compound", compound_row)
    fake_disease_ref = f"disease-{'f' * 64}"
    intersection = {
        "lineage_row_id": f"intersection-{'e' * 64}",
        "canonical_symbol": "IL6",
        "query_date": "2026-07-11",
        "species": "Homo sapiens",
        "derivation": "canonical_symbol_exact_match_v1",
        "disease_lineage_row_ids": [fake_disease_ref],
        "compound_lineage_row_ids": [compound_row["lineage_row_id"]],
        "automatic_status": "derived",
        "adjudication_status": "pending",
        "reviewer_id": None,
        "reviewed_at": None,
        "decision": "unreviewed",
        "decision_rationale": None,
    }
    artifact_path.write_text(
        json.dumps(
            {
                "research_protocol": {
                    "disease": "atopic_dermatitis",
                    "phenotype": "特应性皮炎伴 2 型炎症与皮肤屏障异常",
                    "species": "Homo sapiens",
                    "evidence_policy": "direct_human_first",
                    "query_date": "2026-07-11",
                },
                "target_lineage": {
                    "disease_targets": [disease_row],
                    "compound_targets": [compound_row],
                    "intersection_targets": [intersection],
                    "disease_target_count": 1,
                    "compound_target_count": 1,
                    "intersection_target_count": 1,
                    "disease_lineage_row_count": 1,
                    "compound_lineage_row_count": 1,
                    "intersection_lineage_row_count": 1,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/validate_network_target_lineage.py", str(artifact_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["artifact_consistency_pass"] is False
    assert any("disease_lineage_row_ids" in issue for issue in payload["issues"])


def test_lineage_validator_accepts_a_nonempty_server_derived_intersection(
    tmp_path: Path,
) -> None:
    import_payload = {
        "source_profile": "open_targets_association_v1",
        "disease": "atopic_dermatitis",
        "phenotype": "特应性皮炎伴 2 型炎症",
        "species": "Homo sapiens",
        "source_database": "Open Targets Platform",
        "database_version": "25.06",
        "source_query_id": "EFO_0000274",
        "source_query_label": "atopic eczema",
        "source_query_parameters": {"datatypes": ["genetic_association"]},
        "query_date": "2026-07-11",
        "retrieved_at": "2026-07-11T08:30:00Z",
        "score_name": "association_score",
        "applied_threshold": 0.6,
        "threshold_operator": "gte",
        "identifier_mapping": "Ensembl target approvedSymbol",
        "identifier_mapping_version": "25.06",
        "records": [
            {
                "raw_identifier": "ENSG00000136244",
                "canonical_symbol": "IL6",
                "source_record_id": "EFO_0000274:ENSG00000136244",
                "source_score": 0.91,
            }
        ],
    }
    snapshot = NetworkDiseaseTargetImportSnapshot.model_validate(
        {
            **import_payload,
            "provenance_verification_status": "unverified_client_import",
            "import_payload_sha256": _sha256(import_payload),
        }
    )
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    lineage = build_target_lineage(
        [
            NetworkChain(
                herb="荆芥",
                formula="消风散",
                compound="槲皮素",
                target="IL6",
                pathway="PI3K-Akt signaling",
                disease="Atopic dermatitis",
                score=0.87,
                related_entity_ids=["target-il6"],
            )
        ],
        protocol,
        "mock",
        snapshot,
    )
    artifact_path = tmp_path / "valid-nonempty-lineage.json"
    artifact_path.write_text(
        json.dumps(
            {
                "research_protocol": protocol.model_dump(mode="json"),
                "readiness": assess_network_research_readiness(
                    protocol, "mock", lineage
                ).model_dump(mode="json"),
                "target_lineage": lineage.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/validate_network_target_lineage.py", str(artifact_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["artifact_consistency_pass"] is True
    assert payload["expected_intersection_symbols"] == ["IL6"]

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    disease_row = artifact["target_lineage"]["disease_targets"][0]
    disease_row["database_version"] = "tampered-version"
    disease_row["lineage_row_id"] = _lineage_row_id("disease", disease_row)
    intersection = artifact["target_lineage"]["intersection_targets"][0]
    intersection["disease_lineage_row_ids"] = [disease_row["lineage_row_id"]]
    intersection["lineage_row_id"] = _intersection_row_id(intersection)
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")

    tampered = subprocess.run(
        [sys.executable, "scripts/validate_network_target_lineage.py", str(artifact_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert tampered.returncode == 2
    tampered_payload = json.loads(tampered.stdout)
    assert any("database_version" in issue for issue in tampered_payload["issues"])


def test_lineage_validator_recomputes_verified_raw_artifact_hash(tmp_path: Path) -> None:
    raw_artifact = tmp_path / "open-targets.jsonl"
    raw_artifact.write_bytes(
        (
            Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
        ).read_bytes()
    )
    metadata = NetworkDiseaseTargetVerifyMetadata(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype="特应性皮炎伴 2 型炎症",
        species="Homo sapiens",
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatype": "overall"},
        query_date="2026-07-11",
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        usage_license_note="Open Targets Platform data; see platform terms.",
    )
    snapshot = build_verified_disease_import_snapshot(
        raw_artifact.read_bytes(),
        metadata=metadata,
        source_artifact_filename=raw_artifact.name,
        source_artifact_media_type="application/x-ndjson",
    )
    protocol = NetworkResearchProtocol(
        phenotype=metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=metadata.query_date,
    )
    lineage = build_target_lineage([], protocol, "live", snapshot)
    artifact_path = tmp_path / "verified-result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "research_protocol": protocol.model_dump(mode="json"),
                "readiness": assess_network_research_readiness(
                    protocol, "live", lineage
                ).model_dump(mode="json"),
                "target_lineage": lineage.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "scripts/validate_network_target_lineage.py",
        str(artifact_path),
        "--source-artifact",
        str(raw_artifact),
    ]

    valid = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stdout

    raw_artifact.write_bytes(raw_artifact.read_bytes() + b"\n")
    tampered = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered.returncode == 2
    assert "source_artifact_sha256" in tampered.stdout


def test_lineage_validator_recomputes_verified_compound_raw_artifact_hash(tmp_path: Path) -> None:
    disease_raw_artifact = tmp_path / "open-targets.json"
    disease_raw_artifact.write_bytes(
        (
            Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
        ).read_bytes()
    )
    raw_artifact = tmp_path / "chembl-known-activities.json"
    raw_artifact.write_bytes(
        (Path(__file__).parent / "data" / "chembl_known_activities_34.json").read_bytes()
    )
    metadata = NetworkCompoundTargetVerifyMetadata(
        source_profile="chembl_known_activity_v1",
        compound_id="CHEMBL1201587",
        compound_label="Quercetin",
        species="Homo sapiens",
        source_database="ChEMBL",
        database_version="34",
        source_query_id="CHEMBL1201587",
        source_query_label="Quercetin",
        source_query_parameters={"assay_organism": "Homo sapiens", "pchembl_value_min": 6.0},
        query_date="2026-07-11",
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="pchembl_value",
        applied_threshold=6.0,
        threshold_operator="gte",
        identifier_mapping="ChEMBL target component gene symbol",
        identifier_mapping_version="34",
        usage_license_note="ChEMBL data; see database terms.",
    )
    snapshot = build_verified_compound_import_snapshot(
        raw_artifact.read_bytes(),
        metadata=metadata,
        source_artifact_filename=raw_artifact.name,
        source_artifact_media_type="application/json",
    )
    disease_metadata = NetworkDiseaseTargetVerifyMetadata(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype="特应性皮炎伴 2 型炎症",
        species="Homo sapiens",
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatype": "overall"},
        query_date=metadata.query_date,
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        usage_license_note="Open Targets Platform data; see platform terms.",
    )
    disease_snapshot = build_verified_disease_import_snapshot(
        disease_raw_artifact.read_bytes(),
        metadata=disease_metadata,
        source_artifact_filename=disease_raw_artifact.name,
        source_artifact_media_type="application/json",
    )
    protocol = NetworkResearchProtocol(
        phenotype=disease_metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=metadata.query_date,
    )
    lineage = build_target_lineage(
        [],
        protocol,
        "live",
        disease_snapshot,
        compound_target_import=snapshot,
    )
    artifact_path = tmp_path / "verified-compound-result.json"
    artifact_path.write_text(
        json.dumps(
            {
                "task_id": "network-fedcba987654",
                "source_task_id": "network-0123456789ab",
                "chains": [],
                "enrichment": None,
                "ppi_edges": [],
                "data_sources": [],
                "pipeline_steps": [],
                "warnings": ["导入靶点尚未构建可复算的成分-靶点-通路网络闭环。"],
                "research_protocol": protocol.model_dump(mode="json"),
                "readiness": assess_network_research_readiness(
                    protocol, "live", lineage
                ).model_dump(mode="json"),
                "target_lineage": lineage.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "scripts/validate_network_target_lineage.py",
        str(artifact_path),
        "--source-artifact",
        str(disease_raw_artifact),
        "--compound-source-artifact",
        str(raw_artifact),
    ]

    valid = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stdout

    original_artifact = artifact_path.read_text(encoding="utf-8")
    tampered_artifact = json.loads(original_artifact)
    tampered_artifact["target_lineage"]["compound_import_provenance"]["usage_license_note"] = (
        "Changed after export."
    )
    artifact_path.write_text(
        json.dumps(tampered_artifact, ensure_ascii=False),
        encoding="utf-8",
    )
    tampered_metadata = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered_metadata.returncode == 2
    assert "compound import payload hash" in tampered_metadata.stdout
    artifact_path.write_text(original_artifact, encoding="utf-8")

    tampered_query = json.loads(original_artifact)
    compound_provenance = tampered_query["target_lineage"]["compound_import_provenance"]
    compound_provenance["source_query_parameters"]["pchembl_value_min"] = 19.0
    compound_records = [
        {
            "raw_identifier": row["raw_identifier"],
            "canonical_symbol": row["canonical_symbol"],
            "source_record_id": row["source_record_ids"][0],
            "source_score": row["source_score"],
        }
        for row in tampered_query["target_lineage"]["compound_targets"]
    ]
    compound_provenance["import_payload_sha256"] = _sha256(
        {
            "source_profile": compound_provenance["source_profile"],
            "compound_id": compound_provenance["compound_id"],
            "compound_label": compound_provenance["compound_label"],
            "species": compound_provenance["species"],
            "source_database": compound_provenance["source_database"],
            "database_version": compound_provenance["database_version"],
            "source_query_id": compound_provenance["source_query_id"],
            "source_query_label": compound_provenance["source_query_label"],
            "source_query_parameters": compound_provenance["source_query_parameters"],
            "query_date": compound_provenance["query_date"],
            "retrieved_at": compound_provenance["retrieved_at"],
            "score_name": compound_provenance["score_name"],
            "applied_threshold": compound_provenance["applied_threshold"],
            "threshold_operator": compound_provenance["threshold_operator"],
            "identifier_mapping": compound_provenance["identifier_mapping"],
            "identifier_mapping_version": compound_provenance["identifier_mapping_version"],
            "usage_license_note": compound_provenance["usage_license_note"],
            "records": compound_records,
        }
    )
    artifact_path.write_text(
        json.dumps(tampered_query, ensure_ascii=False),
        encoding="utf-8",
    )
    tampered_query_result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered_query_result.returncode == 2
    assert "pchembl_value_min" in tampered_query_result.stdout
    artifact_path.write_text(original_artifact, encoding="utf-8")

    raw_artifact.write_bytes(raw_artifact.read_bytes() + b"\n")
    tampered = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered.returncode == 2
    assert "compound source_artifact_sha256" in tampered.stdout


def test_lineage_validator_rejects_compound_provenance_without_verified_disease_parent(
    tmp_path: Path,
) -> None:
    raw_artifact = tmp_path / "chembl-known-activities.json"
    raw_artifact.write_bytes(
        (Path(__file__).parent / "data" / "chembl_known_activities_34.json").read_bytes()
    )
    metadata = NetworkCompoundTargetVerifyMetadata(
        source_profile="chembl_known_activity_v1",
        compound_id="CHEMBL1201587",
        compound_label="Quercetin",
        species="Homo sapiens",
        source_database="ChEMBL",
        database_version="34",
        source_query_id="CHEMBL1201587",
        source_query_label="Quercetin",
        source_query_parameters={"assay_organism": "Homo sapiens", "pchembl_value_min": 6.0},
        query_date="2026-07-11",
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="pchembl_value",
        applied_threshold=6.0,
        threshold_operator="gte",
        identifier_mapping="ChEMBL target component gene symbol",
        identifier_mapping_version="34",
        usage_license_note="ChEMBL data; see database terms.",
    )
    snapshot = build_verified_compound_import_snapshot(
        raw_artifact.read_bytes(),
        metadata=metadata,
        source_artifact_filename=raw_artifact.name,
        source_artifact_media_type="application/json",
    )
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date=metadata.query_date,
    )
    lineage = build_target_lineage([], protocol, "live", compound_target_import=snapshot)

    output = validate(
        {
            "research_protocol": protocol.model_dump(mode="json"),
            "readiness": assess_network_research_readiness(protocol, "live", lineage).model_dump(
                mode="json"
            ),
            "target_lineage": lineage.model_dump(mode="json"),
        },
        compound_source_artifact_path=raw_artifact,
    )

    assert output["artifact_consistency_pass"] is False
    assert any("server-verified disease parent" in issue for issue in output["issues"])


def test_lineage_validator_requires_empty_research_set_readiness_blockers(
    tmp_path: Path,
) -> None:
    disease_raw_artifact = tmp_path / "open-targets.json"
    disease_raw_artifact.write_bytes(
        (
            Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
        ).read_bytes()
    )
    compound_raw_artifact = tmp_path / "chembl-known-activities.json"
    compound_raw_artifact.write_bytes(
        (Path(__file__).parent / "data" / "chembl_known_activities_34.json").read_bytes()
    )
    disease_metadata = NetworkDiseaseTargetVerifyMetadata(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype="特应性皮炎伴 2 型炎症",
        species="Homo sapiens",
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatype": "overall"},
        query_date="2026-07-11",
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        usage_license_note="Open Targets Platform data; see platform terms.",
    )
    disease_snapshot = build_verified_disease_import_snapshot(
        disease_raw_artifact.read_bytes(),
        metadata=disease_metadata,
        source_artifact_filename=disease_raw_artifact.name,
        source_artifact_media_type="application/json",
    )
    empty_disease_payload = disease_snapshot.model_dump(
        mode="json",
        exclude={
            "provenance_verification_status",
            "import_payload_sha256",
            "source_artifact_sha256",
            "source_artifact_filename",
            "source_artifact_media_type",
            "records",
        },
    )
    empty_disease_payload["records"] = []
    disease_snapshot = disease_snapshot.model_copy(
        update={
            "records": [],
            "import_payload_sha256": _sha256(empty_disease_payload),
        }
    )
    compound_metadata = NetworkCompoundTargetVerifyMetadata(
        source_profile="chembl_known_activity_v1",
        compound_id="CHEMBL1201587",
        compound_label="Quercetin",
        species="Homo sapiens",
        source_database="ChEMBL",
        database_version="34",
        source_query_id="CHEMBL1201587",
        source_query_label="Quercetin",
        source_query_parameters={"assay_organism": "Homo sapiens", "pchembl_value_min": 6.0},
        query_date=disease_metadata.query_date,
        retrieved_at=disease_metadata.retrieved_at,
        score_name="pchembl_value",
        applied_threshold=6.0,
        threshold_operator="gte",
        identifier_mapping="ChEMBL target component gene symbol",
        identifier_mapping_version="34",
        usage_license_note="ChEMBL data; see database terms.",
    )
    compound_snapshot = build_verified_compound_import_snapshot(
        compound_raw_artifact.read_bytes(),
        metadata=compound_metadata,
        source_artifact_filename=compound_raw_artifact.name,
        source_artifact_media_type="application/json",
    )
    protocol = NetworkResearchProtocol(
        phenotype=disease_metadata.phenotype,
        evidence_policy="direct_human_first",
        query_date=disease_metadata.query_date,
    )
    lineage = build_target_lineage(
        [],
        protocol,
        "live",
        disease_snapshot,
        compound_target_import=compound_snapshot,
    )
    readiness = assess_network_research_readiness(protocol, "live", lineage).model_dump(mode="json")
    readiness["blocking_reasons"] = [
        reason
        for reason in readiness["blocking_reasons"]
        if "疾病靶点集合为空" not in reason and "派生交集为空" not in reason
    ]

    output = validate(
        {
            "research_protocol": protocol.model_dump(mode="json"),
            "readiness": readiness,
            "target_lineage": lineage.model_dump(mode="json"),
        },
        source_artifact_path=disease_raw_artifact,
        compound_source_artifact_path=compound_raw_artifact,
    )

    assert output["artifact_consistency_pass"] is False
    assert any("empty disease-target set blocker" in issue for issue in output["issues"])
    assert any("empty intersection blocker" in issue for issue in output["issues"])
