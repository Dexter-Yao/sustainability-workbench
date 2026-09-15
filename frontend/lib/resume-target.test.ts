// ABOUTME: 「继续上次的编制」解析回归：进度绑定账户，换设备与清缓存都能接着上次那一步。
// ABOUTME: 目标步骤取服务端 preparation 自带的 href，浏览器不维护第二份 area→路由映射。
import { beforeEach, describe, expect, it, vi } from "vitest";

const listReports = vi.fn();
const fetchReportPreparation = vi.fn();

vi.mock("./report-store", () => ({
  listReports: (...args: unknown[]) => listReports(...args),
}));

vi.mock("./material-workspace-api", () => ({
  fetchReportPreparation: (...args: unknown[]) => fetchReportPreparation(...args),
}));

import { resolveResumeTarget, resumeHrefFrom } from "./resume-target";

function report(id: string, updatedAt: string, status = "active") {
  return { id, status, updated_at: updatedAt };
}

function preparation(areas: Array<{ status: string; href: string }>, blockers: Array<{ href: string }> = []) {
  return { areas, generation_blockers: blockers };
}

describe("resumeHrefFrom", () => {
  it("落到第一个待填写的步骤", () => {
    expect(
      resumeHrefFrom(
        preparation([
          { status: "ready", href: "/intake/info" },
          { status: "needs_input", href: "/intake/metrics" },
        ]) as never,
      ),
    ).toBe("/intake/metrics");
  });

  it("没有待填写时按阻断项定位", () => {
    expect(
      resumeHrefFrom(
        preparation([{ status: "ready", href: "/intake/info" }], [{ href: "/materials" }]) as never,
      ),
    ).toBe("/materials");
  });

  it("既无待填写也无阻断项时落到末步，末步由填报方式决定", () => {
    // materials area 无条件产出且恒在 areas 末位（已上传资料在直答路径下仍参与生成），
    // 因此不能按「最后一个 area」推末步——那会把 questions 路径的用户送到
    // 一个不在其步骤序列里的 /materials。
    const areas = [
      { status: "ready", href: "/intake/info" },
      { status: "ready", href: "/intake/questions" },
      { status: "optional_empty", href: "/materials" },
    ];
    expect(
      resumeHrefFrom({ ...(preparation(areas) as object), primary_input_mode: "questions" } as never),
    ).toBe("/intake/questions");
    expect(
      resumeHrefFrom({ ...(preparation(areas) as object), primary_input_mode: "materials" } as never),
    ).toBe("/materials/processing");
    // 尚未二选一：落到填报方式 gateway，这正是用户该做的下一件事。
    expect(
      resumeHrefFrom({ ...(preparation(areas) as object), primary_input_mode: null } as never),
    ).toBe("/intake/input-path");
  });

  it("准备状态缺失时落到第一步，不猜", () => {
    expect(resumeHrefFrom(null)).toBe("/intake/info");
  });
});

describe("resolveResumeTarget", () => {
  beforeEach(() => {
    listReports.mockReset();
    fetchReportPreparation.mockReset();
    fetchReportPreparation.mockResolvedValue(
      preparation([{ status: "needs_input", href: "/intake/metrics" }]),
    );
  });

  it("本机没有指针时按最近编辑的报告继续——换设备的核心场景", async () => {
    // 进度属于账户：新设备上 localStorage 为空，但服务端的 updated_at 是权威事实。
    listReports.mockResolvedValue([
      report("old", "2026-08-01T00:00:00Z"),
      report("recent", "2026-08-19T00:00:00Z"),
    ]);

    expect(await resolveResumeTarget(null)).toEqual({
      reportId: "recent",
      href: "/intake/metrics",
    });
  });

  it("本机指针有效时优先采用，同设备连续操作不受影响", async () => {
    listReports.mockResolvedValue([
      report("old", "2026-08-01T00:00:00Z"),
      report("recent", "2026-08-19T00:00:00Z"),
    ]);

    expect(await resolveResumeTarget("old")).toMatchObject({ reportId: "old" });
  });

  it("指针指向已删除的报告时回退到最近编辑的那份，不把用户带去死链", async () => {
    listReports.mockResolvedValue([
      report("gone", "2026-08-19T00:00:00Z", "archived"),
      report("alive", "2026-08-10T00:00:00Z"),
    ]);

    expect(await resolveResumeTarget("gone")).toMatchObject({ reportId: "alive" });
  });

  it("没有活跃报告时返回 null，由调用方去报告列表", async () => {
    listReports.mockResolvedValue([report("archived-only", "2026-08-19T00:00:00Z", "archived")]);

    expect(await resolveResumeTarget(null)).toBeNull();
  });

  it("准备状态取不到不阻断继续：报告确定，落到第一步", async () => {
    listReports.mockResolvedValue([report("r1", "2026-08-19T00:00:00Z")]);
    fetchReportPreparation.mockRejectedValue(new Error("network down"));

    expect(await resolveResumeTarget(null)).toEqual({ reportId: "r1", href: "/intake/info" });
  });

  it("列表取不到时返回 null，不猜一个报告", async () => {
    listReports.mockRejectedValue(new Error("network down"));

    expect(await resolveResumeTarget("whatever")).toBeNull();
  });
});
