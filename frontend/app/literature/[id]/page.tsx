import { notFound } from "next/navigation";

import { CardBodyText, CardMetaRow } from "../../../components/CardMeta";
import DemoDataBanner from "../../../components/DemoDataBanner";
import EntityChips from "../../../components/EntityChips";
import LiteraturePdfUploadClient from "../../../components/LiteraturePdfUploadClient";
import { ApiStatusError } from "../../../lib/api/client";
import {
  getLiteratureDetail,
  getLiteratureRecordOriginLabel,
  getLiteratureSourceLabel,
} from "../../../lib/api/literature";

type LiteratureDetailPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function LiteratureDetailPage({ params }: LiteratureDetailPageProps) {
  const { id } = await params;

  try {
    const item = await getLiteratureDetail(id);
    const literatureQuestion = encodeURIComponent(
      `请基于证据概述《${item.title}》与特应性皮炎中医药研究的关系，并列出可核对引用。`,
    );

    return (
      <>
        <article className="workbench-hero">
          <div className="workbench-hero-main">
            <p className="workbench-kicker">Evidence workbench</p>
            <h1 className="workbench-title workbench-detail-title">文献详情</h1>
            <p className="workbench-summary">
              先核对文献来源、摘要与年份，再进入 PDF 上传、解析状态与后续人工校正流程。
            </p>
          </div>
          <aside className="workbench-hero-aside" aria-label="文献详情元数据">
            <div className="workbench-stat">
              <span>Language</span>
              <strong>{item.language === "zh" ? "中文" : "英文"}</strong>
            </div>
            <div className="workbench-stat">
              <span>Record</span>
              <strong>{getLiteratureRecordOriginLabel(item.record_origin)}</strong>
            </div>
            <div className="workbench-stat">
              <span>Year</span>
              <strong>{String(item.year)}</strong>
            </div>
          </aside>
        </article>

        <div className="workbench-content-band">
          <DemoDataBanner compact />

          <article>
            <CardMetaRow
              items={[
                `语言 ${item.language === "zh" ? "中文" : "英文"}`,
                `记录来源 ${getLiteratureRecordOriginLabel(item.record_origin)}`,
                `来源 ${getLiteratureSourceLabel(item.source_type)}`,
                `期刊 ${item.source}`,
                `年份 ${String(item.year)}`,
                `文献 ID ${item.id}`,
              ]}
            />
            <EntityChips
              ids={item.related_entity_ids ?? []}
              emptyHint="该文献尚未挂载网药实体；如需跳转 /network 请使用相关词查询。"
            />
            <h2 style={{ color: "var(--qiyan-ink)", fontSize: 34, lineHeight: 1.28, margin: "18px 0 14px" }}>{item.title}</h2>
            <div style={{ display: "grid", gap: 12, color: "var(--qiyan-ink-2)", fontSize: 17, lineHeight: 1.7 }}>
              <CardBodyText>{item.snippet}</CardBodyText>
            </div>
          </article>

          <section
            aria-label="文献详情下一步"
            style={{
              display: "grid",
              gap: 10,
              border: "1px solid var(--qiyan-line)",
              borderRadius: 8,
              background: "var(--qiyan-surface-3)",
              padding: 16,
            }}
          >
            <p style={{ color: "var(--qiyan-kicker)", fontSize: 13, fontWeight: 800, margin: 0 }}>下一步</p>
            <h3 style={{ color: "var(--qiyan-ink)", fontSize: 18, margin: 0 }}>下一步：带这篇文献去问证据</h3>
            <p style={{ color: "var(--qiyan-muted-2)", lineHeight: 1.6, margin: 0 }}>
              核对完来源与 PDF 状态后，可以把当前题名带入 RAG，生成一份可追溯引用的证据简报。
            </p>
            <a
              href={`/rag?question=${literatureQuestion}`}
              style={{ color: "#0d9488", fontWeight: 700, width: "fit-content" }}
            >
              带这篇文献去问证据 →
            </a>
          </section>

          <LiteraturePdfUploadClient key={item.id} item={item} />
        </div>

        <section aria-label="使用提醒" className="workbench-reminder">
          <p className="workbench-reminder-title">使用提醒</p>
          <p className="workbench-reminder-copy">
            本页面信息仅用于研究与产品能力说明，不构成诊断或治疗建议；实际判断仍需结合临床指南、原始文献与专业医生意见。
          </p>
        </section>
      </>
    );
  } catch (error) {
    if (error instanceof ApiStatusError && error.status === 404) notFound();
    throw error;
  }
}
