// ABOUTME: 评分页"真实 Provider 树"渲染回归：AppProvider 真实运行（含加载 effect、自动保存 effect、
// ABOUTME: activeReportId useSyncExternalStore 订阅），只 mock 网络边界与路由；复现或排除线上"一填就崩"更新循环。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.setConfig({ testTimeout: 20_000 });

// 所有 mock 工厂引用的可变对象与类统一在此提升；vi.mock 工厂执行早于模块体,
// 引用非 hoisted 的顶层 const 会触发暂时性死区错误。
const {
  getReportState,
  StateConflictError,
  ReportNotFoundError,
  putAssessmentInput,
  StructuredInputConflictError,
} = vi.hoisted(() => {
  class StateConflictErrorImpl extends Error {
    readonly code = "report_state_conflict";
  }
  class ReportNotFoundErrorImpl extends Error {
    readonly code = "report_not_found";
  }
  class StructuredInputConflictErrorImpl extends Error {
    current: unknown;
    constructor(conflict: { message: string; current: unknown }) {
      super(conflict.message);
      this.name = "StructuredInputConflictError";
      this.current = conflict.current;
    }
  }
  return {
    getReportState: vi.fn(),
    StateConflictError: StateConflictErrorImpl,
    ReportNotFoundError: ReportNotFoundErrorImpl,
    putAssessmentInput: vi.fn(),
    StructuredInputConflictError: StructuredInputConflictErrorImpl,
  };
});

// 真实 next/navigation 的 useRouter() 返回跨渲染稳定的单例引用；mock 必须同样稳定，
// 否则 app-context 加载 effect 的 [..., router] 依赖每次渲染都判定为变化，制造测试自身的假性无限循环
// （而非复现生产问题）。routerHandle 在模块顶层构造一次，所有渲染共享同一引用。
const routerHandle = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => routerHandle,
  usePathname: () => "/intake/scoring",
}));

// --- 边界一：auth-context / account-context 保持真实导出形状，useAuth/useAccount 返回已登录稳定值。 ---
// authSession 与 authValue 默认在模块顶层固定引用；authMode.unstableSession 打开后 useAuth 每次渲染
// 返回内容相同但引用全新的 session——模拟 supabase 高频认证事件(聚焦校验/TOKEN_REFRESHED)推送新
// session 对象的生产形态,守护 app-context 不得以 session 引用为 effect 依赖(线上"一填就跳"根因)。
const authMode = vi.hoisted(() => ({ unstableSession: false }));
const authSession = { access_token: "test-token", user: { id: "user-1" } };
const authValue = {
  session: authSession,
  loading: false,
  configured: true,
  authError: null,
  signOut: async () => {},
};
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => (authMode.unstableSession
    ? { ...authValue, session: { ...authSession, user: { ...authSession.user } } }
    : authValue),
}));

const accountSnapshot = {
  account: {
    id: "account-1",
    email: "test@example.com",
    organization_name: "测试企业",
    status: "active",
    registered_at: "2026-01-01T00:00:00Z",
    last_active_at: null,
  },
  entitlement: {
    grant_id: "grant-1",
    profile_id: "local_single_user@1",
    starts_at: "2026-01-01T00:00:00Z",
    ends_at: null,
    expired: false,
  },
  capabilities: {
    allowed_report_section_ids: [],
    section_regeneration_limit: 0,
    can_create_report: true,
    can_generate: true,
    can_regenerate_sections: true,
    can_export_word: true,
    material_agent_enabled: false,
    can_edit_existing: true,
    collects_materiality_assessment: true,
    allowed_quantitative_metric_keys: [],
    allowed_report_artifact_kinds: ["word", "review"],
  },
};

// 同理：accountValue 固定引用，避免 useAccount() 每次渲染返回新对象误触发依赖它的 effect/useMemo。
const accountValue = {
  snapshot: accountSnapshot,
  loading: false,
  error: null,
  refresh: async () => accountSnapshot,
};
vi.mock("@/lib/account-context", () => ({
  useAccount: () => accountValue,
}));

