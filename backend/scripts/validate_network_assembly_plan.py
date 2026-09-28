"""Independently validate a sealed source-bound network assembly plan.

This script recomputes every binding of a candidate assembly plan from a
public evidence package and reports pass/fail. It deliberately shares no code
with ``app.services.network``: the producer's hashing and selection logic is
re-derived here from first principles so a coordinated producer bug or a
tampered artifact cannot pass both paths.

Evidence package (JSON):
    {
      "plan": { ... full NetworkAssemblyPlan JSON ... },
      "child_result": { ... frozen NetworkAnalysisResult JSON ... },
      "parent_protocol": { ... research protocol JSON ... },
      "child_protocol": { ... research protocol JSON ... },
      "adjudications": [
        {"adjudication_id": "...", "lineage_row_id": "...",
         "decision": "...", "reason": "...|null", "decided_at": "..."}
      ],
      "raw_artifact_dir": "optional path to the server raw-artifact store",

      "outputs": [ { ... NetworkAssemblyOutput JSON ... } ],
      "consumptions": [ { ... NetworkAssemblyConsumptionRecord JSON ...
                          (owner_id included: owner-scoped audit field) } ],
      "output_payload": { ... writer payload; enables output_sha256 recompute }
    }

The output/consumption fields extend the package to the writer consumption
contract (decision D9=B, deferred slice): the output envelope, the exactly-once
consumption binding and the structural honesty of the assembled chains are
re-verified independently. All three fields are optional; a plan-only package
stays valid.

The advisory ``warnings`` texts on an output are intentionally not
content-checked: they are producer copy, not integrity bindings.

The package intentionally excludes reviewer identity: this is the public
consistency path. Privileged audit of reviewer identity is a separate slice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_PLAN_ID_PATTERN = re.compile(r"^assembly-plan-[0-9a-f]{64}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ROW_ID_PATTERN = re.compile(r"^(disease|compound|intersection)-[0-9a-f]{64}$")
_CONSUMPTION_ID_PATTERN = re.compile(r"^assembly-consumption-[0-9a-f]{64}$")
_TERMINAL_DECISIONS = {"included", "excluded"}
_DISCLAIMER = "非诊断结论、需结合临床。"


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _rows(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a JSON array")
    return [_object(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _row_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ROW_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a lineage row id")
    return value


def _latest_decisions(
    child_result: dict[str, Any],
    adjudications: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return latest-wins decision per frozen row plus the row id list.

    Latest wins by append order (last event for a row wins), mirroring the
    producer's projection over the append-only audit stream.
    """
    lineage = _object(child_result.get("target_lineage"), "child_result.target_lineage")
    row_ids: list[str] = []
    for set_name in ("disease_targets", "compound_targets"):
        for row in _rows(lineage.get(set_name), f"child_result.target_lineage.{set_name}"):
            row_ids.append(_row_id(row.get("lineage_row_id"), f"{set_name} row lineage_row_id"))
    for row in _rows(
        lineage.get("intersection_targets"), "child_result.target_lineage.intersection_targets"
    ):
        row_ids.append(_row_id(row.get("lineage_row_id"), "intersection row lineage_row_id"))
    row_ids = sorted(set(row_ids))
    latest: dict[str, dict[str, Any]] = {}
    for entry in adjudications:
        event = _object(entry, "adjudications[]")
        row_id = _row_id(event.get("lineage_row_id"), "adjudication lineage_row_id")
        decision = event.get("decision")
        if decision not in _TERMINAL_DECISIONS and decision != "needs_review":
            raise ValueError(f"adjudication decision is invalid: {decision!r}")
        latest[row_id] = event
    return latest, row_ids


