// ABOUTME: 单个段落的就地文本编辑器：与正文同排版的自增高 textarea，Esc/失焦/⌘Enter 提交一次编辑动作。
// ABOUTME: 只产出提交文本，不碰 Report；文本未变由调用方判定为无动作。
// ABOUTME(en): In-place editor for one paragraph: an auto-growing textarea with the body typography that commits on Esc, blur or ⌘Enter.
// ABOUTME(en): Emits the committed text only; the caller decides whether that becomes an edit action.
"use client";

import { useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";

// The body typography arrives as a prop: importing it from document-nodes would form an import
// cycle (document-nodes → block-text-editor → document-nodes) that breaks at module evaluation.
const editorStyle: CSSProperties = {
  display: "block",
  width: "100%",
  boxSizing: "border-box",
  margin: 0,
  padding: "6px 10px",
  border: "none",
  borderRadius: 6,
  outline: "none",
  resize: "none",
  overflow: "hidden",
  color: "var(--foreground)",
  background: "var(--background)",
  boxShadow: "inset 0 0 0 2px var(--ring), var(--shadow-card)",
  textIndent: "2em",
};

export function BlockTextEditor({
  initialText,
  ariaLabel,
  typography,
  onCommit,
}: {
  initialText: string;
  ariaLabel: string;
  /** Report body typography face, owned by document-nodes. */
  typography: CSSProperties;
  onCommit: (text: string) => void;
}) {
  const [text, setText] = useState(initialText);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const committed = useRef(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [text]);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.focus();
    element.setSelectionRange(element.value.length, element.value.length);
  }, []);

  const commit = () => {
    if (committed.current) return;
    committed.current = true;
    onCommit(text);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" || (event.key === "Enter" && (event.metaKey || event.ctrlKey))) {
      event.preventDefault();
      commit();
    }
  };

  return (
    <textarea
      ref={ref}
      aria-label={ariaLabel}
      value={text}
      rows={1}
      onChange={(event) => setText(event.target.value)}
      onKeyDown={onKeyDown}
      onBlur={commit}
      style={{ ...typography, ...editorStyle }}
    />
  );
}
