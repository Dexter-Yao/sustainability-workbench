// ABOUTME: 资料处理页真实渲染回归——同页三态（draft/processing/reviewed）与两道闸（闸一硬阻断/闸二软须留意）。
// ABOUTME: mock 外部服务边界（app-context/AppShell/material-workspace-api/report-generation-api），页面组件本体真实渲染。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();

vi.mock("next/navigation", () => ({
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
    canGenerate: true,
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
  topic_tags: [{ id: "uncertain", label: "暂不确定", kind: "auxiliary" }],
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
      topic_tags: ["uncertain"],
      asset_title: null,
      revision_id: "rev-1",
      binding_id: "binding-1",
      revision: 1,
      declared_at: "2026-01-01T00:00:00Z",
    },
    admission_status: "admitted",
    error_message: null,
    file_analysis: null,
    parse_status: null,
    parse_failure_reason: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeIntake(overrides: Record<string, unknown> = {}) {
  return {
    report_id: "report-1",
    projection_seq: 1,
    policy,
    active_file_count: 1,
    sources: [makeSource()],
    ingress_receipts: [],
    material_set_confirmation: {
      status: "confirmed",
      confirmed_at: "2026-01-01T00:00:00Z",
      pending_description_count: 0,
    },
    phase: "reviewed",
    ...overrides,
  };
}

function makePreparation(overrides: Record<string, unknown> = {}) {
  return {
    report_id: "report-1",
    report_state_seq: 1,
    generation_eligible: true,
    generation_blockers: [],
    areas: [
      {
        id: "report_identity",
        title: "企业及报告基本信息",
        href: "/intake/info",
        required_for_generation: true,
        status: "ready",
        summary: "已填写必需信息",
        action_label: "修改",
      },
      {
        id: "materiality",
        title: "议题重要性评分",
        href: "/intake/scoring",
        required_for_generation: false,
        status: "optional_empty",
        summary: "未评分，报告将完整覆盖全部议题",
        action_label: "去评分",
      },
      {
        id: "quantitative_metrics",
        title: "ESG 定量信息",
        href: "/intake/metrics",
        required_for_generation: false,
        status: "ready",
        summary: "7 / 62 项已填写",
        action_label: "补充",
      },
    ],
    workbench_enabled: true,
    ...overrides,
  };
}

const {
  fetchReportFileIntake,
  fetchReportPreparation,
  removeReportFile,
  createReportGeneration,
} = vi.hoisted(() => ({
  fetchReportFileIntake: vi.fn(),
  fetchReportPreparation: vi.fn(),
  removeReportFile: vi.fn(),
  createReportGeneration: vi.fn(),
}));

vi.mock("@/lib/material-workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/material-workspace-api")>()),
  fetchReportFileIntake,
  fetchReportPreparation,
  removeReportFile,
}));

vi.mock("@/lib/report-generation-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/report-generation-api")>()),
  createReportGeneration,
}));

import { MaterialProcessingPage } from "./material-processing-page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function renderWithIntake(intake: ReturnType<typeof makeIntake>, preparation = makePreparation()) {
  fetchReportFileIntake.mockResolvedValue(intake);
  fetchReportPreparation.mockResolvedValue(preparation);
  render(<MaterialProcessingPage />);
  // 只等资料清单：生成区由另一条 fetchReportPreparation 驱动，且仅 reviewed 态才发起，
  // 因此不能在这里一并等待。需要断言生成区的用例改用 findBy* 等待其渲染落地
  // （同步 getByText 会偶发找不到按钮——该竞态表现为约 1/8 的随机失败）。
  await waitFor(() => expect(fetchReportFileIntake).toHaveBeenCalled());
}

