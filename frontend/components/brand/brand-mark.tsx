// ABOUTME: 产品文字字标：品牌图形资产随原主体退出，新名定稿前以文字呈现（design.md §2.10）。
// ABOUTME: 点击回到报告列表；不链接任何外部站点。
"use client";

import Link from "next/link";

import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";

export function BrandMark({
  compact = false,
  className = "",
  size = 16,
}: {
  compact?: boolean;
  className?: string;
  /** 字标字号（px）；认证页无顶栏、字标是页首唯一品牌锚点，用更大的尺寸。 */
  size?: number;
}) {
  const t = useT();
  return (
    <Link
      href="/"
      aria-label={interpolate(t.product.homeAria, { product: t.product.name })}
      className={`inline-flex items-center font-semibold tracking-tight text-[color:var(--accent)] hover:text-[color:var(--accent-hover)] ${compact ? "justify-center" : ""} ${className}`}
      style={{ fontSize: size, lineHeight: 1 }}
    >
      {compact ? t.product.markCompact : t.product.name}
    </Link>
  );
}
