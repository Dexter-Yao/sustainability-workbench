// ABOUTME: 整节重写客户端测试——请求形态、幂等意图复用与失败不静默。
// ABOUTME: 不触真实后端；只校验请求体、URL 与响应必经同源合同解析。
import { afterEach, describe, expect, it, vi } from "vitest";

import { regenerateSection, sectionRewriteIntent } from "./section-generation-api";
import type { Report } from "./schema";

// 与 report-generation-api.test.ts 同法：绕开运行时认证配置拉取，
// 否则 fetch 桩会被 accessToken() 的 client-config 请求先消费掉。
vi.mock("./supabase", () => ({ accessToken: async () => "test-token" }));

const reportId = "11111111-1111-4111-8111-111111111111";
const report = {
  knowledgePackageId: "sse_zh_hans",
  title: "t",
  fields: {},
  sections: [],
} as unknown as Report;

function response() {
  return {
    batch_id: "22222222-2222-4222-8222-222222222222",
    mode: "regeneration",
    replayed: false,
    state_seq: 3,
    results: [{ block_id: "sm.strategy", text: "新正文" }],
    section_titles: {},
    input_fingerprint: "a".repeat(64),
    freshness: "fresh",
    company_business_summary: null,
    allowance: { quota: 10, used: 1, reserved: 0, remaining: 9 },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("整节重写客户端", () => {
  it("按章节 key 发起重写，请求体带 report、base_state_seq 与幂等键", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await regenerateSection(
      reportId,
      "sm.strategy",
      report,
      3,
      "33333333-3333-4333-8333-333333333333",
    );

    expect(result.allowance.remaining).toBe(9);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/api/reports/${reportId}/sections/sm.strategy/generations`);
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.base_state_seq).toBe(3);
    expect(body.idempotency_key).toBe("33333333-3333-4333-8333-333333333333");
    expect(body.report).toBeTruthy();
  });

  it("章节 key 含特殊字符时正确转义，不拼出错误路径", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(response()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await regenerateSection(reportId, "section/with slash", report, 3, "k");

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("section%2Fwith%20slash");
  });

  it("服务端拒绝时抛出，不静默当成功", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "该页面包含按资料出具的内容" }), {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      regenerateSection(reportId, "sm.strategy", report, 3, "k"),
    ).rejects.toBeTruthy();
  });

  it("同章节同 state_seq 重试复用幂等键，输入版本变化才换新键", () => {
    const createKey = vi
      .fn()
      .mockReturnValueOnce("key-1")
      .mockReturnValueOnce("key-2");

    const first = sectionRewriteIntent(null, reportId, "sm.strategy", 3, createKey);
    const retry = sectionRewriteIntent(first, reportId, "sm.strategy", 3, createKey);
    const nextSeq = sectionRewriteIntent(first, reportId, "sm.strategy", 4, createKey);

    expect(retry).toBe(first);
    expect(nextSeq.idempotencyKey).toBe("key-2");
    expect(createKey).toHaveBeenCalledTimes(2);
  });

  it("换章节必须换幂等键——否则服务端会判同一键用于其他输入", () => {
    const createKey = vi
      .fn()
      .mockReturnValueOnce("key-1")
      .mockReturnValueOnce("key-2");

    const first = sectionRewriteIntent(null, reportId, "sm.strategy", 3, createKey);
    const otherSection = sectionRewriteIntent(first, reportId, "waste_management", 3, createKey);

    expect(otherSection.idempotencyKey).toBe("key-2");
    expect(otherSection.sectionKey).toBe("waste_management");
  });
});
