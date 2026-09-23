"""Benchmark JSON / SQLite runtime storage backends.

Examples:
    python -m scripts.benchmark_storage_backends --backend json
    python -m scripts.benchmark_storage_backends --backend sqlite
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.repositories.chunk import InMemoryChunkRepository
from app.repositories.literature import InMemoryLiteratureRepository
from app.repositories.protocols import ChunkRepository, LiteratureRepository
from app.repositories.sqlite_chunk import SqliteChunkRepository
from app.repositories.sqlite_literature import SqliteLiteratureRepository
from app.schemas.eval import load_rag_eval_dataset
from app.services.llm.provider import DEFAULT_PROVIDER_NAME
from app.services.rag import answer_question

BackendName = Literal["json", "sqlite"]

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SEED_LITERATURE_PATH = _BACKEND_ROOT / "data" / "literature" / "sample_ad_literature.json"
_SEED_CHUNK_PATH = _BACKEND_ROOT / "data" / "literature" / "sample_ad_chunks.json"
_EVAL_DATA_PATH = _BACKEND_ROOT / "data" / "evals" / "rag_ad_eval_questions.json"


@dataclass(frozen=True)
class Measurement:
    scenario: str
    iterations: int
    total_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass
class BackendContext:
    literature: LiteratureRepository
    chunks: ChunkRepository
    close_callbacks: list[Callable[[], None]]

    def close(self) -> None:
        for callback in reversed(self.close_callbacks):
            callback()


def _copy_seed_files(target_dir: Path) -> tuple[Path, Path]:
    literature_path = target_dir / "literature_state.json"
    chunk_path = target_dir / "chunk_state.json"
    shutil.copyfile(_SEED_LITERATURE_PATH, literature_path)
    shutil.copyfile(_SEED_CHUNK_PATH, chunk_path)
    return literature_path, chunk_path


@contextmanager
def _backend_context(
    backend: BackendName,
) -> Iterator[BackendContext]:
    with tempfile.TemporaryDirectory(prefix=f"qiyan-{backend}-bench-") as tmp_raw:
        tmp = Path(tmp_raw)
        literature_seed, chunk_seed = _copy_seed_files(tmp)
        close_callbacks: list[Callable[[], None]] = []

        os.environ["QIYAN_LLM_PROVIDER"] = DEFAULT_PROVIDER_NAME
        os.environ["QIYAN_RETRIEVAL_PROVIDER"] = "keyword"
        os.environ["QIYAN_STATE_BACKEND"] = backend

        if backend == "json":
            context = BackendContext(
                literature=InMemoryLiteratureRepository(literature_seed),
                chunks=InMemoryChunkRepository(chunk_seed),
                close_callbacks=close_callbacks,
            )
        elif backend == "sqlite":
            sqlite_path = tmp / "qiyan_state.sqlite3"
            context = BackendContext(
                literature=SqliteLiteratureRepository(sqlite_path, seed_path=literature_seed),
                chunks=SqliteChunkRepository(sqlite_path, seed_path=chunk_seed),
                close_callbacks=close_callbacks,
            )
            close_callbacks.extend(
                [
                    lambda: (
                        context.chunks.close()
                        if isinstance(context.chunks, SqliteChunkRepository)
                        else None
                    ),
                    lambda: (
                        context.literature.close()
                        if isinstance(context.literature, SqliteLiteratureRepository)
                        else None
                    ),
                ]
            )
        try:
            yield context
        finally:
            context.close()


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(max(math.ceil(len(ordered) * quantile) - 1, 0), len(ordered) - 1)
    return ordered[index]


def _measure(scenario: str, iterations: int, func: Callable[[], None]) -> Measurement:
    durations: list[float] = []
    started = time.perf_counter()
    for _ in range(iterations):
        tick = time.perf_counter()
        func()
        durations.append((time.perf_counter() - tick) * 1000)
    total_ms = (time.perf_counter() - started) * 1000
    return Measurement(
        scenario=scenario,
        iterations=iterations,
        total_ms=round(total_ms, 3),
        p50_ms=round(_percentile(durations, 0.50), 3),
        p95_ms=round(_percentile(durations, 0.95), 3),
        p99_ms=round(_percentile(durations, 0.99), 3),
    )


def _pubmed_item(index: int) -> dict[str, Any]:
    return {
        "id": f"pmid-bench-{index:05d}",
        "title": f"Benchmark PubMed item {index}",
        "language": "en",
        "source_type": "pubmed",
        "source": "PubMed benchmark seed",
        "year": 2026,
        "snippet": "Benchmark item for storage latency measurement.",
        "abstract": "Atopic dermatitis benchmark abstract.",
        "authors": ["Benchmark Author"],
        "keywords": ["atopic dermatitis", "benchmark"],
        "evidence_tags": ["benchmark"],
        "pubmed_id": f"99{index:06d}",
        "doi": f"10.1000/bench.{index}",
        "citation_url": f"https://pubmed.ncbi.nlm.nih.gov/99{index:06d}/",
    }


def _run_backend_benchmark(
    backend: BackendName,
    *,
    iterations: int,
    rag_runs: int,
) -> list[Measurement]:
    with _backend_context(backend) as context:
        literature = context.literature
        chunks = context.chunks
        questions = load_rag_eval_dataset(_EVAL_DATA_PATH)

        # Force lazy bootstrap before measuring.
        literature.list_items()
        chunks.list_chunks()

        def rag_eval_50q() -> None:
            for question in questions:
                answer_question(
                    question.question,
                    source=question.source_preference,
                    top_k=3,
                    llm_provider_name=DEFAULT_PROVIDER_NAME,
                    retrieval_provider_name="keyword",
                    literature_repository=literature,
                    chunk_repository=chunks,
                )

        single_insert_index = 0

        def single_literature_insert() -> None:
            nonlocal single_insert_index
            single_insert_index += 1
            literature.bulk_upsert_pubmed_items([_pubmed_item(single_insert_index)])

        bulk_10_index = 0

        def bulk_chunk_10() -> None:
            nonlocal bulk_10_index
            bulk_10_index += 1
            _upsert_chunks(chunks, batch_index=bulk_10_index, size=10)

        bulk_50_index = 0

        def bulk_chunk_50() -> None:
            nonlocal bulk_50_index
            bulk_50_index += 1
            _upsert_chunks(chunks, batch_index=bulk_50_index, size=50)

        def get_literature_by_id() -> None:
            literature.get_item_by_id("cn-ad-gbs-001")

        def list_chunks_by_literature_id() -> None:
            chunks.list_chunks_by_literature_id("cn-ad-gbs-001")

        return [
            _measure("rag_eval_50q_keyword", rag_runs, rag_eval_50q),
            _measure("single_literature_insert", iterations, single_literature_insert),
            _measure("bulk_chunk_insert_10", iterations, bulk_chunk_10),
            _measure("bulk_chunk_insert_50", iterations, bulk_chunk_50),
            _measure("get_literature_by_id", iterations, get_literature_by_id),
            _measure("list_chunks_by_literature_id", iterations, list_chunks_by_literature_id),
        ]


def _upsert_chunks(chunks: ChunkRepository, *, batch_index: int, size: int) -> None:
    for index in range(size):
        chunk_id = f"chunk-bench-{size}-{batch_index:05d}-{index:03d}"
        chunks.upsert_uploaded_pdf_chunk(
            chunk_id=chunk_id,
            literature_id="cn-ad-gbs-001",
            pdf_upload_id=f"pdf-bench-{size}-{batch_index:05d}",
            text="Benchmark uploaded PDF chunk for atopic dermatitis retrieval.",
            source_quote="Benchmark uploaded PDF chunk",
            evidence_tags=["benchmark", "uploaded_pdf"],
            related_entity_ids=["disease:atopic-dermatitis"],
        )


def _print_markdown(results: dict[str, list[Measurement]]) -> None:
    print("| Backend | Scenario | Iterations | p50 ms | p95 ms | p99 ms | total ms |")
    print("|---|---|---:|---:|---:|---:|---:|")
    for backend, measurements in results.items():
        for measurement in measurements:
            print(
                "| "
                f"{backend} | {measurement.scenario} | {measurement.iterations} | "
                f"{measurement.p50_ms:.3f} | {measurement.p95_ms:.3f} | "
                f"{measurement.p99_ms:.3f} | {measurement.total_ms:.3f} |"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=["json", "sqlite", "all"],
        default="all",
        help="storage backend to benchmark",
    )
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--rag-runs", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    backends: list[BackendName]
    if args.backend == "all":
        backends = ["json", "sqlite"]
    else:
        backends = [args.backend]

    results: dict[str, list[Measurement]] = {}
    failures: dict[str, str] = {}
    for backend in backends:
        try:
            results[backend] = _run_backend_benchmark(
                backend,
                iterations=args.iterations,
                rag_runs=args.rag_runs,
            )
        except Exception as exc:
            failures[backend] = f"{type(exc).__name__}: {exc}"

    if args.json:
        payload = {
            "results": {
                backend: [measurement.__dict__ for measurement in measurements]
                for backend, measurements in results.items()
            },
            "failures": failures,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_markdown(results)
        if failures:
            print("\nFailures:")
            for backend, message in failures.items():
                print(f"- {backend}: {message}")

    return 1 if failures and not results else 0


if __name__ == "__main__":
    raise SystemExit(main())
