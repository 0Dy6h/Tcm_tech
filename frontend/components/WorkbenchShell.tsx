"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  PlusOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";

const navItems = [
  { href: "/network", label: "网络药理学" },
  { href: "/tasks", label: "我的研究" },
  { href: "/literature", label: "文献检索" },
  { href: "/rag", label: "证据问答" },
  // Dev/review-only pages (/compliance, /evals/rag-ad) stay reachable by URL but are kept out of primary nav.
];

const railSignals = [
  { title: "Research protocol", time: "运行前冻结" },
  { title: "Scientific readiness", time: "默认 fail closed" },
];

function getCurrentNavHref(pathname: string) {
  if (pathname.startsWith("/literature")) {
    return "/literature";
  }

  return navItems.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))?.href;
}

export default function WorkbenchShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname() ?? "/";
  const isHome = pathname === "/";
  const currentHref = getCurrentNavHref(pathname);

  return (
    <main className={`workbench-page${isHome ? " home-page" : ""}`} style={{ minHeight: "100vh", padding: "clamp(12px, 2vw, 24px)" }}>
      <section className="workbench-frame home-app-frame">
        <aside className="home-app-rail" aria-label="工作台侧栏">
          <Link className="home-brand" href="/" aria-label="Qiyan Nexus 首页" aria-current={isHome ? "page" : undefined}>
            <span className="home-brand-mark" aria-hidden="true">
              启
            </span>
            <span className="home-brand-copy">
              <span className="home-brand-title">Qiyan Nexus</span>
              <span className="home-brand-subtitle">Network Pharmacology Workbench</span>
            </span>
          </Link>

          <Link className="home-new-session" href="/network">
            <PlusOutlined aria-hidden="true" />
            <span>新建研究任务</span>
          </Link>

          <nav className="workbench-nav" aria-label="工作台导航">
            {navItems.map((item) => (
              <Link key={item.href} href={item.href} aria-current={currentHref === item.href ? "page" : undefined}>
                {item.label}
              </Link>
            ))}
          </nav>

          <section className="home-rail-signal" aria-label="科研门禁摘要">
            <div className="home-rail-signal-head">
              <SafetyCertificateOutlined aria-hidden="true" />
              <span>科研门禁</span>
              <strong>全部</strong>
            </div>
            {railSignals.map((signal) => (
              <Link className="home-rail-signal-item" href="/network" key={signal.title}>
                <span>{signal.title}</span>
                <small>{signal.time}</small>
              </Link>
            ))}
          </section>

          <div className="home-account-entry" aria-label="内部预览版说明">
            <UserOutlined aria-hidden="true" />
            <span>
              <strong>内部预览版</strong>
              <small>当前未开放账户登录</small>
            </span>
          </div>
        </aside>

        <div className={isHome ? "home-main-stack" : "workbench-main-stack"}>{children}</div>
      </section>
    </main>
  );
}
