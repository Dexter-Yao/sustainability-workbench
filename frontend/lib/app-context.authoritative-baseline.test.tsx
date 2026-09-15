// ABOUTME: app-context 权威基线一致性回归——applyPlan 与 applyServerReportUpdate 都必须保全
// ABOUTME: 仅存于服务端 state 的事实（素材图片放置等），并在拿到完整权威 state 时刷新基线本身。
// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.setConfig({ testTimeout: 20_000 });

const { getReportState, putReportState, planImpl } = vi.hoisted(() => ({
  getReportState: vi.fn(),
  putReportState: vi.fn(),
  planImpl: {
    current: async (report: unknown) => ({ report, diagnostics: [], added: [], dropped: [] }),
  } as { current: (report: unknown, expectedContractVersion?: string, reportId?: string) => Promise<{
    report: unknown;
    diagnostics: unknown[];
    added: string[];
    dropped: string[];
  }> },
}));

// router 必须是稳定引用：AppProvider 的加载/门禁 effect 依赖 router 对象本身，
// 每次渲染返回新对象会导致 effect 无限重跑（务必保持模块级常量）。
const routerHandle = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => routerHandle,
  usePathname: () => "/reports/document",
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

const LAYOUT_ASSET_ID = "11111111-1111-4111-8111-111111111111";

function baselineState() {
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
    // 仅存于服务端 state 的事实：素材承载位的放置结果，浏览器窄投影模板不含该章节时无法重建。
    imageBlocks: {
      "company_intro.layout_assets": { layoutAssetIds: [LAYOUT_ASSET_ID], state: "ready" },
    },
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
  state: baselineState(),
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
  sections: [
    {
      key: "company_intro",
      title: "关于公司",
      headingLevel: 1,
      blocks: [
        {
          id: "company_intro.layout_assets",
          type: "image",
          blockType: "slot",
          source: "user_input",
          image: { layoutAssetSlot: true, layoutAssetIds: [] as string[] },
        },
      ],
    },
  ],
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
  plan: (...args: [unknown, string?, string?]) => planImpl.current(...args),
  ContractUpgradeRequiredError: class ContractUpgradeRequiredError extends Error {},
}));

import { AppProvider, useApp } from "@/lib/app-context";

function LayoutAssetProbe() {
  const { report, applyPlan, applyServerReportUpdate } = useApp();
  if (!report) return null;
  const block = report.sections[0]?.blocks[0];
  const layoutAssetIds = block?.type === "image" ? block.image?.layoutAssetIds ?? [] : [];
  return (
    <div>
      <div data-testid="layout-asset-ids">{layoutAssetIds.join(",")}</div>
      <button type="button" onClick={() => void applyPlan()}>
        重新装配
      </button>
      <button
        type="button"
        onClick={() =>
          applyServerReportUpdate(
            (current) => current,
            42,
            { ...baselineState(), imageBlocks: {} },
          )
        }
      >
        应用不含素材放置的权威状态
      </button>
    </div>
  );
}

afterEach(cleanup);

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(`sustainability-desk:current-report-id:${accountSnapshot.account.id}`, REPORT_ID);
  getReportState.mockClear();
  putReportState.mockReset();
  putReportState.mockResolvedValue(2);
  planImpl.current = async (report: unknown) => ({ report, diagnostics: [], added: [], dropped: [] });
});

describe("applyPlan 保全仅存于服务端 state 的事实", () => {
  it("plan 结果二次重放权威基线，不丢失素材图片放置", async () => {
    render(
      <AppProvider>
        <LayoutAssetProbe />
      </AppProvider>,
    );

    await screen.findByTestId("layout-asset-ids", undefined, { timeout: 5_000 });
    await vi.waitFor(
      () => {
        expect(screen.getByTestId("layout-asset-ids").textContent).toBe(LAYOUT_ASSET_ID);
      },
      { timeout: 5_000, interval: 50 },
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "重新装配" }));
    });

    await vi.waitFor(
      () => {
        expect(screen.getByTestId("layout-asset-ids").textContent).toBe(LAYOUT_ASSET_ID);
      },
      { timeout: 5_000, interval: 50 },
    );
  });
});

describe("applyServerReportUpdate 刷新权威基线", () => {
  it("调用方携带完整权威 state 时同步基线，后续 applyPlan 不再从旧基线保全已被服务端移除的事实", async () => {
    render(
      <AppProvider>
        <LayoutAssetProbe />
      </AppProvider>,
    );

    await vi.waitFor(
      () => {
        expect(screen.getByTestId("layout-asset-ids").textContent).toBe(LAYOUT_ASSET_ID);
      },
      { timeout: 5_000, interval: 50 },
    );

    // 服务端本次原子写回的权威 state 已不再含该素材放置（例如用户在别处移除）。
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "应用不含素材放置的权威状态" }));
    });

    // plan 返回服务端重新装配的干净模板结构，不携带前端已应用的服务端-only 值
    // （模拟真实 /api/plan：装配来自 fields/intakeItems，不回声前端上一次重放结果）。
    planImpl.current = async (report: unknown) => ({
      report: {
        ...(report as { sections: unknown[] }),
        sections: [
          {
            ...(report as { sections: { blocks: unknown[] }[] }).sections[0],
            blocks: [
              {
                id: "company_intro.layout_assets",
                type: "image",
                blockType: "slot",
                source: "user_input",
                image: { layoutAssetSlot: true, layoutAssetIds: [] },
              },
            ],
          },
        ],
      },
      diagnostics: [],
      added: [],
      dropped: [],
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "重新装配" }));
    });

    await vi.waitFor(
      () => {
        expect(screen.getByTestId("layout-asset-ids").textContent).toBe("");
      },
      { timeout: 5_000, interval: 50 },
    );
  });
});
