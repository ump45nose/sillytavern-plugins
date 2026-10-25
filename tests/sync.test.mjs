import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";

const directory = await mkdtemp(tmpdir() + "/wb-sync-tests-");
// yaml resolves to CommonJS on node; the ESM bundle gives it a require.
const result = await build({
  entryPoints: ["src/sync/index.ts"],
  bundle: true,
  format: "esm",
  platform: "node",
  write: false,
  banner: {
    js: 'import { createRequire } from "node:module"; const require = createRequire(import.meta.url);',
  },
});
await writeFile(directory + "/sync.mjs", result.outputFiles[0].text);
const sync = await import(directory + "/sync.mjs");
const {
  worldCodec,
  characterCodec,
  presetCodec,
  profileCodec,
  profileNames,
  personaCodec,
  personaNames,
  outlineCodec,
  tableCodec,
  SyncError,
} = sync;

/** Writes every rendered file back onto the resource; the result must equal the input. */
function roundTrip(codec, data) {
  let next = data;
  for (const [file, text] of codec.files(data)) next = codec.write(next, file, text);
  assert.deepEqual(next, data);
  assert.deepEqual(codec.files(next), codec.files(data));
}
function lineOf(fn) {
  try {
    fn();
  } catch (error) {
    assert.ok(error instanceof SyncError, String(error));
    return error.line;
  }
  assert.fail("expected a SyncError");
}

const entry = (uid, patch) => ({
  uid,
  key: ["灯塔"],
  keysecondary: [],
  comment: "灯塔",
  content: "海边的灯塔。\n第二行",
  constant: false,
  vectorized: false,
  selective: true,
  selectiveLogic: 0,
  addMemo: true,
  order: 100,
  position: 0,
  disable: false,
  excludeRecursion: false,
  probability: 100,
  useProbability: true,
  depth: 4,
  group: "",
  scanDepth: null,
  caseSensitive: null,
  matchWholeWords: null,
  role: null,
  sticky: null,
  displayIndex: uid,
  extensions: { custom: 1 },
  ...patch,
});
const book = {
  entries: {
    0: entry(0),
    1: entry(1, { comment: "", content: "", key: [] }),
    2: entry(2, { comment: "灯塔", position: 4, role: 2, constant: true }),
    5: entry(5, { comment: "a/b: c?", disable: true, selectiveLogic: 3, content: "---\nnot front\n---\n" }),
  },
  originalData: { name: "kept" },
};

test("world books round-trip, including empty, duplicate and unsafe titles", () => {
  const files = worldCodec.files(book);
  assert.deepEqual([...files.keys()].sort(), ["a_b_ c_.md", "灯塔 ~2.md", "灯塔.md", "条目 1.md"].sort());
  assert.match(files.get("灯塔.md"), /^---\nuid: 0\n关键词:\n  - 灯塔\n/);
  assert.match(files.get("灯塔 ~2.md"), /标题: 灯塔\n[\s\S]*注入位置: 指定深度\n[\s\S]*角色: 助手\n/);
  assert.match(files.get("a_b_ c_.md"), /逻辑: 与全部\n[\s\S]*启用: false\n/);
  assert.ok(files.get("灯塔.md").endsWith("---\n海边的灯塔。\n第二行"));
  roundTrip(worldCodec, book);
});

