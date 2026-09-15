// ABOUTME: 结构化输入草稿自动保存——payload 指纹判 dirty、1.5s 防抖、in-flight 串行 trailing，不重复提交未变更内容。
// ABOUTME: 首个启用态快照登记为基线（服务端已存内容的本地投影），仅浏览页面绝不写库；只有用户改动后才判 dirty。
// ABOUTME: 状态机 idle|dirty|saving|saved|conflict|error 由纯逻辑 AutosaveController 驱动；React 钩子只是订阅层，核心可脱离 DOM 单测。
import { useCallback, useEffect, useState } from "react";

export type AutosaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "error";

export const AUTOSAVE_DEBOUNCE_MS = 1500;

export interface AutosaveSnapshot {
  state: AutosaveState;
  error: string | null;
}

/**
 * 显式 flush() 的失败结果。调用方据 conflict 区分「他处已更新需重载」与一般写入失败，
 * 不再读取 React 快照——快照在已执行的 async 闭包里是上一次渲染的陈旧值。
 */
export class AutosaveFlushError extends Error {
  readonly conflict: boolean;

  constructor(message: string, conflict: boolean) {
    super(message);
    this.name = "AutosaveFlushError";
    this.conflict = conflict;
  }
}

/** 纯函数：payload 指纹化为可比较字符串；调用方保证 payload 内部字段顺序稳定（来自固定顺序的目录/清单构造）。 */
export function fingerprintPayload(payload: unknown): string {
  return JSON.stringify(payload);
}

export interface AutosaveControllerOptions<TPayload> {
  save: (payload: TPayload) => Promise<void>;
  isConflict: (error: unknown) => boolean;
  debounceMs?: number;
  onChange: (snapshot: AutosaveSnapshot) => void;
  /** 供测试注入受控计时器；默认 globalThis.setTimeout/clearTimeout。 */
  setTimeoutFn?: typeof setTimeout;
  clearTimeoutFn?: typeof clearTimeout;
}

/**
 * 结构化输入草稿自动保存的纯逻辑核心，不依赖 React：payload 变化即防抖排队；
 * 保存进行中新变化在完成后追加一次（trailing），不并发发起多个请求；
 * 指纹相同的重复触发直接跳过；冲突态下自动保存暂停，直到 resume()。
 */
export class AutosaveController<TPayload> {
  private options: AutosaveControllerOptions<TPayload>;
  private readonly setTimeoutFn: typeof setTimeout;
  private readonly clearTimeoutFn: typeof clearTimeout;
  private latestPayload: TPayload;
  private savedFingerprint: string | null = null;
  private lastNotifiedFingerprint: string | null = null;
  private inFlight = false;
  private trailingRequested = false;
  private pausedForConflict = false;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private snapshot: AutosaveSnapshot = { state: "idle", error: null };
  // 当前进行中（含随后追加的 trailing）保存的统一句柄；flush() 等调用方据此等到真正完成，
  // 而不是在撞见 in-flight 时提前返回——避免"保存全部"点击时早于真实写入完成就报告成功。
  private pendingSettlement: Promise<void> | null = null;
  // 最近一次保存的失败结果；成功即清空。flush() 据此把静默失败还原成调用方可捕获的异常，
  // 后台防抖保存则只更新快照，两者共用同一次真实写入结果。
  private lastSettledFailure: { conflict: boolean; message: string } | null = null;

  constructor(initialPayload: TPayload, options: AutosaveControllerOptions<TPayload>) {
    this.latestPayload = initialPayload;
    this.options = options;
    // 必须绑定 globalThis:裸引用 window.setTimeout 以本实例为 this 调用时,
    // 真实浏览器强制校验 receiver 并抛 "Illegal invocation"(jsdom 不校验,单测发现不了)。
    this.setTimeoutFn = options.setTimeoutFn ?? setTimeout.bind(globalThis);
    this.clearTimeoutFn = options.clearTimeoutFn ?? clearTimeout.bind(globalThis);
  }

  /** React 侧闭包（save/isConflict）随每次渲染变化；由订阅层在 effect 内同步，而非构造时用 ref 间接引用。 */
  updateCallbacks(save: AutosaveControllerOptions<TPayload>["save"], isConflict: AutosaveControllerOptions<TPayload>["isConflict"]): void {
    this.options = { ...this.options, save, isConflict };
  }

  private setSnapshot(next: AutosaveSnapshot): void {
    // 值相等短路：重复渲染或重复通知不得反复推送同值快照，否则会与订阅层互相触发更新循环。
    if (this.snapshot.state === next.state && this.snapshot.error === next.error) return;
    this.snapshot = next;
    this.options.onChange(next);
  }

  getSnapshot(): AutosaveSnapshot {
    return this.snapshot;
  }

