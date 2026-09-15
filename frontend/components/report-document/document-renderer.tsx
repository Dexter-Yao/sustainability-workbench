// ABOUTME: 把文档投影节点序列渲染成报告正文，并用 IntersectionObserver 把当前阅读到的章节回传给目录。
// ABOUTME: 只做节点分派与章节观测；选中/编辑状态经 ReportContext 下传，结构与议题数量无关。
// ABOUTME(en): Renders the document node sequence and reports the section currently in view to the directory.
// ABOUTME(en): Dispatches nodes only; selection and editing state arrive through ReportContext.
"use client";

import { useEffect, useRef } from "react";

import type { DocumentNode } from "@/lib/derive";

import { AnnotationBlock, HeadingBlock, ImageBlock, ParagraphBlock, TableBlock } from "./document-nodes";

function renderNode(node: DocumentNode, index: number) {
  switch (node.type) {
    case "heading":
      return <HeadingBlock key={`h:${node.sectionKey}`} node={node} />;
    case "paragraph":
      return <ParagraphBlock key={`p:${node.blockId}`} node={node} />;
    case "table":
      return <TableBlock key={`t:${node.blockId}`} node={node} />;
    case "image":
      return <ImageBlock key={`i:${node.blockId}`} node={node} />;
    case "standards_clause_annotation":
      return <AnnotationBlock key={`a:${node.sectionKey}:${index}`} node={node} />;
  }
}

export function DocumentRenderer({
  nodes,
  onActiveSectionChange,
}: {
  nodes: readonly DocumentNode[];
  onActiveSectionChange?: (sectionKey: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const callbackRef = useRef(onActiveSectionChange);
  useEffect(() => {
    callbackRef.current = onActiveSectionChange;
  }, [onActiveSectionChange]);

  // Track headings entering the upper part of the viewport; the first one in document order wins.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof IntersectionObserver === "undefined") return;
    const headings = [...container.querySelectorAll<HTMLElement>("[data-section-key]")];
    if (headings.length === 0) return;
    const visible = new Set<string>();
    const report = () => {
      const first = headings.find((heading) => visible.has(heading.dataset.sectionKey ?? ""));
      if (first) callbackRef.current?.(first.dataset.sectionKey ?? null);
    };
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const key = (entry.target as HTMLElement).dataset.sectionKey ?? "";
          if (entry.isIntersecting) visible.add(key);
          else visible.delete(key);
        }
        report();
      },
      { rootMargin: "-10% 0px -70% 0px", threshold: 0 },
    );
    for (const heading of headings) observer.observe(heading);
    return () => observer.disconnect();
  }, [nodes]);

  return (
    <div ref={containerRef} className="gs-report-document">
      {nodes.map(renderNode)}
    </div>
  );
}
