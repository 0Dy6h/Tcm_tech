"""ADR-0018 Gate 3 slice G3-1: omics manifest schema + raw artifact import gate.

The omics import freezes a transcriptomics raw artifact as an immutable,
content-addressed snapshot with server-computed SHA-256 — same discipline as
the Open Targets / ChEMBL raw artifacts. It performs no parsing and no
statistics, never touches ``formal_network_ready``, and rejects every
client-submitted sealed field.
"""

import gzip
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.omics import OmicsTranscriptomicsManifestV1
from app.services.network_omics import (
    OmicsSnapshotConflictError,
    build_verified_omics_import_snapshot,
    import_verified_omics_artifact,
)
from scripts.validate_omics_import import validate as validate_omics_store

OMICS_BYTES = gzip.compress(
    b'!Series_title\t"synthetic fixture"\n!Sample_geo_accession\t"GSMX1"\t"GSMX2"\n'
)
OMICS_SHA256 = hashlib.sha256(OMICS_BYTES).hexdigest()

MANIFEST: dict = {
    "manifest_version": "omics_transcriptomics_v1",
    "dataset": {
        "source": "geo",
        "accession": "GSE32924",
        "disease": "atopic_dermatitis",
        "organism": "Homo sapiens",
        "title": "Nonlesional atopic dermatitis skin (GSE32924 fixture)",
        "tissue": "skin biopsy (lesional, non-lesional, normal)",
        "platform": "GPL570 [HG-U133_Plus_2] Affymetrix Human Genome U133 Plus 2.0 Array",
        "sample_count": 3,
        "sample_groups": {"atopic_lesional": 1, "atopic_nonlesional": 1, "normal": 1},
        "sample_count_note": "synthetic fixture counts; real download governs the live dataset",
        "citation": "Suárez-Fariñas M et al. J Allergy Clin Immunol 2011;127(4):954-64",
        "license": "GEO/NCBI Open Access",
        "public_since": "2011-10-13",
    },
    "raw_artifact": {
        "filename": "GSE32924_series_matrix.txt.gz",
        "size_bytes": len(OMICS_BYTES),
        "format": "GEO series matrix (gzip text)",
    },
    "analysis_context": {
        "modality": "transcriptomics",
        "measurement_type": "gene_expression_microarray",
        "comparison": "atopic_lesional vs normal",
        "normalization": "geo_series_matrix_values",
        "deg_method": "welch_t_test",
        "fdr_correction": "benjamini_hochberg",
        "significance_threshold": 0.05,
        "log2fc_abs_threshold": 1.0,
    },
    "edge_mapping": {
        "network_layer": "disease_target_verification",
        "verified_edges": [],
        "corrected_edges": [],
        "edge_mapping_status": "pending_analysis",
        "mapping_rule": "DEG (adj_p < threshold, |log2FC| > threshold) matching canonical symbol",
    },
}


@pytest.fixture(autouse=True)
def _isolate_omics_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETWORK_RAW_ARTIFACT_DIR", str(tmp_path / "network_raw_artifacts"))


def _manifest_bytes_field(payload: dict, **overrides: object) -> dict:
    merged = deepcopy(payload)
    merged["raw_artifact"].update(overrides)
    return merged


def _omics_store() -> Path:
    return Path(os.environ["NETWORK_RAW_ARTIFACT_DIR"]) / "omics"


# ── snapshot builder (service layer) ────────────────────────


def test_build_snapshot_seals_server_only_fields() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)

    snapshot = build_verified_omics_import_snapshot(
        OMICS_BYTES, manifest=manifest, frozen_by="operator-a"
    )

    assert snapshot.snapshot_id.startswith("omics-snapshot-")
    assert snapshot.raw_artifact.sha256 == OMICS_SHA256
    assert snapshot.raw_artifact.frozen_by == "operator-a"
    assert snapshot.raw_artifact.frozen_at
    assert snapshot.provenance.import_type == "server_verified_raw_artifact"
    assert snapshot.provenance.client_submitted is False
    assert snapshot.provenance.formal_network_ready_impact is False
    assert snapshot.provenance.evidence_level_upgrade == "none (pending analysis)"
    assert snapshot.formal_network_ready is False