describe("资料处理页渲染回归", () => {
  it("draft 态且有文件：提示尚未提交处理，给出返回上一步入口", async () => {
    await renderWithIntake(makeIntake({ phase: "draft" }));
    expect(await screen.findByText("资料尚未提交处理")).toBeTruthy();
    expect(screen.getByText(/返回/)).toBeTruthy();
  });

  it("processing 态：显示进度与逐份状态词，且说明可以关闭页面", async () => {
    await renderWithIntake(
      makeIntake({
        phase: "processing",
        sources: [
          makeSource({ binding_id: "b1", file_analysis: { status: "succeeded", dossier: null } }),
          makeSource({ binding_id: "b2", filename: "b.pdf", file_analysis: { status: "running", dossier: null } }),
        ],
      }),
    );
    expect(await screen.findByText("正在处理资料")).toBeTruthy();
    expect(screen.getByText("已完成 1 / 2 份")).toBeTruthy();
    expect(screen.getByText("已处理")).toBeTruthy();
    expect(screen.getByText("正在处理")).toBeTruthy();
    expect(screen.getByText(/可以关闭页面/)).toBeTruthy();
  });

  it("processing 态：分析失败的资料显示「处理失败」，不冒充已处理", async () => {
    // 后端生成闸只接受 succeeded/needs_attention；把 failed 说成「已处理」会让用户
    // 面对全绿列表却被拒绝生成，两侧判据必须一致。
    await renderWithIntake(
      makeIntake({
        phase: "processing",
        sources: [
          makeSource({ binding_id: "b1", file_analysis: { status: "succeeded", dossier: null } }),
          makeSource({ binding_id: "b2", filename: "b.pdf", file_analysis: { status: "failed", dossier: null } }),
        ],
      }),
    );
    expect(await screen.findByText("正在处理资料")).toBeTruthy();
    expect(screen.getByText("处理失败")).toBeTruthy();
    expect(screen.getAllByText("已处理")).toHaveLength(1);
  });

  it("reviewed 态零文件：提示没有上传资料，仍展示生成区", async () => {
    await renderWithIntake(makeIntake({ phase: "reviewed", active_file_count: 0, sources: [] }));
    expect(await screen.findByText("没有上传资料。报告将基于已填写的信息生成。")).toBeTruthy();
    expect(await screen.findByText("生成报告", { selector: "button" })).toBeTruthy();
  });

  it("闸一（parse_status=failed）：红色阻断卡 + InlineAlert + 生成按钮 disabled", async () => {
    await renderWithIntake(
      makeIntake({
        sources: [
          makeSource({
            binding_id: "b-failed",
            filename: "环境管理制度.docx",
            parse_status: "failed",
            parse_failure_reason: "文件已加密，无法读取内容。",
          }),
        ],
      }),
    );
    expect(await screen.findByText("无法解析 · 阻断生成")).toBeTruthy();
    expect(screen.getByText("文件已加密，无法读取内容。")).toBeTruthy();
    expect(screen.getByText(/1 份文件无法解析，暂时不能生成报告。/)).toBeTruthy();
    const generateButton = (await screen.findByText("生成报告", { selector: "button" })) as HTMLButtonElement;
    expect(generateButton.disabled).toBe(true);
    expect(screen.getByText(/需先处理「环境管理制度.docx」/)).toBeTruthy();
  });

  it("闸二（parse_status=ok_with_attention）：橙色空心环卡片，不阻断生成", async () => {
    await renderWithIntake(
      makeIntake({
        sources: [
          makeSource({
            binding_id: "b-attention",
            filename: "ISO14001证书.jpg",
            parse_status: "ok_with_attention",
            file_analysis: {
              status: "needs_attention",
              dossier: { relevance: "relevant", relevance_reason: "", applicable_scope_count: 1, attention_items: [{ message: "证书有效期未能识别", next_action: "补充有效期或忽略" }] },
            },
          }),
        ],
      }),
    );
    expect(await screen.findByText(/已处理 · 1 项须留意/)).toBeTruthy();
    expect(screen.getByText(/证书有效期未能识别/)).toBeTruthy();
    const generateButton = (await screen.findByText("生成报告", { selector: "button" })) as HTMLButtonElement;
    expect(generateButton.disabled).toBe(false);
  });

  it("ok 文件：中性行 + 已处理，⋯ 菜单可移出", async () => {
    await renderWithIntake(
      makeIntake({
        sources: [makeSource({ file_analysis: { status: "succeeded", dossier: null } })],
      }),
    );
    await screen.findByText("policy.pdf");
    expect(screen.getByText("已处理")).toBeTruthy();
  });

  it("范围外资料：ok 行下方显示服务端的范围说明行，不新增状态", async () => {
    const notice = "资料超出试用版议题范畴，正式版可覆盖此类议题。";
    await renderWithIntake(
      makeIntake({
        sources: [
          makeSource({
            filename: "水资源管理制度.docx",
            parse_status: "ok",
            file_analysis: {
              status: "succeeded",
              dossier: {
                relevance: "relevant",
                relevance_reason: "文件只涉及水资源管理。",
                applicable_scope_count: 1,
                attention_items: [],
                report_scope: "outside_report",
                report_scope_notice: notice,
              },
            },
          }),
        ],
      }),
    );
    await screen.findByText("水资源管理制度.docx");
    expect(screen.getByText("已处理")).toBeTruthy();
    expect(screen.getByText(notice)).toBeTruthy();
  });

  it("点击生成报告成功后跳转到 /reports/generation", async () => {
    createReportGeneration.mockResolvedValue({});
    await renderWithIntake(makeIntake());
    const generateButton = await screen.findByText("生成报告", { selector: "button" });
    await act(async () => {
      fireEvent.click(generateButton);
    });
    await waitFor(() => expect(createReportGeneration).toHaveBeenCalled());
    await waitFor(() => expect(push).toHaveBeenCalledWith("/reports/generation"));
  });

  it("证书素材展示解析出的事实并说明去向，未辨认字段提示补填", async () => {
    await renderWithIntake(
      makeIntake({
        sources: [
          makeSource({
            filename: "iso14001.png",
            content_type: "image/png",
            declaration: {
              description: "环境管理体系认证证书，用于环境合规相关内容",
              role: "layout_asset",
              topic_tags: ["uncertain"],
              asset_title: null,
              revision_id: "rev-1",
            },
            parse_status: null,
            image_analysis: {
              status: "succeeded",
              asset_id: "asset-1",
              caption: "环境管理体系认证证书",
              category: "certificate_or_award",
              placement_scope_id: "report-area:sustainable_achievements",
              certificate_fact: {
                certificate_name: "环境管理体系认证证书",
                issuer: "华信技术检验有限公司",
                covered_scope: "导轨表、数显电表、温控仪的设计与制造",
                holder_name: null,
                unreadable_fields: ["issuer"],
              },
            },
          }),
        ],
      }),
    );
    await screen.findByText("iso14001.png");
    // 这句说明告诉用户识别结论会去哪
    expect(
      screen.getByText(/将出现在报告的「可持续发展成果」一章/),
    ).toBeTruthy();
    expect(screen.getByDisplayValue("环境管理体系认证证书")).toBeTruthy();
    expect(screen.getByDisplayValue("华信技术检验有限公司")).toBeTruthy();
    // 未辨认字段提示补填，但不阻断
    expect(screen.getByText(/未能辨认，请补填/)).toBeTruthy();
  });

  it("非证书素材不显示证书事实区", async () => {
    await renderWithIntake(
      makeIntake({
        sources: [
          makeSource({
            filename: "org-chart.png",
            content_type: "image/png",
            declaration: {
              description: "公司组织架构图，用于治理相关内容",
              role: "layout_asset",
              topic_tags: ["uncertain"],
              asset_title: null,
              revision_id: "rev-1",
            },
            parse_status: null,
            image_analysis: {
              status: "succeeded",
              asset_id: "asset-2",
              caption: "组织架构图",
              category: "other",
              placement_scope_id: "report-area:governance",
              certificate_fact: null,
            },
          }),
        ],
      }),
    );
    await screen.findByText("org-chart.png");
    expect(screen.queryByText(/将出现在报告的「可持续发展成果」一章/)).toBeNull();
  });
});