  /** payload 变化通知；enabled=false 时不判定 dirty（如草稿为空、报告未就绪），但不清空既有状态。 */
  notify(payload: TPayload, enabled: boolean): void {
    this.latestPayload = payload;
    if (!enabled || this.pausedForConflict) return;
    const fingerprint = fingerprintPayload(payload);
    // 首个启用态快照 = 服务端已存内容的本地投影：登记为基线、不判 dirty。
    // 仅浏览页面绝不产生写入——否则会把空评分骨架（scores: []）写进报告状态，
    // 连带触发 plan 的评分完整性判定，使报告无法打开。
    if (this.savedFingerprint === null && this.lastNotifiedFingerprint === null) {
      this.savedFingerprint = fingerprint;
      return;
    }
    if (fingerprint === this.savedFingerprint) return;
    // 同一内容的重复通知（保存后重投影、订阅层重渲染带来的新引用）不重置防抖、不重复置 dirty，
    // 否则"通知 → 快照更新 → 重渲染 → 再通知"会构成无限更新循环，且保存永远等不到防抖到期。
    if (fingerprint === this.lastNotifiedFingerprint) return;
    this.lastNotifiedFingerprint = fingerprint;
    this.setSnapshot({ state: "dirty", error: null });
    if (this.debounceTimer) this.clearTimeoutFn(this.debounceTimer);
    this.debounceTimer = this.setTimeoutFn(() => {
      this.debounceTimer = null;
      void this.triggerSave();
    }, this.options.debounceMs ?? AUTOSAVE_DEBOUNCE_MS);
  }

  /** 触发一次保存并返回可等待句柄；in-flight 时加入 trailing 且句柄等到 trailing 真正完成。 */
  private triggerSave(): Promise<void> {
    if (this.inFlight) {
      this.trailingRequested = true;
      // pendingSettlement 此时必然非空（inFlight=true 由本方法或防抖回调设置时一并赋值）。
      return this.pendingSettlement ?? Promise.resolve();
    }
    const settlement = this.runSave();
    this.pendingSettlement = settlement;
    return settlement;
  }

  private async runSave(): Promise<void> {
    const fingerprint = fingerprintPayload(this.latestPayload);
    if (fingerprint === this.savedFingerprint) return;
    this.inFlight = true;
    this.setSnapshot({ state: "saving", error: null });
    try {
      await this.options.save(this.latestPayload);
      this.savedFingerprint = fingerprint;
      this.lastSettledFailure = null;
      this.setSnapshot({ state: "saved", error: null });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "自动保存失败";
      const conflict = this.options.isConflict(cause);
      // 后台自动保存不得把异常抛进未处理拒绝；失败结果改为落在受控快照上，
      // 由 flush() 的显式调用方（"保存全部"）读取后转成用户可见错误。
      this.lastSettledFailure = { conflict, message };
      if (conflict) {
        this.pausedForConflict = true;
        this.setSnapshot({ state: "conflict", error: message });
      } else {
        this.setSnapshot({ state: "error", error: message });
      }
    } finally {
      this.inFlight = false;
      if (this.trailingRequested) {
        this.trailingRequested = false;
        this.pendingSettlement = this.runSave();
        await this.pendingSettlement;
      }
    }
  }

