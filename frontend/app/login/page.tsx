"use client";
// ABOUTME: 登录页（design.md 注册表 key=login）——邮箱与密码登录本机认证栈；账号由 ops.bootstrap_internal_accounts 建立。
// ABOUTME: 已持有会话也始终展示登录表单：进入工作台必须点击「登录」按钮，不做静默自动登录。
// ABOUTME: 产品权限由登录后的 Account 能力投影决定；认证失败统一提示（InlineAlert），不暴露账号是否存在。
import { useState } from "react";
import { useRouter } from "next/navigation";

import { accountButtonClass, accountInputClass } from "@/components/auth/account-access-frame";
import { BrandMark } from "@/components/brand/brand-mark";
import { PasswordField } from "@/components/auth/password-field";
import { InlineAlert } from "@/components/ui/InlineAlert";
import { useAuth } from "@/lib/auth-context";
import { useT } from "@/lib/i18n/locale-context";
import { signInErrorMessage, signInWithAccountPassword } from "@/lib/password-auth";
import { supabase } from "@/lib/supabase";

const fieldLabelStyle = {
  fontSize: "var(--text-label-size)",
  fontWeight: 500,
  color: "var(--foreground)",
} as const;

export default function LoginPage() {
  const router = useRouter();
  const { configured } = useAuth();
  const t = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn() {
    setError(null);
    setPending(true);
    const result = await signInWithAccountPassword(supabase().auth, {
      identifier: email.trim(),
      kind: "email",
      password,
    });
    setPending(false);
    const message = signInErrorMessage(result, t.login);
    if (message) {
      setError(message);
      return;
    }
    router.replace("/");
  }

  if (!configured) {
    return (
      <main
        data-screen-id="login"
        data-screen-label="登录"
        className="flex min-h-screen items-center justify-center px-6"
      >
        <div className="w-full max-w-[360px]">
          <div className="mb-8 flex justify-center">
            <BrandMark size={22} />
          </div>
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            {t.login.authUnconfigured}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main
      data-screen-id="login"
      data-screen-label="登录"
      className="flex min-h-screen items-center justify-center"
    >
      <div
        className="w-[400px]"
        style={{
          background: "var(--background)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-container)",
          padding: "32px 28px",
        }}
      >
        <div className="mb-8 flex justify-center">
          <BrandMark size={22} />
        </div>
        {/* 字标已显示产品名，标题不再复述——中性功能名较长，重复会挤占登录卡片。 */}
        <h1 className="text-lg font-medium" style={{ color: "var(--foreground)" }}>{t.login.heading}</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)" }}>
          {t.login.subheading}
        </p>
        <form
          className="mt-6 flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void signIn();
          }}
        >
            <div className="flex flex-col gap-1.5">
              <label htmlFor="login-email" style={fieldLabelStyle}>{t.login.email}</label>
              <input
                id="login-email"
                type="email"
                required
                autoFocus
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={accountInputClass}
              />
            </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="login-password" style={fieldLabelStyle}>{t.login.password}</label>
            <PasswordField
              id="login-password"
              autoComplete="current-password"
              value={password}
              onChange={setPassword}
            />
          </div>
          <button
            type="submit"
            disabled={pending || !email.trim() || !password}
            className={accountButtonClass}
          >
            {pending ? t.login.submitting : t.login.submit}
          </button>
        </form>
        {error ? (
          <InlineAlert variant="error" style={{ marginTop: 12 }}>
            {error}
          </InlineAlert>
        ) : null}
      </div>
    </main>
  );
}
