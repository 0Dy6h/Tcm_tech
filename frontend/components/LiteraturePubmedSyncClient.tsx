"use client";

import { FormEvent, useState } from "react";

import { describeApiError } from "../lib/api/client";
import {
  LITERATURE_SYNC_MAX_RESULTS_CAP,
  LiteratureItem,
  LiteratureSyncResponse,
  getLiteratureRecordOriginLabel,
  syncLiteratureFromPubmed,
} from "../lib/api/literature";
import { getSurfaceCardStyle, getSurfaceSectionStyle } from "../lib/ui/surfaces";
import { CardBodyText, CardMetaRow } from "./CardMeta";
import StatusPanel from "./StatusPanel";

type SyncState = {
  query: string;
  maxResults: number;
  result: LiteratureSyncResponse | null;
  error: string | null;
  isLoading: boolean;
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

function SyncResultItem({ item }: { item: LiteratureItem }) {
  return (
    <article style={getSurfaceCardStyle()}>
      <CardMetaRow
        items={[
          `PMID ${item.id.replace(/^pmid-/, "")}`,
          `记录来源 ${getLiteratureRecordOriginLabel(item.record_origin)}`,
          `年份 ${item.year}`,
          `来源 ${item.source}`,
        ]}
      />
      <h3 style={{ color: "var(--qiyan-ink)", fontSize: 18, marginTop: 8, marginBottom: 8 }}>{item.title}</h3>
      <CardBodyText>{item.snippet}</CardBodyText>
      <a
        href={`/literature/${encodeURIComponent(item.id)}`}
        style={{ color: "#0d9488", fontWeight: 700 }}
      >
        查看文献详情 →
      </a>
    </article>
  );
}

export default function LiteraturePubmedSyncClient() {
  const [state, setState] = useState<SyncState>({
    query: "atopic dermatitis",
    maxResults: 10,
    result: null,
    error: null,
    isLoading: false,
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const query = String(form.get("query") ?? "").trim();
    const rawMaxResults = Number(form.get("max_results") ?? state.maxResults);
    const maxResults = Number.isFinite(rawMaxResults)
      ? Math.max(1, Math.min(LITERATURE_SYNC_MAX_RESULTS_CAP, Math.floor(rawMaxResults)))
      : 1;

    if (!query) {
      setState((current) => ({ ...current, query, maxResults, result: null, error: "请输入检索关键词。" }));
      return;
    }

    setState((current) => ({ ...current, query, maxResults, result: null, error: null, isLoading: true }));

    try {
      const result = await syncLiteratureFromPubmed(query, maxResults);
      setState({ query, maxResults, result, error: null, isLoading: false });
    } catch (error) {
      setState({
        query,
        maxResults,
        result: null,
        error: describeApiError(error, "同步 PubMed"),
        isLoading: false,
      });
    }
  }

  return (
    <section style={getSurfaceSectionStyle()}>
      <div style={{ display: "grid", gap: 8, marginBottom: 20 }}>
        <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>同步 PubMed</h2>
        <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
          调用后端 <code>/api/literature/sync</code>，从 NCBI E-utilities 拉取并合并到 runtime
          文献库；不覆盖已有的 PDF 元数据与解析状态。
        </p>
      </div>

      <form onSubmit={onSubmit} style={{ display: "grid", gap: 16 }}>
        <label style={fieldLabelStyle}>
          检索关键词
          <input
            name="query"
            type="text"
            value={state.query}
            onChange={(event) => setState((current) => ({ ...current, query: event.target.value }))}
            aria-label="PubMed 检索关键词"
            style={{ ...fieldControlStyle, width: "100%" }}
          />
        </label>

        <div style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
          <label style={fieldLabelStyle}>
            拉取数量 max_results
            <input
              name="max_results"
              type="number"
              min={1}
              max={LITERATURE_SYNC_MAX_RESULTS_CAP}
              value={state.maxResults}
              onChange={(event) => {
                const nextValue = Number(event.target.value);
                setState((current) => ({
                  ...current,
                  maxResults: Number.isFinite(nextValue)
                    ? Math.max(1, Math.min(LITERATURE_SYNC_MAX_RESULTS_CAP, Math.floor(nextValue)))
                    : 1,
                }));
              }}
              aria-label="PubMed 拉取数量"
              style={{ ...fieldControlStyle, width: 160 }}
            />
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
            {state.isLoading ? "同步中..." : "同步 PubMed"}
          </button>
        </div>
      </form>

      {state.error ? (
        <div style={{ marginTop: 16 }}>
          <StatusPanel message={state.error} tone="error" />
        </div>
      ) : null}

      {state.result ? (
        <div style={{ display: "grid", gap: 16, marginTop: 20 }}>
          <CardMetaRow
            items={[
              `检索关键词 ${state.result.query}`,
              `拉取条数 ${state.result.fetched}`,
              `新增 ${state.result.created}`,
              `刷新 ${state.result.updated}`,
            ]}
          />
          {state.result.items.length > 0 ? (
            <div style={{ display: "grid", gap: 12 }}>
              {state.result.items.map((item) => (
                <SyncResultItem key={item.id} item={item} />
              ))}
            </div>
          ) : (
            <StatusPanel message="本次同步未返回新条目；NCBI 可能没有命中或网络异常。" />
          )}
        </div>
      ) : null}
    </section>
  );
}