def _recompute_selected_intersections(
    child_result: dict[str, Any],
    latest: dict[str, dict[str, Any]],
    issues: list[str],
) -> list[dict[str, Any]]:
    lineage = _object(child_result.get("target_lineage"), "child_result.target_lineage")
    included_disease = {
        row_id
        for row in _rows(
            lineage.get("disease_targets"), "child_result.target_lineage.disease_targets"
        )
        if (row_id := _row_id(row.get("lineage_row_id"), "disease row id")) in latest
        and latest[row_id].get("decision") == "included"
    }
    included_compound = {
        row_id
        for row in _rows(
            lineage.get("compound_targets"), "child_result.target_lineage.compound_targets"
        )
        if (row_id := _row_id(row.get("lineage_row_id"), "compound row id")) in latest
        and latest[row_id].get("decision") == "included"
    }
    selected: list[dict[str, Any]] = []
    for row in _rows(
        lineage.get("intersection_targets"), "child_result.target_lineage.intersection_targets"
    ):
        decision = latest.get(_row_id(row.get("lineage_row_id"), "intersection row id"))
        if decision is None or decision.get("decision") != "included":
            continue
        frozen_disease = sorted(
            _row_id(item, "frozen disease ref") for item in row.get("disease_lineage_row_ids", [])
        )
        frozen_compound = sorted(
            _row_id(item, "frozen compound ref") for item in row.get("compound_lineage_row_ids", [])
        )
        selected_disease = sorted(set(frozen_disease) & included_disease)
        selected_compound = sorted(set(frozen_compound) & included_compound)
        if not selected_disease or not selected_compound:
            issues.append(
                f"included intersection {row.get('lineage_row_id')} lacks included backing rows"
            )
            continue
        selected.append(
            {
                "lineage_row_id": row.get("lineage_row_id"),
                "canonical_symbol": row.get("canonical_symbol"),
                "frozen_disease_lineage_row_ids": frozen_disease,
                "frozen_compound_lineage_row_ids": frozen_compound,
                "selected_disease_lineage_row_ids": selected_disease,
                "selected_compound_lineage_row_ids": selected_compound,
            }
        )
    return selected


def _validate_output_envelope(
    output: dict[str, Any],
    plan: dict[str, Any],
    payload: Any,
    issues: list[str],
) -> None:
    if output.get("assembly_input_ready") is not True:
        issues.append("output.assembly_input_ready must be true")
    if output.get("formal_network_ready") is not False:
        issues.append("output.formal_network_ready must be false")
    for field in (
        "task_id",
        "source_task_id",
        "plan_id",
        "plan_sequence",
        "canonical_plan_input_sha256",
    ):
        if output.get(field) != plan.get(field):
            issues.append(f"output.{field} does not match plan.{field}")
    output_hash = output.get("output_sha256")
    derived_id = "assembly-output-" + _canonical_sha256(
        {
            "task_id": output.get("task_id"),
            "source_task_id": output.get("source_task_id"),
            "plan_id": output.get("plan_id"),
            "plan_sequence": output.get("plan_sequence"),
            "canonical_plan_input_sha256": output.get("canonical_plan_input_sha256"),
            "output_sha256": output_hash,
        }
    )
    if output.get("output_id") != derived_id:
        issues.append("output.output_id does not derive from its binding fields")
    if output.get("disclaimer") != _DISCLAIMER:
        issues.append("output.disclaimer must be the exact product disclaimer")
    # chains/warnings are deliberately outside the hash domain (2026-09-11
    # decision): only the writer payload keys output_sha256.
    if payload is not None and output_hash != _canonical_sha256(payload):
        issues.append("output.output_sha256 does not match the provided output_payload")


def _validate_output_chains(
    output: dict[str, Any],
    selected: list[dict[str, Any]],
    issues: list[str],
) -> None:
    selections = {item.get("lineage_row_id"): item for item in selected if isinstance(item, dict)}
    # Completeness: the 2026-09-11 derivation is deterministic — one chain per
    # (selection × selected compound row). Per-chain honesty checks below only
    # cover chains that exist; this count closes the "silently missing chain"
    # producer-regression class.
    expected_count = sum(
        len(item.get("selected_compound_lineage_row_ids") or []) for item in selections.values()
    )
    chains = _rows(output.get("chains"), "output.chains")
    if len(chains) != expected_count:
        issues.append(
            f"output chain count {len(chains)} does not match the count {expected_count} "
            "derived from plan selections"
        )
    for index, chain in enumerate(chains):
        if chain.get("herb") != "":
            issues.append(f"output chain herb must be empty (chain {index})")
        if chain.get("formula") is not None:
            issues.append(f"output chain formula must be null (chain {index})")
        evidence_type = chain.get("target_evidence_type")
        if evidence_type not in {"predicted", "mock"}:
            issues.append(
                f"output chain target_evidence_type must be predicted or mock (chain {index})"
            )
        level = chain.get("evidence_level")
        # Assembly honesty: verified rows stay predicted (known_activity never
        # floats to experimental, no literature refs), mock rows stay mock_inferred.
        if evidence_type == "mock" and level != "mock_inferred":
            issues.append(
                f"output chain evidence grading violates the assembly policy (chain {index})"
            )
        if evidence_type == "predicted" and (level != "predicted" or chain.get("evidence_refs")):
            issues.append(
                f"output chain evidence grading violates the assembly policy (chain {index})"
            )
        related = chain.get("related_entity_ids")
        related_ids = (
            {item for item in related if isinstance(item, str)}
            if isinstance(related, list)
            else set()
        )
        selection = (
            selections.get(related[0])
            if isinstance(related, list) and related and isinstance(related[0], str)
            else None
        )
        if selection is None:
            issues.append(
                f"output chain does not reference a plan-selected intersection (chain {index})"
            )
            continue
        if chain.get("target") != selection.get("canonical_symbol"):
            issues.append(
                f"output chain target does not match the referenced selected intersection (chain {index})"
            )
        disease_ids = set(selection.get("selected_disease_lineage_row_ids") or [])
        compound_ids = set(selection.get("selected_compound_lineage_row_ids") or [])
        if not disease_ids <= related_ids:
            issues.append(
                f"output chain is missing selected disease lineage row references (chain {index})"
            )
        if not compound_ids & related_ids:
            issues.append(
                f"output chain is missing the selected compound lineage row reference (chain {index})"
            )


