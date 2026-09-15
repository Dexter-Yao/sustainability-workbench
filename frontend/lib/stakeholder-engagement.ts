// ABOUTME: 利益相关方沟通前端目录与快照解析边界，数据由后端 YAML 确定性导出。
// ABOUTME: 编辑器只读稳定 ID 和显示标签；Profile 是唯一可写真相，不解析表格中文单元格。
import rawCatalog from "../public/stakeholder-engagement.json";

import type {
  CustomEngagementMethod,
  EngagementMethodKind,
  StakeholderEngagementEntry,
  StakeholderEngagementProfile,
  StakeholderType,
} from "./schema";

export interface StakeholderCatalogItem {
  id: StakeholderType;
  label: string;
  order: number;
  defaultMethodIds: string[];
}

export interface EngagementMethodCatalogItem {
  id: string;
  label: string;
  kind: EngagementMethodKind;
  allowedStakeholderTypes: StakeholderType[];
}

export interface StakeholderTopicCatalogItem {
  id: string;
  label: string;
  dimension: "环境" | "社会" | "治理";
  order: number;
}

export const STAKEHOLDER_CATALOG = rawCatalog as {
  stakeholders: StakeholderCatalogItem[];
  methods: EngagementMethodCatalogItem[];
  topics: StakeholderTopicCatalogItem[];
};

const STAKEHOLDER_TYPES = STAKEHOLDER_CATALOG.stakeholders.map((item) => item.id);
const TOPIC_IDS = new Set(STAKEHOLDER_CATALOG.topics.map((item) => item.id));
const METHOD_BY_ID = new Map(STAKEHOLDER_CATALOG.methods.map((item) => [item.id, item]));
const TOPIC_ORDER = new Map(STAKEHOLDER_CATALOG.topics.map((item, index) => [item.id, index]));
const METHOD_ORDER = new Map(STAKEHOLDER_CATALOG.methods.map((item, index) => [item.id, index]));
const METHOD_KIND_ORDER: EngagementMethodKind[] = [
  "communication_channel",
  "participation_mechanism",
  "collaboration_activity",
];
const METHOD_KINDS = new Set<EngagementMethodKind>([
  "communication_channel",
  "participation_mechanism",
  "collaboration_activity",
]);

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : null;
}

function uniqueStrings(value: unknown, allowed?: Set<string>): string[] | undefined {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) return undefined;
  const strings = value as string[];
  if (strings.length !== new Set(strings).size) return undefined;
  if (allowed && strings.some((item) => !allowed.has(item))) return undefined;
  return strings;
}

/** 外部/localStorage 快照 → typed Profile；任一引用不合法即拒绝整个 Profile。 */
export function parseStakeholderEngagementProfile(value: unknown): StakeholderEngagementProfile | undefined {
  const record = asRecord(value);
  if (!record) return undefined;
  const scopeAssessmentTopicIds = uniqueStrings(record.scopeAssessmentTopicIds, TOPIC_IDS);
  if (!scopeAssessmentTopicIds || !Array.isArray(record.entries) || record.entries.length !== STAKEHOLDER_TYPES.length) return undefined;

  const entries: StakeholderEngagementProfile["entries"] = [];
  for (const [index, rawEntry] of record.entries.entries()) {
    const entry = asRecord(rawEntry);
    const stakeholderType = STAKEHOLDER_TYPES[index];
    if (!entry || entry.stakeholderType !== stakeholderType) return undefined;
    const assessmentTopicIds = uniqueStrings(entry.assessmentTopicIds, TOPIC_IDS);
    const methodIds = uniqueStrings(entry.methodIds);
    if (!assessmentTopicIds || !methodIds) return undefined;
    if (methodIds.some((methodId) => !METHOD_BY_ID.get(methodId)?.allowedStakeholderTypes.includes(stakeholderType))) return undefined;
    if (!Array.isArray(entry.customMethods)) return undefined;
    const customMethods: StakeholderEngagementProfile["entries"][number]["customMethods"] = [];
    const customKeys = new Set<string>();
    for (const rawMethod of entry.customMethods) {
      const method = asRecord(rawMethod);
      if (!method || typeof method.kind !== "string" || !METHOD_KINDS.has(method.kind as EngagementMethodKind) || typeof method.label !== "string") return undefined;
      const label = method.label.trim();
      const key = `${method.kind}:${label}`;
      if (!label || customKeys.has(key)) return undefined;
      customKeys.add(key);
      customMethods.push({ kind: method.kind as EngagementMethodKind, label });
    }
    entries.push({ stakeholderType, assessmentTopicIds, methodIds, customMethods });
  }
  return { scopeAssessmentTopicIds, entries };
}

