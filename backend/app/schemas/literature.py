from typing import Literal

from pydantic import BaseModel, Field

LiteratureSource = Literal["all", "cn_literature", "pubmed"]
LiteratureSearchSort = Literal["relevance", "year_desc", "year_asc"]
LiteratureRecordOrigin = Literal["seed_sample", "pubmed_live"]


class PdfParseResult(BaseModel):
    file_name: str
    storage_path: str
    file_size: int
    preview_text: str
    extraction_method: str
    quality_warning: str | None = None


class LiteratureItem(BaseModel):
    id: str
    title: str
    language: str
    source_type: str
    source: str
    record_origin: LiteratureRecordOrigin = "seed_sample"
    year: int
    snippet: str
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    evidence_tags: list[str] = Field(default_factory=list)
    abstract: str | None = None
    citation_url: str | None = None
    pubmed_id: str | None = None
    doi: str | None = None
    pdf_upload_id: str | None = None
    pdf_file_name: str | None = None
    pdf_parse_status: str | None = None
    pdf_parse_message: str | None = None
    pdf_parse_started_at: str | None = None
    pdf_parse_finished_at: str | None = None
    pdf_parse_result: PdfParseResult | None = None
    last_parse_trigger: Literal["auto", "manual"] | None = None
    parse_attempt_count: int | None = None
    related_entity_ids: list[str] = Field(default_factory=list)


class LiteratureSearchResponse(BaseModel):
    query: str
    source: LiteratureSource
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: LiteratureSearchSort
    items: list[LiteratureItem]


class PdfMetadataUploadRequest(BaseModel):
    literature_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    source_type: Literal["uploaded_pdf", "user_pdf"]


class PdfParseStatusUpdateRequest(BaseModel):
    literature_id: str = Field(min_length=1)
    pdf_parse_status: Literal["parsed", "failed"]
    pdf_upload_id: str | None = Field(default=None, min_length=1, max_length=104)


class LiteratureSyncRequest(BaseModel):
    source: Literal["pubmed"]
    q: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=50)


class LiteratureSyncResponse(BaseModel):
    source: Literal["pubmed"]
    query: str
    fetched: int
    created: int
    updated: int
    items: list[LiteratureItem]
