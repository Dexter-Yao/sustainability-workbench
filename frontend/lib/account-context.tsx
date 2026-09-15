// ABOUTME: 当前产品 Account 与服务端能力投影上下文，所有界面能力均从 GET /api/account 派生。
// ABOUTME: 会话变化时重新读取；上下文只做界面投影，后端仍对每个业务端点执行权威授权。
"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { fetchCurrentAccount, type AccountSnapshot } from "./account";
import { useAuth } from "./auth-context";

interface AccountContextValue {
  snapshot: AccountSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<AccountSnapshot | null>;
}

const AccountContext = createContext<AccountContextValue>({
  snapshot: null,
  loading: false,
  error: null,
  refresh: async () => null,
});

export function AccountProvider({ children }: { children: React.ReactNode }) {
  const { configured, session } = useAuth();
  const [snapshot, setSnapshot] = useState<AccountSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    // 未配置（本地开发降级）才是「确定没有账户」；此时清空快照是对的。
    if (!configured) {
      setSnapshot(null);
      setError(null);
      return null;
    }
    // 会话尚未传播到本上下文不等于用户没登录：signInWithPassword 刚建立会话时，
    // auth-context 的 onAuthStateChange 还没把它推进来，这里的 session 仍是旧闭包值。
    // 此时若清空快照并返回 null，调用方会拿到「没有账户」的假事实——依赖账户的入口页
    // 所有分支落空，渲染成只有说明文字、没有任何可操作组件的死页。
    // 保留既有快照、不改 error，让调用方按会话到达后的重试拿到真实结果。
    // 用 setter 形式读取当前值，避免把 snapshot 放进依赖数组——那会让 refresh 每次
    // 快照变化都重建，进而触发 effect 重新拉取，形成循环。
    if (!session) {
      let current: AccountSnapshot | null = null;
      setSnapshot((existing) => {
        current = existing;
        return existing;
      });
      return current;
    }
    setLoading(true);
    try {
      const next = await fetchCurrentAccount();
      setSnapshot(next);
      setError(null);
      return next;
    } catch (cause) {
      setSnapshot(null);
      setError(cause instanceof Error ? cause.message : "账户信息加载失败");
      return null;
    } finally {
      setLoading(false);
    }
  }, [configured, session]);

  useEffect(() => {
    void Promise.resolve().then(refresh);
  }, [refresh]);

  const value = useMemo(
    () => ({ snapshot, loading, error, refresh }),
    [snapshot, loading, error, refresh],
  );
  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}

export function useAccount(): AccountContextValue {
  return useContext(AccountContext);
}
