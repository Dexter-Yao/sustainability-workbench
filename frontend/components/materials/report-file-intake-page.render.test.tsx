// ABOUTME: 上传资料页（阶段 1）真实渲染回归——两个上传区各自成区、投放即声明角色、两处填空可直接编辑、blur 保存分支、导航即提交与移出确认。
// ABOUTME: mock 外部服务边界（app-context/AppShell/material-workspace-api），页面组件本体真实渲染。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/materials",
  useRouter: () => ({ push, replace: vi.fn() }),
}));

vi.mock("@/components/shell/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
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
  }),
}));

const policy = {
  max_files_per_report: 30,
  max_file_bytes: 10 * 1024 * 1024,
  max_pdf_pages: 40,
  description_min_chars: 10,
  description_max_chars: 140,
  asset_title_max_chars: 100,
  semantic_material_kinds: ["pdf"],
  layout_asset_kinds: ["png"],
  semantic_material_extensions: [".pdf"],
  layout_asset_extensions: [".png"],
  topic_tags: [
    { id: "uncertain", label: "暂不确定", kind: "auxiliary" },
    { id: "climate_change", label: "应对气候变化", kind: "report_section" },
  ],
};

function makeSource(overrides: Record<string, unknown> = {}) {
  return {
    binding_id: "binding-1",
    source_id: "source-1",
    binding_status: "active",
    filename: "policy.pdf",
    content_type: "application/pdf",
    size_bytes: 2048,
    sha256: "abc",
    declaration: {
      description: "现行环境管理制度文件",
      role: "semantic_material",
      topic_tags: ["climate_change"],
      asset_title: null,
      revision_id: "rev-1",
      binding_id: "binding-1",
      revision: 1,
      declared_at: "2026-01-01T00:00:00Z",
    },
    admission_status: "admitted",
    error_message: null,
    file_analysis: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeLayoutSource(overrides: Record<string, unknown> = {}) {
  return makeSource({
    binding_id: "binding-2",
    source_id: "source-2",
    filename: "certificate.png",
    content_type: "image/png",
    declaration: {
      ...makeSource().declaration,
      description: "2024 年 ISO 14001 认证证书",
      role: "layout_asset",
      binding_id: "binding-2",
      revision_id: "rev-2",
    },
    image_analysis: null,
    ...overrides,
  });
}

function makeIntake(overrides: Record<string, unknown> = {}) {
  return {
    report_id: "report-1",
    projection_seq: 1,
    policy,
    active_file_count: 2,
    sources: [makeSource(), makeLayoutSource()],
    ingress_receipts: [],
    material_set_confirmation: {
      status: "not_required",
      confirmed_at: null,
      pending_description_count: 0,
    },
    phase: "draft",
    ...overrides,
  };
}

const {
  fetchReportFileIntake,
  updateReportFileDeclaration,
  updateReportFileSourceLabel,
  uploadReportFiles,
  confirmMaterialSet,
  removeReportFile,
  restoreReportFile,
  MaterialWorkspaceConflictError,
} = vi.hoisted(() => ({
  fetchReportFileIntake: vi.fn(),
  updateReportFileDeclaration: vi.fn(),
  updateReportFileSourceLabel: vi.fn(),
  uploadReportFiles: vi.fn(),
  confirmMaterialSet: vi.fn(),
  removeReportFile: vi.fn(),
  restoreReportFile: vi.fn(),
  MaterialWorkspaceConflictError: class MaterialWorkspaceConflictError extends Error {},
}));

// 只替换网络边界;selectReportFileIntakeSnapshot 用真实实现,序号守卫回归才有意义。
vi.mock("@/lib/material-workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/material-workspace-api")>()),
  fetchReportFileIntake,
  updateReportFileDeclaration,
  updateReportFileSourceLabel,
  uploadReportFiles,
  confirmMaterialSet,
  removeReportFile,
  restoreReportFile,
  MaterialWorkspaceConflictError,
}));

