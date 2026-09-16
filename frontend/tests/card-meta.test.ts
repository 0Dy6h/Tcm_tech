import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { test } from "node:test";

import {
  getMetaRowStyle,
  getMetaTextStyle,
  joinMetaItems,
} from "../lib/ui/card-meta";
import { CardMetaRow } from "../components/CardMeta";

test("joinMetaItems drops empty items and joins with bullets", () => {
  assert.equal(joinMetaItems(["中文", "", null, "PubMed", undefined, "2024"]), "中文 · PubMed · 2024");
});

test("CardMetaRow renders no empty paragraph when every meta item is blank", () => {
  assert.equal(
    renderToStaticMarkup(createElement(CardMetaRow, { items: [null, undefined, ""] })),
    "",
  );
});

test("CardMetaRow still renders a paragraph when at least one item has content", () => {
  const markup = renderToStaticMarkup(createElement(CardMetaRow, { items: [null, "上传 ID pdf-1"] }));
  assert.match(markup, /上传 ID pdf-1/);
});

test("getMetaRowStyle returns shared card meta layout", () => {
  assert.deepEqual(getMetaRowStyle(), {
    color: "var(--qiyan-muted)",
    margin: 0,
    fontSize: 13,
    fontWeight: 800,
    lineHeight: 1.6,
    overflowWrap: "anywhere",
  });
});

test("getMetaTextStyle returns shared body text layout", () => {
  assert.deepEqual(getMetaTextStyle(), {
    color: "var(--qiyan-ink-2)",
    margin: "0 0 12px",
    lineHeight: 1.7,
  });
});
