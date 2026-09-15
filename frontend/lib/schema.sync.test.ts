// ABOUTME: 防漂移测试——lib/schema.ts 必须是 report.schema.json 的最新生成产物（改后端模型后须重跑 gen:schema）。
import { readFileSync } from "node:fs";

import { compileFromFile } from "json-schema-to-typescript";
import { expect, it } from "vitest";

const BANNER = [
  "// ABOUTME: 前端 schema 类型——由后端 Pydantic Report 模型经 report.schema.json 自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");
const STORED_STATE_BANNER = [
  "// ABOUTME: 报告状态快照类型——由后端 StoredReportStateV4 严格领域合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");
const SECTION_GENERATION_BANNER = [
  "// ABOUTME: 整节生成 API 类型——由后端 SectionGenerationResponse 严格输出合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");
const REPORT_API_BANNER = [
  "// ABOUTME: 报告核心 API 类型——由后端报告导航、持久化与状态驱动响应合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");
const MATERIAL_WORKSPACE_BANNER = [
  "// ABOUTME: 资料工作区 API 类型——由后端 Pydantic 公共投影合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.material.intake.schema_export，前端 npm run gen:schema。",
].join("\n");

it("schema.ts 与 report.schema.json 同步（防漂移）", async () => {
  const committed = readFileSync("lib/schema.ts", "utf-8");
  const regenerated = await compileFromFile("lib/report.schema.json", { bannerComment: BANNER });
  expect(committed).toBe(regenerated);
});

it("StoredReportStateV4 生成类型与后端 schema 同步", async () => {
  const committed = readFileSync("lib/stored-report-state.generated.ts", "utf-8");
  const regenerated = await compileFromFile("lib/stored-report-state.schema.json", {
    bannerComment: STORED_STATE_BANNER,
  });
  expect(committed).toBe(regenerated);
});

it("SectionGenerationResponse 生成类型与后端 schema 同步", async () => {
  const committed = readFileSync("lib/section-generation.generated.ts", "utf-8");
  const regenerated = await compileFromFile("lib/section-generation.schema.json", {
    bannerComment: SECTION_GENERATION_BANNER,
  });
  expect(committed).toBe(regenerated);
});

it("报告核心 API 生成类型与后端 schema 同步", async () => {
  const committed = readFileSync("lib/report-api.generated.ts", "utf-8");
  const regenerated = await compileFromFile("lib/report-api.schema.json", {
    bannerComment: REPORT_API_BANNER,
  });
  expect(committed).toBe(regenerated);
});

it("资料工作区 API 生成类型与后端 schema 同步", async () => {
  const committed = readFileSync("lib/material-workspace.generated.ts", "utf-8");
  const regenerated = await compileFromFile("lib/material-workspace.schema.json", {
    bannerComment: MATERIAL_WORKSPACE_BANNER,
  });
  expect(committed).toBe(regenerated);
});
