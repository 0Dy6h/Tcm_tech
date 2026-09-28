"""Server-private audit HMAC for the adjudication stream (contract §6.2).

Writer consumption contract §6.2 defers a "privileged reviewer-identity audit
HMAC" as its own slice: the adjudication events persisted on a network task
carry a chained server-private HMAC so out-of-band edits, deletions,
reorderings or tag stripping inside the audited era are detectable by the
offline operator tool (``backend/scripts/validate_adjudication_audit.py``).
This is audit evidence, not access control: nothing in the read, report,
plan-seal or writer-consumption paths verifies or exposes it.

The chain rule (``adjudication_audit_hmac_v1``)::

    audit_hmac[i] = HMAC-SHA256(key, canonical_json({
        "policy_id":       "adjudication_audit_hmac_v1",
        "task_id":         task_id,
        "sequence":        i,          # full-stream index at append time
        "prev_audit_hmac": events[i-1].audit_hmac,  # null at head/untagged
        "event":           event minus audit_hmac,     # incl. reviewer_id
    }))

The key is operator-provided via ``QIYAN_ADJUDICATION_AUDIT_KEY`` (unlike the
process-local RAG export signing key, an audit stream is durable state that
must stay verifiable across restarts). Unset or empty means audit is off and
the default path behaves exactly as before. The offline validator keeps a
zero-shared copy of this derivation, mirroring the other ``validate_*.py``
scripts; changing this module means re-deriving the script copy too.
"""

import hashlib
import hmac
import os
from collections.abc import Mapping
from typing import Any

from app.core.canonical_json import canonical_json_payload

AUDIT_POLICY_ID = "adjudication_audit_hmac_v1"
AUDIT_KEY_ENV = "QIYAN_ADJUDICATION_AUDIT_KEY"


def load_audit_key() -> bytes | None:
    """Read the operator key at call time; ``None`` disables audit tagging."""
    raw = os.environ.get(AUDIT_KEY_ENV)
    if not raw:
        return None
    return raw.encode("utf-8")


def derive_adjudication_audit_hmac(
    key: bytes,
    task_id: str,
    sequence: int,
    prev_audit_hmac: str | None,
    event_payload: Mapping[str, Any],
) -> str:
    """Derive one chain tag; ``event_payload`` must exclude ``audit_hmac``."""
    covered = {
        "policy_id": AUDIT_POLICY_ID,
        "task_id": task_id,
        "sequence": sequence,
        "prev_audit_hmac": prev_audit_hmac,
        "event": dict(event_payload),
    }
    return hmac.new(
        key,
        canonical_json_payload(covered).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
