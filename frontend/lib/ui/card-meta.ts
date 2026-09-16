export function joinMetaItems(items: Array<string | null | undefined>) {
  return items.filter((item): item is string => Boolean(item && item.trim())).join(" · ");
}

export function getMetaRowStyle() {
  return {
    color: "var(--qiyan-muted)",
    margin: 0,
    fontSize: 13,
    fontWeight: 800,
    lineHeight: 1.6,
    overflowWrap: "anywhere",
  };
}

export function getMetaTextStyle() {
  return {
    color: "var(--qiyan-ink-2)",
    margin: "0 0 12px",
    lineHeight: 1.7,
  };
}
