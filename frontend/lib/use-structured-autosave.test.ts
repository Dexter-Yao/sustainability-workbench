// ABOUTME: AutosaveController 纯逻辑状态机测试：指纹判 dirty、防抖、in-flight 串行 trailing、冲突暂停与 flush。
// ABOUTME: 不依赖 React 渲染；直接测纯逻辑核心，覆盖 use-structured-autosave.ts 的可单测部分。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AutosaveController, AUTOSAVE_DEBOUNCE_MS, fingerprintPayload } from "./use-structured-autosave";

describe("fingerprintPayload", () => {
  it("相同结构产生相同指纹，不同值产生不同指纹", () => {
    expect(fingerprintPayload({ a: 1, b: "x" })).toBe(fingerprintPayload({ a: 1, b: "x" }));
    expect(fingerprintPayload({ a: 1 })).not.toBe(fingerprintPayload({ a: 2 }));
  });
});

describe("AutosaveController", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeController<T>(overrides: {
    save?: (payload: T) => Promise<void>;
    isConflict?: (error: unknown) => boolean;
    initialPayload: T;
  }) {
    const snapshots: { state: string; error: string | null }[] = [];
    const controller = new AutosaveController<T>(overrides.initialPayload, {
      save: overrides.save ?? (async () => {}),
      isConflict: overrides.isConflict ?? (() => false),
      onChange: (snapshot) => snapshots.push({ ...snapshot }),
    });
    // 首个启用态快照只登记基线（服务端已存内容的本地投影），不判 dirty；
    // 各用例从「已建立基线」状态出发验证真实用户改动的保存行为。
    controller.notify(overrides.initialPayload, true);
    return { controller, snapshots };
  }

  it("基线未建立（数据未就绪）时 flushPending 不发起保存——StrictMode 双挂载不误报", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const snapshots: { state: string; error: string | null }[] = [];
    const controller = new AutosaveController<{ v: number }>({ v: 0 }, {
      save,
      isConflict: () => false,
      onChange: (snapshot) => snapshots.push({ ...snapshot }),
    });
    // 复刻 StrictMode 模拟卸载：仅有 enabled=false 的通知（服务端输入未加载），随即 flushPending。
    controller.notify({ v: 0 }, false);
    expect(controller.hasPendingWork()).toBe(false);
    await controller.flushPending();
    expect(save).not.toHaveBeenCalled();
    expect(snapshots).toEqual([]);
  });

  it("首个启用态快照登记为基线：仅浏览页面不产生任何写入", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller, snapshots } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS * 2);
    expect(save).not.toHaveBeenCalled();
    expect(snapshots).toEqual([]);
    expect(controller.hasPendingWork()).toBe(false);
  })

  it("payload 变化后进入 dirty，防抖到期后 saving 再 saved", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller, snapshots } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    expect(snapshots.at(-1)).toEqual({ state: "dirty", error: null });
    expect(save).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith({ v: 1 });
    expect(snapshots.at(-1)).toEqual({ state: "saved", error: null });
  });

  it("指纹相同的重复触发不发起保存", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller } = makeController<{ v: number }>({ save, initialPayload: { v: 1 } });

    // 与基线同值的通知不判 dirty、不保存。
    controller.notify({ v: 1 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).not.toHaveBeenCalled();

    controller.notify({ v: 2 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);

    // 指纹与已保存内容相同的重复通知，不应再次调用 save。
    controller.notify({ v: 2 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("防抖窗口内连续变化只在最后一次到期后保存一次", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS - 200);
    controller.notify({ v: 2 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS - 200);
    controller.notify({ v: 3 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith({ v: 3 });
  });

  it("保存进行中的新变化在完成后追加一次 trailing 保存，不并发发起", async () => {
    let resolveFirst: (() => void) | undefined;
    const save = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveFirst = resolve;
      }),
    );
    const { controller } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);

    // 保存仍 in-flight 时又发生变化：不应立刻发起第二次保存（防抖计时器会被跳过判定，因 in-flight）。
    controller.notify({ v: 2 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);

    resolveFirst?.();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save).toHaveBeenLastCalledWith({ v: 2 });
  });

  it("flush 在保存 in-flight 时等到 trailing 真正完成才返回，不提前报告成功", async () => {
    const resolvers: (() => void)[] = [];
    const save = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => {
        resolvers.push(resolve);
      }),
    );
    const { controller, snapshots } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);

    controller.notify({ v: 2 }, true);
    let flushSettled = false;
    const flushPromise = controller.flush().then(() => {
      flushSettled = true;
    });

    // 首次保存仍未 resolve：flush 不应提前返回，snapshot 也不应是 saved。
    await Promise.resolve();
    await Promise.resolve();
    expect(flushSettled).toBe(false);
    expect(snapshots.at(-1)?.state).not.toBe("saved");

    resolvers[0]?.();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    resolvers[1]?.();
    await flushPromise;

    expect(flushSettled).toBe(true);
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith({ v: 2 });
    expect(snapshots.at(-1)).toEqual({ state: "saved", error: null });
  });

  it("flush 跳过防抖立即保存", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await controller.flush();

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith({ v: 1 });
  });

  it("flush 在保存失败时抛出，不让调用方误报成功", async () => {
    const save = vi.fn().mockRejectedValue(new Error("评分保存失败"));
    const { controller, snapshots } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await expect(controller.flush()).rejects.toMatchObject({
      name: "AutosaveFlushError",
      message: "评分保存失败",
      conflict: false,
    });
    expect(snapshots.at(-1)).toEqual({ state: "error", error: "评分保存失败" });
  });

  it("flush 在 409 冲突时抛出 conflict=true，供调用方跳过成功提示", async () => {
    const save = vi.fn().mockRejectedValue(new Error("报告已在其他窗口更新"));
    const { controller } = makeController<{ v: number }>({
      save,
      isConflict: () => true,
      initialPayload: { v: 0 },
    });

    controller.notify({ v: 1 }, true);
    await expect(controller.flush()).rejects.toMatchObject({
      name: "AutosaveFlushError",
      conflict: true,
    });
  });

  it("后台防抖保存失败只落快照，不产生未处理拒绝", async () => {
    const save = vi.fn().mockRejectedValue(new Error("网络中断"));
    const { controller, snapshots } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    // 未 await 任何句柄：防抖回调内部必须自行吞掉异常，否则此处会抛出未处理拒绝。
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);

    expect(snapshots.at(-1)).toEqual({ state: "error", error: "网络中断" });
  });

  it("flush 成功后不再因上一次失败而抛出", async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error("临时失败"))
      .mockResolvedValue(undefined);
    const { controller } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await expect(controller.flush()).rejects.toThrow("临时失败");

    controller.notify({ v: 2 }, true);
    await expect(controller.flush()).resolves.toBeUndefined();
  });

  it("防抖未到期就离开页面时，flushPending 立即提交未落库草稿", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    // 防抖窗口内（此处一毫秒都没推进）用户切走：内容必须仍然落库。
    expect(save).not.toHaveBeenCalled();
    await controller.flushPending();

    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith({ v: 1 });
  });

  it("flushPending 在无未落库内容时不发多余请求", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);

    await controller.flushPending();
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("flushPending 不向离开路径抛出失败", async () => {
    const save = vi.fn().mockRejectedValue(new Error("网络中断"));
    const { controller, snapshots } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, true);
    await expect(controller.flushPending()).resolves.toBeUndefined();
    expect(snapshots.at(-1)).toEqual({ state: "error", error: "网络中断" });
  });

  it("冲突态暂停自动保存，resume 后恢复", async () => {
    const save = vi.fn().mockRejectedValue(new Error("报告已在其他窗口更新"));
    const { controller, snapshots } = makeController<{ v: number }>({
      save,
      isConflict: () => true,
      initialPayload: { v: 0 },
    });

    controller.notify({ v: 1 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);

    expect(snapshots.at(-1)).toEqual({ state: "conflict", error: "报告已在其他窗口更新" });

    // 冲突态下继续变化不应重新触发保存。
    controller.notify({ v: 2 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(1);

    controller.resume();
    expect(controller.getSnapshot()).toEqual({ state: "idle", error: null });

    const save2 = vi.fn().mockResolvedValue(undefined);
    // resume 后恢复自动保存判定：模拟真实调用方在权威重载后重建 payload 基线。
    controller.notify({ v: 3 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);
    expect(save).toHaveBeenCalledTimes(2);
    void save2;
  });

  it("非冲突错误落 error 态并保留可读原因", async () => {
    const save = vi.fn().mockRejectedValue(new Error("网络中断"));
    const { controller, snapshots } = makeController<{ v: number }>({
      save,
      isConflict: () => false,
      initialPayload: { v: 0 },
    });

    controller.notify({ v: 1 }, true);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);

    expect(snapshots.at(-1)).toEqual({ state: "error", error: "网络中断" });
  });

  it("enabled=false 时不判定 dirty，也不触发保存", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { controller, snapshots } = makeController<{ v: number }>({ save, initialPayload: { v: 0 } });

    controller.notify({ v: 1 }, false);
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS);

    expect(save).not.toHaveBeenCalled();
    expect(snapshots).toEqual([]);
  });
});

