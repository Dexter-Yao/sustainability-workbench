// ABOUTME: 素材图片元数据上下文回归——file-intake 投影建映射、懒加载单次请求、题注写回刷新与失败留痕。
// ABOUTME: mock material-workspace-api 边界，provider 与消费组件真实渲染；provider 之外按无元数据降级。
// @vitest-environment happy-dom

import { useEffect } from "react";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchReportFileIntake: vi.fn(),
  updateLayoutAssetCaption: vi.fn(),
}));
vi.mock("@/lib/material-workspace-api", () => api);

import {
  LayoutAssetMetadataProvider,
  projectLayoutAssetMetadata,
  useLayoutAssetMetadata,
} from "./layout-asset-metadata-context";
import type { ReportFileIntake } from "./material-workspace-api";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

type SourceOverrides = {
  binding_status?: string;
  image_analysis?: Record<string, unknown> | null;
};

function intakeSource(assetId: string | null, overrides: SourceOverrides = {}) {
  return {
    binding_status: overrides.binding_status ?? "active",
    image_analysis:
      overrides.image_analysis === null
        ? null
        : {
            status: "succeeded",
            asset_id: assetId,
            caption: "厂区全景",
            category: "photo",
            ...overrides.image_analysis,
          },
  };
}

function intakeProjection(reportId: string, sources: unknown[]): ReportFileIntake {
  return { report_id: reportId, sources } as unknown as ReportFileIntake;
}

function Probe({ assetId }: { assetId: string }) {
  const ctx = useLayoutAssetMetadata();
  useEffect(() => {
    ctx?.ensureLoaded();
  });
  const meta = ctx?.asset(assetId);
  return (
    <div>
      <span data-testid={`caption-${assetId}`}>{meta?.caption ?? "无元数据"}</span>
      <button onClick={() => void ctx?.updateCaption(assetId, "新题注")}>改题注</button>
    </div>
  );
}

describe("projectLayoutAssetMetadata", () => {
  it("仅收录 active 且识别成功且有 asset_id 的素材", () => {
    const map = projectLayoutAssetMetadata(
      intakeProjection("report-1", [
        intakeSource("asset-ok"),
        intakeSource("asset-removed", { binding_status: "removed" }),
        intakeSource("asset-running", { image_analysis: { status: "running" } }),
        intakeSource(null),
        intakeSource(null, { image_analysis: null }),
      ]),
    );
    expect([...map.keys()]).toEqual(["asset-ok"]);
    expect(map.get("asset-ok")).toEqual({ caption: "厂区全景" });
  });

  it("缺省题注落到空题注", () => {
    const map = projectLayoutAssetMetadata(
      intakeProjection("report-1", [intakeSource("asset-min", { image_analysis: { caption: null } })]),
    );
    expect(map.get("asset-min")).toEqual({ caption: null });
  });
});

describe("LayoutAssetMetadataProvider", () => {
  it("多个消费者 ensureLoaded 只发一次 file-intake 请求，映射可查", async () => {
    api.fetchReportFileIntake.mockResolvedValue(intakeProjection("report-1", [intakeSource("asset-a")]));
    render(
      <LayoutAssetMetadataProvider reportId="report-1">
        <Probe assetId="asset-a" />
        <Probe assetId="asset-a" />
      </LayoutAssetMetadataProvider>,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("caption-asset-a").map((node) => node.textContent)).toEqual([
        "厂区全景",
        "厂区全景",
      ]),
    );
    expect(api.fetchReportFileIntake).toHaveBeenCalledTimes(1);
    expect(api.fetchReportFileIntake).toHaveBeenCalledWith("report-1");
  });

  it("updateCaption 调用端点并以返回投影刷新映射", async () => {
    api.fetchReportFileIntake.mockResolvedValue(intakeProjection("report-1", [intakeSource("asset-a")]));
    api.updateLayoutAssetCaption.mockResolvedValue(
      intakeProjection("report-1", [intakeSource("asset-a", { image_analysis: { caption: "新题注" } })]),
    );
    render(
      <LayoutAssetMetadataProvider reportId="report-1">
        <Probe assetId="asset-a" />
      </LayoutAssetMetadataProvider>,
    );
    await screen.findByText("厂区全景");
    fireEvent.click(screen.getByRole("button", { name: "改题注" }));
    await screen.findByText("新题注");
    expect(api.updateLayoutAssetCaption).toHaveBeenCalledWith("report-1", "asset-a", "新题注");
  });

  it("file-intake 加载失败时留痕降级为无元数据，不抛错", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    api.fetchReportFileIntake.mockRejectedValue(new Error("network down"));
    render(
      <LayoutAssetMetadataProvider reportId="report-1">
        <Probe assetId="asset-a" />
      </LayoutAssetMetadataProvider>,
    );
    await waitFor(() => expect(consoleError).toHaveBeenCalled());
    expect(screen.getByTestId("caption-asset-a").textContent).toBe("无元数据");
  });

  it("reportId 为 null 时不发请求", async () => {
    render(
      <LayoutAssetMetadataProvider reportId={null}>
        <Probe assetId="asset-a" />
      </LayoutAssetMetadataProvider>,
    );
    expect(screen.getByTestId("caption-asset-a").textContent).toBe("无元数据");
    expect(api.fetchReportFileIntake).not.toHaveBeenCalled();
  });

  it("provider 之外 useLayoutAssetMetadata 返回 null，消费方按无元数据渲染", () => {
    render(<Probe assetId="asset-a" />);
    expect(screen.getByTestId("caption-asset-a").textContent).toBe("无元数据");
  });
});
