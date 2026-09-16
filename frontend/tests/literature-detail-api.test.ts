import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildFakePdfAutoParseRequest,
  buildLiteratureDetailUrl,
  buildPdfDownloadUrl,
  buildPdfParseStatusRequest,
  buildPdfUploadUrl,
  getBackendBaseUrl,
  getPdfParseStatusLabel,
  getParseAttemptLabel,
  getParseTriggerLabel,
} from "../lib/api/literature";

test("getBackendBaseUrl uses the non-public internal API URL during server rendering", () => {
  process.env.QIYAN_INTERNAL_API_BASE_URL = "http://127.0.0.1:8100";
  process.env.NEXT_PUBLIC_API_BASE_URL = "https://trial.example";

  try {
    assert.equal(getBackendBaseUrl(), "http://127.0.0.1:8100");
  } finally {
    delete process.env.QIYAN_INTERNAL_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  }
});

test("getBackendBaseUrl keeps browser requests on the public same-origin API URL", () => {
  process.env.QIYAN_INTERNAL_API_BASE_URL = "http://127.0.0.1:8100";
  process.env.NEXT_PUBLIC_API_BASE_URL = "https://trial.example";
  const originalWindowDescriptor = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {} });

  try {
    assert.equal(getBackendBaseUrl(), "https://trial.example");
  } finally {
    delete process.env.QIYAN_INTERNAL_API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    if (originalWindowDescriptor) {
      Object.defineProperty(globalThis, "window", originalWindowDescriptor);
    } else {
      Reflect.deleteProperty(globalThis, "window");
    }
  }
});

test("buildLiteratureDetailUrl encodes item id with default backend base URL", () => {
  assert.equal(
    buildLiteratureDetailUrl("cn-ad-gbs-001"),
    "http://127.0.0.1:8010/api/literature/cn-ad-gbs-001",
  );
});

test("buildLiteratureDetailUrl encodes reserved characters", () => {
  assert.equal(
    buildLiteratureDetailUrl("cn/ad gbs?001"),
    "http://127.0.0.1:8010/api/literature/cn%2Fad%20gbs%3F001",
  );
});

test("buildPdfUploadUrl points to upload endpoint on default backend base URL", () => {
  assert.equal(buildPdfUploadUrl(), "http://127.0.0.1:8010/api/uploads/pdf");
});

test("buildPdfDownloadUrl points to stable uploaded PDF endpoint", () => {
  assert.equal(
    buildPdfDownloadUrl("pdf-cn-ad-gbs-001-review-pdf"),
    "http://127.0.0.1:8010/api/uploads/pdf/pdf-cn-ad-gbs-001-review-pdf",
  );
});

test("buildPdfDownloadUrl encodes reserved upload id characters", () => {
  assert.equal(
    buildPdfDownloadUrl("pdf-cn/ad gbs?001"),
    "http://127.0.0.1:8010/api/uploads/pdf/pdf-cn%2Fad%20gbs%3F001",
  );
});

test("uploadLiteraturePdf sends only literature_id and file in multipart form", async () => {
  process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN = "dev-token";
  const captured: { body: BodyInit | null | undefined; headers: HeadersInit | undefined }[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (_url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ body: init?.body, headers: init?.headers });
    return {
      ok: true,
      async json() {
        return {
          literature_id: "cn-ad-gbs-001",
          pdf_upload_id: "pdf-cn-ad-gbs-001-review-pdf",
          file_name: "review.pdf",
          content_type: "application/pdf",
          file_size: 3,
          storage_path: "/tmp/pdf-cn-ad-gbs-001-review-pdf.pdf",
          pdf_parse_status: "pending",
        };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { uploadLiteraturePdf } = await import(`../lib/api/literature?ts=${Date.now()}`);
    const file = new File(["pdf"], "review.pdf", { type: "application/pdf" });
    await uploadLiteraturePdf("cn-ad-gbs-001", file);

    assert.equal(captured.length, 1);
    const formData = captured[0].body as FormData;
    const headers = captured[0].headers as Record<string, string>;
    assert.equal(formData.get("literature_id"), "cn-ad-gbs-001");
    assert.equal((formData.get("file") as File).name, "review.pdf");
    assert.equal(formData.has("auto_parse"), false);
    assert.equal("X-Access-Token" in headers, false);
    assert.equal("Content-Type" in headers, false);
  } finally {
    globalThis.fetch = originalFetch;
    delete process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN;
  }
});

test("buildPdfParseStatusRequest builds payload for parsed status update", () => {
  assert.deepEqual(buildPdfParseStatusRequest("cn-ad-gbs-001", "parsed"), {
    literature_id: "cn-ad-gbs-001",
    pdf_parse_status: "parsed",
  });
});

test("buildFakePdfAutoParseRequest builds payload for fake parser step", () => {
  assert.deepEqual(buildFakePdfAutoParseRequest("cn-ad-gbs-001", "ad-evidence.pdf"), {
    literature_id: "cn-ad-gbs-001",
    file_name: "ad-evidence.pdf",
  });
});

test("getParseTriggerLabel returns auto and manual display copy", () => {
  assert.equal(getParseTriggerLabel("auto"), "自动触发");
  assert.equal(getParseTriggerLabel("manual"), "手动触发");
  assert.equal(getParseTriggerLabel(null), null);
});

test("getParseAttemptLabel returns readable retry count copy", () => {
  assert.equal(getParseAttemptLabel(0), "尝试 0 次");
  assert.equal(getParseAttemptLabel(2), "尝试 2 次");
  assert.equal(getParseAttemptLabel(null), null);
});

test("getPdfParseStatusLabel returns compact search card copy", () => {
  assert.equal(getPdfParseStatusLabel("pending"), "PDF 待解析");
  assert.equal(getPdfParseStatusLabel("parsed"), "PDF 已解析");
  assert.equal(getPdfParseStatusLabel("failed"), "PDF 解析失败");
  assert.equal(getPdfParseStatusLabel(null), null);
});
