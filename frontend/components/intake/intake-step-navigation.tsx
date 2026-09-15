// ABOUTME: 分步准备上一步/下一步导航的唯一共享实现（design.md §3.1）：页脚 IntakeStepFooter 与选填页页首 NextStepLink 同源。
// ABOUTME: 步骤序列与位置解析归 lib/intake-steps 所有；本组件只做 token 化渲染，不推断顺序或资格。
// ABOUTME: footer 的"下一步"按钮强调级由页面声明——页内另有唯一主色主按钮时必须传 secondary（design.md §4）。
// ABOUTME: 末步（资料处理）自带页尾生成区与返回链接，本组件在末步不再重复渲染任何内容（避免与该页页尾重叠）。
"use client";

import Link from "next/link";
import { type CSSProperties } from "react";

import { useAppOptional } from "@/lib/app-context";
import { getIntakeSteps, resolveIntakeStep } from "@/lib/intake-steps";
import { interpolate } from "@/lib/i18n/dictionary";
import { stepShortLabel } from "@/lib/i18n/intake-step-copy";
import { useT } from "@/lib/i18n/locale-context";
import { useReportPreparation } from "@/components/shell/use-report-preparation";

export interface IntakeStepScope {
  collectsMaterialityAssessment: boolean;
  materialAgentEnabled: boolean;
}

const secondaryLinkStyle: CSSProperties = {
  width: "fit-content",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-control)",
  background: "var(--background)",
  color: "var(--foreground)",
  fontSize: "var(--text-label-size)",
  padding: "8px 16px",
  textDecoration: "none",
};

const primaryLinkStyle: CSSProperties = {
  width: "fit-content",
  border: "1px solid transparent",
  borderRadius: "var(--radius-control)",
  background: "var(--accent)",
  color: "var(--accent-foreground)",
  fontSize: "var(--text-label-size)",
  padding: "8px 18px",
  textDecoration: "none",
};

export function IntakeStepFooter({
  pathname,
  scope,
  nextEmphasis,
}: {
  pathname: string | null;
  scope: IntakeStepScope;
  nextEmphasis: "primary" | "secondary";
}) {
  const t = useT();
  // 报告级填报方式决定第 4 步是什么；与左栏步骤导航同源读服务端 preparation 投影，
  // 路由变化也重拉（填报方式切换不走保存路径）。
  const app = useAppOptional();
  const preparation = useReportPreparation(
    app?.activeReportId ?? null,
    `${app?.savedAt ?? 0}:${pathname ?? ""}`,
  );
  const steps = getIntakeSteps(scope, preparation?.primary_input_mode ?? null);
  const stepInfo = resolveIntakeStep(pathname, steps);
  if (!stepInfo) return null;
  const nextLinkStyle = nextEmphasis === "primary" ? primaryLinkStyle : secondaryLinkStyle;
  // 末步（materials 的资料处理、questions 的议题信息填写）不经本组件：
  // 那两页自带页尾生成区与返回链接（design.md §7.3）。
  // 本组件的消费者（基本信息/评分/定量信息）在当前步骤序列下 next 恒非空。
  return (
    <footer style={{ borderTop: "1px solid var(--border)", padding: "24px 0" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
        {stepInfo.previous ? (
          <Link href={stepInfo.previous.href} style={{ fontSize: "var(--text-label-size)", color: "var(--muted-foreground)", textDecoration: "none" }}>
            {interpolate(t.shell.previousStep, { step: stepShortLabel(t, stepInfo.previous.key) })}
          </Link>
        ) : (
          // 首步无「上一步」：不放「报告列表」折返（左栏「我的全部报告」已承担），留空占位保持下一步右对齐。
          <span aria-hidden />
        )}
        {stepInfo.next ? (
          <Link href={stepInfo.next.href} style={nextLinkStyle}>
            {interpolate(t.shell.nextStep, { step: stepShortLabel(t, stepInfo.next.key) })}
          </Link>
        ) : null}
      </div>
    </footer>
  );
}

/** 选填页（重要性评分、定量信息）页首右上角的「下一步」：与页脚下一步同一实现源——
 * 同一样式、同一措辞、同一步骤解析（design.md §3.1 选填页顶底同钮）。
 * 存在意义：让用户一进页就看到可以直接进入下一步，无须先把选填内容填完。 */
export function NextStepLink({ pathname, scope }: { pathname: string; scope: IntakeStepScope }) {
  const t = useT();
  const app = useAppOptional();
  const preparation = useReportPreparation(
    app?.activeReportId ?? null,
    `${app?.savedAt ?? 0}:${pathname}`,
  );
  const steps = getIntakeSteps(scope, preparation?.primary_input_mode ?? null);
  const next = resolveIntakeStep(pathname, steps)?.next ?? null;
  if (!next) return null;
  return (
    <Link href={next.href} style={primaryLinkStyle}>
      {interpolate(t.shell.nextStep, { step: stepShortLabel(t, next.key) })}
    </Link>
  );
}
