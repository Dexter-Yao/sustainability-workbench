// ABOUTME: 分步输入的页面外壳，提供步骤导航和前后跳转。
// ABOUTME: 本外壳不推断顺序、生成资格或必填范围，所有门禁由服务端准备投影拥有。
// ABOUTME: 遥测屏标签派生自步骤声明（intakeStepScreenLabel）；它是稳定标识、恒中文，
// ABOUTME: 与页面 h1 刻意不同源——h1 随界面语言变化，屏标签不得随之漂移。
"use client";

import { type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { AppShell } from "@/components/shell/AppShell";
import { IntakeStepFooter } from "@/components/intake/intake-step-navigation";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { intakeStepScreenLabel } from "@/lib/intake-steps";

/** 遥测屏 id 是稳定的内部标识，与步骤标签分列：标签派生自步骤声明，id 不随之漂移。 */
const SCREEN_IDS: Record<string, string> = {
  "/intake/info": "report-config",
  "/intake/scoring": "materiality-scoring",
  "/intake/metrics": "quantitative-intake",
  "/intake/input-path": "input-path",
  "/intake/questions": "topic-questions",
};

export default function IntakeLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { activeReportCapabilities } = useApp();
  const scope = activeReportScope(activeReportCapabilities);

  const stepScope = {
    collectsMaterialityAssessment: scope.collectsMaterialityAssessment,
    materialAgentEnabled: scope.materialAgentEnabled,
  };

  // 屏标签恒中文（design.md §7 注册表），与随界面语言变化的页面 h1 分离。
  // 不再在此特判；未登记子路径不落标签，也不双写。
  const pathKey = pathname ?? "";
  const screenId = SCREEN_IDS[pathKey] ?? SCREEN_IDS["/intake/info"];
  const screenLabel = pathKey in SCREEN_IDS ? intakeStepScreenLabel(pathKey) : "";

  // 页头（h1 + 进度 + 因果说明）由各步骤页面自渲染；保存态与步骤位置归全局顶栏（design.md §3.0）。
  return (
    <AppShell screenId={screenId} screenLabel={screenLabel} contentMaxWidth={1000}>
      <div style={{ padding: "4px 0" }}>{children}</div>

      {/* design.md §4 每屏唯一主色主按钮：intake 各步均无页内主按钮（草稿自动保存），
          footer「下一步」即唯一主操作，统一深绿主色。 */}
      <IntakeStepFooter pathname={pathname} scope={stepScope} nextEmphasis="primary" />
    </AppShell>
  );
}
