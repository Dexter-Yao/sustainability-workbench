// ABOUTME: 资料工作区前端硬边界与用途合同的回归测试。
// ABOUTME: 测试不调用真实存储或模型，只验证浏览器必须 fail-loud 的确定性合同。

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  confirmMaterialSet,
  fetchMaterialWorkspace,
  fetchReportFileIntake,
  MATERIAL_MAX_FILE_BYTES,
  locatorLabel,
  materialSourceMatchesScope,
  projectLatestMaterialIngressBatch,
  removeReportFile,
  restoreReportFile,
  uploadReportFiles,
  selectMaterialWorkspaceSnapshot,
  selectReportFileIntakeSnapshot,
  validateMaterialFiles,
  type MaterialWorkspaceSnapshot,
  type MaterialSource,
  type ReportFileIntake,
} from "./material-workspace-api";
import { parseMaterialWorkspace } from "./material-workspace-contract";

vi.mock("./supabase", () => ({ accessToken: async () => "test-token" }));

const file = (name: string, size = 100): Pick<File, "name" | "size"> => ({ name, size });
const workspace = (
  reportId: string,
  stateSeq: number,
  projectionSeq = stateSeq,
): MaterialWorkspaceSnapshot => ({
  id: "00000000-0000-4000-8000-000000000001",
  report_id: reportId,
  adapter_id: "test",
  contract_version: "test",
  state_seq: stateSeq,
  projection_seq: projectionSeq,
  report_state_seq: stateSeq,
  sources: [],
  messages: [],
  clarifications: [],
  proposals: [],
  facts: [],
  gaps: [],
  topic_primary_input_modes: {},
  scope_summaries: [],
});

const reportFileIntake = (reportId: string, projectionSeq = 1) => ({
  report_id: reportId,
  projection_seq: projectionSeq,
  policy: {
    max_files_per_report: 30,
    max_file_bytes: 10 * 1024 * 1024,
    max_pdf_pages: 10,
    description_min_chars: 10,
    description_max_chars: 100,
    asset_title_max_chars: 100,
    semantic_material_kinds: ["pdf", "docx", "xlsx"],
    layout_asset_kinds: ["png", "jpeg", "webp"],
    semantic_material_extensions: [".pdf", ".docx", ".xlsx"],
    layout_asset_extensions: [".png", ".jpg", ".jpeg", ".webp"],
    topic_tags: [
      { id: "uncertain", label: "暂不确定", kind: "auxiliary" },
      { id: "climate_change", label: "应对气候变化", kind: "report_section" },
    ],
  },
  active_file_count: 0,
  sources: [],
  ingress_receipts: [],
  material_set_confirmation: {
    status: "not_required" as const,
    confirmed_at: null,
    pending_description_count: 0,
  },
});

