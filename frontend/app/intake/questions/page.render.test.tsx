// ABOUTME: 议题信息填写页的真实渲染回归——「生成前需要确认」区只认服务端 required_for_generation；
// ABOUTME: 图片素材区是该路径唯一的素材入口（只开放 layout_asset），服务端 phase=processing 时生成区收到 processing。
// @vitest-environment happy-dom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/intake/questions",
}));

const report = {
  title: "报告",
  sections: [{ key: "climate", title: "应对气候变化", reportSectionId: "climate_change", children: [] }],
  intakeItems: [
    {
      key: "climate.q_climate_risk_choices",
      prompt: "哪些气候相关风险会对公司产生影响？",
      kind: "multi_select",
      options: ["台风"],
      contentScopeId: "climate_change",
      requiredBefore: "generation",
      answer: null,
    },
    {
      key: "climate.q_training_activities",
      prompt: "是否开展过气候相关培训？",
      kind: "single_select",
      options: ["是"],
      contentScopeId: "climate_change",
      answer: null,
    },
  ],
};

vi.mock("@/lib/app-context", () => ({
  useApp: () => ({
    report,
    activeReportId: "report-1",
    activeReportCapabilities: { report_profile_id: "sse_zh_hans@1" },
  }),
}));

const scope = vi.hoisted(() => ({ status: "ready", materialAgentEnabled: true }));

vi.mock("@/lib/active-report-scope", () => ({
  activeReportScope: () => scope,
}));

const generationSectionProps = vi.hoisted(() => vi.fn());

vi.mock("@/components/intake/generation-section", () => ({
  GenerationSection: (props: { processing?: boolean }) => {
    generationSectionProps(props);
    return null;
  },
}));

vi.mock("@/components/intake/workbook-channel", () => ({
  WorkbookChannel: () => null,
}));

vi.mock("@/components/editor/topic-intake-field", () => ({
  TopicIntakeField: ({ item }: { item: { key: string; prompt: string } }) => (
    <div data-testid={`field-${item.key}`}>{item.prompt}</div>
  ),
}));

const { fetchReportPreparation, fetchReportFileIntake } = vi.hoisted(() => ({
  fetchReportPreparation: vi.fn(),
  fetchReportFileIntake: vi.fn(),
}));

// 只替换网络边界；selectReportFileIntakeSnapshot 用真实实现。
vi.mock("@/lib/material-workspace-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/material-workspace-api")>()),
  fetchReportFileIntake,
  fetchReportPreparation,
}));

vi.mock("@/lib/api", () => ({
  downloadTopicQuestionsTemplate: vi.fn(),
  importTopicQuestionsWorkbook: vi.fn(),
}));

import IntakeQuestionsPage from "./page";

const preparationWith = (requiredForGeneration: boolean) => ({
  areas: [
    {
      id: "topic_questions",
      title: "议题信息",
      href: "/intake/questions",
      required_for_generation: requiredForGeneration,
      status: requiredForGeneration ? "needs_input" : "optional_empty",
      summary: "",
      action_label: "",
    },
  ],
  generation_blockers: [],
});

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

function makeLayoutSource(overrides: Record<string, unknown> = {}) {
  return {
    binding_id: "binding-2",
    source_id: "source-2",
    binding_status: "active",
    filename: "certificate.png",
    content_type: "image/png",
    size_bytes: 2048,
    sha256: "abc",
    declaration: {
      description: "2024 年 ISO 14001 认证证书",
      role: "layout_asset",
      topic_tags: ["uncertain"],
      asset_title: null,
      revision_id: "rev-2",
      binding_id: "binding-2",
      revision: 1,
      declared_at: "2026-01-01T00:00:00Z",
    },
    admission_status: "admitted",
    error_message: null,
    file_analysis: null,
    image_analysis: null,
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
    active_file_count: 0,
    sources: [],
    ingress_receipts: [],
    material_set_confirmation: { status: "not_required", confirmed_at: null, pending_description_count: 0 },
    phase: "draft",
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  scope.materialAgentEnabled = true;
});

