// ABOUTME: 页尾生成区的轻量渲染回归——processing 为真时资料行显示处理中、主按钮置灰并给出 §7.1 既有原因；
// ABOUTME: 权益过期/未生效时禁用原因如实陈述，不误导为「必填未完成」。
// ABOUTME: mock 外部服务边界（app-context/account-context/active-report-scope/material-workspace-api/report-generation-api），组件本体真实渲染。
// @vitest-environment happy-dom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

// scope 与账户快照用可变 holder，用例内按需改写（过期/不可生成等分支）。
const scopeState = vi.hoisted(() => ({
  current: { status: "ready", materialAgentEnabled: true, canGenerate: true },
}));
vi.mock("@/lib/active-report-scope", () => ({
  activeReportScope: () => scopeState.current,
}));

/** 组件只读取 entitlement 的这三个字段；holder 显式标注类型，避免 ends_at 被推断成 null 字面量。 */
const accountState = vi.hoisted(() => ({
  current: {
    snapshot: {
      entitlement: { profile_id: "local_single_user@1", expired: false, ends_at: null },
    },
  } as { snapshot: { entitlement: { profile_id: string; expired: boolean; ends_at: string | null } } },
}));
vi.mock("@/lib/account-context", () => ({
  useAccount: () => accountState.current,
}));

const { fetchReportPreparation, createReportGeneration } = vi.hoisted(() => ({
  fetchReportPreparation: vi.fn(),
  createReportGeneration: vi.fn(),
}));

vi.mock("@/lib/material-workspace-api", () => ({
  fetchReportPreparation,
}));

vi.mock("@/lib/report-generation-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/report-generation-api")>()),
  createReportGeneration,
}));

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

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  scopeState.current = { status: "ready", materialAgentEnabled: true, canGenerate: true };
  accountState.current = {
    snapshot: {
      entitlement: { profile_id: "local_single_user@1", expired: false, ends_at: null },
    },
  };
});

describe("权益不可用时的禁用原因", () => {
  it("权益过期：如实说明过期，而不是误导为必填未完成", async () => {
    scopeState.current = { ...scopeState.current, canGenerate: false };
    accountState.current = {
      snapshot: {
        entitlement: { profile_id: "local_single_user@1", expired: true, ends_at: "2026-08-01T00:00:00Z" },
      },
    };
    // 即使准备投影判定已具备生成资格，过期仍是根本原因。
    fetchReportPreparation.mockResolvedValue(preparation);
    render(<GenerationSection intake={null} blockedFileCount={0} />);

    const button = (await screen.findByText("生成报告", { selector: "button" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(
      screen.getByText("「本机单用户」已过期，无法再生成报告；已填写内容仍可继续查看与编辑。"),
    ).toBeTruthy();
    expect(screen.queryByText("生成前还需完成必填信息")).toBeNull();
  });

  it("capability 尚未到达：说明正在读取权限，不误判为权益不可用", async () => {
    // 加载态的 canGenerate 同样为 false，但那是「还不知道」而非「权益不可用」。
    scopeState.current = { ...scopeState.current, status: "loading", canGenerate: false };
    fetchReportPreparation.mockResolvedValue(preparation);
    render(<GenerationSection intake={null} blockedFileCount={0} />);

    const button = (await screen.findByText("生成报告", { selector: "button" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("正在读取报告权限…")).toBeTruthy();
    expect(screen.queryByText("当前权益未生效，暂无法生成报告。")).toBeNull();
    expect(screen.queryByText("生成前还需完成必填信息")).toBeNull();
  });

  it("权益未生效且未过期：给出中性陈述，同样不误导为必填未完成", async () => {
    scopeState.current = { ...scopeState.current, canGenerate: false };
    fetchReportPreparation.mockResolvedValue(preparation);
    render(<GenerationSection intake={null} blockedFileCount={0} />);

    const button = (await screen.findByText("生成报告", { selector: "button" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("当前权益未生效，暂无法生成报告。")).toBeTruthy();
  });
});

describe("生成区的处理中置灰", () => {
  it("processing 为真时按钮 disabled、资料行显示正在处理并给出原因", async () => {
    fetchReportPreparation.mockResolvedValue(preparation);
    render(<GenerationSection intake={null} blockedFileCount={0} processing />);

    const button = (await screen.findByText("生成报告", { selector: "button" })) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText("资料正在处理，完成后即可生成。")).toBeTruthy();
    expect(screen.getByText("正在处理")).toBeTruthy();
  });

  it("processing 为假时按钮可点，资料行按快照如实陈述", async () => {
    fetchReportPreparation.mockResolvedValue(preparation);
    render(<GenerationSection intake={null} blockedFileCount={0} />);

    const button = (await screen.findByText("生成报告", { selector: "button" })) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    expect(screen.queryByText("资料正在处理，完成后即可生成。")).toBeNull();
    expect(screen.getByText("无上传资料")).toBeTruthy();
  });
});
