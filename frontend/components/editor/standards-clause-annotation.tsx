// ABOUTME: 用户可见准则条款批注组件，展示附录索引表对应条款原文。
// ABOUTME: 批注仅用于前端可信性说明，不写入 Report 正文，不进入 Prompt 或 Word 导出。
"use client";

import type { CSSProperties } from "react";

import type { UserVisibleDisclosureClauseAnnotationEntry } from "@/lib/api";
import { interpolate } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";

const annotationStyle: CSSProperties = {
  borderLeft: "2px solid var(--border)",
  padding: "2px 0 2px 10px",
  margin: "4px 0 10px",
  color: "var(--muted-foreground)",
  fontSize: 12,
  lineHeight: 1.65,
  background: "transparent",
};

export function StandardsClauseAnnotation({ entry }: { entry: UserVisibleDisclosureClauseAnnotationEntry | null }) {
  const t = useT();
  if (!entry) return null;
  return (
    <details style={annotationStyle}>
      <summary style={{ cursor: "pointer", color: "var(--muted-foreground)" }}>
        {interpolate(t.documentNodes.clauseAnnotation, {
          topic: entry.reportContentTopicName,
          clauses: entry.appendixIndexClauseReferences.join(t.documentNodes.clauseSeparator),
        })}
      </summary>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        {entry.clauseOriginalTexts.map((item) => (
          <p key={item.clauseReference} style={{ margin: 0 }}>
            <strong>{item.clauseReference}</strong>　{item.clauseOriginalText}
          </p>
        ))}
      </div>
    </details>
  );
}
