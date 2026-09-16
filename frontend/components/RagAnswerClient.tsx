"use client";

import { FormEvent, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  answerRagQuestion,
  CitationCard,
  fetchRagAnswerDocx,
  fetchRagAnswerMarkdown,
  getRagSourceLabel,
  GroundingMetadata,
  ProviderSli,
  RagAnswerResponse,
  RagSource,
} from "../lib/api/rag";
import { ApiStatusError, describeApiError } from "../lib/api/client";
import { buildPdfDownloadUrl } from "../lib/api/literature";
import { buildAnswerDocxFileName, buildAnswerMarkdownFileName } from "../lib/rag-export";
import { getCitationEmptyCopy, getEmptyStateCopy, getStatusCopy } from "../lib/ui/states";
import { getSurfaceCardStyle, getSurfaceSectionStyle } from "../lib/ui/surfaces";
import { CardBodyText, CardMetaRow } from "./CardMeta";
import EntityChips from "./EntityChips";
import StatusPanel from "./StatusPanel";

type RagState = {
  question: string;
  source: RagSource;
  topK: number;
  result: RagAnswerResponse | null;
  error: string | null;
  isLoading: boolean;
};

function formatConfidence(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatMatchScore(value: number | null | undefined) {
  return value == null ? "未计算" : `${Math.round(value * 100)}%`;
}

function getRagGenerationModeLabel(providerName: string) {
  if (providerName === "deterministic") {
    return "本地生成";
  }
  if (providerName === "mock_claude") {
    return "离线 mock 模型";
  }
  if (providerName === "opencode_go" || providerName === "anthropic") {
    return "外部模型 opt-in";
  }
  return providerName;
}

function formatTokenUsage(value: number | null | undefined) {
  return value == null ? "未返回" : `${value}`;
}

function formatLatencyMs(sli: ProviderSli | null | undefined) {
  return sli?.provider_latency_ms == null ? "未返回" : `${sli.provider_latency_ms} ms`;
}

function formatEstimatedCost(sli: ProviderSli | null | undefined) {
  return sli?.estimated_cost_usd == null ? "未估算" : `$${sli.estimated_cost_usd.toFixed(6)}`;
}

function formatGroundingCoverage(grounding: GroundingMetadata) {
  return `${grounding.cited_claim_count}/${grounding.claim_count}`;
}

function formatStructuredClaimCount(grounding: GroundingMetadata) {
  return `${grounding.structured_claims.length}`;
}

function formatNativeGrounding(grounding: GroundingMetadata) {
  return grounding.provider_native_grounding ? "true" : "false";
}

function formatGroundingTool(grounding: GroundingMetadata) {
  return grounding.tool_name ?? "无";
}

function formatSemanticThreshold(grounding: GroundingMetadata) {
  return grounding.semantic_threshold == null ? "未启用" : grounding.semantic_threshold.toFixed(2);
}

function formatSemanticScore(grounding: GroundingMetadata) {
  return grounding.min_semantic_score == null
    ? "未计算"
    : `${Math.round(grounding.min_semantic_score * 100)}%`;
}

function formatNliThreshold(grounding: GroundingMetadata) {
  return grounding.nli_threshold == null ? "未启用" : grounding.nli_threshold.toFixed(2);
}

function formatNliScore(grounding: GroundingMetadata) {
  return grounding.min_entailment_score == null
    ? "未计算"
    : `${Math.round(grounding.min_entailment_score * 100)}%`;
}

function formatGroundingBlockedReason(reason: string | null | undefined) {
  if (reason === "unsupported_evidence_ref") {
    return "存在未提供的证据 ID";
  }
  if (reason === "structured_claims_parse_error") {
    return "模型草稿没有按结构化 claims JSON 输出";
  }
  if (reason === "empty_structured_claims") {
    return "结构化 claims 为空";
  }
  if (reason === "missing_tool_use") {
    return "模型未调用受控引用工具";
  }
  if (reason === "tool_name_mismatch") {
    return "模型调用了非预期工具";
  }
  if (reason === "tool_input_schema_error") {
    return "引用工具参数不符合结构化 schema";
  }
  if (reason === "empty_tool_claims") {
    return "引用工具 claims 为空";
  }
  if (reason === "claim_without_evidence_ref") {
    return "存在未声明证据 ID 的结构化 claim";
  }
  if (reason === "blank_claim_text") {
    return "存在内容为空的结构化 claim";
  }
  if (reason === "semantic_low_support") {
    return "存在与引用证据语义支持度过低的 claim";
  }
  if (reason === "nli_low_entailment") {
    return "存在未被引用证据蕴含的结构化 claim";
  }
  return "无";
}

function CitationListItem({ citation }: { citation: CitationCard }) {
  const isUploadedPdf = citation.source_type === "uploaded_pdf";
  const pdfPreviewUrl = isUploadedPdf && citation.pdf_upload_id ? buildPdfDownloadUrl(citation.pdf_upload_id) : null;
  return (
    <article style={getSurfaceCardStyle()}>
      <CardMetaRow
        items={[
          `来源 ${citation.source}`,
          `检索匹配度 ${formatMatchScore(citation.match_score)}`,
          `来源类型先验 ${formatConfidence(citation.confidence)}`,
          isUploadedPdf ? "用户上传 PDF 片段（来自上传 PDF）" : null,
        ]}
      />
      <h3 style={{ color: "var(--qiyan-ink)", fontSize: 22, marginBottom: 12 }}>{citation.title}</h3>
      <CardBodyText>{citation.snippet}</CardBodyText>
      <EntityChips ids={citation.related_entity_ids ?? []} />
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <a href={`/literature/${encodeURIComponent(citation.literature_id)}`} style={{ color: "#0d9488", fontWeight: 700 }}>
          查看文献详情 →
        </a>
        {pdfPreviewUrl ? (
          <a href={pdfPreviewUrl} target="_blank" rel="noopener noreferrer" style={{ color: "#0d9488", fontWeight: 700 }}>
            预览原文 PDF ↗
          </a>
        ) : null}
      </div>
    </article>
  );
}

export default function RagAnswerClient() {
  const searchParams = useSearchParams();
  const initialQuestion =
    searchParams.get("question")?.trim() || "特应性皮炎和肠-脑-皮肤轴有什么关系？";
  const [state, setState] = useState<RagState>({
    question: initialQuestion,
    source: "all",
    topK: 2,
    result: null,
    error: null,
    isLoading: false,
  });
  const statusCopy = getStatusCopy("rag", state.isLoading);
  const emptyStateCopy = getEmptyStateCopy("rag");
  const citationEmptyCopy = getCitationEmptyCopy();

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const question = String(form.get("question") ?? "").trim();
    const source = String(form.get("source") ?? "all") as RagSource;
    const rawTopK = Number(form.get("top_k") ?? state.topK);
    const topK = Number.isFinite(rawTopK) ? Math.max(1, Math.floor(rawTopK)) : 1;

    if (!question) {
      setState((current) => ({ ...current, question, source, topK, result: null, error: "请输入问题。" }));
      return;
    }

    setState((current) => ({ ...current, question, source, topK, result: null, error: null, isLoading: true }));

    try {
      const result = await answerRagQuestion(question, source, topK);
      setState({ question, source, topK, result, error: null, isLoading: false });
    } catch (error) {
      setState({
        question,
        source,
        topK,
        result: null,
        error:
          error instanceof ApiStatusError
            ? `生成回答失败（HTTP ${error.status}），请稍后重试或调整检索范围。`
            : "请求失败，请确认后端服务已启动。",
        isLoading: false,
      });
    }
  }

  function downloadBlob(blob: Blob, fileName: string) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  async function onExportAnswer() {
    if (!state.result) {
      return;
    }
    let markdown: string;
    try {
      markdown = await fetchRagAnswerMarkdown(state.result);
    } catch (error) {
      setState((current) => ({ ...current, error: describeApiError(error, "导出 Markdown 答案") }));
      return;
    }
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    downloadBlob(blob, buildAnswerMarkdownFileName(state.result.answered_at));
  }

  async function onExportDocx() {
    if (!state.result) {
      return;
    }
    let blob: Blob;
    try {
      blob = await fetchRagAnswerDocx(state.result);
    } catch (error) {
      setState((current) => ({ ...current, error: describeApiError(error, "导出 Word 答案") }));
      return;
    }
    downloadBlob(blob, buildAnswerDocxFileName(state.result.answered_at));
  }

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <section style={getSurfaceSectionStyle()}>
        <div style={{ display: "grid", gap: 8, marginBottom: 20 }}>
          <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>问答条件</h2>
          <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
            先明确问题，再限定来源与引用数量，随后核对回答、技术审计信息与引用证据。
          </p>
        </div>

        <form onSubmit={onSubmit} style={{ display: "grid", gap: 16 }}>
          <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
            问题
            <textarea
              name="question"
              value={state.question}
              onChange={(event) => setState((current) => ({ ...current, question: event.target.value }))}
              aria-label="RAG 问题"
              rows={4}
              style={{
                width: "100%",
                border: "1px solid var(--qiyan-line)",
                borderRadius: 8,
                fontSize: 16,
                padding: "12px 14px",
                resize: "vertical",
              }}
            />
          </label>

          <div style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
            <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
              文献来源
              <select
                name="source"
                value={state.source}
                onChange={(event) => setState((current) => ({ ...current, source: event.target.value as RagSource }))}
                aria-label="RAG 文献来源"
                style={{
                  minWidth: 180,
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 8,
                  fontSize: 16,
                  padding: "12px 14px",
                }}
              >
                <option value="all">全部文献</option>
                <option value="cn_literature">中文文献</option>
                <option value="pubmed">PubMed</option>
              </select>
            </label>

            <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
              引用数量 top_k
              <input
                name="top_k"
                type="number"
                min={1}
                value={state.topK}
                onChange={(event) => {
                  const nextValue = Number(event.target.value);
                  setState((current) => ({
                    ...current,
                    topK: Number.isFinite(nextValue) ? Math.max(1, Math.floor(nextValue)) : 1,
                  }));
                }}
                aria-label="引用数量"
                style={{
                  width: 140,
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 8,
                  fontSize: 16,
                  padding: "12px 14px",
                }}
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
              {state.isLoading ? statusCopy.loadingLabel : statusCopy.submitLabel}
            </button>
          </div>
        </form>
      </section>

      {state.error ? <StatusPanel message={state.error} tone="error" /> : null}

      {state.result ? (
        <div style={{ display: "grid", gap: 20 }}>
          <section style={getSurfaceSectionStyle()}>
            <div style={{ display: "grid", gap: 4, marginBottom: 16 }}>
              <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>证据简报</h2>
              <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
                先阅读结论，再回到下方引用卡片核对证据来源与检索边界；技术细节保留在审计信息中。
              </p>
            </div>
            <CardMetaRow
              items={[
                `回答模式 ${getRagGenerationModeLabel(state.result.provider_name)}`,
                `证据范围 ${getRagSourceLabel(state.result.retrieval.applied_source)}`,
                `引用卡片 ${state.result.citations.length}`,
                `可用引用数 ${state.result.retrieval.available_citation_count}`,
              ]}
            />
            <h3 style={{ color: "var(--qiyan-ink)", fontSize: 28, marginTop: 12, marginBottom: 12 }}>{state.result.question}</h3>
            {state.result.grounding.status === "blocked" ? (
              <div style={{ marginBottom: 12 }}>
                <StatusPanel
                  message={`模型草稿未通过引用证据校验，已拦截展示。拦截原因：${formatGroundingBlockedReason(state.result.grounding.blocked_reason)}。`}
                  tone="warning"
                />
              </div>
            ) : null}
            <CardBodyText>{state.result.answer}</CardBodyText>
            <p style={{ color: "var(--qiyan-muted-2)", marginBottom: 12, lineHeight: 1.6 }}>{state.result.disclaimer}</p>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
              <button
                type="button"
                onClick={onExportAnswer}
                aria-label="导出答案为 Markdown"
                style={{
                  border: "1px solid #0d9488",
                  borderRadius: 8,
                  background: "var(--qiyan-surface)",
                  color: "#0d9488",
                  fontSize: 15,
                  fontWeight: 700,
                  padding: "10px 18px",
                  minHeight: 44,
                  cursor: "pointer",
                }}
              >
                导出答案为 Markdown ↓
              </button>
              <button
                type="button"
                onClick={onExportDocx}
                aria-label="导出答案为 Word 文档"
                style={{
                  border: "1px solid #0d9488",
                  borderRadius: 8,
                  background: "var(--qiyan-surface)",
                  color: "#0d9488",
                  fontSize: 15,
                  fontWeight: 700,
                  padding: "10px 18px",
                  minHeight: 44,
                  cursor: "pointer",
                }}
              >
                导出为 Word (.docx) ↓
              </button>
              <a href="/evals/rag-ad" style={{ color: "#0d9488", fontWeight: 700 }}>
                运行 RAG 评估
              </a>
              <a href="/compliance" style={{ color: "#0d9488", fontWeight: 700 }}>
                核对合规边界
              </a>
              <span style={{ color: "var(--qiyan-muted-2)", fontSize: 13 }}>
                Markdown 适合纯文本归档；Word (.docx) 可直接在 Word / WPS 中编辑。
              </span>
            </div>
            <div
              aria-label="证据简报后续动作"
              style={{
                border: "1px solid var(--qiyan-line)",
                borderRadius: 8,
                marginTop: 12,
                padding: "10px 12px",
                background: "var(--qiyan-surface-3)",
              }}
            >
              <p style={{ color: "var(--qiyan-kicker)", fontSize: 13, fontWeight: 800, margin: "0 0 4px" }}>下一步</p>
              <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
                导出后可运行 50 题回归评估，或核对合规边界，确认这份证据材料适合进入 reviewer 走查。
              </p>
            </div>
            <details
              style={{
                border: "1px solid var(--qiyan-line)",
                borderRadius: 8,
                marginTop: 16,
                padding: "10px 12px",
                background: "var(--qiyan-surface-3)",
              }}
            >
              <summary
                style={{
                  color: "var(--qiyan-ink)",
                  cursor: "pointer",
                  fontSize: 15,
                  fontWeight: 700,
                  lineHeight: 1.6,
                }}
              >
                技术审计信息（开发者可选，临床核对可跳过）
              </summary>
              <p style={{ color: "var(--qiyan-muted-2)", margin: "10px 0", lineHeight: 1.6 }}>
                面向开发者与内部审计：用于确认当前回答实际使用的来源范围、引用上限、可核对证据数量、provider、grounding 与成本/延迟。临床/科研核对证据时可忽略本节。
              </p>
              <CardMetaRow
                items={[
                  `应用来源 ${getRagSourceLabel(state.result.retrieval.applied_source)}`,
                  `应用 top_k ${state.result.retrieval.applied_top_k}`,
                  `可用引用数 ${state.result.retrieval.available_citation_count}`,
                  `Provider ${state.result.provider_name}`,
                  `检索策略 ${state.result.retrieval.strategy}`,
                  `Grounding ${state.result.grounding.status}`,
                  `Grounding 策略 ${state.result.grounding.policy}`,
                  `Native Grounding ${formatNativeGrounding(state.result.grounding)}`,
                  `Grounding Tool ${formatGroundingTool(state.result.grounding)}`,
                  `Tool 调用数 ${state.result.grounding.tool_call_count}`,
                  `语义阈值 ${formatSemanticThreshold(state.result.grounding)}`,
                  `最小语义支持度 ${formatSemanticScore(state.result.grounding)}`,
                  `NLI 阈值 ${formatNliThreshold(state.result.grounding)}`,
                  `最小蕴含支持度 ${formatNliScore(state.result.grounding)}`,
                  `句级引用覆盖 ${formatGroundingCoverage(state.result.grounding)}`,
                  `结构化声明 ${formatStructuredClaimCount(state.result.grounding)}`,
                  `Token 输入 ${formatTokenUsage(state.result.input_tokens)}`,
                  `Token 输出 ${formatTokenUsage(state.result.output_tokens)}`,
                  `Provider 延迟 ${formatLatencyMs(state.result.sli)}`,
                  `预估成本 ${formatEstimatedCost(state.result.sli)}`,
                ]}
              />
            </details>
          </section>

          <section style={getSurfaceSectionStyle()}>
            <div style={{ display: "grid", gap: 4, marginBottom: 16 }}>
              <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>引用卡片</h2>
              <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
                应用来源：{getRagSourceLabel(state.result.retrieval.applied_source)}；应用 top_k：
                {state.result.retrieval.applied_top_k}
              </p>
            </div>
            {state.result.citations.length > 0 ? (
              <div style={{ display: "grid", gap: 16 }}>
                {state.result.citations.map((citation, index) => (
                  <CitationListItem
                    key={`${citation.literature_id}:${citation.chunk_id ?? "doc"}:${index}`}
                    citation={citation}
                  />
                ))}
              </div>
            ) : (
              <StatusPanel message={citationEmptyCopy} />
            )}
          </section>
        </div>
      ) : state.error ? null : (
        <StatusPanel message={emptyStateCopy.idle} />
      )}
    </div>
  );
}