def _validate_consumptions(
    consumptions: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    plan: dict[str, Any],
    issues: list[str],
) -> None:
    outputs_by_id = {item.get("output_id"): item for item in outputs if isinstance(item, dict)}
    seen: set[tuple[Any, Any, Any]] = set()
    consumed_output_ids: set[str] = set()
    for index, consumption in enumerate(consumptions):
        record = f"record {index}"
        consumption_id = consumption.get("consumption_id")
        if not isinstance(consumption_id, str) or not _CONSUMPTION_ID_PATTERN.fullmatch(
            consumption_id
        ):
            issues.append(
                f"consumption.consumption_id must match assembly-consumption-<sha256> ({record})"
            )
        for field in ("task_id", "plan_id", "plan_sequence", "canonical_plan_input_sha256"):
            if consumption.get(field) != plan.get(field):
                issues.append(f"consumption.{field} does not match plan.{field} ({record})")
        owner_id = consumption.get("owner_id")
        if not isinstance(owner_id, str) or not owner_id:
            issues.append(f"consumption.owner_id must not be empty ({record})")
        output_id = consumption.get("output_id")
        output = outputs_by_id.get(output_id) if isinstance(output_id, str) else None
        if output is None:
            issues.append(f"consumption.output_id does not reference a sealed output ({record})")
        else:
            for field in (
                "task_id",
                "plan_id",
                "plan_sequence",
                "canonical_plan_input_sha256",
                "output_sha256",
                "writer_id",
                "consumed_at",
            ):
                if consumption.get(field) != output.get(field):
                    issues.append(
                        f"consumption.{field} does not match the referenced output ({record})"
                    )
            consumed_output_ids.add(output_id)
        key = (consumption.get("task_id"), owner_id, consumption.get("plan_id"))
        if key in seen:
            issues.append(
                f"consumption violates exactly-once: duplicate (task_id, owner_id, plan_id) ({record})"
            )
        seen.add(key)
    for output in outputs:
        if output.get("output_id") not in consumed_output_ids:
            issues.append(f"output has no consumption record: {output.get('output_id')}")


def _validate_outputs_and_consumptions(
    evidence: dict[str, Any],
    plan: dict[str, Any],
    issues: list[str],
) -> None:
    raw_outputs = evidence.get("outputs")
    raw_consumptions = evidence.get("consumptions")
    payload = evidence.get("output_payload")
    if raw_outputs is None and raw_consumptions is None:
        if payload is not None:
            issues.append("output_payload provided without outputs; sha256 recompute skipped")
        return
    try:
        outputs = _rows(raw_outputs, "outputs") if raw_outputs is not None else []
        consumptions = (
            _rows(raw_consumptions, "consumptions") if raw_consumptions is not None else []
        )
        if payload is not None:
            payload = _object(payload, "output_payload")
    except ValueError as exc:
        # The extension fields are optional: a structurally malformed package
        # degrades to a reported issue instead of a stack-trace exit.
        issues.append(str(exc))
        return
    plan_selected = plan.get("selected_intersections")
    selected = plan_selected if isinstance(plan_selected, list) else []
    for output in outputs:
        _validate_output_envelope(output, plan, payload, issues)
        try:
            _validate_output_chains(output, selected, issues)
        except ValueError as exc:
            issues.append(str(exc))
    _validate_consumptions(consumptions, outputs, plan, issues)


