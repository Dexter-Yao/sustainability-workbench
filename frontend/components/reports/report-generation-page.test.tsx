// ABOUTME: 报告生成页回归——路由不依赖报告编辑上下文（REPORTLESS）：报告指针读账户当前指针、
// ABOUTME: 能力投影按需自取一次；成功后不在本页做权威状态重载（该职责归 AppProvider 路由进入时整树重载）。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/shell/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/lib/account-context", () => ({
  useAccount: () => ({
    snapshot: { account: { id: "account-1" } },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

const fetchLatestReportGeneration = vi.fn();
vi.mock("@/lib/report-generation-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/report-generation-api")>(
    "@/lib/report-generation-api",
  );
  return {
    ...actual,
    fetchLatestReportGeneration: (...args: unknown[]) => fetchLatestReportGeneration(...(args as [string])),
  };
});

vi.mock("@/lib/material-workspace-api", () => ({
  fetchReportPreparation: vi.fn(async () => ({ report_update_available: false })),
}));

const getReportState = vi.fn();
vi.mock("@/lib/report-store", () => ({
  currentReportId: () => "report-1",
  subscribeCurrentReportId: () => () => {},
  getReportState: (...args: unknown[]) => getReportState(...(args as [string])),
}));

import { ReportGenerationPage } from "./report-generation-page";

const runId = "00000000-0000-4000-8000-000000000002";
const reportId = "report-1";

function generation(overrides: Record<string, unknown> = {}) {
  return {
    contract: "sustainability_desk.report_generation.v1",
    run_id: runId,
    report_id: reportId,
    status: "running",
    base_report_state_seq: 1,
    result_report_state_seq: null,
    completed_block_count: 1,
    total_block_count: 4,
    summary: "正在依据当前输入形成报告。",
    events: [],
    artifacts: [],
    workbench_enabled: true,
    ...overrides,
  };
}

afterEach(cleanup);

beforeEach(() => {
  fetchLatestReportGeneration.mockReset();
  getReportState.mockReset();
  getReportState.mockResolvedValue({
    state: { version: 4 },
    state_seq: 9,
    contract_version: "contract-test@1",
    capabilities: {},
  });
});

describe("ReportGenerationPage（REPORTLESS）", () => {
  it("从账户当前报告指针读取报告，轮询观察 run 从运行中推进到成功", async () => {
    fetchLatestReportGeneration.mockResolvedValueOnce(generation({ status: "running" }));

    render(<ReportGenerationPage />);
    await screen.findByText("正在依据当前输入形成报告。");
    expect(fetchLatestReportGeneration).toHaveBeenCalledWith(reportId);

    fetchLatestReportGeneration.mockResolvedValueOnce(
      generation({
        status: "succeeded",
        completed_block_count: 4,
        result_report_state_seq: 2,
        summary: "报告已生成。",
      }),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2_600));
    });

    await screen.findByText("报告已生成。");
  });

  it("getReportState 只为能力投影取用一次；成功与手动刷新都不重载权威状态", async () => {
    fetchLatestReportGeneration.mockResolvedValueOnce(generation({ status: "running" }));

    render(<ReportGenerationPage />);
    await screen.findByText("正在依据当前输入形成报告。");

    fetchLatestReportGeneration.mockResolvedValue(
      generation({ status: "succeeded", completed_block_count: 4, result_report_state_seq: 2 }),
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2_600));
    });

    // 挂载于运行中状态时运行记录默认展开，刷新按钮直接可见。
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    });
    await act(async () => {
      await Promise.resolve();
    });

    // 仅 mount 时为能力投影调用一次；权威状态重载由 AppProvider 在进入编辑路由时完成。
    expect(getReportState).toHaveBeenCalledTimes(1);
    expect(getReportState).toHaveBeenCalledWith(reportId);
  });

});
