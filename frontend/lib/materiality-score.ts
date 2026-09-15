// ABOUTME: 双重重要性评分输入的前端投影；数值尺度只读取 Report.assessmentScoreScale。
// ABOUTME: 本模块不自定义业务范围，供在线评分表单与其单测共用。
import type { Report } from "./schema";
import { interpolate, type Dictionary } from "./i18n/dictionary";

export type AssessmentScoreScale = NonNullable<Report["assessmentScoreScale"]>;

function decimalPlaces(step: number): number {
  const fraction = String(step).split(".")[1];
  return fraction?.length ?? 0;
}

function scoreText(value: number): string {
  return String(value);
}

export function materialityScoreStep(scale: AssessmentScoreScale): number {
  return scale.multipleOf;
}

export function parseMaterialityScore(value: string, scale: AssessmentScoreScale): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const score = Number(trimmed);
  if (!Number.isFinite(score) || score <= scale.minimumExclusive || score > scale.maximum) return null;
  const units = score / scale.multipleOf;
  return Math.abs(units - Math.round(units)) < 1e-9 ? score : null;
}

/** 评分范围提示；措辞按界面语言，数值口径仍由包的 AssessmentScoreScale 决定。 */
export function materialityScoreGuidance(scale: AssessmentScoreScale, t: Dictionary): string {
  const places = decimalPlaces(scale.multipleOf);
  const precision = places === 0
    ? t.scoring.scorePrecisionInteger
    : interpolate(t.scoring.scorePrecisionDecimals, { places });
  return interpolate(t.scoring.scoreRange, {
    min: scoreText(scale.minimumExclusive),
    max: scoreText(scale.maximum),
    precision,
  });
}