export function topicLabel(assessmentTopicId: string): string {
  return STAKEHOLDER_CATALOG.topics.find((topic) => topic.id === assessmentTopicId)?.label ?? assessmentTopicId;
}

export function methodLabel(methodId: string): string {
  return METHOD_BY_ID.get(methodId)?.label ?? methodId;
}

export function orderedStakeholderTopicLabels(assessmentTopicIds: string[]): string[] {
  return [...assessmentTopicIds]
    .sort((left, right) => (TOPIC_ORDER.get(left) ?? Number.MAX_SAFE_INTEGER) - (TOPIC_ORDER.get(right) ?? Number.MAX_SAFE_INTEGER))
    .map(topicLabel);
}

export function orderedStakeholderMethodLabels(entry: StakeholderEngagementEntry): string[] {
  const labels: string[] = [];
  for (const kind of METHOD_KIND_ORDER) {
    labels.push(
      ...entry.methodIds
        .filter((methodId) => METHOD_BY_ID.get(methodId)?.kind === kind)
        .sort((left, right) => (METHOD_ORDER.get(left) ?? Number.MAX_SAFE_INTEGER) - (METHOD_ORDER.get(right) ?? Number.MAX_SAFE_INTEGER))
        .map(methodLabel),
      ...entry.customMethods.filter((method) => method.kind === kind).map((method) => method.label),
    );
  }
  return [...new Set(labels)];
}

function updateEntry(
  profile: StakeholderEngagementProfile,
  stakeholderType: StakeholderType,
  updater: (entry: StakeholderEngagementEntry) => StakeholderEngagementEntry,
): StakeholderEngagementProfile {
  return {
    ...profile,
    entries: profile.entries.map((entry) => entry.stakeholderType === stakeholderType ? updater(entry) : entry),
  };
}

export function toggleStakeholderTopic(
  profile: StakeholderEngagementProfile,
  stakeholderType: StakeholderType,
  assessmentTopicId: string,
): StakeholderEngagementProfile {
  if (!profile.scopeAssessmentTopicIds.includes(assessmentTopicId)) return profile;
  return updateEntry(profile, stakeholderType, (entry) => ({
    ...entry,
    assessmentTopicIds: entry.assessmentTopicIds.includes(assessmentTopicId)
      ? entry.assessmentTopicIds.filter((id) => id !== assessmentTopicId)
      : [...entry.assessmentTopicIds, assessmentTopicId],
  }));
}

export function toggleStakeholderMethod(
  profile: StakeholderEngagementProfile,
  stakeholderType: StakeholderType,
  methodId: string,
): StakeholderEngagementProfile {
  const method = METHOD_BY_ID.get(methodId);
  if (!method?.allowedStakeholderTypes.includes(stakeholderType)) return profile;
  return updateEntry(profile, stakeholderType, (entry) => ({
    ...entry,
    methodIds: entry.methodIds.includes(methodId)
      ? entry.methodIds.filter((id) => id !== methodId)
      : [...entry.methodIds, methodId],
  }));
}

export function addCustomStakeholderMethod(
  profile: StakeholderEngagementProfile,
  stakeholderType: StakeholderType,
  method: CustomEngagementMethod,
): StakeholderEngagementProfile {
  const label = method.label.trim();
  if (!label) return profile;
  return updateEntry(profile, stakeholderType, (entry) => {
    if (entry.customMethods.some((item) => item.kind === method.kind && item.label === label)) return entry;
    return { ...entry, customMethods: [...entry.customMethods, { ...method, label }] };
  });
}

export function removeCustomStakeholderMethod(
  profile: StakeholderEngagementProfile,
  stakeholderType: StakeholderType,
  method: CustomEngagementMethod,
): StakeholderEngagementProfile {
  return updateEntry(profile, stakeholderType, (entry) => ({
    ...entry,
    customMethods: entry.customMethods.filter((item) => !(item.kind === method.kind && item.label === method.label)),
  }));
}

export function missingStakeholderTopicIds(profile: StakeholderEngagementProfile): string[] {
  const covered = new Set(profile.entries.flatMap((entry) => entry.assessmentTopicIds));
  return profile.scopeAssessmentTopicIds.filter((assessmentTopicId) => !covered.has(assessmentTopicId));
}
