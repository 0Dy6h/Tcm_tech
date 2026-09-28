r"""Operator tool: populate a real PubMed corpus into runtime state.

The seed literature set is intentionally a small *synthetic* sample (it must not
ship real, copyrighted abstracts as fixtures). When you want a realistic,
broader corpus for an internal trial or reviewer walkthrough, run this script:
it calls the existing ``sync_pubmed`` service for several curated AD + TCM
queries and accumulates the real ``pubmed_live`` records into runtime state
(``backend/data/runtime/``, gitignored) — never into the seed fixtures.

Usage (from ``backend/`` with the project venv):

    & .\.uv-test-venv\Scripts\python.exe scripts\seed_pubmed_corpus.py
    & .\.uv-test-venv\Scripts\python.exe scripts\seed_pubmed_corpus.py --per-query 15

For a Track A real-only validation snapshot (no synthetic seed bootstrap):

    & .\.uv-test-venv\Scripts\python.exe scripts\seed_pubmed_corpus.py `
        --runtime-root ..\.tmp\retrieval-validation-v1 --per-query 50 `
        --min-live-records 300

This makes live calls to NCBI E-utilities; set ``NCBI_API_KEY`` to raise the
rate limit from 3 to 10 req/s. To reset, clear the runtime literature state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# Curated atopic-dermatitis + TCM queries spanning the corpus's themes.
DEFAULT_QUERIES = [
    "atopic dermatitis traditional chinese medicine",
    "atopic dermatitis chinese herbal medicine randomized",
    "atopic dermatitis acupuncture",
    "eczema gut skin axis microbiome",
    "atopic dermatitis skin barrier filaggrin",
    "atopic dermatitis network pharmacology",
    "atopic dermatitis pruritus IL-31",
    "atopic dermatitis JAK inhibitor",
]


def prepare_isolated_runtime(runtime_root: Path, *, resume: bool = False) -> tuple[Path, Path]:
    """Create explicit empty JSON state so runtime bootstrap cannot copy seed fixtures."""

    literature_path = runtime_root / "literature_state.json"
    chunk_path = runtime_root / "chunk_state.json"
    existing = [path for path in (literature_path, chunk_path) if path.exists()]
    if existing and not resume:
        names = ", ".join(str(path) for path in existing)
        raise ValueError(f"isolated runtime state already exists: {names}; pass --resume to reuse")

    runtime_root.mkdir(parents=True, exist_ok=True)
    for path in (literature_path, chunk_path):
        if not path.exists():
            path.write_text("[]\n", encoding="utf-8")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"runtime state must contain a JSON list: {path}")
    return literature_path, chunk_path


def validate_real_only_corpus(items: list[Any], *, min_live_records: int) -> tuple[int, int]:
    """Fail closed if an isolated validation corpus contains seed/non-live records."""

    live = sum(item.record_origin == "pubmed_live" for item in items)
    seed = sum(item.record_origin == "seed_sample" for item in items)
    non_live = len(items) - live
    if non_live:
        raise ValueError(
            f"real-only corpus contains {non_live} non-live records ({seed} seed_sample)"
        )
    if live < min_live_records:
        raise ValueError(
            f"real-only corpus has {live} pubmed_live records; minimum required is "
            f"{min_live_records}"
        )
    return live, seed


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a real PubMed corpus into runtime state.")
    parser.add_argument(
        "--per-query",
        type=int,
        default=10,
        help="Max records to fetch per query (1-50, NCBI hard cap 50).",
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help="Create/use an isolated real-only JSON runtime under this directory.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse an existing --runtime-root snapshot instead of refusing overwrite.",
    )
    parser.add_argument(
        "--min-live-records",
        type=int,
        default=100,
        help="With --runtime-root, fail if fewer live records exist after sync (default 100).",
    )
    parser.add_argument(
        "--queries-file",
        type=Path,
        help="JSON file containing a non-empty list of query strings; overrides DEFAULT_QUERIES.",
    )
    args = parser.parse_args()

    if args.runtime_root is not None:
        try:
            literature_path, chunk_path = prepare_isolated_runtime(
                args.runtime_root.resolve(), resume=args.resume
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Refused to prepare isolated runtime: {exc}")
            return 2
        os.environ["QIYAN_STATE_BACKEND"] = "json"
        os.environ["LITERATURE_RUNTIME_STATE_PATH"] = str(literature_path)
        os.environ["CHUNK_RUNTIME_STATE_PATH"] = str(chunk_path)

    # Imported lazily so --help works without importing the app stack.
    from app.repositories.runtime_storage import get_literature_repository
    from app.services.literature import sync_pubmed

    if args.queries_file is not None:
        raw_queries = json.loads(args.queries_file.read_text(encoding="utf-8"))
        if (
            not isinstance(raw_queries, list)
            or not raw_queries
            or not all(isinstance(q, str) and q.strip() for q in raw_queries)
        ):
            print("Refused to load queries-file: expected a non-empty JSON list of strings.")
            return 2
        queries = raw_queries
        print(f"Loaded {len(queries)} queries from {args.queries_file}.")
    else:
        queries = DEFAULT_QUERIES

    per_query = max(1, min(args.per_query, 50))
    total_created = 0
    total_updated = 0
    failed_queries: list[str] = []
    for query in queries:
        try:
            result = sync_pubmed(query, per_query)
        except Exception as exc:  # noqa: BLE001 - operator script, report and continue
            print(f"  ! '{query}' failed: {exc}")
            failed_queries.append(query)
            continue
        total_created += result.created
        total_updated += result.updated
        print(
            f"  '{query}': fetched={result.fetched} created={result.created} updated={result.updated}"
        )

    items = get_literature_repository().list_items()
    live = sum(1 for item in items if item.record_origin == "pubmed_live")
    seed = sum(1 for item in items if item.record_origin == "seed_sample")
    print(
        f"\nDone. created={total_created} updated={total_updated}. "
        f"Runtime corpus now: {len(items)} items ({live} pubmed_live, {seed} seed_sample)."
    )
    if args.runtime_root is not None:
        try:
            validate_real_only_corpus(items, min_live_records=max(0, args.min_live_records))
        except ValueError as exc:
            print(f"Validation snapshot rejected: {exc}")
            return 2
        if failed_queries:
            print(
                "Validation snapshot incomplete: PubMed sync failed for "
                + ", ".join(failed_queries)
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