test("world entry edits keep unlisted fields; new files create entries; uid collisions are refused", () => {
  const text = worldCodec
    .files(book)
    .get("灯塔.md")
    .replace("顺序: 100", "顺序: 7")
    .replace("第二行", "改过");
  const edited = worldCodec.write(book, "灯塔.md", text);
  assert.equal(edited.entries[0].order, 7);
  assert.equal(edited.entries[0].content, "海边的灯塔。\n改过");
  assert.deepEqual(edited.entries[0].extensions, { custom: 1 });
  assert.equal(edited.originalData.name, "kept");
  const created = worldCodec.write(book, "新条目.md", "---\n关键词: [雾]\n常驻: true\n---\n雾气");
  assert.deepEqual(
    [
      created.entries[6].uid,
      created.entries[6].comment,
      created.entries[6].constant,
      created.entries[6].content,
    ],
    [6, "新条目", true, "雾气"],
  );
  assert.equal(created.entries[6].probability, 100);
  assert.equal(
    lineOf(() => worldCodec.write(book, "副本.md", "---\nuid: 0\n---\nx")),
    2,
  );
  assert.equal(
    lineOf(() => worldCodec.write(book, "灯塔.md", "---\nuid: 0\n注入位置: 天上\n---\n")),
    3,
  );
  assert.equal(
    lineOf(() => worldCodec.write(book, "灯塔.md", "---\nuid: 0\n顺序: 高\n---\n")),
    3,
  );
  assert.equal(
    lineOf(() => worldCodec.write(book, "灯塔.md", "---\nuid: 0\n关键字: []\n---\n")),
    3,
  );
  assert.equal(
    lineOf(() => worldCodec.write(book, "灯塔.md", "---\nuid: 0\n关键词: [a\n---\n")),
    3,
  );
  assert.equal(
    lineOf(() => worldCodec.write(book, "灯塔.md", "---\nuid: 0\n")),
    1,
  );
  assert.equal(Object.keys(worldCodec.remove(book, "条目 1.md").entries).length, 3);
  assert.equal(worldCodec.rename(book, "灯塔.md", "海灯.md").entries[0].comment, "海灯");
  assert.throws(() => worldCodec.rename(book, "灯塔.md", "条目 1.md"), SyncError);
});

const card = {
  name: "林晚",
  description: "图书管理员。",
  personality: "",
  scenario: "灯塔下的图书馆",
  first_mes: "你好。",
  mes_example: "<START>\n{{char}}: 嗯。",
  creator_notes: "备注",
  system_prompt: "",
  post_history_instructions: "",
  alternate_greetings: ["早。", "晚上好。\n"],
  tags: ["原创"],
  creator: "me",
  character_version: "1.0",
  extensions: {
    talkativeness: "0.5",
    fav: false,
    world: "灯塔",
    depth_prompt: { prompt: "记得灯塔", depth: 4, role: "system" },
    other: [1],
  },
  character_book: { entries: [] },
};

test("character cards round-trip as 角色卡.yaml, field files and numbered greetings", () => {
  const files = characterCodec.files(card);
  assert.deepEqual(
    [...files.keys()],
    [
      "角色卡.yaml",
      "角色描述.md",
      "性格.md",
      "场景.md",
      "第一条消息.md",
      "对话示例.md",
      "系统提示词.md",
      "历史后指令.md",
      "创作者注释.md",
      "备选开场白/01.md",
      "备选开场白/02.md",
    ],
  );
  assert.match(
    files.get("角色卡.yaml"),
    /^名称: 林晚\n标签:\n  - 原创\n[\s\S]*深度提示词:\n  内容: 记得灯塔\n  深度: 4\n  注入角色: 系统\n$/,
  );
  roundTrip(characterCodec, card);
  const sparse = { name: "空", extensions: {} };
  roundTrip(characterCodec, sparse);
});

test("character edits: yaml keys, greeting append and removal, ordered numbering", () => {
  const yaml = characterCodec.files(card).get("角色卡.yaml").replace("收藏: false", "收藏: true");
  assert.equal(characterCodec.write(card, "角色卡.yaml", yaml).extensions.fav, true);
  assert.deepEqual(characterCodec.write(card, "角色卡.yaml", yaml).extensions.other, [1]);
  assert.deepEqual(characterCodec.write(card, "备选开场白/03.md", "第三").alternate_greetings, [
    "早。",
    "晚上好。\n",
    "第三",
  ]);
  assert.throws(() => characterCodec.write(card, "备选开场白/05.md", "x"), /按顺序编号/);
  assert.deepEqual(characterCodec.remove(card, "备选开场白/01.md").alternate_greetings, ["晚上好。\n"]);
  assert.throws(() => characterCodec.write(card, "其他.md", "x"), SyncError);
  assert.equal(
    lineOf(() => characterCodec.write(card, "角色卡.yaml", "名称: 林晚\n收藏: 是的\n")),
    2,
  );
  assert.throws(() => characterCodec.write(card, "角色卡.yaml", "名称: ''\n"), /不能为空/);
});

