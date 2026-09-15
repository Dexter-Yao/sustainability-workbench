// ABOUTME: 轻量版结构化输入前端 API 合同测试。
// ABOUTME: 锁定 report-bound 路径、乐观锁、整批导入及 409 权威快照重载语义。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./supabase", () => ({ accessToken: vi.fn().mockResolvedValue("access-token") }));

import {
  downloadAssessmentTemplate,
  fetchAssessmentInput,
  fetchQuantitativeMetricsInput,
  importAssessmentWorkbook,
  importQuantitativeMetricsWorkbook,
  putAssessmentInput,
  putQuantitativeMetricsInput,
} from "./api";

const readiness = {
  stages: [],
  issues: [],
  readyForWorkbench: false,
  firstIncompleteStageId: null,
  firstIncompleteHref: null,
};

const state = {
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
  imageBlocks: {},
  structuredInputFreshness: {
    assessmentContextFingerprint: null,
    quantitativeMetricsContextFingerprint: null,
  },
};

const mutation = {
  state,
  state_seq: 8,
  contract_version: "contract-v4",
  readiness,
};

describe("structured input API", () => {
  beforeEach(() => {
    vi.stubGlobal("window", {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("从 report-bound typed 端点读取重要性与定量权威状态", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: "missing",
        state_seq: 7,
        contract_version: "contract-v4",
        context_fingerprint: "a".repeat(64),
        score_scale: {
          minimumExclusive: 0,
          maximum: 5,
          multipleOf: 0.1,
        },
        topics: [],
        current: null,
        resolved: null,
        readiness,
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: "missing",
        state_seq: 7,
        contract_version: "contract-v4",
        context_fingerprint: "b".repeat(64),
        catalog: [],
        greenhouse_gas_accounting_standard_options: [],
        no_value_reasons: [
          "not_collected",
          "not_available",
          "not_applicable",
          "will_supplement",
        ],
        current: {
          metrics: {},
          greenhouseGasAccountingStandard: null,
          greenhouseGasAccountingStandardOther: null,
        },
        readiness,
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchAssessmentInput("report/id");
    await fetchQuantitativeMetricsInput("report/id");

    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "/api/reports/report%2Fid/structured-inputs/assessment",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toContain(
      "/api/reports/report%2Fid/structured-inputs/quantitative-metrics",
    );
  });

  it("在线写入只发送服务端合同字段和 expected_state_seq", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async () => new Response(JSON.stringify(mutation), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);

    await putAssessmentInput("report-id", {
      expected_state_seq: 7,
      threshold: { financial: 4, impact: 4 },
      scores: [{
        assessmentTopicId: "climate_change",
        financialScore: 4.2,
        impactScore: 4.5,
      }],
    });
    await putQuantitativeMetricsInput("report-id", {
      expected_state_seq: 8,
      metrics: {
        total_energy: { noValueReason: "not_collected" },
      },
      greenhouseGasAccountingStandard: null,
      greenhouseGasAccountingStandardOther: null,
    });

    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      expected_state_seq: 7,
      threshold: { financial: 4, impact: 4 },
      scores: [{
        assessmentTopicId: "climate_change",
        financialScore: 4.2,
        impactScore: 4.5,
      }],
    });
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      expected_state_seq: 8,
      metrics: {
        total_energy: { noValueReason: "not_collected" },
      },
      greenhouseGasAccountingStandard: null,
      greenhouseGasAccountingStandardOther: null,
    });
  });

  it("整批导入携带文件、expected_state_seq 与重要性阈值", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async () => new Response(JSON.stringify(mutation), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    vi.stubGlobal("fetch", fetchMock);
    const workbook = new File(["xlsx"], "input.xlsx");

    await importAssessmentWorkbook(
      "report-id",
      workbook,
      7,
      { financial: 4, impact: 4.2 },
    );
    await importQuantitativeMetricsWorkbook("report-id", workbook, 8);

    const assessmentForm = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(assessmentForm.get("file")).toBe(workbook);
    expect(assessmentForm.get("expected_state_seq")).toBe("7");
    expect(assessmentForm.get("financial_threshold")).toBe("4");
    expect(assessmentForm.get("impact_threshold")).toBe("4.2");
    const quantitativeForm = fetchMock.mock.calls[1]?.[1]?.body as FormData;
    expect(quantitativeForm.get("file")).toBe(workbook);
    expect(quantitativeForm.get("expected_state_seq")).toBe("8");
  });

  it("409 冲突必须暴露服务端权威快照，不允许客户端猜测合并", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => {
      return new Response(JSON.stringify({
        code: "report_state_conflict",
        message: "报告已在其他入口更新，请重新确认。",
        current: mutation,
      }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      putAssessmentInput("report-id", {
        expected_state_seq: 7,
        threshold: { financial: 4, impact: 4 },
        scores: [],
      }),
    ).rejects.toMatchObject({
      name: "StructuredInputConflictError",
      current: mutation,
    });
  });

  it("拒绝未通过后端同源 schema 的成功响应", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        status: "missing",
        state_seq: 7,
        contract_version: "contract-v4",
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    ));

    await expect(fetchAssessmentInput("report-id")).rejects.toThrow(
      "ReportApi 不符合合同",
    );
  });

  it("模板下载使用 report-bound 端点", async () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:test");
    const revokeObjectURL = vi.fn();
    const click = vi.fn();
    const remove = vi.fn();
    const append = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    vi.stubGlobal("document", {
      createElement: vi.fn().mockReturnValue({ href: "", download: "", click, remove }),
      body: { append },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("xlsx", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await downloadAssessmentTemplate("report-id");

    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "/api/reports/report-id/structured-inputs/assessment/template",
    );
    expect(click).toHaveBeenCalledOnce();
  });
});