import { ReportFileIntakePage } from "./report-file-intake-page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderWithIntake(intake: ReturnType<typeof makeIntake>) {
  fetchReportFileIntake.mockResolvedValue(intake);
  render(<ReportFileIntakePage />);
  await waitFor(() => expect(fetchReportFileIntake).toHaveBeenCalled());
  await screen.findByLabelText("policy.pdf 的展示名");
}

describe("上传资料页渲染回归", () => {
  it("两处填空可直接编辑，且不展示任何处理结果", async () => {
    await renderWithIntake(makeIntake());
    expect(screen.getByLabelText("policy.pdf 的展示名")).toBeTruthy();
    expect(screen.getByLabelText("policy.pdf 的说明")).toBeTruthy();
    expect(screen.queryByText("编辑")).toBeNull();
    // 阶段 1 不得出现任何处理结论文案。
    expect(screen.queryByText(/资料已处理/)).toBeNull();
    expect(screen.queryByText(/正在处理/)).toBeNull();
    expect(screen.queryByText(/图片已处理/)).toBeNull();
  });

  it("两个上传区各自成区，文件按 declaration.role 归入所在区", async () => {
    await renderWithIntake(makeIntake());
    const semantic = screen.getByRole("region", { name: "报告资料" });
    const layout = screen.getByRole("region", { name: "图片素材" });
    expect(within(semantic).getByLabelText("policy.pdf 的展示名")).toBeTruthy();
    expect(within(semantic).queryByLabelText("certificate.png 的展示名")).toBeNull();
    expect(within(layout).getByLabelText("certificate.png 的展示名")).toBeTruthy();
    expect(within(layout).getByText("这张图是什么、希望放在哪类内容旁？", { exact: false })).toBeTruthy();
    // 各区白名单在区内自陈，合计上限只在页头说明一次。
    expect(within(semantic).getByText(".pdf")).toBeTruthy();
    expect(within(layout).getByText(".png")).toBeTruthy();
    expect(screen.getAllByText(/两区合计最多 30 份/)).toHaveLength(1);
  });

  it("投放到图片素材区的文件一律以 layout_asset 角色上传；不支持的格式具名拒绝、不跨区改投", async () => {
    const intake = makeIntake();
    uploadReportFiles.mockResolvedValue(intake);
    await renderWithIntake(intake);
    const input = screen.getByLabelText("选择图片素材") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, {
        target: { files: [new File(["a"], "award.png"), new File(["b"], "ledger.xlsx")] },
      });
    });
    await waitFor(() => expect(uploadReportFiles).toHaveBeenCalledTimes(1));
    const [reportId, files, declarations] = uploadReportFiles.mock.calls[0];
    expect(reportId).toBe("report-1");
    expect((files as File[]).map((file) => file.name)).toEqual(["award.png"]);
    expect(declarations).toEqual([
      { description: "", role: "layout_asset", topic_tags: ["uncertain"], asset_title: null },
    ]);
    expect(await screen.findByText(/ledger\.xlsx：不是「图片素材」支持的格式（\.png）/)).toBeTruthy();
  });

  it("投放到报告资料区的文件一律以 semantic_material 角色上传", async () => {
    const intake = makeIntake();
    uploadReportFiles.mockResolvedValue(intake);
    await renderWithIntake(intake);
    const input = screen.getByLabelText("选择报告资料") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, { target: { files: [new File(["a"], "handbook.pdf")] } });
    });
    await waitFor(() => expect(uploadReportFiles).toHaveBeenCalledTimes(1));
    expect(uploadReportFiles.mock.calls[0][2]).toEqual([
      { description: "", role: "semantic_material", topic_tags: ["uncertain"], asset_title: null },
    ]);
  });

  it("说明 blur 值未变不发 PATCH", async () => {
    await renderWithIntake(makeIntake());
    const field = screen.getByLabelText("policy.pdf 的说明");
    await act(async () => {
      fireEvent.blur(field);
    });
    expect(updateReportFileDeclaration).not.toHaveBeenCalled();
  });

  it("1–9 字 blur 不提交且显示“还差 N 字”", async () => {
    await renderWithIntake(makeIntake());
    const field = screen.getByLabelText("policy.pdf 的说明") as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(field, { target: { value: "太短了" } });
      fireEvent.blur(field);
    });
    expect(updateReportFileDeclaration).not.toHaveBeenCalled();
    expect(await screen.findByText("还差 7 字")).toBeTruthy();
  });

  it("≥10 字 blur 触发 updateReportFileDeclaration 且透传 role/asset_title/topic_tags 现值", async () => {
    const intake = makeIntake();
    updateReportFileDeclaration.mockResolvedValue(intake);
    await renderWithIntake(intake);
    const field = screen.getByLabelText("policy.pdf 的说明") as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(field, { target: { value: "全新的十个字以上说明内容" } });
      fireEvent.blur(field);
    });
    await waitFor(() => expect(updateReportFileDeclaration).toHaveBeenCalledTimes(1));
    expect(updateReportFileDeclaration).toHaveBeenCalledWith(
      "report-1",
      "binding-1",
      {
        description: "全新的十个字以上说明内容",
        role: "semantic_material",
        topic_tags: ["climate_change"],
        asset_title: null,
      },
      1,
    );
  });

  it("文件名 blur：空值回退不提交，变更触发 updateReportFileSourceLabel", async () => {
    const intake = makeIntake();
    await renderWithIntake(intake);
    const field = screen.getByLabelText("policy.pdf 的展示名") as HTMLInputElement;

    await act(async () => {
      fireEvent.change(field, { target: { value: "  " } });
      fireEvent.blur(field);
    });
    expect(updateReportFileSourceLabel).not.toHaveBeenCalled();
    expect(field.value).toBe("policy.pdf");

    updateReportFileSourceLabel.mockResolvedValue(intake);
    await act(async () => {
      fireEvent.change(field, { target: { value: "2025年环境管理制度.pdf" } });
      fireEvent.blur(field);
    });
    await waitFor(() =>
      expect(updateReportFileSourceLabel).toHaveBeenCalledWith("report-1", "binding-1", "2025年环境管理制度.pdf"),
    );
  });

  it("缺少说明的文件在元信息行标注「待填说明」，区头计数、页尾按钮 disabled 并显示缺说明数", async () => {
    await renderWithIntake(
      makeIntake({
        sources: [makeSource({ declaration: { ...makeSource().declaration, description: "" } })],
        material_set_confirmation: { status: "pending_description", confirmed_at: null, pending_description_count: 1 },
      }),
    );
    expect(screen.getByText(/待填说明/)).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "报告资料" })).getByText("1 份待补说明")).toBeTruthy();
    const button = screen.getByText("下一步：资料处理 →") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getAllByText("1 份缺少说明").length).toBeGreaterThan(0);
  });

  it("缺少说明的图片素材与语义资料同级阻断「下一步」", async () => {
    await renderWithIntake(
      makeIntake({
        sources: [
          makeSource(),
          makeLayoutSource({ declaration: { ...makeLayoutSource().declaration, description: "" } }),
        ],
        material_set_confirmation: { status: "pending_description", confirmed_at: null, pending_description_count: 1 },
      }),
    );
    expect(within(screen.getByRole("region", { name: "图片素材" })).getByText("1 份待补说明")).toBeTruthy();
    const button = screen.getByText("下一步：资料处理 →") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("说明齐备时点击「下一步：资料处理」触发 confirmMaterialSet 并跳转", async () => {
    const intake = makeIntake({
      material_set_confirmation: { status: "required", confirmed_at: null, pending_description_count: 0 },
    });
    confirmMaterialSet.mockResolvedValue({
      ...intake,
      material_set_confirmation: { status: "confirmed", confirmed_at: "2026-01-02T00:00:00Z", pending_description_count: 0 },
    });
    await renderWithIntake(intake);
    const button = screen.getByText("下一步：资料处理 →") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    await act(async () => {
      fireEvent.click(button);
    });
    await waitFor(() => expect(confirmMaterialSet).toHaveBeenCalledWith("report-1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/materials/processing"));
  });

  it("资料集已确认或零文件时点击「下一步」直接跳转，不重复调用 confirmMaterialSet", async () => {
    const intake = makeIntake({
      material_set_confirmation: { status: "confirmed", confirmed_at: "2026-01-01T00:00:00Z", pending_description_count: 0 },
    });
    await renderWithIntake(intake);
    const button = screen.getByText("下一步：资料处理 →") as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(button);
    });
    expect(confirmMaterialSet).not.toHaveBeenCalled();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/materials/processing"));
  });

  it("移出报告走 ConfirmDialog（<dialog> 承载），点击确认后才调用 removeReportFile", async () => {
    const intake = makeIntake();
    removeReportFile.mockResolvedValue({
      ...intake,
      sources: [{ ...makeSource(), binding_status: "removed" }, makeLayoutSource()],
    });
    await renderWithIntake(intake);
    const semantic = screen.getByRole("region", { name: "报告资料" });
    fireEvent.click(within(semantic).getByLabelText("更多操作"));
    fireEvent.click(within(semantic).getByRole("menuitem", { name: "移出报告" }));
    // 每行各自持有一个 ConfirmDialog；只在报告资料区内定位，避免命中图片素材行的对话框。
    const dialog = await within(semantic).findByRole("dialog", { hidden: true });
    const confirmButton = within(dialog).getByText("移出报告", { selector: "button" });
    // 菜单点击本身不触发移出:必须经过 ConfirmDialog 二次确认。
    expect(removeReportFile).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(confirmButton);
    });
    await waitFor(() => expect(removeReportFile).toHaveBeenCalledWith("report-1", "binding-1"));
  });

  it("blur 保存落地后，乱序到达的旧快照响应不回退界面", async () => {
    const stale = makeIntake();
    const saved = makeIntake({
      projection_seq: 2,
      sources: [makeSource({ source_label: "2026年环境台账.pdf" })],
    });
    fetchReportFileIntake.mockResolvedValue(stale);
    updateReportFileSourceLabel.mockResolvedValue(saved);
    updateReportFileDeclaration.mockRejectedValue(new MaterialWorkspaceConflictError("冲突"));
    render(<ReportFileIntakePage />);
    await screen.findByLabelText("policy.pdf 的展示名");

    const label = screen.getByLabelText("policy.pdf 的展示名") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(label, { target: { value: "2026年环境台账.pdf" } });
      fireEvent.blur(label);
    });
    await waitFor(() => expect(updateReportFileSourceLabel).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(label.value).toBe("2026年环境台账.pdf"));

    // 说明 blur 撞 409 触发重新拉取,而该响应仍是改名前的旧快照(projection_seq 1)。
    const description = screen.getByLabelText("policy.pdf 的说明") as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(description, { target: { value: "十个字以上的全新说明内容" } });
      fireEvent.blur(description);
    });
    await screen.findByText("说明已被其他操作更新，已刷新。");

    // 序号守卫必须丢弃旧快照:文件名不得回退为 policy.pdf。
    expect((screen.getByLabelText("policy.pdf 的展示名") as HTMLInputElement).value).toBe(
      "2026年环境台账.pdf",
    );
  });

  it("409 后 draft 重置并显示刷新提示", async () => {
    const intake = makeIntake();
    const refreshed = makeIntake({
      sources: [makeSource({ declaration: { ...makeSource().declaration, description: "服务端已更新的说明内容", revision: 2 } })],
    });
    updateReportFileDeclaration.mockRejectedValue(new MaterialWorkspaceConflictError("冲突"));
    fetchReportFileIntake.mockResolvedValueOnce(intake).mockResolvedValueOnce(refreshed);
    render(<ReportFileIntakePage />);
    await screen.findByLabelText("policy.pdf 的展示名");

    const field = screen.getByLabelText("policy.pdf 的说明") as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(field, { target: { value: "本地未提交的十个字以上说明" } });
      fireEvent.blur(field);
    });

    await screen.findByText("说明已被其他操作更新，已刷新。");
    await waitFor(() =>
      expect((screen.getByLabelText("policy.pdf 的说明") as HTMLTextAreaElement).value).toBe("服务端已更新的说明内容"),
    );
  });
});
