// ABOUTME: 报告基础设置：收集全局共用信息，只需填写一次。
// ABOUTME: 章节专属输入在对应章节步骤中收集；本页页头自渲染进度与待完成 chip（design.md §8.2）。
"use client";

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { CoachMarks } from "@/components/onboarding/CoachMarks";
import { FieldGroup, fieldControlBorder, FieldRow, requiredStarStyle } from "@/components/ui/FieldRow";
import { Hint } from "@/components/ui/Hint";
import { LoadingState } from "@/components/ui/LoadingState";
import { TypedFieldInput } from "@/components/forms/TypedFieldInput";
import { OptionalSupplement } from "@/components/intake/optional-supplement";
import { WorkbookChannel, type WorkbookChannelNote } from "@/components/intake/workbook-channel";
import {
  downloadReportBasicsTemplate,
  importReportBasicsWorkbook,
} from "@/lib/api";
import { useApp } from "@/lib/app-context";
import { activeReportScope } from "@/lib/active-report-scope";
import { intakeStepKey } from "@/lib/intake-steps";
import { stepLabel } from "@/lib/i18n/intake-step-copy";
import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { configAnchorId } from "@/lib/config-anchors";
import { isVisible } from "@/lib/conditions";
import { industryCatalogFor } from "@/lib/industry-catalog-hsic";
import { isFieldValueAllowed, isPhoneInput } from "@/lib/input-validation";
import { inputGuidanceAt } from "@/lib/report-input-guidance";
import { fixedStandardName, mainlandStandardNames } from "@/lib/disclosure-basis";
import { INTAKE_INFO_SECTIONS, visibleIntakeInfoSections } from "@/lib/intake-info-sections";
import type { Field, Report } from "@/lib/schema";
import { updateIntakeItem } from "@/lib/report-section-flow";
import {
  fetchReportPreparation,
  type ReportPreparation,
} from "@/lib/material-workspace-api";

const sectionStyle: CSSProperties = {
  borderTop: "1px solid var(--border)",
  padding: "26px 0",
  scrollMarginTop: "calc(var(--topbar-height) + 16px)",
};

const gridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
  gap: 14,
};

const inputStyle: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  borderRadius: "var(--radius-control)",
  background: "var(--background)",
  color: "var(--foreground)",
  fontSize: "var(--text-body-size)",
  padding: "8px 10px",
};

const textareaStyle: CSSProperties = {
  ...inputStyle,
  minHeight: 96,
  resize: "vertical",
  lineHeight: 1.7,
};

/** 区块必填/选填义务一律自唯一事实源派生（与左栏二级条目同口径），不得就地双写。 */
function infoSectionObligation(sectionId: string): "required" | "optional" | undefined {
  return INTAKE_INFO_SECTIONS.find((section) => section.id === sectionId)?.obligation;
}

function SectionTitle({
  title,
  meta,
  hint,
  obligation,
}: {
  title: string;
  meta?: ReactNode;
  hint?: string;
  /** 区块必填/选填标记（事实源 lib/intake-info-sections）；与左栏二级条目同一口径。 */
  obligation?: "required" | "optional";
}) {
  const t = useT();
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: "var(--text-subsection-size)", fontWeight: 600, color: "var(--foreground)" }}>{title}</h2>
      {obligation ? (
        <span
          style={{
            fontSize: "var(--text-overline-size)",
            color: obligation === "required" ? "var(--destructive)" : "var(--muted-foreground)",
          }}
        >
          {obligation === "required" ? t.shell.obligationRequired : t.shell.obligationOptional}
        </span>
      ) : null}
      {hint ? <Hint content={hint} /> : null}
      {meta ? (
        <span style={{ marginLeft: "auto", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
          {meta}
        </span>
      ) : null}
    </div>
  );
}