// --- 边界二：网络函数层。report-store：getReportState 返回最小合法 ServerReportState；
// currentReportId/subscribeCurrentReportId/setCurrentReportId 用真实实现（走 localStorage），
// 测试前 seed localStorage 使 activeReportId 与 fixture 报告一致。 ---
const REPORT_ID = "report-1";
const CONTRACT_VERSION = "contract-test@1";

const reportCapabilities = {
  allowed_report_section_ids: [],
  can_generate: true,
  can_regenerate_sections: true,
  can_export_word: true,
  material_agent_enabled: false,
  collects_materiality_assessment: true,
  allowed_quantitative_metric_keys: [],
  allowed_report_artifact_kinds: ["word", "review"] as ("word" | "review")[],
};

function emptyStoredState() {
  return {
    version: 4,
    fields: {},
    intakeItems: {},
    assessmentInput: null,
    disclosureProfile: null,
    appendixPackage: null,
    meta: null,
    stakeholderEngagement: null,
    sectionTitles: {},
    generatedBlocks: {},
    tableBlocks: {},
  };
}

vi.mock("@/lib/report-store", async () => {
  const actual = await vi.importActual<typeof import("@/lib/report-store")>("@/lib/report-store");
  return {
    ...actual,
    getReportState: (...args: unknown[]) => getReportState(...(args as [string])),
    putReportState: vi.fn(async () => 2),
    StateConflictError,
    ReportNotFoundError,
    // currentReportId/setCurrentReportId/subscribeCurrentReportId 保留真实实现（走 localStorage）。
  };
});

getReportState.mockImplementation(async () => ({
  state: emptyStoredState(),
  state_seq: 1,
  contract_version: CONTRACT_VERSION,
  capabilities: reportCapabilities,
}));

// --- report-template：最小合法 Report（AppProvider/scoring 页只依赖 fields/sections/intakeItems 等顶层结构）。 ---
const MINIMAL_REPORT = {
  fields: {},
  intakeItems: [],
  assessmentInput: null,
  assessment: null,
  disclosureProfile: null,
  appendixPackage: null,
  meta: null,
  stakeholderEngagement: null,
  sections: [],
  assessmentScoreScale: { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 },
  // 分类名与两轴名是包资产，由 /api/plan 按包下发；缺了它评分页的轴标签会是空串。
  assessmentVocabulary: {
    materiality: { dual: "双重重要性", impact: "影响重要性", financial: "财务重要性", non: "非重要性" },
    materialityAxes: { financial: "财务重要性", impact: "影响重要性" },
    iroKind: { impact: "影响", risk: "风险", opportunity: "机遇", risk_opportunity: "风险与机遇" },
    impactClass: { actual_positive: "实际正面影响", potential_positive: "潜在正面影响", potential_negative: "潜在负面影响" },
  },
};

vi.mock("@/lib/report-template", () => ({
  loadReportTemplate: vi.fn(async () => structuredClone(MINIMAL_REPORT)),
}));

// --- lib/api：app-context 与 scoring 页共同消费的函数逐一覆盖。 ---
const assessmentFixture = {
  status: "draft" as const,
  state_seq: 1,
  contract_version: CONTRACT_VERSION,
  context_fingerprint: "fp-1",
  score_scale: { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 },
  topics: [
    { assessmentTopicId: "t1", name: "议题一", dimension: "环境", order: 1, reportSectionId: "s1" },
    { assessmentTopicId: "t2", name: "议题二", dimension: "社会", order: 2, reportSectionId: "s2" },
  ],
  current: null,
  resolved: null,
  readiness: {
    stages: [],
    issues: [],
    readyForWorkbench: false,
    firstIncompleteStageId: null,
    firstIncompleteHref: null,
  },
};

