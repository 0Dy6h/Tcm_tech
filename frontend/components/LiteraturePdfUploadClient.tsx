"use client";

import { FormEvent, useMemo, useRef, useState } from "react";

import { describeApiError } from "../lib/api/client";
import {
  buildPdfDownloadUrl,
  getParseTriggerLabel,
  LiteratureItem,
  PdfUploadResponse,
  runFakePdfAutoParse,
  updatePdfParseStatus,
  uploadLiteraturePdf,
} from "../lib/api/literature";
import { getParseMethodLabel } from "../lib/literature/parseMethodLabel";
import { getPdfActionLabels, getPdfStatusCopy, getPdfStatusTone } from "../lib/ui/status-card";
import { getSurfaceSectionStyle } from "../lib/ui/surfaces";
import { CardMetaRow } from "./CardMeta";
import StatusPanel from "./StatusPanel";

type LiteraturePdfUploadClientProps = {
  item: LiteratureItem;
};

type UploadState = {
  fileName: string;
  result: PdfUploadResponse | null;
  currentItem: LiteratureItem;
  error: string | null;
  isLoading: boolean;
  isParsing: boolean;
  isUpdatingStatus: boolean;
};

function formatTimestamp(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  return value;
}

export default function LiteraturePdfUploadClient({ item }: LiteraturePdfUploadClientProps) {
  const busyRef = useRef(false);
  const [state, setState] = useState<UploadState>({
    fileName: item.pdf_file_name ?? "",
    result: null,
    currentItem: item,
    error: null,
    isLoading: false,
    isParsing: false,
    isUpdatingStatus: false,
  });

  const currentStatus = state.result?.pdf_parse_status ?? state.currentItem.pdf_parse_status;
  const currentUploadId = state.result?.pdf_upload_id ?? state.currentItem.pdf_upload_id;
  const currentFileName = state.result?.file_name ?? state.currentItem.pdf_file_name;
  const currentStoragePath = state.result?.storage_path ?? null;
  const currentParseMessage = state.currentItem.pdf_parse_message ?? null;
  const currentParseStartedAt = state.currentItem.pdf_parse_started_at ?? null;
  const currentParseFinishedAt = state.currentItem.pdf_parse_finished_at ?? null;
  const currentParseTrigger = getParseTriggerLabel(state.currentItem.last_parse_trigger ?? null);
  const currentParseAttemptCount = state.currentItem.parse_attempt_count ?? null;
  const currentPdfDownloadUrl = currentUploadId ? buildPdfDownloadUrl(currentUploadId) : null;
  const currentParseResult = state.currentItem.pdf_parse_result ?? null;
  const statusTone = useMemo(() => getPdfStatusTone(currentStatus), [currentStatus]);
  const actionLabels = useMemo(() => getPdfActionLabels(currentStatus), [currentStatus]);
  const statusCopy = useMemo(
    () => getPdfStatusCopy(currentStatus, state.isParsing, currentParseMessage),
    [currentStatus, state.isParsing, currentParseMessage],
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busyRef.current) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("file");

    if (!(file instanceof File) || !file.name) {
      setState((current) => ({ ...current, error: "请选择要上传的 PDF 文件。" }));
      return;
    }
    if (file.size === 0 || file.size > 20 * 1024 * 1024) {
      setState((current) => ({ ...current, error: "请选择非空且不超过 20 MB 的 PDF 文件。" }));
      return;
    }

    busyRef.current = true;
    setState((current) => ({ ...current, fileName: file.name, result: null, error: null, isLoading: true, isParsing: false }));

    let result: PdfUploadResponse;
    try {
      result = await uploadLiteraturePdf(state.currentItem.id, file);
    } catch (error) {
      busyRef.current = false;
      setState((current) => ({
        ...current, error: describeApiError(error, "PDF 上传"), isLoading: false,
      }));
      return;
    }

    setState((current) => ({
        ...current,
        fileName: result.file_name,
        result,
        currentItem: {
          ...current.currentItem,
          pdf_upload_id: result.pdf_upload_id,
          pdf_file_name: result.file_name,
          pdf_parse_status: result.pdf_parse_status,
          pdf_parse_message: null,
          pdf_parse_started_at: null,
          pdf_parse_finished_at: null,
          pdf_parse_result: null,
          last_parse_trigger: null,
          parse_attempt_count: 0,
        },
        error: null,
        isLoading: false,
        isParsing: true,
      }));

    try {
      const parsedItem = await runFakePdfAutoParse(state.currentItem.id, result.file_name, result.pdf_upload_id);
      setState((current) => ({
        ...current,
        currentItem: parsedItem,
        result: current.result
          ? {
              ...current.result,
              pdf_parse_status: parsedItem.pdf_parse_status ?? current.result.pdf_parse_status,
            }
          : current.result,
        error: null,
        isParsing: false,
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        fileName: file.name,
        result: current.result,
        error: `PDF 已上传；${describeApiError(error, "PDF 自动解析")}`,
        isLoading: false,
        isParsing: false,
      }));
    } finally {
      busyRef.current = false;
    }
  }

  async function onUpdateStatus(nextStatus: "parsed" | "failed") {
    if (busyRef.current) return;
    busyRef.current = true;
    setState((current) => ({ ...current, error: null, isUpdatingStatus: true }));

    try {
      const updatedItem = await updatePdfParseStatus(state.currentItem.id, nextStatus, currentUploadId ?? undefined);
      setState((current) => ({
        ...current,
        currentItem: updatedItem,
        result: current.result
          ? {
              ...current.result,
              pdf_parse_status: updatedItem.pdf_parse_status ?? current.result.pdf_parse_status,
            }
          : current.result,
        error: null,
        isUpdatingStatus: false,
      }));
    } catch (error) {
      setState((current) => ({
        ...current,
        error: describeApiError(error, "PDF 解析状态更新"),
        isUpdatingStatus: false,
      }));
    } finally {
      busyRef.current = false;
    }
  }

  return (
    <section
      style={{
        ...getSurfaceSectionStyle(),
        display: "grid",
        gap: 16,
      }}
    >
      <div style={{ display: "grid", gap: 8 }}>
        <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>PDF 上传与解析状态</h2>
        <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
          先确认当前 PDF 与解析状态，再决定是继续自动解析、预览原文，还是进入人工校正。
        </p>
      </div>

      <StatusPanel message={statusCopy} tone={statusTone} />

      <CardMetaRow
        items={[
          currentUploadId ? `上传 ID ${currentUploadId}` : null,
          currentFileName ? `当前文件 ${currentFileName}` : null,
          currentStoragePath ? `存储路径 ${currentStoragePath}` : null,
        ]}
      />

      {currentPdfDownloadUrl ? (
        <a
          href={currentPdfDownloadUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "#0d9488", fontWeight: 700, width: "fit-content" }}
        >
          预览 PDF
        </a>
      ) : null}

      <CardMetaRow
        items={[
          currentParseTrigger ? `触发方式 ${currentParseTrigger}` : null,
          currentParseAttemptCount !== null ? `解析次数 ${currentParseAttemptCount} 次` : null,
          currentParseStartedAt ? `开始时间 ${formatTimestamp(currentParseStartedAt)}` : null,
          currentParseFinishedAt ? `完成时间 ${formatTimestamp(currentParseFinishedAt)}` : null,
        ]}
      />

      {currentParseResult ? (
        <div
          style={{
            display: "grid",
            gap: 10,
            padding: 16,
            border: "1px solid var(--qiyan-line)",
            borderRadius: 8,
            background: "var(--qiyan-surface-3)",
          }}
        >
          <div style={{ display: "grid", gap: 4 }}>
            <h3 style={{ color: "var(--qiyan-ink-2)", fontSize: 16, margin: 0 }}>解析结果预览</h3>
            <p style={{ color: "var(--qiyan-muted-2)", margin: 0, fontSize: 14, lineHeight: 1.6 }}>
              {currentParseResult.extraction_method === "pypdf-text-preview"
                ? "已抽取文本层预览，可对照原文做证据核对；扫描件与 OCR 能力将在后续接入。"
                : "未能抽取文本层，已回退到文件级占位说明；正文抽取与 OCR 能力将在后续接入。"}
            </p>
          </div>
          <CardMetaRow
            items={[
              `解析方式 ${getParseMethodLabel(currentParseResult.extraction_method)}`,
              `文件大小 ${currentParseResult.file_size} 字节`,
            ]}
          />
          {currentParseResult.quality_warning ? (
            <p
              style={{
                color: "var(--qiyan-status-warning-text)",
                background: "var(--qiyan-status-warning-bg)",
                border: "1px solid var(--qiyan-status-warning-line)",
                borderRadius: 16,
                margin: 0,
                padding: "10px 12px",
                fontSize: 14,
                lineHeight: 1.6,
              }}
            >
              {`抽取质量提示 ${currentParseResult.quality_warning}`}
            </p>
          ) : null}
          <p style={{ color: "var(--qiyan-ink-2)", margin: 0, fontSize: 14, lineHeight: 1.7 }}>
            {`预览说明 ${currentParseResult.preview_text}`}
          </p>
        </div>
      ) : null}

      <div style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gap: 6 }}>
          <label htmlFor="literature-pdf-file" style={{ color: "var(--qiyan-ink-2)", fontSize: 15, fontWeight: 700 }}>
            选择 PDF 文件
          </label>
          <p style={{ color: "var(--qiyan-muted-2)", margin: 0, fontSize: 14, lineHeight: 1.6 }}>
            建议上传当前文献对应的 PDF 原文，用于后续证据核对、解析与人工校正。
          </p>
        </div>

        <form onSubmit={onSubmit} style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <input
            id="literature-pdf-file"
            name="file"
            type="file"
            accept="application/pdf,.pdf"
            disabled={state.isLoading || state.isParsing || state.isUpdatingStatus}
            aria-label="选择 PDF 文件"
            style={{ color: "var(--qiyan-ink-2)", maxWidth: "100%" }}
          />
          <button
            type="submit"
            disabled={state.isLoading || state.isParsing || state.isUpdatingStatus}
            style={{
              border: 0,
              borderRadius: 8,
              background: state.isLoading || state.isParsing ? "#94a3b8" : "#0d9488",
              color: "white",
              fontSize: 15,
              fontWeight: 700,
              padding: "10px 16px",
              minHeight: 44,
            }}
          >
            {state.isLoading ? "上传中..." : state.isParsing ? "解析中..." : "上传 PDF"}
          </button>
        </form>
        {state.error ? <StatusPanel message={state.error} tone="error" /> : null}
      </div>

      {actionLabels.length > 0 ? (
        <div
          style={{
            display: "grid",
            gap: 12,
            padding: 16,
            border: "1px solid var(--qiyan-line)",
            borderRadius: 8,
            background: "var(--qiyan-surface-3)",
          }}
        >
          <div style={{ display: "grid", gap: 4 }}>
            <h3 style={{ color: "var(--qiyan-ink-2)", fontSize: 16, margin: 0 }}>人工校正</h3>
            <p style={{ color: "var(--qiyan-muted-2)", margin: 0, fontSize: 14, lineHeight: 1.6 }}>
              当自动解析结果待确认时，可回到原文预览与状态面板，再人工标记当前 PDF 是否解析完成。
            </p>
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <button
              type="button"
              disabled={state.isUpdatingStatus || state.isLoading || state.isParsing}
              onClick={() => onUpdateStatus("parsed")}
              style={{
                border: 0,
                borderRadius: 8,
                background: state.isUpdatingStatus ? "#94a3b8" : "#16a34a",
                color: "white",
                fontSize: 15,
                fontWeight: 700,
                padding: "10px 16px",
                minHeight: 44,
              }}
            >
              {state.isUpdatingStatus ? "状态更新中..." : actionLabels[0]}
            </button>
            <button
              type="button"
              disabled={state.isUpdatingStatus || state.isLoading || state.isParsing}
              onClick={() => onUpdateStatus("failed")}
              style={{
                border: 0,
                borderRadius: 8,
                background: state.isUpdatingStatus ? "#94a3b8" : "#dc2626",
                color: "white",
                fontSize: 15,
                fontWeight: 700,
                padding: "10px 16px",
                minHeight: 44,
              }}
            >
              {state.isUpdatingStatus ? "状态更新中..." : actionLabels[1]}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
