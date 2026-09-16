"""Parametrized tests that exercise both JSON and SQLite literature backends.

Run with:
    pytest tests/test_literature_repository_backends.py          # json only (default)
    QIYAN_STATE_BACKEND=sqlite pytest tests/test_literature_repository_backends.py  # sqlite only

Or run both at once:
    pytest tests/test_literature_repository_backends.py -k "json or sqlite"
"""

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from app.repositories.literature import InMemoryLiteratureRepository
from app.repositories.protocols import LiteratureRepository
from app.repositories.runtime_storage import (
    clear_literature_repository_cache,
    get_literature_repository,
)
from app.repositories.sqlite_literature import SqliteLiteratureRepository

# ── Minimal seed data ──────────────────────────────────────────────────

SEED_ITEMS: list[dict[str, Any]] = [
    {
        "id": "cn-ad-gbs-001",
        "title": "肠-脑-皮肤轴与特应性皮炎中医证候研究",
        "language": "zh",
        "source_type": "cn_literature",
        "source": "CNKI curated AD sample",
        "year": 2025,
        "snippet": "围绕特应性皮炎、肠-脑-皮肤轴与中医证候关联进行综述。",
        "authors": ["王琳", "张倩"],
        "keywords": ["特应性皮炎", "肠-脑-皮肤轴"],
        "evidence_tags": ["gut_skin_axis", "tcm_syndrome"],
        "abstract": "文章从肠-脑-皮肤轴视角讨论特应性皮炎的中医证候演变。",
        "citation_url": "https://example.org/cnki/cn-ad-gbs-001",
    },
    {
        "id": "pmid-40100001",
        "title": "Atopic dermatitis, skin barrier dysfunction, and immune pathways",
        "language": "en",
        "source_type": "pubmed",
        "source": "PubMed curated AD sample",
        "year": 2024,
        "snippet": "Reviewing barrier disruption, Th2 skewing, and epithelial cytokines.",
        "authors": ["Emily Carter", "Jason Lee"],
        "keywords": ["atopic dermatitis", "skin barrier", "Th2"],
        "evidence_tags": ["skin_barrier", "immune_pathway", "review"],
        "abstract": "This review summarizes how barrier disruption and type 2 inflammation interact.",
        "pubmed_id": "40100001",
        "doi": "10.1000/ad.2024.001",
        "citation_url": "https://pubmed.ncbi.nlm.nih.gov/40100001/",
    },
]


def _write_json_seed(path: Path) -> None:
    """Write SEED_ITEMS to a JSON file for InMemoryLiteratureRepository."""
    path.write_text(json.dumps(SEED_ITEMS, ensure_ascii=False), encoding="utf-8")


def _make_json_repo(path: Path) -> InMemoryLiteratureRepository:
    _write_json_seed(path)
    return InMemoryLiteratureRepository(path)


def _make_sqlite_repo(db_path: Path) -> SqliteLiteratureRepository:
    """Create a SqliteLiteratureRepository, bootstrapping from SEED_ITEMS."""
    seed_path = db_path.parent / "literature_state.json"
    _write_json_seed(seed_path)
    return SqliteLiteratureRepository(db_path, seed_path=seed_path)


# ── Parametrized fixture ──────────────────────────────────────────────

_BACKEND_FACTORIES = {
    "json": lambda tmp: _make_json_repo(tmp / "literature_state.json"),
    "sqlite": lambda tmp: _make_sqlite_repo(tmp / "backend_test.sqlite3"),
}


