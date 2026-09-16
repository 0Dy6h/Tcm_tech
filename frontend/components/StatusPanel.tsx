import type { CSSProperties } from "react";

import { getStatusCardStyle, getStatusMessageStyle, getStatusTone, type StatusTone } from "../lib/ui/status-card";

type StatusPanelProps = {
  message: string;
  tone?: StatusTone;
};

export default function StatusPanel({ message, tone = "idle" }: StatusPanelProps) {
  const resolvedTone = tone === "idle" || tone === "error" ? getStatusTone(tone === "error") : tone;

  return (
    <div role={resolvedTone === "danger" || resolvedTone === "error" ? "alert" : "status"} aria-atomic="true" style={getStatusCardStyle(resolvedTone) as CSSProperties}>
      <p style={getStatusMessageStyle(resolvedTone) as CSSProperties}>{message}</p>
    </div>
  );
}
