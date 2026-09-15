// ABOUTME: 运行时报告模板边界测试，确保产品只加载无用户值契约而不加载演示实例。
// ABOUTME: 同时验证前端公开契约不携带样例企业或其他用户填报状态。
import { describe, expect, it, vi } from "vitest";

import contractJson from "../public/contract.json";
import { applyReportInputDefaults } from "./report-input-guidance";
import { loadReportTemplate } from "./report-template";
import type { Report } from "./schema";
import { newReportStoredState } from "./stored-report-state";

describe("loadReportTemplate", () => {
  it("loads the blank public contract instead of the sample instance", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => contractJson });

    await expect(loadReportTemplate(fetcher)).resolves.toEqual(contractJson);
    expect(fetcher).toHaveBeenCalledWith("/contract.json");
  });

  it("rejects malformed runtime contracts instead of returning null", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ title: "损坏合同", fields: {}, sections: [], unknown: true }),
    });

    await expect(loadReportTemplate(fetcher)).rejects.toThrow("Report 不符合合同");
  });

  it("propagates contract fetch failures instead of returning null", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("network down"));

    await expect(loadReportTemplate(fetcher)).rejects.toThrow("network down");
  });

  it("keeps the public runtime contract free of user and sample state", () => {
    const report = contractJson as unknown as Report;
    const serialized = JSON.stringify(report).toLowerCase();

    expect(serialized).not.toContain("晟原");
    expect(serialized).not.toContain("shengyuan");
    expect(
      Object.values(report.fields).filter((field) => field.source === "user_input").every(
        (field) => field.value === undefined || field.value === null || field.value === "",
      ),
    ).toBe(true);
    expect(
      (report.intakeItems ?? []).every(
        (item) =>
          (item.answer === undefined || item.answer === null || item.answer === "") &&
          (item.supplement === undefined || item.supplement === null || item.supplement === ""),
      ),
    ).toBe(true);
  });

  it("默认 fetch 路径缓存原始 JSON，仅首次调用发起网络请求", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => contractJson });
    // report-template.ts 只对全局 fetch 生效缓存；模拟“默认参数”场景需直接调用不传自定义 fetcher。
    vi.stubGlobal("fetch", fetcher);

    const { loadReportTemplate: loadWithGlobalFetch } = await import("./report-template");
    await loadWithGlobalFetch();
    await loadWithGlobalFetch();

    expect(fetcher).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("测试注入的 fetcher 路径不缓存，每次都重新取回", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => contractJson });

    await loadReportTemplate(fetcher);
    await loadReportTemplate(fetcher);

    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("默认 fetch 路径失败后清空缓存，下次调用可重试", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce({ ok: true, json: async () => contractJson });
    vi.stubGlobal("fetch", fetcher);

    const { loadReportTemplate: loadWithGlobalFetch } = await import("./report-template");
    await expect(loadWithGlobalFetch()).rejects.toThrow("network down");
    await expect(loadWithGlobalFetch()).resolves.toEqual(contractJson);

    expect(fetcher).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("保留多语言发布规则，但不虚构当前英文版本", () => {
    const report = contractJson as unknown as Report;
    // 「关于本报告」的正文分布在各小节（报告范围/时间范围/…），逐层取块而非只读章级块。
    const collect = (section: Report["sections"][number]): Report["sections"][number]["blocks"] => [
      ...section.blocks,
      ...(section.children ?? []).flatMap(collect),
    ];
    const about = report.sections.find((section) => section.key === "about_report");
    const text = (about ? collect(about) : [])
      .flatMap((block) => block.content ?? [])
      .filter((inline) => inline.kind === "text")
      .map((inline) => inline.text ?? "")
      .join("");

    expect(text).toContain("提供简体中文版本。若另行发布其他语言版本，如内容存在差异，以简体中文版为准。");
    expect(text).not.toContain("简体中文与英文两种版本");
  });

  it("新建报告的首个状态不携带任何空块骨架", () => {
    // 写入边界按报告侧口径全等比较：范围外章节的空块一旦
    // 随首个状态写入即判为范围外并 403，新建流程会在第二步失败、报告建成却进不去。
    // 空块不是用户事实，任何范围都不该写入，因此在此以范围无关的不变量钉住。
    const template = contractJson as unknown as Report;
    const state = newReportStoredState(applyReportInputDefaults(template, new Date("2026-07-15T00:00:00+08:00")));

    expect(state.generatedBlocks).toEqual({});
    expect(state.tableBlocks).toEqual({});
    expect(state.imageBlocks).toEqual({});
    expect(state.sectionTitles).toEqual({});
    expect(state.intakeItems).toEqual({});
  });

  it("新建报告的首个状态仍落定输入默认值与模板初始配置", () => {
    const template = contractJson as unknown as Report;
    const state = newReportStoredState(applyReportInputDefaults(template, new Date("2026-07-15T00:00:00+08:00")));

    expect(state.fields).toMatchObject({
      reporting_year: "2025",
      report_period_start: "2025-01-01",
      report_period_end: "2025-12-31",
    });
    expect(state.disclosureProfile).toEqual(template.disclosureProfile ?? null);
    expect(state.appendixPackage).toEqual(template.appendixPackage ?? null);
  });
});
