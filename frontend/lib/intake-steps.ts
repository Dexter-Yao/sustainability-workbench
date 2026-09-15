// ABOUTME: intake 步骤序列——根据当前报告 scope 与报告级主输入路径动态决定用户可见步骤。
// ABOUTME: 两版共用一条固定四步序列；第 4 步「定性信息」恒在，所选路径的页面作为它的二级条目。

export type PrimaryInputMode = "materials" | "questions";

/** 步骤下的二级条目：所选路径的实际页面；不参与步骤编号。 */
export interface IntakeStepSection {
  href: string;
  key: IntakeStepKey;
}

/** 步骤标识；界面文案由字典按此 key 取（lib/i18n 的 intakeSteps）。 */
export type IntakeStepKey =
  | "reportBasics"
  | "materialityScoring"
  | "quantitative"
  | "inputPath"
  | "topicQuestions"
  | "materialUpload"
  | "materialProcessing";

export interface IntakeStep {
  href: string;
  key: IntakeStepKey;
  /**
   * 遥测屏标签（design.md §7 注册表的中文名）。
   *
   * 它与 `data-screen-id` 同级，是**稳定标识**而非用户可见 chrome：屏幕上不显示，
   * 守护测试与 e2e 都按 id/label 定位。因此恒为中文，不随界面语言变化——
   * 让它跟着字典走，遥测标识会随用户切语言而漂移。
   */
  screenLabel: string;
  /** 必填步骤（生成前必须完成）；左栏步骤导航据此渲染红色「必填」标记。 */
  required?: boolean;
  /** 二级条目（当前仅第 4 步按所选路径产出）；空数组表示该步无下级页面。 */
  sections?: readonly IntakeStepSection[];
}

/** 资料处理步骤（materials 路径末步）；上传资料确认后导航到此，承载两道闸与生成区。 */
const MATERIAL_PROCESSING_STEP: IntakeStep = {
  href: "/materials/processing",
  key: "materialProcessing",
  screenLabel: "资料处理",
};

/** 资料上传步骤（materials 路径第 4 步）。 */
const MATERIAL_UPLOAD_STEP: IntakeStep = {
  href: "/materials",
  key: "materialUpload",
  screenLabel: "上传资料",
};

/** 定性信息（二选一）步——尚未选择提供方式时的第 4 步；选择后被所选路径替换。
 * 与「定量信息」相对应：议题的定性内容由上传资料或直接回答问题二选一提供。 */
const INPUT_PATH_STEP: IntakeStep = {
  href: "/intake/input-path",
  key: "inputPath",
  screenLabel: "定性信息",
};

/** 议题信息直填步（questions 路径末步）；页尾承载生成区。 */
const TOPIC_QUESTIONS_STEP: IntakeStep = {
  href: "/intake/questions",
  key: "topicQuestions",
  screenLabel: "议题信息填写",
};

/** 基本信息步骤（两版共用，唯一 required 声明处）。 */
const REPORT_BASICS_STEP: IntakeStep = {
  href: "/intake/info",
  key: "reportBasics",
  screenLabel: "企业及报告基本信息",
  required: true,
};

/** 重要性评分步骤；是否出现由 collectsMaterialityAssessment 决定，不按报告 kind 判断。 */
const MATERIALITY_SCORING_STEP: IntakeStep = {
  href: "/intake/scoring",
  key: "materialityScoring",
  screenLabel: "议题重要性评分",
};

const QUANTITATIVE_STEP: IntakeStep = {
  href: "/intake/metrics",
  key: "quantitative",
  screenLabel: "ESG 定量信息",
};

/** 按路由取步骤声明；未登记路由属编程错误，fail-loud。 */
function declaredStep(href: string): IntakeStep {
  const declared = [
    REPORT_BASICS_STEP,
    MATERIALITY_SCORING_STEP,
    QUANTITATIVE_STEP,
    INPUT_PATH_STEP,
    TOPIC_QUESTIONS_STEP,
    MATERIAL_UPLOAD_STEP,
    MATERIAL_PROCESSING_STEP,
  ];
  const step = declared.find((candidate) => candidate.href === href);
  if (!step) throw new Error(`unknown intake step route: ${href}`);
  return step;
}

/**
 * 遥测屏标签（恒中文，见 IntakeStep.screenLabel）。
 *
 * 与页面 h1 **不再同源**：h1 是用户可见文案、随界面语言变化，而屏标签是稳定标识。
 * 让两者继续同源，会使遥测标签随用户切语言漂移。
 */
export function intakeStepScreenLabel(href: string): string {
  return declaredStep(href).screenLabel;
}

/** 步骤的字典 key；页面 h1 与导航文案据此取词。 */
export function intakeStepKey(href: string): IntakeStepKey {
  return declaredStep(href).key;
}

/** 根据当前报告 scope 与报告级主输入路径返回用户可见的步骤序列。
 *
 *
 *
 * primaryInputMode 来自服务端 preparation 投影（未到达或未选择时为 null），
 * 前端不得从本地状态推断。
 */
