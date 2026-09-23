"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { describeApiError } from "../lib/api/client";
import { fetchNetworkTasks } from "../lib/api/network";
import { truncateLabel } from "../lib/format-text";
import { mapNetworkTasksToRows, type NetworkTaskListRow } from "../lib/network-tasks";
import { getSurfaceSectionStyle } from "../lib/ui/surfaces";
import StatusPanel from "./StatusPanel";

const RECENT_LIMIT = 5;

export default function HomeRecentTasksClient() {
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [rows, setRows] = useState<NetworkTaskListRow[]>([]);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchNetworkTasks()
      .then((payload) => {
        if (!cancelled) {
          setRows(mapNetworkTasksToRows(payload.tasks).slice(0, RECENT_LIMIT));
          setPhase("ready");
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setErrorMessage(describeApiError(error, "加载最近的研究"));
          setPhase("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section style={getSurfaceSectionStyle()} aria-label="最近的研究">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <h2 style={{ color: "var(--qiyan-ink)", fontSize: 20, margin: 0 }}>最近的研究</h2>
        <Link href="/tasks" style={{ color: "#0d9488", fontWeight: 700 }}>
          查看全部 →
        </Link>
      </div>
      {phase === "loading" ? <StatusPanel message="正在加载最近的研究..." /> : null}
      {phase === "error" ? <StatusPanel message={errorMessage} tone="error" /> : null}
      {phase === "ready" && rows.length === 0 ? (
        <p style={{ color: "var(--qiyan-muted-2)", margin: 0 }}>还没有研究任务。点击上方「开始新分析」创建第一个。</p>
      ) : null}
      {phase === "ready" && rows.length > 0 ? (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
          {rows.map((row) => (
            <li key={row.taskId}>
              <Link
                href={row.viewHref}
                style={{ display: "flex", justifyContent: "space-between", gap: 12, color: "var(--qiyan-ink)", textDecoration: "none" }}
              >
                <strong title={row.query}>{truncateLabel(row.query)}</strong>
                <span style={{ color: "var(--qiyan-muted-2)", whiteSpace: "nowrap" }}>
                  {row.statusLabel} · {row.createdAtLabel}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