  /**
   * 立即保存当前 payload（跳过防抖等待）；in-flight 时排入 trailing 并等到其真正完成再返回。
   * 本次写入失败（含 409 冲突）时抛出 AutosaveFlushError：显式保存必须让调用方看到失败，
   * 不得像后台自动保存那样只落快照——否则界面会在未落库时报告成功。
   */
  async flush(): Promise<void> {
    if (this.debounceTimer) {
      this.clearTimeoutFn(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.lastSettledFailure = null;
    await this.triggerSave();
    // 经方法读取：控制流分析看不到 runSave() 在 await 期间对该字段的重新赋值，
    // 直接读属性会被窄化成 null 而误报 never。
    const failure = this.takeSettledFailure();
    if (failure) {
      throw new AutosaveFlushError(failure.message, failure.conflict);
    }
  }

  /** 读取最近一次保存的失败结果（供 flush 判定）；不清空，快照仍是错误态的唯一展示源。 */
  private takeSettledFailure(): { conflict: boolean; message: string } | null {
    return this.lastSettledFailure;
  }

  /** 冲突态下调用方完成权威重载后调用，恢复自动保存判定。 */
  resume(): void {
    this.pausedForConflict = false;
    this.setSnapshot({ state: "idle", error: null });
  }

  /** 是否还有已通知但未落库的内容：防抖计时中或正在写入都算未落定。 */
  hasPendingWork(): boolean {
    if (this.pausedForConflict) return false;
    if (this.debounceTimer !== null || this.inFlight) return true;
    // 基线未建立（enabled 从未为真，如服务端输入尚未加载完成）= 从未有可落库的用户改动；
    // 不得让离开路径的 flushPending 强行保存——StrictMode 双挂载的模拟卸载会在数据
    // 就绪前触发它，使「当前页面未关联轻量版报告」错误常驻页面。
    if (this.savedFingerprint === null) return false;
    return fingerprintPayload(this.latestPayload) !== this.savedFingerprint;
  }

  /**
   * 立即提交尚未落库的草稿，不等待防抖；供离开页面（卸载、切走、刷新）时保底调用。
   * 与 flush() 的区别：本方法不抛出——离开路径上没有界面能承接错误，
   * 失败仍落快照并保留草稿，由下次进入页面时的读取回填决定最终呈现。
   */
  async flushPending(): Promise<void> {
    if (!this.hasPendingWork()) return;
    try {
      await this.flush();
    } catch {
      // 已在 runSave 内落快照；离开路径不再冒泡。
    }
  }

  dispose(): void {
    if (this.debounceTimer) {
      this.clearTimeoutFn(this.debounceTimer);
      this.debounceTimer = null;
    }
  }
}

export interface UseStructuredAutosaveOptions<TPayload> {
  /** 当前草稿投影；变化即可能触发防抖保存（指纹相同则跳过）。 */
  payload: TPayload;
  /** false 时不参与自动保存判定；不清空既有 saved/error 状态。
      必须表达「数据已就绪」（如服务端输入已加载），不得绑定「内容非空」——
      首个启用态快照会登记为基线，用户动作触发的启用会把该笔输入吞进基线。 */
  enabled: boolean;
  /** 实际提交；冲突信号由 isConflict 判定，其余异常一律落 error 态并保留草稿供重试。 */
  save: (payload: TPayload) => Promise<void>;
  /** 判定某次 save 失败是否为并发冲突（409）；冲突态暂停自动保存直到调用方显式 resume。 */
  isConflict: (error: unknown) => boolean;
  debounceMs?: number;
}

export interface UseStructuredAutosaveResult {
  state: AutosaveState;
  /** 冲突或失败态下最近一次捕获的错误消息，供横幅展示真实原因。 */
  error: string | null;
  /** 立即保存当前 payload（防抖、in-flight 均照常排队）；用于"保存全部"等显式操作。 */
  flush: () => Promise<void>;
  /** 冲突态下调用方完成权威重载后调用，恢复自动保存判定。 */
  resume: () => void;
}

/** React 订阅层：把 AutosaveController 的快照变化投影为组件状态，payload/enabled 变化时通知控制器。 */
export function useStructuredAutosave<TPayload>({
  payload,
  enabled,
  save,
  isConflict,
  debounceMs,
}: UseStructuredAutosaveOptions<TPayload>): UseStructuredAutosaveResult {
  const [snapshot, setSnapshot] = useState<AutosaveSnapshot>({ state: "idle", error: null });

  // 惰性初始化一次：controller 生命周期与组件实例绑定，不随 payload/enabled/闭包变化重建；
  // 首次构造捕获的 save/isConflict 只用于首次渲染前的窗口，随后每次渲染都经 effect 用 updateCallbacks 刷新。
  const [controller] = useState(
    () => new AutosaveController<TPayload>(payload, {
      save,
      isConflict,
      debounceMs,
      onChange: setSnapshot,
    }),
  );

  // 每次渲染后把最新闭包同步进 controller（effect 内允许，渲染阶段不得写可变状态）。
  useEffect(() => {
    controller.updateCallbacks(save, isConflict);
  });

  // 卸载（切换页面、路由跳转）时先提交未落库草稿再释放计时器：
  // 只清 timer 会把防抖窗口内刚输入的内容直接丢掉。
  useEffect(() => () => {
    void controller.flushPending();
    controller.dispose();
  }, [controller]);

  // 刷新、关闭标签页、切到后台：pagehide 是移动端与桌面端都可靠的最后时机，
  // visibilitychange:hidden 覆盖切到其他标签后才被系统回收的情形。
  useEffect(() => {
    if (typeof window === "undefined") return;
    const flushNow = () => {
      void controller.flushPending();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushNow();
    };
    window.addEventListener("pagehide", flushNow);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", flushNow);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [controller]);

  useEffect(() => {
    controller.notify(payload, enabled);
  }, [controller, payload, enabled]);

  const flush = useCallback(async () => {
    await controller.flush();
  }, [controller]);

  const resume = useCallback(() => {
    controller.resume();
  }, [controller]);

  return { state: snapshot.state, error: snapshot.error, flush, resume };
}
