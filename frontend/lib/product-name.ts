// ABOUTME: 用户可见产品名的唯一来源；改名只改这里，界面文案与页面标题据此派生。
// ABOUTME: 品牌名为 Sustainability Workbench；技术标识（包名、环境变量前缀、契约版本串）不从本常量派生。
export const PRODUCT_NAME = "Sustainability Workbench";

/** 页头紧凑标（窄屏）显示的短形。品牌定名后可改为缩写或字母标。 */
export const PRODUCT_MARK_COMPACT = "SW";

/** 用户下载的工作簿文件名。与后端 `contract/product_name.py` 的
 * `workbook_download_filename` 同一口径——两处分叉会让浏览器落盘名与响应头不符。 */
export function workbookDownloadFilename(documentLabel: string): string {
  return `${documentLabel}.xlsx`;
}
