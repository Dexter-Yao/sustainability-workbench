// ABOUTME: 应用级共享状态：运行时 Report + 提示词配置，跨报告准备流程与工作台共享。
// ABOUTME: Supabase 已配置时走服务端快照（登录门禁 + 乐观锁），未配置时保留 localStorage 开发模式；两种模式共用同一 parse/apply 边界。
// ABOUTME: 加载 effect 依赖 isReportlessRoute（非 pathname）避免报告路由间导航整树重载；4 请求并行、定量指标目录按 reportId 缓存；loadWarning/conflictNotice 承载非阻断告警。
// ABOUTME: contract_upgrade_required 投影为独立可操作状态（说明 + 返回列表 + 已生成产物下载入口），不并入通用加载失败红字。
// ABOUTME: 「新建报告」点击即创建服务端报告（lib/report-create），本 Provider 只服务已选定报告的上下文；无报告一律回报告列表。
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  ContractUpgradeRequiredError,
  fetchPromptConfig,
  fetchQuantitativeMetricsInput,
  plan,
  type PromptConfig,
  type QuantitativeMetricDef,
} from "./api";
import { isSessionExpired } from "./api-error";
import { useAuth } from "./auth-context";
import { useAccount } from "./account-context";
import { loadReportTemplate } from "./report-template";
import { industryDisplay } from "./industry-catalog";
import { isFieldValueAllowed } from "./input-validation";
import { projectQuantitativeMetricRows } from "./quantitative-metrics";
import { applyReportInputDefaults, withReportPeriodDefaults } from "./report-input-guidance";
import { LocaleDerivation } from "./i18n/locale-derivation";
import { useT } from "./i18n/locale-context";
import { restoreRuntimeReport } from "./runtime-report";
import {
  currentReportId,
  getReportState,
  putReportState,
  ReportNotFoundError,
  setCurrentReportId,
  StateConflictError,
  subscribeCurrentReportId,
} from "./report-store";
import type { AssessmentResult, Report } from "./schema";
import type { ServerReportState } from "./report-store";
import {
  applyStoredStateToTemplate,
  buildStoredReportStatePayload,
  parseLocalStoredReportState,
  parseStoredReportState,
  reportToStoredReportState,
  serializeStoredReportState,
  type StoredReportStateV4,
} from "./stored-report-state";

const STORE_KEY = "sustainability-desk:report";

// 不依赖报告上下文的账户路由：登录与报告列表直接渲染子树。
const REPORTLESS_ROUTES = new Set([
  // 引导页废止后 / 只是重定向壳（design.md §3.0），自行按报告指针分流，不依赖报告上下文。
  "/",
  "/login",
  "/reports",
  // 生成与交付页不依赖报告编辑上下文：旧契约报告已生成的 Word 必须仍可查看下载，
  // 不得被 plan 加载链路的契约门禁整屏拦截（后端下载端点本就独立于契约版本）。
  "/reports/generation",
]);
const PUBLIC_ACCOUNT_ROUTES = new Set(["/login"]);

