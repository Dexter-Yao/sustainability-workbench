// ABOUTME: 前端输入类型约束回归，防止数值和时间字段退化为自由文本输入。
// ABOUTME: 业务范围仍由 Report 契约声明；本测试只验证通用控件和写入校验映射。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  fieldInputAttributes,
  finalizeDecimalDraft,
  isDecimalDraft,
  isFieldDraftAllowed,
  isFieldValueAllowed,
  isNumericDraft,
  isPhoneInput,
  normalizeDecimalPaste,
} from "./input-validation";

describe("input validation", () => {
  it("从 Field.type 派生数值与时间控件", () => {
    expect(fieldInputAttributes("number")).toMatchObject({ type: "text", inputMode: "decimal" });
    expect(fieldInputAttributes("percent")).toMatchObject({ type: "text", inputMode: "decimal" });
    expect(fieldInputAttributes("year")).toMatchObject({ type: "text", inputMode: "numeric" });
    expect(fieldInputAttributes("month")).toEqual({ type: "month" });
    expect(fieldInputAttributes("date")).toEqual({ type: "date" });
  });

  it("拒绝数值、年份、日期和月份字段中的自由文本", () => {
    expect(isFieldValueAllowed("number", "-12.5")).toBe(true);
    expect(isFieldValueAllowed("number", "1e3")).toBe(false);
    expect(isFieldValueAllowed("number", "12吨")).toBe(false);
    expect(isFieldValueAllowed("percent", "100.01")).toBe(false);
    expect(isFieldValueAllowed("year", "2026")).toBe(true);
    expect(isFieldValueAllowed("year", "26年")).toBe(false);
    expect(isFieldValueAllowed("date", "2026-02-29")).toBe(false);
    expect(isFieldValueAllowed("date", "2024-02-29")).toBe(true);
    expect(isFieldValueAllowed("month", "2026-13")).toBe(false);
  });

  it("指标与评分草稿接收十进制中间态，仍拒绝单位与说明文字", () => {
    expect(isDecimalDraft("0")).toBe(true);
    expect(isDecimalDraft("123.45")).toBe(true);
    expect(isDecimalDraft("3.")).toBe(true);
    expect(isDecimalDraft(".5")).toBe(true);
    expect(isDecimalDraft("-")).toBe(true);
    expect(isDecimalDraft("12% ")).toBe(false);
    expect(isDecimalDraft("12吨")).toBe(false);
    expect(isNumericDraft("4.5")).toBe(true);
    expect(isNumericDraft("4.")).toBe(true);
    expect(isNumericDraft("4/5")).toBe(false);
  });

  it("草稿层允许键入中间态，严格层继续拒绝不完整值", () => {
    expect(isFieldDraftAllowed("year", "2")).toBe(true);
    expect(isFieldDraftAllowed("year", "202")).toBe(true);
    expect(isFieldDraftAllowed("year", "20261")).toBe(false);
    expect(isFieldValueAllowed("year", "202")).toBe(false);
    expect(isFieldDraftAllowed("date", "2026-0")).toBe(true);
    expect(isFieldValueAllowed("date", "2026-0")).toBe(false);
    expect(isFieldDraftAllowed("number", "3.")).toBe(true);
    expect(isFieldValueAllowed("number", "3.")).toBe(false);
    expect(isFieldDraftAllowed("percent", "150")).toBe(false);
    expect(isFieldDraftAllowed("percent", "99.")).toBe(true);
  });

  it("粘贴清洗移除千分位与全角字符，不剥离单位", () => {
    expect(normalizeDecimalPaste("1,234.5")).toBe("1234.5");
    expect(normalizeDecimalPaste("１２３．４")).toBe("123.4");
    expect(normalizeDecimalPaste(" 1 234，5 ")).toBe("12345");
    expect(normalizeDecimalPaste("－12")).toBe("-12");
    expect(normalizeDecimalPaste("12吨")).toBe("12吨");
  });

  it("提交收敛把草稿转成严格十进制值，无法收敛视作未填写", () => {
    expect(finalizeDecimalDraft("3.")).toBe("3");
    expect(finalizeDecimalDraft(".5")).toBe("0.5");
    expect(finalizeDecimalDraft("007")).toBe("7");
    expect(finalizeDecimalDraft("-")).toBe("");
    expect(finalizeDecimalDraft(".")).toBe("");
    expect(finalizeDecimalDraft("")).toBe("");
    expect(finalizeDecimalDraft("123.45")).toBe("123.45");
  });

  it("电话输入不接受自由文本，但保留合法区号和分隔符", () => {
    expect(isPhoneInput("+86 025-12345678")).toBe(true);
    expect(isPhoneInput("请致电前台")).toBe(false);
  });

  it("邮箱严格层与后端 is_valid_contact_email 对 golden fixture 判定一致", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const golden = JSON.parse(
      readFileSync(join(here, "../../backend/tests/fixtures/email_validation_golden.json"), "utf-8"),
    ) as { cases: { value: string; expected: boolean }[] };
    expect(golden.cases.length).toBeGreaterThan(0);
    for (const { value, expected } of golden.cases) {
      expect(isFieldValueAllowed("email", value), value).toBe(expected);
    }
    // 空串代表未填写，允许写回（清空）。
    expect(isFieldValueAllowed("email", "")).toBe(true);
  });
});
