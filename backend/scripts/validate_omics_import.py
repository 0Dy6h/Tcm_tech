"""Independently validate a sealed omics import snapshot (ADR-0018 Gate 3, G3-1).

This script recomputes every sealed binding of an omics snapshot from the
frozen store and reports pass/fail. It deliberately shares no code with
``app.services.network_omics``: the producer's hashing and sealing logic is
re-derived here from first principles so a coordinated producer bug or a
tampered artifact cannot pass both paths.

Store layout (operator-controlled, gitignored):
    <omics_dir>/<accession>.json          immutable snapshot document
    <omics_dir>/artifacts/<sha256>.bin    content-addressed raw artifact bytes

Usage:
    python scripts/validate_omics_import.py --omics-dir <dir> --accession GSE32924
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_SNAPSHOT_ID_PATTERN = re.compile(r"^omics-snapshot-[0-9a-f]{64}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SEALED_PROVENANCE = {
    "import_type": "server_verified_raw_artifact",
    "client_submitted": False,
    "formal_network_ready_impact": False,
    "evidence_level_upgrade": "none (pending analysis)",
}
_CLIENT_SECTIONS = ("dataset", "analysis_context", "edge_mapping")


def _canonical_snapshot_id(
    client_manifest: dict[str, Any], artifact_sha256: str, annotation_sha256: str | None
) -> str:
    canonical = json.dumps(
        {
            "client_manifest": client_manifest,
            "raw_artifact_sha256": artifact_sha256,
            "platform_annotation_sha256": annotation_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "omics-snapshot-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate(store: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate one sealed omics snapshot; returns (ok, issues)."""
    issues: list[str] = []
    omics_dir_raw = store.get("omics_dir")
    accession = store.get("accession")
    if not isinstance(omics_dir_raw, str) or not omics_dir_raw:
        return False, ["store.omics_dir must be a non-empty path"]
    if not isinstance(accession, str) or not re.fullmatch(r"GSE[0-9]+", accession or ""):
        return False, ["store.accession must be a GEO accession like GSE32924"]
    omics_dir = Path(omics_dir_raw)
    snapshot_path = omics_dir / f"{accession}.json"
    if not snapshot_path.is_file():
        return False, [f"snapshot document missing: {snapshot_path}"]
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, [f"snapshot document is not readable JSON: {exc}"]
    if not isinstance(snapshot, dict):
        return False, ["snapshot document must be a JSON object"]

    if snapshot.get("manifest_version") != "omics_transcriptomics_v1":
        issues.append("snapshot.manifest_version must be omics_transcriptomics_v1")

    dataset = snapshot.get("dataset")
    if not isinstance(dataset, dict):
        issues.append("snapshot.dataset must be an object")
    else:
        if dataset.get("organism") != "Homo sapiens":
            issues.append("snapshot.dataset.organism must be Homo sapiens")
        if dataset.get("disease") != "atopic_dermatitis":
            issues.append("snapshot.dataset.disease must be atopic_dermatitis")
        if dataset.get("accession") != accession:
            issues.append("snapshot.dataset.accession must match the validated accession")

    raw_artifact = snapshot.get("raw_artifact")
    if not isinstance(raw_artifact, dict):
        issues.append("snapshot.raw_artifact must be an object")
        raw_artifact = {}
    artifact_sha256 = raw_artifact.get("sha256")
    if not isinstance(artifact_sha256, str) or not _SHA256_PATTERN.fullmatch(artifact_sha256):
        issues.append("snapshot.raw_artifact.sha256 must be a sha256 hex digest")
        artifact_sha256 = ""
    else:
        artifact_path = omics_dir / "artifacts" / f"{artifact_sha256}.bin"
        if not artifact_path.is_file():
            issues.append(f"raw artifact bytes missing for sha256 {artifact_sha256}")
        else:
            actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if actual != artifact_sha256:
                issues.append(
                    "raw artifact bytes fail SHA-256 re-computation: sealed sha256 "
                    f"{artifact_sha256} != actual {actual}"
                )

    if not isinstance(raw_artifact.get("frozen_at"), str) or not raw_artifact.get("frozen_at"):
        issues.append("snapshot.raw_artifact.frozen_at must be a sealed timestamp string")
    if not isinstance(raw_artifact.get("frozen_by"), str) or not raw_artifact.get("frozen_by"):
        issues.append("snapshot.raw_artifact.frozen_by must be a sealed operator string")

    platform_annotation = snapshot.get("platform_annotation")
    annotation_sha256: str | None = None
    if platform_annotation is not None:
        if not isinstance(platform_annotation, dict):
            issues.append("snapshot.platform_annotation must be an object when present")
            platform_annotation = {}
        annotation_sha256 = platform_annotation.get("sha256")
        if not isinstance(annotation_sha256, str) or not _SHA256_PATTERN.fullmatch(
            annotation_sha256
        ):
            issues.append("snapshot.platform_annotation.sha256 must be a sha256 hex digest")
            annotation_sha256 = None
        else:
            annotation_path = omics_dir / "artifacts" / f"{annotation_sha256}.bin"
            if not annotation_path.is_file():
                issues.append(f"platform annotation bytes missing for sha256 {annotation_sha256}")
            else:
                actual = hashlib.sha256(annotation_path.read_bytes()).hexdigest()
                if actual != annotation_sha256:
                    issues.append(
                        "platform annotation bytes fail SHA-256 re-computation: sealed "
                        f"{annotation_sha256} != actual {actual}"
                    )
        if not isinstance(platform_annotation.get("frozen_at"), str) or not platform_annotation.get(
            "frozen_at"
        ):
            issues.append("snapshot.platform_annotation.frozen_at must be a sealed timestamp")
        if not isinstance(platform_annotation.get("frozen_by"), str) or not platform_annotation.get(
            "frozen_by"
        ):
            issues.append("snapshot.platform_annotation.frozen_by must be a sealed operator")

    provenance = snapshot.get("provenance")
    if provenance != _SEALED_PROVENANCE:
        issues.append(
            "snapshot.provenance must equal the sealed server-only provenance "
            f"({_SEALED_PROVENANCE!r})"
        )
    if isinstance(provenance, dict) and provenance.get("client_submitted") is not False:
        issues.append("snapshot.provenance.client_submitted must be false")

    if snapshot.get("formal_network_ready") is not False:
        issues.append("snapshot.formal_network_ready must be false")

    client_manifest: dict[str, Any] = {
        "manifest_version": snapshot.get("manifest_version"),
        "dataset": dataset,
        "raw_artifact": {
            key: raw_artifact.get(key) for key in ("filename", "size_bytes", "format")
        },
        "platform_annotation": None
        if platform_annotation is None
        else {key: platform_annotation.get(key) for key in ("filename", "size_bytes", "format")},
        "analysis_context": snapshot.get("analysis_context"),
        "edge_mapping": snapshot.get("edge_mapping"),
    }
    if any(client_manifest.get(section) is None for section in _CLIENT_SECTIONS):
        issues.append("snapshot is missing one or more client manifest sections")
    recomputed_id = _canonical_snapshot_id(client_manifest, artifact_sha256, annotation_sha256)
    if snapshot.get("snapshot_id") != recomputed_id:
        issues.append(
            "snapshot.snapshot_id does not match re-computed content binding "
            f"(expected {recomputed_id})"
        )
    if not isinstance(snapshot.get("snapshot_id"), str) or not _SNAPSHOT_ID_PATTERN.fullmatch(
        snapshot.get("snapshot_id") or ""
    ):
        issues.append("snapshot.snapshot_id must match omics-snapshot-<sha256>")

    return not issues, issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omics-dir", required=True, help="path to the omics frozen store")
    parser.add_argument("--accession", required=True, help="GEO accession, e.g. GSE32924")
    args = parser.parse_args(argv)
    ok, issues = validate({"omics_dir": args.omics_dir, "accession": args.accession})
    if ok:
        print(f"OK: omics snapshot {args.accession} passed independent validation")
        return 0
    print(f"FAIL: omics snapshot {args.accession} failed independent validation:")
    for issue in issues:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