export function getIntakeSteps(
  scope: {
    collectsMaterialityAssessment: boolean;
    materialAgentEnabled: boolean;
  },
  primaryInputMode: PrimaryInputMode | null = null,
): IntakeStep[] {
  const baseSteps = [
    REPORT_BASICS_STEP,
    ...(scope.collectsMaterialityAssessment ? [MATERIALITY_SCORING_STEP] : []),
    QUANTITATIVE_STEP,
  ];
  return [...baseSteps, { ...INPUT_PATH_STEP, sections: qualitativeSections(scope, primaryInputMode) }];
}

/**
 * 第 4 步「定性信息」的二级条目：所选路径的实际页面。
 *
 * 路径页面是该步的**下级**，不是替代它的同级步骤。若让 materials 路径把步骤条
 * 改写成「4 上传资料 / 5 资料处理」、questions 改写成「4 议题信息」，
 * 一级标签就随路径漂移，用户看不出这些页面同属「定性信息」，
 * 也失去回到二选一页的导航入口。因此一级恒为「定性信息」（去向恒为二选一
 * gateway，即换路径入口），总步数恒为 4。
 *
 * `materialAgentEnabled=false` 时不存在可选的 materials 路径，直填是唯一去向，
 * 无需展开二级——一个下级等于没有下级。
 */
function qualitativeSections(
  scope: { materialAgentEnabled: boolean },
  primaryInputMode: PrimaryInputMode | null,
): readonly IntakeStepSection[] {
  // 无资料解析能力：直填是唯一去向，二选一不成立。仍产出这一条二级——它是
  // 该步真正可操作、且承载页尾生成区的页面；缺了它，「下一步」与生成入口都会
  // 指向只承载路径选择的 gateway（那一页没有生成区）。
  if (!scope.materialAgentEnabled) {
    return [{ href: TOPIC_QUESTIONS_STEP.href, key: TOPIC_QUESTIONS_STEP.key }];
  }
  if (primaryInputMode === "questions") {
    return [{ href: TOPIC_QUESTIONS_STEP.href, key: TOPIC_QUESTIONS_STEP.key }];
  }
  if (primaryInputMode === "materials") {
    return [
      { href: MATERIAL_UPLOAD_STEP.href, key: MATERIAL_UPLOAD_STEP.key },
      { href: MATERIAL_PROCESSING_STEP.href, key: MATERIAL_PROCESSING_STEP.key },
    ];
  }
  // 尚未二选一：还没有下级页面可去，只有 gateway 本身。
  return [];
}

/**
 * 按最长 href 前缀匹配当前步骤索引（而非声明顺序命中即止），避免 `/materials` 前缀
 * 误吞 `/materials/processing`。未匹配任何步骤时返回 -1。
 */
export function matchIntakeStepIndex(pathname: string | null, steps: IntakeStep[]): number {
  if (!pathname) return -1;
  let index = -1;
  let bestLength = -1;
  steps.forEach((step, candidateIndex) => {
    // 二级条目一并参与匹配：停留在 /materials 或 /intake/questions 时，
    // 当前步仍是它们所属的第 4 步「定性信息」。
    for (const href of [step.href, ...(step.sections ?? []).map((section) => section.href)]) {
      if (!pathname.startsWith(href)) continue;
      if (href.length > bestLength) {
        bestLength = href.length;
        index = candidateIndex;
      }
    }
  });
  return index;
}

/** 根据当前 pathname 解析步骤位置；非 intake 页面返回 null。 */
export function resolveIntakeStep(
  pathname: string | null,
  steps: IntakeStep[],
): {
  current: IntakeStep;
  previous: IntakeStep | null;
  next: IntakeStep | null;
  index: number;
  total: number;
} | null {
  const index = matchIntakeStepIndex(pathname, steps);
  if (index < 0) return null;
  const nextStep = steps[index + 1] ?? null;
  // 「下一步」指向下一步的**首个可操作页**：第 4 步已选路径时，用户该去的是
  // 路径首页（/materials 或 /intake/questions），不是只承载路径选择的二选一
  // gateway——已选过还把人送回选择页是一次无谓折返。
  // 未选路径时二级为空，next 仍是 gateway，那正是他该做的下一件事。
  const nextEntry = nextStep && (nextStep.sections?.length ?? 0) > 0
    ? { ...nextStep, href: nextStep.sections![0].href }
    : nextStep;
  return {
    current: steps[index],
    previous: steps[index - 1] ?? null,
    next: nextEntry,
    index,
    total: steps.length,
  };
}

/** 生成入口所在页:分步流末步(准备概览页已废除,生成动作在末步页尾就地完成)。 */
export function generationEntryHref(
  scope: {
    collectsMaterialityAssessment: boolean;
    materialAgentEnabled: boolean;
  },
  primaryInputMode: PrimaryInputMode | null = null,
): string {
  const steps = getIntakeSteps(scope, primaryInputMode);
  const lastStep = steps[steps.length - 1];
  if (!lastStep) return "/intake/info";
  // 末步有二级条目时，生成区在其最后一页（如 materials 路径的 /materials/processing），
  // 不在一级的二选一 gateway 上——gateway 只承载路径选择，不承载生成动作。
  const sections = lastStep.sections ?? [];
  return sections.length > 0 ? sections[sections.length - 1].href : lastStep.href;
}
