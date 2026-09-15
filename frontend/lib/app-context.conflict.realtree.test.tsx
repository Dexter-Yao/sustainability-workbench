// ABOUTME: app-context 双窗冲突策略回归——409 后暂停自动保存并保留本页修改，
// ABOUTME: 只有用户显式确认才丢弃本地内容加载最新;与评分页 pausedForConflict 语义对齐。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.setConfig({ testTimeout: 20_000 });

const { getReportState, putReportState, StateConflictError, ReportNotFoundError } = vi.hoisted(() => {
  class StateConflictErrorImpl extends Error {
    readonly code = "report_state_conflict";
  }
  class ReportNotFoundErrorImpl extends Error {
    readonly code = "report_not_found";
  }
  return {
    getReportState: vi.fn(),
    putReportState: vi.fn(),
    StateConflictError: StateConflictErrorImpl,
    ReportNotFoundError: ReportNotFoundErrorImpl,
  };
});

const routerHandle = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => routerHandle,
  usePathname: () => "/intake/info",
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
    allowed_quantitative_metric_keys: [],
    allowed_report_artifact_kinds: ["word", "review"],
  },
};
const accountValue = {
  snapshot: accountSnapshot,
  loading: false,
  error: null,
  refresh: async () => accountSnapshot,
};
vi.mock("@/lib/account-context", () => ({ useAccount: () => accountValue }));

const REPORT_ID = "report-1";
const CONTRACT_VERSION = "contract-test@1";
const reportCapabilities = {
  allowed_report_section_ids: [],
  can_generate: true,
  can_regenerate_sections: true,
  can_export_word: true,
  material_agent_enabled: false,
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
    StateConflictError,
    ReportNotFoundError,
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

import { ApiError } from "@/lib/api-error";
import { AppProvider, useApp } from "@/lib/app-context";

function ConflictProbe() {
  const { report, setFieldValue, conflictNotice, conflictPending, confirmConflictReload, sessionExpired, saveError } =
    useApp();
  if (!report) return null;
  return (
    <div>
      <input
        aria-label="公司注册名"
        value={String(report.fields.company_registered_name?.value ?? "")}
        onChange={(event) => setFieldValue("company_registered_name", event.target.value)}
      />
      {conflictNotice ? <div role="alert">{conflictNotice}</div> : null}
      {sessionExpired ? <div data-testid="session-expired">请重新登录</div> : null}
      {saveError ? <div data-testid="save-error">{saveError}</div> : null}
      {conflictPending ? (
        <button type="button" onClick={() => void confirmConflictReload()}>
          加载最新内容
        </button>
      ) : null}
    </div>
  );
}

afterEach(cleanup);

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(`sustainability-desk:current-report-id:${accountSnapshot.account.id}`, REPORT_ID);
  getReportState.mockClear();
  putReportState.mockReset();
});

describe("app-context 双窗冲突显式确认", () => {
  it("409 后保留本页修改并暂停自动保存；确认后才丢弃本地内容并恢复保存", async () => {
    putReportState.mockRejectedValueOnce(new StateConflictError("冲突"));
    putReportState.mockResolvedValue(3);

    render(
      <AppProvider>
        <ConflictProbe />
      </AppProvider>,
    );
    const input = await screen.findByLabelText("公司注册名", undefined, { timeout: 5_000 });

    await act(async () => {
      fireEvent.change(input, { target: { value: "本地公司" } });
    });

    // 防抖保存到期 → 409 → 显式确认横幅出现，本地修改保留。
    await vi.waitFor(
      () => {
        expect(putReportState).toHaveBeenCalledTimes(1);
        expect(screen.getByRole("alert").textContent).toContain("报告已在其他窗口更新");
      },
      { timeout: 5_000, interval: 50 },
    );
    expect((screen.getByLabelText("公司注册名") as HTMLInputElement).value).toBe("本地公司");
    expect(screen.getByRole("button", { name: "加载最新内容" })).toBeTruthy();

    // 冲突未决期间继续编辑不再触发保存（不会反复 409、反复弹横幅）。
    await act(async () => {
      fireEvent.change(screen.getByLabelText("公司注册名"), { target: { value: "本地公司二" } });
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1_300));
    });
    expect(putReportState).toHaveBeenCalledTimes(1);

    // 显式确认后：以服务端为准重载（本地修改被覆盖），横幅关闭。
    const loadsBeforeConfirm = getReportState.mock.calls.length;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "加载最新内容" }));
    });
    await vi.waitFor(
      () => {
        expect(getReportState.mock.calls.length).toBe(loadsBeforeConfirm + 1);
        expect(screen.queryByRole("alert")).toBeNull();
      },
      { timeout: 5_000, interval: 50 },
    );
    expect((screen.getByLabelText("公司注册名") as HTMLInputElement).value).toBe("");

    // 自动保存已恢复：新的编辑再次走保存。
    await act(async () => {
      fireEvent.change(screen.getByLabelText("公司注册名"), { target: { value: "确认后编辑" } });
    });
    await vi.waitFor(
      () => {
        expect(putReportState).toHaveBeenCalledTimes(2);
      },
      { timeout: 5_000, interval: 50 },
    );
    expect((screen.getByLabelText("公司注册名") as HTMLInputElement).value).toBe("确认后编辑");
  });
});

describe("app-context 会话过期语义", () => {
  it("自动保存收到 401 时给重新登录信号，而非刷新重试文案", async () => {
    putReportState.mockRejectedValue(
      new ApiError({ message: "未授权", code: "http_401", httpStatus: 401 }),
    );

    render(
      <AppProvider>
        <ConflictProbe />
      </AppProvider>,
    );
    const input = await screen.findByLabelText("公司注册名", undefined, { timeout: 5_000 });

    await act(async () => {
      fireEvent.change(input, { target: { value: "本地公司" } });
    });

    await vi.waitFor(
      () => {
        expect(screen.getByTestId("session-expired").textContent).toContain("请重新登录");
      },
      { timeout: 5_000, interval: 50 },
    );
    // 401 不落入通用「检查网络后重试」话术。
    expect(screen.queryByTestId("save-error")).toBeNull();
  });
});
