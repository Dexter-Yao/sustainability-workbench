// ABOUTME: 报告目录章节可见性与页内导航的真实渲染回归——服务端准备投影是唯一权威判定，投影缺席才退回字段临时判定。
// ABOUTME: 覆盖缺陷实证场景：reporting_year 为空但服务端判定最低生成信息已填写时，章节树不得静默消失。
// @vitest-environment happy-dom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Report } from "@/lib/schema";
import type { ReportPreparationProjection } from "@/lib/report-api.generated";

const { fetchReportPreparation } = vi.hoisted(() => ({
  fetchReportPreparation: vi.fn(),
}));

vi.mock("@/lib/material-workspace-api", () => ({ fetchReportPreparation }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/reports/document",
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("next/image", () => ({
  // eslint-disable-next-line @next/next/no-img-element
  default: (props: Record<string, unknown>) => <img {...(props as object)} alt="" />,
}));

function makeReport(fields: Record<string, string | null>): Report {
  return {
    fields: Object.fromEntries(
      Object.entries(fields).map(([key, value]) => [
        key,
        { key, label: key, type: "string", source: "user_input", value },
      ]),
    ),
    sections: [
      {
        key: "climate_change",
        title: "应对气候变化",
        reportSectionId: "climate_change",
        blocks: [],
        children: [],
      },
    ],
    intakeItems: [],
  } as unknown as Report;
}

const appState: {
  report: Report;
  activeReportCapabilities: unknown;
  activeReportId: string | null;
  savedAt: number | null;
} = {
  report: makeReport({}),
  activeReportCapabilities: null,
  activeReportId: null,
  savedAt: null,
};

vi.mock("@/lib/app-context", () => ({ useApp: () => appState }));
vi.mock("@/lib/account-context", () => ({ useAccount: () => ({ snapshot: null }) }));

const capabilities = {
  allowed_report_section_ids: ["climate_change"],
  allowed_quantitative_metric_keys: [],
  can_generate: true,
  can_regenerate_sections: true,
  can_export_word: true,
  material_agent_enabled: true,
  allowed_report_artifact_kinds: ["word"],
};

function makePreparation(
  identityStatus: "ready" | "needs_input",
): ReportPreparationProjection {
  return {
    contract: "sustainability_desk.report_preparation.v1",
    report_id: "9ca1a5db-38f8-4748-9b5f-c021dcdf97b7",
    report_state_seq: 3,
    generation_eligible: identityStatus === "ready",
    generation_blockers: [],
    areas: [
      {
        id: "report_identity",
        title: "企业及报告基本信息",
        href: "/intake/info",
        required_for_generation: true,
        status: identityStatus,
        summary:
          identityStatus === "ready"
            ? "最低生成信息已填写。"
            : "还有 2 项最低信息需要填写。",
        action_label: identityStatus === "ready" ? "查看或修改" : "填写基本信息",
      },
    ],
    report_update_available: false,
    workbench_enabled: false,
  };
}

const onSelectSection = vi.fn();

async function renderDirectory() {
  const { ReportDirectory } = await import("./ReportDirectory");
  return render(<ReportDirectory onSelectSection={onSelectSection} />);
}

describe("ReportDirectory 章节可见性", () => {
  beforeEach(() => {
    fetchReportPreparation.mockReset();
    appState.report = makeReport({
      company_short_name: "示例",
      company_registered_name: "示例科技有限公司",
      reporting_year: null,
    });
    appState.activeReportCapabilities = capabilities;
    appState.activeReportId = "9ca1a5db-38f8-4748-9b5f-c021dcdf97b7";
    appState.savedAt = null;
  });

  afterEach(() => {
    cleanup();
  });

  it("服务端判定最低生成信息已填写时，即使 reporting_year 为空也渲染章节树", async () => {
    fetchReportPreparation.mockResolvedValue(makePreparation("ready"));
    await renderDirectory();
    await waitFor(() => {
      expect(screen.getByText("应对气候变化")).toBeTruthy();
    });
  });

  it("点击章节把 Section.key 交给页面滚动，不自行路由", async () => {
    fetchReportPreparation.mockResolvedValue(makePreparation("ready"));
    await renderDirectory();
    const entry = await screen.findByText("应对气候变化");
    entry.closest("button")?.click();
    expect(onSelectSection).toHaveBeenCalledWith("climate_change");
  });

  it("服务端判定基本信息未就绪时隐藏章节树，但渲染同文案引导入口而非静默消失", async () => {
    fetchReportPreparation.mockResolvedValue(makePreparation("needs_input"));
    appState.report = makeReport({
      company_short_name: "示例",
      company_registered_name: "示例科技有限公司",
      reporting_year: "2025",
    });
    await renderDirectory();
    await waitFor(() => {
      expect(screen.getByText("还有 2 项最低信息需要填写。")).toBeTruthy();
    });
    expect(screen.queryByText("应对气候变化")).toBeNull();
    const guidance = screen.getByText("还有 2 项最低信息需要填写。").closest("a");
    expect(guidance?.getAttribute("href")).toBe("/intake/info");
  });

  it("投影不可用时退回已填字段判定：字段齐全则渲染章节树", async () => {
    fetchReportPreparation.mockRejectedValue(new Error("network down"));
    appState.report = makeReport({
      company_short_name: "示例",
      company_registered_name: "示例科技有限公司",
      reporting_year: "2025",
    });
    await renderDirectory();
    expect(await screen.findByText("应对气候变化")).toBeTruthy();
  });

  it("投影不可用且字段不全时渲染临时引导入口，不静默隐藏", async () => {
    fetchReportPreparation.mockRejectedValue(new Error("network down"));
    await renderDirectory();
    expect(
      await screen.findByText("填写企业名称和报告年度后展示报告章节。"),
    ).toBeTruthy();
    expect(screen.queryByText("应对气候变化")).toBeNull();
  });
});