function FieldInput({ field }: { field: Field }) {
  const t = useT();
  const { report, setFieldValue } = useApp();
  const value = field.value == null ? "" : String(field.value);
  const inputPath = `fields.${field.key}.value`;
  const filled = value.trim() !== "";
  return (
    <FieldRow
      label={field.label}
      required={!!field.required}
      inlineHint={inputGuidanceAt(report, inputPath)?.helpText ?? undefined}
      hint={inputGuidanceAt(report, inputPath)?.termExplanation ?? undefined}
      htmlFor={configAnchorId(inputPath)}
    >
      {field.type === "enum" && field.options ? (
        <select
          id={configAnchorId(inputPath)}
          data-field={field.key}
          value={value}
          onChange={(event) => setFieldValue(field.key, event.target.value)}
          className="gs-input"
          style={{ ...inputStyle, border: fieldControlBorder(filled) }}
        >
          <option value="">{t.reportConfig.notSelected}</option>
          {field.options.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      ) : (
        <TypedFieldInput
          field={field}
          id={configAnchorId(inputPath)}
          value={value}
          onChange={(next) => setFieldValue(field.key, next)}
          className="gs-input"
          style={{ ...inputStyle, border: fieldControlBorder(filled) }}
          dataField={field.key}
        />
      )}
    </FieldRow>
  );
}

function field(report: Report, key: string): Field | null {
  return report.fields[key] ?? null;
}

function FieldsGroup({ keys }: { keys: string[] }) {
  const { report } = useApp();
  // 组内有任一字段带常驻说明时，其余字段留出等高空位，使同排输入框对齐。
  const hasGuidance = keys.some(
    (key) => field(report, key) && inputGuidanceAt(report, `fields.${key}.value`)?.helpText,
  );
  return (
    <FieldGroup reserveGuidanceSpace={!!hasGuidance} style={gridStyle}>
      {keys.map((key) => {
        const item = field(report, key);
        return item ? <FieldInput key={key} field={item} /> : null;
      })}
    </FieldGroup>
  );
}

/** 公司简介在第一个输入停靠点收集；它不是生成门禁，缺失时由生成侧按缺资料分支处理。 */
function CompanyProfileSection() {
  const { report, setReport } = useApp();
  const item = (report.intakeItems ?? []).find((entry) => entry.key === "company_profile");
  if (!item) return null;
  const answer = typeof item.answer === "string" ? item.answer : "";
  // 题干即「公司简介」（合同 SSOT），与节标题同义，故不再另设 SectionTitle；占位示例已删除。
  return (
    <section id="section-company-profile" style={sectionStyle}>
      <FieldRow
        label={item.prompt}
        required={!!item.requiredBefore}
        inlineHint={item.hint ?? undefined}
        hint={item.termExplanation ?? undefined}
        htmlFor="company-profile-textarea"
        counter={{ count: answer.length, max: item.maxChars ?? 800, min: item.minChars ?? undefined }}
      >
        <textarea
          id="company-profile-textarea"
          data-intake-item="company_profile"
          value={answer}
          onChange={(event) =>
            setReport((current) =>
              updateIntakeItem(current, item.key, { answer: event.target.value, supplement: item.supplement ?? null }),
            )
          }
          maxLength={item.maxChars ?? undefined}
          className="gs-input"
          style={{ ...textareaStyle, border: fieldControlBorder(answer.trim() !== "") }}
        />
      </FieldRow>
    </section>
  );
}

/** 治理与可持续管理：前四章正文的直填输入（可选，不阻断首次生成）。
 * 入口收敛在基本信息步骤，工作台不设前四章停靠点（design.md §3.1）。 */
function GovernanceInputsSection() {
  const t = useT();
  const { report, setReport } = useApp();
  const keys = [
    "articles",
    "sustainability_governance_structure",
    "sustainability_governance_duties",
  ];
  const items = keys
    .map((key) => (report.intakeItems ?? []).find((entry) => entry.key === key))
    .filter((item): item is NonNullable<typeof item> => item != null);
  if (items.length === 0) return null;
  return (
    <section style={sectionStyle}>
      <SectionTitle title={t.reportConfig.governanceHeading} />
      <div style={{ display: "grid", gap: 16 }}>
        {items.map((item) => (
          <FieldRow key={item.key} label={item.prompt} inlineHint={item.hint ?? undefined} hint={item.termExplanation ?? undefined} htmlFor={`intake-${item.key}`}>
            <textarea
              id={`intake-${item.key}`}
              data-intake-item={item.key}
              value={typeof item.answer === "string" ? item.answer : ""}
              onChange={(event) =>
                setReport((current) =>
                  updateIntakeItem(current, item.key, { answer: event.target.value, supplement: item.supplement ?? null }),
                )
              }
              rows={4}
              maxLength={item.maxChars ?? undefined}
              className="gs-input"
              style={{
                ...textareaStyle,
                border: fieldControlBorder((typeof item.answer === "string" ? item.answer : "").trim() !== ""),
              }}
            />
          </FieldRow>
        ))}
      </div>
    </section>
  );
}

/** 企业资质与认证：填一次全报告可用，不必逐个议题重复填同一张证书。
 *
 * 与图片素材是两条并行入口：上传证书图片的用户由识别 Agent 解析出名称/发证机构/
 * 认证范围并汇总到「可持续发展成果」章；在此填文字的用户，内容进「关于公司」正文。
 * 两条都不需要用户在 22 个议题里各填一遍。 */
function CompanyCertificationsSection() {
  const t = useT();
  const { report, setReport } = useApp();
  const item = (report.intakeItems ?? []).find((entry) => entry.key === "company_certifications");
  if (!item) return null;
  const answer = typeof item.answer === "string" ? item.answer : "";
  return (
    <section id="section-company-certifications" style={sectionStyle}>
      <SectionTitle title={t.reportConfig.certificationsHeading} />
      <FieldRow
        label={item.prompt}
        inlineHint={item.hint ?? undefined}
        hint={item.termExplanation ?? undefined}
        htmlFor="company-certifications-textarea"
        counter={{ count: answer.length, max: item.maxChars ?? 3000 }}
      >
        <textarea
          id="company-certifications-textarea"
          data-intake-item="company_certifications"
          value={answer}
          onChange={(event) =>
            setReport((current) =>
              updateIntakeItem(current, item.key, { answer: event.target.value, supplement: item.supplement ?? null }),
            )
          }
          rows={4}
          maxLength={item.maxChars ?? undefined}
          className="gs-input"
          style={{ ...textareaStyle, border: fieldControlBorder(answer.trim() !== "") }}
        />
      </FieldRow>
    </section>
  );
}

/** 公司主体：注册名/简称/行业门类大类——全局，多章引用。主营业务概述由公司简介派生（见 company_business_summary），不在此直填。 */
function CompanySubjectSection() {
  const t = useT();
  const { report, setFieldValue } = useApp();
  const major = String(report.fields.industry_major_category?.value ?? "");
  const division = String(report.fields.industry_division?.value ?? "");
  // 行业目录随报告所属知识包切换：内地包国标 GB/T 4754，港交所两包 HSIC。
  const { majorCategories, divisions: allDivisions } = industryCatalogFor(report.knowledgePackageId);
  const selectedMajorCode = majorCategories.find((item) => item.name === major)?.code ?? "";
  const divisions = selectedMajorCode
    ? allDivisions.filter((item) => item.majorCode === selectedMajorCode)
    : allDivisions;
  const majorField = field(report, "industry_major_category");
  return (
    <section id="section-company-subject" style={sectionStyle}>
      <SectionTitle title={t.intakeInfoSections["section-company-subject"]} obligation={infoSectionObligation("section-company-subject")} />
      <FieldsGroup keys={["company_registered_name", "company_short_name"]} />
      <div style={{ ...gridStyle, marginTop: 14 }}>
        <FieldRow
          label={report.fields.industry_major_category?.label ?? ""}
          required={!!majorField?.required}
          htmlFor={configAnchorId("fields.industry_major_category.value")}
        >
          <select
            id={configAnchorId("fields.industry_major_category.value")}
            data-field="industry_major_category"
            value={major}
            onChange={(event) => {
              const nextMajor = event.target.value;
              setFieldValue("industry_major_category", nextMajor);
              const nextMajorCode = majorCategories.find((item) => item.name === nextMajor)?.code ?? "";
              const divisionStillValid =
                !division || allDivisions.some((item) => item.name === division && item.majorCode === nextMajorCode);
              if (!divisionStillValid) setFieldValue("industry_division", "");
            }}
            className="gs-input"
            style={{ ...inputStyle, border: fieldControlBorder(major.trim() !== "") }}
          >
            <option value="">{t.reportConfig.notSelected}</option>
            {majorCategories.map((item) => (
              <option key={item.code} value={item.name}>
                {item.code} {item.name}
              </option>
            ))}
          </select>
        </FieldRow>
        <FieldRow label={report.fields.industry_division?.label ?? ""} htmlFor={configAnchorId("fields.industry_division.value")}>
          <select
            id={configAnchorId("fields.industry_division.value")}
            data-field="industry_division"
            value={division}
            onChange={(event) => setFieldValue("industry_division", event.target.value)}
            className="gs-input"
            style={{ ...inputStyle, border: fieldControlBorder(division.trim() !== "") }}
          >
            <option value="">{t.reportConfig.notSelected}</option>
            {divisions.map((item) => (
              <option key={item.code} value={item.name}>
                {item.code} {item.name}
              </option>
            ))}
          </select>
        </FieldRow>
      </div>
    </section>
  );
}

/**
 * 披露准则：内地包收窄为沪、深、北三所指引三选一；港交所包的准则由知识包固定，无可选项。
 *
 * 后端以 package.yaml 的 disclosure_basis.mainland_standard_selectable 表达同一事实
 * （diagnostics.py 据此跳过「未选择大陆准则」的判定）。前端按报告所属包分支，
 * 固定准则的包只陈述依据、不渲染选择器——给港交所发行人一份沪深北单选是错的口径。
 *
 * 其他参考文件尚无条款级映射，控件禁用但保留字段与已保存值的回显：
 * 已有报告的编制依据正文仍由该项参与派生（lib/report-values.ts）。
 */


function DisclosureProfileSection() {
  const t = useT();
  const { report, setDisclosureProfile } = useApp();
  const profile = report.disclosureProfile ?? {
    mainlandStandard: "sse",
    includesHongKongExchangeGuide: false,
    additionalDisclosureReferences: [],
  };
  const update = (patch: Partial<typeof profile>) => setDisclosureProfile({ ...profile, ...patch });
  // 准则由知识包固定的包（港交所两包）不渲染选择器，只陈述依据。
  // 依据文本与报告正文的准则名引用同源（lib/disclosure-basis），两处不各写一份。
  const fixedName = fixedStandardName(report);
  return (
    <section id="section-disclosure-profile" style={sectionStyle}>
      <SectionTitle title={t.intakeInfoSections["section-disclosure-profile"]} obligation={infoSectionObligation("section-disclosure-profile")} hint={t.reportConfig.disclosureHint} />
      <div style={{ display: "grid", gap: 14 }}>
        {fixedName ? (
          <div id={configAnchorId("disclosureProfile.mainlandStandard")}>
            <div style={{ fontSize: "var(--text-label-size)", fontWeight: 500, color: "var(--foreground)", marginBottom: 8 }}>
              {t.reportConfig.basisHeading}
            </div>
            <div style={{ fontSize: "var(--text-body-size)", lineHeight: 1.6, color: "var(--foreground)" }}>
              {fixedName}
            </div>
            <div style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", marginTop: 6 }}>
              {t.reportConfig.basisFixedNote}
            </div>
          </div>
        ) : (
          <div id={configAnchorId("disclosureProfile.mainlandStandard")}>
            <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 8 }}>
              <span style={{ fontSize: "var(--text-label-size)", fontWeight: 500, color: "var(--foreground)" }}>{t.reportConfig.mainlandStandard}</span>
              <span aria-hidden style={requiredStarStyle}>*</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {(["sse", "szse", "bse"] as const).map((key) => (
                <label key={key} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: "var(--text-body-size)", lineHeight: 1.6 }}>
                  <input
                    type="radio"
                    name="mainlandStandard"
                    checked={profile.mainlandStandard === key}
                    onChange={() => update({ mainlandStandard: key })}
                    style={{ marginTop: 4 }}
                  />
                  <span>{mainlandStandardNames(report)[key]}</span>
                </label>
              ))}
            </div>
          </div>
        )}
        {/* 两个附加参考项都已停用。**有存量值时仍渲染**（禁用态回显）——design.md §4.0.2：
            禁用只关闭写入、不隐藏事实，控件消失而正文仍引用该值会让界面与交付物互相矛盾。
            无存量值时不渲染：对新报告它只是一个永远灰着的控件，除了让人以为功能残缺别无作用。 */}
        {fixedName || !profile.includesHongKongExchangeGuide ? null : (
        <FieldRow
          label={t.reportConfig.alsoReferenceHkex}
          htmlFor={configAnchorId("disclosureProfile.includesHongKongExchangeGuide")}
          disabled
          disabledReason={t.reportConfig.unavailableStandardReason}
        >
          {/* 勾选框保留是为了让已勾选的历史报告仍看得见自己的选择；标签由 FieldRow 承担，此处不复述。 */}
          <input
            id={configAnchorId("disclosureProfile.includesHongKongExchangeGuide")}
            type="checkbox"
            aria-label={t.reportConfig.alsoReferenceHkex}
            checked={profile.includesHongKongExchangeGuide}
            disabled
            readOnly
            style={{ marginTop: 2 }}
          />
        </FieldRow>
        )}
        {(profile.additionalDisclosureReferences ?? []).length === 0 ? null : (
        <FieldRow
          label={t.reportConfig.otherStandards}
          htmlFor={configAnchorId("disclosureProfile.additionalDisclosureReferences")}
          disabled
          disabledReason={t.reportConfig.unavailableStandardReason}
        >
          <textarea
            id={configAnchorId("disclosureProfile.additionalDisclosureReferences")}
            value={(profile.additionalDisclosureReferences ?? []).join("\n")}
            disabled
            readOnly
            rows={3}
            style={{ ...textareaStyle, minHeight: 76 }}
          />
        </FieldRow>
        )}
        {/* 披露详略当前固定为简化披露（唯一档位），不再展示无选择余地的说明行。 */}
      </div>
    </section>
  );
}

