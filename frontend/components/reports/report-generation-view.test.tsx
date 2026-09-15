// ABOUTME: 报告生成与交付视图测试，锁定服务端事件直出、可行动异常和客户交付边界。
// ABOUTME: 页面不把 event_type 解释为浏览器阶段，也不显示或提供 internal_audit。
// @vitest-environment happy-dom

import { cleanup, render as renderRtl, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportGeneration } from "@/lib/report-generation-api";
import {
  ReportGenerationView,
  reportGenerationProgress,
} from "./report-generation-view";

const reportId = "00000000-0000-4000-8000-000000000001";
const runId = "00000000-0000-4000-8000-000000000002";

function generation(
  overrides: Partial<ReportGeneration> = {},
): ReportGeneration {
  return {
    contract: "sustainability_desk.report_generation.v1",
    run_id: runId,
    report_id: reportId,
    status: "running",
    base_report_state_seq: 8,
    result_report_state_seq: null,
    completed_block_count: 2,
    total_block_count: 8,
    summary: "正在依据当前输入形成报告。",
    events: [
      {
        sequence: 1,
        event_type: "started",
        message: "系统已开始生成完整报告。",
        current_object: null,
        action_required: false,
        occurred_at: "2026-07-30T09:00:00Z",
      },
      {
        sequence: 2,
        event_type: "block_completed",
        message: "气候风险相关内容已经完成。",
        current_object: "应对气候变化",
        action_required: false,
        occurred_at: "2026-07-30T09:01:00Z",
      },
    ],
    artifacts: [],
    workbench_enabled: true,
    ...overrides,
  };
}

function render(value: ReportGeneration): string {
  return renderToStaticMarkup(
    <ReportGenerationView
      generation={value}
      refreshing={false}
      error={null}
      downloadingArtifactId={null}
      onRefresh={vi.fn()}
      onDownload={vi.fn()}
    />,
  );
}

afterEach(cleanup);

