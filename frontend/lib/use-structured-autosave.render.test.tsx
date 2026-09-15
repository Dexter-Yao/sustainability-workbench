// ABOUTME: useStructuredAutosave 的真实渲染回归：复现"每次渲染新 payload 引用"下的更新循环风险。
// ABOUTME: 若钩子在未保存 dirty 态对相同内容重复 setState，将触发 React 无限更新并在此失败。
// @vitest-environment happy-dom
import { act, cleanup, render, screen } from "@testing-library/react";
import { useMemo, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

import { useStructuredAutosave } from "./use-structured-autosave";

function Harness({ save }: { save: (payload: { rows: number[] }) => Promise<void> }) {
  const [rows, setRows] = useState<number[]>([]);
  // 模拟页面:payload 由 useMemo 派生;rows 变化才换引用。
  const payload = useMemo(() => ({ rows }), [rows]);
  const autosave = useStructuredAutosave({
    payload,
    // enabled 表达「数据已就绪」（合同要求）；挂载时的空 rows 登记为基线，不写库。
    enabled: true,
    save,
    isConflict: () => false,
    debounceMs: 50,
  });
  return (
    <div>
      <span data-testid="state">{autosave.state}</span>
      <button type="button" onClick={() => setRows((current) => [...current, current.length + 1])}>
        add
      </button>
    </div>
  );
}

/** 模拟自动保存成功后父级状态变化导致 payload 重算(内容相同、引用变化)的页面形态。 */
function ReprojectingHarness({ save }: { save: () => Promise<void> }) {
  const [tick, setTick] = useState(0);
  const [filled, setFilled] = useState(false);
  // 每次 tick 变化 payload 引用都变,内容只由 filled 决定——复现 setInput(state_seq) 后的重投影。
  const payload = { rows: filled ? [1] : [] };
  const autosave = useStructuredAutosave({
    payload,
    // enabled 表达「数据已就绪」（合同要求）；初始空投影是基线，fill 后才是用户改动。
    enabled: true,
    save: async () => {
      await save();
      setTick((current) => current + 1);
    },
    isConflict: () => false,
    debounceMs: 20,
  });
  return (
    <div>
      <span data-testid="state">{autosave.state}</span>
      <span data-testid="tick">{tick}</span>
      <button type="button" onClick={() => setFilled(true)}>fill</button>
    </div>
  );
}

describe("useStructuredAutosave 渲染回归", () => {
  it("键入后进入 dirty 并在防抖后保存一次,不产生更新循环", async () => {
    vi.useFakeTimers();
    const save = vi.fn().mockResolvedValue(undefined);
    render(<Harness save={save} />);
    const button = screen.getByRole("button", { name: "add" });
    await act(async () => {
      button.click();
    });
    expect(screen.getByTestId("state").textContent).toBe("dirty");
    await act(async () => {
      vi.advanceTimersByTime(60);
      await Promise.resolve();
    });
    expect(save).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("state").textContent).toBe("saved");
    vi.useRealTimers();
  });

  it("保存触发父级重投影(payload 引用变化)不重复保存、不循环", async () => {
    vi.useFakeTimers();
    const save = vi.fn().mockResolvedValue(undefined);
    render(<ReprojectingHarness save={save} />);
    await act(async () => {
      screen.getByRole("button", { name: "fill" }).click();
    });
    await act(async () => {
      vi.advanceTimersByTime(30);
      await Promise.resolve();
      await Promise.resolve();
    });
    // 再推进几轮计时器:若存在"重投影→dirty→再保存"循环,save 会被调用多次。
    await act(async () => {
      vi.advanceTimersByTime(200);
      await Promise.resolve();
    });
    expect(save).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("state").textContent).toBe("saved");
    vi.useRealTimers();
  });
});