/**
 * 发布与审批信息：均为可选字段，填写后进入「关于本报告」的报告获取方式与审批说明。
 * 字段清单与必填标记都由合同派生（FieldsGroup 读 field.required），不在此硬编码。
 * 公司官网地址由合同的 appears_when 控制显隐，仅在选择「公司官网发布」时出现。
 */
function PublicationAndApprovalSection() {
  const t = useT();
  const { report } = useApp();
  const keys = [
    "report_publication_channel",
    "report_publication_website_url",
    "report_approval_year",
    "report_approval_month",
    "report_approval_body",
  ].filter((key) => {
    const item = field(report, key);
    return item != null && isVisible(item, report);
  });
  if (keys.length === 0) return null;
  return (
    <section style={sectionStyle}>
      <SectionTitle title={t.reportConfig.publicationHeading} />
      <div style={gridStyle}>
        {keys.map((key) => {
          const item = field(report, key);
          if (!item) return null;
          return <FieldInput key={key} field={item} />;
        })}
      </div>
    </section>
  );
}

/** 合并范围：结构化单选，选项决定「关于本报告」披露范围段落的口径变体；
 * 「特殊口径」时按合同 appears_when 追加一句说明。说明文字统一取合同 inputGuidance（FieldInput ⓘ）。 */
