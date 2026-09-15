// ABOUTME: Report Field 的统一前端控件，根据 Field.type 选择受限 HTML 输入类型。
// ABOUTME: 键入中间态只留在本地草稿；仅完整合法值（或清空）写回 Report，失焦时回退未完成草稿。
"use client";

import { useState, type CSSProperties } from "react";

import {
  fieldInputAttributes,
  isFieldDraftAllowed,
  isFieldValueAllowed,
  normalizeDecimalPaste,
} from "@/lib/input-validation";
import type { Field } from "@/lib/schema";

const DECIMAL_TYPES = new Set(["number", "percent", "year"]);

export function TypedFieldInput({
  field,
  id,
  value,
  onChange,
  className,
  style,
  ariaLabelledby,
  dataField,
}: {
  field: Field;
  id: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
  style?: CSSProperties;
  ariaLabelledby?: string;
  dataField?: string;
}) {
  const attributes = fieldInputAttributes(field.type);
  const [draft, setDraft] = useState(value);
  // render 期镜像受控值：committed 变化时直接对齐草稿，等价于原 effect，但不经历“旧草稿闪现一帧”。
  const [committed, setCommitted] = useState(value);
  if (committed !== value) {
    setCommitted(value);
    setDraft(value);
  }

  return (
    <input
      id={id}
      aria-labelledby={ariaLabelledby}
      data-field={dataField}
      value={draft}
      onChange={(event) => {
        const raw = event.target.value;
        const next = DECIMAL_TYPES.has(field.type) ? normalizeDecimalPaste(raw) : raw;
        if (!isFieldDraftAllowed(field.type, next)) return;
        setDraft(next);
        if (next === "" || isFieldValueAllowed(field.type, next)) onChange(next);
      }}
      onBlur={() => {
        if (draft !== "" && !isFieldValueAllowed(field.type, draft)) setDraft(value);
      }}
      className={className}
      style={style}
      {...attributes}
    />
  );
}
