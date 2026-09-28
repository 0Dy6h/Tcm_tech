"""Independently validate target-lineage counts in a network result artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

_ROW_ID_PATTERN = re.compile(r"^(disease|compound|intersection)-[0-9a-f]{64}$")
_NETWORK_TASK_ID_PATTERN = re.compile(r"^network-[0-9a-f]{12,32}$")
_SNAPSHOT_ONLY_NETWORK_BLOCKER = "导入靶点尚未构建可复算的成分-靶点-通路网络闭环。"


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _same_timestamp(left: Any, right: Any) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    try:
        left_value = datetime.fromisoformat(left.replace("Z", "+00:00")).astimezone(UTC)
        right_value = datetime.fromisoformat(right.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return False
    return left_value == right_value


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _validate_research_protocol(protocol: dict[str, Any], issues: list[str]) -> None:
    if protocol.get("disease") != "atopic_dermatitis":
        issues.append("research_protocol.disease must be atopic_dermatitis")
    phenotype = protocol.get("phenotype")
    if not isinstance(phenotype, str) or not 4 <= len(phenotype.strip()) <= 200:
        issues.append("research_protocol.phenotype must contain 4 to 200 non-whitespace characters")
    if protocol.get("species") != "Homo sapiens":
        issues.append("research_protocol.species must be Homo sapiens")
    if protocol.get("evidence_policy") not in {
        "direct_human_first",
        "mixed_exploratory",
    }:
        issues.append("research_protocol.evidence_policy is invalid")
    query_date = protocol.get("query_date")
    if not isinstance(query_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", query_date):
        issues.append("research_protocol.query_date must be an ISO date")
        return
    try:
        parsed_query_date = date.fromisoformat(query_date)
    except ValueError:
        issues.append("research_protocol.query_date must be an ISO date")
        return
    if parsed_query_date > date.today():
        issues.append("research_protocol.query_date cannot be in the future")


def _rows(lineage: dict[str, Any], name: str) -> list[dict[str, Any]]:
    value = lineage.get(name)
    if not isinstance(value, list):
        raise ValueError(f"target_lineage.{name} must be a JSON array")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        rows.append(_object(row, f"target_lineage.{name}[{index}]"))
    return rows


def _bounded_numeric_value(
    value: Any,
    *,
    field: str,
    upper_bound: int,
    issues: list[str],
) -> float | None:
    message = f"{field} must be a finite numeric value in [0, {upper_bound}]"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append(message)
        return None
    try:
        numeric_value = float(value)
    except (OverflowError, ValueError):
        issues.append(message)
        return None
    if not math.isfinite(numeric_value) or not 0 <= numeric_value <= upper_bound:
        issues.append(message)
        return None
    return numeric_value


def _non_negative_integer(
    value: Any,
    *,
    field: str,
    issues: list[str],
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        issues.append(f"{field} must be a non-negative integer")
        return None
    return value


def _symbols(rows: list[dict[str, Any]], name: str) -> set[str]:
    symbols: set[str] = set()
    for index, row in enumerate(rows):
        symbol = row.get("canonical_symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"target_lineage.{name}[{index}].canonical_symbol must be non-empty")
        symbols.add(symbol.strip())
    return symbols


def _lineage_row_id(set_kind: str, row: dict[str, Any]) -> str:
    source_record_ids = row.get("source_record_ids")
    if not isinstance(source_record_ids, list) or not all(
        isinstance(record_id, str) for record_id in source_record_ids
    ):
        raise ValueError(f"{set_kind} row source_record_ids must be a string array")
    identity = {
        "set_kind": set_kind,
        "source_database": row.get("source_database"),
        "database_version": row.get("database_version"),
        "source_query": row.get("source_query"),
        "query_date": row.get("query_date"),
        "retrieved_at": row.get("retrieved_at"),
        "species": row.get("species"),
        "source_record_ids": sorted(source_record_ids),
        "raw_identifier": row.get("raw_identifier"),
        "canonical_symbol": row.get("canonical_symbol"),
        "source_score": row.get("source_score"),
        "score_name": row.get("score_name"),
        "applied_threshold": row.get("applied_threshold"),
        "threshold_operator": row.get("threshold_operator"),
        "identifier_mapping": row.get("identifier_mapping"),
        "identifier_mapping_version": row.get("identifier_mapping_version"),
    }
    return f"{set_kind}-{_canonical_sha256(identity)}"


def _validate_lineage_row_ids(
    set_kind: str,
    rows: list[dict[str, Any]],
    issues: list[str],
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        row_id = row.get("lineage_row_id")
        if not isinstance(row_id, str) or not _ROW_ID_PATTERN.fullmatch(row_id):
            issues.append(f"{set_kind}_targets[{index}].lineage_row_id is missing or invalid")
            continue
        try:
            expected_id = _lineage_row_id(set_kind, row)
        except ValueError as exc:
            issues.append(f"{set_kind}_targets[{index}]: {exc}")
            continue
        if row_id != expected_id:
            issues.append(
                f"{set_kind}_targets[{index}].lineage_row_id does not match row provenance"
            )
        if row_id in by_id:
            issues.append(f"{set_kind}_targets lineage_row_id values must be unique")
        by_id[row_id] = row
    return by_id


def _intersection_row_id(row: dict[str, Any]) -> str:
    disease_refs = row.get("disease_lineage_row_ids")
    compound_refs = row.get("compound_lineage_row_ids")
    if not isinstance(disease_refs, list) or not all(
        isinstance(item, str) for item in disease_refs
    ):
        raise ValueError("disease_lineage_row_ids must be a string array")
    if not isinstance(compound_refs, list) or not all(
        isinstance(item, str) for item in compound_refs
    ):
        raise ValueError("compound_lineage_row_ids must be a string array")
    identity = {
        "derivation": "canonical_symbol_exact_match_v1",
        "canonical_symbol": row.get("canonical_symbol"),
        "disease_lineage_row_ids": sorted(disease_refs),
        "compound_lineage_row_ids": sorted(compound_refs),
    }
    return f"intersection-{_canonical_sha256(identity)}"


def _validate_intersection_refs(
    rows: list[dict[str, Any]],
    disease_rows: list[dict[str, Any]],
    compound_rows: list[dict[str, Any]],
    disease_by_id: dict[str, dict[str, Any]],
    compound_by_id: dict[str, dict[str, Any]],
    issues: list[str],
) -> None:
    seen_symbols: set[str] = set()
    for index, row in enumerate(rows):
        symbol = row.get("canonical_symbol")
        if isinstance(symbol, str):
            if symbol in seen_symbols:
                issues.append("intersection_targets must contain one derivation row per symbol")
            seen_symbols.add(symbol)
        disease_refs = row.get("disease_lineage_row_ids")
        compound_refs = row.get("compound_lineage_row_ids")
        expected_disease_refs = sorted(
            row_id
            for row_id, source_row in disease_by_id.items()
            if source_row.get("canonical_symbol") == symbol
        )
        expected_compound_refs = sorted(
            row_id
            for row_id, source_row in compound_by_id.items()
            if source_row.get("canonical_symbol") == symbol
        )
        if not isinstance(disease_refs, list) or sorted(disease_refs) != expected_disease_refs:
            issues.append(
                f"intersection_targets[{index}].disease_lineage_row_ids must exactly reference all matching disease rows"
            )
        if not isinstance(compound_refs, list) or sorted(compound_refs) != expected_compound_refs:
            issues.append(
                f"intersection_targets[{index}].compound_lineage_row_ids must exactly reference all matching compound rows"
            )
        if row.get("derivation") != "canonical_symbol_exact_match_v1":
            issues.append(f"intersection_targets[{index}].derivation is invalid")
        if row.get("automatic_status") != "derived":
            issues.append(f"intersection_targets[{index}].automatic_status must be derived")
        if row.get("adjudication_status") != "pending" or row.get("decision") != "unreviewed":
            issues.append(f"intersection_targets[{index}] must remain pending/unreviewed")
        if any(
            row.get(field) is not None
            for field in ("reviewer_id", "reviewed_at", "decision_rationale")
        ):
            issues.append(
                f"intersection_targets[{index}] must not invent human adjudication metadata"
            )
        try:
            expected_row_id = _intersection_row_id(row)
        except ValueError as exc:
            issues.append(f"intersection_targets[{index}]: {exc}")
        else:
            if row.get("lineage_row_id") != expected_row_id:
                issues.append(
                    f"intersection_targets[{index}].lineage_row_id does not match derivation refs"
                )


def _validate_disease_import(
    result: dict[str, Any],
    protocol: dict[str, Any],
    lineage: dict[str, Any],
    disease_rows: list[dict[str, Any]],
    issues: list[str],
    source_artifact_path: Path | None,
) -> None:
    provenance_value = lineage.get("disease_import_provenance")
    if not disease_rows and provenance_value is None:
        return
    if not isinstance(provenance_value, dict):
        issues.append(
            "target_lineage.disease_import_provenance is required for imported disease rows"
        )
        return
    provenance = provenance_value
    verification_status = provenance.get("provenance_verification_status")
    if verification_status not in {
        "unverified_client_import",
        "server_verified_raw_artifact",
    }:
        issues.append("disease import provenance verification status is invalid")
    if provenance.get("source_profile") != "open_targets_association_v1":
        issues.append("disease import source_profile is invalid")
    if provenance.get("source_database") != "Open Targets Platform":
        issues.append("disease import source_database is invalid")
    if provenance.get("query_date") != protocol.get("query_date"):
        issues.append("disease import query_date does not match research_protocol")
    _bounded_numeric_value(
        provenance.get("applied_threshold"),
        field="disease import applied_threshold",
        upper_bound=1,
        issues=issues,
    )
    _non_negative_integer(
        provenance.get("record_count"),
        field="disease import record_count",
        issues=issues,
    )
    if provenance.get("record_count") != len(disease_rows):
        issues.append("disease import record_count does not match disease lineage rows")
    seen_source_record_ids: set[str] = set()
    for index, row in enumerate(disease_rows):
        expected_metadata = {
            "source_database": provenance.get("source_database"),
            "database_version": provenance.get("database_version"),
            "source_query": provenance.get("source_query_id"),
            "query_date": provenance.get("query_date"),
            "species": protocol.get("species"),
            "score_name": provenance.get("score_name"),
            "applied_threshold": provenance.get("applied_threshold"),
            "threshold_operator": provenance.get("threshold_operator"),
            "identifier_mapping": provenance.get("identifier_mapping"),
            "identifier_mapping_version": provenance.get("identifier_mapping_version"),
            "evidence_origin": "disease_association",
        }
        for field, expected_value in expected_metadata.items():
            if row.get(field) != expected_value:
                issues.append(
                    f"disease_targets[{index}].{field} does not match disease import provenance"
                )
        if not _same_timestamp(row.get("retrieved_at"), provenance.get("retrieved_at")):
            issues.append(
                f"disease_targets[{index}].retrieved_at does not match disease import provenance"
            )
        if row.get("automatic_status") != "extracted":
            issues.append(f"disease_targets[{index}].automatic_status must be extracted")
        if row.get("adjudication_status") != "pending" or row.get("decision") != "unreviewed":
            issues.append(f"disease_targets[{index}] must remain pending/unreviewed")
        if any(
            row.get(field) is not None
            for field in ("reviewer_id", "reviewed_at", "decision_rationale")
        ):
            issues.append(f"disease_targets[{index}] must not invent human adjudication metadata")
        source_record_ids = row.get("source_record_ids")
        if (
            not isinstance(source_record_ids, list)
            or len(source_record_ids) != 1
            or not isinstance(source_record_ids[0], str)
            or not source_record_ids[0].strip()
        ):
            issues.append("each disease lineage row must contain exactly one source_record_id")
        elif source_record_ids[0] in seen_source_record_ids:
            issues.append("disease target source_record_id values must be unique")
        else:
            seen_source_record_ids.add(source_record_ids[0])
        score = _bounded_numeric_value(
            row.get("source_score"),
            field=f"disease_targets[{index}].source_score",
            upper_bound=1,
            issues=issues,
        )
        threshold = _bounded_numeric_value(
            row.get("applied_threshold"),
            field=f"disease_targets[{index}].applied_threshold",
            upper_bound=1,
            issues=issues,
        )
        if score is not None and threshold is not None and score < threshold:
            issues.append(f"disease_targets[{index}] does not satisfy applied threshold")
    readiness = result.get("readiness")
    if not isinstance(readiness, dict):
        issues.append("readiness is required when disease import provenance is present")
    else:
        if readiness.get("formal_network_ready") is not False:
            issues.append("disease import cannot be formal_network_ready before later gates")
        blockers = readiness.get("blocking_reasons")
        if verification_status == "unverified_client_import":
            if not isinstance(blockers, list) or not any(
                isinstance(reason, str) and "客户端导入" in reason and "未验证" in reason
                for reason in blockers
            ):
                issues.append("readiness must expose the unverified client import blocker")
        elif lineage.get("compound_import_provenance") is not None:
            if not isinstance(blockers, list) or not any(
                isinstance(reason, str) and "疾病与 compound 来源已服务端核验" in reason
                for reason in blockers
            ):
                issues.append("readiness must expose the dual-artifact remaining-gates blocker")
        elif not isinstance(blockers, list) or not any(
            isinstance(reason, str) and "疾病来源已服务端核验" in reason for reason in blockers
        ):
            issues.append("readiness must expose the verified-disease remaining-gates blocker")
    if verification_status == "server_verified_raw_artifact":
        for field in (
            "source_artifact_filename",
            "source_artifact_media_type",
            "usage_license_note",
        ):
            if not isinstance(provenance.get(field), str) or not provenance[field].strip():
                issues.append(f"verified disease import {field} is missing")
        artifact_hash = provenance.get("source_artifact_sha256")
        if not isinstance(artifact_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact_hash):
            issues.append("verified disease import source_artifact_sha256 is missing or invalid")
        elif source_artifact_path is not None:
            try:
                recomputed_artifact_hash = hashlib.sha256(
                    source_artifact_path.read_bytes()
                ).hexdigest()
            except OSError as exc:
                issues.append(f"cannot read source artifact: {exc}")
            else:
                if recomputed_artifact_hash != artifact_hash:
                    issues.append(
                        "verified disease import source_artifact_sha256 does not match raw bytes"
                    )
    payload_hash = provenance.get("import_payload_sha256")
    if not isinstance(payload_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", payload_hash):
        issues.append("disease import payload hash is missing or invalid")
        return
    records: list[dict[str, Any]] = []
    for row in disease_rows:
        source_record_ids = row.get("source_record_ids")
        if (
            not isinstance(source_record_ids, list)
            or len(source_record_ids) != 1
            or not isinstance(source_record_ids[0], str)
            or not source_record_ids[0].strip()
        ):
            issues.append("each disease lineage row must contain exactly one source_record_id")
            return
        records.append(
            {
                "raw_identifier": row.get("raw_identifier"),
                "canonical_symbol": row.get("canonical_symbol"),
                "source_record_id": source_record_ids[0],
                "source_score": row.get("source_score"),
            }
        )
    import_payload = {
        "source_profile": provenance.get("source_profile"),
        "disease": protocol.get("disease"),
        "phenotype": protocol.get("phenotype"),
        "species": protocol.get("species"),
        "source_database": provenance.get("source_database"),
        "database_version": provenance.get("database_version"),
        "source_query_id": provenance.get("source_query_id"),
        "source_query_label": provenance.get("source_query_label"),
        "source_query_parameters": provenance.get("source_query_parameters"),
        "query_date": provenance.get("query_date"),
        "retrieved_at": provenance.get("retrieved_at"),
        "score_name": provenance.get("score_name"),
        "applied_threshold": provenance.get("applied_threshold"),
        "threshold_operator": provenance.get("threshold_operator"),
        "identifier_mapping": provenance.get("identifier_mapping"),
        "identifier_mapping_version": provenance.get("identifier_mapping_version"),
        "records": records,
    }
    if verification_status == "server_verified_raw_artifact":
        import_payload["usage_license_note"] = provenance.get("usage_license_note")
    if _canonical_sha256(import_payload) != payload_hash:
        issues.append("disease import payload hash does not match persisted import rows")


def _validate_compound_import(
    result: dict[str, Any],
    protocol: dict[str, Any],
    lineage: dict[str, Any],
    compound_rows: list[dict[str, Any]],
    issues: list[str],
    source_artifact_path: Path | None,
) -> None:
    provenance_value = lineage.get("compound_import_provenance")
    if provenance_value is None:
        return
    if not isinstance(provenance_value, dict):
        issues.append(
            "target_lineage.compound_import_provenance is required for imported compound rows"
        )
        return
    provenance = provenance_value
    if provenance.get("provenance_verification_status") != "server_verified_raw_artifact":
        issues.append("compound import provenance verification status is invalid")
    if provenance.get("source_profile") != "chembl_known_activity_v1":
        issues.append("compound import source_profile is invalid")
    if provenance.get("source_database") != "ChEMBL":
        issues.append("compound import source_database is invalid")
    if provenance.get("source_query_id") != provenance.get("compound_id"):
        issues.append("compound import source_query_id must match compound_id")
    if provenance.get("query_date") != protocol.get("query_date"):
        issues.append("compound import query_date does not match research_protocol")
    if provenance.get("species") != protocol.get("species"):
        issues.append("compound import species does not match research_protocol")
    source_task_id = result.get("source_task_id")
    if (
        not isinstance(source_task_id, str)
        or _NETWORK_TASK_ID_PATTERN.fullmatch(source_task_id) is None
    ):
        issues.append("compound import result source_task_id is missing or invalid")
    elif source_task_id == result.get("task_id"):
        issues.append("compound import result source_task_id must not equal result.task_id")
    for field, expected in (
        ("chains", []),
        ("enrichment", None),
        ("ppi_edges", []),
        ("data_sources", []),
        ("pipeline_steps", []),
    ):
        if result.get(field) != expected:
            expected_label = "null" if expected is None else "[]"
            issues.append(f"compound import snapshot-only output requires {field}={expected_label}")
    warnings = result.get("warnings")
    if not isinstance(warnings, list) or _SNAPSHOT_ONLY_NETWORK_BLOCKER not in warnings:
        issues.append(
            "compound import snapshot-only output must expose its network-assembly warning"
        )
    provenance_threshold = _bounded_numeric_value(
        provenance.get("applied_threshold"),
        field="compound import applied_threshold",
        upper_bound=20,
        issues=issues,
    )
    _non_negative_integer(
        provenance.get("record_count"),
        field="compound import record_count",
        issues=issues,
    )
    query_parameters = provenance.get("source_query_parameters")
    if not isinstance(query_parameters, dict):
        issues.append("compound source_query_parameters must be an object")
    else:
        allowed_query_fields = {"assay_organism", "pchembl_value_min", "standard_type"}
        required_query_fields = {"assay_organism", "pchembl_value_min"}
        unknown_query_fields = set(query_parameters) - allowed_query_fields
        missing_query_fields = required_query_fields - set(query_parameters)
        if unknown_query_fields:
            issues.append(
                "compound source_query_parameters contain unsupported fields: "
                f"{sorted(unknown_query_fields)}"
            )
        if missing_query_fields:
            issues.append(
                "compound source_query_parameters are missing fields: "
                f"{sorted(missing_query_fields)}"
            )
        if query_parameters.get("assay_organism") != provenance.get("species"):
            issues.append("compound assay_organism must match species")
        query_threshold = _bounded_numeric_value(
            query_parameters.get("pchembl_value_min"),
            field="compound pchembl_value_min",
            upper_bound=20,
            issues=issues,
        )
        if (
            query_threshold is not None
            and provenance_threshold is not None
            and query_threshold != provenance_threshold
        ):
            issues.append("compound pchembl_value_min must match applied_threshold")
        standard_type = query_parameters.get("standard_type")
        if standard_type is not None and (
            not isinstance(standard_type, str) or not standard_type.strip()
        ):
            issues.append("compound standard_type must be a non-empty string when present")
    if provenance.get("record_count") != len(compound_rows):
        issues.append("compound import record_count does not match compound lineage rows")
    for field in (
        "compound_id",
        "compound_label",
        "database_version",
        "source_query_id",
        "source_query_label",
        "score_name",
        "identifier_mapping",
        "identifier_mapping_version",
        "usage_license_note",
        "source_artifact_filename",
        "source_artifact_media_type",
    ):
        if not isinstance(provenance.get(field), str) or not provenance[field].strip():
            issues.append(f"verified compound import {field} is missing")
    artifact_hash = provenance.get("source_artifact_sha256")
    if not isinstance(artifact_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact_hash):
        issues.append("verified compound import source_artifact_sha256 is missing or invalid")
    elif source_artifact_path is not None:
        try:
            recomputed_artifact_hash = hashlib.sha256(source_artifact_path.read_bytes()).hexdigest()
        except OSError as exc:
            issues.append(f"cannot read compound source artifact: {exc}")
        else:
            if recomputed_artifact_hash != artifact_hash:
                issues.append("compound source_artifact_sha256 does not match raw bytes")

    records: list[dict[str, Any]] = []
    seen_source_record_ids: set[str] = set()
    for index, row in enumerate(compound_rows):
        expected_metadata = {
            "source_database": provenance.get("source_database"),
            "database_version": provenance.get("database_version"),
            "source_query": provenance.get("source_query_id"),
            "query_date": provenance.get("query_date"),
            "species": provenance.get("species"),
            "score_name": provenance.get("score_name"),
            "applied_threshold": provenance.get("applied_threshold"),
            "threshold_operator": provenance.get("threshold_operator"),
            "identifier_mapping": provenance.get("identifier_mapping"),
            "identifier_mapping_version": provenance.get("identifier_mapping_version"),
            "evidence_origin": "known_activity",
        }
        for field, expected_value in expected_metadata.items():
            if row.get(field) != expected_value:
                issues.append(
                    f"compound_targets[{index}].{field} does not match compound import provenance"
                )
        if not _same_timestamp(row.get("retrieved_at"), provenance.get("retrieved_at")):
            issues.append(
                f"compound_targets[{index}].retrieved_at does not match compound import provenance"
            )
        source_record_ids = row.get("source_record_ids")
        if (
            not isinstance(source_record_ids, list)
            or len(source_record_ids) != 1
            or not isinstance(source_record_ids[0], str)
            or not source_record_ids[0].strip()
        ):
            issues.append("each compound lineage row must contain exactly one source_record_id")
            continue
        if source_record_ids[0] in seen_source_record_ids:
            issues.append("compound target source_record_id values must be unique")
        else:
            seen_source_record_ids.add(source_record_ids[0])
        score = _bounded_numeric_value(
            row.get("source_score"),
            field=f"compound_targets[{index}].source_score",
            upper_bound=20,
            issues=issues,
        )
        threshold = _bounded_numeric_value(
            row.get("applied_threshold"),
            field=f"compound_targets[{index}].applied_threshold",
            upper_bound=20,
            issues=issues,
        )
        if score is not None and threshold is not None and score < threshold:
            issues.append(f"compound_targets[{index}] does not satisfy applied threshold")
        records.append(
            {
                "raw_identifier": row.get("raw_identifier"),
                "canonical_symbol": row.get("canonical_symbol"),
                "source_record_id": source_record_ids[0],
                "source_score": score,
            }
        )
    payload_hash = provenance.get("import_payload_sha256")
    if not isinstance(payload_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", payload_hash):
        issues.append("compound import payload hash is missing or invalid")
    else:
        import_payload = {
            "source_profile": provenance.get("source_profile"),
            "compound_id": provenance.get("compound_id"),
            "compound_label": provenance.get("compound_label"),
            "species": provenance.get("species"),
            "source_database": provenance.get("source_database"),
            "database_version": provenance.get("database_version"),
            "source_query_id": provenance.get("source_query_id"),
            "source_query_label": provenance.get("source_query_label"),
            "source_query_parameters": provenance.get("source_query_parameters"),
            "query_date": provenance.get("query_date"),
            "retrieved_at": provenance.get("retrieved_at"),
            "score_name": provenance.get("score_name"),
            "applied_threshold": provenance.get("applied_threshold"),
            "threshold_operator": provenance.get("threshold_operator"),
            "identifier_mapping": provenance.get("identifier_mapping"),
            "identifier_mapping_version": provenance.get("identifier_mapping_version"),
            "usage_license_note": provenance.get("usage_license_note"),
            "records": records,
        }
        if _canonical_sha256(import_payload) != payload_hash:
            issues.append("compound import payload hash does not match persisted import rows")
    readiness = result.get("readiness")
    if not isinstance(readiness, dict):
        issues.append("readiness is required when compound import provenance is present")
    elif readiness.get("formal_network_ready") is not False:
        issues.append("compound import cannot be formal_network_ready before later gates")
    else:
        blockers = readiness.get("blocking_reasons")
        if not isinstance(blockers, list) or not any(
            isinstance(reason, str) and "人工判定" in reason for reason in blockers
        ):
            issues.append("readiness must expose the remaining human-adjudication blocker")
        if not isinstance(blockers, list) or _SNAPSHOT_ONLY_NETWORK_BLOCKER not in blockers:
            issues.append("readiness must expose the snapshot-only network-assembly blocker")


def validate(
    artifact: Any,
    source_artifact_path: Path | None = None,
    compound_source_artifact_path: Path | None = None,
) -> dict[str, Any]:
    root = _object(artifact, "artifact")
    result = _object(root.get("result"), "artifact.result") if "result" in root else root
    protocol = _object(result.get("research_protocol"), "research_protocol")
    lineage = _object(result.get("target_lineage"), "target_lineage")

    disease_rows = _rows(lineage, "disease_targets")
    compound_rows = _rows(lineage, "compound_targets")
    intersection_rows = _rows(lineage, "intersection_targets")
    disease_symbols = _symbols(disease_rows, "disease_targets")
    compound_symbols = _symbols(compound_rows, "compound_targets")
    intersection_symbols = _symbols(intersection_rows, "intersection_targets")

    recomputed = {
        "disease_target_count": len(disease_symbols),
        "compound_target_count": len(compound_symbols),
        "intersection_target_count": len(intersection_symbols),
        "disease_lineage_row_count": len(disease_rows),
        "compound_lineage_row_count": len(compound_rows),
        "intersection_lineage_row_count": len(intersection_rows),
    }
    issues: list[str] = []
    _validate_research_protocol(protocol, issues)
    for field, actual in recomputed.items():
        if lineage.get(field) != actual:
            issues.append(f"{field}: declared={lineage.get(field)!r}, recomputed={actual}")

    expected_intersection_symbols = disease_symbols & compound_symbols
    if intersection_symbols != expected_intersection_symbols:
        issues.append(
            "intersection_targets must exactly equal the canonical-symbol intersection "
            "of disease_targets and compound_targets"
        )

    has_import_provenance = lineage.get("disease_import_provenance") is not None
    should_validate_row_ids = (
        has_import_provenance
        or lineage.get("observation_unit") == "mixed"
        or bool(intersection_rows)
        or any(row.get("lineage_row_id") is not None for row in disease_rows + compound_rows)
    )
    if should_validate_row_ids:
        disease_by_id = _validate_lineage_row_ids("disease", disease_rows, issues)
        compound_by_id = _validate_lineage_row_ids("compound", compound_rows, issues)
        _validate_intersection_refs(
            intersection_rows,
            disease_rows,
            compound_rows,
            disease_by_id,
            compound_by_id,
            issues,
        )

    expected_query_date = protocol.get("query_date")
    expected_species = protocol.get("species")
    for set_name, rows in (
        ("disease_targets", disease_rows),
        ("compound_targets", compound_rows),
        ("intersection_targets", intersection_rows),
    ):
        for index, row in enumerate(rows):
            if row.get("query_date") != expected_query_date:
                issues.append(f"{set_name}[{index}].query_date does not match research_protocol")
            if row.get("species") != expected_species:
                issues.append(f"{set_name}[{index}].species does not match research_protocol")

    compound_rows_have_current_contract = lineage.get("observation_unit") == "mixed" or any(
        row.get("lineage_row_id") is not None for row in compound_rows
    )
    for index, row in enumerate(compound_rows if compound_rows_have_current_contract else []):
        if row.get("automatic_status") != "extracted":
            issues.append(f"compound_targets[{index}].automatic_status must be extracted")
        if row.get("adjudication_status") != "pending" or row.get("decision") != "unreviewed":
            issues.append(f"compound_targets[{index}] must remain pending/unreviewed")
        if any(
            row.get(field) is not None
            for field in ("reviewer_id", "reviewed_at", "decision_rationale")
        ):
            issues.append(f"compound_targets[{index}] must not invent human adjudication metadata")

    if lineage.get("compound_import_provenance") is not None:
        disease_provenance = lineage.get("disease_import_provenance")
        if (
            not isinstance(disease_provenance, dict)
            or disease_provenance.get("provenance_verification_status")
            != "server_verified_raw_artifact"
        ):
            issues.append("compound import requires a server-verified disease parent provenance")

    _validate_disease_import(
        result,
        protocol,
        lineage,
        disease_rows,
        issues,
        source_artifact_path,
    )
    _validate_compound_import(
        result,
        protocol,
        lineage,
        compound_rows,
        issues,
        compound_source_artifact_path,
    )

    readiness = result.get("readiness")
    if lineage.get("observation_unit") == "mixed" and not isinstance(readiness, dict):
        issues.append("readiness is required for the current mixed lineage contract")
    elif isinstance(readiness, dict):
        if readiness.get("formal_network_ready") is not False:
            issues.append(
                "formal_network_ready must remain false until independently verified "
                "provenance and human adjudication are implemented"
            )
        blockers = readiness.get("blocking_reasons")
        if (
            lineage.get("disease_import_provenance") is not None
            and not disease_rows
            and (
                not isinstance(blockers, list)
                or not any(
                    isinstance(reason, str) and "疾病靶点集合为空" in reason for reason in blockers
                )
            )
        ):
            issues.append("readiness must expose the empty disease-target set blocker")
        if (
            lineage.get("disease_import_provenance") is not None
            and lineage.get("compound_import_provenance") is not None
            and not intersection_rows
            and (
                not isinstance(blockers, list)
                or not any(
                    isinstance(reason, str) and "派生交集为空" in reason for reason in blockers
                )
            )
        ):
            issues.append("readiness must expose the empty intersection blocker")

    return {
        "artifact_consistency_pass": not issues,
        "recomputed": recomputed,
        "declared_intersection_symbols": sorted(intersection_symbols),
        "expected_intersection_symbols": sorted(expected_intersection_symbols),
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--source-artifact", "--disease-source-artifact", type=Path)
    parser.add_argument("--compound-source-artifact", type=Path)
    args = parser.parse_args()
    try:
        artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
        output = validate(
            artifact,
            source_artifact_path=args.source_artifact,
            compound_source_artifact_path=args.compound_source_artifact,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        output = {
            "artifact_consistency_pass": False,
            "recomputed": {},
            "issues": [str(exc)],
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["artifact_consistency_pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