@pytest.fixture(params=["json", "sqlite"], ids=["json", "sqlite"])
def repo(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[LiteratureRepository]:
    """Yield a LiteratureRepository for both backends; close SQLite on teardown."""
    factory = _BACKEND_FACTORIES[request.param]
    instance = factory(tmp_path)
    yield instance
    close = getattr(instance, "close", None)
    if callable(close):
        close()


# ── Tests ─────────────────────────────────────────────────────────────


class TestListItems:
    def test_returns_all_seed_items(self, repo: LiteratureRepository) -> None:
        items = repo.list_items()
        assert len(items) == 2

    def test_ids_match_seed(self, repo: LiteratureRepository) -> None:
        ids = {item.id for item in repo.list_items()}
        assert ids == {"cn-ad-gbs-001", "pmid-40100001"}


class TestGetItemById:
    def test_found(self, repo: LiteratureRepository) -> None:
        item = repo.get_item_by_id("cn-ad-gbs-001")
        assert item is not None
        assert item.title == "肠-脑-皮肤轴与特应性皮炎中医证候研究"

    def test_not_found(self, repo: LiteratureRepository) -> None:
        assert repo.get_item_by_id("nonexistent") is None


class TestUpdatePdfMetadata:
    def test_write_and_read_back(self, repo: LiteratureRepository) -> None:
        result = repo.update_pdf_metadata(
            literature_id="cn-ad-gbs-001",
            pdf_upload_id="pdf-cn-ad-gbs-001-test-pdf",
            pdf_file_name="test.pdf",
            pdf_parse_status="pending",
        )
        assert result is not None
        assert result.pdf_upload_id == "pdf-cn-ad-gbs-001-test-pdf"
        assert result.pdf_file_name == "test.pdf"
        assert result.pdf_parse_status == "pending"
        assert result.parse_attempt_count == 0

        # Verify persistence via get_item_by_id
        again = repo.get_item_by_id("cn-ad-gbs-001")
        assert again is not None
        assert again.pdf_upload_id == "pdf-cn-ad-gbs-001-test-pdf"

    def test_nonexistent_id_returns_none(self, repo: LiteratureRepository) -> None:
        assert repo.update_pdf_metadata("no-such-id", "x", "y", "pending") is None


class TestUpdatePdfParseStatus:
    def test_replaced_upload_rejects_stale_parse_without_incrementing_counter(self, repo):
        repo.update_pdf_metadata("cn-ad-gbs-001", "pdf-old", "same.pdf", "pending")
        repo.update_pdf_metadata("cn-ad-gbs-001", "pdf-new", "same.pdf", "pending")
        assert (
            repo.update_pdf_parse_status(
                "cn-ad-gbs-001", "parsed", expected_pdf_upload_id="pdf-old"
            )
            is None
        )
        current = repo.get_item_by_id("cn-ad-gbs-001")
        assert current.pdf_upload_id == "pdf-new"
        assert current.pdf_parse_status == "pending"
        assert current.parse_attempt_count == 0

    def test_sqlite_compare_and_set_checks_the_upload_again_at_write_time(self, tmp_path):
        first = _make_sqlite_repo(tmp_path / "parse-race.sqlite3")
        second = SqliteLiteratureRepository(tmp_path / "parse-race.sqlite3")
        first.update_pdf_metadata("cn-ad-gbs-001", "pdf-old", "same.pdf", "pending")
        connection = first._conn

        class InterleavedConnection:
            def execute(self, sql, parameters=()):
                cursor = connection.execute(sql, parameters)
                if sql.startswith("SELECT pdf_upload_id, pdf_file_name"):
                    old_row = cursor.fetchone()
                    second.update_pdf_metadata("cn-ad-gbs-001", "pdf-new", "same.pdf", "pending")

                    class OldSnapshot:
                        def fetchone(self):
                            return old_row

                    return OldSnapshot()
                return cursor

            def __getattr__(self, name):
                return getattr(connection, name)

        first._conn = InterleavedConnection()
        try:
            assert (
                first.update_pdf_parse_status(
                    "cn-ad-gbs-001", "parsed", expected_pdf_upload_id="pdf-old"
                )
                is None
            )
            current = second.get_item_by_id("cn-ad-gbs-001")
            assert current.pdf_upload_id == "pdf-new"
            assert current.pdf_parse_status == "pending"
            assert current.parse_attempt_count == 0
        finally:
            first.close()
            second.close()

    def test_counter_increments(self, repo: LiteratureRepository) -> None:
        # First attach PDF metadata
        repo.update_pdf_metadata("pmid-40100001", "pdf-pmid-40100001-paper", "paper.pdf", "pending")

        # First parse
        r1 = repo.update_pdf_parse_status(
            "pmid-40100001",
            "parsed",
            pdf_parse_message="ok",
            pdf_parse_started_at="2025-01-01T00:00:00",
            pdf_parse_finished_at="2025-01-01T00:01:00",
            last_parse_trigger="manual",
        )
        assert r1 is not None
        assert r1.pdf_parse_status == "parsed"
        assert r1.parse_attempt_count == 1

        # Second parse
        r2 = repo.update_pdf_parse_status(
            "pmid-40100001",
            "failed",
            pdf_parse_message="error",
            last_parse_trigger="auto",
        )
        assert r2 is not None
        assert r2.parse_attempt_count == 2

    def test_missing_pdf_metadata_returns_none(self, repo: LiteratureRepository) -> None:
        # Item exists but has no pdf_upload_id / pdf_file_name
        assert repo.update_pdf_parse_status("cn-ad-gbs-001", "parsed") is None


class TestBulkUpsertPubmedItems:
    def test_create_new_item(self, repo: LiteratureRepository) -> None:
        incoming = [
            {
                "id": "pmid-39000003",
                "title": "JAK inhibitors in AD",
                "language": "en",
                "source_type": "pubmed",
                "source": "PubMed live sync",
                "year": 2025,
                "snippet": "JAK inhibitors review",
                "abstract": "A systematic review.",
                "authors": ["Liu Wei"],
                "keywords": ["JAK", "atopic dermatitis"],
                "pubmed_id": "39000003",
                "doi": "10.1000/ad.2025.003",
                "citation_url": "https://pubmed.ncbi.nlm.nih.gov/39000003/",
            },
        ]
        created, updated = repo.bulk_upsert_pubmed_items(incoming)
        assert created == 1
        assert updated == 0
        item = repo.get_item_by_id("pmid-39000003")
        assert item is not None
        assert item.title == "JAK inhibitors in AD"

    def test_update_preserves_pdf_fields(self, repo: LiteratureRepository) -> None:
        # Attach PDF metadata first
        repo.update_pdf_metadata(
            "pmid-40100001",
            "pdf-pmid-40100001-paper",
            "paper.pdf",
            "parsed",
        )
        repo.update_pdf_parse_status(
            "pmid-40100001",
            "parsed",
            pdf_parse_message="ok",
            last_parse_trigger="manual",
        )

        # Now upsert with refreshed PubMed data
        incoming = [
            {
                "id": "pmid-40100001",
                "title": "Updated title",
                "language": "en",
                "source_type": "pubmed",
                "source": "PubMed live sync",
                "year": 2025,
                "snippet": "Updated snippet",
                "abstract": "Updated abstract",
                "authors": ["New Author"],
                "keywords": ["updated"],
                "pubmed_id": "40100001",
                "doi": "10.1000/ad.2024.001",
                "citation_url": "https://pubmed.ncbi.nlm.nih.gov/40100001/",
            },
        ]
        created, updated = repo.bulk_upsert_pubmed_items(incoming)
        assert created == 0
        assert updated == 1

        item = repo.get_item_by_id("pmid-40100001")
        assert item is not None
        # PubMed fields updated
        assert item.title == "Updated title"
        assert item.year == 2025
        # PDF fields preserved
        assert item.pdf_upload_id == "pdf-pmid-40100001-paper"
        assert item.pdf_file_name == "paper.pdf"
        assert item.pdf_parse_status == "parsed"

    def test_sqlite_rolls_back_the_whole_batch_when_one_item_is_invalid(
        self, tmp_path: Path
    ) -> None:
        sqlite_repo = _make_sqlite_repo(tmp_path / "rollback.sqlite3")
        valid_item = {
            "id": "pmid-rollback-001",
            "title": "Must not survive failed batch",
            "language": "en",
            "source_type": "pubmed",
            "source": "PubMed live sync",
            "year": 2025,
            "snippet": "rollback test",
        }

        try:
            with pytest.raises(KeyError):
                sqlite_repo.bulk_upsert_pubmed_items([valid_item, {"title": "missing id"}])

            assert sqlite_repo.get_item_by_id("pmid-rollback-001") is None
            sqlite_repo.update_pdf_metadata(
                "cn-ad-gbs-001",
                "pdf-cn-ad-gbs-001-after-rollback",
                "after-rollback.pdf",
                "pending",
            )
            assert sqlite_repo.get_item_by_id("pmid-rollback-001") is None
        finally:
            sqlite_repo.close()

    def test_sqlite_shared_connection_accepts_concurrent_upserts_without_data_loss(
        self, tmp_path: Path
    ) -> None:
        sqlite_repo = _make_sqlite_repo(tmp_path / "concurrent.sqlite3")
        worker_count = 8
        records_per_worker = 20
        start = Barrier(worker_count)

        def write_records(worker_id: int) -> None:
            start.wait()
            for record_id in range(records_per_worker):
                suffix = f"{worker_id:02d}{record_id:02d}"
                sqlite_repo.bulk_upsert_pubmed_items(
                    [
                        {
                            "id": f"pmid-concurrent-{suffix}",
                            "title": f"Concurrent literature {suffix}",
                            "language": "en",
                            "source_type": "pubmed",
                            "source": "PubMed live sync",
                            "year": 2025,
                            "snippet": "Concurrent write test",
                            "authors": ["Test Author"],
                            "keywords": ["concurrency"],
                            "pubmed_id": suffix,
                        }
                    ]
                )

        try:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(write_records, worker_id) for worker_id in range(worker_count)
                ]
                for future in futures:
                    future.result()

            concurrent_items = [
                item for item in sqlite_repo.list_items() if item.id.startswith("pmid-concurrent-")
            ]
            assert len(concurrent_items) == worker_count * records_per_worker
        finally:
            sqlite_repo.close()


