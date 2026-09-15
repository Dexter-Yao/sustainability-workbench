// ABOUTME: 登录后会话尚未传播时的账户上下文回归——不得把已知账户抹成「没有账户」。
// ABOUTME: 该假事实会让依赖账户的入口页所有分支落空，渲染成没有任何可操作组件的死页。
// @vitest-environment happy-dom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchCurrentAccount = vi.fn();
const authState = { configured: true, session: { access_token: "t" } as unknown };

vi.mock("./account", () => ({
  fetchCurrentAccount: () => fetchCurrentAccount(),
}));

vi.mock("./auth-context", () => ({
  useAuth: () => authState,
}));

import { AccountProvider, useAccount } from "./account-context";

function Probe() {
  const { snapshot, loading, error } = useAccount();
  return (
    <div>
      <span data-testid="snapshot">{snapshot ? "有账户" : "无账户"}</span>
      <span data-testid="loading">{loading ? "加载中" : "空闲"}</span>
      <span data-testid="error">{error ?? "无错误"}</span>
    </div>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  authState.configured = true;
  authState.session = { access_token: "t" } as unknown;
});

describe("账户上下文在会话滞后时的行为", () => {
  it("会话尚未到达时不把已知账户抹成「无账户」", async () => {
    // signInWithPassword 刚建立会话，auth-context 还没把它推进来。
    // 若 refresh 在 !session 时 setSnapshot(null)，调用方会据此认为用户没有账户。
    fetchCurrentAccount.mockResolvedValue({
      account: { id: "a1" },
      capabilities: { can_create_report: true },
    });
    render(
      <AccountProvider>
        <Probe />
      </AccountProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("snapshot").textContent).toBe("有账户"));

    // 会话短暂缺失（引用尚未同步）不得清空既有快照。
    authState.session = null;
    render(
      <AccountProvider>
        <Probe />
      </AccountProvider>,
    );
    await waitFor(() => expect(screen.getAllByTestId("snapshot")[0].textContent).toBe("有账户"));
  });

  it("未配置认证才是确定没有账户，此时清空是对的", async () => {
    authState.configured = false;
    authState.session = null;
    render(
      <AccountProvider>
        <Probe />
      </AccountProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("snapshot").textContent).toBe("无账户"));
    expect(fetchCurrentAccount).not.toHaveBeenCalled();
  });
});
