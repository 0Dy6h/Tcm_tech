"""Independently validate the adjudication audit HMAC chain (contract §6.2).

The writer consumption contract defers a "privileged reviewer-identity audit
HMAC" as its own slice: adjudication events persisted on network tasks carry
a chained server-private HMAC (opt-in via ``QIYAN_ADJUDICATION_AUDIT_KEY``)
so out-of-band tampering of the audited era is detectable. This script
re-derives the whole chain from the persisted state and reports violations.
It deliberately shares no code with ``app.core.audit_hmac``: the producer's
canonicalization and chain derivation are re-implemented here from first
principles, mirroring the other ``validate_*.py`` scripts.

Chain rule (``adjudication_audit_hmac_v1``)::

    audit_hmac[i] = HMAC-SHA256(key, canonical_json({
        "policy_id":       "adjudication_audit_hmac_v1",
        "task_id":         task_id,
        "sequence":        i,               # full-stream index at append time
        "prev_audit_hmac": events[i-1].audit_hmac,  # null at head/untagged
        "event":           event minus audit_hmac,     # incl. reviewer_id
    }))

An event without ``audit_hmac`` is reported as ``unaudited`` (legacy prefix
or audit disabled at append time), never as a violation. A tag mismatch
means the event content, its index (deletion/insertion before it), its
neighbour link or the tag itself no longer matches the key.

State inputs (operator-controlled, gitignored):
    --state-json PATH    network-task JSON state file (list of records)
    --sqlite-db PATH     SQLite database with the network_task table
    --task-id ID         optional: restrict verification to one task

Exit codes: 0 = no violations, 1 = violations found, 2 = usage/config error.
The verification key is read from ``QIYAN_ADJUDICATION_AUDIT_KEY``; without
it the tool fails closed (exit 2) instead of guessing.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

_POLICY_ID = "adjudication_audit_hmac_v1"
_KEY_ENV = "QIYAN_ADJUDICATION_AUDIT_KEY"


def _canonical_json(payload: Any) -> str:
    """Zero-shared copy of ``qiyan_canonical_json_v1``."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _derive_tag(
    key: bytes,
    task_id: str,
    sequence: int,
    prev_audit_hmac: str | None,
    event: dict[str, Any],
) -> str:
    covered = {
        "policy_id": _POLICY_ID,
        "task_id": task_id,
        "sequence": sequence,
        "prev_audit_hmac": prev_audit_hmac,
        "event": {name: value for name, value in event.items() if name != "audit_hmac"},
    }
    return hmac.new(
        key,
        _canonical_json(covered).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def validate_tasks(
    tasks: list[Any], key: bytes
) -> tuple[bool, list[str], int]:
    """Walk every task's adjudication stream; return (ok, issues, unaudited)."""
    issues: list[str] = []
    unaudited = 0
    for task_index, task in enumerate(tasks):
        if not isinstance(task, dict):
            issues.append(f"tasks[{task_index}] must be a JSON object")
            continue
        raw_task_id = task.get("task_id")
        task_id = raw_task_id if isinstance(raw_task_id, str) else ""
        task_label = raw_task_id if isinstance(raw_task_id, str) else f"tasks[{task_index}]"
        events = task.get("adjudications")
        if events is None:
            continue
        if not isinstance(events, list):
            issues.append(f"{task_label}.adjudications must be an array")
            continue
        prev_tag: str | None = None
        seen_ids: set[str] = set()
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                issues.append(f"{task_label}.adjudications[{index}] must be a JSON object")
                prev_tag = None
                continue
            adjudication_id = event.get("adjudication_id")
            id_label = adjudication_id if isinstance(adjudication_id, str) else "?"
            if isinstance(adjudication_id, str):
                if adjudication_id in seen_ids:
                    issues.append(
                        f"duplicate adjudication_id {adjudication_id} "
                        f"at task {task_label} index {index}"
                    )
                seen_ids.add(adjudication_id)
            tag = event.get("audit_hmac")
            if not isinstance(tag, str):
                unaudited += 1
                prev_tag = None
                continue
            reviewer_id = event.get("reviewer_id")
            reviewer_label = reviewer_id if isinstance(reviewer_id, str) else "?"
            expected = _derive_tag(key, task_id, index, prev_tag, event)
            if not hmac.compare_digest(tag, expected):
                issues.append(
                    f"audit_hmac mismatch at task {task_label} index {index} "
                    f"({id_label}, reviewer_id={reviewer_label})"
                )
            # Link against the stored tag regardless of the verdict above: a
            # tampered event must not cascade mismatches onto intact children.
            prev_tag = tag
    return (not issues, issues, unaudited)


def _load_json_state(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("state json must be a list of task records")
    return payload


def _load_sqlite_state(path: Path) -> list[Any]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT task_id, owner_id, adjudications FROM network_task"
        ).fetchall()
    finally:
        connection.close()
    tasks: list[Any] = []
    for task_id, owner_id, raw_events in rows:
        events = [] if raw_events is None else json.loads(raw_events)
        tasks.append({"task_id": task_id, "owner_id": owner_id, "adjudications": events})
    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-json", type=Path, default=None, help="network-task JSON state")
    parser.add_argument("--sqlite-db", type=Path, default=None, help="SQLite network-task DB")
    parser.add_argument("--task-id", default=None, help="restrict verification to one task")
    args = parser.parse_args(argv)

    raw_key = os.environ.get(_KEY_ENV)
    if not raw_key:
        print(f"error: {_KEY_ENV} is not set; nothing to verify against", file=sys.stderr)
        return 2
    if args.state_json is None and args.sqlite_db is None:
        print("error: pass --state-json and/or --sqlite-db", file=sys.stderr)
        return 2

    tasks: list[Any] = []
    try:
        if args.state_json is not None:
            tasks.extend(_load_json_state(args.state_json))
        if args.sqlite_db is not None:
            tasks.extend(_load_sqlite_state(args.sqlite_db))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"error: cannot read state: {exc}", file=sys.stderr)
        return 2

    if args.task_id is not None:
        tasks = [task for task in tasks if isinstance(task, dict) and task.get("task_id") == args.task_id]

    ok, issues, unaudited = validate_tasks(tasks, raw_key.encode("utf-8"))
    for issue in issues:
        print(f"issue: {issue}", file=sys.stderr)
    status = "OK" if ok else "VIOLATIONS"
    print(
        f"adjudication audit: {status}; tasks={len(tasks)} "
        f"unaudited_events={unaudited} violations={len(issues)}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
