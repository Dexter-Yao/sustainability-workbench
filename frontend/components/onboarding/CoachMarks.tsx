// ABOUTME: 首次引导 coach mark（design.md §6.1）：每步至多 3 条、每条 ≤30 字、只讲界面里看不出来的事；
// ABOUTME: 状态存服务端 account.onboarding_seen[]（"all" 表示一键关停），锚定元素加光晕、深色浮层指向。
"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { useT } from "@/lib/i18n/locale-context";

import { useAccount } from "@/lib/account-context";
import { putOnboardingSeen } from "@/lib/account";

export const COACH_SKIP_ALL = "all";

export interface CoachMarkItem {
  /** 锚定元素的 DOM id；找不到时跳过该条。 */
  anchorId: string;
  /** ≤30 字，只讲「这个界面里你看不出来的事」，不讲业务概念。 */
  text: string;
}

export function CoachMarks({ stepKey, items }: { stepKey: string; items: CoachMarkItem[] }) {
  const t = useT();
  const { snapshot, refresh } = useAccount();
  const [index, setIndex] = useState(0);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const anchorRef = useRef<HTMLElement | null>(null);
  const seen = snapshot?.account.onboarding_seen ?? null;
  const active =
    seen !== null && !seen.includes(COACH_SKIP_ALL) && !seen.includes(stepKey) && index < items.length;

  const currentAnchorId = active ? items[index]?.anchorId : null;

  const locate = useCallback(() => {
    if (!currentAnchorId) {
      setAnchorRect(null);
      return;
    }
    const element = document.getElementById(currentAnchorId);
    if (anchorRef.current && anchorRef.current !== element) {
      anchorRef.current.classList.remove("gs-coach-halo");
    }
    anchorRef.current = element;
    if (!element) {
      setAnchorRect(null);
      return;
    }
    element.classList.add("gs-coach-halo");
    setAnchorRect(element.getBoundingClientRect());
  }, [currentAnchorId]);

  useEffect(() => {
    // 首帧需要同步测量锚点位置（DOM 外部系统读取），与 resize/scroll 回调共用同一 locate。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    locate();
    if (!currentAnchorId) return;
    window.addEventListener("resize", locate);
    window.addEventListener("scroll", locate, { capture: true, passive: true });
    return () => {
      window.removeEventListener("resize", locate);
      window.removeEventListener("scroll", locate, { capture: true });
      anchorRef.current?.classList.remove("gs-coach-halo");
    };
  }, [currentAnchorId, locate]);

  const persist = useCallback(
    async (nextSeen: string[]) => {
      try {
        await putOnboardingSeen(nextSeen);
        await refresh();
      } catch {
        // 引导状态保存失败只影响是否重放，不阻断填写；静默降级。
      }
    },
    [refresh],
  );

  if (!active) return null;

  // 找不到锚点的条目直接前进，不渲染悬空浮层。
  if (!anchorRect) {
    if (index < items.length - 1) {
      // 渲染期跳过：等 locate 失败后前进由「知道了」路径兜底；这里保持静默。
    }
    return null;
  }

  const advance = () => {
    if (index < items.length - 1) {
      setIndex(index + 1);
    } else {
      void persist([...(seen ?? []), stepKey]);
    }
  };

  const skipAll = () => {
    void persist([...(seen ?? []), COACH_SKIP_ALL]);
  };

  const top = Math.min(anchorRect.bottom + 10, window.innerHeight - 160);
  const left = Math.min(Math.max(anchorRect.left - 12, 12), window.innerWidth - 320);

  return (
    <div
      role="dialog"
      aria-label={t.reportConfig.coachAriaLabel}
      style={{
        position: "fixed",
        top,
        left,
        width: 300,
        background: "var(--foreground)",
        borderRadius: "var(--radius-container)",
        boxShadow: "var(--shadow-modal)",
        padding: "16px 18px",
        zIndex: 50,
      }}
    >
      <span
        aria-hidden
        style={{
          position: "absolute",
          top: -7,
          left: Math.min(Math.max(anchorRect.left + anchorRect.width / 2 - left - 7, 12), 270),
          width: 0,
          height: 0,
          borderLeft: "7px solid transparent",
          borderRight: "7px solid transparent",
          borderBottom: "7px solid var(--foreground)",
        }}
      />
      <div
        style={{
          fontSize: "var(--text-overline-size)",
          letterSpacing: ".06em",
          color: "var(--accent-subtle-border)",
          marginBottom: 8,
        }}
      >
        {index + 1} / {items.length}
      </div>
      <p
        style={{
          margin: "0 0 14px",
          fontSize: "var(--text-label-size)",
          lineHeight: 1.75,
          color: "var(--background)",
        }}
      >
        {items[index].text}
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <button
          type="button"
          onClick={advance}
          style={{
            border: "1px solid var(--background)",
            background: "var(--background)",
            color: "var(--foreground)",
            borderRadius: "var(--radius-control)",
            padding: "6px 14px",
            fontSize: "var(--text-label-size)",
            fontWeight: "var(--font-weight-medium)" as CSSProperties["fontWeight"],
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          {t.reportConfig.coachGotIt}
        </button>
        <button
          type="button"
          onClick={skipAll}
          style={{
            border: 0,
            background: "transparent",
            color: "var(--accent-subtle-border)",
            fontSize: "var(--text-label-size)",
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          {t.reportConfig.coachSkipAll}
        </button>
      </div>
    </div>
  );
}
