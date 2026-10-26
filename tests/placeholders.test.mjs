import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(
  await readFile(new URL("../src/host/placeholders.ts", import.meta.url), "utf8"),
  {
    loader: "ts",
    format: "esm",
  },
);
const { expandPlaceholders, placeholderInputs, placeholderComplete } = await import(
  "data:text/javascript;base64," + Buffer.from(code).toString("base64")
);

/** Runs one expansion; `answers` is what the dialog returns (null cancels), `asked` records each dialog. */
const run = async (text, { vars = {}, inputOn = true, answers, confirm = true } = {}) => {
  const asked = [],
    toasts = [],
    shown = [];
  const result = await expandPlaceholders(text, {
    vars,
    inputOn,
    ask: async (inputs, current) => {
      asked.push({ inputs, current });
      return answers === undefined ? inputs.map(() => "") : answers;
    },
    toast: (m) => toasts.push(m),
    confirm: async (m) => {
      shown.push(m);
      return confirm;
    },
  });
  return { ...result, asked, toasts, shown };
};

test("plain and defaulted reads", async () => {
  assert.equal((await run("{@女主}好", { vars: { 女主: "林" } })).text, "林好");
  assert.equal((await run("{@女主}好")).text, "好");
  assert.equal((await run("{@女主:女主}", { vars: { 女主: "林" } })).text, "林");
  // Unset or empty falls back to the default, and nothing is stored.
  const unset = await run("{@女主:女主}主导");
  assert.equal(unset.text, "女主主导");
  assert.deepEqual(unset.vars, {});
  assert.equal((await run("{@女主:女主}", { vars: { 女主: "" } })).text, "女主");
  assert.equal((await run("{@黄毛:他人}", { vars: { 黄毛: "王" } })).text, "王");
  // An empty default stays empty.
  assert.equal((await run("[{@x:}]")).text, "[]");
});

test("assignment and deletion expand to nothing", async () => {
  const set = await run("a{@女主=林}b{@女主}");
  assert.equal(set.text, "ab林");
  assert.deepEqual(set.vars, { 女主: "林" });
  const del = await run("{@女主!}{@女主:无}", { vars: { 女主: "林", 男主: "张" } });
  assert.equal(del.text, "无");
  assert.deepEqual(del.vars, { 男主: "张" });
  // Reserved names are never written.
  assert.deepEqual((await run("{@list=1}{@Clear!}")).vars, {});
});

test("indicator 2 (default) asks while the dialog is on", async () => {
  const r = await run("寻找{@寻人:某个人:输入你想寻找的对象}的位置", { answers: ["小明"] });
  assert.equal(r.text, "寻找小明的位置");
  assert.deepEqual(r.vars, { 寻人: "小明" });
  assert.deepEqual(r.asked[0].inputs, [
    { name: "寻人", fallback: "某个人", prompt: "输入你想寻找的对象", mode: 2 },
  ]);
  // Empty input keeps the stored value, then the default.
  assert.equal((await run("{@寻人:某个人:输入}", { vars: { 寻人: "老王" } })).text, "老王");
  const fallback = await run("{@寻人:某个人:输入}");
  assert.equal(fallback.text, "某个人");
  assert.deepEqual(fallback.vars, { 寻人: "某个人" });
});

test("indicator 2 with the dialog off uses the value or stores the default", async () => {
  const off = await run("{@寻人:某个人:输入}", { inputOn: false });
  assert.equal(off.asked.length, 0);
  assert.equal(off.text, "某个人");
  assert.deepEqual(off.vars, { 寻人: "某个人" });
  assert.equal((await run("{@寻人:某个人:输入:2}", { inputOn: false, vars: { 寻人: "甲" } })).text, "甲");
});

test("indicator 1 never asks and expands to nothing", async () => {
  const r = await run("<{@a:默认:提示:1}>", { vars: { a: "x" } });
  assert.equal(r.asked.length, 0);
  assert.equal(r.text, "<>");
  assert.deepEqual(r.vars, { a: "x" });
});

test("indicator -1 always asks, stores and expands to nothing; -2 expands to the value", async () => {
  const silent = await run("<{@男主:男主:请输入男性名称:-1}>", { inputOn: false, answers: ["张三"] });
  assert.equal(silent.asked.length, 1);
  assert.equal(silent.text, "<>");
  assert.deepEqual(silent.vars, { 男主: "张三" });
  const shown = await run("[{@男主:男主:请输入:-2}]", { inputOn: false, answers: [""] });
  assert.equal(shown.text, "[男主]");
  assert.deepEqual(shown.vars, { 男主: "男主" });
});

