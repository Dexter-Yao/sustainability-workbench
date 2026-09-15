// ABOUTME: 文件入口的单角色上传区（design.md §3.5）：一个拖放区 + 本区文件列表，投放到本区即声明该区角色。
// ABOUTME: 白名单、字数、大小全部取自 intake.policy；/materials 两区与 /intake/questions 图片区共用，默认不显示处理结果（showAnalysisStatus 是 §7.3 登记的唯一例外）。
"use client";

import {
  type ChangeEvent,
  type CSSProperties,
  type FocusEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/Button";
import { interpolate, type Dictionary } from "@/lib/i18n/dictionary";
import { useT } from "@/lib/i18n/locale-context";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { FileDropZone } from "@/components/ui/FileDropZone";
import {
  fetchReportFileIntake,
  MaterialWorkspaceConflictError,
  removeReportFile,
  restoreReportFile,
  updateReportFileDeclaration,
  updateReportFileSourceLabel,
  uploadReportFiles,
  type ReportFileDeclarationInput,
  type ReportFileIntake,
} from "@/lib/material-workspace-api";
import { imageAnalysisLabel } from "./file-analysis-labels";

export type ReportFileRole = ReportFileIntake["sources"][number]["declaration"]["role"];

type SourceWithLabel = ReportFileIntake["sources"][number];

/**
 * 两个上传区的文案定稿（design.md §3.5 表格）；代码只从这里取。
 *
 * role 是稳定标识（semantic_material / layout_asset），措辞随界面语言：
 * 取词函数而非字符串常量，调用侧传入当前字典。
 */
type RoleCopy = {
  title: (t: Dictionary) => string;
  headerQuestion: (t: Dictionary) => string;
  placeholder: (t: Dictionary) => string;
  emptyTitle: (t: Dictionary) => string;
  emptyDescription?: (t: Dictionary) => string;
  usageNote: (t: Dictionary) => string;
};

export const ROLE_COPY: Record<ReportFileRole, RoleCopy> = {
  semantic_material: {
    title: (t) => t.materials.semanticTitle,
    headerQuestion: (t) => t.materials.semanticHeaderQuestion,
    placeholder: (t) => t.materials.semanticPlaceholder,
    emptyTitle: (t) => t.materials.semanticEmptyTitle,
    emptyDescription: (t) => t.materials.semanticEmptyDescription,
    usageNote: (t) => t.materials.semanticUsageNote,
  },
  layout_asset: {
    title: (t) => t.materials.layoutTitle,
    headerQuestion: (t) => t.materials.layoutHeaderQuestion,
    placeholder: (t) => t.materials.layoutPlaceholder,
    emptyTitle: (t) => t.materials.layoutEmptyTitle,
    emptyDescription: (t) => t.materials.layoutEmptyDescription,
    usageNote: (t) => t.materials.layoutUsageNote,
  },
};

/**
 * 异步回调的卸载守卫:blur 保存或移出请求在途时组件可能因新快照被卸载,
 * 之后不得再写本地 state。StrictMode 会重挂载,故挂载时须重置为 true。
 */
function useAliveRef() {
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  return alive;
}

function fallbackTopicTag(policy: ReportFileIntake["policy"]): string {
  return policy.topic_tags.find((tag) => tag.id === "uncertain")?.id ?? policy.topic_tags[0]!.id;
}

export function sizeLabel(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MiB`
    : `${Math.ceil(bytes / 1024)} KiB`;
}

function fileSuffix(file: File): string {
  const name = file.name.toLowerCase();
  return name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
}

export function roleExtensions(policy: ReportFileIntake["policy"], role: ReportFileRole): string[] {
  return role === "semantic_material"
    ? policy.semantic_material_extensions
    : policy.layout_asset_extensions;
}

export interface FilePartitionRejection {
  file: File;
  reason: string;
}

export interface FilePartitionResult {
  accepted: File[];
  rejected: FilePartitionRejection[];
}

/**
 * 按本区角色的服务端白名单分区一批文件：角色由投放的区声明，只判定该角色的扩展名与大小，
 * 不支持的逐个具名拒绝、不跨区改投。不做 accept 属性兜底——用户可从系统选择器选中任意文件，
 * 分区结果才是唯一真相。
 */
export function partitionFilesForRole(
  files: File[],
  role: ReportFileRole,
  policy: ReportFileIntake["policy"],
  t: Dictionary,
): FilePartitionResult {
  const extensions = roleExtensions(policy, role);
  const accepted: File[] = [];
  const rejected: FilePartitionRejection[] = [];
  for (const file of files) {
    if (!extensions.includes(fileSuffix(file))) {
      rejected.push({
        file,
        reason: interpolate(t.materials.unsupportedFormat, { role: ROLE_COPY[role].title(t), extensions: extensions.join(t.materials.listSeparator) }),
      });
      continue;
    }
    if (file.size > policy.max_file_bytes) {
      rejected.push({ file, reason: interpolate(t.materials.oversize, { limit: sizeLabel(policy.max_file_bytes) }) });
      continue;
    }
    accepted.push(file);
  }
  return { accepted, rejected };
}

function rowColumns(showAnalysisStatus: boolean): string {
  return showAnalysisStatus ? "300px minmax(0,1fr) 110px 32px" : "300px minmax(0,1fr) 32px";
}

/**
 * blur 即保存的填空底座：静默态透明边框占位防跳动，hover 显中性边框，focus 显主色边框。
 * 这是"直接编辑"的核心视觉表达——读起来像文本，点进去即编辑。
 */
function fillInStyle(extra?: CSSProperties): CSSProperties {
  return {
    width: "100%",
    boxSizing: "border-box",
    border: "1px solid transparent",
    borderRadius: "var(--radius-control)",
    background: "transparent",
    color: "var(--foreground)",
    font: "inherit",
    padding: "5px 7px",
    margin: "-5px -7px",
    ...extra,
  };
}

const fillInHoverFocusCss = `
.gs-fillin { transition: border-color 0.1s ease; }
.gs-fillin:hover { border-color: var(--border); }
.gs-fillin:focus { outline: none; border-color: var(--accent); }
`;

function FileNameField({
  source,
  reportId,
  onSnapshot,
  onSavingChange,
}: {
  source: SourceWithLabel;
  reportId: string;
  onSnapshot: (next: ReportFileIntake) => void;
  onSavingChange: (delta: number) => void;
}) {
  const t = useT();
  const alive = useAliveRef();
  const committed = source.source_label ?? source.filename;
  const [draft, setDraft] = useState(committed);
  const [error, setError] = useState<string | null>(null);
  // render 期镜像受控文件名：committed 变化时直接对齐草稿并清空旧错误，等价于原 effect。
  const [prevCommitted, setPrevCommitted] = useState(committed);
  if (prevCommitted !== committed) {
    setPrevCommitted(committed);
    setDraft(committed);
    setError(null);
  }

  const handleBlur = async (event: FocusEvent<HTMLInputElement>) => {
    const next = event.target.value.trim();
    if (!next) {
      setDraft(committed);
      return;
    }
    if (next === committed) return;
    setError(null);
    onSavingChange(1);
    try {
      const snapshot = await updateReportFileSourceLabel(reportId, source.binding_id, next);
      onSnapshot(snapshot);
    } catch {
      if (alive.current) {
        setDraft(committed);
        setError(t.materials.errorRenameFile);
      }
    } finally {
      onSavingChange(-1);
    }
  };

  const notReady = !source.declaration.description.trim();
  const sizeText = notReady
    ? interpolate(t.materials.pendingDescription, { size: sizeLabel(source.size_bytes) })
    : sizeLabel(source.size_bytes);

  return (
    <div style={{ minWidth: 0 }}>
      <input
        className="gs-fillin"
        style={fillInStyle({ fontSize: "var(--text-body-size)", fontWeight: 500 })}
        value={draft}
        disabled={source.binding_status !== "active"}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={(event) => void handleBlur(event)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setDraft(committed);
            setError(null);
          } else if (event.key === "Enter") {
            event.currentTarget.blur();
          }
        }}
        aria-label={interpolate(t.materials.ariaDisplayName, { filename: source.filename })}
      />
      <div
        style={{
          fontSize: "var(--text-supporting-size)",
          color: notReady ? "var(--warning)" : "var(--muted-foreground)",
          paddingLeft: 7,
          marginTop: 2,
        }}
      >
        {sizeText}
      </div>
      {error ? (
        <span role="alert" style={{ fontSize: "var(--text-supporting-size)", color: "var(--destructive)", paddingLeft: 7 }}>
          {error}
        </span>
      ) : null}
    </div>
  );
}

function DescriptionField({
  source,
  intake,
  reportId,
  placeholder,
  onSnapshot,
  onConflict,
  onSavingChange,
}: {
  source: SourceWithLabel;
  intake: ReportFileIntake;
  reportId: string;
  placeholder: string;
  onSnapshot: (next: ReportFileIntake) => void;
  onConflict: () => void;
  onSavingChange: (delta: number) => void;
}) {
  const t = useT();
  const alive = useAliveRef();
  const committed = source.declaration.description;
  const revision = source.declaration.revision;
  const [draft, setDraft] = useState(committed);
  const [error, setError] = useState<string | null>(null);
  // render 期镜像受控说明：仅 revision（服务端真正落库的版本号）变化时才对齐草稿并清空旧错误，
  // 与原 effect 依赖 [revision] 而非 [committed] 等价——轮询刷新若说明未真正变更，不打断用户正在输入的草稿。
  const [prevRevision, setPrevRevision] = useState(revision);
  if (prevRevision !== revision) {
    setPrevRevision(revision);
    setDraft(committed);
    setError(null);
  }

  const minChars = intake.policy.description_min_chars;
  const maxChars = intake.policy.description_max_chars;
  const trimmedLength = draft.trim().length;
  const shortOfMin = trimmedLength > 0 && trimmedLength < minChars;

  const handleBlur = async (event: FocusEvent<HTMLTextAreaElement>) => {
    const value = event.target.value;
    const trimmed = value.trim();
    if (trimmed === committed.trim()) return;
    if (trimmed.length > 0 && trimmed.length < minChars) return;
    setError(null);
    onSavingChange(1);
    try {
      const payload: ReportFileDeclarationInput = {
        description: trimmed,
        role: source.declaration.role,
        topic_tags: source.declaration.topic_tags.length
          ? source.declaration.topic_tags
          : [fallbackTopicTag(intake.policy)],
        asset_title: source.declaration.asset_title,
      };
      const snapshot = await updateReportFileDeclaration(
        reportId,
        source.binding_id,
        payload,
        revision,
      );
      onSnapshot(snapshot);
    } catch (cause) {
      if (cause instanceof MaterialWorkspaceConflictError) {
        onConflict();
        return;
      }
      // 保留草稿供重试;回滚等于把用户输入无声丢弃。
      if (alive.current) setError(t.materials.errorSaveDescription);
    } finally {
      onSavingChange(-1);
    }
  };

  return (
    <div style={{ minWidth: 0 }}>
      <textarea
        className="gs-fillin"
        style={fillInStyle({ resize: "none", lineHeight: 1.7, fontSize: "var(--text-body-size)", border: "1px solid var(--border)", margin: 0, padding: "7px 9px" })}
        rows={2}
        value={draft}
        maxLength={maxChars}
        disabled={source.binding_status !== "active"}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={(event) => void handleBlur(event)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setDraft(committed);
            setError(null);
          }
        }}
        aria-label={interpolate(t.materials.ariaDescription, { filename: source.filename })}
      />
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 3 }}>
        <span style={{ marginRight: "auto", minWidth: 0 }}>
          {error ? (
            <span role="alert" style={{ fontSize: "var(--text-supporting-size)", color: "var(--destructive)" }}>
              {error}
            </span>
          ) : shortOfMin ? (
            <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--warning)" }}>
              {interpolate(t.materials.charsShort, { count: minChars - trimmedLength })}
            </span>
          ) : null}
        </span>
        <span
          style={{
            fontSize: "var(--text-supporting-size)",
            color: shortOfMin ? "var(--destructive)" : "var(--muted-foreground)",
            whiteSpace: "nowrap",
          }}
        >
          {trimmedLength} / {maxChars}
          {shortOfMin ? interpolate(t.reportConfig.counterAtLeast, { min: minChars }) : ""}
        </span>
      </div>
    </div>
  );
}

function FileRowMenu({ onRemove }: { onRemove: () => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <span style={{ position: "relative", display: "inline-flex" }}>
      <button
        type="button"
        aria-label={t.materials.moreActions}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((current) => !current)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        style={{ border: 0, background: "transparent", color: "var(--muted-foreground)", fontSize: "var(--text-glyph-size)", cursor: "pointer", padding: "6px", fontFamily: "inherit" }}
      >
        ⋯
      </button>
      {open ? (
        <span
          role="menu"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            minWidth: 130,
            background: "var(--background)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-container)",
            boxShadow: "var(--shadow-overlay)",
            padding: 6,
            zIndex: 30,
          }}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onRemove();
            }}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              border: 0,
              background: "transparent",
              padding: "8px 10px",
              borderRadius: "var(--radius-control)",
              fontSize: "var(--text-label-size)",
              color: "var(--destructive)",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            {t.materials.removeFromReport}
          </button>
        </span>
      ) : null}
    </span>
  );
}

/** 图片识别状态词（§7.1）：只在说明已填、服务端已有识别事实时显示；没有事实不编造进度。 */
function ImageAnalysisStatus({ source }: { source: SourceWithLabel }) {
  const t = useT();
  const status = source.image_analysis?.status;
  if (!status || !source.declaration.description.trim()) return <span />;
  return (
    <span
      style={{
        fontSize: "var(--text-supporting-size)",
        color: status === "failed" ? "var(--foreground-secondary)" : "var(--muted-foreground)",
        paddingTop: 6,
        whiteSpace: "nowrap",
      }}
    >
      {imageAnalysisLabel(status, t)}
    </span>
  );
}

function ExistingFile({
  source,
  intake,
  reportId,
  placeholder,
  showAnalysisStatus,
  onSnapshot,
  onSavingChange,
}: {
  source: SourceWithLabel;
  intake: ReportFileIntake;
  reportId: string;
  placeholder: string;
  showAnalysisStatus: boolean;
  onSnapshot: (next: ReportFileIntake) => void;
  onSavingChange: (delta: number) => void;
}) {
  const t = useT();
  const alive = useAliveRef();
  const [message, setMessage] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const isActive = source.binding_status === "active";
  const isRemoved = source.binding_status === "removed";

  const [conflictNotice, setConflictNotice] = useState(false);
  const handleConflict = () => {
    setConflictNotice(true);
    void fetchReportFileIntake(reportId).then(onSnapshot).catch(() => undefined);
  };

  const remove = () => {
    setConfirmRemove(false);
    void removeReportFile(reportId, source.binding_id)
      .then(onSnapshot)
      .catch((cause: unknown) => {
        console.error("Remove file failed", cause);
        if (alive.current) setMessage(t.materials.errorRemove);
      });
  };

  const restore = () => {
    void restoreReportFile(reportId, source.binding_id)
      .then(onSnapshot)
      .catch((cause: unknown) => {
        console.error("Restore file failed", cause);
        if (alive.current) setMessage(t.materials.errorRestore);
      });
  };

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: rowColumns(showAnalysisStatus),
        gap: 20,
        alignItems: "start",
        padding: "13px 0",
        borderBottom: "1px solid var(--border)",
        opacity: isRemoved ? 0.55 : 1,
      }}
    >
      <FileNameField source={source} reportId={reportId} onSnapshot={onSnapshot} onSavingChange={onSavingChange} />
      <DescriptionField
        source={source}
        intake={intake}
        reportId={reportId}
        placeholder={placeholder}
        onSnapshot={onSnapshot}
        onConflict={handleConflict}
        onSavingChange={onSavingChange}
      />
      {showAnalysisStatus ? <ImageAnalysisStatus source={source} /> : null}
      <div>
        {isActive ? (
          <FileRowMenu onRemove={() => setConfirmRemove(true)} />
        ) : isRemoved ? (
          <button
            type="button"
            onClick={restore}
            style={{ border: 0, background: "transparent", color: "var(--accent)", fontSize: "var(--text-label-size)", cursor: "pointer", padding: "6px", fontFamily: "inherit" }}
          >
            {t.materials.restore}
          </button>
        ) : null}
      </div>
      {conflictNotice ? (
        <p style={{ gridColumn: "1 / -1", margin: 0, fontSize: "var(--text-supporting-size)", color: "var(--warning)" }} role="status">
          {t.materials.descriptionRefreshed}
        </p>
      ) : null}
      {message ? (
        <p role="alert" style={{ gridColumn: "1 / -1", margin: 0, fontSize: "var(--text-supporting-size)", color: "var(--destructive)" }}>
          {message}
        </p>
      ) : null}
      <ConfirmDialog
        open={confirmRemove}
        title={interpolate(t.materials.removeConfirmTitle, { name: source.source_label ?? source.filename })}
        description={t.materials.removeConfirmBody}
        confirmLabel={t.materials.removeFromReport}
        destructive
        onConfirm={remove}
        onCancel={() => setConfirmRemove(false)}
      />
    </div>
  );
}

function UploadProgressBar({ ratio }: { ratio: number }) {
  const t = useT();
  const percent = Math.round(Math.min(1, Math.max(0, ratio)) * 100);
  return (
    <div style={{ display: "grid", gap: 4 }} role="status" aria-label={t.materials.uploadProgress}>
      <div style={{ height: 6, width: "100%", borderRadius: "var(--radius-pill)", background: "var(--surface-sunken)" }}>
        <div
          style={{
            height: 6,
            borderRadius: "var(--radius-pill)",
            background: "var(--accent)",
            width: `${percent}%`,
            transition: "width 0.2s ease",
          }}
        />
      </div>
      <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>{percent}%</span>
    </div>
  );
}

export function FileIntakeRoleSection({
  role,
  intake,
  reportId,
  onSnapshot,
  onSavingChange,
  coachAnchorId,
  showAnalysisStatus = false,
}: {
  role: ReportFileRole;
  intake: ReportFileIntake;
  reportId: string;
  onSnapshot: (next: ReportFileIntake) => void;
  onSavingChange: (delta: number) => void;
  /** 表头问句的 DOM id，供页面级 CoachMarks 锚定；不传则不设 id。 */
  coachAnchorId?: string;
  /** 行尾显示服务端 image_analysis 状态词（design.md §7.3 唯一例外：questions 路径没有处理页）。 */
  showAnalysisStatus?: boolean;
}) {
  const t = useT();
  const copy = ROLE_COPY[role];
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const sources = intake.sources.filter((source) => source.declaration.role === role);
  const activeSources = sources.filter((source) => source.binding_status === "active");
  const missingDescriptionCount = activeSources.filter(
    (source) => !source.declaration.description.trim(),
  ).length;
  const extensions = roleExtensions(intake.policy, role);

  const runUpload = useCallback(async (files: File[]) => {
    if (!files.length) return;
    const defaultTag = fallbackTopicTag(intake.policy);
    if (!defaultTag) {
      setMessage(t.materials.errorNoTags);
      return;
    }
    const { accepted, rejected } = partitionFilesForRole(files, role, intake.policy, t);
    const rejectionText = rejected.map((item) => `${item.file.name}：${item.reason}`).join("；");
    if (!accepted.length) {
      setMessage(rejectionText || t.materials.errorNoFiles);
      return;
    }
    setBusy(true);
    setUploadProgress(0);
    setMessage(null);
    try {
      const declarations: ReportFileDeclarationInput[] = accepted.map(() => ({
        description: "",
        role,
        topic_tags: [defaultTag],
        asset_title: null,
      }));
      const next = await uploadReportFiles(reportId, accepted, declarations, setUploadProgress);
      onSnapshot(next);
      if (rejected.length) setMessage(rejectionText);
    } catch (cause) {
      console.error("File upload failed", cause);
      setMessage(t.materials.errorUpload);
    } finally {
      setBusy(false);
      setUploadProgress(null);
    }
  }, [intake.policy, onSnapshot, reportId, role, t]);

  const handleFilesSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    // 处理开始即清空 input.value；用户重选同一文件也能触发 onChange。
    event.target.value = "";
    await runUpload(files);
  };

  return (
    <section aria-label={copy.title(t)} style={{ display: "grid", gap: 12 }}>
      <style>{fillInHoverFocusCss}</style>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: "var(--text-label-size)", fontWeight: 600, color: "var(--foreground)" }}>
          {copy.title(t)}
        </h2>
        <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
          {interpolate(t.materials.fileCount, { count: activeSources.length })}
        </span>
        {missingDescriptionCount > 0 ? (
          <span style={{ fontSize: "var(--text-supporting-size)", color: "var(--warning)" }}>
            {interpolate(t.materials.missingDescriptionCount, { count: missingDescriptionCount })}
          </span>
        ) : null}
      </div>

      {/* 常驻用途说明：两个上传区的内容进报告的方式不同，若只在空状态里说一次，
          已上传的用户再也看不到。用户凭什么知道证书该放哪个区——这一行就是答案。 */}
      <p
        style={{
          margin: 0,
          fontSize: "var(--text-supporting-size)",
          color: "var(--muted-foreground)",
        }}
      >
        {copy.usageNote(t)}
      </p>

      <input
        ref={inputRef}
        type="file"
        multiple
        aria-label={interpolate(t.materials.ariaChooseFor, { role: copy.title(t) })}
        style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0,0,0,0)" }}
        onChange={(event) => void handleFilesSelected(event)}
      />
      <FileDropZone
        dashed
        disabled={busy}
        onFiles={(files) => void runUpload(files)}
        style={{ padding: 20, textAlign: "center" }}
      >
        <p style={{ margin: "0 0 12px", fontSize: "var(--text-body-size)", fontWeight: 500, color: "var(--foreground)" }}>
          {t.materials.dropHint}
        </p>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          disabledReason={t.materials.uploading}
          onClick={() => {
            if (!busy) inputRef.current?.click();
          }}
        >
          {busy ? t.materials.uploading : t.materials.chooseFile}
        </Button>
        <p style={{ margin: "12px 0 0", fontSize: "var(--text-supporting-size)", color: "var(--muted-foreground)" }}>
          {extensions.join(" / ")}
        </p>
      </FileDropZone>
      {uploadProgress !== null ? <UploadProgressBar ratio={uploadProgress} /> : null}

      {message ? (
        <p role="alert" style={{ margin: 0, fontSize: "var(--text-label-size)", color: "var(--destructive)" }}>
          {message}
        </p>
      ) : null}

      {sources.length ? (
        <div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: rowColumns(showAnalysisStatus),
              gap: 20,
              paddingBottom: 8,
              borderBottom: "1px solid var(--border-strong)",
            }}
          >
            <div style={{ fontSize: "var(--text-supporting-size)", fontWeight: 500, color: "var(--muted-foreground)" }}>
              {t.materials.fileColumn}
            </div>
            <div id={coachAnchorId} style={{ fontSize: "var(--text-supporting-size)", fontWeight: 500, color: "var(--muted-foreground)" }}>
              {copy.headerQuestion(t)}
              <span style={{ fontWeight: 400 }}>
                {interpolate(t.materials.descriptionHint, { min: intake.policy.description_min_chars, max: intake.policy.description_max_chars })}
              </span>
            </div>
            {showAnalysisStatus ? <div /> : null}
            <div />
          </div>
          {sources.map((source) => (
            <ExistingFile
              key={source.binding_id}
              source={source}
              intake={intake}
              reportId={reportId}
              placeholder={copy.placeholder(t)}
              showAnalysisStatus={showAnalysisStatus}
              onSnapshot={onSnapshot}
              onSavingChange={onSavingChange}
            />
          ))}
        </div>
      ) : (
        <EmptyState title={copy.emptyTitle(t)} description={copy.emptyDescription?.(t)} style={{ padding: "20px 0" }} />
      )}
    </section>
  );
}