interface AppCtx {
  report: Report;
  setReport: (updater: (r: Report) => Report) => void;
  /** 服务端模式下当前报告 id；本地开发模式为 null。生成调用据此关联生成证据。 */
  activeReportId: string | null;
  activeReportCapabilities: ServerReportState["capabilities"] | null;
  /** 立即持久化指定或当前快照，并同步本地已保存基线，供服务端原子生成建立乐观锁。 */
  persistNow: (snapshot?: Report) => Promise<number>;
  /**
   * 应用服务端已原子保存的页面补丁，并同步 state_seq；该本地投影不再重复 PUT。
   *
   * 调用方若持有本次原子写回的完整权威 state（如 StructuredInputMutationResponse.state），
   * 应一并传入以同步刷新 authoritativeBaseline。
   *
   * **省略第三参数的前提不是「没有完整 state」，而是「updater 已把服务端本次写入的
   * 每一个字段都回放进运行时 Report」**——投影会从 Report 重新生成 state，凡未回放的
   * 字段都会被下一次自动保存按陈旧基线覆盖回旧值。两个典型失败形态：
   * `primaryInputMode` 因调用方丢弃返回值被覆盖回 null（用户过不了生成门禁）；
   * 整节生成的 `sectionTitles` 因 updater 未回放被覆盖回旧标题。
   *
   * 服务端拥有的字段（后端 `SERVER_OWNED_STATE_FIELDS`）现由 `put_state` 在锁内保全，
   * 前端漏回放不再导致数据丢失——那是权威防线。但**非服务端拥有的字段仍然只有这一道**：
   * `sectionTitles` 就不在保全集合里（它由工作台正常编辑，不能一律锁死）。
   * 因此新增写 state 的端点时仍要先问「服务端这次改了哪些字段、updater 是否逐个回放」，
   * 答不上来就传完整 state 或改用 applyAuthoritativeReportState。
   */
  applyServerReportUpdate: (
    updater: (r: Report) => Report,
    nextStateSeq: number,
    authoritativeState?: unknown,
  ) => void;
  /** 以服务端返回的完整 StoredReportState 替换本地状态，避免在旧快照上模拟并发写入。 */
  applyAuthoritativeReportState: (state: unknown, nextStateSeq: number) => Promise<void>;
  config: PromptConfig;
  genBlocks: Set<string>;
  setFieldValue: (key: string, value: string) => void;
  setDisclosureProfile: (profile: NonNullable<Report["disclosureProfile"]>) => void;
  setReaderFeedbackContactInformation: (
    values: Partial<NonNullable<Report["appendixPackage"]>["readerFeedbackContactInformation"]>,
  ) => void;
  setExternalAssuranceReport: (
    values: Partial<NonNullable<Report["appendixPackage"]>["externalAssuranceReport"]>,
  ) => void;
  setAssessment: (assessment: AssessmentResult | null) => void;
  /** confirmDrop：存在将被移除的章节时由调用方 UI（ConfirmDialog）确认；未提供或拒绝则不应用。 */
  applyPlan: (
    confirmDrop?: (dropped: string[]) => Promise<boolean>,
  ) => Promise<{ added: string[]; dropped: string[] } | null>;
  saving: boolean;
  savedAt: number | null;
  saveError: string | null;
  retrySave: () => void;
  /** 非阻断加载告警（如附录 KPI 投影失败）；不影响报告可用性，供 AppShell 与 saveError 同位展示。 */
  loadWarning: string | null;
  dismissLoadWarning: () => void;
  /** 服务端拒绝当前令牌（401）：会话已过期，恢复动作是重新登录而非刷新重试。 */
  sessionExpired: boolean;
  /** 并发冲突提示；conflictPending 期间自动保存暂停、本页修改保留，等待用户显式确认加载最新内容。 */
  conflictNotice: string | null;
  conflictPending: boolean;
  confirmConflictReload: () => Promise<void>;
  dismissConflictNotice: () => void;
}

const Ctx = createContext<AppCtx | null>(null);

function Loading({ text }: { text?: string }) {
  const t = useT();
  const shown = text ?? t.appContext.loadingReport;
  return <main style={{ padding: 24, fontFamily: "var(--font-sans)", color: "var(--muted-foreground)" }}>{shown}</main>;
}

function ConfigError({ message }: { message: string }) {
  return (
    <main style={{ padding: 24, fontFamily: "var(--font-sans)", color: "var(--destructive)", lineHeight: 1.7 }}>
      {message}
    </main>
  );
}

function ContractUpgradeScreen({ message }: { message: string }) {
  const t = useT();
  const router = useRouter();
  return (
    <main className="mx-auto w-full max-w-[680px] px-6 py-16" style={{ fontFamily: "var(--font-sans)" }}>
      <h1 className="text-lg font-medium" style={{ color: "var(--foreground)" }}>{t.appContext.contractUpgradeHeading}</h1>
      <p className="mt-3 text-sm" style={{ color: "var(--muted-foreground)", lineHeight: 1.7 }}>
        {t.appContext.contractUpgradeBody}
      </p>
      <p className="mt-3 text-sm" style={{ color: "var(--muted-foreground)", lineHeight: 1.7 }}>
        {t.appContext.contractUpgradeArtifacts}
      </p>
      <p className="mt-2 text-xs" style={{ color: "var(--muted-foreground)" }}>{message}</p>
      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={() => router.push("/reports")}
          className="h-9 rounded-md bg-[color:var(--accent)] px-4 text-sm text-[color:var(--accent-foreground)] enabled:hover:bg-[color:var(--accent-hover)]"
        >
          {t.appContext.backToReports}
        </button>
        <button
          onClick={() => router.push("/reports/generation")}
          className="h-9 rounded-md px-4 text-sm"
          style={{ border: "1px solid var(--border-strong)", background: "var(--background)", color: "var(--foreground-secondary)" }}
        >
          {t.appContext.viewGeneratedReport}
        </button>
      </div>
    </main>
  );
}

