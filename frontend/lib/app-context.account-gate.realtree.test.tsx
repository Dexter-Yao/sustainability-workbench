// ABOUTME: 服务端模式门禁回归——整页直开报告路由时 AccountProvider 尚未解析（loading 初值 false、
// ABOUTME: snapshot null），门禁不得把 activeReportId=null 误判为「未选报告」弹回 /reports；账户解析后按指针加载。
// @vitest-environment happy-dom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.setConfig({ testTimeout: 20_000 });

const { getReportState, putReportState } = vi.hoisted(() => ({
  getReportState: vi.fn(),
  putReportState: vi.fn(),
}));

const routerHandle = { replace: vi.fn(), push: vi.fn() };
// 可变 pathname：任何报告上下文路由（含 /intake/info）无报告指针一律重定向
// （「新建报告」点击即创建报告，不存在本地草稿模式）。
let pathname = "/intake/info";
vi.mock("next/navigation", () => ({
  useRouter: () => routerHandle,
  usePathname: () => pathname,
}));

const authValue = {
  session: { access_token: "test-token", user: { id: "user-1" } },
  loading: false,
  configured: true,
  authError: null,
  signOut: async () => {},
};
vi.mock("@/lib/auth-context", () => ({ useAuth: () => authValue }));

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
// 可变账户上下文：初始形态复刻 AccountProvider 挂载瞬间（refresh 尚未开始），测试中再切到已解析。
const accountValue: {
  snapshot: typeof accountSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<typeof accountSnapshot | null>;
} = {
  snapshot: null,
  loading: false,
  error: null,
  refresh: async () => accountSnapshot,
};
vi.mock("@/lib/account-context", () => ({ useAccount: () => ({ ...accountValue }) }));

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
    putReportState: (...args: unknown[]) => putReportState(...(args as [string, unknown, number])),
  };
});

getReportState.mockImplementation(async () => ({
  state: emptyStoredState(),
  state_seq: 1,
  contract_version: CONTRACT_VERSION,
  capabilities: reportCapabilities,
}));

const MINIMAL_REPORT = {
  fields: {
    company_registered_name: {
      key: "company_registered_name",
      label: "公司注册名",
      type: "string",
      source: "user_input",
      value: "",
    },
  },
  intakeItems: [],
  assessmentInput: null,
  assessment: null,
  disclosureProfile: null,
  appendixPackage: null,
  meta: null,
  stakeholderEngagement: null,
  sections: [],
  assessmentScoreScale: { minimumExclusive: 0, maximum: 5, multipleOf: 0.1 },
};
vi.mock("@/lib/report-template", () => ({
  loadReportTemplate: vi.fn(async () => structuredClone(MINIMAL_REPORT)),
}));

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
    readiness: {
      stages: [],
      issues: [],
      readyForWorkbench: false,
      firstIncompleteStageId: null,
      firstIncompleteHref: null,
    },
  })),
  plan: vi.fn(async (report: unknown) => ({ report, diagnostics: [], added: [], dropped: [] })),
  ContractUpgradeRequiredError: class ContractUpgradeRequiredError extends Error {},
}));

import { AppProvider, useApp } from "@/lib/app-context";

function ReportProbe() {
  const { report } = useApp();
  if (!report) return null;
  return <div data-testid="report-loaded">{String(report.fields.company_registered_name?.value ?? "")}</div>;
}

afterEach(cleanup);

beforeEach(() => {
  window.localStorage.clear();
  routerHandle.replace.mockClear();
  routerHandle.push.mockClear();
  getReportState.mockClear();
  accountValue.snapshot = null;
  accountValue.loading = false;
  accountValue.error = null;
  pathname = "/intake/info";
});

describe("app-context 服务端模式门禁加载竞态", () => {
  it("账户尚未解析时整页直开报告路由不弹回 /reports；解析后按本地指针加载报告", async () => {
    window.localStorage.setItem(`sustainability-desk:current-report-id:${accountSnapshot.account.id}`, REPORT_ID);

    const view = render(
      <AppProvider>
        <ReportProbe />
      </AppProvider>,
    );

    // 复刻竞态窗口：snapshot null、loading false、error null → 门禁必须按「账户仍在解析」等待。
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(routerHandle.replace).not.toHaveBeenCalled();

    // 账户解析完成 → activeReportId 从本地指针恢复，报告正常加载，全程无重定向。
    accountValue.snapshot = accountSnapshot;
    view.rerender(
      <AppProvider>
        <ReportProbe />
      </AppProvider>,
    );
    await screen.findByTestId("report-loaded", undefined, { timeout: 5_000 });
    expect(routerHandle.replace).not.toHaveBeenCalled();
    expect(getReportState).toHaveBeenCalledWith(REPORT_ID);
  });

  it("账户解析完成且确无报告指针时，非草稿落点的报告路由仍重定向 /reports（门禁语义不回退）", async () => {
    pathname = "/intake/scoring";
    accountValue.snapshot = accountSnapshot;

    render(
      <AppProvider>
        <ReportProbe />
      </AppProvider>,
    );

    await vi.waitFor(
      () => {
        expect(routerHandle.replace).toHaveBeenCalledWith("/reports");
      },
      { timeout: 5_000, interval: 50 },
    );
  });

  it("确无报告指针时 /intake/info 同样重定向 /reports（不存在本地草稿模式）", async () => {
    accountValue.snapshot = accountSnapshot;

    render(
      <AppProvider>
        <ReportProbe />
      </AppProvider>,
    );

    // 「新建报告」点击即创建报告：不存在无报告的编制页，也不读任何服务端报告状态。
    await vi.waitFor(
      () => {
        expect(routerHandle.replace).toHaveBeenCalledWith("/reports");
      },
      { timeout: 5_000, interval: 50 },
    );
    expect(getReportState).not.toHaveBeenCalled();
  });
});
