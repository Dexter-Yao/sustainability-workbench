// ABOUTME: 双重重要性评分表上传错误的用户可读投影，供评分页以内联消息说明修复动作。
// ABOUTME: 业务校验仍由后端拥有；本模块只将已返回的明确失败原因组织为稳定、可操作的界面文案。

export interface AssessmentUploadMessage {
  title: string;
  detail: string;
  canDownloadTemplate: boolean;
}

function labelsAfter(prefix: string, source: string): string[] {
  const match = source.match(new RegExp(`${prefix}：(.+?)(?:；|$)`));
  return match?.[1]
    .split("、")
    .map((label) => label.trim())
    .filter(Boolean) ?? [];
}

function quoteLabels(labels: string[]): string {
  return labels.map((label) => `“${label}”`).join("、");
}

function sourceMessage(error: unknown): string {
  return error instanceof Error ? error.message : "";
}

/** 将评分导入失败转换为用户可执行的更正提示。 */
export function assessmentUploadMessage(error: unknown): AssessmentUploadMessage {
  const source = sourceMessage(error);
  const unmatched = labelsAfter("评分表包含非官方议题名称", source);
  const missing = labelsAfter("评分表缺少适用议题", source);

  if (unmatched.length) {
    const detail = [
      `${quoteLabels(unmatched)}不是当前配置下的官方议题名称`,
      missing.length ? `本次评分还缺少${quoteLabels(missing)}` : "",
    ].filter(Boolean).join("；");
    return {
      title: "发现未匹配的议题名称",
      detail: `${detail}。请更正名称，或下载当前评分模板后重新填写。`,
      canDownloadTemplate: true,
    };
  }

  if (source.includes("评分表需为 .xlsx 文件")) {
    return {
      title: "文件格式不支持",
      detail: "请上传 .xlsx 格式的评分表；如当前文件格式不确定，请下载当前评分模板后重新填写。",
      canDownloadTemplate: true,
    };
  }

  if (source.includes("文件过大")) {
    return {
      title: "评分表文件过大",
      detail: `${source.replace(/^评分表解析失败：/, "")}。请删除无关工作表或图片后重试。`,
      canDownloadTemplate: false,
    };
  }

  if (source.includes("评分表包含不符合评分尺度的数值")) {
    return {
      title: "评分值不符合要求",
      detail: `${source.replace(/^评分表解析失败：/, "")}。请按当前评分尺度更正后重新上传。`,
      canDownloadTemplate: true,
    };
  }

  if (source.includes("File is not a zip file") || source.includes("BadZipFile")) {
    return {
      title: "无法读取评分表",
      detail: "请确认上传的是未损坏的 .xlsx 文件；如仍无法读取，请下载当前评分模板后重新填写。",
      canDownloadTemplate: true,
    };
  }

  if (source) {
    return {
      title: "评分表上传失败",
      detail: source.replace(/^评分表解析失败：/, ""),
      canDownloadTemplate: false,
    };
  }

  return {
    title: "评分表上传失败",
    detail: "请检查网络连接后重试；如文件格式不确定，可改为在线填写评分。",
    canDownloadTemplate: false,
  };
}
