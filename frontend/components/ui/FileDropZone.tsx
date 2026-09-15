// ABOUTME: 拖拽上传区（L2 原语，design.md §4.0）：把任意区域变成文件拖放目标——拖入时 accent 高亮，
// ABOUTME: drop 把文件数组交回调；不承载上传逻辑与文件校验（扩展名/类型的权威校验在调用方与服务端）。
// ABOUTME: dashed=true 渲染常驻虚线拾取框（上传资料页形态）；默认是隐形包装，仅拖拽悬停时显示虚线描边。
"use client";

import { useRef, useState, type CSSProperties, type DragEvent, type ReactNode } from "react";

export function FileDropZone({
  onFiles,
  disabled = false,
  dashed = false,
  style,
  children,
}: {
  /** 拖放的文件列表（非空才回调）；单文件场景由调用方自行取首个。 */
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  /** 常驻虚线拾取框形态（含居中内容）；false 时为隐形包装，仅拖拽悬停时高亮。 */
  dashed?: boolean;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const [active, setActive] = useState(false);
  // 子元素间的 dragenter/dragleave 会成对触发；计数归零才算真正离开区域。
  const depth = useRef(0);

  const reset = () => {
    depth.current = 0;
    setActive(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    reset();
    if (disabled) return;
    const files = Array.from(event.dataTransfer.files ?? []);
    if (files.length) onFiles(files);
  };

  const visual: CSSProperties = dashed
    ? {
        border: `1.5px dashed ${active ? "var(--accent)" : "var(--border-strong)"}`,
        borderRadius: "var(--radius-container)",
        background: active ? "var(--accent-subtle)" : "transparent",
        transition: "background .12s, border-color .12s",
      }
    : {
        borderRadius: "var(--radius-container)",
        outline: active ? "2px dashed var(--accent)" : "2px dashed transparent",
        outlineOffset: 4,
        background: active ? "var(--accent-subtle)" : "transparent",
        transition: "background .12s, outline-color .12s",
      };

  return (
    <div
      data-drop-active={active}
      onDragEnter={(event) => {
        event.preventDefault();
        if (disabled) return;
        depth.current += 1;
        setActive(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setActive(false);
      }}
      onDrop={handleDrop}
      style={{ ...visual, ...style }}
    >
      {children}
    </div>
  );
}
