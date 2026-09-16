"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import { describeApiError } from "../lib/api/client";
import {
  getLiteratureDataSourceFilter,
  getPdfParseStatusLabel,
  getLiteratureRecordOriginLabel,
  getLiteratureSourceLabel,
  LiteratureDataSourceView,
  LiteratureItem,
  LiteratureSearchSort,
  searchLiterature,
} from "../lib/api/literature";
import { getEmptyStateCopy, getStatusCopy } from "../lib/ui/states";
import { getSurfaceCardStyle, getSurfaceSectionStyle } from "../lib/ui/surfaces";
import { CardBodyText, CardMetaRow } from "./CardMeta";
import LiteratureDataSourceBanner from "./LiteratureDataSourceBanner";
import StatusPanel from "./StatusPanel";

type SearchState = {
  query: string;
  view: LiteratureDataSourceView;
  sort: LiteratureSearchSort;
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  items: LiteratureItem[];
  error: string | null;
  isLoading: boolean;
  hasSearched: boolean;
};

const fieldLabelStyle = {
  display: "grid",
  gap: 8,
  color: "var(--qiyan-ink)",
  fontWeight: 700,
} as const;

const fieldControlStyle = {
  border: "1px solid var(--qiyan-line)",
  borderRadius: 8,
  fontSize: 16,
  padding: "12px 14px",
} as const;