function ConsolidationScopeSection() {
  const { report } = useApp();
  const keys = ["consolidation_scope", "consolidation_scope_note"].filter((key) => {
    const item = field(report, key);
    return item != null && isVisible(item, report);
  });
  if (keys.length === 0) return null;
  return (
    <section style={sectionStyle}>
      <FieldsGroup keys={keys} />
    </section>
  );
}

/** 外部鉴证：可选开关；开启后「关于本报告」生成鉴证段落、附录装配鉴证说明，机构/标准/文件名须齐备。 */
function ExternalAssuranceSection() {
  const t = useT();
  const { report, setExternalAssuranceReport } = useApp();
  const assurance = report.appendixPackage?.externalAssuranceReport ?? { isIncluded: false, fileLabel: null };
  return (
    <section style={sectionStyle}>
      {/* 勾选后的段落已说明补齐要求与省略后果，节级 ⓘ 不再复述。 */}
      <SectionTitle title={t.reportConfig.assuranceHeading} />
      <div style={{ display: "grid", gap: 14 }}>
        <label id={configAnchorId("appendixPackage.externalAssuranceReport.isIncluded")} style={{ display: "flex", gap: 8, fontSize: "var(--text-body-size)" }}>
          <input
            type="checkbox"
            checked={assurance.isIncluded}
            onChange={(event) => {
              const included = event.target.checked;
              setExternalAssuranceReport({ isIncluded: included, fileLabel: included ? assurance.fileLabel ?? "" : null });
            }}
          />
          <span>{t.reportConfig.assuranceIncluded}</span>
        </label>
        {assurance.isIncluded ? (
          <>
            <p style={{ margin: 0, fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", lineHeight: 1.6 }}>
              {t.reportConfig.assuranceIncompleteNote}
            </p>
            <FieldRow
              label={t.reportConfig.assuranceFileLabel}
              htmlFor={configAnchorId("appendixPackage.externalAssuranceReport.fileLabel")}
            >
              <input
                id={configAnchorId("appendixPackage.externalAssuranceReport.fileLabel")}
                value={assurance.fileLabel ?? ""}
                onChange={(event) => setExternalAssuranceReport({ fileLabel: event.target.value.trim() || null })}
                className="gs-input"
                style={{ ...inputStyle, border: fieldControlBorder(!!assurance.fileLabel) }}
              />
            </FieldRow>
            <FieldsGroup keys={["assurance_provider_name", "assurance_standard"]} />
          </>
        ) : null}
      </div>
    </section>
  );
}

/** 读者反馈联系：纯选填——填写后装配附录「读者反馈」联系块并被「关于本报告」联络段落引用；
 * 不填则对应附录与段落按合同 appears_when 自动省略，不影响生成与导出。 */
function ReaderContactSection() {
  const t = useT();
  const { report, setReaderFeedbackContactInformation } = useApp();
  const info = report.appendixPackage?.readerFeedbackContactInformation ?? { address: null, email: null, phone: null };
  const committedEmail = info.email ?? "";
  const [emailDraft, setEmailDraft] = useState(committedEmail);
  // 已提交值在外部变化（加载/冲突重载）时于渲染期收敛草稿，不经 effect。
  const [emailBaseline, setEmailBaseline] = useState(committedEmail);
  if (committedEmail !== emailBaseline) {
    setEmailBaseline(committedEmail);
    setEmailDraft(committedEmail);
  }
  return (
    <section style={sectionStyle}>
      <SectionTitle
        title={t.reportConfig.readerContactHeading}
        meta={t.reportConfig.readerContactMeta}
      />
      <FieldGroup reserveGuidanceSpace style={gridStyle}>
        <FieldRow
          label={t.reportConfig.readerEmail}
          inlineHint={inputGuidanceAt(report, "appendixPackage.readerFeedbackContactInformation.email")?.helpText ?? undefined}
          hint={inputGuidanceAt(report, "appendixPackage.readerFeedbackContactInformation.email")?.termExplanation ?? undefined}
          htmlFor={configAnchorId("appendixPackage.readerFeedbackContactInformation.email")}
        >
          <input
            id={configAnchorId("appendixPackage.readerFeedbackContactInformation.email")}
            type="email"
            value={emailDraft}
            onChange={(event) => {
              const next = event.target.value;
              setEmailDraft(next);
              if (next === "" || isFieldValueAllowed("email", next)) {
                setReaderFeedbackContactInformation({ email: next });
              }
            }}
            onBlur={() => {
              if (emailDraft !== "" && !isFieldValueAllowed("email", emailDraft)) setEmailDraft(committedEmail);
            }}
            className="gs-input"
            style={{ ...inputStyle, border: fieldControlBorder(emailDraft.trim() !== "") }}
          />
        </FieldRow>
        <FieldRow
          label={t.reportConfig.companyAddress}
          inlineHint={inputGuidanceAt(report, "appendixPackage.readerFeedbackContactInformation.address")?.helpText ?? undefined}
          hint={inputGuidanceAt(report, "appendixPackage.readerFeedbackContactInformation.address")?.termExplanation ?? undefined}
          htmlFor={configAnchorId("appendixPackage.readerFeedbackContactInformation.address")}
        >
          <input
            id={configAnchorId("appendixPackage.readerFeedbackContactInformation.address")}
            value={info.address ?? ""}
            onChange={(event) => setReaderFeedbackContactInformation({ address: event.target.value })}
            className="gs-input"
            style={{ ...inputStyle, border: fieldControlBorder(!!info.address) }}
          />
        </FieldRow>
        <FieldRow
          label={t.reportConfig.contactPhone}
          inlineHint={inputGuidanceAt(report, "appendixPackage.readerFeedbackContactInformation.phone")?.helpText ?? undefined}
          hint={inputGuidanceAt(report, "appendixPackage.readerFeedbackContactInformation.phone")?.termExplanation ?? undefined}
          htmlFor={configAnchorId("appendixPackage.readerFeedbackContactInformation.phone")}
        >
          <input
            id={configAnchorId("appendixPackage.readerFeedbackContactInformation.phone")}
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            value={info.phone ?? ""}
            onChange={(event) => {
              const next = event.target.value;
              if (isPhoneInput(next)) setReaderFeedbackContactInformation({ phone: next });
            }}
            className="gs-input"
            style={{ ...inputStyle, border: fieldControlBorder(!!info.phone) }}
          />
        </FieldRow>
      </FieldGroup>
    </section>
  );
}

/** 年份紧凑输入：纯数字 4 位，无日历弹窗；键入中间态留在本地草稿，凑满 4 位才写回 Report。 */
function YearCompact({ field }: { field: Field | null }) {
  const { setFieldValue } = useApp();
  const committed = field?.value == null ? "" : String(field.value);
  const [draft, setDraft] = useState(committed);
  // render 期镜像受控值：committed 变化时直接对齐草稿，等价于原 effect。
  const [prevCommitted, setPrevCommitted] = useState(committed);
  if (prevCommitted !== committed) {
    setPrevCommitted(committed);
    setDraft(committed);
  }
  if (!field) return null;
  return (
    <FieldRow label={field.label} required={!!field.required} htmlFor="year-compact-input">
      <input
        id="year-compact-input"
        type="text"
        inputMode="numeric"
        placeholder="2025"
        maxLength={4}
        data-field={field.key}
        value={draft}
        onChange={(e) => {
          const next = e.target.value.replace(/\D/g, "").slice(0, 4);
          setDraft(next);
          if (next === "" || isFieldValueAllowed("year", next)) setFieldValue(field.key, next);
        }}
        onBlur={() => {
          if (draft !== "" && !isFieldValueAllowed("year", draft)) setDraft(committed);
        }}
        className="gs-input"
        style={{ ...inputStyle, border: fieldControlBorder(draft.trim() !== "") }}
      />
    </FieldRow>
  );
}

/** 日期紧凑输入：text 格式 YYYY-MM-DD，避免浏览器原生日历弹窗的中英混搭；完整日期才写回 Report。 */
function DateCompact({ field, label }: { field: Field | null; label: string }) {
  const { setFieldValue } = useApp();
  const committed = field?.value == null ? "" : String(field.value);
  const [draft, setDraft] = useState(committed);
  // render 期镜像受控值：committed 变化时直接对齐草稿，等价于原 effect。
  const [prevCommitted, setPrevCommitted] = useState(committed);
  if (prevCommitted !== committed) {
    setPrevCommitted(committed);
    setDraft(committed);
  }
  if (!field) return null;
  const id = `date-compact-${field.key}`;
  return (
    <FieldRow label={label} required={!!field.required} htmlFor={id}>
      <input
        id={id}
        type="text"
        placeholder="YYYY-MM-DD"
        data-field={field.key}
        value={draft}
        onChange={(e) => {
          const next = e.target.value.replace(/[^0-9-]/g, "").slice(0, 10);
          setDraft(next);
          if (next === "" || isFieldValueAllowed("date", next)) setFieldValue(field.key, next);
        }}
        onBlur={() => {
          if (draft !== "" && !isFieldValueAllowed("date", draft)) setDraft(committed);
        }}
        className="gs-input"
        style={{ ...inputStyle, border: fieldControlBorder(draft.trim() !== "") }}
      />
    </FieldRow>
  );
}

/** 本页必填项的本地完成判定：字段级 required=true（可见者）+ 公司简介（core，非选填区）。
 * 与服务端生成门槛（仅 3 个 profile 字段）不同——本地判定服务于页头进度组件的用户可感知完成度，
 * 不是生成资格真相源；生成资格仍完全由服务端 preparation 投影拥有。 */
function localRequiredItems(report: Report, t: Dictionary): { key: string; label: string; filled: boolean; sectionId: string }[] {
  const items: { key: string; label: string; filled: boolean; sectionId: string }[] = [];
  const pushField = (key: string, sectionId: string) => {
    const item = field(report, key);
    if (!item || !item.required) return;
    if (!isVisible(item, report)) return;
    items.push({
      key,
      label: item.label,
      filled: String(item.value ?? "").trim() !== "",
      sectionId,
    });
  };
  pushField("company_registered_name", "section-company-subject");
  pushField("company_short_name", "section-company-subject");
  pushField("industry_major_category", "section-company-subject");
  pushField("reporting_year", "section-reporting-period");
  pushField("has_technology_ethics_sensitive_activity", "section-applicable-scope");

  const profileItem = (report.intakeItems ?? []).find((entry) => entry.key === "company_profile");
  if (profileItem) {
    items.push({
      key: "company_profile",
      label: t.reportConfig.companyProfileLabel,
      filled: (typeof profileItem.answer === "string" ? profileItem.answer : "").trim() !== "",
      sectionId: "section-company-profile",
    });
  }
  const disclosureFilled = !!report.disclosureProfile?.mainlandStandard;
  items.push({
    key: "disclosureProfile.mainlandStandard",
    label: t.reportConfig.mainlandStandard,
    filled: disclosureFilled,
    sectionId: "section-disclosure-profile",
  });
  return items;
}


/** 页头：h1 + 完成计数 + 4px 进度条 + 因果说明。不再渲染「待完成」chip 行——
 * 完成计数与左栏「本页内容」状态点已表达同一事实。 */
function PageHeader({ title, requiredItems }: { title: string; requiredItems: { key: string; label: string; filled: boolean; sectionId: string }[] }) {
  const t = useT();
  const total = requiredItems.length;
  const done = requiredItems.filter((item) => item.filled).length;
  const ratio = total > 0 ? done / total : 1;
  return (
    <header style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16 }}>
        {/* 页标题派生自步骤声明（intakeStepLabel），与左栏/页脚导航同源。 */}
        <h1 style={{ margin: 0, fontSize: "var(--text-title-size)", fontWeight: 600, color: "var(--foreground)" }}>{title}</h1>
        {total > 0 ? (
          <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)", whiteSpace: "nowrap" }}>
            {interpolate(t.reportConfig.progress, { total, done })}
          </span>
        ) : null}
      </div>
      {total > 0 ? (
        <div
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={total}
          style={{
            marginTop: 10,
            height: 4,
            borderRadius: "var(--radius-pill)",
            background: "var(--surface-sunken)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              height: "100%",
              width: `${Math.round(ratio * 100)}%`,
              borderRadius: "var(--radius-pill)",
              background: "var(--accent)",
              transition: "width .2s ease",
            }}
          />
        </div>
      ) : null}
    </header>
  );
}

