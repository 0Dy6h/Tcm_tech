"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { describeApiError } from "../lib/api/client";
import { fetchNetworkTasks } from "../lib/api/network";
import { truncateLabel } from "../lib/format-text";
import { mapNetworkTasksToRows, type NetworkTaskListRow } from "../lib/network-tasks";
import { getSurfaceSectionStyle } from "../lib/ui/surfaces";
import StatusPanel from "./StatusPanel";

type ListPhase = "loading" | "ready" | "error";

function getTaskStatusPillStyle(status: NetworkTaskListRow["status"]) {
  switch (status) {
    case "completed":
      return { color: "#0f766e", background: "rgba(204, 251, 241, 0.72)", border: "1px solid rgba(13, 148, 136, 0.3)" };
    case "failed":
      return { color: "#b91c1c", background: "rgba(254, 226, 226, 0.78)", border: "1px solid rgba(185, 28, 28, 0.28)" };
    case "running":
      return { color: "#0f766e", background: "rgba(240, 253, 250, 0.9)", border: "1px solid rgba(13, 148, 136, 0.3)" };
    default:
      return { color: "var(--qiyan-muted)", background: "var(--qiyan-surface-3)", border: "1px solid var(--qiyan-line)" };
  }
}

export default function NetworkTaskListClient() {
  const [phase, setPhase] = useState<ListPhase>("loading");
  const [rows, setRows] = useState<NetworkTaskListRow[]>([]);
  const [reloadTick, setReloadTick] = useState(0);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchNetworkTasks()
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setRows(mapNetworkTasksToRows(payload.tasks));
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        setPhase("error");
        setErrorMessage(describeApiError(error, "加载研究任务列表"));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadTick]);

  if (phase === "loading") {
    return <StatusPanel message="加载研究任务列表..." />;
  }

  if (phase === "error") {
    return (
      <div style={{ display: "grid", gap: 12, justifyItems: "start" }}>
        <StatusPanel message={errorMessage} tone="error" />
        <button
          type="button"
          onClick={() => {
            setPhase("loading");
            setReloadTick((tick) => tick + 1);
          }}
          style={{
            border: "1px solid #0d9488",
            borderRadius: 8,
            background: "var(--qiyan-surface)",
            color: "#0f766e",
            fontWeight: 700,
            minHeight: 40,
            padding: "8px 16px",
            cursor: "pointer",
          }}
        >
          重试加载
        </button>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <section style={getSurfaceSectionStyle()} aria-label="研究任务空状态">
        <p style={{ color: "var(--qiyan-ink)", fontSize: 18, fontWeight: 700, margin: "0 0 8px" }}>
          还没有研究任务，去网络药理学页创建。
        </p>
        <p style={{ color: "var(--qiyan-muted-2)", margin: "0 0 16px", lineHeight: 1.65 }}>
          先冻结研究协议，再运行可审计的网络药理学任务；创建后会出现在这里。
        </p>
        <Link
          href="/network"
          style={{
            display: "inline-flex",
            alignItems: "center",
            border: "1px solid #0d9488",
            borderRadius: 8,
            color: "#0f766e",
            fontWeight: 700,
            minHeight: 40,
            padding: "8px 16px",
            textDecoration: "none",
          }}
        >
          去网络药理学页创建研究任务 →
        </Link>
      </section>
    );
  }

  return (
    <section style={getSurfaceSectionStyle()} aria-label="研究任务列表">
      <div style={{ display: "grid", gap: 6, marginBottom: 16 }}>
        <h2 style={{ color: "var(--qiyan-ink)", fontSize: 20, margin: 0 }}>研究任务（按创建时间倒序）</h2>
        <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.65 }}>
          共 {rows.length} 个任务；本地预览展示当前环境全部任务，受保护部署下仅显示本人的研究任务。
        </p>
      </div>
      <div style={{ maxWidth: "100%", overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            minWidth: 1080,
            borderCollapse: "collapse",
            fontSize: 14,
            textAlign: "left",
          }}
        >
          <thead>
            <tr style={{ borderBottom: "2px solid var(--qiyan-line)" }}>
              {["分析对象", "对象类型", "状态", "数据模式", "科研就绪", "创建时间", "操作"].map((heading) => (
                <th
                  key={heading}
                  scope="col"
                  style={{ padding: "10px 8px", color: "var(--qiyan-muted)", whiteSpace: "nowrap" }}
                >
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.taskId} style={{ borderBottom: "1px solid var(--qiyan-line)" }}>
                <td style={{ padding: "12px 8px", color: "var(--qiyan-ink)", fontWeight: 800 }}>
                  <div style={{ display: "grid", gap: 4 }}>
                    <span title={row.query}>{truncateLabel(row.query)}</span>
                    {row.isDerived ? (
                      <span
                        title={`派生自父任务 ${row.sourceTaskId}`}
                        style={{
                          justifySelf: "start",
                          border: "1px solid rgba(13, 148, 136, 0.3)",
                          borderRadius: 999,
                          background: "rgba(240, 253, 250, 0.9)",
                          color: "#0f766e",
                          fontSize: 12,
                          fontWeight: 700,
                          padding: "2px 10px",
                        }}
                      >
                        派生任务
                      </span>
                    ) : null}
                  </div>
                </td>
                <td style={{ padding: "12px 8px", color: "var(--qiyan-muted-2)" }}>{row.analysisTypeLabel}</td>
                <td style={{ padding: "12px 8px" }}>
                  <span
                    style={{
                      ...getTaskStatusPillStyle(row.status),
                      borderRadius: 999,
                      fontSize: 12,
                      fontWeight: 700,
                      padding: "3px 10px",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {row.statusLabel}
                  </span>
                </td>
                <td style={{ padding: "12px 8px", color: row.dataMode === "live" ? "#0f766e" : "var(--qiyan-muted-2)", fontWeight: 700, whiteSpace: "nowrap" }}>
                  {row.dataModeLabel}
                </td>
                <td style={{ padding: "12px 8px", whiteSpace: "nowrap" }}>
                  <span style={{ color: row.formalNetworkReady ? "#0f766e" : "#92400e", fontWeight: 700 }}>
                    {row.readinessLabel}
                  </span>
                </td>
                <td style={{ padding: "12px 8px", color: "var(--qiyan-muted-2)", whiteSpace: "nowrap" }}>
                  {row.createdAtLabel}
                </td>
                <td style={{ padding: "12px 8px" }}>
                  <Link
                    href={row.viewHref}
                    aria-label={`查看任务 ${truncateLabel(row.query)}`}
                    style={{ color: "#0f766e", fontWeight: 700, whiteSpace: "nowrap" }}
                  >
                    查看 →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
