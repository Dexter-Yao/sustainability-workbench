// ABOUTME: 字典完备性与纯净度守护：英文字典不得残留中文，key 结构必须与基准一致。
// ABOUTME: key 缺失由 tsc 拦下；本测试给出更好的失败信息，并守住 tsc 看不见的「英文里粘了中文」。
import { describe, expect, it } from "vitest";

import { interpolate } from "./dictionary";
import { en } from "./en";
import { zhHans } from "./zh-Hans";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out[path] = value;
    else Object.assign(out, flatten(value, path));
  }
  return out;
}

const HAN = /\p{Script=Han}/u;

/** 中文字面量在英文字典里合法的 key：语言切换项按各自语言自称，不翻译。 */
const ALLOWED_HAN_KEYS = new Set(["common.languageSimplifiedChinese"]);

describe("界面文案字典", () => {
  const baseline = flatten(zhHans as unknown as Tree);
  const english = flatten(en as unknown as Tree);

  it("英文字典与基准字典 key 集合全等", () => {
    expect(Object.keys(english).sort()).toEqual(Object.keys(baseline).sort());
  });

  it("英文字典不残留中文", () => {
    const leaks = Object.entries(english)
      .filter(([key, value]) => !ALLOWED_HAN_KEYS.has(key) && HAN.test(value))
      .map(([key, value]) => `${key}: ${value}`);
    expect(leaks).toEqual([]);
  });

  it("两侧文案都非空", () => {
    for (const [key, value] of Object.entries(baseline)) {
      expect(value.trim(), `zh-Hans.${key}`).not.toBe("");
      expect(english[key].trim(), `en.${key}`).not.toBe("");
    }
  });

  it("插值占位在两种语言里成对出现", () => {
    // 一侧漏掉 {date} 会让界面少一段事实，而不是仅仅措辞不同。
    const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of Object.keys(baseline)) {
      expect(placeholders(english[key]), key).toEqual(placeholders(baseline[key]));
    }
  });
});

describe("interpolate", () => {
  it("按名替换占位", () => {
    expect(interpolate("有效至 {date}", { date: "2026/9/7" })).toBe("有效至 2026/9/7");
  });

  it("未提供的占位原样保留，不静默变成空串", () => {
    expect(interpolate("{a} 与 {b}", { a: "甲" })).toBe("甲 与 {b}");
  });
});
