import { ApiStatusError, apiFetch, buildApiHeaders, getBackendBaseUrl } from "./client";
export { getBackendBaseUrl } from "./client";

export type LiteratureItem = {
  id: string;
  title: string;
  language: "zh" | "en";
  source_type: "cn_literature" | "pubmed";
  source: string;
  record_origin: "seed_sample" | "pubmed_live";
  year: number;
  snippet: string;
  pdf_upload_id?: string | null;
  pdf_file_name?: string | null;
  pdf_parse_status?: "pending" | "parsed" | "failed" | null;
  pdf_parse_message?: string | null;
  pdf_parse_started_at?: string | null;
  pdf_parse_finished_at?: string | null;
  pdf_parse_result?: {
    file_name: string;
    storage_path: string;
    file_size: number;
    preview_text: string;
    extraction_method: string;
    quality_warning?: string | null;
  } | null;
  last_parse_trigger?: "auto" | "manual" | null;
  parse_attempt_count?: number | null;
  related_entity_ids?: string[];
};

export type LiteratureSource = "all" | "cn_literature" | "pubmed";
export type LiteratureSearchSort = "relevance" | "year_desc" | "year_asc";
export type PdfParseStatus = "pending" | "parsed" | "failed";

export type LiteratureDataSourceView = "all" | "pubmed_live" | "cnki_sample" | "uploaded_pdf";

export type LiteratureDataSourceFilter = {
  source: LiteratureSource;
  hasPdfUpload?: boolean;
};

export type LiteratureDataSourceBanner = {
  tone: "info" | "live" | "sample" | "upload";
  title: string;
  summary: string;
};

export type LiteratureSearchResponse = {
  query: string;
  source: LiteratureSource;
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  sort: LiteratureSearchSort;
  items: LiteratureItem[];
};

export type PdfUploadResponse = {
  literature_id: string;
  pdf_upload_id: string;
  file_name: string;
  content_type: string;
  file_size: number;
  storage_path: string;
  pdf_parse_status: PdfParseStatus;
};

export type LiteratureSyncRequest = {
  source: "pubmed";
  q: string;
  max_results: number;
};

export type LiteratureSyncResponse = {
  source: "pubmed";
  query: string;
  fetched: number;
  created: number;
  updated: number;
  items: LiteratureItem[];
};

export function getLiteratureSourceLabel(source: LiteratureSource) {
  if (source === "cn_literature") {
    return "中文文献";
  }
  if (source === "pubmed") {
    return "PubMed";
  }
  return "全部";
}

export function getLiteratureDataSourceLabel(view: LiteratureDataSourceView) {
  if (view === "pubmed_live") {
    return "PubMed 记录";
  }
  if (view === "cnki_sample") {
    return "CNKI 样本";
  }
  if (view === "uploaded_pdf") {
    return "上传 PDF";
  }
  return "全部来源";
}

export function getLiteratureDataSourceFilter(view: LiteratureDataSourceView): LiteratureDataSourceFilter {
  if (view === "pubmed_live") {
    return { source: "pubmed" };
  }
  if (view === "cnki_sample") {
    return { source: "cn_literature" };
  }
  if (view === "uploaded_pdf") {
    return { source: "all", hasPdfUpload: true };
  }
  return { source: "all" };
}

export function getLiteratureDataSourceBanner(view: LiteratureDataSourceView): LiteratureDataSourceBanner {
  if (view === "pubmed_live") {
    return {
      tone: "live",
      title: "PubMed 记录（含演示 seed）",
      summary:
        "此视图会展示 PubMed source_type 记录；标记为“PubMed 实时同步”的条目来自 NCBI E-utilities，标记为“演示样本”的 seed 条目不可当作外部可检索真实文献。",
    };
  }
  if (view === "cnki_sample") {
    return {
      tone: "sample",
      title: "CNKI 样本（演示）",
      summary:
        "当前中文条目为合成 seed 样本，用于演示证据工作台骨架，未对接知网/万方真实授权数据库。",
    };
  }
  if (view === "uploaded_pdf") {
    return {
      tone: "upload",
      title: "上传 PDF（仅本地）",
      summary:
        "上传 PDF 仅在本地解析与展示，不公开、不分发；请确保对原文具有合法访问权，并自行承担引用合规责任。",
    };
  }
  return {
    tone: "info",
    title: "全部来源",
    summary:
      "已汇总中文/英文演示 seed、PubMed 实时同步与上传 PDF 三类记录；每张卡片会标明记录来源，演示样本不可当作外部数据库真实文献引用。",
  };
}

export function getLiteratureRecordOriginLabel(origin: LiteratureItem["record_origin"]) {
  if (origin === "pubmed_live") {
    return "PubMed 实时同步";
  }
  return "演示样本";
}

export function getParseTriggerLabel(trigger: LiteratureItem["last_parse_trigger"]) {
  if (trigger === "auto") {
    return "自动触发";
  }
  if (trigger === "manual") {
    return "手动触发";
  }
  return null;
}

export function getParseAttemptLabel(count: LiteratureItem["parse_attempt_count"]) {
  if (count === null || count === undefined) {
    return null;
  }
  return `尝试 ${count} 次`;
}

