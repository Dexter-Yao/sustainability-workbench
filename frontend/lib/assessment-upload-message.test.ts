// ABOUTME: 评分表上传失败信息的前端分类测试，确保用户获得可操作的修复提示。
// ABOUTME: 本测试不重复解析业务规则，只验证后端已判定的错误会被清晰投影到评分页。
import { describe, expect, it } from "vitest";

import { assessmentUploadMessage } from "./assessment-upload-message";

describe("assessmentUploadMessage", () => {
  it("将未匹配官方议题名称转为带修复动作的提示", () => {
    const message = assessmentUploadMessage(
      new Error("评分表解析失败：评分表包含非官方议题名称：利益相关方调查；评分表缺少适用议题：利益相关方沟通"),
    );

    expect(message).toEqual({
      title: "发现未匹配的议题名称",
      detail: "“利益相关方调查”不是当前配置下的官方议题名称；本次评分还缺少“利益相关方沟通”。请更正名称，或下载当前评分模板后重新填写。",
      canDownloadTemplate: true,
    });
  });

  it("保留评分尺度错误的具体原因", () => {
    const message = assessmentUploadMessage(
      new Error("评分表解析失败：评分表包含不符合评分尺度的数值：应对气候变化（评分必须按 0.1 的步长填写）"),
    );

    expect(message.title).toBe("评分值不符合要求");
    expect(message.detail).toContain("应对气候变化");
    expect(message.canDownloadTemplate).toBe(true);
  });

  it("对不可读文件给出不暴露内部错误的提示", () => {
    const message = assessmentUploadMessage(new Error("评分表解析失败：File is not a zip file"));

    expect(message).toEqual({
      title: "无法读取评分表",
      detail: "请确认上传的是未损坏的 .xlsx 文件；如仍无法读取，请下载当前评分模板后重新填写。",
      canDownloadTemplate: true,
    });
  });

  it("区分不支持的格式与文件大小限制", () => {
    expect(assessmentUploadMessage(new Error("评分表需为 .xlsx 文件"))).toMatchObject({
      title: "文件格式不支持",
      canDownloadTemplate: true,
    });
    expect(assessmentUploadMessage(new Error("文件过大（上限 20MB）"))).toMatchObject({
      title: "评分表文件过大",
      canDownloadTemplate: false,
    });
  });
});
