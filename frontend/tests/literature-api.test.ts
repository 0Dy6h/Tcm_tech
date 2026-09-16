import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildLiteratureSearchUrl,
  getLiteratureDataSourceBanner,
  getLiteratureDataSourceFilter,
  getLiteratureDataSourceLabel,
  getLiteratureRecordOriginLabel,
  getLiteratureSourceLabel,
} from "../lib/api/literature";

test("buildLiteratureSearchUrl encodes query with default backend base URL", () => {
  const url = buildLiteratureSearchUrl("特应性皮炎");

  assert.equal(
    url,
    "http://127.0.0.1:8010/api/literature/search?q=%E7%89%B9%E5%BA%94%E6%80%A7%E7%9A%AE%E7%82%8E",
  );
});

test("buildLiteratureSearchUrl trims query", () => {
  const url = buildLiteratureSearchUrl("  AD  ");

  assert.equal(url, "http://127.0.0.1:8010/api/literature/search?q=AD");
});

test("buildLiteratureSearchUrl appends non-default search contract params", () => {
  const url = buildLiteratureSearchUrl("AD", "pubmed", 2, 5, "year_asc");

  assert.equal(
    url,
    "http://127.0.0.1:8010/api/literature/search?q=AD&source=pubmed&page=2&page_size=5&sort=year_asc",
  );
});

test("getLiteratureSourceLabel returns display text", () => {
  assert.equal(getLiteratureSourceLabel("all"), "全部");
  assert.equal(getLiteratureSourceLabel("cn_literature"), "中文文献");
  assert.equal(getLiteratureSourceLabel("pubmed"), "PubMed");
});

test("buildLiteratureSearchUrl appends has_pdf_upload when set", () => {
  const onlyUploaded = buildLiteratureSearchUrl("AD", "all", 1, 10, "relevance", true);
  assert.equal(
    onlyUploaded,
    "http://127.0.0.1:8010/api/literature/search?q=AD&has_pdf_upload=true",
  );

  const excludingUploaded = buildLiteratureSearchUrl("AD", "all", 1, 10, "relevance", false);
  assert.equal(
    excludingUploaded,
    "http://127.0.0.1:8010/api/literature/search?q=AD&has_pdf_upload=false",
  );
});

test("buildLiteratureSearchUrl omits has_pdf_upload when undefined", () => {
  const url = buildLiteratureSearchUrl("AD", "all", 1, 10, "relevance", undefined);
  assert.equal(url, "http://127.0.0.1:8010/api/literature/search?q=AD");
});

test("getLiteratureDataSourceLabel surfaces compliance-friendly copy for the 4 views", () => {
  assert.equal(getLiteratureDataSourceLabel("all"), "全部来源");
  assert.equal(getLiteratureDataSourceLabel("pubmed_live"), "PubMed 记录");
  assert.equal(getLiteratureDataSourceLabel("cnki_sample"), "CNKI 样本");
  assert.equal(getLiteratureDataSourceLabel("uploaded_pdf"), "上传 PDF");
});

test("getLiteratureRecordOriginLabel distinguishes seed and live PubMed metadata", () => {
  assert.equal(getLiteratureRecordOriginLabel("seed_sample"), "演示样本");
  assert.equal(getLiteratureRecordOriginLabel("pubmed_live"), "PubMed 实时同步");
});

test("getLiteratureDataSourceFilter maps each view to backend search params", () => {
  assert.deepEqual(getLiteratureDataSourceFilter("all"), { source: "all" });
  assert.deepEqual(getLiteratureDataSourceFilter("pubmed_live"), { source: "pubmed" });
  assert.deepEqual(getLiteratureDataSourceFilter("cnki_sample"), { source: "cn_literature" });
  assert.deepEqual(getLiteratureDataSourceFilter("uploaded_pdf"), {
    source: "all",
    hasPdfUpload: true,
  });
});

test("getLiteratureDataSourceBanner returns view-aware compliance copy", () => {
  const all = getLiteratureDataSourceBanner("all");
  assert.equal(all.tone, "info");
  assert.ok(all.title.length > 0);
  assert.ok(all.summary.length > 0);

  const pubmed = getLiteratureDataSourceBanner("pubmed_live");
  assert.ok(/PubMed|NCBI/.test(pubmed.summary));
  assert.ok(/演示样本|seed/.test(pubmed.summary));
  assert.ok(/不可当作外部可检索真实文献/.test(pubmed.summary));

  const cnki = getLiteratureDataSourceBanner("cnki_sample");
  // CNKI sample 必须明示是 seed / 演示样本，不是真实知网授权
  assert.ok(/seed|sample|演示|示例/.test(cnki.summary));

  const uploaded = getLiteratureDataSourceBanner("uploaded_pdf");
  // 上传 PDF banner 必须强调本地用途 + 用户自证权利（A6 合规章节口径）
  assert.ok(/本地|不公开|不分发/.test(uploaded.summary));
});
