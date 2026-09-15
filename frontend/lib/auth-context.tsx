"use client";
// ABOUTME: 认证会话上下文——订阅 Supabase Auth 状态，向全局暴露 user/loading/signOut；不承载业务数据。
// ABOUTME: 后端显式声明 503（浏览器认证未配置）时进入 unconfigured 态（合法开发期降级）；其余失败视为初始化故障，authError 显式暴露。
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { ApiError } from "./api-error";
import { AUTH_NOT_CONFIGURED_HTTP_STATUS, configureSupabase, supabase } from "./supabase";

interface AuthContextValue {
  session: Session | null;
  loading: boolean;
  configured: boolean;
  /** 认证初始化真实故障（非"环境未配置"降级）的可读原因；受保护路由应据此显式报错而非静默放行或拦截。 */
  authError: string | null;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  session: null,
  loading: true,
  configured: false,
  authError: null,
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [configured, setConfigured] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let unsubscribe: (() => void) | undefined;
    void configureSupabase()
      .then(() => {
        if (!active) return;
        const auth = supabase().auth;
        return auth.getSession().then(({ data }) => {
          if (!active) return;
          setSession(data.session);
          setConfigured(true);
          setLoading(false);
          const { data: sub } = auth.onAuthStateChange((_event, next) => {
            // supabase 会以高频事件（INITIAL_SESSION、窗口聚焦校验、TOKEN_REFRESHED）推送新 session
            // 对象；引用无条件替换会让下游以 session 为依赖的 effect（如报告加载链）反复整树重载。
            // 仅在登录主体或访问令牌实质变化时更新引用。
            setSession((current) => {
              if (current === next) return current;
              if (
                current
                && next
                && current.access_token === next.access_token
                && current.user?.id === next.user?.id
              ) {
                return current;
              }
              return next;
            });
          });
          unsubscribe = () => sub.subscription.unsubscribe();
        });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setConfigured(false);
        setLoading(false);
        const isDeliberateDegrade = error instanceof ApiError
          && error.httpStatus === AUTH_NOT_CONFIGURED_HTTP_STATUS;
        if (!isDeliberateDegrade) {
          console.error("Auth runtime configuration initialization failed", error);
          setAuthError(
            error instanceof Error && error.message.trim() ? error.message.trim() : "认证初始化失败",
          );
        }
      });
    return () => {
      active = false;
      unsubscribe?.();
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      loading,
      configured,
      authError,
      signOut: async () => {
        await supabase().auth.signOut();
      },
    }),
    [session, loading, configured, authError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