export default function LiteratureSearchClient() {
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q")?.trim() || "特应性皮炎";
  const appliedQueryRef = useRef<string | null>(null);
  const searchRequestRef = useRef<AbortController | null>(null);
  const [state, setState] = useState<SearchState>({
    query: initialQuery,
    view: "all",
    sort: "relevance",
    page: 1,
    pageSize: 10,
    total: 0,
    totalPages: 0,
    items: [],
    error: null,
    isLoading: false,
    hasSearched: false,
  });
  const statusCopy = getStatusCopy("literature", state.isLoading);
  const emptyStateCopy = getEmptyStateCopy("literature");

  async function runSearch(
    query: string,
    view: LiteratureDataSourceView,
    page: number,
    pageSize: number,
    sort: LiteratureSearchSort,
  ) {
    searchRequestRef.current?.abort();
    const request = new AbortController();
    searchRequestRef.current = request;
    setState((current) => ({
      ...current,
      query,
      view,
      sort,
      page,
      pageSize,
      items: [],
      error: null,
      isLoading: true,
      hasSearched: true,
    }));

    const filter = getLiteratureDataSourceFilter(view);
    try {
      const result = await searchLiterature(
        query,
        filter.source,
        page,
        pageSize,
        sort,
        filter.hasPdfUpload,
        request.signal,
      );
      if (request.signal.aborted || searchRequestRef.current !== request) return;
      setState({
        query: result.query,
        view,
        sort: result.sort,
        page: result.page,
        pageSize: result.page_size,
        total: result.total,
        totalPages: result.total_pages,
        items: result.items,
        error: null,
        isLoading: false,
        hasSearched: true,
      });
    } catch (error) {
      if (request.signal.aborted || searchRequestRef.current !== request) return;
      setState({
        query,
        view,
        sort,
        page,
        pageSize,
        total: 0,
        totalPages: 0,
        items: [],
        error: describeApiError(error, "文献检索"),
        isLoading: false,
        hasSearched: true,
      });
    }
  }

  useEffect(() => () => {
    searchRequestRef.current?.abort();
    appliedQueryRef.current = null;
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const query = String(form.get("q") ?? "").trim();
    const view = String(form.get("view") ?? "all") as LiteratureDataSourceView;
    const sort = String(form.get("sort") ?? "relevance") as LiteratureSearchSort;
    const pageSize = Number(form.get("page_size") ?? state.pageSize);

    if (!query) {
      searchRequestRef.current?.abort();
      setState((current) => ({
        ...current,
        query,
        view,
        sort,
        items: [],
        error: "请输入检索关键词。",
        hasSearched: true,
        isLoading: false,
      }));
      return;
    }

    await runSearch(query, view, 1, pageSize, sort);
  }

  useEffect(() => {
    const linkedQuery = searchParams.get("q")?.trim();
    if (!linkedQuery || appliedQueryRef.current === linkedQuery) {
      return;
    }
    appliedQueryRef.current = linkedQuery;
    void runSearch(linkedQuery, "all", 1, state.pageSize, "relevance");
    // runSearch intentionally stays out of the dependency list so a linked query
    // triggers one search rather than resubmitting on every state update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, state.pageSize]);

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <LiteratureDataSourceBanner view={state.view} />

      <section style={getSurfaceSectionStyle()}>
        <div style={{ display: "grid", gap: 8, marginBottom: 20 }}>
          <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>检索条件</h2>
          <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
            先明确关键词，再限定来源、排序与每页数量，随后进入结果核对与原文追踪。
          </p>
        </div>

        <form onSubmit={onSubmit} style={{ display: "grid", gap: 16 }}>
          <label style={fieldLabelStyle}>
            检索关键词
            <input
              name="q"
              value={state.query}
              onChange={(event) => setState((current) => ({ ...current, query: event.target.value }))}
              aria-label="检索关键词"
              style={{
                ...fieldControlStyle,
                width: "100%",
                minWidth: 220,
              }}
            />
          </label>

          <div style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
            <label style={fieldLabelStyle}>
              文献来源
              <select
                name="view"
                defaultValue={state.view}
                aria-label="文献来源"
                style={{ ...fieldControlStyle, minWidth: 180 }}
              >
                <option value="all">全部来源</option>
                <option value="pubmed_live">PubMed 记录</option>
                <option value="cnki_sample">CNKI 样本</option>
                <option value="uploaded_pdf">上传 PDF</option>
              </select>
            </label>
            <label style={fieldLabelStyle}>
              排序方式
              <select name="sort" defaultValue={state.sort} aria-label="排序方式" style={fieldControlStyle}>
                <option value="relevance">相关度</option>
                <option value="year_desc">年份降序</option>
                <option value="year_asc">年份升序</option>
              </select>
            </label>
            <label style={fieldLabelStyle}>
              每页数量
              <select name="page_size" defaultValue={state.pageSize} aria-label="每页数量" style={fieldControlStyle}>
                <option value="5">5 条/页</option>
                <option value="10">10 条/页</option>
                <option value="20">20 条/页</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={state.isLoading}
              style={{
                border: 0,
                borderRadius: 8,
                background: state.isLoading ? "#94a3b8" : "#0d9488",
                color: "white",
                fontSize: 16,
                fontWeight: 700,
                padding: "12px 20px",
                minHeight: 44,
              }}
            >
              {state.isLoading ? statusCopy.loadingLabel : statusCopy.submitLabel}
            </button>
          </div>
        </form>
      </section>

      {state.error ? <StatusPanel message={state.error} tone="error" /> : null}

      {!state.error && state.total > 0 ? (
        <section style={getSurfaceSectionStyle()}>
          <div
            style={{
              alignItems: "center",
              color: "var(--qiyan-muted)",
              display: "flex",
              flexWrap: "wrap",
              fontSize: 14,
              gap: 12,
              justifyContent: "space-between",
              marginBottom: 16,
            }}
          >
            <div style={{ display: "grid", gap: 4 }}>
              <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>检索结果</h2>
              <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
                共 {state.total} 条结果，第 {state.page} / {state.totalPages} 页；请优先核对来源、年份与解析状态。
              </p>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                disabled={state.isLoading || state.page <= 1}
                onClick={() => runSearch(state.query, state.view, state.page - 1, state.pageSize, state.sort)}
                style={{
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 8,
                  background: "var(--qiyan-surface)",
                  color: "var(--qiyan-ink-2)",
                  fontSize: 14,
                  fontWeight: 600,
                  padding: "10px 14px",
                  minHeight: 44,
                }}
              >
                上一页
              </button>
              <button
                type="button"
                disabled={state.isLoading || state.page >= state.totalPages}
                onClick={() => runSearch(state.query, state.view, state.page + 1, state.pageSize, state.sort)}
                style={{
                  border: 0,
                  borderRadius: 8,
                  background: state.isLoading || state.page >= state.totalPages ? "#94a3b8" : "#0d9488",
                  color: "white",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "10px 14px",
                  minHeight: 44,
                }}
              >
                下一页
              </button>
            </div>
          </div>

          <div style={{ display: "grid", gap: 16 }}>
            {state.items.map((item) => (
              <article key={item.id} style={getSurfaceCardStyle()}>
                <CardMetaRow
                  items={[
                    `语言 ${item.language === "zh" ? "中文" : "英文"}`,
                    `记录来源 ${getLiteratureRecordOriginLabel(item.record_origin)}`,
                    `来源 ${getLiteratureSourceLabel(item.source_type)}`,
                    `期刊 ${item.source}`,
                    `年份 ${String(item.year)}`,
                    `解析状态 ${getPdfParseStatusLabel(item.pdf_parse_status ?? null)}`,
                  ]}
                />
                <h3 style={{ color: "var(--qiyan-ink)", fontSize: 22, marginBottom: 12 }}>{item.title}</h3>
                <CardBodyText>{item.snippet}</CardBodyText>
                <a href={`/literature/${encodeURIComponent(item.id)}`} style={{ color: "#0d9488", fontWeight: 700 }}>
                  查看详情 →
                </a>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {state.items.length > 0 || state.isLoading || state.error ? null : (
        <div style={{ display: "grid", gap: 12 }}>
          <StatusPanel
            message={state.hasSearched ? "未检索到匹配文献，请调整关键词、来源或排序后重试。" : emptyStateCopy.idle}
          />
          {state.hasSearched ? (
            <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
              当前为小型演示语料，可命中的文献主题有限；靶点缩写（如 IL6、TNF）暂无对应记录。下面的示例词在演示语料中有命中，点击即可直接检索。
            </p>
          ) : (
            <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
              还没有检索记录：点下面的示例词直接开始，或输入关键词后检索。
            </p>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {["消风散", "特应性皮炎", "atopic dermatitis"].map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                disabled={state.isLoading}
                onClick={() => runSearch(suggestion, state.view, 1, state.pageSize, state.sort)}
                style={{
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 8,
                  background: "var(--qiyan-surface)",
                  color: "var(--qiyan-ink-2)",
                  fontSize: 14,
                  fontWeight: 600,
                  padding: "10px 14px",
                  minHeight: 44,
                }}
              >
                {`试试「${suggestion}」`}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
