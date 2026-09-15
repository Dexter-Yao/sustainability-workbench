// ABOUTME: ESG 定量指标摘要图前端预览——按 image.derivedVisualization 请求后端 PNG。
// ABOUTME: 与 Word 导出共用 metric_summary_chart，同源展示用户已填写的报告年度指标值。
"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { fetchMetricSummaryImage } from "@/lib/api";
import type { DerivedVisualizationSpec, Report } from "@/lib/schema";

export function MetricSummaryImage({
  report,
  spec,
  fallback = null,
  maxWidth = 760,
}: {
  report: Report;
  spec: DerivedVisualizationSpec;
  fallback?: ReactNode;
  maxWidth?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [empty, setEmpty] = useState(false);
  const [failed, setFailed] = useState(false);
  const urlRef = useRef<string | null>(null);
  const specKey = useMemo(() => JSON.stringify(spec), [spec]);

  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => {
      fetchMetricSummaryImage(report, spec)
        .then((blob) => {
          if (!alive) return;
          if (urlRef.current) {
            URL.revokeObjectURL(urlRef.current);
            urlRef.current = null;
          }
          if (!blob) {
            setUrl(null);
            setEmpty(true);
            setFailed(false);
            return;
          }
          const next = URL.createObjectURL(blob);
          urlRef.current = next;
          setUrl(next);
          setEmpty(false);
          setFailed(false);
        })
        .catch(() => {
          if (alive) setFailed(true);
        });
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [report, spec, specKey]);

  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  if (url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={url}
        alt="ESG 定量指标摘要"
        style={{ display: "block", width: "100%", maxWidth, margin: "0 auto" }}
      />
    );
  }
  if (failed) return <>{fallback}</>;
  if (empty) return <>{spec.emptyBehavior === "placeholder" ? fallback : null}</>;
  return (
    <div
      style={{
        width: "100%",
        maxWidth,
        aspectRatio: "5 / 1",
        margin: "0 auto",
        display: "grid",
        placeItems: "center",
        fontSize: 12,
        color: "var(--muted-foreground)",
      }}
    >
      指标图生成中...
    </div>
  );
}
