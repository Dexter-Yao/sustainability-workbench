// ABOUTME: 登录页的账户访问页面外壳。
// ABOUTME: 只统一版式与返回入口，不承载认证或账户业务状态。
import { BrandMark } from "@/components/brand/brand-mark";

export function AccountAccessFrame({
  screenId,
  title,
  description,
  children,
}: {
  screenId: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <main
      data-screen-id={screenId}
      data-screen-label={title}
      className="flex min-h-screen items-center justify-center px-6 py-12"
    >
      <div className="w-full max-w-[400px]">
        <div className="mb-8 flex justify-center">
          <BrandMark size={22} />
        </div>
        <h1 className="text-xl font-medium" style={{ color: "var(--foreground)" }}>{title}</h1>
        <p className="mt-2 text-sm leading-6" style={{ color: "var(--muted-foreground)" }}>{description}</p>
        <div className="mt-6">{children}</div>
      </div>
    </main>
  );
}

export const accountInputClass =
  "gs-input h-10 w-full rounded-md border border-[color:var(--border)] px-3 text-sm";

export const accountButtonClass =
  "h-10 w-full rounded-md bg-[color:var(--accent)] px-4 text-sm text-[color:var(--accent-foreground)] disabled:opacity-40";
