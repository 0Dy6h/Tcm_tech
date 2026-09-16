import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfReader

from app.repositories.runtime_storage import get_literature_repository
from app.schemas.literature import (
    LiteratureItem,
    LiteratureSearchResponse,
    LiteratureSearchSort,
    LiteratureSource,
    LiteratureSyncResponse,
    PdfParseResult,
)
from app.services.pdf_storage import resolve_stored_pdf_path
from app.services.pubmed import PubmedClient, PubmedFetcher, PubmedRecord

_PDF_PARSE_RESULT_FALLBACK_PREVIEW = (
    "已读取上传 PDF 文件，当前提供文件级解析预览；正文抽取将在后续接入。"
)
_PDF_TEXT_QUALITY_WARNING = "检测到抽取文本可能存在数字或表格乱码，请对照原始 PDF 核对关键数值。"
_PDF_BODY_SIGNALS = (
    "摘要",
    "目的",
    "方法",
    "结果",
    "结论",
    "特应性皮炎",
    "异位性皮炎",
    "atopic dermatitis",
    "methods",
    "results",
    "conclusion",
    "skin barrier",
)
_PDF_HEADER_FOOTER_PATTERNS = (
    re.compile(r"^\s*\d+\s*$"),
    re.compile(r"^\s*第\s*\d+\s*(卷|期|页)\s*$"),
    re.compile(r"^\s*(参考文献|references)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\[\d+\]"),
)

_REPOSITORY = get_literature_repository()
DEFAULT_SEARCH_PAGE_SIZE = 10
MAX_SEARCH_PAGE_SIZE = 50

_SEARCH_ALIASES = {
    "disease": ["特应性皮炎", "atopic dermatitis", "atopic", "dermatitis", "ad"],
    "gut_skin_axis": [
        "肠",
        "肠道",
        "肠道菌群",
        "肠-脑-皮肤轴",
        "gut",
        "gut-skin",
        "microbiome",
        "菌群",
    ],
    "skin_barrier": ["屏障", "皮肤屏障", "barrier", "filaggrin", "ceramide"],
    "immune": ["免疫", "炎症", "inflammation", "immune", "th2", "jak", "cytokine"],
    "pruritus": ["瘙痒", "itch", "itching", "il-31", "pruritus"],
    "formula": ["复方", "方剂", "中药", "formula", "herbal", "消风散"],
    "network": ["网络药理学", "靶点", "通路", "network pharmacology", "target", "pathway"],
    "pediatric": ["儿童", "pediatric", "children"],
}
_DISEASE_TERMS = {term.lower() for term in _SEARCH_ALIASES["disease"]}


def _english_term_matches(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _keyword_in_text(text: str, keyword: str) -> bool:
    keyword = keyword.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9\-]*", keyword):
        return _english_term_matches(text, keyword)
    return keyword in text


def tokenize_search_query(query: str) -> list[str]:
    normalized = query.lower().strip()
    terms = set(re.findall(r"[a-z0-9][a-z0-9\-]*", normalized))
    terms.update(re.findall(r"[\u4e00-\u9fff]+", normalized))

    for alias_terms in _SEARCH_ALIASES.values():
        if any(_keyword_in_text(normalized, keyword) for keyword in alias_terms):
            terms.update(alias_terms)

    return sorted((term for term in terms if term), key=lambda term: (-len(term), term))


def _is_broad_disease_query(query_terms: list[str]) -> bool:
    return bool(query_terms) and all(term.lower() in _DISEASE_TERMS for term in query_terms)


def _build_search_haystacks(item: LiteratureItem) -> list[tuple[str, int]]:
    evidence_tags = " ".join(
        item.evidence_tags + [tag.replace("_", " ") for tag in item.evidence_tags]
    )
    return [
        (item.title.lower(), 4),
        (" ".join(item.keywords).lower(), 3),
        (evidence_tags.lower(), 2),
        (item.snippet.lower(), 2),
        ((item.abstract or "").lower(), 1),
        (" ".join(item.authors).lower(), 1),
    ]


def score_literature_item(item: LiteratureItem, query_terms: list[str]) -> int:
    score = 0
    for haystack, weight in _build_search_haystacks(item):
        if not haystack:
            continue
        for term in query_terms:
            if _keyword_in_text(haystack, term):
                score += weight
    return score