// 服务端权威评分状态的最小可变镜像：putAssessmentInput 写入后，fetchAssessmentInput（reload 使用）
// 必须能读到刚保存的值——真实后端就是这样；若两者各说各话，测试会把"mock 语义不一致"误判为页面 bug。
let serverAssessmentState: {
  state_seq: number;
  scores: { assessmentTopicId: string; financialScore: number; impactScore: number }[];
  threshold: { financial: number; impact: number };
} = { state_seq: 1, scores: [], threshold: { financial: 3, impact: 3 } };

putAssessmentInput.mockImplementation(async (
  _reportId: string,
  input: {
    expected_state_seq: number;
    threshold: { financial: number; impact: number };
    scores: { assessmentTopicId: string; financialScore: number; impactScore: number }[];
  },
) => {
  serverAssessmentState = {
    state_seq: input.expected_state_seq + 1,
    scores: input.scores,
    threshold: input.threshold,
  };
  return {
    state: { ...emptyStoredState(), assessmentInput: null },
    state_seq: serverAssessmentState.state_seq,
    contract_version: CONTRACT_VERSION,
    readiness: assessmentFixture.readiness,
  };
});

vi.mock("@/lib/api", () => ({
  fetchPromptConfig: vi.fn(async () => ({ blocks: [], user_visible_disclosure_clause_annotations: [] })),
  fetchQuantitativeMetricsInput: vi.fn(async () => ({
    status: "draft",
    state_seq: 1,
    contract_version: CONTRACT_VERSION,
    context_fingerprint: "fp-metrics",
    catalog: [],
    greenhouse_gas_accounting_standard_options: [],
    no_value_reasons: [],
    current: { metrics: {}, greenhouseGasAccountingStandard: null, greenhouseGasAccountingStandardOther: null },
    readiness: assessmentFixture.readiness,
  })),
  fetchAssessmentInput: vi.fn(async () => ({
    ...structuredClone(assessmentFixture),
    state_seq: serverAssessmentState.state_seq,
    current: serverAssessmentState.scores.length
      ? {
          reportingYear: 2026,
          threshold: serverAssessmentState.threshold,
          scores: serverAssessmentState.scores,
        }
      : null,
  })),
  putAssessmentInput: (...args: unknown[]) => putAssessmentInput(...(args as [string, { expected_state_seq: number }])),
  downloadAssessmentTemplate: vi.fn(),
  importAssessmentWorkbook: vi.fn(),
  StructuredInputConflictError,
  plan: vi.fn(async (report: unknown) => ({ report, diagnostics: [], added: [], dropped: [] })),
  ContractUpgradeRequiredError: class ContractUpgradeRequiredError extends Error {},
}));

vi.mock("@/lib/active-report-scope", () => ({
  activeReportScope: () => ({
    status: "ready",
    collectsMaterialityAssessment: true,
    allowedReportSectionIds: [],
    allowedFileTopicTags: null,
    allowedMetricKeys: [],
    canGenerate: true,
    canRegenerateSections: true,
    canExportWord: true,
    materialAgentEnabled: false,
    allowedArtifactKinds: ["word", "review"],
  }),
}));

vi.mock("@/components/editor/matrix-image", () => ({
  MatrixImage: () => null,
}));

import { AppProvider } from "@/lib/app-context";
import IntakeScoringPage from "./page";

afterEach(cleanup);

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(`sustainability-desk:current-report-id:${accountSnapshot.account.id}`, REPORT_ID);
  serverAssessmentState = { state_seq: 1, scores: [], threshold: { financial: 3, impact: 3 } };
  putAssessmentInput.mockClear();
  getReportState.mockClear();
});