const preset = {
  temperature: 1,
  top_p: 0.9,
  openai_max_context: 8192,
  stream_openai: true,
  custom_url: "http://example.invalid/v1",
  proxy_password: "never-shown",
  names_behavior: 0,
  prompts: [
    { name: "Main Prompt", system_prompt: true, role: "system", content: "Write.", identifier: "main" },
    { name: "Chat History", system_prompt: true, marker: true, identifier: "chatHistory" },
    {
      identifier: "x1",
      name: "风格/语气",
      role: "user",
      content: "短句。",
      injection_position: 1,
      injection_depth: 2,
      system_prompt: false,
      marker: false,
    },
    { identifier: "orphan", name: "未排序", role: "system", content: "" },
  ],
  prompt_order: [
    { character_id: 100000, order: [{ identifier: "main", enabled: true }] },
    {
      character_id: 100001,
      order: [
        { identifier: "chatHistory", enabled: true },
        { identifier: "main", enabled: true },
        { identifier: "x1", enabled: false },
      ],
    },
  ],
};

test("presets round-trip; prompts follow the global order; the proxy password stays out", () => {
  const files = presetCodec.files(preset);
  assert.deepEqual(
    [...files.keys()],
    [
      "参数.yaml",
      "提示词/01-Chat History.md",
      "提示词/02-Main Prompt.md",
      "提示词/03-风格_语气.md",
      "提示词/04-未排序.md",
    ],
  );
  assert.doesNotMatch(files.get("参数.yaml"), /proxy_password|never-shown/);
  assert.match(
    files.get("参数.yaml"),
    /^温度: 1\nTop P: 0.9\n上下文 Token 上限: 8192\n流式传输: true\n其他:\n  custom_url: /,
  );
  assert.match(
    files.get("提示词/03-风格_语气.md"),
    /identifier: x1\n名称: 风格\/语气\n启用: false\n角色: 用户\n注入位置: 指定聊天深度\n深度: 2\n/,
  );
  roundTrip(presetCodec, preset);
});

test("preset edits: params, other keys, prompt switches, new prompts and refusals", () => {
  const params = presetCodec
    .files(preset)
    .get("参数.yaml")
    .replace("温度: 1", "温度: 0.7")
    .replace("names_behavior: 0", "names_behavior: 2");
  const next = presetCodec.write(preset, "参数.yaml", params);
  assert.deepEqual([next.temperature, next.names_behavior, next.proxy_password], [0.7, 2, "never-shown"]);
  assert.throws(
    () => presetCodec.write(preset, "参数.yaml", "其他:\n  proxy_password: x\n"),
    /不能写 proxy_password/,
  );
  const on = presetCodec.write(
    preset,
    "提示词/03-风格_语气.md",
    presetCodec.files(preset).get("提示词/03-风格_语气.md").replace("启用: false", "启用: true"),
  );
  assert.equal(on.prompt_order[1].order[2].enabled, true);
  assert.deepEqual(on.prompt_order[0], preset.prompt_order[0]);
  const added = presetCodec.write(preset, "提示词/09-收尾.md", "---\n角色: 助手\n---\n结束。");
  const prompt = added.prompts.at(-1);
  assert.deepEqual([prompt.name, prompt.role, prompt.content], ["收尾", "assistant", "结束。"]);
  assert.deepEqual(added.prompt_order[1].order.at(-1), { identifier: prompt.identifier, enabled: true });
  assert.throws(() => presetCodec.remove(preset, "提示词/02-Main Prompt.md"), /不能删除/);
  assert.equal(presetCodec.remove(preset, "提示词/03-风格_语气.md").prompt_order[1].order.length, 2);
  assert.equal(
    lineOf(() =>
      presetCodec.write(preset, "提示词/02-Main Prompt.md", "---\nidentifier: main\n注入位置: 中间\n---\n"),
    ),
    3,
  );
});

