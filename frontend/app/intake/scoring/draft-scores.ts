// ABOUTME: 重要性评分在线草稿过滤纯逻辑：自动保存只提交两维都已填且解析通过的行。
// ABOUTME: 独立于 page.tsx 之外，避免 Next.js 对 page 文件仅允许特定命名导出的类型约束。
import { parseMaterialityScore } from "@/lib/materiality-score";
import type { AssessmentInputResponse } from "@/lib/report-api.generated";

export type ScoreDraft = Record<string, { financial: string; impact: string }>;

/**
 * 自动保存草稿只提交两维都已填且解析通过的行；财务/影响任一为空或非法即从草稿中排除，
 * 不因单行未填而阻塞其余已完成行的自动保存（"保存全部"仍走完整覆盖校验）。
 */
export function draftScores(
  input: Pick<AssessmentInputResponse, "topics" | "score_scale"> | null,
  draft: ScoreDraft,
): { assessmentTopicId: string; financialScore: number; impactScore: number }[] {
  if (!input) return [];
  const scores: { assessmentTopicId: string; financialScore: number; impactScore: number }[] = [];
  for (const topic of input.topics) {
    const value = draft[topic.assessmentTopicId];
    const financialScore = parseMaterialityScore(value?.financial.trim() ?? "", input.score_scale);
    const impactScore = parseMaterialityScore(value?.impact.trim() ?? "", input.score_scale);
    if (financialScore === null || impactScore === null) continue;
    scores.push({ assessmentTopicId: topic.assessmentTopicId, financialScore, impactScore });
  }
  return scores;
}