export function getPdfParseStatusLabel(status: LiteratureItem["pdf_parse_status"]) {
  if (status === "pending") {
    return "PDF 待解析";
  }
  if (status === "parsed") {
    return "PDF 已解析";
  }
  if (status === "failed") {
    return "PDF 解析失败";
  }
  return null;
}

export function buildLiteratureSearchUrl(
  query: string,
  source: LiteratureSource = "all",
  page = 1,
  pageSize = 10,
  sort: LiteratureSearchSort = "relevance",
  hasPdfUpload?: boolean,
) {
  const url = new URL("/api/literature/search", getBackendBaseUrl());
  url.searchParams.set("q", query.trim());
  if (source !== "all") {
    url.searchParams.set("source", source);
  }
  if (page !== 1) {
    url.searchParams.set("page", String(page));
  }
  if (pageSize !== 10) {
    url.searchParams.set("page_size", String(pageSize));
  }
  if (sort !== "relevance") {
    url.searchParams.set("sort", sort);
  }
  if (hasPdfUpload !== undefined) {
    url.searchParams.set("has_pdf_upload", hasPdfUpload ? "true" : "false");
  }
  return url.toString();
}

export function buildLiteratureDetailUrl(itemId: string) {
  const encodedItemId = encodeURIComponent(itemId);
  return new URL(`/api/literature/${encodedItemId}`, getBackendBaseUrl()).toString();
}

export function buildPdfUploadUrl() {
  return new URL("/api/uploads/pdf", getBackendBaseUrl()).toString();
}

export function buildPdfDownloadUrl(pdfUploadId: string) {
  const encodedPdfUploadId = encodeURIComponent(pdfUploadId);
  return new URL(`/api/uploads/pdf/${encodedPdfUploadId}`, getBackendBaseUrl()).toString();
}

export function buildPdfParseStatusRequest(literatureId: string, status: Exclude<PdfParseStatus, "pending">, pdfUploadId?: string) {
  return {
    literature_id: literatureId,
    pdf_parse_status: status,
    ...(pdfUploadId ? { pdf_upload_id: pdfUploadId } : {}),
  };
}

export function buildFakePdfAutoParseRequest(literatureId: string, fileName: string, pdfUploadId?: string) {
  return {
    literature_id: literatureId,
    file_name: fileName,
    ...(pdfUploadId ? { pdf_upload_id: pdfUploadId } : {}),
  };
}

export async function searchLiterature(
  query: string,
  source: LiteratureSource = "all",
  page = 1,
  pageSize = 10,
  sort: LiteratureSearchSort = "relevance",
  hasPdfUpload?: boolean,
  signal?: AbortSignal,
): Promise<LiteratureSearchResponse> {
  const response = await apiFetch(
    buildLiteratureSearchUrl(query, source, page, pageSize, sort, hasPdfUpload),
    { signal },
  );

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Literature search failed");
  }

  return response.json();
}

export async function getLiteratureDetail(itemId: string): Promise<LiteratureItem> {
  const response = await apiFetch(buildLiteratureDetailUrl(itemId));

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Literature detail request failed");
  }

  return response.json();
}

export async function uploadLiteraturePdf(
  literatureId: string,
  file: File,
): Promise<PdfUploadResponse> {
  const formData = new FormData();
  formData.set("literature_id", literatureId);
  formData.set("file", file);

  const response = await apiFetch(buildPdfUploadUrl(), {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "PDF upload failed");
  }

  return response.json();
}

export async function runFakePdfAutoParse(literatureId: string, fileName: string, pdfUploadId?: string): Promise<LiteratureItem> {
  const response = await apiFetch(new URL("/api/uploads/pdf/auto-parse", getBackendBaseUrl()).toString(), {
    method: "POST",
    headers: buildApiHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(buildFakePdfAutoParseRequest(literatureId, fileName, pdfUploadId)),
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Fake PDF auto parse failed");
  }

  return response.json();
}

export async function updatePdfParseStatus(
  literatureId: string,
  status: Exclude<PdfParseStatus, "pending">,
  pdfUploadId?: string,
): Promise<LiteratureItem> {
  const response = await apiFetch(new URL("/api/literature/pdf-parse-status", getBackendBaseUrl()).toString(), {
    method: "POST",
    headers: buildApiHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(buildPdfParseStatusRequest(literatureId, status, pdfUploadId)),
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "PDF parse status update failed");
  }

  return response.json();
}

export const LITERATURE_SYNC_MAX_RESULTS_CAP = 50;

export function buildLiteratureSyncUrl() {
  return new URL("/api/literature/sync", getBackendBaseUrl()).toString();
}

export function buildLiteratureSyncRequest(query: string, maxResults: number): LiteratureSyncRequest {
  const trimmed = query.trim();
  const bounded = Math.max(1, Math.min(LITERATURE_SYNC_MAX_RESULTS_CAP, Math.floor(maxResults)));
  return {
    source: "pubmed",
    q: trimmed,
    max_results: bounded,
  };
}

export async function syncLiteratureFromPubmed(
  query: string,
  maxResults: number,
): Promise<LiteratureSyncResponse> {
  const response = await apiFetch(buildLiteratureSyncUrl(), {
    method: "POST",
    headers: buildApiHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(buildLiteratureSyncRequest(query, maxResults)),
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Literature sync failed");
  }

  return response.json();
}