test("connection profiles and personas round-trip without secrets", () => {
  const profiles = [
    {
      id: "p1",
      mode: "cc",
      exclude: [],
      name: "主力",
      api: "custom",
      preset: "Default",
      "api-url": "http://127.0.0.1:1/v1",
      model: "m",
      "secret-id": "s-1",
      extra: true,
    },
    { id: "p2", mode: "tc", exclude: ["model"], name: "a/b", api: "kobold" },
  ];
  const names = profileNames(profiles);
  assert.deepEqual(
    [...names.values()].map((n) => n.stem),
    ["主力", "a_b"],
  );
  for (const profile of profiles) {
    const { stem, explicit } = names.get(profile.id),
      text = profileCodec.render(profile, explicit);
    assert.deepEqual(profileCodec.parse(profile, stem, explicit, text), profile);
  }
  const text = profileCodec.render(profiles[0], false);
  assert.match(text, /^id: p1\n接口类型: Chat Completion\n服务类型: custom\n服务地址: /);
  assert.match(text, /凭据引用: s-1\n/);
  assert.equal(profileCodec.parse(profiles[0], "主力", false, text.replace("模型: m", "模型: n")).model, "n");
  assert.equal(
    lineOf(() => profileCodec.parse(profiles[0], "主力", false, "id: p9\n")),
    1,
  );

  const personas = [
    {
      id: "user.png",
      name: "旅人",
      description: "一个旅人。",
      position: 0,
      depth: 2,
      role: 0,
      lorebook: "",
      title: "",
    },
    {
      id: "u2.png",
      name: "旅人",
      description: "",
      position: 4,
      depth: 3,
      role: 1,
      connections: [{ type: "character", id: "a.png" }],
    },
  ];
  const personaFiles = personaNames(personas);
  assert.deepEqual(
    [...personaFiles.values()].map((n) => n.stem),
    ["旅人", "旅人 ~u2.png"],
  );
  for (const { id, ...persona } of personas) {
    const { stem, explicit } = personaFiles.get(id),
      text = personaCodec.render(persona, id, explicit);
    assert.deepEqual(personaCodec.parse(persona, id, stem, explicit, text), persona);
  }
  const { id, ...first } = personas[0];
  assert.match(
    personaCodec.render(first, id, false),
    /^---\nid: user.png\n说明标题: ""\n注入位置: 提示词 \/ 故事模板\n深度: 2\n注入角色: 系统\n绑定世界书: ""\n---\n一个旅人。$/,
  );
});

const outline = {
  version: 1,
  nodes: [
    {
      id: "p",
      parent: null,
      title: "第一章",
      content: "背景\n# 不是标题\n\\# 原本就有反斜杠",
      status: "done",
      rounds: 1,
      completed: 1,
    },
    { id: "a", parent: "p", title: "相遇", content: "", status: "active", rounds: 2, completed: 1 },
    {
      id: "b",
      parent: "p",
      title: "离别",
      content: "结尾带空行\n\n",
      status: "todo",
      rounds: 1,
      completed: 0,
    },
    {
      id: "c",
      parent: null,
      title: "第二章",
      content: "<!-- 只是注释 -->",
      status: "todo",
      rounds: 3,
      completed: 0,
    },
  ],
  selected: "a",
  settings: { mode: "replace", send: true, inject: { enabled: true, depth: 2 } },
  job: { queue: ["b"], index: 0 },
};