describe("评分页真实 Provider 树渲染回归", () => {
  it("真实 AppProvider 下键入评分不产生无限更新循环，防抖保存各恰好一次", async () => {
    render(
      <AppProvider>
        <IntakeScoringPage />
      </AppProvider>,
    );

    const financial = await screen.findByLabelText("议题一 财务重要性", undefined, { timeout: 5_000 });

    // 交替连续键入四个输入框，模拟真实录入节奏。
    await act(async () => {
      fireEvent.change(financial, { target: { value: "3" } });
    });
    expect((screen.getByLabelText("议题一 财务重要性") as HTMLInputElement).value).toBe("3");

    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题一 财务重要性"), { target: { value: "3." } });
    });
    expect((screen.getByLabelText("议题一 财务重要性") as HTMLInputElement).value).toBe("3.");

    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题一 财务重要性"), { target: { value: "3.5" } });
    });
    expect((screen.getByLabelText("议题一 财务重要性") as HTMLInputElement).value).toBe("3.5");

    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题一 影响重要性"), { target: { value: "4" } });
    });
    expect((screen.getByLabelText("议题一 影响重要性") as HTMLInputElement).value).toBe("4");

    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题二 财务重要性"), { target: { value: "2" } });
    });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题二 影响重要性"), { target: { value: "2.5" } });
    });
    expect((screen.getByLabelText("议题二 财务重要性") as HTMLInputElement).value).toBe("2");
    expect((screen.getByLabelText("议题二 影响重要性") as HTMLInputElement).value).toBe("2.5");

    // 推进 1600ms 让防抖保存发生：仅两议题四输入中一议题（议题一）两维已填、议题二两维也已填，
    // 故本次 draftScores 应含两行，putAssessmentInput 恰调用一次。
    // 用 vi.waitFor + 真实定时器轮询防抖到期，而非切换 fake timers——useStructuredAutosave 的
    // debounce setTimeout 在键入时已用真实定时器排入，切换 fake timers 后无法追溯到它。
    await vi.waitFor(
      () => {
        expect(putAssessmentInput).toHaveBeenCalledTimes(1);
      },
      { timeout: 5_000, interval: 50 },
    );
    // 页面仍稳定：输入值未被保存流程清空或重置。
    expect((screen.getByLabelText("议题一 财务重要性") as HTMLInputElement).value).toBe("3.5");
    expect((screen.getByLabelText("议题二 影响重要性") as HTMLInputElement).value).toBe("2.5");

    // 再键入触发第二次防抖保存。
    await act(async () => {
      fireEvent.change(screen.getByLabelText("议题一 财务重要性"), { target: { value: "4.5" } });
    });
    await vi.waitFor(
      () => {
        expect(putAssessmentInput).toHaveBeenCalledTimes(2);
      },
      { timeout: 5_000, interval: 50 },
    );
    expect((screen.getByLabelText("议题一 财务重要性") as HTMLInputElement).value).toBe("4.5");
  });

  it("session 引用每次渲染变化(supabase 高频认证事件形态)不触发整树重载,填写不被打断", async () => {
    authMode.unstableSession = true;
    try {
      render(
        <AppProvider>
          <IntakeScoringPage />
        </AppProvider>,
      );
      const financial = await screen.findByLabelText("议题一 财务重要性", undefined, { timeout: 3_000 });
      const loadsAfterMount = getReportState.mock.calls.length;

      for (const value of ["3", "3.", "3.5"]) {
        await act(async () => {
          fireEvent.change(screen.getByLabelText("议题一 财务重要性"), { target: { value } });
        });
      }
      await act(async () => {
        fireEvent.change(screen.getByLabelText("议题一 影响重要性"), { target: { value: "4" } });
      });

      // 键入过程中的每次渲染都换了 session 引用;若加载 effect 仍依赖该引用,
      // 这里会观察到 getReportState 风暴与输入被重载清空。
      expect((screen.getByLabelText("议题一 财务重要性") as HTMLInputElement).value).toBe("3.5");
      expect((screen.getByLabelText("议题一 影响重要性") as HTMLInputElement).value).toBe("4");
      expect(getReportState.mock.calls.length).toBe(loadsAfterMount);
      expect(financial).toBe(screen.getByLabelText("议题一 财务重要性"));
    } finally {
      authMode.unstableSession = false;
    }
  });
});
