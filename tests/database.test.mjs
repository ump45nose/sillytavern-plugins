import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
const { code } = await transform(await readFile(new URL("../src/host/database.ts", import.meta.url), "utf8"), {
  loader: "ts",
  format: "esm",
});
const { readTables, rowLabel, matchRows, lockOf, lockCount, rowLocked, changedCells, wideColumns } = await import(
  "data:text/javascript;base64," + Buffer.from(code).toString("base64")
);

const exported = {
  mate: { type: "chatSheets", version: 1 },
  sheet_b: {
    name: "人物",
    orderNo: 1,
    sourceData: { note: "  出场人物与现状  " },
    content: [
      [null, "姓名", "身份", "备注"],
      [7, "林晚", "图书管理员", null],
      ["8", "", "邮差", 3],
    ],
  },
  sheet_a: { name: "全局", orderNo: 0, content: [[null, "时间", "地点"], [1, "黄昏", "灯塔"]] },
  sheet_c: { name: "无序", content: [[null]] },
  broken: { name: "不是表", content: [] },
};

test("an export reads as ordered tables without the row_id column, cells as text", () => {
  const tables = readTables(exported, (key) => (key === "sheet_b" ? { rows: [1], cols: [2], cells: ["0:1", 4] } : null));
  assert.deepEqual(tables.map((t) => t.name), ["全局", "人物", "无序"]);
  const people = tables[1];
  assert.equal(people.key, "sheet_b");
  assert.equal(people.note, "出场人物与现状");
  assert.deepEqual(people.columns, ["姓名", "身份", "备注"]);
  assert.deepEqual(people.rows, [
    { id: "7", index: 1, cells: ["林晚", "图书管理员", ""] },
    { id: "8", index: 2, cells: ["", "邮差", "3"] },
  ]);
  assert.deepEqual(people.locks, { rows: [1], cols: [2], cells: ["0:1", "4"] });
  assert.deepEqual(tables[2].columns, []);
  assert.deepEqual(readTables(null), []);
});

test("a row is titled by its first filled cell and summarised by the second", () => {
  const [, people] = readTables(exported);
  assert.deepEqual(rowLabel(people.rows[0]), { title: "林晚", summary: "图书管理员" });
  assert.deepEqual(rowLabel(people.rows[1]), { title: "邮差", summary: "3" });
});

test("rows filter on any cell, ignoring case", () => {
  const [, people] = readTables(exported);
  assert.equal(matchRows(people, "邮").length, 1);
  assert.equal(matchRows(people, "  ").length, 2);
  assert.equal(matchRows(people, "无").length, 0);
});

test("locks resolve row over column over cell, by 0-based data positions", () => {
  const [, people] = readTables(exported, () => ({ rows: [1], cols: [2], cells: ["0:1"] }));
  const [first, second] = people.rows;
  assert.equal(lockOf(people, first, 0), null);
  assert.equal(lockOf(people, first, 1), "cell");
  assert.equal(lockOf(people, first, 2), "col");
  assert.equal(lockOf(people, second, 0), "row");
  assert.equal(lockOf(people, null, 2), "col");
  assert.equal(lockCount(people), 3);
  assert.equal(rowLocked(people, first), true);
  assert.equal(rowLocked(readTables(exported)[1], first), false);
});

test("only changed columns are written", () => {
  assert.deepEqual(changedCells(["姓名", "身份", "备注"], ["林晚", "图书管理员", ""], ["林晚", "馆长", "新"]), {
    身份: "馆长",
    备注: "新",
  });
  assert.deepEqual(changedCells(["姓名"], ["a"], ["a"]), {});
});

test("long-text columns are wide", () => {
  const table = readTables({ sheet_x: { name: "纪要", content: [[null, "时间", "概要"], [1, "第一天", "很长".repeat(20)]] } })[0];
  assert.deepEqual(wideColumns(table), [false, true]);
});
