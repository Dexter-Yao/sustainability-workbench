// ABOUTME: 命令态键盘流的可编辑段落导航纯逻辑——按有序 blockId 列表计算 ↑↓ 选择移动。
// ABOUTME: 不触 DOM、不持有状态；段落顺序由 DocPane 从编辑器可编辑块派生后传入。design.md §5.5。

export type SelectionDirection = "up" | "down";

/**
 * ↑↓ 在可编辑段落间移动选择，到达两端不回绕。
 * 无当前选中：向下落到首段、向上落到末段；当前 id 不在序列时按方向落到对应端点。
 */
export function stepSelection(
  sequence: string[],
  current: string | null,
  direction: SelectionDirection,
): string | null {
  if (sequence.length === 0) return null;
  const index = current === null ? -1 : sequence.indexOf(current);
  if (index === -1) {
    return direction === "down" ? sequence[0] : sequence[sequence.length - 1];
  }
  const nextIndex = direction === "down" ? Math.min(index + 1, sequence.length - 1) : Math.max(index - 1, 0);
  return sequence[nextIndex];
}