test("cancelling leaves the text but keeps defaults stored before the dialog", async () => {
  const text = "{@b:乙:提示:2}{@a:甲:提示:-1}";
  const r = await run(text, { inputOn: false, answers: null });
  assert.equal(r.text, text);
  assert.deepEqual(r.vars, { b: "乙" });
});

test("one dialog per name, in order, reserved names skipped", async () => {
  const inputs = placeholderInputs("{@a:1:提示A}{@toast:x:y}{@b:2:提示B:-1}{@a:9:重复}");
  assert.deepEqual(
    inputs.map((x) => [x.name, x.fallback, x.prompt, x.mode]),
    [
      ["a", "1", "提示A", 2],
      ["b", "2", "提示B", -1],
    ],
  );
  // A repeated prompted name expands everywhere with the one answer.
  assert.equal((await run("{@a:1:p}-{@a:1:q}", { answers: ["z"] })).text, "z-z");
  // A reserved name in the prompted form reads its variable (normally empty).
  assert.equal((await run("[{@toast:x:y}]")).text, "[]");
});

test("the super menu's role assignment and later reads", async () => {
  const menu =
    "<{@男主:男主:请输入接下来剧情男性的名称:-1}{@女主:女主:请输入接下来剧情女性的名称:-1}{@黄毛:黄毛:请输入接下来剧情的黄毛名称:-1}{@露出男:男主:请输入露出剧情的男性的名称:-1}{@露出女:女主:请输入接下来露出剧情剧情女性的名称:-1}{@色色男性:男性:请输入接下来剧情男性的名称:-1}{@色色女性:女性:请输入接下来剧情女性的名称:-1}>";
  const set = await run("前文" + menu, { answers: ["张三", "李四", "", "", "", "", "小美"] });
  assert.equal(set.asked[0].inputs.length, 7);
  assert.equal(set.text, "前文<>");
  assert.deepEqual(set.vars, {
    男主: "张三",
    女主: "李四",
    黄毛: "黄毛",
    露出男: "男主",
    露出女: "女主",
    色色男性: "男性",
    色色女性: "小美",
  });
  const later = await run("<{@黄毛:他人}和{@女主:女主}找到机会进行私下接触, 避开{@男主:男主}的视线.>", {
    vars: set.vars,
  });
  assert.equal(later.text, "<黄毛和李四找到机会进行私下接触, 避开张三的视线.>");
  assert.equal(later.asked.length, 0);
  const inject = await run("<切换到{@男主:男主}的控制视角>", { vars: {} });
  assert.equal(inject.text, "<切换到男主的控制视角>");
});

test("whole-text commands", async () => {
  const list = await run(" {@LIST} ", { vars: { a: "1", b: "x".repeat(25) } });
  assert.equal(list.text, "");
  assert.equal(list.toasts[0], `变量(2个):\na: 1\nb: ${"x".repeat(20)}...`);
  assert.equal((await run("{@list}")).toasts[0], "当前角色卡没有变量");
  const clear = await run("{@clear}", { vars: { a: "1" } });
  assert.deepEqual([clear.text, clear.clear, clear.vars], ["", "scope", {}]);
  const reset = await run("{@reset}", { vars: { a: "1" } });
  assert.deepEqual([reset.text, reset.clear, reset.shown.length], ["", "all", 1]);
  const kept = await run("{@reset}", { vars: { a: "1" }, confirm: false });
  assert.deepEqual([kept.text, kept.clear, kept.vars], ["", undefined, { a: "1" }]);
  // Inside other text these are plain (empty) reads.
  assert.equal((await run("x{@list}y")).text, "xy");
});

test("input toggle flips the dialog and expands nothing else", async () => {
  const r = await run("{@input:toggle}{@a:1}", { inputOn: true });
  assert.equal(r.inputOn, false);
  assert.equal(r.text, "{@a:1}");
  assert.equal(r.toasts[0], "输入弹窗已关闭");
  assert.equal((await run("{@INPUT:TOGGLE}", { inputOn: false })).inputOn, true);
});

test("toast and confirm show their text", async () => {
  const r = await run("a{@toast:你好}b{@confirm:确认一下}c");
  assert.equal(r.text, "abc");
  assert.deepEqual(r.toasts, ["你好"]);
  assert.deepEqual(r.shown, ["确认一下"]);
});

test("completeness waits for the closing brace and the caret", () => {
  assert.equal(placeholderComplete("{@女主"), false);
  assert.equal(placeholderComplete("{@女主}"), true);
  assert.equal(placeholderComplete("{@女主} {@男"), false);
  assert.equal(placeholderComplete("{@a}xx", 2), false);
  assert.equal(placeholderComplete("{@a}xx", 4), true);
  assert.equal(placeholderComplete("  {@list}  ", 0), true);
});