def test_snapshot_id_is_deterministic_and_excludes_wall_clock() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)

    first = build_verified_omics_import_snapshot(
        OMICS_BYTES, manifest=manifest, frozen_by="operator-a"
    )
    second = build_verified_omics_import_snapshot(
        OMICS_BYTES, manifest=manifest, frozen_by="operator-b"
    )

    assert first.snapshot_id == second.snapshot_id
    expected_input = {
        "client_manifest": manifest.model_dump(mode="json"),
        "raw_artifact_sha256": OMICS_SHA256,
        "platform_annotation_sha256": None,
    }
    canonical = json.dumps(
        expected_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert (
        first.snapshot_id
        == "omics-snapshot-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )


ANNOTATION_BYTES = gzip.compress(
    b"!platform_table_begin\nID\tGene symbol\n1007_s_at\tMIR4640///DDR1\n"
)


def _annotation_manifest() -> dict:
    merged = deepcopy(MANIFEST)
    merged["raw_artifact"] = {
        "filename": "GSE32924_series_matrix.txt.gz",
        "size_bytes": len(OMICS_BYTES),
        "format": "GEO series matrix (gzip text)",
    }
    merged["platform_annotation"] = {
        "filename": "GPL570.annot.gz",
        "size_bytes": len(ANNOTATION_BYTES),
        "format": "GEO GPL570 annot (gzip text)",
    }
    return merged


def test_annotation_artifact_is_sealed_and_persisted() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(_annotation_manifest())

    outcome = import_verified_omics_artifact(
        OMICS_BYTES, manifest=manifest, frozen_by="op", annotation_bytes=ANNOTATION_BYTES
    )

    assert outcome.snapshot.platform_annotation is not None
    annotation_sha = hashlib.sha256(ANNOTATION_BYTES).hexdigest()
    assert outcome.snapshot.platform_annotation.sha256 == annotation_sha
    assert (
        Path(os.environ["NETWORK_RAW_ARTIFACT_DIR"])
        / "omics"
        / "artifacts"
        / f"{annotation_sha}.bin"
    ).read_bytes() == ANNOTATION_BYTES
    assert outcome.snapshot.formal_network_ready is False


def test_annotation_size_mismatch_fails_closed() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(_annotation_manifest())

    with pytest.raises(ValueError, match="platform annotation"):
        import_verified_omics_artifact(
            OMICS_BYTES,
            manifest=manifest,
            frozen_by="op",
            annotation_bytes=ANNOTATION_BYTES + b"tail",
        )


def test_annotation_bytes_without_manifest_field_fail_closed() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)

    with pytest.raises(ValueError, match="without a matching manifest"):
        import_verified_omics_artifact(
            OMICS_BYTES, manifest=manifest, frozen_by="op", annotation_bytes=b"x"
        )


@pytest.mark.parametrize(
    "sealed_payload",
    [
        {"provenance": {"import_type": "server_verified_raw_artifact"}},
        {"snapshot_id": "omics-snapshot-" + "0" * 64},
        {"formal_network_ready": True},
        {"raw_artifact": {"sha256": OMICS_SHA256}},
    ],
)
def test_client_manifest_rejects_sealed_fields(sealed_payload: dict) -> None:
    payload = deepcopy(MANIFEST)
    payload.update(sealed_payload)

    with pytest.raises(ValidationError):
        OmicsTranscriptomicsManifestV1.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    ["sha256", "frozen_at", "frozen_by"],
)
def test_client_manifest_rejects_sealed_raw_artifact_fields(field: str) -> None:
    payload = _manifest_bytes_field(MANIFEST, **{field: "x" * 64})

    with pytest.raises(ValidationError):
        OmicsTranscriptomicsManifestV1.model_validate(payload)


def test_declared_size_mismatch_fails_closed() -> None:
    payload = _manifest_bytes_field(MANIFEST, size_bytes=len(OMICS_BYTES) + 1)
    manifest = OmicsTranscriptomicsManifestV1.model_validate(payload)

    with pytest.raises(ValueError, match="size"):
        build_verified_omics_import_snapshot(OMICS_BYTES, manifest=manifest, frozen_by="op")


