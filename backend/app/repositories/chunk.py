import json
from pathlib import Path
from typing import Any

from app.core.file_storage import atomic_write_text, path_lock
from app.schemas.chunk import LiteratureChunk


class InMemoryChunkRepository:
    def __init__(self, data_path: Path):
        self.data_path = data_path
        self._lock = path_lock(data_path)

    def list_chunks(self) -> list[LiteratureChunk]:
        with self._lock:
            raw_items: list[dict[str, Any]] = json.loads(self.data_path.read_text(encoding="utf-8"))
            return [LiteratureChunk(**item) for item in raw_items]

    def list_chunks_by_literature_id(self, literature_id: str) -> list[LiteratureChunk]:
        with self._lock:
            return [chunk for chunk in self.list_chunks() if chunk.literature_id == literature_id]

    def get_chunk_by_id(self, chunk_id: str) -> LiteratureChunk | None:
        with self._lock:
            for chunk in self.list_chunks():
                if chunk.chunk_id == chunk_id:
                    return chunk
            return None

    def upsert_uploaded_pdf_chunk(
        self,
        chunk_id: str,
        literature_id: str,
        pdf_upload_id: str,
        text: str,
        source_quote: str,
        evidence_tags: list[str],
        related_entity_ids: list[str] | None = None,
    ) -> LiteratureChunk:
        with self._lock:
            raw_items: list[dict[str, Any]] = json.loads(self.data_path.read_text(encoding="utf-8"))
            next_item: dict[str, Any] = {
                "chunk_id": chunk_id,
                "literature_id": literature_id,
                "section": "uploaded_pdf",
                "text": text,
                "source_quote": source_quote,
                "evidence_tags": evidence_tags,
                "related_entity_ids": related_entity_ids or ["disease:atopic-dermatitis"],
                "source_type": "uploaded_pdf",
                "pdf_upload_id": pdf_upload_id,
            }

            for index, item in enumerate(raw_items):
                if item.get("chunk_id") == chunk_id:
                    raw_items[index] = next_item
                    atomic_write_text(
                        self.data_path,
                        json.dumps(raw_items, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    return LiteratureChunk(**next_item)

            raw_items.append(next_item)
            atomic_write_text(
                self.data_path,
                json.dumps(raw_items, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return LiteratureChunk(**next_item)
