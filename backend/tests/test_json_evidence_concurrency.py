"""Independent repository instances must not lose each other's evidence writes."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, current_thread

import pytest

from app.repositories.chunk import InMemoryChunkRepository
from app.repositories.literature import InMemoryLiteratureRepository


@pytest.mark.parametrize("kind", ["literature", "chunks"])
def test_json_writers_share_one_file_lock_and_preserve_both_updates(tmp_path, monkeypatch, kind):
    data_path = tmp_path / f"{kind}.json"
    if kind == "literature":
        seed = Path(__file__).resolve().parents[1] / "data/literature/sample_ad_literature.json"
        data_path.write_bytes(seed.read_bytes())
        repositories = [InMemoryLiteratureRepository(data_path) for _ in range(2)]

        def update(index):
            return repositories[index].update_pdf_metadata(
                ["cn-ad-gbs-001", "pmid-40100001"][index], f"pdf-{index}", f"{index}.pdf", "pending"
            )

        def ids():
            return {
                item.pdf_upload_id for item in repositories[0].list_items() if item.pdf_upload_id
            }
    else:
        data_path.write_text("[]", encoding="utf-8")
        repositories = [InMemoryChunkRepository(data_path) for _ in range(2)]

        def update(index):
            return repositories[index].upsert_uploaded_pdf_chunk(
                f"chunk-{index}", f"lit-{index}", f"pdf-{index}", "test evidence", "quote", []
            )

        def ids():
            return {item.pdf_upload_id for item in repositories[0].list_chunks()}

    first_read = Event()
    second_finished = Event()
    read_text = Path.read_text
    first_thread = None

    def read_during_write(path, *args, **kwargs):
        result = read_text(path, *args, **kwargs)
        if path == data_path and current_thread() is first_thread:
            first_read.set()
            # With the lock, the second write waits. Without it, the second
            # commits before this stale snapshot resumes and is overwritten.
            second_finished.wait(timeout=0.3)
        return result

    monkeypatch.setattr(Path, "read_text", read_during_write)

    def first():
        nonlocal first_thread
        first_thread = current_thread()
        return update(0)

    def second():
        try:
            return update(1)
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        one = executor.submit(first)
        assert first_read.wait(timeout=3)
        two = executor.submit(second)
        assert one.result(timeout=5) is not None
        assert two.result(timeout=5) is not None
    assert ids() == {"pdf-0", "pdf-1"}
    assert isinstance(json.loads(data_path.read_text(encoding="utf-8")), list)


def test_failed_json_publication_preserves_readable_previous_state(tmp_path, monkeypatch):
    data_path = tmp_path / "chunks.json"
    data_path.write_text("[]\n", encoding="utf-8")
    repository = InMemoryChunkRepository(data_path)

    def fail_replace(_source, _destination):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic publication failure"):
        repository.upsert_uploaded_pdf_chunk("chunk-a", "lit-a", "pdf-a", "evidence", "quote", [])
    assert data_path.read_text(encoding="utf-8") == "[]\n"
    assert list(tmp_path.glob("*.tmp")) == []
