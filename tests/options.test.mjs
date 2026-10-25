import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(await readFile(new URL("../src/host/options.ts", import.meta.url), "utf8"), {
  loader: "ts",
  format: "esm",
});
const {
  parseOptions,
  stripOptions,
  stripHistory,
  tableOptions,
  readOptionsConfig,
  storedOptionsConfig,
  optionText,
  DEFAULT_OPTIONS_PROMPT,
} = await import(
  "data:text/javascript;base64," + Buffer.from(code).toString("base64")
);

const reply = [
  "雪停了。",
  "<options>",
  '<option title="追上去">踩着脚印追进林子，&quot;天黑前&quot;要找到他。</option>',
  "<option title='回村'>先回村里报信。</option>",
  "<option>原地生火，等他回来</option>",
  "</options>",
].join("\n");

test("a reply's last complete block gives its options; a bare option is its own title", () => {
  assert.deepEqual(parseOptions(reply), [
    { title: "追上去", detail: '踩着脚印追进林子，"天黑前"要找到他。' },
    { title: "回村", detail: "先回村里报信。" },
    { title: "原地生火，等他回来", detail: "" },
  ]);
  assert.deepEqual(parseOptions('<options><option title="旧">x</option></options>正文<options><option title="新">y</option></options>'), [
    { title: "新", detail: "y" },
  ]);
  assert.deepEqual(parseOptions("没有选项。"), []);
  assert.deepEqual(parseOptions('<options><option title="未完">还在写'), []);
});

test("a reader never sees a block, nor one still streaming, nor its opening tag half written", () => {
  assert.equal(stripOptions(reply), "雪停了。");
  assert.equal(stripOptions('雪停了。\n<options><option title="追'), "雪停了。");
  assert.equal(stripOptions("雪停了。\n<opt"), "雪停了。");
  assert.equal(stripOptions("a < b，雪停了。"), "a < b，雪停了。");
  assert.equal(stripOptions("没有选项。\n"), "没有选项。\n");
});

test("earlier replies' blocks leave the prompt; the instruction's example at the end stays", () => {
  const prompt = `${reply}\n用户：好\n${DEFAULT_OPTIONS_PROMPT}`;
  const out = stripHistory(prompt, true);
  assert.equal(out.includes("追上去"), false);
  assert.equal(out.endsWith(DEFAULT_OPTIONS_PROMPT), true);
  assert.equal(stripHistory(reply, false).includes("<options>"), false);
  assert.equal(stripHistory("无", true), "无");
});

test("a bound table becomes options: one row column by column, several rows row by row", () => {
  const row = (id, ...cells) => ({ id: String(id), index: id + 1, cells });
  const one = { columns: ["选项一", "选项二", "选项三", "选项四"], rows: [row(0, "追上去", "回村", "", "生火")] };
  assert.deepEqual(tableOptions(one), [
    { title: "追上去", detail: "" },
    { title: "回村", detail: "" },
    { title: "生火", detail: "" },
  ]);
  const many = {
    columns: ["行动", "后果", "代价"],
    rows: [row(0, "追上去", "找到他", "天黑"), row(1, "回村", "", "错过"), row(2, "", "", "")],
  };
  assert.deepEqual(tableOptions(many), [
    { title: "追上去", detail: "后果：找到他\n代价：天黑" },
    { title: "回村", detail: "代价：错过" },
  ]);
  assert.deepEqual(tableOptions({ columns: [], rows: [] }), []);
});

test("choosing fills the input in Noval and sends in RP unless the chat says otherwise", () => {
  const defaults = { source: "off", table: "", novel: "fill", rp: "send" };
  assert.deepEqual(readOptionsConfig(undefined), defaults);
  // A chat saved before the actions existed keeps its source and gets the defaults.
  assert.deepEqual(readOptionsConfig({ source: "db", table: "选项表" }), { ...defaults, source: "db", table: "选项表" });
  assert.deepEqual(readOptionsConfig({ source: "model", novel: "send", rp: "fill" }), {
    ...defaults,
    source: "model",
    novel: "send",
    rp: "fill",
  });
  assert.deepEqual(readOptionsConfig({ source: "x", table: 3, novel: "go", rp: null }), defaults);
});

test("a chat stores its config only while something differs from the defaults", () => {
  assert.equal(storedOptionsConfig({ source: "off", table: "" }), undefined);
  assert.equal(storedOptionsConfig({ source: "off", table: "", novel: "fill", rp: "send" }), undefined);
  assert.deepEqual(storedOptionsConfig({ source: "off", rp: "fill" }), { source: "off", table: "", novel: "fill", rp: "fill" });
  assert.deepEqual(storedOptionsConfig({ source: "model", table: "" }), { source: "model", table: "", novel: "fill", rp: "send" });
});

test("an option puts its detail in the input, or its title when it has none", () => {
  assert.equal(optionText({ title: "追上去", detail: "踩着脚印追进林子。" }), "踩着脚印追进林子。");
  assert.equal(optionText({ title: "原地生火", detail: "" }), "原地生火");
});
