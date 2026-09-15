// ABOUTME: 前端标题编辑的唯一派生边界，与后端共用同一指纹语义。
// ABOUTME: 稳定 title 服务导航；正文只通过 displayTitle 或 titleContent 投影用户可见标题。
import type { Inline, Report, Section, SectionDisplayTitle } from "./schema";

function findSection(sections: Section[], key: string): Section | null {
  for (const section of sections) {
    if (section.key === key) return section;
    const child = findSection(section.children ?? [], key);
    if (child) return child;
  }
  return null;
}

function inlineText(content: Inline[] | null | undefined, report: Report): string {
  return (content ?? []).map((inline) => {
    if (inline.kind === "text") return inline.text ?? "";
    if (inline.kind !== "ref" || !inline.ref) return "";
    if (inline.ref.startsWith("fields.") && inline.ref.endsWith(".value")) {
      const key = inline.ref.slice("fields.".length, -".value".length);
      return String(report.fields[key]?.value ?? inline.fallback ?? "");
    }
    return inline.fallback ?? "";
  }).join("").trim();
}

export function resolvedDisplayTitle(section: Section, report: Report): string {
  return section.displayTitle?.text ?? (inlineText(section.titleContent, report) || section.title);
}

/**
 * 按 key 取该章节当前显示的标题；章节不存在时返回 null。
 *
 * 「保留当前标题」需要以现值重新盖指纹，而章节树遍历归本文件所有——
 * 调用方不应各自再写一遍递归查找。
 */
export function resolvedDisplayTitleByKey(report: Report, sectionKey: string): string | null {
  const section = findSection(report.sections, sectionKey);
  return section ? resolvedDisplayTitle(section, report) : null;
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, entry]) => entry !== undefined && entry !== null)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonical(entry)]),
    );
  }
  return value;
}

async function sha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(canonical(value)));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function titleInputFingerprint(section: Section, report: Report): Promise<string | null> {
  if (section.reportModuleId) return moduleFingerprint(section, report);
  if (!section.titleGeneration) return null;
  const block = section.blocks.find((candidate) => candidate.id === section.titleGeneration?.sourceBlockId);
  return block ? sha256(block.content ?? []) : null;
}

async function moduleFingerprint(section: Section, report: Report): Promise<string> {
  const payload = [];
  for (const h2 of section.children ?? []) {
    const h4 = [];
    for (const h3 of h2.children ?? []) {
      for (const child of h3.children ?? []) {
        if (child.headingLevel !== 4) continue;
        h4.push({
          title: resolvedDisplayTitle(child, report),
          sourceFingerprint: await titleInputFingerprint(child, report),
        });
      }
    }
    payload.push({ reportSectionId: h2.reportSectionId, title: h2.title, h4 });
  }
  return sha256(payload);
}

export async function updateSectionDisplayTitle(
  report: Report,
  sectionKey: string,
  text: string,
): Promise<Report> {
  const section = findSection(report.sections, sectionKey);
  const normalized = text.trim();
  if (!section || !normalized || (!section.reportModuleId && !section.titleGeneration)) return report;
  const inputFingerprint = await titleInputFingerprint(section, report);
  if (!inputFingerprint) return report;
  const displayTitle: SectionDisplayTitle = { text: normalized, origin: "user", inputFingerprint };
  const replace = (sections: Section[]): Section[] => sections.map((candidate) => ({
    ...candidate,
    displayTitle: candidate.key === sectionKey ? displayTitle : candidate.displayTitle,
    children: candidate.children ? replace(candidate.children) : candidate.children,
  }));
  return { ...report, sections: replace(report.sections) };
}

export function applyStoredSectionTitles(
  report: Report,
  titles: Record<string, SectionDisplayTitle>,
): Report {
  const replace = (sections: Section[]): Section[] => sections.map((section) => ({
    ...section,
    displayTitle: titles[section.key] ?? section.displayTitle,
    children: section.children ? replace(section.children) : section.children,
  }));
  return { ...report, sections: replace(report.sections) };
}
