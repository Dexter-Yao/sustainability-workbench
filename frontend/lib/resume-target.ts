// ABOUTME: 「继续上次的编制」目标解析：把服务端权威事实解析成一个可直接跳转的报告与步骤。
// ABOUTME: 进度属于账户不属于设备；本机指针只是同设备快捷方式，缺失或失效时按服务端事实重建。
import { fetchReportPreparation, type ReportPreparation } from "./material-workspace-api";
import { listReports, type ReportSummary } from "./report-store";

/** 分步流第一步：报告存在但准备状态取不到时的确定性落点。 */
const FIRST_STEP_HREF = "/intake/info";
/** 分步流末步：由报告级填报方式决定，与 lib/intake-steps.ts 的序列一致。 */
const TOPIC_QUESTIONS_HREF = "/intake/questions";
const MATERIAL_PROCESSING_HREF = "/materials/processing";
const INPUT_PATH_HREF = "/intake/input-path";

export interface ResumeTarget {
  reportId: string;
  /** 该报告当前应当继续的那一步；始终是一个可直接 router.replace 的站内路径。 */
  href: string;
}

/**
 * 在一组报告里选出「上次编辑的那一份」。
 *
 * 服务端 `updated_at` 每次状态保存都会推进（reports.py 的 put_state），因此
 * 「最近编辑」是权威事实，不需要再存一份可能与之漂移的指针。
 */
function mostRecentlyEdited(reports: readonly ReportSummary[]): ReportSummary | null {
  const active = reports.filter((report) => report.status === "active");
  if (active.length === 0) return null;
  return active.reduce((latest, candidate) =>
    candidate.updated_at > latest.updated_at ? candidate : latest,
  );
}

export type PreparationFacts = Pick<
  ReportPreparation,
  "areas" | "generation_blockers" | "primary_input_mode"
>;

/**
 * 从准备状态里取出「该继续哪一步」。
 *
 * href 由服务端 preparation 投影自带，浏览器不自行维护 area→路由映射：那会让
 * 步骤归属出现第二份真相，服务端调整步骤后前端静默跳到过时的页面。
 */
export function resumeHrefFrom(preparation: PreparationFacts | null): string {
  if (!preparation) return FIRST_STEP_HREF;
  const pending = preparation.areas.find((area) => area.status === "needs_input");
  if (pending?.href) return pending.href;
  const blocker = preparation.generation_blockers[0];
  if (blocker?.href) return blocker.href;
  // 无待办也无阻断项：该报告已可生成，落到分步流末步的生成区所在页更贴近用户意图。
  //
  // 末步由**填报方式**决定，不能取 areas 的最后一项：materials area 无条件产出且恒在末位
  // （已上传资料在直答路径下仍参与生成），直接取它会把 questions 路径的用户送到
  // 一个不在其步骤序列里的 /materials——左栏无从高亮，用户也不知道自己在哪一步。
  if (preparation.primary_input_mode === "questions") return TOPIC_QUESTIONS_HREF;
  if (preparation.primary_input_mode === "materials") return MATERIAL_PROCESSING_HREF;
  // 尚未二选一：落到填报方式 gateway，这正是他该做的下一件事。
  return INPUT_PATH_HREF;
}

/**
 * 解析「继续上次的编制」应当去哪里；没有可继续的报告时返回 null。
 *
 * `preferredReportId` 是本机指针。它命中当前账户的活跃报告时优先采用（同设备连续
 * 操作的体验不变）；失效或缺失则回退到最近编辑的那份——换设备、清缓存、换浏览器
 * 都能接着上次那一步继续，因为依据的是账户在服务端的事实而不是这台设备的记忆。
 */
export async function resolveResumeTarget(
  preferredReportId: string | null,
): Promise<ResumeTarget | null> {
  let reports: readonly ReportSummary[];
  try {
    reports = await listReports();
  } catch {
    // 列表取不到时不猜：交给报告列表页按它自己的门禁与错误提示处理。
    return null;
  }

  const preferred = preferredReportId
    ? reports.find((report) => report.id === preferredReportId && report.status === "active")
    : undefined;
  const target = preferred ?? mostRecentlyEdited(reports);
  if (!target) return null;

  try {
    const preparation = await fetchReportPreparation(target.id);
    return { reportId: target.id, href: resumeHrefFrom(preparation) };
  } catch {
    // 准备状态取不到不应阻断「继续」：报告本身是确定的，落到第一步仍然可用。
    return { reportId: target.id, href: FIRST_STEP_HREF };
  }
}