def _sort_scored_items(
    scored_items: list[tuple[int, int, int, LiteratureItem]],
    sort: LiteratureSearchSort,
    is_broad_disease_query: bool,
) -> list[LiteratureItem]:
    if sort == "year_desc":
        scored_items.sort(key=lambda row: (row[3].year, row[0], row[1], -row[2]), reverse=True)
    elif sort == "year_asc":
        scored_items.sort(key=lambda row: (row[3].year, -row[0], -row[1], row[2]))
    elif is_broad_disease_query:
        scored_items.sort(key=lambda row: (row[1], -row[2]), reverse=True)
    else:
        scored_items.sort(key=lambda row: (row[1], row[0], row[3].year, -row[2]), reverse=True)
    return [item for _, _, _, item in scored_items]


def detect_query_language(query: str) -> str:
    for char in query:
        if "\u4e00" <= char <= "\u9fff":
            return "zh"
    return "en"


def search_literature(
    query: str,
    source: LiteratureSource = "all",
    page: int = 1,
    page_size: int = DEFAULT_SEARCH_PAGE_SIZE,
    sort: LiteratureSearchSort = "relevance",
    has_pdf_upload: bool | None = None,
) -> LiteratureSearchResponse:
    normalized_query = query.strip()
    query_language = detect_query_language(normalized_query)
    preferred_source_type = "cn_literature" if query_language == "zh" else "pubmed"
    query_terms = tokenize_search_query(normalized_query)
    items = _REPOSITORY.list_items()
    if source != "all":
        items = [item for item in items if item.source_type == source]
    if has_pdf_upload is True:
        items = [item for item in items if item.pdf_upload_id]
    elif has_pdf_upload is False:
        items = [item for item in items if not item.pdf_upload_id]
    scored_items = [
        (score, 1 if item.source_type == preferred_source_type else 0, index, item)
        for index, item in enumerate(items)
        if (score := score_literature_item(item, query_terms)) > 0
    ]
    items = _sort_scored_items(scored_items, sort, _is_broad_disease_query(query_terms))
    total = len(items)
    normalized_page = max(page, 1)
    normalized_page_size = min(max(page_size, 1), MAX_SEARCH_PAGE_SIZE)
    start = (normalized_page - 1) * normalized_page_size
    end = start + normalized_page_size
    paged_items = items[start:end]
    total_pages = (total + normalized_page_size - 1) // normalized_page_size if total else 0
    return LiteratureSearchResponse(
        query=normalized_query,
        source=source,
        page=normalized_page,
        page_size=normalized_page_size,
        total=total,
        total_pages=total_pages,
        sort=sort,
        items=paged_items,
    )


def get_literature_item(item_id: str) -> LiteratureItem | None:
    return _REPOSITORY.get_item_by_id(item_id)


def build_pdf_upload_id(
    literature_id: str, file_name: str, *, content_sha256: str | None = None
) -> str:
    if content_sha256 is not None:
        # Include the exact filename and literature identity, not their lossy
        # slugs. Old citations retain their file when a paper is uploaded again.
        binding = json.dumps([literature_id, file_name, content_sha256], ensure_ascii=False)
        return f"pdf-{hashlib.sha256(binding.encode('utf-8')).hexdigest()}"
    slug = re.sub(r"[^a-z0-9]+", "-", file_name.lower()).strip("-")
    # When the slug collapses to empty or the bare extension (typical for
    # pure-CJK filenames), fold a short content-addressed digest of the original
    # file_name into the slug so two distinct Chinese uploads on the same
    # literature_id do not produce the same upload_id (and thus overwrite each
    # other on disk + in runtime state).
    if not slug or slug == "pdf":
        digest = hashlib.sha1(file_name.encode("utf-8")).hexdigest()[:8]
        slug = f"pdf-{digest}"
    upload_id = f"pdf-{literature_id}-{slug}"
    if len(upload_id) > 104:
        binding = json.dumps([literature_id, file_name], ensure_ascii=False)
        return f"pdf-{hashlib.sha256(binding.encode('utf-8')).hexdigest()}"
    return upload_id


def attach_pdf_metadata(
    literature_id: str, file_name: str, *, pdf_upload_id: str | None = None
) -> LiteratureItem | None:
    return _REPOSITORY.update_pdf_metadata(
        literature_id=literature_id,
        pdf_upload_id=pdf_upload_id or build_pdf_upload_id(literature_id, file_name),
        pdf_file_name=file_name,
        pdf_parse_status="pending",
    )


def build_parse_metadata(pdf_parse_status: str) -> tuple[str, str, str]:
    started_at = datetime.now(UTC).isoformat()
    finished_at = datetime.now(UTC).isoformat()
    if pdf_parse_status == "failed":
        return "Mock parser flagged file as failed", started_at, finished_at
    return "Mock parser completed successfully", started_at, finished_at


