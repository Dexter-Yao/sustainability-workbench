// ABOUTME: 报告配置页定位锚点，供诊断 issue.path 与配置控件稳定互跳。
// ABOUTME: 只做路径到 DOM id 的确定性转换，不承载业务逻辑。
export function configAnchorId(path: string): string {
  return `config-${path.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}
