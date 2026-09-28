"""Independent validator tests for the source-bound network assembly plan.

The validator is a separate, producer-independent recomputation path. These
tests prove it accepts a genuinely sealed plan produced through the live API
flow, and that it rejects every tampered binding: altered hashes, altered
selection, altered decisions, altered row references, plan id derivation and
snapshot-only boundary violations.
"""

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.runtime_storage import (
    clear_network_task_repository_cache,
    get_network_task_repository,
)
from scripts.validate_network_assembly_plan import validate

OPEN_TARGETS_FIXTURE = (
    Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
)
CHEMBL_FIXTURE = Path(__file__).parent / "data" / "chembl_known_activities_34.json"

DISEASE_METADATA = {
    "source_profile": "open_targets_association_v1",
    "disease": "atopic_dermatitis",
    "phenotype": "特应性皮炎伴 2 型炎症与皮肤屏障异常",
    "species": "Homo sapiens",
    "source_database": "Open Targets Platform",
    "database_version": "25.06",
    "source_query_id": "EFO_0000274",
    "source_query_label": "atopic eczema",
    "source_query_parameters": {"datatype": "overall"},
    "query_date": "2026-07-11",
    "retrieved_at": "2026-07-11T08:30:00Z",
    "score_name": "association_score",
    "applied_threshold": 0.6,
    "threshold_operator": "gte",
    "identifier_mapping": "Ensembl target approvedSymbol",
    "identifier_mapping_version": "25.06",
    "usage_license_note": "Open Targets Platform data; see platform terms.",
}

COMPOUND_METADATA = {
    "source_profile": "chembl_known_activity_v1",
    "compound_id": "CHEMBL1201587",
    "compound_label": "Quercetin",
    "species": "Homo sapiens",
    "source_database": "ChEMBL",
    "database_version": "34",
    "source_query_id": "CHEMBL1201587",
    "source_query_label": "Quercetin",
    "source_query_parameters": {
        "assay_organism": "Homo sapiens",
        "standard_type": "IC50",
        "pchembl_value_min": 6.0,
    },
    "query_date": "2026-07-11",
    "retrieved_at": "2026-07-11T08:30:00Z",
    "score_name": "pchembl_value",
    "applied_threshold": 6.0,
    "threshold_operator": "gte",
    "identifier_mapping": "ChEMBL target component gene symbol",
    "identifier_mapping_version": "34",
    "usage_license_note": "ChEMBL data; see database terms.",
}