def _calculate_cjk_ratio(text: str) -> float:
    """Calculate the ratio of CJK (Chinese/Japanese/Korean) characters in text."""
    if not text:
        return 0.0
    cjk_count = sum(1 for c in text if "一" <= c <= "鿿")
    return cjk_count / len(text)


def _detect_low_text_density(text: str) -> bool:
    """Detect if text has low alphanumeric density (likely table/formula).

    Returns True if text appears to be mostly non-textual content.
    """
    if not text or len(text) < 10:
        return False
    alphanumeric = sum(1 for c in text if c.isalnum())
    # If <20% alphanumeric, likely table/formula/diagram
    return (alphanumeric / len(text)) < 0.2


def _filter_header_footer_pages(
    reader: PdfReader, skip_top_ratio: float = 0.15, skip_bottom_ratio: float = 0.15
) -> str:
    """Extract text from PDF pages, skipping likely header/footer regions.

    Args:
        reader: pypdf PdfReader instance
        skip_top_ratio: Skip top N% of each page (default 15% for headers)
        skip_bottom_ratio: Skip bottom N% of each page (default 15% for footers)

    Returns:
        Extracted text with headers/footers filtered
    """
    full_pages_text = []

    for page in reader.pages:
        try:
            # Extract full page text first
            page_text = page.extract_text() or ""
            if not page_text:
                continue

            lines = page_text.split("\n")
            if len(lines) <= 3:
                # Too few lines, keep as-is
                full_pages_text.append(page_text.strip())
                continue

            # Skip top and bottom portions (likely headers/footers)
            skip_top_lines = max(1, int(len(lines) * skip_top_ratio))
            skip_bottom_lines = max(1, int(len(lines) * skip_bottom_ratio))

            # Keep middle portion
            middle_lines = lines[skip_top_lines : len(lines) - skip_bottom_lines]
            filtered_text = "\n".join(middle_lines).strip()

            if filtered_text:
                full_pages_text.append(filtered_text)
        except Exception:
            # If page extraction fails, skip this page
            continue

    return "\n".join(full_pages_text)


def _is_likely_pdf_preview_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if any(pattern.search(stripped) for pattern in _PDF_HEADER_FOOTER_PATTERNS):
        return True
    if _detect_low_text_density(stripped):
        return True
    nul_count = stripped.count("\x00")
    return nul_count >= 5 and nul_count / max(len(stripped), 1) >= 0.15


def _score_pdf_preview_line(line: str) -> int:
    normalized = line.lower()
    score = 0
    for signal in _PDF_BODY_SIGNALS:
        if signal in normalized:
            score += 4
    cjk_ratio = _calculate_cjk_ratio(line)
    if cjk_ratio >= 0.2:
        score += 1
    if len(line.strip()) >= 24:
        score += 1
    return score


def _select_pdf_preview_window(text: str, max_chars: int = 300) -> str:
    """Select the most readable body-like preview window from extracted text."""

    candidates = [
        line.strip()
        for line in re.split(r"[\r\n]+", text)
        if not _is_likely_pdf_preview_noise(line)
    ]
    if not candidates:
        return text[:max_chars].strip()

    best_index = 0
    best_score = -1
    for index, line in enumerate(candidates):
        score = _score_pdf_preview_line(line)
        if score > best_score:
            best_index = index
            best_score = score

    window_lines: list[str] = []
    total_length = 0
    for line in candidates[best_index:]:
        if total_length and total_length + 1 + len(line) > max_chars:
            break
        window_lines.append(line)
        total_length += len(line) + (1 if total_length else 0)

    preview = "\n".join(window_lines).strip()
    if not preview:
        preview = "\n".join(candidates).strip()
    return preview[:max_chars].strip()


def extract_pdf_preview_text(storage_path: Path, max_chars: int = 300) -> str | None:
    """Extract preview text from PDF with quality improvements.

    Improvements:
    - Filter header/footer regions (top/bottom 15% of pages)
    - Skip low-density text (likely tables/formulas)

    Args:
        storage_path: Path to PDF file
        max_chars: Maximum characters to return

    Returns:
        Extracted text preview or None if extraction fails
    """
    try:
        reader = PdfReader(str(storage_path))

        # Use improved extraction with header/footer filtering
        text = _filter_header_footer_pages(reader)

    except Exception:
        return None

    if not text:
        return None

    return _select_pdf_preview_window(text, max_chars=max_chars)