describe("议题信息填写页的必答区", () => {
  it("服务端判定必答时，必答题平铺在「生成前需要确认」区", async () => {
    fetchReportPreparation.mockResolvedValue(preparationWith(true));
    fetchReportFileIntake.mockResolvedValue(makeIntake());
    render(<IntakeQuestionsPage />);

    await waitFor(() => {
      expect(screen.getByRole("region", { name: "生成前需要确认" })).toBeTruthy();
    });
    // 必答题在页顶平铺，不藏进折叠分组。
    expect(screen.getByTestId("field-climate.q_climate_risk_choices")).toBeTruthy();
  });

  it("服务端判定不必答时不得出现必答区——合同虽声明这三题，但不因它阻断生成", async () => {
    fetchReportPreparation.mockResolvedValue(preparationWith(false));
    fetchReportFileIntake.mockResolvedValue(makeIntake());
    render(<IntakeQuestionsPage />);

    await waitFor(() => {
      expect(fetchReportPreparation).toHaveBeenCalled();
    });
    expect(screen.queryByRole("region", { name: "生成前需要确认" })).toBeNull();
  });
});

describe("议题信息填写页的图片素材区", () => {
  it("materialAgentEnabled 时渲染「图片素材」区，且不存在「报告资料」区", async () => {
    fetchReportPreparation.mockResolvedValue(preparationWith(false));
    fetchReportFileIntake.mockResolvedValue(makeIntake({ active_file_count: 1, sources: [makeLayoutSource()] }));
    render(<IntakeQuestionsPage />);

    await waitFor(() => {
      expect(screen.getByRole("region", { name: "图片素材" })).toBeTruthy();
    });
    expect(screen.queryByRole("region", { name: "报告资料" })).toBeNull();
    expect(screen.getByLabelText("certificate.png 的说明")).toBeTruthy();
    expect(screen.getByText("缺少说明的图片会阻断生成；不上传图片也可以生成。")).toBeTruthy();
  });

  it("行尾显示服务端 image_analysis 状态词——失败的图片在本页必须可见", async () => {
    fetchReportPreparation.mockResolvedValue(preparationWith(false));
    fetchReportFileIntake.mockResolvedValue(
      makeIntake({ active_file_count: 1, sources: [makeLayoutSource({ image_analysis: { status: "failed" } })] }),
    );
    render(<IntakeQuestionsPage />);

    expect(await screen.findByText("资料暂不可用")).toBeTruthy();
  });

  it("materialAgentEnabled=false 时不渲染图片素材区", async () => {
    scope.materialAgentEnabled = false;
    fetchReportPreparation.mockResolvedValue(preparationWith(false));
    fetchReportFileIntake.mockResolvedValue(makeIntake());
    render(<IntakeQuestionsPage />);

    await waitFor(() => {
      expect(fetchReportFileIntake).toHaveBeenCalled();
    });
    expect(screen.queryByRole("region", { name: "图片素材" })).toBeNull();
  });

  it("服务端 phase=processing 时生成区收到 processing", async () => {
    fetchReportPreparation.mockResolvedValue(preparationWith(false));
    fetchReportFileIntake.mockResolvedValue(
      makeIntake({
        active_file_count: 1,
        sources: [makeLayoutSource({ image_analysis: { status: "running" } })],
        phase: "processing",
      }),
    );
    render(<IntakeQuestionsPage />);

    await waitFor(() => {
      expect(generationSectionProps).toHaveBeenLastCalledWith(expect.objectContaining({ processing: true }));
    });
  });

  it("phase=draft 时生成区不因本页置灰", async () => {
    fetchReportPreparation.mockResolvedValue(preparationWith(false));
    fetchReportFileIntake.mockResolvedValue(makeIntake({ active_file_count: 1, sources: [makeLayoutSource()] }));
    render(<IntakeQuestionsPage />);

    await waitFor(() => {
      expect(screen.getByRole("region", { name: "图片素材" })).toBeTruthy();
    });
    expect(generationSectionProps).toHaveBeenLastCalledWith(expect.objectContaining({ processing: false }));
  });
});
