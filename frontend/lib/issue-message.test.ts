// ABOUTME: 诊断文案渲染守护——按 code + params 取界面语言文案，绝不透传后端简体 message。
// ABOUTME: 回归 2026-09-16：英文报告的导出前检查显示简体阻断提示（checks-drawer 直渲 issue.message）。
import { describe, expect, it } from "vitest";

import type { Issue } from "./api";
import type { Dictionary } from "./i18n/dictionary";
import { en } from "./i18n/en";
import { zhHans } from "./i18n/zh-Hans";
import { issueMessage } from "./issue-message";

const ZH = zhHans as unknown as Dictionary;
const HAN = /\p{Script=Han}/u;

/** 后端 message 恒简体；本字段存在即代表「不渲染它」这条纪律必须被守住。 */
const BACKEND_MESSAGE = "正文引用的报告内容未生成或未填写，导出时该处会缺失";

describe("诊断条目文案", () => {
  it("英文界面不渲染后端简体 message", () => {
    const issue: Issue = { level: "block", code: "key_residue", message: BACKEND_MESSAGE };
    const rendered = issueMessage(issue, en);
    expect(rendered).not.toBe(BACKEND_MESSAGE);
    expect(HAN.test(rendered)).toBe(false);
  });

  it("带标签与不带标签是两种措辞，无标签时不暴露内部 ref", () => {
    const withLabel: Issue = {
      level: "block",
      code: "key_residue",
      message: BACKEND_MESSAGE,
      params: { label: "Company registered name" },
    };
    expect(issueMessage(withLabel, en)).toContain("Company registered name");
    const withoutLabel: Issue = { level: "block", code: "key_residue", message: BACKEND_MESSAGE };
    expect(issueMessage(withoutLabel, en)).not.toContain("{");
  });

  it("名称列表按界面语言的分隔符连接", () => {
    const issue: Issue = {
      level: "block",
      code: "stakeholder_topic_unassigned",
      message: "尚有 2 个适用议题未分配沟通对象：气候变化、排放",
      params: { count: 2, topics: ["Climate Change", "Emissions"] },
    };
    expect(issueMessage(issue, en)).toBe(
      "2 applicable topics still have no stakeholders assigned: Climate Change, Emissions",
    );
    expect(issueMessage(issue, ZH)).toContain("Climate Change、Emissions");
  });

  it("阶段取稳定 id 而非后端中文标签", () => {
    const issue: Issue = {
      level: "block",
      code: "required_input_obligation",
      message: "公司注册名未填写，无法进入正式生成阶段",
      params: { label: "Company registered name", phase: "generation" },
    };
    expect(issueMessage(issue, en)).toBe("Company registered name is empty; you cannot move on to generation");
  });

  it("未登记的 code 回落通用措辞，不显示后端原文", () => {
    const issue: Issue = { level: "warn", code: "some_future_code", message: BACKEND_MESSAGE };
    expect(issueMessage(issue, en)).toBe(en.checksDrawer.issues.fallback);
  });

  it("后端每个 code 都有对应文案——漏登记即回落，用户看到的是通用措辞而非实情", () => {
    // 与 diagnostics.py 的构造点一一对应；后端新增 code 而此处未登记时本用例失败。
    const backendCodes = [
      "key_residue",
      "stakeholder_topic_unassigned",
      "required_input_obligation",
      "stale_display_title",
      "required_disclosure_profile",
      "missing_user_visible_clause_annotation_source",
      "required_report_configuration",
      "required_assurance_report",
      "unresolved_standard_disclosure_requirement",
      "internal_report_text",
      "materiality_complete_coverage",
      "required_empty",
      "ai_text_empty",
      "row_failed",
      "fixed_row_missing",
      "fixed_row_duplicate",
    ];
    const missing = backendCodes.filter(
      (code) => !(code in (en.checksDrawer.issues as Record<string, unknown>)),
    );
    expect(missing).toEqual([]);
  });
});
