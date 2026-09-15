// ABOUTME: 溯源投影稳定 code 到用户可见文案的唯一出口：依据、资料处置、生成结果、省略原因、守卫结论与问题类别。
// ABOUTME: 文案随界面语言（lib/i18n 的 provenance 组），判定始终依据 code；界面不得直接渲染 code。
// ABOUTME(en): Sole projection from provenance codes to user-visible copy; the UI never renders a raw code.

import type {
  EvidenceLevel,
  EvidenceSelectorKind,
  GenerationOutcome,
  GuardrailIssueCode,
  GuardrailVerdict,
  MaterialDispositionCode,
  OmissionCode,
  ProvenanceBasis,
} from "./report-api.generated";
import type { Dictionary } from "./i18n/dictionary";

/**
 * 契约新增 code 时，字典缺条目会在 tsc 阶段报错——`Dictionary` 的形状由基准字典
 * 反推，而基准字典的键集合就是这里的 Record 键集合。
 */
export function basisLabel(code: ProvenanceBasis, t: Dictionary): string {
  return (t.provenance.basis as Record<ProvenanceBasis, string>)[code];
}

export function dispositionLabel(code: MaterialDispositionCode, t: Dictionary): string {
  return (t.provenance.disposition as Record<MaterialDispositionCode, string>)[code];
}

export function outcomeLabel(code: GenerationOutcome, t: Dictionary): string {
  return (t.provenance.outcome as Record<GenerationOutcome, string>)[code];
}

export function omissionLabel(code: OmissionCode, t: Dictionary): string {
  return (t.provenance.omission as Record<OmissionCode, string>)[code];
}

export function guardrailVerdictLabel(code: GuardrailVerdict, t: Dictionary): string {
  return (t.provenance.guardrailVerdict as Record<GuardrailVerdict, string>)[code];
}

export function guardrailIssueLabel(code: GuardrailIssueCode, t: Dictionary): string {
  return (t.provenance.guardrailIssue as Record<GuardrailIssueCode, string>)[code];
}

export function evidenceLevelLabel(code: EvidenceLevel, t: Dictionary): string {
  return (t.provenance.evidenceLevel as Record<EvidenceLevel, string>)[code];
}

export function selectorLabel(code: EvidenceSelectorKind, t: Dictionary): string {
  return (t.provenance.selector as Record<EvidenceSelectorKind, string>)[code];
}

export function traceUnavailableCopy(t: Dictionary): string {
  return t.provenance.traceUnavailable;
}