function withDerivedIndustry(fields: Report["fields"], key: string, value: string): Report["fields"] {
  const base = fields[key] ?? { key, label: key, type: "string" as const, source: "user_input" as const };
  const next = { ...fields, [key]: { ...base, value } };
  if (key !== "industry_major_category" && key !== "industry_division") return next;
  const major = String(next.industry_major_category?.value ?? "");
  const division = String(next.industry_division?.value ?? "");
  return {
    ...next,
    industry: {
      ...(next.industry ?? { key: "industry", label: "所属行业", type: "string" as const, source: "derived" as const }),
      value: industryDisplay(major, division),
    },
  };
}

function withoutAssessmentSnapshot(report: Report): Report {
  return { ...report, assessment: null };
}

// 定量指标目录（catalog）按 reportId 键控缓存；只供 KPI 投影消费，不作为 metrics 页自身数据源（metrics 页保持新鲜自取）。
const quantitativeCatalogCache = new Map<string, QuantitativeMetricDef[]>();

/** 取回并缓存指定报告的定量指标目录；已缓存时直接复用，避免重复 fetch。 */
async function cachedQuantitativeCatalog(reportId: string): Promise<QuantitativeMetricDef[]> {
  const cached = quantitativeCatalogCache.get(reportId);
  if (cached) return cached;
  const { catalog } = await fetchQuantitativeMetricsInput(reportId);
  quantitativeCatalogCache.set(reportId, catalog);
  return catalog;
}

/** 附录 KPI 表只缓存 meta 的投影；页面加载和冲突重载时统一重建，避免恢复旧快照行。 */
function withQuantitativeMetricProjection(
  report: Report,
  catalog: QuantitativeMetricDef[],
): Report {
  return projectQuantitativeMetricRows(report, catalog);
}