def test_organism_guard_is_enforced_outside_pydantic() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)
    tampered_dataset = manifest.dataset.model_construct(
        **{**manifest.dataset.model_dump(), "organism": "Mus musculus"}
    )
    tampered = manifest.model_copy(update={"dataset": tampered_dataset})

    with pytest.raises(ValueError, match="Homo sapiens"):
        build_verified_omics_import_snapshot(OMICS_BYTES, manifest=tampered, frozen_by="op")


# ── import + frozen store ───────────────────────────────────


def test_import_persists_content_addressed_artifact_and_snapshot() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)

    outcome = import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")

    assert outcome.idempotent is False
    artifact_path = _omics_store() / "artifacts" / f"{OMICS_SHA256}.bin"
    snapshot_path = _omics_store() / "GSE32924.json"
    assert artifact_path.read_bytes() == OMICS_BYTES
    stored = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert stored["snapshot_id"] == outcome.snapshot.snapshot_id
    assert stored["raw_artifact"]["sha256"] == OMICS_SHA256
    assert stored["provenance"]["client_submitted"] is False


def test_reimport_of_identical_input_is_idempotent() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)

    first = import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")
    second = import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")

    assert first.idempotent is False
    assert second.idempotent is True
    assert second.snapshot.snapshot_id == first.snapshot.snapshot_id
    artifacts = list((_omics_store() / "artifacts").iterdir())
    assert len(artifacts) == 1


def test_reimport_with_different_content_same_accession_conflicts() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)
    import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")
    snapshot_before = (_omics_store() / "GSE32924.json").read_bytes()

    alt_bytes = gzip.compress(b"different experiment payload\n")
    alt_manifest = OmicsTranscriptomicsManifestV1.model_validate(
        _manifest_bytes_field(MANIFEST, size_bytes=len(alt_bytes))
    )

    with pytest.raises(OmicsSnapshotConflictError):
        import_verified_omics_artifact(alt_bytes, manifest=alt_manifest, frozen_by="op")
    assert (_omics_store() / "GSE32924.json").read_bytes() == snapshot_before


def test_reimport_with_same_content_but_different_manifest_conflicts() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)
    import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")

    mutated = deepcopy(MANIFEST)
    mutated["analysis_context"]["significance_threshold"] = 0.01
    alt_manifest = OmicsTranscriptomicsManifestV1.model_validate(mutated)

    with pytest.raises(OmicsSnapshotConflictError):
        import_verified_omics_artifact(OMICS_BYTES, manifest=alt_manifest, frozen_by="op")


# ── HTTP endpoint ───────────────────────────────────────────


def _post_omics_import(payload_bytes: bytes, manifest_payload: dict, **extra_fields: str):
    client = TestClient(app)
    return client.post(
        "/api/network/omics-import/verify",
        data={"manifest": json.dumps(manifest_payload, ensure_ascii=False), **extra_fields},
        files={
            "file": (
                "GSE32924_series_matrix.txt.gz",
                payload_bytes,
                "application/gzip",
            )
        },
    )


def test_verify_endpoint_imports_snapshot_and_never_flips_readiness() -> None:
    response = _post_omics_import(OMICS_BYTES, MANIFEST)

    assert response.status_code == 201
    body = response.json()
    assert body["idempotent"] is False
    assert body["snapshot_id"] == body["snapshot"]["snapshot_id"]
    assert body["snapshot"]["provenance"]["formal_network_ready_impact"] is False
    assert body["formal_network_ready"] is False


def test_verify_endpoint_reimport_is_idempotent_with_200() -> None:
    first = _post_omics_import(OMICS_BYTES, MANIFEST)
    second = _post_omics_import(OMICS_BYTES, MANIFEST)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert second.json()["snapshot_id"] == first.json()["snapshot_id"]


def test_verify_endpoint_conflicts_on_different_content_same_accession() -> None:
    _post_omics_import(OMICS_BYTES, MANIFEST)
    alt_bytes = gzip.compress(b"another payload\n")

    response = _post_omics_import(
        alt_bytes, _manifest_bytes_field(MANIFEST, size_bytes=len(alt_bytes))
    )

    assert response.status_code == 409


def test_verify_endpoint_rejects_unexpected_multipart_fields() -> None:
    response = _post_omics_import(OMICS_BYTES, MANIFEST, records="[]")

    assert response.status_code == 422


