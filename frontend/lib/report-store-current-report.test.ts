// ABOUTME: 当前报告指针的同页订阅合同测试。
// ABOUTME: 报告列表写入指针后，AppProvider 必须立即收到变更，不能等待 pathname 或浏览器 storage 事件。
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  currentReportId,
  setCurrentReportId,
  subscribeCurrentReportId,
} from "./report-store";

function localStorageStub(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => {
      values.delete(key);
    },
    setItem: (key, value) => {
      values.set(key, value);
    },
  };
}

describe("current report pointer", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("notifies same-page subscribers when the report changes", () => {
    vi.stubGlobal("window", {
      localStorage: localStorageStub(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const accountId = "account-a";
    const listener = vi.fn();
    const unsubscribe = subscribeCurrentReportId(accountId, listener);

    setCurrentReportId(accountId, "report-b");

    expect(currentReportId(accountId)).toBe("report-b");
    expect(listener).toHaveBeenCalledOnce();
    unsubscribe();
  });

  it("notifies subscribers when the current report is cleared", () => {
    vi.stubGlobal("window", {
      localStorage: localStorageStub(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });
    const accountId = "account-a";
    setCurrentReportId(accountId, "report-a");
    const listener = vi.fn();
    const unsubscribe = subscribeCurrentReportId(accountId, listener);

    setCurrentReportId(accountId, null);

    expect(currentReportId(accountId)).toBeNull();
    expect(listener).toHaveBeenCalledOnce();
    unsubscribe();
  });

  it("does not expose one account's current report to another account", () => {
    vi.stubGlobal("window", {
      localStorage: localStorageStub(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    setCurrentReportId("account-a", "report-a");

    expect(currentReportId("account-a")).toBe("report-a");
    expect(currentReportId("account-b")).toBeNull();
  });
});
