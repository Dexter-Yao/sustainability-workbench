// ABOUTME: 块级编辑动作测试：未变更不产动作、提交写回 Report 并置 ready、撤销恢复原文、重做重放。
import { describe, expect, it } from "vitest";

import {
  applyBlockTextEdit,
  blockTextEdit,
  commitEdit,
  editedBlockIdsFromLog,
  EMPTY_EDIT_LOG,
  inlineText,
  redoEdit,
  revertBlockTextEdit,
  undoEdit,
} from "./block-edits";
import type { Report } from "./schema";

const report: Report = {
  title: "t",
  fields: {},
  intakeItems: [],
  sections: [
    {
      key: "climate",
      title: "气候",
      headingLevel: 2,
      blocks: [
        {
          id: "climate.body",
          type: "paragraph",
          blockType: "generative",
          source: "ai",
          state: "ready",
          content: [{ kind: "text", text: "旧正文" }],
        },
      ],
    },
  ],
};

describe("block edits", () => {
  it("does not create an edit when the text is unchanged or the block is unknown", () => {
    expect(blockTextEdit(report, "climate.body", "旧正文")).toBeNull();
    expect(blockTextEdit(report, "missing", "x")).toBeNull();
  });

  it("commit applies the edit to the Report and marks the block ready; undo restores the original", () => {
    const edit = blockTextEdit(report, "climate.body", "新正文")!;
    const edited = applyBlockTextEdit(report, edit);
    expect(inlineText(edited.sections[0].blocks[0].content)).toBe("新正文");
    expect(edited.sections[0].blocks[0].state).toBe("ready");

    const log = commitEdit(EMPTY_EDIT_LOG, edit);
    const undone = undoEdit(log)!;
    expect(inlineText(revertBlockTextEdit(edited, undone.edit).sections[0].blocks[0].content)).toBe("旧正文");
    expect(undone.log).toEqual({ past: [], future: [edit] });

    const redone = redoEdit(undone.log)!;
    expect(redone.log).toEqual({ past: [edit], future: [] });
    expect(undoEdit(EMPTY_EDIT_LOG)).toBeNull();
    expect(redoEdit(EMPTY_EDIT_LOG)).toBeNull();
  });

  it("a new commit discards the redo stack and edited ids follow the past", () => {
    const first = blockTextEdit(report, "climate.body", "一")!;
    const second = { ...first, before: first.after, after: [{ kind: "text" as const, text: "二" }] };
    const log = commitEdit(undoEdit(commitEdit(commitEdit(EMPTY_EDIT_LOG, first), second))!.log, second);
    expect(log.future).toEqual([]);
    expect([...editedBlockIdsFromLog(log)]).toEqual(["climate.body"]);
  });
});