def test_verify_endpoint_rejects_client_submitted_provenance() -> None:
    payload = deepcopy(MANIFEST)
    payload["provenance"] = {"import_type": "server_verified_raw_artifact"}

    response = _post_omics_import(OMICS_BYTES, payload)

    assert response.status_code == 422


def test_verify_endpoint_rejects_oversized_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import network as network_api

    monkeypatch.setattr(network_api, "_MAX_OMICS_RAW_ARTIFACT_BYTES", 8)

    response = _post_omics_import(OMICS_BYTES, MANIFEST)

    assert response.status_code == 413


# ── independent validator ───────────────────────────────────


def test_validator_passes_a_clean_store() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)
    import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")

    ok, issues = validate_omics_store({"omics_dir": str(_omics_store()), "accession": "GSE32924"})

    assert ok, issues
    assert issues == []


def _import_once() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)
    import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")


@pytest.mark.parametrize(
    ("tamper", "expected_fragment"),
    [
        ("flip_impact", "formal_network_ready_impact"),
        ("flip_sha", "sha256"),
        ("truncate_artifact", "artifact"),
        ("flip_threshold", "snapshot_id"),
        ("flip_client_submitted", "client_submitted"),
    ],
)
def test_validator_rejects_every_tamper_path(tamper: str, expected_fragment: str) -> None:
    _import_once()
    snapshot_path = _omics_store() / "GSE32924.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if tamper == "flip_impact":
        snapshot["provenance"]["formal_network_ready_impact"] = True
    elif tamper == "flip_sha":
        snapshot["raw_artifact"]["sha256"] = "0" * 64
    elif tamper == "truncate_artifact":
        artifact = _omics_store() / "artifacts" / f"{OMICS_SHA256}.bin"
        artifact.write_bytes(OMICS_BYTES[:-1])
    elif tamper == "flip_threshold":
        snapshot["analysis_context"]["significance_threshold"] = 0.2
    elif tamper == "flip_client_submitted":
        snapshot["provenance"]["client_submitted"] = True
    if tamper != "truncate_artifact":
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    ok, issues = validate_omics_store({"omics_dir": str(_omics_store()), "accession": "GSE32924"})

    assert ok is False
    assert any(expected_fragment in issue for issue in issues), issues


# ── slice G3-2: series matrix parsing + deterministic DEG candidates ──

from app.schemas.network import NetworkAnalysisResult  # noqa: E402
from app.services.network_omics import (  # noqa: E402
    OmicsVerificationBlockedError,
    compute_omics_deg_projection,
    load_frozen_omics_bytes,
)

DEG_MATRIX_PLAIN = b"\n".join(
    [
        b'!Sample_geo_accession\t"GSM1"\t"GSM2"\t"GSM3"\t"GSM4"\t"GSM5"',
        b'!Sample_characteristics_ch1\t"condition: AL"\t"condition: AL"\t"condition: ANL"\t"condition: Normal"\t"condition: Normal"',
        b"!series_matrix_table_begin",
        b'"ID_REF"\t"GSM1"\t"GSM2"\t"GSM3"\t"GSM4"\t"GSM5"',
        b'"1007_s_at"\t10\t10.2\t9\t4\t3.8',
        b'"1053_at"\t5\t5\t5\t4\t4.2',
        b'"117_at"\t3\t3\t3\t3\t3',
        b"!series_matrix_table_end",
        b"",
    ]
)
DEG_MATRIX_BYTES = gzip.compress(DEG_MATRIX_PLAIN)
DEG_ANNOTATION_BYTES = gzip.compress(
    b"\n".join(
        [
            b"!platform_table_begin",
            b"ID\tGene symbol",
            b"1007_s_at\tIL6",
            b"1053_at\tSTAT3",
            b"117_at\tTNF",
            b"!platform_table_end",
            b"",
        ]
    )
)


def _deg_manifest() -> dict:
    merged = _annotation_manifest()
    merged["raw_artifact"] = {
        "filename": "GSE32924_series_matrix.txt.gz",
        "size_bytes": len(DEG_MATRIX_BYTES),
        "format": "GEO series matrix (gzip text)",
    }
    merged["platform_annotation"] = {
        "filename": "GPL570.annot.gz",
        "size_bytes": len(DEG_ANNOTATION_BYTES),
        "format": "GEO GPL570 annot (gzip text)",
    }
    merged["dataset"]["sample_count"] = 5
    merged["dataset"]["sample_groups"] = {
        "atopic_lesional": 2,
        "atopic_nonlesional": 1,
        "normal": 2,
    }
    return merged