describe("默认计时器的 receiver 安全性", () => {
  it("默认路径调用计时器不得携带 controller 作为 this(真实浏览器会抛 Illegal invocation)", async () => {
    // jsdom 的 setTimeout 不校验 receiver;这里用严格替身模拟真实浏览器的行为。
    const realSetTimeout = globalThis.setTimeout;
    const realClearTimeout = globalThis.clearTimeout;
    function strictSetTimeout(this: unknown, ...args: Parameters<typeof setTimeout>) {
      if (this !== undefined && this !== globalThis) {
        throw new TypeError("Illegal invocation");
      }
      return realSetTimeout(...args);
    }
    function strictClearTimeout(this: unknown, ...args: Parameters<typeof clearTimeout>) {
      if (this !== undefined && this !== globalThis) {
        throw new TypeError("Illegal invocation");
      }
      return realClearTimeout(...args);
    }
    vi.stubGlobal("setTimeout", strictSetTimeout);
    vi.stubGlobal("clearTimeout", strictClearTimeout);
    try {
      const save = vi.fn().mockResolvedValue(undefined);
      const controller = new AutosaveController<string[]>([], {
        save,
        isConflict: () => false,
        onChange: () => undefined,
      });
      expect(() => controller.notify(["draft"], true)).not.toThrow();
      controller.dispose();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
