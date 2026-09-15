// ABOUTME: 生成模型选择器的渲染回归——单模型不出现选择器，多模型出现且选定值随请求下发。
// ABOUTME: mock 外部服务边界（app-context/account-context/scope/preparation/生成客户端/模型清单），组件本体真实渲染。
// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/app-context", () => ({
  useApp: () => ({
    activeReportId: "report-1",
    activeReportCapabilities: { material_agent_enabled: true },
  }),
}));

vi.mock("@/lib/active-report-scope", () => ({
  activeReportScope: () => ({
    status: "ready",
    materialAgentEnabled: true,
    canGenerate: true,
  }),
}));

vi.mock("@/lib/account-context", () => ({
  useAccount: () => ({
    snapshot: {
      entitlement: { profile_id: "local_single_user@1", expired: false, ends_at: null },
    },
  }),
}));

const { fetchReportPreparation, createReportGeneration, fetchGenerationModelOptions } =
  vi.hoisted(() => ({
    fetchReportPreparation: vi.fn(),
    createReportGeneration: vi.fn(),
    fetchGenerationModelOptions: vi.fn(),
  }));

vi.mock("@/lib/material-workspace-api", () => ({ fetchReportPreparation }));

vi.mock("@/lib/report-generation-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/report-generation-api")>()),
  createReportGeneration,
}));

vi.mock("@/lib/report-store", () => ({ fetchGenerationModelOptions }));

import { GenerationSection } from "./generation-section";

const preparation = {
  generation_eligible: true,
  generation_blockers: [],
  areas: [],
  report_state_seq: 3,
  assessment_partially_scored: false,
  assessment_scored_topic_count: 0,
  assessment_applicable_topic_count: 0,
  report_update_available: false,
};

function withModels(...ids: string[]) {
  fetchGenerationModelOptions.mockResolvedValue({
    models: ids.map((model_id) => ({ model_id, vendor: "vendor" })),
    default_model_id: ids[0] ?? "luna",
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("生成模型选择器", () => {
  it("只有一个可选模型时不出现选择器——没有可选项的选择器只是噪音", async () => {
    fetchReportPreparation.mockResolvedValue(preparation);
    withModels("luna");

    render(<GenerationSection intake={null} blockedFileCount={0} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "生成报告" })).toBeTruthy());
    expect(screen.queryByLabelText("选择生成模型")).toBeNull();
  });

  it("清单读取失败不阻断生成：不出现选择器，请求仍可发出（服务端用默认模型）", async () => {
    fetchReportPreparation.mockResolvedValue(preparation);
    fetchGenerationModelOptions.mockRejectedValue(new Error("offline"));

    render(<GenerationSection intake={null} blockedFileCount={0} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "生成报告" })).toBeTruthy());
    expect(screen.queryByLabelText("选择生成模型")).toBeNull();
  });

  it("多个可选模型时出现选择器，默认项不下发 model_id", async () => {
    fetchReportPreparation.mockResolvedValue(preparation);
    withModels("luna", "openai-compatible");
    createReportGeneration.mockResolvedValue({});

    render(<GenerationSection intake={null} blockedFileCount={0} />);

    const selector = await waitFor(() => screen.getByLabelText("选择生成模型"));
    expect((selector as HTMLSelectElement).value).toBe("");

    fireEvent.click(screen.getByRole("button", { name: "生成报告" }));

    await waitFor(() => expect(createReportGeneration).toHaveBeenCalled());
    // 第四个实参是模型：默认项为 null，客户端不复制一份默认值。
    expect(createReportGeneration.mock.calls[0]?.[3]).toBeNull();
  });

  it("选定非默认模型后，该 id 随生成请求下发", async () => {
    fetchReportPreparation.mockResolvedValue(preparation);
    withModels("luna", "openai-compatible");
    createReportGeneration.mockResolvedValue({});

    render(<GenerationSection intake={null} blockedFileCount={0} />);

    const selector = await waitFor(() => screen.getByLabelText("选择生成模型"));
    fireEvent.change(selector, { target: { value: "openai-compatible" } });
    fireEvent.click(screen.getByRole("button", { name: "生成报告" }));

    await waitFor(() => expect(createReportGeneration).toHaveBeenCalled());
    expect(createReportGeneration.mock.calls[0]?.[3]).toBe("openai-compatible");
  });
});
