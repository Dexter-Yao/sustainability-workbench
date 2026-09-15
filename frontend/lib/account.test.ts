// ABOUTME: 产品账户 API 合同测试：当前账户读取与引导已读写入的传输失败与鉴权头。
// ABOUTME: 浏览器只带 bearer token 调后端；不从 Auth metadata 推断权益。
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./supabase", () => ({ accessToken: vi.fn(async () => "token-1") }));

import { fetchCurrentAccount, putOnboardingSeen } from "./account";

describe("account api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("maps transport failures to a stable account-domain message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(fetchCurrentAccount()).rejects.toThrow("无法连接账户服务，请检查网络后重试");
  });

  it("sends the bearer token and the full onboarding step set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ onboarding_seen: ["a", "b"] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(putOnboardingSeen(["b", "a"])).resolves.toEqual(["a", "b"]);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("PUT");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer token-1");
    expect(init.body).toBe(JSON.stringify({ steps: ["b", "a"] }));
  });
});
