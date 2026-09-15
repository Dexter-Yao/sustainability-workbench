// ABOUTME: 字符级文本差异的纯函数：比较生成稿与当前正文，产出等长/插入/删除三类片段供侧栏渲染。
// ABOUTME: 只做确定性 LCS，不解释语义；超出上限的长文退化为 null，由调用方改为「已修改」而非硬算。
// ABOUTME(en): Pure character-level text diff producing equal/insert/delete segments for the provenance panel.
// ABOUTME(en): Deterministic LCS only; texts beyond the size cap yield null so the caller falls back to "modified".

export type DiffSegmentKind = "equal" | "insert" | "delete";

export interface DiffSegment {
  kind: DiffSegmentKind;
  text: string;
}

/** Character budget per side; above this the O(n*m) table is not worth computing for a sidebar. */
export const TEXT_DIFF_MAX_CHARS = 4000;

/**
 * Diff two strings character by character. Returns null when either side exceeds the cap.
 * Adjacent characters of the same kind are merged into one segment.
 */
export function textDiff(before: string, after: string): DiffSegment[] | null {
  if (before.length > TEXT_DIFF_MAX_CHARS || after.length > TEXT_DIFF_MAX_CHARS) return null;
  const a = Array.from(before);
  const b = Array.from(after);
  const n = a.length;
  const m = b.length;
  // lengths[i][j] = LCS length of a[i:] and b[j:]
  const lengths: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      lengths[i][j] = a[i] === b[j]
        ? lengths[i + 1][j + 1] + 1
        : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }
  const segments: DiffSegment[] = [];
  const push = (kind: DiffSegmentKind, text: string) => {
    const last = segments[segments.length - 1];
    if (last && last.kind === kind) last.text += text;
    else segments.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push("equal", a[i]);
      i += 1;
      j += 1;
    } else if (lengths[i + 1][j] >= lengths[i][j + 1]) {
      push("delete", a[i]);
      i += 1;
    } else {
      push("insert", b[j]);
      j += 1;
    }
  }
  while (i < n) {
    push("delete", a[i]);
    i += 1;
  }
  while (j < m) {
    push("insert", b[j]);
    j += 1;
  }
  return segments;
}

/** True when the two texts differ at all; cheaper than a full diff for badges and counters. */
export function textChanged(before: string, after: string): boolean {
  return before !== after;
}