def _seal_deg_snapshot() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(_deg_manifest())
    import_verified_omics_artifact(
        DEG_MATRIX_BYTES,
        manifest=manifest,
        frozen_by="op",
        annotation_bytes=DEG_ANNOTATION_BYTES,
    )


def _deg_result(source_task_id: str | None = None) -> NetworkAnalysisResult:
    return NetworkAnalysisResult.model_validate(
        {
            "task_id": "network-" + "a" * 12,
            "source_task_id": source_task_id,
            "query": "消风散",
            "analysis_type": "formula",
            "chains": [],
            "disclaimer": "非诊断结论、需结合临床。",
            "target_lineage": {
                "disease_targets": [
                    {
                        "lineage_row_id": "disease-" + "1" * 64,
                        "raw_identifier": "ENSG00000136244",
                        "canonical_symbol": "IL6",
                        "source_database": "Open Targets Platform",
                        "query_date": "2026-07-11",
                        "identifier_mapping": "Ensembl target approvedSymbol",
                        "evidence_origin": "disease_association",
                    },
                    {
                        "lineage_row_id": "disease-" + "2" * 64,
                        "raw_identifier": "ENSG00000136244",
                        "canonical_symbol": "TNF",
                        "source_database": "Open Targets Platform",
                        "query_date": "2026-07-11",
                        "identifier_mapping": "Ensembl target approvedSymbol",
                        "evidence_origin": "disease_association",
                    },
                ]
            },
        }
    )


def test_deg_projection_computes_candidates_and_matches_lineage() -> None:
    _seal_deg_snapshot()
    result = _deg_result()

    projection = compute_omics_deg_projection(result, accession="GSE32924")

    assert projection.formal_network_ready is False
    assert projection.case_group == "atopic_lesional"
    assert projection.control_group == "normal"
    assert projection.analyzed_gene_count == 3
    # IL6: mean 10.1 vs 3.9 → log2fc 6.2, p tiny → passes; STAT3: |log2fc| ≈ 0.9
    # not > 1 → out; TNF: constant values → non-finite Welch p → out (honest).
    assert [candidate.canonical_symbol for candidate in projection.candidates] == ["IL6"]
    il6 = projection.candidates[0]
    assert il6.log2fc == pytest.approx(6.2)
    assert il6.adj_p_value < 0.05
    assert il6.lineage_row_ids == ["disease-" + "1" * 64]
    assert il6.status == "pending_human_confirmation"
    assert projection.passing_gene_count == 1


def test_deg_projection_recompute_is_byte_identical() -> None:
    _seal_deg_snapshot()
    result = _deg_result()

    first = compute_omics_deg_projection(result, accession="GSE32924")
    second = compute_omics_deg_projection(result, accession="GSE32924")

    assert first.model_dump_json() == second.model_dump_json()


def test_deg_projection_is_deterministic_json_bytes() -> None:
    _seal_deg_snapshot()
    result = _deg_result()

    first = compute_omics_deg_projection(result, accession="GSE32924")
    second = compute_omics_deg_projection(result, accession="GSE32924")

    assert json.dumps(first.model_dump(), sort_keys=True) == json.dumps(
        second.model_dump(), sort_keys=True
    )


def test_deg_projection_group_count_mismatch_fails_closed() -> None:
    payload = _deg_manifest()
    payload["dataset"]["sample_groups"] = {
        "atopic_lesional": 1,
        "atopic_nonlesional": 1,
        "normal": 1,
    }
    manifest = OmicsTranscriptomicsManifestV1.model_validate(payload)
    import_verified_omics_artifact(
        DEG_MATRIX_BYTES,
        manifest=manifest,
        frozen_by="op",
        annotation_bytes=DEG_ANNOTATION_BYTES,
    )
    result = _deg_result()

    with pytest.raises(OmicsVerificationBlockedError, match="sample_groups"):
        compute_omics_deg_projection(result, accession="GSE32924")