def detect_pdf_text_quality_warning(preview_text: str | None) -> str | None:
    """Detect if PDF text extraction has quality issues.

    Improved thresholds:
    - NUL byte ratio increased from 2% to 5% (more tolerant of header garbling)
    - Still requires >=3 NUL bytes as absolute minimum

    Args:
        preview_text: Extracted preview text

    Returns:
        Warning message if quality issues detected, None otherwise
    """
    if not preview_text:
        return None
    nul_count = preview_text.count("\x00")
    # Increased tolerance from 0.02 (2%) to 0.05 (5%)
    if nul_count >= 3 or (nul_count > 0 and nul_count / max(len(preview_text), 1) >= 0.05):
        return _PDF_TEXT_QUALITY_WARNING
    return None


def build_pdf_parse_result(item: LiteratureItem) -> PdfParseResult | None:
    if item.pdf_parse_status != "parsed" or not item.pdf_upload_id or not item.pdf_file_name:
        return None
    storage_path = resolve_stored_pdf_path(item.pdf_upload_id)
    if storage_path is None:
        return None
    preview_text = extract_pdf_preview_text(storage_path)
    return PdfParseResult(
        file_name=item.pdf_file_name,
        storage_path=str(storage_path),
        file_size=storage_path.stat().st_size,
        preview_text=preview_text or _PDF_PARSE_RESULT_FALLBACK_PREVIEW,
        extraction_method="pypdf-text-preview" if preview_text else "file-metadata-placeholder",
        quality_warning=detect_pdf_text_quality_warning(preview_text),
    )


def update_pdf_parse_status(
    literature_id: str,
    pdf_parse_status: str,
    trigger: str = "manual",
    *,
    expected_pdf_upload_id: str | None = None,
    expected_file_name: str | None = None,
) -> tuple[str, LiteratureItem | None]:
    item = _REPOSITORY.get_item_by_id(literature_id)
    if item is None:
        return "not_found", None
    if not item.pdf_upload_id or not item.pdf_file_name:
        return "missing_metadata", None
    if (expected_pdf_upload_id is not None and item.pdf_upload_id != expected_pdf_upload_id) or (
        expected_file_name is not None and item.pdf_file_name != expected_file_name
    ):
        return "conflict", None
    pdf_parse_message, pdf_parse_started_at, pdf_parse_finished_at = build_parse_metadata(
        pdf_parse_status
    )
    next_item = LiteratureItem(
        **{
            **item.model_dump(),
            "pdf_parse_status": pdf_parse_status,
        }
    )
    updated = _REPOSITORY.update_pdf_parse_status(
        literature_id,
        pdf_parse_status,
        pdf_parse_message=pdf_parse_message,
        pdf_parse_started_at=pdf_parse_started_at,
        pdf_parse_finished_at=pdf_parse_finished_at,
        pdf_parse_result=build_pdf_parse_result(next_item),
        last_parse_trigger=trigger,
        expected_pdf_upload_id=item.pdf_upload_id,
    )
    return ("ok", updated) if updated is not None else ("conflict", None)


def _default_pubmed_fetcher() -> PubmedFetcher:
    return PubmedClient()


def _pubmed_record_to_item_dict(record: PubmedRecord) -> dict[str, object]:
    title = record.title
    abstract = record.abstract or ""
    snippet = abstract[:280] if abstract else title
    return {
        "id": f"pmid-{record.pmid}",
        "title": title,
        "language": "en",
        "source_type": "pubmed",
        "source": "PubMed live sync",
        "record_origin": "pubmed_live",
        "year": record.year if record.year is not None else 0,
        "snippet": snippet,
        "abstract": abstract or None,
        "authors": list(record.authors),
        "keywords": list(record.keywords),
        "evidence_tags": [],
        "pubmed_id": record.pmid,
        "doi": record.doi,
        "citation_url": f"https://pubmed.ncbi.nlm.nih.gov/{record.pmid}/",
    }


def sync_pubmed(
    query: str, max_results: int, fetcher: PubmedFetcher | None = None
) -> LiteratureSyncResponse:
    client = fetcher if fetcher is not None else _default_pubmed_fetcher()
    pmids = client.esearch(query.strip(), max_results=max_results)
    if not pmids:
        return LiteratureSyncResponse(
            source="pubmed", query=query.strip(), fetched=0, created=0, updated=0, items=[]
        )
    records = client.efetch(pmids)
    payload = [_pubmed_record_to_item_dict(record) for record in records]
    created, updated = _REPOSITORY.bulk_upsert_pubmed_items(payload)
    refreshed_ids = {entry["id"] for entry in payload}
    items = [item for item in _REPOSITORY.list_items() if item.id in refreshed_ids]
    return LiteratureSyncResponse(
        source="pubmed",
        query=query.strip(),
        fetched=len(records),
        created=created,
        updated=updated,
        items=items,
    )
