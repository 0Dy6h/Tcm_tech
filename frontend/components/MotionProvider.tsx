"use client";

import { useLayoutEffect, useEffect, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { ConfigProvider } from "antd";

// Motion tokens (mimo-inspired, restrained): everyday ≤ .3s, entry uses ease-out-expo.
const motionTheme = {
  token: {
    motionDurationFast: "0.12s",
    motionDurationMid: "0.2s",
    motionDurationSlow: "0.3s",
    motionEaseOut: "cubic-bezier(0.16, 1, 0.3, 1)",
    motionEaseInOut: "cubic-bezier(0.4, 0, 0.2, 1)",
    motionEaseOutQuint: "cubic-bezier(0.23, 1, 0.32, 1)",
    motionEaseOutCirc: "cubic-bezier(0.16, 1, 0.3, 1)",
  },
};

const REVEAL_SELECTOR =
  ":is(.home-main-stack, .workbench-main-stack) > *, :is(.home-main-stack, .workbench-main-stack) :is(.ant-card, .task-card)";

// Isomorphic layout effect: useLayoutEffect on client (hide before paint), noop-safe on server.
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Reveal-on-enter: runs once per route change (keyed on pathname), never on data refresh/polling.
 * SSR-safe: content is fully visible in server HTML; only JS adds the hidden state.
 */
export function useRevealOnEnter(key: string) {
  useIsoLayoutEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;

    const all = Array.from(document.querySelectorAll<HTMLElement>(REVEAL_SELECTOR));
    // Skip already-revealed nodes and cards nested inside another reveal target (avoid double rise).
    const els = all.filter(
      (el) => !el.dataset.mRevealed && !all.some((other) => other !== el && other.contains(el)),
    );
    let batch = 0;
    const io = new IntersectionObserver(
      (entries) => {
        batch = 0;
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const el = entry.target as HTMLElement;
          el.style.setProperty("--i", String(Math.min(batch++, 5)));
          el.classList.add("is-in");
          // Drop reveal classes once settled so hover lift uses its own ≤.3s transition.
          el.addEventListener(
            "transitionend",
            () => {
              el.classList.remove("m-reveal", "is-in");
              el.style.removeProperty("--i");
            },
            { once: true },
          );
          io.unobserve(el);
        }
      },
      { rootMargin: "0px 0px -8% 0px" },
    );
    for (const el of els) {
      el.dataset.mRevealed = "1";
      el.classList.add("m-reveal");
      io.observe(el);
    }
    return () => io.disconnect();
  }, [key]);
}

export default function MotionProvider({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname() ?? "/";
  useRevealOnEnter(pathname);
  return <ConfigProvider theme={motionTheme}>{children}</ConfigProvider>;
}
