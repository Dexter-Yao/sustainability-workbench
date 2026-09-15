// ABOUTME: 轻量版报告级真实进度与客户交付路由，默认读取当前报告最新生成运行。
// ABOUTME: 交互、轮询和下载位于独立 Client Component，路由本身不持有运行状态。

import { ReportGenerationPage } from "@/components/reports/report-generation-page";

export default function GenerationPage() {
  return <ReportGenerationPage />;
}