describe("ReportGenerationView", () => {
  it("直接展示服务端友好事件和真实完成计数，不显示内部 event_type", () => {
    const html = render(generation());

    expect(html).toContain("已完成 2 /");
    expect(html).toContain("8 项报告内容");
    expect(html).not.toContain("block_completed");
    expect(html).toContain('aria-valuenow="25"');
  });

  it("运行中默认展开运行记录（活动实时跟随），展示服务端友好事件文案，不显示内部 event_type", () => {
    renderRtl(
      <ReportGenerationView
        generation={generation()}
        refreshing={false}
        error={null}
        downloadingArtifactId={null}
        onRefresh={vi.fn()}
        onDownload={vi.fn()}
      />,
    );

    // 运行中（active）默认展开：滚动框实时跟随最新事件；终态运行默认折叠。
    expect(screen.queryByText("系统已开始生成完整报告。")).not.toBeNull();
    expect(screen.queryByText("气候风险相关内容已经完成。")).not.toBeNull();
    expect(screen.queryByText("应对气候变化")).not.toBeNull();
    expect(screen.queryByText(/block_completed/)).toBeNull();
  });

  it("仅根据 action_required 展示可操作异常及返回准备概览入口", () => {
    const html = render(
      generation({
        status: "failed",
        summary: "当前版本未完成，已有版本不受影响。",
        events: [
          {
            sequence: 1,
            event_type: "failed",
            message: "报告输入在生成期间发生变化，请重新确认。",
            current_object: "报告基本信息",
            action_required: true,
            occurred_at: "2026-07-30T09:02:00Z",
          },
        ],
      }),
    );

    expect(html).toContain("需要你处理");
    expect(html).toContain("报告输入在生成期间发生变化");
    expect(html).toContain("相关内容：");
    expect(html).toContain("报告基本信息");
    // 准备概览页已废除:异常修复入口指向分步流(默认首步,由 entryHref 注入末步)。
    expect(html).toContain('href="/intake/info"');
  });

  it("成功后只展示 Word 和 审阅版报告，不暴露内部审计包", () => {
    const html = render(
      generation({
        status: "succeeded",
        completed_block_count: 8,
        result_report_state_seq: 9,
        artifacts: [
          {
            artifact_id: "00000000-0000-4000-8000-000000000011",
            kind: "word",
            filename: "示例企业 ESG 报告.docx",
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
      }),
    );

    expect(html).toContain("Word 报告");
    expect(html).toContain("示例企业 ESG 报告.docx");
    expect(html).toContain("审阅版报告");
    expect(html).not.toContain("内部审计包.json");
    expect(html).not.toContain("internal_audit");
    expect(html).toContain("阅读并修订报告正文");
    expect(html).toContain('href="/reports/document"');
    expect(html).toContain('aria-valuenow="100"');
    // 每个交付物卡片携带文档图标：完成后交付物要一眼可见地突出。
    expect((html.match(/<svg aria-hidden/g) ?? []).length).toBe(2);
  });

  it("成功且有交付物：交付区升到页首，先于当前进度", () => {
    const html = render(
      generation({
        status: "succeeded",
        completed_block_count: 8,
        result_report_state_seq: 9,
        artifacts: [
          {
            artifact_id: "00000000-0000-4000-8000-000000000011",
            kind: "word",
            filename: "示例企业 ESG 报告.docx",
            media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            download_href: `/api/reports/${reportId}/generations/${runId}/artifacts/00000000-0000-4000-8000-000000000011/download`,
          },
        ],
      }),
    );
    const deliveryIndex = html.indexOf("下载交付物");
    const progressIndex = html.indexOf("当前进度");
    expect(deliveryIndex).toBeGreaterThan(-1);
    expect(progressIndex).toBeGreaterThan(-1);
    expect(deliveryIndex).toBeLessThan(progressIndex);
    // 页标题出自事实源常量（REPORT_GENERATION_PAGE_LABEL），不在视图里双写。
    expect(html).toContain("报告生成与交付");
    // 进入页首的交付区携带一次性进入动画类。
    expect(html).toContain("gs-delivery-enter");
  });

  it("成功但零交付物：维持原序，「需要你处理」仍在交付区之前", () => {
    const html = render(
      generation({
        status: "succeeded",
        completed_block_count: 8,
        result_report_state_seq: 9,
        artifacts: [],
        events: [
          {
            sequence: 1,
            event_type: "export_blocked",
            message: "存在待完善事项，本次未生成可下载交付物。",
            current_object: null,
            action_required: true,
            occurred_at: "2026-07-30T09:05:00Z",
          },
        ],
      }),
    );
    const actionIndex = html.indexOf("需要你处理");
    const deliveryIndex = html.indexOf("下载交付物");
    expect(actionIndex).toBeGreaterThan(-1);
    expect(deliveryIndex).toBeGreaterThan(actionIndex);
    expect(html).not.toContain("gs-delivery-enter");
  });

    it("导出闸阻断（成功但零交付物+待办事件）时引导处理而非刷新重试", () => {
    const blocked = render(
      generation({
        status: "succeeded",
        completed_block_count: 8,
        result_report_state_seq: 9,
        artifacts: [],
        events: [
          {
            sequence: 1,
            event_type: "export_blocked",
            message: "报告内容已生成并保存，但存在 2 项待完善事项，本次未生成可下载的 Word 交付物。",
            current_object: null,
            action_required: true,
            occurred_at: "2026-07-30T09:10:00Z",
          },
        ],
      }),
    );
    expect(blocked).toContain("需要你处理");
    expect(blocked).toContain("本次未生成可下载交付物");
    expect(blocked).not.toContain("请稍后刷新重试");

    const pendingArtifacts = render(
      generation({
        status: "succeeded",
        completed_block_count: 8,
        result_report_state_seq: 9,
        artifacts: [],
        events: [],
      }),
    );
    expect(pendingArtifacts).toContain("交付物尚未就绪，请稍后刷新重试");
  });

  it("updateAvailable 时交付区提示输入已变化并给出更新入口", () => {
    const succeeded = generation({
      status: "succeeded",
      completed_block_count: 8,
      result_report_state_seq: 9,
      artifacts: [],
    });
    const withUpdate = renderToStaticMarkup(
      <ReportGenerationView
        generation={succeeded}
        refreshing={false}
        error={null}
        downloadingArtifactId={null}
        updateAvailable
        onRefresh={vi.fn()}
        onDownload={vi.fn()}
      />,
    );
    expect(withUpdate).toContain("资料或填写内容已更新");
    expect(withUpdate).toContain("更新报告");

    const withoutUpdate = render(succeeded);
    expect(withoutUpdate).not.toContain("资料或填写内容已更新");
  });

  it("进度投影对异常计数做显示层边界收敛", () => {
    expect(
      reportGenerationProgress(
        generation({ completed_block_count: 20, total_block_count: 8 }),
      ),
    ).toBe(100);
    expect(
      reportGenerationProgress(
        generation({ completed_block_count: 0, total_block_count: 8 }),
      ),
    ).toBe(0);
  });
});
