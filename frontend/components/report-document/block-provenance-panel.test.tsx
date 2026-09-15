// ABOUTME: 溯源面板渲染测试：稳定 code 全部经文案表投影为中文，原始 code 与内部标识不出现在界面上。
// @vitest-environment happy-dom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { BlockProvenanceEntry, ReportBlockProvenanceProjection } from "@/lib/block-provenance-api";

import { BlockProvenancePanel } from "./block-provenance-panel";

const entry: BlockProvenanceEntry = {
  block_id: "climate.body",
  basis: ["validated_material", "quantitative_metric", "structured_input"],
  generation_outcome: "ready",
  material_disposition: "supported",
  sources: [{ material_name: "员工手册.docx", adopted_material_count: 2 }],
  intake_items: [{ question: "公司如何组织员工培训？", answered: true }],
  metrics: [{ metric_name: "员工总数", value: "1500", unit: "人" }],
  attention_note: false,
  generated_content: [{ kind: "text", text: "生成时的正文。" }],
  run: {
    stage_status: "succeeded",
    attempt_count: 2,
    guardrail: "accepted_after_retry",
    guardrail_issue_codes: ["placeholder_output"],
    evidence_selector_kind: "explicit",
    evidence_level: "block_facts",
    intake_fact_count: 1,
    metric_evidence_count: 1,
    prior_disclosure_count: 0,
  },
};

const projection: ReportBlockProvenanceProjection = {
  contract: "sustainability_desk.block_provenance.v1",
  report_id: "9ca1a5db-38f8-4748-9b5f-c021dcdf97b7",
  revision: 1,
  generated_report_state_seq: 7,
  generated_at: "2026-09-05T09:00:00Z",
  trace_availability: "available",
  blocks: [entry],
};

afterEach(cleanup);

describe("BlockProvenancePanel", () => {
  it("renders every fact as Chinese copy and never the raw code", () => {
    const { container } = render(
      <BlockProvenancePanel entry={entry} currentText="生成时的正文。" projection={projection} loading={false} error={null} />,
    );
    const html = container.innerHTML;
    expect(html).toContain("用户上传并经核对的资料");
    expect(html).toContain("资料直接支持本块");
    expect(html).toContain("员工手册.docx");
    expect(html).toContain("采用 2 段资料");
    expect(html).toContain("已作答");
    expect(html).toContain("员工总数：1500人");
    expect(html).toContain("经重试后通过在线守卫");
    expect(html).toContain("输出含占位表述");
    expect(html).toContain("与生成稿一致");
    for (const raw of ["validated_material", "accepted_after_retry", "placeholder_output", "block_facts", "9ca1a5db"]) {
      expect(html).not.toContain(raw);
    }
  });

  it("shows a character diff against the generated baseline once the prose is edited", () => {
    render(
      <BlockProvenancePanel entry={entry} currentText="生成后修订的正文。" projection={projection} loading={false} error={null} />,
    );
    expect(screen.getByText("与生成稿的差异")).toBeTruthy();
    expect(document.querySelector("ins")?.textContent).toBe("后修订");
    expect(document.querySelector("del")?.textContent).toBe("时");
  });

  it("states honestly when the run trace is unavailable", () => {
    render(
      <BlockProvenancePanel
        entry={{ ...entry, run: null }}
        currentText="生成时的正文。"
        projection={{ ...projection, trace_availability: "unavailable" }}
        loading={false}
        error={null}
      />,
    );
    expect(screen.getByText(/运行记录不可用/)).toBeTruthy();
  });

  it("guides the reader when nothing is selected", () => {
    render(<BlockProvenancePanel entry={null} currentText={null} projection={null} loading={false} error={null} />);
    expect(screen.getByText(/点击正文任一段/)).toBeTruthy();
  });
});
