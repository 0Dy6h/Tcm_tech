"use client";

import { useState } from "react";

import { describeApiError } from "../lib/api/client";
import {
  formatEvalPassRate,
  getEvalItemStatusLabel,
  getRagAdEvalReport,
  getRagEvalCorpusLabel,
  type RagEvalReport,
} from "../lib/api/evals";
import { getRagSourceLabel } from "../lib/api/rag";
import { CardMetaRow } from "./CardMeta";
import StatusPanel from "./StatusPanel";

type RagEvalReportState = {
  report: RagEvalReport | null;
  isLoading: boolean;
  error: string | null;
};

function SummaryMetric({ label, value }: { label: string; value: string | number }) {
  const displayValue = String(value);
  return (
    <div
      style={{
        background: "var(--qiyan-surface)",
        border: "1px solid var(--qiyan-line)",
        borderRadius: 8,
        padding: 16,
        minHeight: 92,
      }}
    >
      <p style={{ color: "var(--qiyan-muted-2)", margin: 0 }}>{label}</p>
      <strong
        style={{
          color: "var(--qiyan-ink)",
          display: "block",
          fontSize: displayValue.length > 8 ? 20 : 28,
          lineHeight: 1.2,
          marginTop: 8,
          overflowWrap: "anywhere",
        }}
      >
        {value}
      </strong>
    </div>
  );
}

function joinOrFallback(items: string[], fallback: string) {
  return items.length > 0 ? items.join("、") : fallback;
}

export default function RagEvalReportClient() {
  const [state, setState] = useState<RagEvalReportState>({
    report: null,
    isLoading: false,
    error: null,
  });

  async function runReport() {
    setState({ report: null, isLoading: true, error: null });
    try {
      const report = await getRagAdEvalReport();
      setState({ report, isLoading: false, error: null });
    } catch (error) {
      setState({
        report: null,
        isLoading: false,
        error: describeApiError(error, "读取 RAG 评估报告"),
      });
    }
  }

  return (
    <div style={{ display: "grid", gap: 20, marginTop: 32 }}>
      <button
        type="button"
        onClick={runReport}
        disabled={state.isLoading}
        style={{
          justifySelf: "start",
          border: 0,
          borderRadius: 8,
          background: state.isLoading ? "#94a3b8" : "#0d9488",
          color: "white",
          fontSize: 16,
          fontWeight: 700,
          padding: "12px 20px",
        }}
      >
        {state.isLoading ? "正在运行评估" : "运行 RAG 评估"}
      </button>

      {state.error ? <StatusPanel message={state.error} tone="error" /> : null}

      {state.report ? (
        <>
          <section
            style={{
              display: "grid",
              gap: 12,
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            }}
          >
            <SummaryMetric label="通过率" value={formatEvalPassRate(state.report.summary.pass_rate)} />
            <SummaryMetric
              label="通过问题"
              value={`${state.report.summary.passed_questions}/${state.report.summary.total_questions}`}
            />
            <SummaryMetric
              label="语料范围"
              value={getRagEvalCorpusLabel(state.report.summary.corpus)}
            />
            <SummaryMetric label="文献命中题数" value={state.report.summary.citation_hit_count} />
            <SummaryMetric label="Chunk 命中题数" value={state.report.summary.chunk_hit_count} />
            <SummaryMetric label="免责声明覆盖" value={state.report.summary.disclaimer_coverage_count} />
            <SummaryMetric label="禁用语违规" value={state.report.summary.must_not_violation_count} />
            <SummaryMetric label="Grounding 拦截" value={state.report.summary.grounding_blocked_count} />
          </section>

          <section style={{ display: "grid", gap: 12 }}>
            {state.report.items.map((item) => (
              <article
                key={item.id}
                style={{
                  background: "var(--qiyan-surface)",
                  border: `1px solid ${item.passed ? "var(--qiyan-status-success-line)" : "var(--qiyan-status-danger-line)"}`,
                  borderRadius: 8,
                  padding: 20,
                }}
              >
                <CardMetaRow
                  items={[
                    item.id,
                    getEvalItemStatusLabel(item.passed),
                    getRagSourceLabel(item.source_preference),
                    item.difficulty,
                    `引用 ${item.citation_count} 条`,
                    `Grounding ${item.grounding_status}`,
                  ]}
                />
                <h2 style={{ color: "var(--qiyan-ink)", fontSize: 20, lineHeight: 1.4 }}>{item.question}</h2>
                <div style={{ color: "var(--qiyan-muted)", display: "grid", gap: 6, lineHeight: 1.7 }}>
                  <p style={{ margin: 0 }}>
                    命中文献：{joinOrFallback(item.expected_literature_hits, "无")}
                  </p>
                  <p style={{ margin: 0 }}>
                    命中片段：{joinOrFallback(item.expected_chunk_hits, "无")}
                  </p>
                  <p style={{ margin: 0 }}>
                    缺少关键词：{joinOrFallback(item.missing_must_include, "无")}
                  </p>
                  <p style={{ margin: 0 }}>
                    禁用语命中：{joinOrFallback(item.violated_must_not_include, "无")}
                  </p>
                </div>
              </article>
            ))}
          </section>
        </>
      ) : state.error ? null : (
        <StatusPanel message="运行评估后，将展示 50 个 AD RAG 问题的引用命中、chunk 命中、免责声明覆盖和禁用语检查。" />
      )}
    </div>
  );
}