def test_deg_projection_unknown_condition_label_fails_closed() -> None:
    mutated_matrix = gzip.compress(DEG_MATRIX_PLAIN.replace(b"condition: ANL", b"condition: FLARE"))
    manifest_payload = _deg_manifest()
    manifest_payload["raw_artifact"]["size_bytes"] = len(mutated_matrix)
    manifest = OmicsTranscriptomicsManifestV1.model_validate(manifest_payload)
    import_verified_omics_artifact(
        mutated_matrix,
        manifest=manifest,
        frozen_by="op",
        annotation_bytes=DEG_ANNOTATION_BYTES,
    )
    # re-address the mismatched snapshot under another accession so the unknown
    # condition label (not a group-count mismatch) is what the parser trips on
    from app.services.network_omics import omics_artifact_dir

    snapshot_path = omics_artifact_dir() / "GSE32924.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["dataset"]["accession"] = "GSE99999"
    (omics_artifact_dir() / "GSE99999.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    result = _deg_result()

    with pytest.raises(OmicsVerificationBlockedError, match="condition"):
        compute_omics_deg_projection(result, accession="GSE99999")


def test_deg_projection_without_annotation_fails_closed() -> None:
    manifest = OmicsTranscriptomicsManifestV1.model_validate(MANIFEST)
    import_verified_omics_artifact(OMICS_BYTES, manifest=manifest, frozen_by="op")
    result = _deg_result()

    with pytest.raises(OmicsVerificationBlockedError, match="platform annotation"):
        compute_omics_deg_projection(result, accession="GSE32924")


def test_deg_projection_refuses_compound_child_result() -> None:
    _seal_deg_snapshot()
    result = _deg_result(source_task_id="network-" + "b" * 16)

    with pytest.raises(OmicsVerificationBlockedError, match="compound"):
        compute_omics_deg_projection(result, accession="GSE32924")


def test_load_frozen_omics_bytes_rejects_hash_mismatch() -> None:
    _seal_deg_snapshot()
    from app.services.network_omics import load_frozen_omics_snapshot  # noqa: E402

    snapshot = load_frozen_omics_snapshot("GSE32924")
    sha = snapshot.raw_artifact.sha256
    artifact = _omics_store() / "artifacts" / f"{sha}.bin"
    artifact.write_bytes(DEG_MATRIX_BYTES + b"tampered")

    with pytest.raises(ValueError, match="SHA-256"):
        load_frozen_omics_bytes(expected_sha256=sha)


DISEASE_VERIFY_METADATA = {
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
OPEN_TARGETS_FIXTURE = (
    Path(__file__).parent / "data" / "open_targets_graphql_associations_25_06.json"
)


def test_result_envelope_carries_omics_projection_on_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _omics_store().parent / "trusted-open-targets-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "artifacts": {
                    hashlib.sha256(OPEN_TARGETS_FIXTURE.read_bytes()).hexdigest(): (
                        DISEASE_VERIFY_METADATA
                    )
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NETWORK_OPEN_TARGETS_MANIFEST_PATH", str(manifest_path))
    _seal_deg_snapshot()
    client = TestClient(app)
    verify = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(DISEASE_VERIFY_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                "open_targets.json",
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/x-ndjson",
            )
        },
    )
    assert verify.status_code == 202, verify.text
    task_id = verify.json()["task_id"]
    payload = {}
    for _ in range(50):
        payload = client.get(f"/api/network/result/{task_id}").json()
        if payload["status"] == "completed":
            break
    assert payload["status"] == "completed"

    opt_in = client.get(
        f"/api/network/result/{task_id}",
        params={"omics_verification": "true", "omics_accession": "GSE32924"},
    )

    assert opt_in.status_code == 200, opt_in.text
    projection = opt_in.json()["omics_verification"]
    assert projection is not None
    assert projection["policy_id"] == "omics_transcriptomics_deg_v1"
    assert projection["formal_network_ready"] is False
    matched = [c["canonical_symbol"] for c in projection["candidates"]]
    assert "IL6" in matched

    default = client.get(f"/api/network/result/{task_id}").json()
    assert default["omics_verification"] is None


# ── slice G3-3: omics_validated evidence level + HITL binding ──

from itertools import product  # noqa: E402

from app.schemas.network import (  # noqa: E402
    NetworkAdjudicationRequest,
    NetworkChain,
    NetworkTargetAdjudication,
)
from app.services.network_lineage import (  # noqa: E402
    build_network_report_markdown,
    derive_chain_evidence_level,
)
from app.services.network_queries import (  # noqa: E402
    _with_omics_evidence_overlay,
)