def validate(evidence: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a plan evidence package; returns (ok, issues)."""
    issues: list[str] = []
    plan = _object(evidence.get("plan"), "plan")
    child_result = _object(evidence.get("child_result"), "child_result")
    parent_protocol = _object(evidence.get("parent_protocol"), "parent_protocol")
    child_protocol = _object(evidence.get("child_protocol"), "child_protocol")
    adjudications = _rows(evidence.get("adjudications"), "adjudications")

    plan_id = plan.get("plan_id")
    input_hash = plan.get("canonical_plan_input_sha256")
    if not isinstance(plan_id, str) or not _PLAN_ID_PATTERN.fullmatch(plan_id):
        issues.append("plan.plan_id must match assembly-plan-<sha256>")
    if not isinstance(input_hash, str) or not _SHA256_PATTERN.fullmatch(input_hash):
        issues.append("plan.canonical_plan_input_sha256 must be a sha256 hex digest")

    if plan.get("policy_id") != "source_bound_network_assembly_v1":
        issues.append("plan.policy_id must be source_bound_network_assembly_v1")
    if plan.get("canonicalization_id") != "qiyan_canonical_json_v1":
        issues.append("plan.canonicalization_id must be qiyan_canonical_json_v1")
    if plan.get("assembly_input_ready") is not True:
        issues.append("plan.assembly_input_ready must be true")
    if plan.get("formal_network_ready") is not False:
        issues.append("plan.formal_network_ready must be false")

    # Snapshot-only boundary: the frozen child must not carry network outputs.
    if child_result.get("chains"):
        issues.append("child_result.chains must be empty (snapshot-only)")
    if child_result.get("enrichment") is not None:
        issues.append("child_result.enrichment must be null (snapshot-only)")
    for field in ("ppi_edges", "data_sources", "pipeline_steps"):
        if child_result.get(field):
            issues.append(f"child_result.{field} must be empty (snapshot-only)")

    # Protocol bindings.
    parent_protocol_hash = _canonical_sha256(parent_protocol)
    child_protocol_hash = _canonical_sha256(child_protocol)
    if plan.get("parent_protocol_sha256") != parent_protocol_hash:
        issues.append("plan.parent_protocol_sha256 does not match parent_protocol")
    if plan.get("child_protocol_sha256") != child_protocol_hash:
        issues.append("plan.child_protocol_sha256 does not match child_protocol")
    if parent_protocol_hash != child_protocol_hash:
        issues.append("parent and child research protocols are not byte-equivalent")
    for field in ("disease", "phenotype", "species", "evidence_policy", "query_date"):
        if parent_protocol.get(field) != child_protocol.get(field):
            issues.append(f"parent/child protocol field mismatch: {field}")

    # Source provenance bindings (frozen values, re-hashed when raw bytes exist).
    lineage = _object(child_result.get("target_lineage"), "child_result.target_lineage")
    disease_provenance = _object(
        lineage.get("disease_import_provenance"),
        "child_result.target_lineage.disease_import_provenance",
    )
    compound_provenance = _object(
        lineage.get("compound_import_provenance"),
        "child_result.target_lineage.compound_import_provenance",
    )
    for side, provenance, plan_field, payload_field in (
        (
            "disease",
            disease_provenance,
            "disease_source_artifact_sha256",
            "disease_import_payload_sha256",
        ),
        (
            "compound",
            compound_provenance,
            "compound_source_artifact_sha256",
            "compound_import_payload_sha256",
        ),
    ):
        if provenance.get("provenance_verification_status") != "server_verified_raw_artifact":
            issues.append(f"{side} provenance must be server_verified_raw_artifact")
        artifact_hash = provenance.get("source_artifact_sha256")
        payload_hash = provenance.get("import_payload_sha256")
        if plan.get(plan_field) != artifact_hash:
            issues.append(f"plan.{plan_field} does not match frozen {side} source artifact hash")
        if plan.get(payload_field) != payload_hash:
            issues.append(f"plan.{payload_field} does not match frozen {side} import payload hash")

    # Raw byte re-hash when the store is available.
    raw_dir = evidence.get("raw_artifact_dir")
    if raw_dir:
        for side, provenance in (
            ("disease", disease_provenance),
            ("compound", compound_provenance),
        ):
            artifact_hash = provenance.get("source_artifact_sha256")
            artifact_path = Path(raw_dir) / f"{artifact_hash}.json"
            if not artifact_path.is_file():
                issues.append(f"{side} raw artifact bytes missing at {artifact_path.name}")
                continue
            if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact_hash:
                issues.append(f"{side} raw artifact bytes do not match their frozen sha256")

    # Frozen lineage and adjudication selection bindings.
    if plan.get("target_lineage_sha256") != _canonical_sha256(lineage):
        issues.append("plan.target_lineage_sha256 does not match child_result.target_lineage")

    latest, row_ids = _latest_decisions(child_result, adjudications)
    incomplete = sorted(
        row_id
        for row_id in row_ids
        if row_id not in latest or latest[row_id].get("decision") == "needs_review"
    )
    if incomplete:
        issues.append(f"adjudication is incomplete for rows: {incomplete}")
    adjudication_snapshot = [
        {
            "adjudication_id": latest[row_id].get("adjudication_id"),
            "lineage_row_id": row_id,
            "decision": latest[row_id].get("decision"),
            "reason": latest[row_id].get("reason"),
            "decided_at": latest[row_id].get("decided_at"),
        }
        for row_id in sorted(latest)
    ]
    if plan.get("adjudication_selection_sha256") != _canonical_sha256(adjudication_snapshot):
        issues.append("plan.adjudication_selection_sha256 does not match the latest-wins snapshot")

    # Selected intersections must equal the independent recomputation.
    recomputed_selected = _recompute_selected_intersections(child_result, latest, issues)
    plan_selected = plan.get("selected_intersections")
    if not isinstance(plan_selected, list):
        issues.append("plan.selected_intersections must be an array")
        plan_selected = []
    if not recomputed_selected:
        issues.append("no included intersection with included backing rows can be derived")
    if plan_selected != recomputed_selected:
        issues.append("plan.selected_intersections do not match the independent recomputation")
        if recomputed_selected:
            issues.append(
                "expected: " + json.dumps(recomputed_selected, ensure_ascii=False, sort_keys=True)
            )

    # Writer consumption contract (D9=B): output envelope + consumption binding.
    _validate_outputs_and_consumptions(evidence, plan, issues)

    # Canonical plan input and idempotent plan id.
    if not isinstance(plan_selected, list) or not plan_selected:
        return False, issues
    recomputed_input = {
        "policy_id": "source_bound_network_assembly_v1",
        "canonicalization_id": "qiyan_canonical_json_v1",
        "task_id": plan.get("task_id"),
        "source_task_id": plan.get("source_task_id"),
        "parent_protocol_sha256": plan.get("parent_protocol_sha256"),
        "child_protocol_sha256": plan.get("child_protocol_sha256"),
        "disease_source_artifact_sha256": plan.get("disease_source_artifact_sha256"),
        "compound_source_artifact_sha256": plan.get("compound_source_artifact_sha256"),
        "disease_import_payload_sha256": plan.get("disease_import_payload_sha256"),
        "compound_import_payload_sha256": plan.get("compound_import_payload_sha256"),
        "target_lineage_sha256": plan.get("target_lineage_sha256"),
        "adjudication_selection_sha256": plan.get("adjudication_selection_sha256"),
        "selected_intersections": recomputed_selected,
    }
    recomputed_input_hash = _canonical_sha256(recomputed_input)
    if plan.get("canonical_plan_input_sha256") != recomputed_input_hash:
        issues.append("plan.canonical_plan_input_sha256 does not match the recomputed plan input")
    if plan.get("plan_id") != f"assembly-plan-{recomputed_input_hash}":
        issues.append("plan.plan_id does not derive from the canonical plan input")

    return not issues, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_path", type=Path, help="path to the evidence package JSON")
    args = parser.parse_args()
    try:
        evidence = json.loads(args.evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read evidence package: {exc}")
        return 2
    ok, issues = validate(evidence)
    for issue in issues:
        print(f"FAIL: {issue}", file=sys.stderr)
    print("VALID" if ok else "INVALID")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