# ── Factory / Protocol tests ──────────────────────────────────────────


class TestGetLiteratureRepository:
    def test_json_backend_returns_in_memory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        json_path = tmp_path / "literature_state.json"
        _write_json_seed(json_path)
        monkeypatch.setenv("LITERATURE_RUNTIME_STATE_PATH", str(json_path))
        monkeypatch.setenv("QIYAN_STATE_BACKEND", "json")
        clear_literature_repository_cache()

        repo = get_literature_repository()
        assert isinstance(repo, InMemoryLiteratureRepository)

    def test_sqlite_backend_returns_sqlite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        json_path = tmp_path / "literature_state.json"
        _write_json_seed(json_path)
        db_path = tmp_path / "test.sqlite3"
        monkeypatch.setenv("LITERATURE_RUNTIME_STATE_PATH", str(json_path))
        monkeypatch.setenv("QIYAN_STATE_BACKEND", "sqlite")
        monkeypatch.setenv("QIYAN_SQLITE_DB_PATH", str(db_path))
        clear_literature_repository_cache()

        repo = get_literature_repository()
        assert isinstance(repo, SqliteLiteratureRepository)

    def test_cache_is_reused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        json_path = tmp_path / "literature_state.json"
        _write_json_seed(json_path)
        monkeypatch.setenv("LITERATURE_RUNTIME_STATE_PATH", str(json_path))
        monkeypatch.setenv("QIYAN_STATE_BACKEND", "json")
        clear_literature_repository_cache()

        repo1 = get_literature_repository()
        repo2 = get_literature_repository()
        assert repo1 is repo2

    def test_cache_invalidated_on_backend_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        json_path = tmp_path / "literature_state.json"
        _write_json_seed(json_path)
        db_path = tmp_path / "test.sqlite3"
        monkeypatch.setenv("LITERATURE_RUNTIME_STATE_PATH", str(json_path))
        monkeypatch.setenv("QIYAN_SQLITE_DB_PATH", str(db_path))

        monkeypatch.setenv("QIYAN_STATE_BACKEND", "json")
        clear_literature_repository_cache()
        repo_json = get_literature_repository()
        assert isinstance(repo_json, InMemoryLiteratureRepository)

        monkeypatch.setenv("QIYAN_STATE_BACKEND", "sqlite")
        clear_literature_repository_cache()
        repo_sqlite = get_literature_repository()
        assert isinstance(repo_sqlite, SqliteLiteratureRepository)

    def test_clear_cache_resets(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        json_path = tmp_path / "literature_state.json"
        _write_json_seed(json_path)
        monkeypatch.setenv("LITERATURE_RUNTIME_STATE_PATH", str(json_path))
        monkeypatch.setenv("QIYAN_STATE_BACKEND", "json")
        clear_literature_repository_cache()

        repo1 = get_literature_repository()
        clear_literature_repository_cache()
        repo2 = get_literature_repository()
        assert repo1 is not repo2
