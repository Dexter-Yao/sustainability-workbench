// ABOUTME: 条件求值跨端 golden 一致性测试（前端侧）——读后端共享 fixture 跑 isVisible，断言 == expected。
// ABOUTME: 与后端 test_conditions_golden.py 消费同一 fixture，两端各自对 golden 成立即防 conditions 双写漂移（H2）。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { intakeExistsKeysFromCondition, isVisible } from "./conditions";
import type { Block, Report } from "./schema";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(join(here, "../../backend/tests/fixtures/conditions_golden.json"), "utf-8"),
) as { cases: { name: string; appears_when: unknown; report: Report; expected: boolean }[] };

describe("conditions golden 一致性（前端 isVisible 镜像后端 _visible）", () => {
  for (const c of fixture.cases) {
    it(c.name, () => {
      const node = { appears_when: c.appears_when } as Block;
      expect(isVisible(node, c.report)).toBe(c.expected);
    });
  }
});

describe("intake 条件依赖提取", () => {
  it("只提取 intakeItems.<key> exists 依赖", () => {
    expect(
      intakeExistsKeysFromCondition({
        all: [
          { path: "intakeItems.climate_scenario_docs", op: "exists" },
          { path: "intakeItems.climate_target_docs", op: "not_exists" },
          { path: "fields.has_goals_table.value", op: "eq", value: "是" },
        ],
        any: [{ path: "intakeItems.certificate_images", op: "exists" }],
      }),
    ).toEqual(["climate_scenario_docs", "certificate_images"]);
  });
});