@pytest.fixture(autouse=True)
def _isolate_network_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_network_task_repository_cache()
    monkeypatch.setenv(
        "NETWORK_TASKS_RUNTIME_STATE_PATH", str(tmp_path / "network_tasks_state.json")
    )
    monkeypatch.setenv("NETWORK_RAW_ARTIFACT_DIR", str(tmp_path / "network_raw_artifacts"))
    disease_manifest = tmp_path / "trusted-open-targets-manifest.json"
    disease_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    hashlib.sha256(OPEN_TARGETS_FIXTURE.read_bytes()).hexdigest(): DISEASE_METADATA
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    compound_manifest = tmp_path / "trusted-chembl-manifest.json"
    compound_manifest.write_text(
        json.dumps(
            {
                "artifacts": {
                    hashlib.sha256(CHEMBL_FIXTURE.read_bytes()).hexdigest(): COMPOUND_METADATA
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NETWORK_OPEN_TARGETS_MANIFEST_PATH", str(disease_manifest))
    monkeypatch.setenv("NETWORK_CHEMBL_MANIFEST_PATH", str(compound_manifest))
    yield
    clear_network_task_repository_cache()


WRITER_OUTPUT_PAYLOAD = {
    "format": "qiyan-assembly-writer-v1",
    "edges": [{"source": "Quercetin", "target": "IL6", "weight": 0.75}],
}


def _run_flow(client: TestClient) -> tuple[dict[str, object], str, str]:
    """Run the real API flow; return the evidence package plus child/plan ids."""
    disease_response = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(DISEASE_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                OPEN_TARGETS_FIXTURE.name,
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )
    assert disease_response.status_code == 202
    parent_id = disease_response.json()["task_id"]
    assert client.get(f"/api/network/result/{parent_id}").status_code == 200
    parent_completed = client.get(f"/api/network/result/{parent_id}")
    assert parent_completed.json()["status"] == "completed"

    child_response = client.post(
        "/api/network/compound-import/verify",
        data={
            "source_task_id": parent_id,
            "metadata": json.dumps(COMPOUND_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                CHEMBL_FIXTURE.name,
                CHEMBL_FIXTURE.read_bytes(),
                "application/json",
            )
        },
    )
    assert child_response.status_code == 202
    child_id = child_response.json()["task_id"]
    assert client.get(f"/api/network/result/{child_id}").json()["status"] == "running"
    child_payload = client.get(f"/api/network/result/{child_id}").json()
    assert child_payload["status"] == "completed"

    for set_name in ("disease_targets", "compound_targets", "intersection_targets"):
        for row in child_payload["result"]["target_lineage"][set_name]:
            created = client.post(
                f"/api/network/result/{child_id}/adjudications",
                json={"lineage_row_id": row["lineage_row_id"], "decision": "included"},
            )
            assert created.status_code == 201

    sealed = client.post(f"/api/network/result/{child_id}/assembly-plans")
    assert sealed.status_code == 201
    plan = sealed.json()

    parent_payload = client.get(f"/api/network/result/{parent_id}").json()
    child_result = child_payload["result"]
    record = get_network_task_repository().get_owned(child_id, "local-preview")
    assert record is not None
    adjudications = [
        event.model_dump(mode="json", exclude={"reviewer_id"}) for event in record.adjudications
    ]
    return (
        {
            "plan": plan,
            "child_result": child_result,
            "parent_protocol": parent_payload["result"]["research_protocol"],
            "child_protocol": child_result["research_protocol"],
            "adjudications": adjudications,
            "raw_artifact_dir": os.environ["NETWORK_RAW_ARTIFACT_DIR"],
        },
        child_id,
        plan["plan_id"],
    )


def _build_evidence(client: TestClient) -> dict[str, object]:
    """Run the real API flow and assemble a public evidence package."""
    return _run_flow(client)[0]


def _build_consumed_evidence(client: TestClient) -> dict[str, object]:
    """Seal a plan through the API, consume it, and extend the package."""
    evidence, child_id, plan_id = _run_flow(client)
    consume = client.post(
        f"/api/network/result/{child_id}/assembly-plans/{plan_id}/consume",
        json={"writer_id": "assembly-writer-1", "output_payload": WRITER_OUTPUT_PAYLOAD},
    )
    assert consume.status_code == 201, consume.text
    accepted = consume.json()
    consumptions = [
        item.model_dump(mode="json")
        for item in get_network_task_repository().list_assembly_consumptions(
            child_id, "local-preview"
        )
    ]
    assert len(consumptions) == 1
    return {
        **evidence,
        "outputs": [accepted["output"]],
        "consumptions": consumptions,
        "output_payload": WRITER_OUTPUT_PAYLOAD,
    }


def test_validator_accepts_a_plan_sealed_through_the_live_api() -> None:
    client = TestClient(app)
    evidence = _build_evidence(client)

    ok, issues = validate(evidence)

    assert ok, issues
    assert issues == []


def test_validator_rejects_every_tampered_plan_binding() -> None:
    client = TestClient(app)
    evidence = _build_evidence(client)

    mutations: list[tuple[str, dict[str, object]]] = []

    altered_plan_id = deepcopy(evidence)
    altered_plan_id["plan"] = {**evidence["plan"], "plan_id": "assembly-plan-" + "0" * 64}
    mutations.append(("plan_id does not derive from the canonical plan input", altered_plan_id))

    altered_input_hash = deepcopy(evidence)
    altered_input_hash["plan"] = {
        **evidence["plan"],
        "canonical_plan_input_sha256": "0" * 64,
    }
    mutations.append(("plan.canonical_plan_input_sha256 does not match", altered_input_hash))

    altered_lineage_hash = deepcopy(evidence)
    altered_lineage_hash["plan"] = {
        **evidence["plan"],
        "target_lineage_sha256": "0" * 64,
    }
    mutations.append(("plan.target_lineage_sha256 does not match", altered_lineage_hash))

    altered_adjudication_hash = deepcopy(evidence)
    altered_adjudication_hash["plan"] = {
        **evidence["plan"],
        "adjudication_selection_sha256": "0" * 64,
    }
    mutations.append(
        (
            "plan.adjudication_selection_sha256 does not match the latest-wins snapshot",
            altered_adjudication_hash,
        )
    )

    altered_selection = deepcopy(evidence)
    altered_selection["plan"] = {
        **evidence["plan"],
        "selected_intersections": [
            {
                **evidence["plan"]["selected_intersections"][0],
                "selected_disease_lineage_row_ids": [],
            }
        ],
    }
    mutations.append(("plan.selected_intersections do not match", altered_selection))

    altered_protocol = deepcopy(evidence)
    altered_protocol["child_protocol"] = {
        **evidence["child_protocol"],
        "phenotype": "被篡改的表型描述",
    }
    mutations.append(("plan.child_protocol_sha256 does not match child_protocol", altered_protocol))

    snapshot_violation = deepcopy(evidence)
    snapshot_violation["child_result"] = {
        **evidence["child_result"],
        "chains": [
            {
                "herb": "消风散",
                "compound": "Quercetin",
                "target": "IL6",
                "pathway": "x",
                "disease": "atopic_dermatitis",
                "score": 0.9,
                "related_entity_ids": [],
            }
        ],
    }
    mutations.append(("child_result.chains must be empty (snapshot-only)", snapshot_violation))

    incomplete = deepcopy(evidence)
    incomplete["adjudications"] = evidence["adjudications"][:-1]
    mutations.append(("adjudication is incomplete for rows", incomplete))

    pending_review = deepcopy(evidence)
    pending_review["adjudications"] = [
        *evidence["adjudications"],
        {
            "adjudication_id": "adjudication-" + "9" * 64,
            "lineage_row_id": evidence["adjudications"][-1]["lineage_row_id"],
            "decision": "needs_review",
            "reason": None,
            "decided_at": "2026-08-02T12:00:00+00:00",
        },
    ]
    mutations.append(("adjudication is incomplete for rows", pending_review))

    for expected_issue, mutated in mutations:
        ok, issues = validate(mutated)
        assert not ok, f"expected validator to reject: {expected_issue}"
        assert any(expected_issue in issue for issue in issues), (expected_issue, issues)


def test_validator_rejects_tampered_raw_artifact_bytes() -> None:
    client = TestClient(app)
    evidence = _build_evidence(client)
    child_result = evidence["child_result"]
    disease_hash = child_result["target_lineage"]["disease_import_provenance"][
        "source_artifact_sha256"
    ]
    tampered_dir = Path(os.environ["NETWORK_RAW_ARTIFACT_DIR"])
    artifact_path = tampered_dir / f"{disease_hash}.json"
    artifact_path.write_bytes(b"tampered raw bytes")

    ok, issues = validate(evidence)

    assert not ok
    assert any("raw artifact bytes do not match" in issue for issue in issues)


def test_validator_never_requires_reviewer_identity_in_the_public_package() -> None:
    client = TestClient(app)
    evidence = _build_evidence(client)

    assert "reviewer_id" not in json.dumps(evidence["adjudications"])
    assert "reviewer_id" not in json.dumps(evidence["plan"])
    ok, issues = validate(evidence)
    assert ok, issues


def test_validator_accepts_consumed_output_envelope_and_consumption_bindings() -> None:
    client = TestClient(app)
    evidence = _build_consumed_evidence(client)
    output = evidence["outputs"][0]
    assert output["chains"], "fixture flow must produce assembled chains"

    ok, issues = validate(evidence)

    assert ok, issues
    assert issues == []


def test_validator_rejects_every_tampered_output_binding() -> None:
    client = TestClient(app)
    evidence = _build_consumed_evidence(client)
    non_intersection_row_id = evidence["child_result"]["target_lineage"]["disease_targets"][0][
        "lineage_row_id"
    ]

    def with_output(**changes: object) -> dict[str, object]:
        mutated = deepcopy(evidence)
        mutated["outputs"] = [{**evidence["outputs"][0], **changes}]
        return mutated

    def with_chain(**changes: object) -> dict[str, object]:
        mutated = deepcopy(evidence)
        mutated["outputs"] = [
            {
                **evidence["outputs"][0],
                "chains": [{**evidence["outputs"][0]["chains"][0], **changes}],
            }
        ]
        return mutated

    def with_consumption(index: int, **changes: object) -> dict[str, object]:
        mutated = deepcopy(evidence)
        mutated["consumptions"] = [
            {**item, **changes} if position == index else item
            for position, item in enumerate(evidence["consumptions"])
        ]
        return mutated

    duplicate = deepcopy(evidence)
    duplicate["consumptions"] = [
        *evidence["consumptions"],
        {**evidence["consumptions"][0], "consumption_id": "assembly-consumption-" + "1" * 64},
    ]
    orphan_output = deepcopy(evidence)
    orphan_output["consumptions"] = []
    tampered_payload = deepcopy(evidence)
    tampered_payload["output_payload"] = {
        **WRITER_OUTPUT_PAYLOAD,
        "edges": [{"source": "Quercetin", "target": "IL6", "weight": 0.9}],
    }

    mutations: list[tuple[str, dict[str, object]]] = [
        (
            "output.output_id does not derive",
            with_output(output_id="assembly-output-" + "0" * 64),
        ),
        (
            "output.output_sha256 does not match the provided output_payload",
            with_output(output_sha256="0" * 64),
        ),
        (
            "output.plan_sequence does not match plan.plan_sequence",
            with_output(plan_sequence=evidence["outputs"][0]["plan_sequence"] + 1),
        ),
        (
            "output.canonical_plan_input_sha256 does not match plan.canonical_plan_input_sha256",
            with_output(canonical_plan_input_sha256="0" * 64),
        ),
        (
            "output.output_sha256 does not match the provided output_payload",
            tampered_payload,
        ),
        (
            "output.disclaimer",
            with_output(disclaimer="仅供参考。"),
        ),
        (
            "output.formal_network_ready must be false",
            with_output(formal_network_ready=True),
        ),
        (
            "output chain herb must be empty",
            with_chain(herb="消风散"),
        ),
        (
            "output chain does not reference a plan-selected intersection",
            with_chain(related_entity_ids=[non_intersection_row_id, "d", "e"]),
        ),
        (
            "output chain evidence grading",
            with_chain(target_evidence_type="mock", evidence_level="predicted"),
        ),
        (
            "output chain evidence grading",
            with_chain(evidence_level="experimental"),
        ),
        (
            "exactly-once",
            duplicate,
        ),
        (
            "consumption.output_id does not reference a sealed output",
            with_consumption(0, output_id="assembly-output-" + "2" * 64),
        ),
        (
            "consumption.output_sha256 does not match the referenced output",
            with_consumption(0, output_sha256="0" * 64),
        ),
        (
            "output has no consumption record",
            orphan_output,
        ),
    ]

    for expected_issue, mutated in mutations:
        ok, issues = validate(mutated)
        assert not ok, f"expected validator to reject: {expected_issue}"
        assert any(expected_issue in issue for issue in issues), (expected_issue, issues)


def test_validator_ignores_output_fields_only_when_the_package_omits_them() -> None:
    """Plan-only packages (existing shape) must stay valid."""
    client = TestClient(app)
    evidence = _build_evidence(client)

    assert "outputs" not in evidence
    ok, issues = validate(evidence)
    assert ok, issues
