// ABOUTME: 素材图片承载块（layoutAssetSlot）投影——按 assetId 向后端取归一化原图，与 Word 导出同一图源。
// ABOUTME: 模块级 blob 缓存按资产去重；题注的数据源和写回由上层（素材图片元数据上下文）注入。

"use client";

import { useEffect, useRef, useState } from "react";

import { API_BASE } from "@/lib/api";
import { useT } from "@/lib/i18n/locale-context";

/** 同一资产在多处渲染（如同一份素材被多个块引用）共享同一次取图请求与结果。 */
const blobCache = new Map<string, Promise<Blob>>();

// 并发首次动态 import 同一模块存在竞态（部分调用方绕过 mock 命中真实模块），模块级单例化解析规避。
let supabaseModulePromise: Promise<typeof import("../../lib/supabase")> | null = null;
function supabaseModule(): Promise<typeof import("../../lib/supabase")> {
  supabaseModulePromise ??= import("../../lib/supabase");
  return supabaseModulePromise;
}

async function fetchLayoutAssetImage(reportId: string, assetId: string): Promise<Blob> {
  const { accessToken } = await supabaseModule();
  const token = await accessToken();
  if (!token) throw new Error("登录状态已失效，请重新登录");
  const res = await fetch(
    `${API_BASE}/api/reports/${encodeURIComponent(reportId)}/layout-assets/${encodeURIComponent(assetId)}/image`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!res.ok) throw new Error(`素材图片加载失败：HTTP ${res.status}`);
  return res.blob();
}

function cachedLayoutAssetImage(reportId: string, assetId: string): Promise<Blob> {
  const key = `${reportId}:${assetId}`;
  const cached = blobCache.get(key);
  if (cached) return cached;
  const promise = fetchLayoutAssetImage(reportId, assetId);
  blobCache.set(key, promise);
  promise.catch(() => blobCache.delete(key));
  return promise;
}

const placeholderBox: React.CSSProperties = {
  border: "1px dashed var(--border-strong)",
  borderRadius: "var(--radius-control)",
  minHeight: 120,
  display: "grid",
  placeItems: "center",
  color: "var(--muted-foreground)",
};

const captionTextStyle: React.CSSProperties = {
  fontSize: 13,
  color: "var(--foreground-secondary)",
  textAlign: "center",
  marginTop: 4,
};

function CaptionRow({
  caption,
  onCaptionChange,
}: {
  caption: string;
  onCaptionChange: (caption: string) => void | Promise<void>;
}) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(caption);
  const [error, setError] = useState<string | null>(null);
  // render 期镜像受控题注：caption 变化时直接对齐草稿并清空旧错误，等价于原 effect。
  const [prevCaption, setPrevCaption] = useState(caption);
  if (prevCaption !== caption) {
    setPrevCaption(caption);
    setDraft(caption);
    setError(null);
  }

  const commit = async () => {
    setEditing(false);
    const next = draft.trim();
    if (!next || next === caption) {
      setDraft(caption);
      return;
    }
    try {
      await onCaptionChange(next);
      setError(null);
    } catch {
      // 保留草稿供重试；静默回滚会让用户误以为已保存。
      setError(t.documentNodes.captionSaveFailed);
      setEditing(true);
    }
  };

  if (editing) {
    return (
      <>
        <input
          autoFocus
          value={draft}
          maxLength={50}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => {
            void commit();
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setDraft(caption);
              setError(null);
              setEditing(false);
            } else if (event.key === "Enter") {
              event.currentTarget.blur();
            }
          }}
          style={{
            fontSize: 13,
            color: "var(--foreground-secondary)",
            textAlign: "center",
            marginTop: 4,
            width: "100%",
            border: "none",
            borderBottom: "1px solid var(--border-strong)",
            background: "transparent",
          }}
        />
        {error ? <div role="alert" style={{ ...captionTextStyle, color: "var(--destructive)" }}>{error}</div> : null}
      </>
    );
  }

  return (
    <>
      <div onClick={() => setEditing(true)} style={{ ...captionTextStyle, cursor: "text" }}>
        {t.documentNodes.figureCaptionPrefix}{caption}
      </div>
      {error ? <div role="alert" style={{ ...captionTextStyle, color: "var(--destructive)" }}>{error}</div> : null}
    </>
  );
}

/** 素材图片承载块单图投影：assetId 取图 + 可选题注（数据源与写回由上层注入）。 */
export function LayoutAssetFigure({
  assetId,
  reportId,
  caption,
  onCaptionChange,
}: {
  assetId: string;
  reportId: string;
  caption?: string;
  onCaptionChange?: (caption: string) => void | Promise<void>;
}) {
  const t = useT();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const urlRef = useRef<string | null>(null);

  const fetchKey = `${reportId}:${assetId}`;
  // render 期复位：取图键变化时先清旧图/旧失败态再进 effect 发起新请求，等价于原效果开头的同步 reset。
  const [prevFetchKey, setPrevFetchKey] = useState(fetchKey);
  if (prevFetchKey !== fetchKey) {
    setPrevFetchKey(fetchKey);
    setUrl(null);
    setFailed(false);
  }

  useEffect(() => {
    let alive = true;
    cachedLayoutAssetImage(reportId, assetId)
      .then((blob) => {
        if (!alive) return;
        const next = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setUrl(next);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [reportId, assetId]);

  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  return (
    <div>
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={caption ?? t.documentNodes.assetAlt} style={{ display: "block", width: "100%", maxWidth: "100%", margin: "0 auto" }} />
      ) : failed ? (
        <div style={placeholderBox}>{t.documentNodes.assetUnavailable}</div>
      ) : (
        <div style={placeholderBox} />
      )}
      {caption ? (
        onCaptionChange ? (
          <CaptionRow caption={caption} onCaptionChange={onCaptionChange} />
        ) : (
          <div style={captionTextStyle}>{t.documentNodes.figureCaptionPrefix}{caption}</div>
        )
      ) : null}
    </div>
  );
}
