// ABOUTME: 由后端领域合同 JSON Schema 生成前端 TypeScript 类型。
// ABOUTME: Report 与 StoredReportStateV4 的运行时解析和静态类型保持同源。
import { writeFileSync } from "node:fs";
import { compileFromFile } from "json-schema-to-typescript";

const banner = [
  "// ABOUTME: 前端 schema 类型——由后端 Pydantic Report 模型经 report.schema.json 自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");

const ts = await compileFromFile("lib/report.schema.json", { bannerComment: banner });
writeFileSync("lib/schema.ts", ts);

const storedStateBanner = [
  "// ABOUTME: 报告状态快照类型——由后端 StoredReportStateV4 严格领域合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");
const storedStateTs = await compileFromFile("lib/stored-report-state.schema.json", {
  bannerComment: storedStateBanner,
});
writeFileSync("lib/stored-report-state.generated.ts", storedStateTs);

const sectionGenerationBanner = [
  "// ABOUTME: 整节生成 API 类型——由后端 SectionGenerationResponse 严格输出合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");
const sectionGenerationTs = await compileFromFile("lib/section-generation.schema.json", {
  bannerComment: sectionGenerationBanner,
});
writeFileSync("lib/section-generation.generated.ts", sectionGenerationTs);

const reportApiBanner = [
  "// ABOUTME: 报告核心 API 类型——由后端报告导航、持久化与状态驱动响应合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.contract.schema_export，前端 npm run gen:schema。",
].join("\n");
const reportApiTs = await compileFromFile("lib/report-api.schema.json", {
  bannerComment: reportApiBanner,
});
writeFileSync("lib/report-api.generated.ts", reportApiTs);


const materialBanner = [
  "// ABOUTME: 资料工作区 API 类型——由后端 Pydantic 公共投影合同自动生成，请勿手改。",
  "// ABOUTME: 重新生成：后端 python -m sustainability_desk.material.intake.schema_export，前端 npm run gen:schema。",
].join("\n");
const materialTs = await compileFromFile("lib/material-workspace.schema.json", {
  bannerComment: materialBanner,
});
writeFileSync("lib/material-workspace.generated.ts", materialTs);
console.log("已生成 Report、StoredReportStateV4、SectionGenerationResponse、报告核心 API 与资料工作区类型");
