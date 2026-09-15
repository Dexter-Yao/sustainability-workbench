// ABOUTME: 错误解析边界回归：detail 三种形态与非 JSON body 均收敛为携带 code 的 ApiError。
// ABOUTME: code 缺失时以 http_<status> 兜底；cellMessages 最多保留 3 条。
import { describe, expect, it } from "vitest";

import { ApiError, describeError, isSessionExpired, parseErrorResponse } from "./api-error";

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("parseErrorResponse", () => {
  it("解析 string detail", async () => {
    const error = await parseErrorResponse(jsonResponse({ detail: "无权访问" }, 403), "加载失败");
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("无权访问");
    expect(error.code).toBe("http_403");
    expect(error.httpStatus).toBe(403);
  });

  it("解析 object detail 的 code、message 与前 3 条 cellMessages", async () => {
    const error = await parseErrorResponse(
      jsonResponse(
        {
          detail: {
            code: "structured_input_workbook_invalid",
            message: "工作簿未通过完整校验。",
            errors: [{ message: "A2 非法" }, { message: "B3 非法" }, { message: "C4 非法" }, { message: "D5 非法" }],
          },
        },
        422,
      ),
      "导入失败",
    );
    expect(error.code).toBe("structured_input_workbook_invalid");
    expect(error.message).toBe("工作簿未通过完整校验。");
    expect(error.cellMessages).toEqual(["A2 非法", "B3 非法", "C4 非法"]);
  });

  it("FastAPI 请求体校验 422 收敛为稳定文案与可判定 code，不泄漏字段与输入片段", async () => {
    const error = await parseErrorResponse(
      jsonResponse(
        {
          detail: [
            { type: "extra_forbidden", loc: ["body", "report", "meta", "primaryInputMode"], msg: "Extra inputs are not permitted", input: "questions" },
          ],
        },
        422,
      ),
      "装配失败",
    );
    expect(error.code).toBe("request_body_invalid");
    expect(error.httpStatus).toBe(422);
    expect(error.message).toBe("装配失败：提交的数据不符合服务端合同。");
    expect(error.message).not.toContain("primaryInputMode");
    expect(error.message).not.toContain("questions");
  });

  it("cellMessages 携带工作表与单元格定位", async () => {
    const error = await parseErrorResponse(
      jsonResponse(
        {
          detail: {
            code: "structured_input_workbook_invalid",
            message: "工作簿未通过完整校验。",
            errors: [
              { sheet: "填写说明", row: 8, column: "B", message: "必须选择核算标准" },
              { message: "无定位信息" },
            ],
          },
        },
        422,
      ),
      "导入失败",
    );
    expect(error.cellMessages).toEqual(["填写说明 B8：必须选择核算标准", "无定位信息"]);
  });

  it("旧模板导入：重复文案去重，隐藏元数据页不作为单元格定位暴露给用户", async () => {
    const stale = "这份表格与当前模板不一致，可能是旧版本。请重新下载模板并填写后再导入。";
    const error = await parseErrorResponse(
      jsonResponse(
        {
          detail: {
            code: "structured_input_workbook_invalid",
            message: "工作簿未通过完整校验，未写入任何数据。",
            errors: [
              { sheet: "_模板元数据", row: 4, column: "B", message: stale },
              { sheet: "_模板元数据", row: 5, column: "B", message: stale },
              { sheet: "_模板元数据", row: 6, column: "B", message: stale },
            ],
          },
        },
        422,
      ),
      "导入失败",
    );
    // 同一句话不重复三遍；用户看不见的元数据页不冒充可定位单元格。
    expect(error.cellMessages).toEqual([stale]);
    expect(error.cellMessages[0]).not.toContain("_模板元数据");
    expect(error.cellMessages[0]).toContain("重新下载模板");
  });

  it("旧模板导入的完整用户可见串：一句可执行提示，且不含任何内部标识符", async () => {
    // 载荷取自后端真实产出（parse_report_basics_workbook 对过期上下文的三条 metadata_mismatch）。
    const stale = "这份表格与当前模板不一致，可能是旧版本。请重新下载模板并填写后再导入。";
    const error = await parseErrorResponse(
      jsonResponse(
        {
          detail: {
            code: "structured_input_workbook_invalid",
            message: "工作簿未通过完整校验，未写入任何数据。",
            errors: [
              { code: "metadata_mismatch", sheet: "_模板元数据", row: 4, column: "B", message: stale },
              { code: "metadata_mismatch", sheet: "_模板元数据", row: 5, column: "B", message: stale },
              { code: "metadata_mismatch", sheet: "_模板元数据", row: 6, column: "B", message: stale },
            ],
          },
        },
        422,
      ),
      "导入失败",
    );
    // lib/api.ts structuredInputError 以此串拼出页面提示。
    const shown = [error.message, ...error.cellMessages].join(" ");
    expect(shown).toBe(`工作簿未通过完整校验，未写入任何数据。 ${stale}`);
    for (const internal of ["_模板元数据", "context_fingerprint", "contract_version", "report_id"]) {
      expect(shown).not.toContain(internal);
    }
  });

  it("解析顶层 code+message 形态", async () => {
    const error = await parseErrorResponse(
      jsonResponse({ code: "report_state_conflict", message: "报告已更新。" }, 409),
      "保存失败",
    );
    expect(error.code).toBe("report_state_conflict");
    expect(error.message).toBe("报告已更新。");
  });

  it("非 JSON body 使用兜底文案与 http code", async () => {
    const error = await parseErrorResponse(new Response("<html>", { status: 502 }), "服务不可用");
    expect(error.message).toBe("服务不可用：HTTP 502");
    expect(error.code).toBe("http_502");
  });
});

describe("isSessionExpired", () => {
  it("仅 401 的 ApiError 判定为会话过期", async () => {
    const unauthorized = await parseErrorResponse(jsonResponse({ detail: "未授权" }, 401), "请求失败");
    expect(isSessionExpired(unauthorized)).toBe(true);
    expect(isSessionExpired(new ApiError({ message: "x", code: "http_500", httpStatus: 500 }))).toBe(false);
    expect(isSessionExpired(new Error("装配失败：HTTP 401"))).toBe(false);
    expect(isSessionExpired(null)).toBe(false);
  });
});

describe("describeError", () => {
  it("Error 取 message，空值给未知错误", () => {
    expect(describeError(new Error("网络中断"))).toBe("网络中断");
    expect(describeError(null)).toBe("未知错误");
    expect(describeError("字符串原因")).toBe("字符串原因");
  });
});
