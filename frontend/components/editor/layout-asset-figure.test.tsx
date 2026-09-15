// ABOUTME: 素材图片承载块投影回归——取图缓存去重、失败占位、题注只读/可编辑三态与保存失败可见化。
// ABOUTME: mock 认证与 fetch 边界，组件本体真实渲染；happy-dom 提供 URL.createObjectURL/revokeObjectURL。
// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ accessToken: vi.fn().mockResolvedValue("access-token") }));

import { LayoutAssetFigure } from "./layout-asset-figure";

/** 题注前缀「图　」与文本分属独立 JSX 子节点，findByText 需按拼接后全文匹配且只认最底层容器。 */
function findByCaptionText(text: string) {
  return screen.findByText((_content, node) => {
    if (node?.textContent !== text) return false;
    return Array.from(node.children).every((child) => child.textContent !== text);
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function pngResponse(): Response {
  return new Response(new Blob(["fake-png-bytes"], { type: "image/png" }), { status: 200 });
}

describe("LayoutAssetFigure", () => {
  it("加载成功后渲染图片（blob URL）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(pngResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(<LayoutAssetFigure assetId="asset-1" reportId="report-1" />);

    const img = await screen.findByRole("img");
    expect(img.getAttribute("src")).toMatch(/^blob:/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/reports/report-1/layout-assets/asset-1/image");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer access-token");
  });

  it("同一资产多处渲染只发一次请求（模块级缓存命中）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(pngResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(<LayoutAssetFigure assetId="asset-shared" reportId="report-1" />);
    await screen.findAllByRole("img");
    cleanup();

    render(<LayoutAssetFigure assetId="asset-shared" reportId="report-1" />);
    await screen.findAllByRole("img");

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("取图失败落占位并提示图片暂不可用", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<LayoutAssetFigure assetId="asset-missing" reportId="report-1" />);

    expect(await screen.findByText("图片暂不可用")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("有 caption 时渲染题注前缀", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(pngResponse()));

    render(<LayoutAssetFigure assetId="asset-caption" reportId="report-1" caption="厂区全景" />);

    expect(await findByCaptionText("图　厂区全景")).toBeTruthy();
  });

  describe("题注可编辑（onCaptionChange）", () => {
    beforeEach(() => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(pngResponse()));
    });

    it("blur 且值变化时回调新题注", async () => {
      const onCaptionChange = vi.fn();
      render(
        <LayoutAssetFigure
          assetId="asset-edit"
          reportId="report-1"
          caption="原题注"
          onCaptionChange={onCaptionChange}
        />,
      );
      const captionRow = await findByCaptionText("图　原题注");
      fireEvent.click(captionRow);
      const input = screen.getByDisplayValue("原题注") as HTMLInputElement;
      fireEvent.change(input, { target: { value: "新题注" } });
      fireEvent.blur(input);

      await waitFor(() => expect(onCaptionChange).toHaveBeenCalledWith("新题注"));
    });

    it("blur 但值未变化时不回调", async () => {
      const onCaptionChange = vi.fn();
      render(
        <LayoutAssetFigure
          assetId="asset-noop"
          reportId="report-1"
          caption="原题注"
          onCaptionChange={onCaptionChange}
        />,
      );
      const captionRow = await findByCaptionText("图　原题注");
      fireEvent.click(captionRow);
      const input = screen.getByDisplayValue("原题注") as HTMLInputElement;
      fireEvent.blur(input);

      expect(onCaptionChange).not.toHaveBeenCalled();
    });

    it("保存失败时展示错误并保留草稿供重试", async () => {
      const onCaptionChange = vi.fn().mockRejectedValue(new Error("boom"));
      render(
        <LayoutAssetFigure
          assetId="asset-save-fail"
          reportId="report-1"
          caption="原题注"
          onCaptionChange={onCaptionChange}
        />,
      );
      const captionRow = await findByCaptionText("图　原题注");
      fireEvent.click(captionRow);
      const input = screen.getByDisplayValue("原题注") as HTMLInputElement;
      fireEvent.change(input, { target: { value: "新题注" } });
      fireEvent.blur(input);

      const alert = await screen.findByRole("alert");
      expect(alert.textContent).toContain("题注保存失败");
      expect(screen.getByDisplayValue("新题注")).toBeTruthy();
    });

    it("清空后 blur 不回调并恢复原题注（后端题注不允许为空）", async () => {
      const onCaptionChange = vi.fn();
      render(
        <LayoutAssetFigure
          assetId="asset-empty"
          reportId="report-1"
          caption="原题注"
          onCaptionChange={onCaptionChange}
        />,
      );
      const captionRow = await findByCaptionText("图　原题注");
      fireEvent.click(captionRow);
      const input = screen.getByDisplayValue("原题注") as HTMLInputElement;
      fireEvent.change(input, { target: { value: "   " } });
      fireEvent.blur(input);

      expect(await findByCaptionText("图　原题注")).toBeTruthy();
      expect(onCaptionChange).not.toHaveBeenCalled();
    });

    it("Escape 取消编辑并恢复原值，不回调", async () => {
      const onCaptionChange = vi.fn();
      render(
        <LayoutAssetFigure
          assetId="asset-escape"
          reportId="report-1"
          caption="原题注"
          onCaptionChange={onCaptionChange}
        />,
      );
      const captionRow = await findByCaptionText("图　原题注");
      fireEvent.click(captionRow);
      const input = screen.getByDisplayValue("原题注") as HTMLInputElement;
      fireEvent.change(input, { target: { value: "改到一半" } });
      fireEvent.keyDown(input, { key: "Escape" });

      expect(await findByCaptionText("图　原题注")).toBeTruthy();
      expect(onCaptionChange).not.toHaveBeenCalled();
    });
  });
});
