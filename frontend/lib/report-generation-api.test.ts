// ABOUTME: 报告级生成前端 API 的 parse-first、显式命令、轮询与客户交付边界测试。
// ABOUTME: 测试证明页面只消费服务端运行投影，且内部审计包无法进入客户下载路径。

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createReportGeneration,
  customerVisibleArtifacts,
  fetchLatestReportGeneration,
  fetchReportGeneration,
  isReportGenerationActive,
  reportGenerationIntent,
  type ReportGeneration,
} from "./report-generation-api";

vi.mock("./supabase", () => ({ accessToken: async () => "test-token" }));

const reportId = "00000000-0000-4000-8000-000000000001";
const runId = "00000000-0000-4000-8000-000000000002";

function projection(
  overrides: Partial<ReportGeneration> = {},
): ReportGeneration {
  return {
    contract: "sustainability_desk.report_generation.v1",
    run_id: runId,
    report_id: reportId,
    status: "running",
    base_report_state_seq: 8,
    result_report_state_seq: null,
    completed_block_count: 3,
    total_block_count: 10,
    summary: "系统正在依据当前资料生成完整报告。",
    events: [
      {
        sequence: 1,
        event_type: "started",
        message: "系统已开始生成完整报告。",
        current_object: null,
        action_required: false,
        occurred_at: "2026-07-30T09:00:00Z",
      },
    ],
    artifacts: [],
    workbench_enabled: true,
    ...overrides,
  };
}

describe("report generation browser API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("以显式幂等命令发起生成并解析服务端投影", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(projection()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createReportGeneration(
      reportId,
      8,
      "00000000-0000-4000-8000-000000000003",
    );

    expect(result.run_id).toBe(runId);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/api/reports/${reportId}/generations`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      base_report_state_seq: 8,
      idempotency_key: "00000000-0000-4000-8000-000000000003",
    });
  });

  it("选定模型时随请求下发 model_id，省略时不出现该键", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(projection()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createReportGeneration(
      reportId,
      8,
      "00000000-0000-4000-8000-000000000004",
      "openai-compatible",
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      base_report_state_seq: 8,
      idempotency_key: "00000000-0000-4000-8000-000000000004",
      model_id: "openai-compatible",
    });
  });

  it("latest 无运行时返回 null，公共合同拒绝内部审计包", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 404 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify(
            {
              ...projection({
                status: "succeeded",
              }),
              status: "succeeded",
              artifacts: [
                {
                  artifact_id: "00000000-0000-4000-8000-000000000009",
                  kind: "internal_audit",
                  filename: "内部审计包.json",
                  media_type: "application/json",
                  download_href: `/api/reports/${reportId}/generations/${runId}/artifacts/00000000-0000-4000-8000-000000000009/download`,
                },
              ],
            },
          ),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLatestReportGeneration(reportId)).resolves.toBeNull();
    await expect(fetchReportGeneration(reportId, runId)).rejects.toThrow(
      "ReportApi 不符合合同",
    );
  });

  it("拒绝绕过公共合同的伪进度响应", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            ...projection(),
            total_block_count: 0,
            internal_path: "/private/debug.json",
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      ),
    );

    await expect(fetchLatestReportGeneration(reportId)).rejects.toThrow(
      "ReportApi 不符合合同",
    );
  });

  it("客户合同只允许 Word 与审阅版报告", async () => {
    const generation = projection({
      status: "succeeded",
      artifacts: [
        {
          artifact_id: "00000000-0000-4000-8000-000000000011",
          kind: "word",
          filename: "ESG报告.docx",
          media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          download_href: `/api/reports/${reportId}/generations/${runId}/artifacts/00000000-0000-4000-8000-000000000011/download`,
        },
        {
          artifact_id: "00000000-0000-4000-8000-000000000012",
          kind: "review",
          filename: "审阅版报告.docx",
          media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          download_href: `/api/reports/${reportId}/generations/${runId}/artifacts/00000000-0000-4000-8000-000000000012/download`,
        },
      ],
    });

    expect(customerVisibleArtifacts(generation).map((item) => item.kind)).toEqual([
      "word",
      "review",
    ]);
  });

  it("仅以公共运行状态决定是否继续轮询", () => {
    expect(isReportGenerationActive("queued")).toBe(true);
    expect(isReportGenerationActive("running")).toBe(true);
    expect(isReportGenerationActive("succeeded")).toBe(false);
    expect(isReportGenerationActive("failed")).toBe(false);
    expect(isReportGenerationActive("superseded")).toBe(false);
  });

  it("同一报告输入重试复用幂等键，输入版本变化才创建新意图", () => {
    const createKey = vi
      .fn()
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000021")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000022");
    const first = reportGenerationIntent(null, reportId, 8, createKey, null);
    const retry = reportGenerationIntent(first, reportId, 8, createKey, null);
    const changed = reportGenerationIntent(first, reportId, 9, createKey, null);

    expect(retry).toBe(first);
    expect(changed.idempotencyKey).toBe(
      "00000000-0000-4000-8000-000000000022",
    );
    expect(createKey).toHaveBeenCalledTimes(2);
  });

  it("换模型必须轮换幂等键，否则服务端会判冲突或拿回旧模型的运行", () => {
    const createKey = vi
      .fn()
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000031")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000032");
    const onDefault = reportGenerationIntent(null, reportId, 8, createKey, null);
    const sameModel = reportGenerationIntent(onDefault, reportId, 8, createKey, null);
    const switched = reportGenerationIntent(
      onDefault,
      reportId,
      8,
      createKey,
      "openai-compatible",
    );

    expect(sameModel).toBe(onDefault);
    expect(onDefault.modelId).toBeNull();
    expect(switched.modelId).toBe("openai-compatible");
    expect(switched.idempotencyKey).toBe(
      "00000000-0000-4000-8000-000000000032",
    );
    expect(createKey).toHaveBeenCalledTimes(2);
  });
});