test("outlines round-trip as headings with an attribute line under each", () => {
  const text = outlineCodec.render(outline);
  assert.match(
    text,
    /^# 第一章\n<!-- id: p · 状态: 完成 · 轮数: 1 · 已完成: 1 -->\n背景\n\\# 不是标题\n\\\\# 原本就有反斜杠\n\n## 相遇\n/,
  );
  assert.deepEqual(outlineCodec.parse(outline, text), outline);
  assert.equal(outlineCodec.render(outlineCodec.parse(outline, text)), text);
  assert.equal(outlineCodec.render({ ...outline, nodes: [] }), "");
  assert.deepEqual(outlineCodec.parse(outline, "").nodes, []);
});

test("outline edits: new headings get ids, settings stay, errors carry lines", () => {
  const text = outlineCodec.render(outline) + "\n## 新节点\n内容";
  const next = outlineCodec.parse(outline, text);
  const added = next.nodes.at(-1);
  assert.deepEqual([added.parent, added.title, added.content, added.status], ["c", "新节点", "内容", "todo"]);
  assert.ok(added.id);
  assert.deepEqual(next.settings, outline.settings);
  assert.equal(
    lineOf(() => outlineCodec.parse(outline, "前言\n# A")),
    1,
  );
  assert.equal(
    lineOf(() => outlineCodec.parse(outline, "# A\n### C")),
    2,
  );
  assert.equal(
    lineOf(() => outlineCodec.parse(outline, "# A\n<!-- 状态: 未知 -->")),
    2,
  );
  assert.equal(
    lineOf(() => outlineCodec.parse(outline, "# A\n<!-- id: x -->\n# B\n<!-- id: x -->")),
    4,
  );
});

const table = {
  key: "sheet_people",
  name: "人物",
  columns: ["姓名", "备注|说明"],
  rows: [
    { id: "r1", index: 1, cells: ["艾琳", "第一行\n第二行 | 含竖线 \\ 反斜杠"] },
    { id: "", index: 2, cells: ["  前后空格  ", ""] },
    { id: "r3", index: 3, cells: ["\t制表", "*星号*"] },
  ],
};

test("database tables round-trip as Markdown tables keyed by row_id", () => {
  const text = tableCodec.render(table);
  assert.match(text, /^\| row_id \| 姓名 \| 备注\\\|说明 \|$/m);
  assert.match(text, /^\| #2 \| /m);
  assert.deepEqual(tableCodec.parse(table, text), table);
  // Alignment padding and missing outer pipes are only formatting.
  const lines = text.split("\n");
  lines[2] = lines[2].replace("| r1 | 艾琳 |", "r1|   艾琳   |").replace(/ \|$/, "");
  lines[1] = "|:---|---:|:-:|";
  const loose = lines.join("\n");
  assert.notEqual(loose, text);
  assert.ok(!lines[2].startsWith("|") && !lines[2].endsWith("|"), lines[2]);
  assert.deepEqual(tableCodec.parse(table, loose), table);
});

test("database edits update, insert and delete rows", () => {
  const lines = tableCodec.render(table).split("\n");
  lines[2] = lines[2].replace("艾琳", "艾琳娜");
  lines.splice(3, 1); // the row without an id
  lines.splice(4, 0, "|  | 新人 | 新备注 |");
  const next = tableCodec.parse(table, lines.join("\n"));
  assert.deepEqual(next.rows, [
    { ...table.rows[0], cells: ["艾琳娜", table.rows[0].cells[1]] },
    table.rows[2],
    { id: "", index: 0, cells: ["新人", "新备注"] },
  ]);
});

test("database parse errors carry the line", () => {
  const text = tableCodec.render(table);
  const at = (t) => lineOf(() => tableCodec.parse(table, t));
  assert.equal(at(text.replace("| row_id | 姓名", "| row_id | 名字")), 1);
  assert.equal(at(text.replace("| r3 |", "| r9 |")), 5);
  assert.equal(at(text.replace("| r3 |", "| r1 |")), 5);
  assert.equal(at(text.replace("| r3 | \\t制表 |", "| r3 |")), 5);
  assert.equal(at(text + "备注文字\n"), 6);
});
