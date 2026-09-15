// ABOUTME: 交付物图标：文档轮廓 + 类型徽标区分 Word 正式稿与审阅版。
// ABOUTME: 纯装饰元素（aria-hidden），交付物语义由相邻文本承载，不依赖图标传达。
"use client";

import { useT } from "@/lib/i18n/locale-context";

/** 文档轮廓 + 类型徽标：word 为「W」，review（审阅版）的字符随界面语言取自字典。 */
export function ArtifactIcon({ kind }: { kind: "word" | "review" }) {
  const t = useT();
  return (
    <svg
      aria-hidden
      width="36"
      height="40"
      viewBox="0 0 36 40"
      style={{ flexShrink: 0 }}
    >
      {/* 文档轮廓（右上角折角） */}
      <path
        d="M6 3.5C6 2.12 7.12 1 8.5 1h14.9L30 7.6V34.5c0 1.38-1.12 2.5-2.5 2.5h-19A2.5 2.5 0 0 1 6 34.5v-31Z"
        fill="var(--background)"
        stroke="var(--border-strong)"
        strokeWidth="1.5"
      />
      <path
        d="M23.4 1v6.6H30"
        fill="none"
        stroke="var(--border-strong)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {/* 正文行 */}
      <line x1="10.5" y1="15" x2="25.5" y2="15" stroke="var(--border-strong)" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="10.5" y1="19.5" x2="25.5" y2="19.5" stroke="var(--border-strong)" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="10.5" y1="24" x2="20" y2="24" stroke="var(--border-strong)" strokeWidth="1.5" strokeLinecap="round" />
      {/* 类型徽标 */}
      <circle cx="12.5" cy="31" r="7" fill="var(--accent)" />
      <text
        x="12.5"
        y="31"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={kind === "word" ? 8 : 7.5}
        fontWeight={600}
        fill="var(--accent-foreground)"
        style={{ fontFamily: "inherit" }}
      >
        {kind === "word" ? "W" : t.artifactIcon.reviewGlyph}
      </text>
    </svg>
  );
}