def test_derive_chain_evidence_level_never_yields_omics_validated() -> None:
    """No pipeline/derivation path may mint omics_validated — only HITL can."""
    chain = NetworkChain.model_validate(
        {
            "herb": "黄芩",
            "compound": "baicalin",
            "target": "IL6",
            "pathway": "p",
            "disease": "d",
            "score": 0.9,
            "related_entity_ids": ["e1"],
        }
    )
    for data_mode, evidence_type, refs in product(
        ["mock", "live"],
        ["mock", "known_activity", "predicted", "mixed"],
        [[], ["ref-1"]],
    ):
        graded = derive_chain_evidence_level(
            chain.model_copy(update={"target_evidence_type": evidence_type, "evidence_refs": refs}),
            data_mode=data_mode,
        )
        assert graded != "omics_validated"


def test_report_grading_table_lists_omics_level_with_zero_by_default() -> None:
    markdown = build_network_report_markdown(_deg_result())

    assert "| 组学验证 | `omics_validated` | 0 |" in markdown


def _omics_confirmed_event(
    lineage_row_id: str,
    symbol: str = "IL6",
    accession: str = "GSE32924",
) -> NetworkTargetAdjudication:
    return NetworkTargetAdjudication.model_validate(
        {
            "adjudication_id": "omics-adjudication-" + "1" * 12,
            "lineage_row_id": lineage_row_id,
            "decision": "omics_confirmed",
            "decided_at": "2026-09-03T12:00:00+00:00",
            "reviewer_id": "reviewer-a",
            "omics_accession": accession,
            "omics_canonical_symbol": symbol,
        }
    )


def _chain(level: str, target: str = "IL6") -> NetworkChain:
    return NetworkChain.model_validate(
        {
            "herb": "黄芩",
            "compound": "baicalin",
            "target": target,
            "pathway": "p",
            "disease": "d",
            "score": 0.9,
            "related_entity_ids": [],
            "evidence_level": level,
        }
    )


def test_overlay_upgrades_live_chain_only_from_lower_live_tiers() -> None:
    result = _deg_result().model_copy(
        update={
            "data_mode": "live",
            "chains": [
                _chain("literature_supported"),
                _chain("predicted"),
                _chain("experimental"),
                _chain("mock_inferred"),
                _chain("literature_supported", target="TNF"),
            ],
        }
    )
    events = [_omics_confirmed_event("disease-" + "1" * 64)]

    overlaid = _with_omics_evidence_overlay(result, events)

    levels = [chain.evidence_level for chain in overlaid.chains]
    assert levels == [
        "omics_validated",
        "omics_validated",
        "experimental",
        "mock_inferred",
        "literature_supported",
    ]
    # stored frozen result untouched
    assert result.chains[0].evidence_level == "literature_supported"


def test_overlay_ignores_mock_mode_and_missing_events() -> None:
    mock_result = _deg_result().model_copy(
        update={"data_mode": "mock", "chains": [_chain("mock_inferred")]}
    )
    events = [_omics_confirmed_event("disease-" + "1" * 64)]

    assert _with_omics_evidence_overlay(mock_result, events).chains[0].evidence_level == (
        "mock_inferred"
    )
    live = _deg_result().model_copy(
        update={"data_mode": "live", "chains": [_chain("literature_supported")]}
    )
    assert _with_omics_evidence_overlay(live, []).chains[0].evidence_level == (
        "literature_supported"
    )


def test_omics_adjudication_request_context_is_symmetrically_required() -> None:
    row = "disease-" + "1" * 64
    with pytest.raises(ValidationError):
        NetworkAdjudicationRequest.model_validate(
            {"lineage_row_id": row, "decision": "omics_confirmed"}
        )
    with pytest.raises(ValidationError):
        NetworkAdjudicationRequest.model_validate(
            {
                "lineage_row_id": row,
                "decision": "included",
                "omics": {"accession": "GSE32924", "canonical_symbol": "IL6"},
            }
        )
    ok = NetworkAdjudicationRequest.model_validate(
        {
            "lineage_row_id": row,
            "decision": "omics_confirmed",
            "omics": {"accession": "GSE32924", "canonical_symbol": "IL6"},
        }
    )
    assert ok.omics is not None and ok.omics.canonical_symbol == "IL6"


