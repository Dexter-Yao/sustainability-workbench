// ABOUTME: 提示图标 ⓘ 的唯一实现（design.md §2.8.1）：指针端 hover 即显、移开即消，触摸端点击开合，
// ABOUTME: Esc/滚动/outside-click 均可关闭，全局单例；浮层白底 + --shadow-overlay，近右缘自动翻转。
"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

/** 全局单例：同一时刻只允许一个 Hint 打开。 */
let closeActiveHint: (() => void) | null = null;

const OPEN_DELAY_MS = 120;
const CLOSE_DELAY_MS = 80;

export function Hint({
  content,
  id,
  label = "查看说明",
  style,
}: {
  /** 浮层内容；≤80 字 / 3 行，不得含链接、按钮或表单控件（那是 Popover，不是 Hint）。 */
  content: ReactNode;
  /** 浮层元素 id，供字段 aria-describedby 引用。 */
  id?: string;
  label?: string;
  style?: CSSProperties;
}) {
  const fallbackId = useId();
  const tooltipId = id ?? fallbackId;
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  // 触摸/指针分支：SSR 与首帧按指针渲染，挂载后按 matchMedia 校正（同 AppShell 折叠态先例）。
  const [hoverCapable, setHoverCapable] = useState(true);
  const rootRef = useRef<HTMLSpanElement>(null);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHoverCapable(window.matchMedia("(hover: hover)").matches);
  }, []);

  const clearTimers = () => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    openTimer.current = null;
    closeTimer.current = null;
  };

  const close = useCallback(() => {
    clearTimers();
    setOpen(false);
    // 不清 registry：已关闭 Hint 的 close 幂等，残留注册由下一次 show 覆盖。
  }, []);

  const show = useCallback(() => {
    if (closeActiveHint && closeActiveHint !== close) closeActiveHint();
    closeActiveHint = close;
    const rect = rootRef.current?.getBoundingClientRect();
    setAlignRight(rect ? rect.left + 274 > window.innerWidth : false);
    setOpen(true);
  }, [close]);

  const scheduleOpen = () => {
    clearTimers();
    openTimer.current = window.setTimeout(show, OPEN_DELAY_MS);
  };

  const scheduleClose = () => {
    clearTimers();
    closeTimer.current = window.setTimeout(close, CLOSE_DELAY_MS);
  };

  // 打开期间的全局关闭路径：Esc（任意焦点位置）、滚动（立即）、触摸端 outside-click。
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const onScroll = () => close();
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("scroll", onScroll, { capture: true });
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open, close]);

  useEffect(() => clearTimers, []);

  return (
    <span
      ref={rootRef}
      style={{ position: "relative", display: "inline-flex", verticalAlign: "middle", ...style }}
      onMouseEnter={() => {
        if (hoverCapable) scheduleOpen();
      }}
      onMouseLeave={() => {
        if (hoverCapable) scheduleClose();
      }}
    >
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? tooltipId : undefined}
        onClick={() => {
          if (!hoverCapable) {
            if (open) close();
            else show();
          }
        }}
        onFocus={() => {
          if (hoverCapable) show();
        }}
        onBlur={close}
        style={{
          // 命中区 ≥32px（指针）/≥44px（触摸）由透明 padding 扩展；视觉仍是 15px 圆（子元素）。
          width: hoverCapable ? 32 : 44,
          height: hoverCapable ? 32 : 44,
          margin: hoverCapable ? -8 : -14,
          padding: 0,
          border: 0,
          background: "transparent",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "help",
        }}
      >
        <span
          aria-hidden
          style={{
            width: 15,
            height: 15,
            border: `1px solid ${open ? "var(--accent)" : "var(--border-strong)"}`,
            borderRadius: "50%",
            background: open ? "var(--accent-subtle)" : "var(--background)",
            color: open ? "var(--accent)" : "var(--muted-foreground)",
            fontSize: "10px",
            fontWeight: "var(--font-weight-semibold)" as CSSProperties["fontWeight"],
            lineHeight: "13px",
            textAlign: "center",
            display: "inline-block",
          }}
        >
          i
        </span>
      </button>
      {open ? (
        <span
          id={tooltipId}
          role="tooltip"
          style={{
            position: "absolute",
            zIndex: 30,
            top: 20,
            ...(alignRight ? { right: -4 } : { left: -4 }),
            width: "max-content",
            maxWidth: 270,
            padding: "9px 11px",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-container)",
            background: "var(--hint-surface)",
            boxShadow: "var(--shadow-overlay)",
            color: "var(--hint-foreground)",
            fontSize: "var(--text-supporting-size)",
            fontWeight: 400,
            lineHeight: 1.65,
            transition: "opacity .12s ease",
          }}
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}