describe("material workspace browser contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("将 fetch 传输失败映射为稳定、可行动的资料域错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(fetchMaterialWorkspace("report-1")).rejects.toThrow(
      "无法连接资料工作区，请检查网络后重试",
    );
  });

  it("只接受当前报告的单调快照，避免旧轮询覆盖 mutation 结果", () => {
    const current = workspace("report-1", 8, 20);
    const stalePoll = workspace("report-1", 9, 19);
    const currentPoll = workspace("report-1", 8, 20);
    const nextMutation = workspace("report-1", 8, 21);
    const nextReportEdit = {
      ...workspace("report-1", 8, 20),
      report_state_seq: 9,
    };
    const otherReport = workspace("report-2", 99);

    expect(selectMaterialWorkspaceSnapshot(current, stalePoll, "report-1")).toBe(current);
    expect(selectMaterialWorkspaceSnapshot(current, currentPoll, "report-1")).toBe(current);
    expect(selectMaterialWorkspaceSnapshot(current, nextMutation, "report-1")).toBe(nextMutation);
    expect(selectMaterialWorkspaceSnapshot(current, nextReportEdit, "report-1")).toBe(nextReportEdit);
    expect(selectMaterialWorkspaceSnapshot(current, otherReport, "report-1")).toBe(current);
    expect(selectMaterialWorkspaceSnapshot(null, otherReport, "report-1")).toBeNull();
  });

  it("报告文件准入快照只接受较新序号，乱序旧响应不覆盖当前状态", () => {
    const intakeSnapshot = (
      reportId: string,
      projectionSeq: number,
      activeFileCount = 0,
    ): ReportFileIntake => ({
      ...reportFileIntake(reportId, projectionSeq),
      active_file_count: activeFileCount,
    }) as unknown as ReportFileIntake;
    const current = intakeSnapshot("report-1", 20, 2);
    const stalePoll = intakeSnapshot("report-1", 19, 3);
    const samePoll = intakeSnapshot("report-1", 20, 2);
    const sameSeqChanged = intakeSnapshot("report-1", 20, 3);
    const nextMutation = intakeSnapshot("report-1", 21, 1);
    const otherReport = intakeSnapshot("report-2", 99);

    expect(selectReportFileIntakeSnapshot(current, stalePoll, "report-1")).toBe(current);
    expect(selectReportFileIntakeSnapshot(current, samePoll, "report-1")).toBe(current);
    expect(selectReportFileIntakeSnapshot(current, sameSeqChanged, "report-1")).toBe(sameSeqChanged);
    expect(selectReportFileIntakeSnapshot(current, nextMutation, "report-1")).toBe(nextMutation);
    expect(selectReportFileIntakeSnapshot(current, otherReport, "report-1")).toBe(current);
    expect(selectReportFileIntakeSnapshot(null, otherReport, "report-1")).toBeNull();
    expect(selectReportFileIntakeSnapshot(null, nextMutation, "report-1")).toBe(nextMutation);
  });

  it("同版本快照以持久化 ingress receipts 判断新旧，不再依赖瞬时上传错误", () => {
    const rejectedReceipt = {
      receipt_id: "00000000-0000-4000-8000-000000000021",
      batch_id: "00000000-0000-4000-8000-000000000022",
      filename: "oversized.pdf",
      status: "rejected" as const,
      reason_code: "file_rejected" as const,
      message: "文件超过准入大小上限。",
      next_action: "压缩文件后重新上传。",
    };
    const current = {
      ...workspace("report-1", 8, 20),
      ingress_receipts: [rejectedReceipt],
    };
    const sameReceipts = {
      ...workspace("report-1", 8, 20),
      ingress_receipts: [rejectedReceipt],
    };
    const nextReceipt = {
      ...workspace("report-1", 8, 20),
      ingress_receipts: [
        rejectedReceipt,
        {
          ...rejectedReceipt,
          receipt_id: "00000000-0000-4000-8000-000000000023",
          filename: "damaged.docx",
        },
      ],
    };

    expect(selectMaterialWorkspaceSnapshot(current, sameReceipts, "report-1")).toBe(current);
    expect(selectMaterialWorkspaceSnapshot(current, nextReceipt, "report-1")).toBe(nextReceipt);
  });

  it("只按响应最后一个 batch_id 投影本批准入结果", () => {
    const snapshot = {
      ...workspace("report-1", 8, 20),
      ingress_receipts: [
        {
          receipt_id: "00000000-0000-4000-8000-000000000031",
          batch_id: "00000000-0000-4000-8000-000000000032",
          filename: "history.pdf",
          status: "rejected" as const,
          reason_code: "file_rejected" as const,
          message: "历史拒绝。",
          next_action: "历史下一步。",
        },
        {
          receipt_id: "00000000-0000-4000-8000-000000000033",
          batch_id: "00000000-0000-4000-8000-000000000034",
          filename: "accepted.docx",
          status: "accepted" as const,
          reason_code: "admitted" as const,
          source_id: "00000000-0000-4000-8000-000000000035",
          sha256: "a".repeat(64),
          message: "已上传。",
          next_action: "等待解析。",
        },
        {
          receipt_id: "00000000-0000-4000-8000-000000000036",
          batch_id: "00000000-0000-4000-8000-000000000034",
          filename: "rejected.xlsx",
          status: "rejected" as const,
          reason_code: "upload_failed" as const,
          message: "上传流程失败。",
          next_action: "重新上传。",
        },
      ],
    };

    const batch = projectLatestMaterialIngressBatch(snapshot);

    expect(batch.batchId).toBe("00000000-0000-4000-8000-000000000034");
    expect(batch.receipts.map((receipt) => receipt.filename)).toEqual([
      "accepted.docx",
      "rejected.xlsx",
    ]);
    expect(batch.receivedCount).toBe(1);
    expect(batch.rejectedReceipts.map((receipt) => receipt.filename)).toEqual([
      "rejected.xlsx",
    ]);
  });

  it("在 HTTP 边界拒绝缺少公共合同字段的快照", () => {
    const invalid = {
      ...workspace("00000000-0000-4000-8000-000000000002", 1),
      projection_seq: undefined,
    };
    expect(() => parseMaterialWorkspace(invalid)).toThrow(
      "资料工作区响应不符合资料工作区合同",
    );
  });

  it("接受 MLP 文件并在旧 Office、未知格式、超限和超量时明确失败", () => {
    expect(validateMaterialFiles([file("report.pdf"), file("ledger.xlsx"), file("photo.jpeg")])).toBeNull();
    expect(validateMaterialFiles([file("old.doc")])).toContain("转换为 .docx");
    expect(validateMaterialFiles([file("archive.zip")])).toContain("格式不受支持");
    expect(validateMaterialFiles([file("large.pdf", MATERIAL_MAX_FILE_BYTES + 1)])).toContain("20MB");
    expect(validateMaterialFiles(Array.from({ length: 11 }, (_, index) => file(`${index}.png`)))).toContain("最多上传 10");
  });

  it("按 typed locator 生成人类可核验的位置", () => {
    expect(locatorLabel({ kind: "pdf_page", page: 7 })).toBe("第 7 页");
    expect(locatorLabel({ kind: "docx_table", table_index: 2, row_start: 3, row_end: 5 })).toBe("表格 2 · 第 3–5 行");
    expect(locatorLabel({ kind: "xlsx_range", sheet_name: "员工", cell_range: "B2:D9" })).toBe("员工 · B2:D9");
    expect(locatorLabel({ kind: "image_region", region_label: "右上角印章" })).toBe("图片区域 右上角印章");
  });

  it("资料来源只进入声明的 scope，不把暂未归属资料泄漏到议题", () => {
    const source = {
      id: "source-1",
      filename: "待归属资料.docx",
      content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      size_bytes: 100,
      sha256: "a".repeat(64),
      scope: { kind: "uncertain", report_section_ids: [] },
      status: "ready",
      content_availability: "available",
      can_retry: false,
      parse_result: {
        status: "available",
        fragment_count: 2,
        fragment_kinds: ["text", "table"],
        summary: "已取得 2 个可定位片段（text、table）。",
      },
      processing_steps: [],
      created_at: "2026-07-23T00:00:00Z",
      updated_at: "2026-07-23T00:00:00Z",
    } satisfies MaterialSource;
    expect(materialSourceMatchesScope(source, { kind: "uncertain", report_section_ids: [] })).toBe(true);
    expect(materialSourceMatchesScope(source, { kind: "topics", report_section_ids: ["climate_change"] })).toBe(false);
    expect(materialSourceMatchesScope(source, { kind: "report", report_section_ids: [] })).toBe(true);
  });

  it("报告文件入口只提交逐文件声明，不泄露旧用途或范围语义", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(
      reportFileIntake("00000000-0000-4000-8000-000000000041"),
    ), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await uploadReportFiles(
      "report-1",
      [new File(["evidence"], "climate.docx", {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      })],
      [{
        description: "2025 年度温室气体核算台账及边界说明",
        role: "semantic_material",
        topic_tags: ["climate_change"],
        asset_title: null,
      }],
    );

    const uploadCall = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit];
    expect(String(uploadCall[0])).toContain("/file-intake/files");
    const submitted = uploadCall[1].body as FormData;
    expect(Array.from(submitted.keys())).toEqual(["files", "declarations"]);
    expect(JSON.parse(String(submitted.get("declarations")))).toEqual([{
      description: "2025 年度温室气体核算台账及边界说明",
      role: "semantic_material",
      topic_tags: ["climate_change"],
      asset_title: null,
    }]);
    expect(Array.from(submitted.keys())).not.toContain("purpose");
    expect(Array.from(submitted.keys())).not.toContain("scope_kind");
  });

  it("上传允许空文件说明（先上传后补充），且无 XMLHttpRequest 环境时安全回退 fetch", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(
      reportFileIntake("00000000-0000-4000-8000-000000000041"),
    ), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const onProgress = vi.fn();

    const result = await uploadReportFiles(
      "report-1",
      [new File(["evidence"], "climate.docx", {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      })],
      [{
        description: "",
        role: "semantic_material",
        topic_tags: ["climate_change"],
        asset_title: null,
      }],
      onProgress,
    );

    expect(result.report_id).toBe("00000000-0000-4000-8000-000000000041");
    const uploadCall = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit];
    const submitted = uploadCall[1].body as FormData;
    expect(JSON.parse(String(submitted.get("declarations")))).toEqual([{
      description: "",
      role: "semantic_material",
      topic_tags: ["climate_change"],
      asset_title: null,
    }]);
    // Node 测试环境没有 XMLHttpRequest，进度回调不会被调用，但上传本身不受影响。
    expect(onProgress).not.toHaveBeenCalled();
  });

  it("上传失败时把冲突状态映射为可识别的资料工作区冲突错误", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "文件说明已被同事更新" }),
      { status: 409, headers: { "Content-Type": "application/json" } },
    )));

    await expect(uploadReportFiles(
      "report-1",
      [new File(["evidence"], "climate.docx")],
      [{ description: "", role: "semantic_material", topic_tags: ["climate_change"], asset_title: null }],
    )).rejects.toMatchObject({ message: "文件说明已被同事更新" });
  });

  it("文件入口只接收 File Agent 的受限状态和 Dossier 摘要", async () => {
    const payload = {
      ...reportFileIntake("00000000-0000-4000-8000-000000000041"),
      sources: [{
        binding_id: "00000000-0000-4000-8000-000000000051",
        source_id: "00000000-0000-4000-8000-000000000052",
        binding_status: "active",
        filename: "climate.docx",
        content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes: 120,
        sha256: "a".repeat(64),
        declaration: {
          revision_id: "00000000-0000-4000-8000-000000000053",
          binding_id: "00000000-0000-4000-8000-000000000051",
          revision: 1,
          description: "2025 年度温室气体核算台账及边界说明",
          role: "semantic_material",
          topic_tags: ["climate_change"],
          asset_title: null,
          declared_at: "2026-07-30T00:00:00Z",
        },
        admission_status: "admitted",
        error_message: null,
        file_analysis: {
          status: "succeeded",
          dossier: {
            relevance: "relevant",
            relevance_reason: "文件提供温室气体管理制度和边界说明。",
            applicable_scope_count: 1,
            attention_items: [{
              message: "请确认该台账覆盖完整报告期间。",
              next_action: "补充期间说明。",
            }],
            report_scope: "within_report",
            report_scope_notice: null,
          },
        },
        created_at: "2026-07-30T00:00:00Z",
        updated_at: "2026-07-30T00:00:00Z",
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));

    const intake = await fetchReportFileIntake(payload.report_id);

    expect(intake.sources[0].file_analysis).toEqual(payload.sources[0].file_analysis);
    expect(Object.keys(intake.sources[0].file_analysis ?? {})).toEqual([
      "status",
      "dossier",
    ]);
    expect(Object.keys(intake.sources[0].file_analysis?.dossier ?? {})).toEqual([
      "relevance",
      "relevance_reason",
      "applicable_scope_count",
      "attention_items",
      "report_scope",
      "report_scope_notice",
    ]);
  });

  it("报告文件成员关系使用显式移出与恢复命令，不发送 DELETE", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(
      reportFileIntake("00000000-0000-4000-8000-000000000041"),
    ), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    await removeReportFile("report-1", "binding-1");
    await restoreReportFile("report-1", "binding-1");

    const removeCall = fetchMock.mock.calls[0] as unknown as [
      RequestInfo | URL,
      RequestInit,
    ];
    const restoreCall = fetchMock.mock.calls[1] as unknown as [
      RequestInfo | URL,
      RequestInit,
    ];
    expect(String(removeCall[0])).toContain(
      "/file-intake/files/binding-1/remove",
    );
    expect(removeCall[1].method).toBe("POST");
    expect(String(restoreCall[0])).toContain(
      "/file-intake/files/binding-1/restore",
    );
    expect(restoreCall[1].method).toBe("POST");
    expect([removeCall, restoreCall].some((call) => call[1].method === "DELETE")).toBe(false);
  });

  it("确认资料集齐备时提交 confirm 命令并返回最新投影", async () => {
    const confirmed = {
      ...reportFileIntake("00000000-0000-4000-8000-000000000041"),
      material_set_confirmation: {
        status: "confirmed" as const,
        confirmed_at: "2026-08-03T00:00:00Z",
        pending_description_count: 0,
      },
    };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(confirmed), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await confirmMaterialSet("report-1");

    const call = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit];
    expect(String(call[0])).toContain("/file-intake/confirm");
    expect(call[1].method).toBe("POST");
    expect(result.material_set_confirmation.status).toBe("confirmed");
  });

  it("确认资料集时说明未齐，把 409 映射为携带真实原因的错误", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "还有 2 份文件待补充说明，无法确认资料集" }),
      { status: 409, headers: { "Content-Type": "application/json" } },
    )));

    await expect(confirmMaterialSet("report-1")).rejects.toMatchObject({
      message: "还有 2 份文件待补充说明，无法确认资料集",
    });
  });

});