def _setup_completed_verified_disease_task(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, str, str]:
    manifest_path = _omics_store().parent / "trusted-open-targets-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "artifacts": {
                    hashlib.sha256(OPEN_TARGETS_FIXTURE.read_bytes()).hexdigest(): (
                        DISEASE_VERIFY_METADATA
                    )
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NETWORK_OPEN_TARGETS_MANIFEST_PATH", str(manifest_path))
    _seal_deg_snapshot()
    client = TestClient(app)
    verify = client.post(
        "/api/network/disease-import/verify",
        data={
            "query": "消风散",
            "analysis_type": "formula",
            "evidence_policy": "direct_human_first",
            "metadata": json.dumps(DISEASE_VERIFY_METADATA, ensure_ascii=False),
        },
        files={
            "file": (
                "open_targets.json",
                OPEN_TARGETS_FIXTURE.read_bytes(),
                "application/x-ndjson",
            )
        },
    )
    assert verify.status_code == 202, verify.text
    task_id = verify.json()["task_id"]
    payload = {}
    for _ in range(50):
        payload = client.get(f"/api/network/result/{task_id}").json()
        if payload["status"] == "completed":
            break
    assert payload["status"] == "completed"
    rows = payload["result"]["target_lineage"]["disease_targets"]
    il6_row = next(row["lineage_row_id"] for row in rows if row["canonical_symbol"] == "IL6")
    other_row = next(row["lineage_row_id"] for row in rows if row["canonical_symbol"] != "IL6")
    return client, il6_row, other_row


def _adjudicate(
    client: TestClient,
    task_id: str,
    row: str,
    symbol: str,
    accession: str = "GSE32924",
):
    return client.post(
        f"/api/network/result/{task_id}/adjudications",
        json={
            "lineage_row_id": row,
            "decision": "omics_confirmed",
            "omics": {"accession": accession, "canonical_symbol": symbol},
        },
    )


def test_omics_adjudication_happy_path_seals_server_verified_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, il6_row, _ = _setup_completed_verified_disease_task(monkeypatch)
    task_id = client.get("/api/network/tasks").json()["tasks"][-1]["task_id"]

    response = _adjudicate(client, task_id, il6_row, "IL6")

    assert response.status_code == 201, response.text
    record = response.json()
    assert record["decision"] == "omics_confirmed"
    assert record["omics_accession"] == "GSE32924"
    assert record["omics_canonical_symbol"] == "IL6"
    assert record["omics_log2fc"] == pytest.approx(6.2)
    assert record["omics_adj_p_value"] < 0.05
    assert "reviewer_id" not in record

    summary = client.get(f"/api/network/result/{task_id}").json()["adjudication"]
    assert summary["counts"]["omics_confirmed"] == 1


def test_omics_adjudication_refuses_symbol_without_passing_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, other_row = _setup_completed_verified_disease_task(monkeypatch)
    task_id = client.get("/api/network/tasks").json()["tasks"][-1]["task_id"]
    payload = client.get(f"/api/network/result/{task_id}").json()
    other_symbol = next(
        row["canonical_symbol"]
        for row in payload["result"]["target_lineage"]["disease_targets"]
        if row["lineage_row_id"] == other_row
    )
    assert other_symbol not in ("IL6",)

    response = _adjudicate(client, task_id, other_row, other_symbol)

    assert response.status_code == 422
    assert "refused" in response.json()["detail"]


def test_omics_adjudication_refuses_row_symbol_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, il6_row, _ = _setup_completed_verified_disease_task(monkeypatch)
    task_id = client.get("/api/network/tasks").json()["tasks"][-1]["task_id"]

    response = _adjudicate(client, task_id, il6_row, "TNF")

    assert response.status_code == 422
    assert "does not belong" in response.json()["detail"]


def test_omics_adjudication_missing_snapshot_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, il6_row, _ = _setup_completed_verified_disease_task(monkeypatch)
    task_id = client.get("/api/network/tasks").json()["tasks"][-1]["task_id"]

    response = _adjudicate(client, task_id, il6_row, "IL6", accession="GSE00000")

    assert response.status_code == 404
