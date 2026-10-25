import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
const directory = await mkdtemp(tmpdir() + "/wb-outline-tests-");
const result = await build({ entryPoints: ["src/addons/outline/model.ts"], bundle: true, format: "esm", platform: "node", write: false });
await writeFile(directory + "/model.mjs", result.outputFiles[0].text);
const model = await import(directory + "/model.mjs");

const node = (id, parent, title, content = "", status = "todo") => ({ id, parent, title, content, status, rounds: 1, completed: 0 });
const story = () =>
  model.normalizeOutline({
    nodes: [
      node("c1", null, "第一章", "山村，冬天。"),
      node("a", "c1", "相遇", "两人在雪地里相遇。"),
      node("b", "c1", "争执", "为猎物起了争执。"),
      node("c2", null, "第二章", ""),
      node("c", "c2", "进城", "一起进城卖皮子。"),
    ],
  });

test("only one node is current; older data with several keeps the first", () => {
  const data = model.normalizeOutline({ nodes: [node("a", null, "A", "", "active"), node("b", null, "B", "", "active")] });
  assert.deepEqual(data.nodes.map((n) => n.status), ["active", "todo"]);
  assert.deepEqual(data.settings.inject, { enabled: false, depth: 4 });
});

test("making a node current returns the previous one; finishing moves on to the next unfinished leaf", () => {
  let data = model.advance(story(), "a", "active");
  data = model.advance(data, "b", "active");
  assert.deepEqual(data.nodes.map((n) => n.status), ["todo", "todo", "active", "todo", "todo"]);
  data = model.advance(data, "b", "done");
  assert.equal(data.nodes.find((n) => n.status === "active").id, "c");
  // A skipped node earlier in the story comes back once everything after it is done.
  data = model.advance(data, "c", "done");
  assert.equal(data.nodes.find((n) => n.status === "active").id, "a");
  data = model.advance(data, "a", "done");
  assert.equal(data.nodes.some((n) => n.status === "active"), false);
  data = model.advance(data, "a", "todo");
  assert.equal(data.nodes.find((n) => n.id === "a").status, "todo");
});

test("{{outline}} is the current node under its chapters' background, with the next node's title", () => {
  assert.equal(model.outlineContext(story()), "");
  const text = model.outlineContext(model.advance(story(), "b", "active"));
  assert.equal(text, "背景 · 第一章\n山村，冬天。\n\n当前节点 · 争执\n为猎物起了争执。\n\n下一节点 · 进城");
  assert.equal(model.outlineContext(model.advance(story(), "c", "active")), "当前节点 · 进城\n一起进城卖皮子。");
});

test("reusing another chat's outline keeps the tree and text and clears the progress", () => {
  const used = model.normalizeOutline({
    ...model.advance(model.advance(story(), "a", "done"), "b", "active"),
    settings: { mode: "replace", send: true, inject: { enabled: true, depth: 2 } },
    job: { queue: ["b"], index: 0 },
  });
  const fresh = model.reuseOutline(used);
  assert.deepEqual(fresh.nodes.map((n) => [n.id, n.parent, n.title, n.status, n.completed]), story().nodes.map((n) => [n.id, n.parent, n.title, "todo", 0]));
  assert.equal(fresh.job, undefined);
  assert.deepEqual(fresh.settings.inject, { enabled: false, depth: 4 });
});
