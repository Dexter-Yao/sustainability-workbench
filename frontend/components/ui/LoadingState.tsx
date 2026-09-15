// ABOUTME: 加载状态原语（design.md §4）：页面级骨架屏、列表骨架、内容级/行内三点脉冲；
// ABOUTME: 不得只用裸文字「加载中…」代替骨架或 spinner。
"use client";

import type { CSSProperties } from "react";

const skeletonBar = (width: string, height = 16, opacity = 1): CSSProperties => ({
  height,
  width,
  background: "var(--surface-sunken)",
  borderRadius: "var(--radius-control)",
  opacity,
});

function PulseDots({ size = 6 }: { size?: number }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }} aria-hidden>
      {[0, 0.2, 0.4].map((delay) => (
        <span
          key={delay}
          className="gs-status-pulse"
          style={{
            display: "inline-block",
            width: size,
            height: size,
            borderRadius: "50%",
            background: "var(--accent)",
            animationDelay: `${delay}s`,
          }}
        />
      ))}
    </span>
  );
}

export function LoadingState({
  type = "content",
  text = "加载中…",
}: {
  type?: "page" | "content" | "inline" | "list";
  text?: string;
}) {
  if (type === "inline") {
    return (
      <span
        role="status"
        aria-label={text}
        style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
      >
        <PulseDots size={4} />
      </span>
    );
  }

  if (type === "page") {
    return (
      <div role="status" aria-label={text} className="gs-skeleton" style={{ display: "grid", gap: 16 }}>
        <div style={skeletonBar("75%")} />
        <div style={skeletonBar("50%")} />
        <div style={skeletonBar("83%")} />
      </div>
    );
  }

  if (type === "list") {
    return (
      <div role="status" aria-label={text} className="gs-skeleton" style={{ display: "grid", gap: 12 }}>
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 16,
              padding: "12px 0",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div style={{ display: "grid", gap: 8, flex: 1 }}>
              <div style={skeletonBar("33%")} />
              <div style={skeletonBar("25%", 12, 0.6)} />
            </div>
            <div style={skeletonBar("80px", 12)} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div role="status" style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 0" }}>
      <PulseDots />
      <span style={{ fontSize: "var(--text-body-size)", color: "var(--muted-foreground)" }}>{text}</span>
    </div>
  );
}
