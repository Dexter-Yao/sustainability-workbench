// ABOUTME: 素材图片元数据（题注）在工作台正文的投影上下文——按 asset_id 建映射，SSOT 仍是服务端 file-intake 投影。
// ABOUTME: 懒加载：仅当正文出现素材承载块时才拉取一次；题注改写经既有端点写回并以返回投影刷新映射。
"use client";

import { createContext, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { fetchReportFileIntake, updateLayoutAssetCaption, type ReportFileIntake } from "./material-workspace-api";

export interface LayoutAssetMetadata {
  caption: string | null;
}

interface LayoutAssetMetadataCtx {
  asset: (assetId: string) => LayoutAssetMetadata | undefined;
  /** 正文出现素材承载块时调用；同一报告只发一次 file-intake 请求。 */
  ensureLoaded: () => void;
  updateCaption: (assetId: string, caption: string) => Promise<void>;
}

const Ctx = createContext<LayoutAssetMetadataCtx | null>(null);

/** 从 file-intake 投影提取活跃且识别成功的素材图片元数据；其余绑定不参与正文题注。 */
export function projectLayoutAssetMetadata(intake: ReportFileIntake): Map<string, LayoutAssetMetadata> {
  const map = new Map<string, LayoutAssetMetadata>();
  for (const source of intake.sources) {
    const image = source.image_analysis;
    if (source.binding_status !== "active" || !image || image.status !== "succeeded" || !image.asset_id) continue;
    map.set(image.asset_id, { caption: image.caption ?? null });
  }
  return map;
}

export function LayoutAssetMetadataProvider({
  reportId,
  children,
}: {
  reportId: string | null;
  children: ReactNode;
}) {
  // 映射与其归属报告绑定：切换报告后旧映射即失效，迟到的旧报告响应也不会污染当前投影。
  const [assets, setAssets] = useState<{ reportId: string; map: Map<string, LayoutAssetMetadata> } | null>(null);
  const loadedForReportRef = useRef<string | null>(null);

  const value = useMemo<LayoutAssetMetadataCtx>(() => {
    const applyIntake = (intake: ReportFileIntake) => {
      setAssets({ reportId: intake.report_id, map: projectLayoutAssetMetadata(intake) });
    };
    return {
      asset: (assetId) => (assets && assets.reportId === reportId ? assets.map.get(assetId) : undefined),
      ensureLoaded: () => {
        if (!reportId || loadedForReportRef.current === reportId) return;
        loadedForReportRef.current = reportId;
        fetchReportFileIntake(reportId)
          .then(applyIntake)
          .catch((error) => {
            // 元数据缺席只影响题注，不阻断正文；留痕便于定位而非静默吞错。
            console.error("素材图片元数据加载失败", { reportId, error });
          });
      },
      updateCaption: async (assetId, caption) => {
        if (!reportId) throw new Error("当前报告未关联服务端记录");
        applyIntake(await updateLayoutAssetCaption(reportId, assetId, caption));
      },
    };
  }, [assets, reportId]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** provider 之外（如 intake 只读预览）返回 null，正文按无元数据渲染纯图片。 */
export function useLayoutAssetMetadata(): LayoutAssetMetadataCtx | null {
  return useContext(Ctx);
}
