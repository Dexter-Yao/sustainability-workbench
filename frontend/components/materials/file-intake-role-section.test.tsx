// ABOUTME: 上传区按角色白名单分区上传文件的回归测试：投放的区声明角色，只判该角色的扩展名与大小。
// ABOUTME: 校验不支持的文件逐个具名拒绝、不跨区改投，不依赖浏览器 accept 属性兜底。

import { describe, expect, it } from "vitest";
import { zhHans } from "@/lib/i18n/zh-Hans";

import type { ReportFileIntake } from "@/lib/material-workspace-api";
import { partitionFilesForRole } from "./file-intake-role-section";

const policy: ReportFileIntake["policy"] = {
  max_files_per_report: 30,
  max_file_bytes: 10 * 1024 * 1024,
  max_pdf_pages: 40,
  description_min_chars: 10,
  description_max_chars: 140,
  asset_title_max_chars: 100,
  semantic_material_kinds: ["pdf", "docx", "xlsx"],
  layout_asset_kinds: ["png", "jpeg", "webp", "pdf"],
  semantic_material_extensions: [".pdf", ".docx", ".xlsx"],
  layout_asset_extensions: [".png", ".jpg", ".jpeg", ".webp", ".pdf"],
  topic_tags: [
    { id: "uncertain", label: "暂不确定", kind: "auxiliary" },
    { id: "comprehensive", label: "综合", kind: "auxiliary" },
    { id: "climate_change", label: "应对气候变化", kind: "report_section" },
  ],
};

describe("partitionFilesForRole", () => {
  it("报告资料区按语义资料白名单整批接受", () => {
    const result = partitionFilesForRole(
      [new File(["a"], "policy.pdf"), new File(["b"], "ledger.xlsx")],
      "semantic_material",
      policy,
      zhHans,
    );
    expect(result.accepted.map((file) => file.name)).toEqual(["policy.pdf", "ledger.xlsx"]);
    expect(result.rejected).toEqual([]);
  });

  it("逐个具名拒绝不支持的格式，不影响其余文件整批接受", () => {
    const result = partitionFilesForRole(
      [new File(["a"], "policy.pdf"), new File(["b"], "notes.txt")],
      "semantic_material",
      policy,
      zhHans,
    );
    expect(result.accepted.map((file) => file.name)).toEqual(["policy.pdf"]);
    expect(result.rejected).toEqual([
      { file: expect.objectContaining({ name: "notes.txt" }), reason: expect.stringContaining("不是「报告资料」支持的格式") },
    ]);
  });

  it("超过单文件大小上限时具名拒绝，不阻断同批其他文件", () => {
    const oversized = new File([new Uint8Array(policy.max_file_bytes + 1)], "large.pdf");
    const result = partitionFilesForRole(
      [new File(["a"], "policy.pdf"), oversized],
      "semantic_material",
      policy,
      zhHans,
    );
    expect(result.accepted.map((file) => file.name)).toEqual(["policy.pdf"]);
    expect(result.rejected).toEqual([
      { file: expect.objectContaining({ name: "large.pdf" }), reason: expect.stringContaining("上限") },
    ]);
  });

  it(".pdf 投入图片素材区按 layout_asset 白名单接受——角色由投放的区声明，不由扩展名推断", () => {
    const result = partitionFilesForRole(
      [new File(["a"], "certificate.pdf")],
      "layout_asset",
      policy,
      zhHans,
    );
    expect(result.accepted.map((file) => file.name)).toEqual(["certificate.pdf"]);
    expect(result.rejected).toEqual([]);
  });

  it(".png 投入报告资料区具名拒绝，不跨区改投", () => {
    const result = partitionFilesForRole(
      [new File(["a"], "certificate.png")],
      "semantic_material",
      policy,
      zhHans,
    );
    expect(result.accepted).toEqual([]);
    expect(result.rejected[0].reason).toBe("不是「报告资料」支持的格式（.pdf、.docx、.xlsx）。");
  });
});
