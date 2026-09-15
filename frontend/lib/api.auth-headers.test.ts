// ABOUTME: 受保护端点调用回归——要求登录的端点必须携带访问令牌。
// ABOUTME: prompt-config 要求登录，其唯一调用方若漏加 header，401 会阻断建报后的首页。
// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";

const accessToken = vi.fn();

vi.mock("./supabase", () => ({
  accessToken: () => accessToken(),
}));

import { fetchPromptConfig } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  accessToken.mockReset();
});

describe("fetchPromptConfig", () => {
  it("携带访问令牌调用受保护端点", async () => {
    accessToken.mockResolvedValue("token-abc");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ blocks: [], user_visible_disclosure_clause_annotations: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await fetchPromptConfig();

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/prompt-config");
    // 端点要求登录：没有 Authorization 就是线上那次 401。
    expect((init?.headers as Record<string, string>)?.Authorization).toBe("Bearer token-abc");
  });

  it("没有令牌时给出可行动的中文提示，不放任 401 冒充服务故障", async () => {
    accessToken.mockResolvedValue(null);
    vi.stubGlobal("fetch", vi.fn());

    await expect(fetchPromptConfig()).rejects.toThrow(/登录状态已失效/);
  });
});
