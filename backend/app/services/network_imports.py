"""Server-verified import snapshot construction and raw artifact persistence."""

import hashlib
import os
import tempfile
from pathlib import Path

from app.schemas.network import (
    NetworkCompoundTargetVerifiedSnapshot,
    NetworkCompoundTargetVerifyMetadata,
    NetworkDiseaseTargetImport,
    NetworkDiseaseTargetImportSnapshot,
    NetworkDiseaseTargetVerifiedSnapshot,
    NetworkDiseaseTargetVerifyMetadata,
)
from app.services.network_chembl import ChEMBLRawArtifactConnector
from app.services.network_common import _canonical_sha256
from app.services.network_open_targets import OpenTargetsRawArtifactConnector


def _build_import_snapshot(
    imported: NetworkDiseaseTargetImport,
) -> NetworkDiseaseTargetImportSnapshot:
    payload = imported.model_dump(mode="json")
    return NetworkDiseaseTargetImportSnapshot.model_validate(
        {
            **payload,
            "provenance_verification_status": "unverified_client_import",
            "import_payload_sha256": _canonical_sha256(payload),
        }
    )


def build_verified_disease_import_snapshot(
    raw_bytes: bytes,
    *,
    metadata: NetworkDiseaseTargetVerifyMetadata,
    source_artifact_filename: str,
    source_artifact_media_type: str,
) -> NetworkDiseaseTargetVerifiedSnapshot:
    records = OpenTargetsRawArtifactConnector.parse_open_targets_associations(
        raw_bytes, expected=metadata
    )
    imported_payload = {
        **metadata.model_dump(mode="json"),
        "records": [record.model_dump(mode="json") for record in records],
    }
    return NetworkDiseaseTargetVerifiedSnapshot.model_validate(
        {
            **imported_payload,
            "provenance_verification_status": "server_verified_raw_artifact",
            "import_payload_sha256": _canonical_sha256(imported_payload),
            "source_artifact_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_artifact_filename": Path(source_artifact_filename).name,
            "source_artifact_media_type": source_artifact_media_type,
        }
    )


def build_verified_compound_import_snapshot(
    raw_bytes: bytes,
    *,
    metadata: NetworkCompoundTargetVerifyMetadata,
    source_artifact_filename: str,
    source_artifact_media_type: str,
) -> NetworkCompoundTargetVerifiedSnapshot:
    records = sorted(
        ChEMBLRawArtifactConnector.parse_known_activities(raw_bytes, expected=metadata),
        key=lambda record: (
            record.canonical_symbol,
            record.source_record_id,
            record.raw_identifier,
        ),
    )
    imported_payload = {
        **metadata.model_dump(mode="json"),
        "records": [record.model_dump(mode="json") for record in records],
    }
    return NetworkCompoundTargetVerifiedSnapshot.model_validate(
        {
            **imported_payload,
            "provenance_verification_status": "server_verified_raw_artifact",
            "import_payload_sha256": _canonical_sha256(imported_payload),
            "source_artifact_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_artifact_filename": Path(source_artifact_filename).name,
            "source_artifact_media_type": source_artifact_media_type,
        }
    )


def _persist_verified_raw_artifact(raw_bytes: bytes, artifact_sha256: str) -> Path:
    configured_dir = os.environ.get("NETWORK_RAW_ARTIFACT_DIR")
    artifact_dir = (
        Path(configured_dir)
        if configured_dir
        else Path(__file__).resolve().parents[2] / "data" / "runtime" / "network_raw_artifacts"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{artifact_sha256}.json"
    if (
        artifact_path.exists()
        and hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact_sha256
    ):
        return artifact_path
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=artifact_dir,
            prefix=f".{artifact_sha256}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(raw_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if hashlib.sha256(temporary_path.read_bytes()).hexdigest() != artifact_sha256:
            raise ValueError("temporary raw artifact hash does not match expected bytes")
        os.replace(temporary_path, artifact_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return artifact_path