export default function IntakeInfoPage() {
  const t = useT();
  const { activeReportCapabilities, activeReportId, report, savedAt } = useApp();
  const scope = activeReportScope(activeReportCapabilities);
  const requiredItems = localRequiredItems(report, t);
  const [preparation, setPreparation] = useState<ReportPreparation | null>(null);
  const [workbookNote, setWorkbookNote] = useState<WorkbookChannelNote | null>(null);

  useEffect(() => {
    if (!activeReportId) return;
    let active = true;
    void fetchReportPreparation(activeReportId)
      .then((next) => {
        if (active) setPreparation(next);
      })
      .catch((error: unknown) => {
        if (active) setPreparation(null);
        console.error("Report preparation load failed", error);
      });
    return () => {
      active = false;
    };
    // savedAt 变化后重新拉取，与自动保存落库节奏同步（原 FirstStepReadiness 语义保留）。
  }, [activeReportId, savedAt]);

  // 服务端投影可用时优先消费（generation_blockers 过滤到本页），否则回退本地判定；
  // 二者衡量的粒度不同（生成门槛 vs 用户可感知完成度），投影缺失不影响页面可用性。
  const serverBlockers = preparation?.generation_blockers.filter((blocker) => blocker.href === "/intake/info") ?? null;
  const headerItems = serverBlockers
    ? requiredItems.map((item) => ({
        ...item,
        filled: item.filled && !serverBlockers.some((blocker) => blockerMatches(blocker.target_handle, item.key)),
      }))
    : requiredItems;

  if (scope.status === "loading") {
    return (
      <div role="status" style={{ maxWidth: 780, margin: "0 auto", padding: "8px 0 28px" }}>
        <LoadingState type="content" text={t.reportConfig.loadingScope} />
      </div>
    );
  }

  return (
    // 单列布局：步骤导航在外壳左栏（IntakeStepRail），本页不设页内导航；
    // 信息分区靠节标题 + 分隔线 + 留白表达。
    <div style={{ maxWidth: 780, margin: "0 auto" }}>
      <main style={{ padding: "8px 0 28px", minWidth: 0 }}>
        <PageHeader title={stepLabel(t, intakeStepKey("/intake/info"))} requiredItems={headerItems} />
        {/* Excel 通道：与评分/定量/议题页同一形态与命名模式（design.md §3.1）。
            统一填报工作簿是报告级整册通道，入口在「我的全部报告」列表（design.md §7.2），不在本页。 */}
        <WorkbookChannel
          tableLabel={t.reportConfig.workbookTableLabel}
          onDownload={downloadReportBasicsTemplate}
          onImport={importReportBasicsWorkbook}
          onNote={setWorkbookNote}
          successText={t.reportConfig.workbookImported}
        />
        {workbookNote ? (
          <div
            role={workbookNote.kind === "error" ? "alert" : "status"}
            style={{
              padding: "10px 0",
              color: workbookNote.kind === "error" ? "var(--destructive)" : "var(--accent)",
              fontSize: "var(--text-label-size)",
            }}
          >
            {workbookNote.text}
          </div>
        ) : null}
        <CompanySubjectSection />
        <CompanyProfileSection />
        <section id="section-reporting-period" style={sectionStyle}>
          <SectionTitle title={t.intakeInfoSections["section-reporting-period"]} obligation={infoSectionObligation("section-reporting-period")} />
          <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 1fr", gap: 14, alignItems: "start" }}>
            <YearCompact field={field(report, "reporting_year")} />
            <DateCompact field={field(report, "report_period_start")} label={t.reportConfig.periodStart} />
            <DateCompact field={field(report, "report_period_end")} label={t.reportConfig.periodEnd} />
          </div>
        </section>
        {/* 前四章与附录进入交付物；准则选择、适用范围与选填补充是这些章节的用户输入面，
            不按范围隐藏。 */}
        <DisclosureProfileSection />
        {/* 适用范围只在声明了该字段的包出现（内地包）；缺字段时整块退场，
            不留一个标着「必填」却没有输入的空区块。左栏二级条目同源过滤。 */}
        {visibleIntakeInfoSections(report).some((section) => section.id === "section-applicable-scope") ? (
          <section id="section-applicable-scope" style={sectionStyle}>
            <SectionTitle title={t.intakeInfoSections["section-applicable-scope"]} obligation={infoSectionObligation("section-applicable-scope")} />
            <FieldsGroup keys={["has_technology_ethics_sensitive_activity"]} />
          </section>
        ) : null}
        <section id="section-optional-supplement" style={{ marginTop: 28 }}>
          <OptionalSupplement defaultOpen hint={t.reportConfig.optionalSupplementHint}>
            <PublicationAndApprovalSection />
            <ExternalAssuranceSection />
            <ReaderContactSection />
            <GovernanceInputsSection />
            <CompanyCertificationsSection />
            <ConsolidationScopeSection />
          </OptionalSupplement>
        </section>
      </main>
      <CoachMarks
        stepKey="intake-info"
        items={[
          { anchorId: "section-company-subject", text: t.reportConfig.coachFields },
          { anchorId: "section-optional-supplement", text: t.reportConfig.coachOptional },
          { anchorId: "coach-autosave", text: t.reportConfig.coachAutosave },
        ]}
      />
    </div>
  );
}

/** target_handle 形如 field.<key> 或 intake item key 本身；用于判定服务端 blocker 是否对应本地某个已判定项。 */
function blockerMatches(targetHandle: string, itemKey: string): boolean {
  if (targetHandle === `field.${itemKey}`) return true;
  return targetHandle === itemKey;
}

