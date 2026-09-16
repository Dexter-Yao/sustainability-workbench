// ABOUTME: 双重重要性矩阵图（后端单一渲染源）——据评估结果请后端 PNG 显示，与 Word 导出同一图源(所见即所得)。
// ABOUTME: 评分页/编辑台共用；防抖请求、保留旧图避免闪烁、生成中显示等尺寸占位、失败回退 fallback；blob URL 卸载即回收。
// ABOUTME: visibleMaterialities 为视图级过滤（交互预览）；不传完整渲染，全分类隐藏时占位不发请求。
"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { fetchMatrixImage } from "@/lib/api";
import { useT } from "@/lib/i18n/locale-context";
import type { AssessmentResult, Materiality } from "@/lib/schema";

/** 矩阵图块 ID：与 report_contract.yaml 中 sm.matrix_image 一致。 */
export const MATRIX_IMAGE_BLOCK_ID = "sm.matrix_image";

export function MatrixImage({
  assessment,
  fallback = null,
  maxWidth = 520,
  visibleMaterialities,
}: {
  assessment: AssessmentResult | null | undefined;
  fallback?: ReactNode;
  maxWidth?: number;
  visibleMaterialities?: readonly Materiality[];
}) {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const urlRef = useRef<string | null>(null);
  const topicCount = assessment?.topics?.length ?? 0;
  const visibleKey = visibleMaterialities?.join(",") ?? "";
  const allHidden = visibleMaterialities !== undefined && visibleMaterialities.length === 0;

  // 评估变化（含拖阈值重分类）→ 防抖请求后端重渲染；保留旧图直到新图就绪，避免拖动时闪烁。
  // setState 仅在异步回调中调用（不在 effect 同步体内），无议题时由渲染层回退 fallback。
  useEffect(() => {
    if (!assessment || topicCount === 0 || allHidden) return;
    let alive = true;
    const timer = setTimeout(() => {
      fetchMatrixImage(
        assessment,
        visibleKey ? (visibleKey.split(",") as Materiality[]) : undefined,
      )
        .then((blob) => {
          if (!alive) return;
          const next = URL.createObjectURL(blob);
          if (urlRef.current) URL.revokeObjectURL(urlRef.current);
          urlRef.current = next;
          setUrl(next);
          setFailed(false);
        })
        .catch(() => {
          if (alive) setFailed(true);
        });
    }, 400);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [assessment, topicCount, allHidden, visibleKey]);

  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  if (topicCount > 0 && allHidden) {
    return (
      <div
        style={{
          width: "100%",
          maxWidth,
          aspectRatio: "1 / 1",
          margin: "0 auto",
          display: "grid",
          placeItems: "center",
          fontSize: 12,
          color: "var(--muted-foreground)",
        }}
      >
        {t.documentNodes.matrixAllHidden}
      </div>
    );
  }
  if (topicCount > 0 && url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt={t.documentNodes.matrixAlt}
        style={{ display: "block", width: "100%", maxWidth, margin: "0 auto" }}
      />
    );
  }
  if (topicCount > 0 && failed) {
    return <>{fallback ?? <span style={{ fontSize: 12, color: "var(--muted-foreground)" }}>{t.documentNodes.matrixFailed}</span>}</>;
  }
  if (topicCount > 0) {
    // 有评估、后端图生成中：等尺寸占位，避免草图先显示再被后端图覆盖（双图闪烁）与布局跳动。
    return (
      <div
        style={{
          width: "100%",
          maxWidth,
          aspectRatio: "1 / 1",
          margin: "0 auto",
          display: "grid",
          placeItems: "center",
          fontSize: 12,
          color: "var(--muted-foreground)",
        }}
      >
        {t.documentNodes.matrixLoading}
      </div>
    );
  }
  return <>{fallback}</>;
}