export function AppProvider({ children }: { children: ReactNode }) {
  const t = useT();
  const auth = useAuth();
  const account = useAccount();
  const router = useRouter();
  const pathname = usePathname();
  const serverMode = auth.configured;
  const [report, setReportState] = useState<Report | null>(null);
  const [config, setConfig] = useState<PromptConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [contractUpgradeNotice, setContractUpgradeNotice] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadedReportId, setLoadedReportId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loadWarning, setLoadWarning] = useState<string | null>(null);
  const [conflictNotice, setConflictNotice] = useState<string | null>(null);
  const [conflictPending, setConflictPending] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [saveRetryToken, setSaveRetryToken] = useState(0);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 冲突后暂停自动保存的闸门（与评分页 pausedForConflict 同语义）：
  // 不暂停会反复 409→反复弹横幅，且用户来不及决定就被覆盖本地修改。
  const conflictPaused = useRef(false);
  const firstSave = useRef(true);
  const stateSeq = useRef(1);
  // 最近一次权威服务端 state:保存时凡前端投影覆盖不到的块条目(议题章节生成正文、
  // 表格行、素材图片放置)以此为基线保全,防止窄投影整体覆写抹掉服务端事实。
  const authoritativeBaseline = useRef<StoredReportStateV4 | null>(null);
  const accountId = account.snapshot?.account.id ?? null;
  const subscribeToCurrentReport = useCallback(
    (listener: () => void) => accountId
      ? subscribeCurrentReportId(accountId, listener)
      : () => {},
    [accountId],
  );
  const readCurrentReport = useCallback(
    () => accountId ? currentReportId(accountId) : null,
    [accountId],
  );
  const activeReportId = useSyncExternalStore(
    subscribeToCurrentReport,
    readCurrentReport,
    () => null,
  );
  const [activeContractVersion, setActiveContractVersion] = useState<string | null>(null);
  const [loadedReportCapabilities, setLoadedReportCapabilities] = useState<ServerReportState["capabilities"] | null>(null);
  const [capabilitiesReportId, setCapabilitiesReportId] = useState<string | null>(null);
  // 报告切换在 effect 重置前也必须 fail-closed，不能在一个 render 中把旧 Report 的范围交给新 Report。
  const activeReportCapabilities = capabilitiesReportId === activeReportId
    ? loadedReportCapabilities
    : null;

  // 两个 effect 只关心"是否已登录"这一布尔事实；绝不能以 session 对象引用为依赖——
  // supabase 认证事件（token 刷新、窗口聚焦校验）会频繁换新引用，会导致键入过程中整树反复重载。
  const hasSession = Boolean(auth.session);

  // 服务端模式门禁：未登录去登录页；已登录但未选报告去报告列表。
  useEffect(() => {
    if (!serverMode || auth.loading) return;
    if (!hasSession) {
      if (!PUBLIC_ACCOUNT_ROUTES.has(pathname)) router.replace("/login");
      return;
    }
    // 整页加载时 AccountProvider 的 refresh 尚未开始（loading 初值 false、snapshot null），
    // 此时 accountId 为 null 会把 activeReportId 误读为「未选报告」。snapshot 与 error 同时为空
    // 视为账户仍在解析，不做重定向。
    if (account.loading || (!account.snapshot && !account.error)) return;
    // 「新建报告」点击即创建服务端报告，不存在本地草稿模式：
    // 任何报告上下文路由都要求已选定报告，否则回报告列表。
    if (!activeReportId && !REPORTLESS_ROUTES.has(pathname)) {
      router.replace("/reports");
    }
  }, [serverMode, auth.loading, hasSession, account.loading, account.snapshot, account.error, activeReportId, pathname, router]);

  const isReportlessRoute = REPORTLESS_ROUTES.has(pathname);

  useEffect(() => {
    // 无报告上下文的路由拥有独立 API 投影，不加载报告正文 state。
    if (isReportlessRoute) return;
    if (serverMode && (!hasSession || account.loading || !accountId)) return;
    if (serverMode && !activeReportId) return;
    const reportIdForLoad = serverMode ? activeReportId : null;
    let cancelled = false;
    const load = async () => {
      await Promise.resolve();
      if (cancelled) return;
      setLoaded(false);
      setReportState(null);
      setConfig(null);
      setConfigError(null);
      setContractUpgradeNotice(null);
      setSaveError(null);
      setLoadWarning(null);
      setActiveContractVersion(null);
      setLoadedReportCapabilities(null);
      setCapabilitiesReportId(null);
      // 4 个独立请求并行发起：运行时合同、服务端报告状态、定量指标目录（供 KPI 投影）、生成配置。
      // 各请求互不依赖输入，按现有分支顺序（合同 → 服务端状态/本地快照 → 定量投影 → 配置）处理结果，不改变错误语义。
      const [templateResult, serverStateResult, catalogResult, promptConfigResult] = await Promise.allSettled([
        loadReportTemplate(),
        serverMode && activeReportId ? getReportState(activeReportId) : Promise.resolve(null),
        reportIdForLoad ? cachedQuantitativeCatalog(reportIdForLoad) : Promise.resolve(null),
        fetchPromptConfig(),
      ]);
      if (cancelled) return;

      if (templateResult.status === "rejected") {
        console.error("Runtime report contract load failed", templateResult.reason);
        console.error("Report contract load failed", templateResult.reason);
        setConfigError(t.appContext.errorContractLoad);
        setLoadedReportId(reportIdForLoad);
        setLoaded(true);
        return;
      }
      const template = templateResult.value;

      let r: Report | null = null;
      if (serverMode && activeReportId) {
        if (serverStateResult.status === "rejected") {
          const error = serverStateResult.reason;
          if (error instanceof ContractUpgradeRequiredError) {
            setConfigError(error.message);
            setLoadedReportId(reportIdForLoad);
            setLoaded(true);
            return;
          }
          if (error instanceof ReportNotFoundError) {
            if (accountId) setCurrentReportId(accountId, null);
            router.replace("/reports");
            return;
          }
          console.error("Report state load failed", error);
          if (error instanceof ContractUpgradeRequiredError) {
            setContractUpgradeNotice(error.message);
          } else {
            setConfigError(t.appContext.errorReportLoad);
          }
          setLoadedReportId(reportIdForLoad);
          setLoaded(true);
          return;
        }
        const server = serverStateResult.value;
        if (!server) return;
        try {
          stateSeq.current = server.state_seq;
          setActiveContractVersion(server.contract_version);
          setLoadedReportCapabilities(server.capabilities);
          setCapabilitiesReportId(activeReportId);
          const serverState = parseStoredReportState(JSON.stringify(server.state));
          authoritativeBaseline.current = serverState;
          r = await restoreRuntimeReport(
            template,
            serverState,
            server.contract_version,
            activeReportId,
          );
          if (cancelled) return;
        } catch (error) {
          console.error("Report state load failed", error);
          if (error instanceof ContractUpgradeRequiredError) {
            setContractUpgradeNotice(error.message);
          } else {
            setConfigError(t.appContext.errorReportLoad);
          }
          setLoadedReportId(reportIdForLoad);
          setLoaded(true);
          return;
        }
      } else {
        const raw = window.localStorage.getItem(STORE_KEY);
        const localSnapshot = raw === null
          ? { state: reportToStoredReportState(applyReportInputDefaults(template)), discardedObsoleteVersion: false }
          : parseLocalStoredReportState(raw);
        let state = localSnapshot.state;
        if (localSnapshot.discardedObsoleteVersion) {
          window.localStorage.removeItem(STORE_KEY);
          // 非阻断告知（design.md §4.0.1 禁 window.alert）：走 loadWarning 横幅，与其他加载告警同位。
          setLoadWarning(t.appContext.warnStaleLocalSnapshot);
          state = reportToStoredReportState(applyReportInputDefaults(template));
        }
        if (!state) throw new Error("本地报告状态重建失败");
        r = await restoreRuntimeReport(template, state);
        const nextRaw = serializeStoredReportState(r);
        if (nextRaw !== raw) window.localStorage.setItem(STORE_KEY, nextRaw);
      }
      if (r) {
        if (catalogResult.status === "fulfilled" && catalogResult.value) {
          r = withQuantitativeMetricProjection(r, catalogResult.value);
        } else if (catalogResult.status === "rejected") {
          console.error("Quantitative metric projection load failed", catalogResult.reason);
          console.error("Metric projection failed", catalogResult.reason);
          setLoadWarning(t.appContext.warnMetricProjection);
        }
      }
      let cfg: PromptConfig;
      if (promptConfigResult.status === "fulfilled") {
        cfg = promptConfigResult.value;
      } else {
        cfg = { blocks: [], user_visible_disclosure_clause_annotations: [] };
        console.error("Prompt configuration load failed", promptConfigResult.reason);
        console.error("Prompt config load failed", promptConfigResult.reason);
        setConfigError(t.appContext.errorPromptConfig);
      }
      if (!cancelled) {
        setReportState(r);
        setConfig(cfg);
        setLoadedReportId(reportIdForLoad);
        setLoaded(true);
        firstSave.current = true;
        conflictPaused.current = false;
        setConflictPending(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [serverMode, hasSession, account.loading, accountId, activeReportId, isReportlessRoute, router, t]);

  // 防抖持久化：report 变更统一投影成 StoredReportStateV4；服务端模式走乐观锁，
  // 409 时暂停自动保存并保留本页修改，等待用户显式确认后才以服务端为准重载。
  useEffect(() => {
    if (
      !loaded ||
      !report ||
      conflictPaused.current ||
      (serverMode && loadedReportId !== activeReportId)
    ) return;
    if (firstSave.current) {
      firstSave.current = false;
      return;
    }
    setSaving(true);
    setSaveError(null);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      if (serverMode && !activeReportId) {
        // 服务端模式必有已选定报告（建报即建 + 无报告门禁）；此分支只是防御性收尾。
        setSaving(false);
        return;
      }
      if (serverMode && activeReportId) {
        void (async () => {
          try {
            const snapshot = buildStoredReportStatePayload(report, authoritativeBaseline.current);
            stateSeq.current = await putReportState(activeReportId, JSON.parse(JSON.stringify(snapshot)), stateSeq.current);
            authoritativeBaseline.current = snapshot;
            setSavedAt(Date.now());
            setSessionExpired(false);
          } catch (error) {
            if (error instanceof StateConflictError) {
              conflictPaused.current = true;
              setConflictPending(true);
              setConflictNotice(t.appContext.conflictNotice);
            } else if (isSessionExpired(error)) {
              setSessionExpired(true);
            } else {
              console.error("Report auto-save failed", error);
              console.error("Autosave failed", error);
              setSaveError(t.appContext.errorAutosave);
            }
          } finally {
            setSaving(false);
          }
        })();
        return;
      }
      try {
        window.localStorage.setItem(STORE_KEY, serializeStoredReportState(report));
        setSavedAt(Date.now());
        setSaveError(null);
      } catch (error) {
        console.error("Local report auto-save failed", error);
        setSaveError(t.appContext.errorLocalPersist);
      } finally {
        setSaving(false);
      }
    }, 1000);
  }, [report, loaded, loadedReportId, serverMode, activeReportId, accountId, saveRetryToken, t]);

  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    },
    [],
  );

  const setReport = useCallback((updater: (r: Report) => Report) => {
    setReportState((r) => (r ? updater(r) : r));
  }, []);

  const persistNow = useCallback(async (snapshot?: Report): Promise<number> => {
    if (!report || !activeReportId) throw new Error("当前报告未关联服务端记录");
    if (saveTimer.current) {
      clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const stored = buildStoredReportStatePayload(snapshot ?? report, authoritativeBaseline.current);
      const nextSeq = await putReportState(activeReportId, JSON.parse(JSON.stringify(stored)), stateSeq.current);
      stateSeq.current = nextSeq;
      authoritativeBaseline.current = stored;
      if (snapshot) {
        firstSave.current = true;
        setReportState(snapshot);
      }
      setSavedAt(Date.now());
      return nextSeq;
    } catch (error) {
      if (isSessionExpired(error)) {
        setSessionExpired(true);
      } else {
        console.error("Immediate report save failed", error);
        setSaveError(t.appContext.errorSave);
      }
      throw error;
    } finally {
      setSaving(false);
    }
  }, [report, activeReportId, t]);

  const retrySave = useCallback(() => {
    setSaveRetryToken((current) => current + 1);
  }, []);

  const dismissLoadWarning = useCallback(() => setLoadWarning(null), []);
  const dismissConflictNotice = useCallback(() => setConflictNotice(null), []);

  /** 用户显式确认后才丢弃本页修改、加载其他窗口的最新内容，并恢复自动保存。 */
  const confirmConflictReload = useCallback(async () => {
    if (!activeReportId) return;
    try {
      const server = await getReportState(activeReportId);
      const template = await loadReportTemplate();
      if (!template) throw new Error("报告模板不可用");
      stateSeq.current = server.state_seq;
      firstSave.current = true;
      setActiveContractVersion(server.contract_version);
      setLoadedReportCapabilities(server.capabilities);
      setCapabilitiesReportId(activeReportId);
      const conflictServerState = parseStoredReportState(JSON.stringify(server.state));
      authoritativeBaseline.current = conflictServerState;
      const restored = await restoreRuntimeReport(
        template,
        conflictServerState,
        server.contract_version,
        activeReportId,
      );
      let projected = restored;
      try {
        projected = withQuantitativeMetricProjection(
          restored,
          await cachedQuantitativeCatalog(activeReportId),
        );
      } catch (projectionError) {
        console.error("Quantitative metric projection reload failed", projectionError);
        console.error("Metric projection failed", projectionError);
        setLoadWarning(t.appContext.warnMetricProjection);
      }
      setReportState(projected);
      conflictPaused.current = false;
      setConflictPending(false);
      setConflictNotice(null);
      setSaveError(null);
    } catch (reloadError) {
      if (reloadError instanceof ContractUpgradeRequiredError) {
        setContractUpgradeNotice(reloadError.message);
        setReportState(null);
        return;
      }
      console.error("Runtime report reload failed", reloadError);
      console.error("Report reload failed", reloadError);
      setSaveError(t.appContext.errorReload);
    }
  }, [activeReportId, t]);

  const applyServerReportUpdate = useCallback(
    (updater: (r: Report) => Report, nextStateSeq: number, authoritativeState?: unknown) => {
      stateSeq.current = nextStateSeq;
      firstSave.current = true;
      // 调用方携带服务端本次原子写回的完整权威 state 时同步刷新基线：
      // applyServerReportUpdate 更新 stateSeq 与运行时 Report，若不同步基线会违反
      // “最近一次权威服务端 state” 的不变量（见 authoritativeBaseline 定义处注释）。
      if (authoritativeState !== undefined) {
        authoritativeBaseline.current = parseStoredReportState(JSON.stringify(authoritativeState));
      }
      setReportState((current) => (current ? updater(current) : current));
      setSavedAt(Date.now());
      setSaveError(null);
    },
    [],
  );

  const applyAuthoritativeReportState = useCallback(
    async (state: unknown, nextStateSeq: number) => {
      if (!activeReportId) throw new Error("当前报告未关联服务端记录");
      const template = await loadReportTemplate();
      const authoritativeState = parseStoredReportState(JSON.stringify(state));
      authoritativeBaseline.current = authoritativeState;
      let restored = await restoreRuntimeReport(
        template,
        authoritativeState,
        activeContractVersion ?? undefined,
        activeReportId,
      );
      try {
        restored = withQuantitativeMetricProjection(restored, await cachedQuantitativeCatalog(activeReportId));
      } catch (error) {
        console.error("Quantitative metric projection reload failed", error);
        console.error("Metric projection failed", error);
        setLoadWarning(t.appContext.warnMetricProjection);
      }
      stateSeq.current = nextStateSeq;
      firstSave.current = true;
      setReportState(restored);
      setSavedAt(Date.now());
      setSaveError(null);
    },
    [activeContractVersion, activeReportId, t],
  );

  const setFieldValue = useCallback(
    (key: string, value: string) => {
      setReport((r) => {
        const field = r.fields[key];
        if (!field || !isFieldValueAllowed(field.type, value)) return r;
        // 报告年份填入后按合同 defaultRule 补齐仍为空的报告期起止；已填值不覆盖。
        const next = withReportPeriodDefaults(
          { ...r, fields: withDerivedIndustry(r.fields, key, value) },
          key,
        );
        return key === "has_technology_ethics_sensitive_activity" && r.fields[key]?.value !== value
          ? withoutAssessmentSnapshot(next)
          : next;
      });
    },
    [setReport],
  );

  const setDisclosureProfile = useCallback(
    (profile: NonNullable<Report["disclosureProfile"]>) => {
      // 披露准则配置不再影响议题适用范围（双档已移除），无需失效评估快照。
      setReport((r) => ({ ...r, disclosureProfile: profile }));
    },
    [setReport],
  );

  const setReaderFeedbackContactInformation = useCallback(
    (values: Partial<NonNullable<Report["appendixPackage"]>["readerFeedbackContactInformation"]>) => {
      setReport((r) => ({
        ...r,
        appendixPackage: {
          externalAssuranceReport: r.appendixPackage?.externalAssuranceReport ?? { isIncluded: false, fileLabel: null },
          readerFeedbackContactInformation: {
            address: null,
            email: null,
            ...(r.appendixPackage?.readerFeedbackContactInformation ?? {}),
            ...values,
          },
        },
      }));
    },
    [setReport],
  );

  const setExternalAssuranceReport = useCallback(
    (values: Partial<NonNullable<Report["appendixPackage"]>["externalAssuranceReport"]>) => {
      setReport((r) => ({
        ...r,
        appendixPackage: {
          readerFeedbackContactInformation: r.appendixPackage?.readerFeedbackContactInformation ?? {
            address: null,
            email: null,
          },
          externalAssuranceReport: {
            isIncluded: false,
            fileLabel: null,
            ...(r.appendixPackage?.externalAssuranceReport ?? {}),
            ...values,
          },
        },
      }));
    },
    [setReport],
  );

  const setAssessment = useCallback(
    (assessment: AssessmentResult | null) => {
      setReport((r) => ({ ...r, assessment }));
    },
    [setReport],
  );

  // 按报告配置与完整适用评估清单调用服务端 plan；丢弃章节由调用方 UI 确认后再应用
  // （design.md §4.0.1 禁 window.confirm，确认走 ConfirmDialog）。
  const applyPlan = useCallback(async (
    confirmDrop?: (dropped: string[]) => Promise<boolean>,
  ) => {
    if (!report || (serverMode && !activeReportId)) return null;
    const result = await plan(report, activeContractVersion ?? undefined, activeReportId ?? undefined);
    if (result.dropped.length) {
      const confirmed = confirmDrop ? await confirmDrop(result.dropped) : false;
      if (!confirmed) return null;
    }
    // plan 结果只是模板重装配；仅存于服务端 state 的事实（如素材图片放置）须以权威基线重放，
    // 否则会被这次窄投影覆写抹掉（与 restoreRuntimeReport 的二次投影同语义）。
    const baseline = authoritativeBaseline.current;
    setReportState(baseline ? applyStoredStateToTemplate(result.report, baseline) : result.report);
    return { added: result.added, dropped: result.dropped };
  }, [report, serverMode, activeReportId, activeContractVersion]);

  const value = useMemo<AppCtx | null>(() => {
    if (!report || !config) return null;
    return {
      report,
      setReport,
      activeReportId,
      activeReportCapabilities,
      persistNow,
      applyServerReportUpdate,
      applyAuthoritativeReportState,
      config,
      genBlocks: new Set(config.blocks.map((block) => block.id)),
      setFieldValue,
      setDisclosureProfile,
      setReaderFeedbackContactInformation,
      setExternalAssuranceReport,
      setAssessment,
      applyPlan,
      saving,
      savedAt,
      saveError,
      retrySave,
      loadWarning,
      dismissLoadWarning,
      sessionExpired,
      conflictNotice,
      conflictPending,
      confirmConflictReload,
      dismissConflictNotice,
    };
  }, [
    report,
    config,
    activeReportId,
    activeReportCapabilities,
    persistNow,
    applyServerReportUpdate,
    applyAuthoritativeReportState,
    setReport,
    setFieldValue,
    setDisclosureProfile,
    setReaderFeedbackContactInformation,
    setExternalAssuranceReport,
    setAssessment,
    applyPlan,
    saving,
    savedAt,
    saveError,
    retrySave,
    loadWarning,
    dismissLoadWarning,
    sessionExpired,
    conflictNotice,
    conflictPending,
    confirmConflictReload,
    dismissConflictNotice,
  ]);

  // 认证初始化真实故障（非"环境未配置"降级）：不得静默退化为本地开发模式，必须显式报错。
  if (auth.authError) return <ConfigError message={t.appContext.errorAuthInit} />;
  // 登录页与报告列表页不依赖报告上下文，直接渲染；其余路由等待门禁与加载完成。
  if (REPORTLESS_ROUTES.has(pathname)) return <>{children}</>;
  if (serverMode && (auth.loading || account.loading || !auth.session)) return <Loading />;
  // 未选定报告：门禁 effect 即将重定向 /reports，先渲染加载占位。
  if (serverMode && !activeReportId) return <Loading />;
  if (serverMode && account.error) return <ConfigError message={account.error} />;
  if (serverMode && !account.snapshot) return <Loading text={t.appContext.loadingAccount} />;
  if (!loaded || (serverMode && loadedReportId !== activeReportId)) {
    return <Loading text={t.appContext.loadingCurrentReport} />;
  }
  if (contractUpgradeNotice) return <ContractUpgradeScreen message={contractUpgradeNotice} />;
  if (configError) return <ConfigError message={configError} />;
  if (!report) return <ConfigError message={t.appContext.errorReportState} />;
  // Context 仅保存事件回调；此处判断 memo 结果，不会在渲染阶段执行回调或读取其内部 ref。
  // eslint-disable-next-line react-hooks/refs
  if (!value) return <Loading text={t.appContext.loadingConfig} />;
  return (
    <Ctx.Provider value={value}>
      {/* 界面语言的默认值跟随本报告的知识包语言；用户显式选过后不再改写。
          放在这里而不是 LocaleProvider 里：后者在账户上下文之外，拿不到报告。 */}
      <LocaleDerivation />
      {children}
    </Ctx.Provider>
  );
}

export function useApp(): AppCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp 必须在 AppProvider 内使用");
  return ctx;
}

/** 报告上下文的可缺省读取：reportless 路由（/reports、/ 等）不建报告 context，
    共享外壳（AppShell/AppTopBar）据此降级——不渲染保存态与冲突横幅。 */
export function useAppOptional(): AppCtx | null {
  return useContext(Ctx);
}
