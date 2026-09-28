"""Shared primitives for the split ``network`` service modules.

Dependency-light on purpose (schemas + canonical JSON only) so every sibling
submodule can import from here at module level without import cycles.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.canonical_json import canonical_json_sha256

_MAX_CHAINS_PER_QUERY = 5
_IMPORTED_COMPOUND_SNAPSHOT_BLOCKER = "导入靶点尚未构建可复算的成分-靶点-通路网络闭环。"
_UNLINKED_COMPOUND_CHILD_ERROR = "成分靶点导入缺少不可变的疾病父任务链接，已失败关闭。"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_sha256(payload: Any) -> str:
    # Shared with the repository backends so write-time and consume-time
    # recomputation of bound hashes always agree (qiyan_canonical_json_v1).
    return canonical_json_sha256(payload)
