import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";

const { outputFiles } = await build({
  entryPoints: [new URL("../src/ui/md/commands.ts", import.meta.url).pathname],
  bundle: true,
  format: "esm",
  write: false,
});
const { continueItem, inItem, pair, toggleWrap, pasteLink, indentItem } = await import(
  "data:text/javascript;base64," + Buffer.from(outputFiles[0].text).toString("base64")
);

test("Enter continues bullets, quotes and tasks with the same marker and gap", () => {
  assert.deepEqual(continueItem("- 雨夜"), { insert: "\n- " });
  assert.deepEqual(continueItem("  * 子项"), { insert: "\n  * " });
  assert.deepEqual(continueItem("> 引用"), { insert: "\n> " });
  assert.deepEqual(continueItem(">> 二级"), { insert: "\n>> " });
  assert.deepEqual(continueItem("- [x] 已完成"), { insert: "\n- [ ] " });
  assert.deepEqual(continueItem("+   宽间距"), { insert: "\n+   " });
});

test("numbered items count up and keep their delimiter", () => {
  assert.deepEqual(continueItem("1. 第一"), { insert: "\n2. " });
  assert.deepEqual(continueItem("9) 九"), { insert: "\n10) " });
  assert.deepEqual(continueItem("3. [ ] 任务"), { insert: "\n4. [ ] " });
});

test("Enter on an empty item ends the list, or steps a nested item out one level", () => {
  assert.deepEqual(continueItem("- "), { replaceLine: "" });
  assert.deepEqual(continueItem("2. "), { replaceLine: "" });
  assert.deepEqual(continueItem("> "), { replaceLine: "" });
  assert.deepEqual(continueItem("    - "), { replaceLine: "  " });
  assert.deepEqual(continueItem("\t- "), { replaceLine: "" });
  // A nested quote has no indent level to step out of.
  assert.deepEqual(continueItem("  > "), { replaceLine: "" });
});

test("ordinary lines are not items", () => {
  for (const line of ["正文", "-没有空格", "**粗体**", "2026.10 年", "#标题", ""]) {
    assert.equal(continueItem(line), null, line);
    assert.equal(inItem(line), false, line);
  }
  assert.equal(inItem("- 项"), true);
});

test("pairs close themselves, Chinese quotes and brackets included", () => {
  assert.deepEqual(pair("「", ""), { text: "「」", caret: 1 });
  assert.deepEqual(pair("“", ""), { text: "“”", caret: 1 });
  assert.deepEqual(pair("（", ""), { text: "（）", caret: 1 });
  assert.deepEqual(pair("【", "选中"), { text: "【选中】", caret: 4 });
  assert.deepEqual(pair("`", ""), { text: "``", caret: 1 });
  assert.equal(pair("a", ""), null);
});

test("emphasis marks only wrap a selection", () => {
  assert.equal(pair("*", ""), null);
  assert.equal(pair("_", ""), null);
  assert.deepEqual(pair("*", "重"), { text: "*重*", caret: 3 });
  assert.deepEqual(pair("~", "删"), { text: "~删~", caret: 3 });
});

test("wrap shortcuts toggle", () => {
  assert.equal(toggleWrap("词", "**"), "**词**");
  assert.equal(toggleWrap("**词**", "**"), "词");
  assert.equal(toggleWrap("", "`"), "``");
  // Too short to be wrapped already: wrap it.
  assert.equal(toggleWrap("**", "**"), "******");
});

test("a URL pasted over single-line text makes a link; anything else pastes as is", () => {
  assert.equal(pasteLink("灯塔", "https://example.com/a?b=1"), "[灯塔](https://example.com/a?b=1)");
  assert.equal(pasteLink("灯塔", "  www.example.com  "), "[灯塔](www.example.com)");
  assert.equal(pasteLink("", "https://example.com"), null);
  assert.equal(pasteLink("两\n行", "https://example.com"), null);
  assert.equal(pasteLink("灯塔", "不是链接 https://example.com"), null);
});

test("Tab and Shift+Tab indent list lines only", () => {
  assert.equal(indentItem("- 项", false), "  - 项");
  assert.equal(indentItem("    - 项", true), "  - 项");
  assert.equal(indentItem(" - 项", true), "- 项");
  assert.equal(indentItem("\t- 项", true), "- 项");
  assert.equal(indentItem("正文", false), null);
});
