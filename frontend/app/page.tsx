import type { ReactNode } from "react";
import {
  ArrowRightOutlined,
  BranchesOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";

import HomeRecentTasksClient from "../components/HomeRecentTasksClient";

const DISCLAIMER = "非诊断结论、需结合临床。";

const taskCards: Array<{
  href: string;
  icon: ReactNode;
  eyebrow: string;
  title: string;
  body: string;
  metric: string;
}> = [
  {
    href: "/network",
    icon: <BranchesOutlined aria-hidden="true" />,
    eyebrow: "Step 1",
    title: "定研究协议",
    body: "选定方药、明确特应性皮炎的具体表型、物种和证据要求，并记录查询日期，避免把所有疾病靶点混在一起。",
    metric: "研究参数先确认",
  },
  {
    href: "/network",
    icon: <BranchesOutlined aria-hidden="true" />,
    eyebrow: "Step 2",
    title: "构建网络",
    body: "按研究协议串起方药-成分-靶点-通路，每一步都保留数据来源和证据等级。",
    metric: "靶点网络与通路富集",
  },
  {
    href: "/literature",
    icon: <FileSearchOutlined aria-hidden="true" />,
    eyebrow: "Step 3",
    title: "核证据",
    body: "用文献检索、PDF 和带引用的问答核对靶点与通路，机器提取与人工判断分开记录。",
    metric: "文献与引用核对",
  },
  {
    href: "/network",
    icon: <ExperimentOutlined aria-hidden="true" />,
    eyebrow: "Step 4",
    title: "出研究报告",
    body: "导出研究协议、数据来源、网络链路、富集结果和尚未满足的条件；「报告是否完整」与「结论是否可用于科研」分开说明。",
    metric: "可追溯的报告",
  },
];

const controlRows = [
  { label: "Scope", value: "特应性皮炎", note: "AD only" },
  { label: "Audience", value: "医生 / 科研人员", note: "非 C 端" },
  { label: "Primary", value: "网络药理学科研辅助", note: "主轴" },
  { label: "Evidence", value: "文献 / PDF / RAG", note: "服务层" },
  { label: "Readiness", value: "Scientific readiness = false", note: "默认 fail closed（条件不满足即阻断）" },
];

const signalCards = [
  { value: "只做特应性皮炎", label: "病种范围明确" },
  { value: "先定参数", label: "分析前确认研究设置" },
  { value: "每条连线有出处", label: "来源与证据分级可查" },
  { value: "条件不足不下结论", label: "证据不够时明确提示" },
  { value: DISCLAIMER, label: "输出边界" },
];

function TaskCard({ card }: Readonly<{ card: (typeof taskCards)[number] }>) {
  return (
    <a className="task-card" href={card.href}>
      <span className="task-icon">{card.icon}</span>
      <span className="task-eyebrow">{card.eyebrow}</span>
      <h3>{card.title}</h3>
      <p>{card.body}</p>
      <span className="task-foot">
        <span>{card.metric}</span>
        <ArrowRightOutlined aria-hidden="true" />
      </span>
    </a>
  );
}

export default function HomePage() {
  return (
    <>
      <article className="home-hero" aria-label="Qiyan Nexus 首页">
        <div className="home-hero-main">
          <p className="workbench-kicker">中医药网络药理学 · 特应性皮炎</p>
          <h1 className="home-title">窄领域网络药理学科研工作台</h1>
          <p className="home-summary">
            围绕特应性皮炎中医药研究，先冻结研究协议，再构建可追溯的成分-靶点-通路网络。文献检索、PDF 归档与 RAG 问答是证据服务层，用来核验科研链路，而不是另一个聊天产品。
          </p>

          <div className="home-app-console">
            <nav className="home-mode-tabs" aria-label="研究工作模式">
              <a className="home-mode-tab home-mode-tab-active" href="/network">
                <BranchesOutlined aria-hidden="true" />
                网络药理学研究
              </a>
              <a className="home-mode-tab" href="/literature">
                <FileSearchOutlined aria-hidden="true" />
                证据服务
              </a>
            </nav>

            <div className="home-prompt-card" aria-label="新建网络药理学研究任务">
              <div>
                <strong>开始新分析</strong>
                <p>输入方药 → 选择表型与证据要求 → 生成成分-靶点-通路网络</p>
              </div>
              <div className="home-prompt-tools">
                <a
                  className="home-mode-tab home-mode-tab-active"
                  href="/network"
                  aria-label="开始新分析"
                  style={{ fontWeight: 700 }}
                >
                  开始新分析
                  <ArrowRightOutlined aria-hidden="true" />
                </a>
              </div>
            </div>
          </div>
        </div>

        <aside className="home-boundary-panel" aria-label="当前产品边界摘要">
          <div>
            <span>主要用途</span>
            <strong>网络药理学科研辅助</strong>
          </div>
          <div>
            <span>使用前提</span>
            <strong>先确认研究参数再分析</strong>
          </div>
          <div>
            <span>默认数据</span>
            <strong>演示数据，证据不足时不下结论</strong>
          </div>
        </aside>
      </article>

      <HomeRecentTasksClient />

      <section className="home-signal-strip" aria-label="科研链路概览">
        {signalCards.map((card) => (
          <article className="home-signal-card" key={card.label}>
            <strong>{card.value}</strong>
            <span>{card.label}</span>
          </article>
        ))}
      </section>

      <section className="workbench-content-band" aria-label="工作台任务入口">
        <div className="home-section-head">
          <div>
            <p className="workbench-kicker">研究流程</p>
            <h2>网络药理学是主流程，证据能力为每条科研链路服务</h2>
          </div>
          <p>
            主路径固定为：定研究协议 → 构建网络 → 核证据 → 出研究报告。前一步条件不满足时，系统不会给出后续科研结论。
          </p>
        </div>

        <div className="task-grid">
          {taskCards.map((card) => (
            <TaskCard key={`${card.eyebrow}-${card.title}`} card={card} />
          ))}
        </div>

        <section className="home-control-panel" aria-label="产品边界">
          <div className="home-control-intro">
            <SafetyCertificateOutlined aria-hidden="true" />
            <div>
              <h2>边界可见，结论才可信</h2>
              <p>
                当前版本提供可追溯的科研流程，证据不足时会明确提示而不是给出结论；演示结果不代表真实网络药理学发现，也不替代诊断、处方或个体治疗判断。
                <strong>{DISCLAIMER}</strong>
              </p>
            </div>
          </div>

          <details>
            <summary style={{ cursor: "pointer", fontWeight: 700 }}>技术细节（研发与审阅用）</summary>
          <dl className="home-control-table">
            {controlRows.map((row) => (
              <div className="home-control-row" key={row.label}>
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
                <dd>{row.note}</dd>
              </div>
            ))}
          </dl>
          </details>
        </section>
      </section>
    </>
  );
}
