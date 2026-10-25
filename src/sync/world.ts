import {
  SyncError,
  joinFront,
  readFields,
  splitFront,
  uniqueNames,
  writeFields,
  type Data,
  type Field,
} from "./text";

/** SillyTavern's labels for entry positions, as the world book editor shows them. */
const positions: [number, string][] = [
  [0, "角色定义之前"],
  [1, "角色定义之后"],
  [2, "作者注释之前"],
  [3, "作者注释之后"],
  [4, "指定深度"],
  [5, "示例之前"],
  [6, "示例之后"],
  [7, "Outlet"],
];
export const roles: [number, string][] = [
  [0, "系统"],
  [1, "用户"],
  [2, "助手"],
];
const fields: Field[] = [
  { name: "关键词", path: ["key"], type: "strings" },
  { name: "辅助关键词", path: ["keysecondary"], type: "strings" },
  { name: "使用辅助关键词", path: ["selective"], type: "boolean" },
  {
    name: "逻辑",
    path: ["selectiveLogic"],
    type: "number",
    labels: [
      [0, "与任意"],
      [1, "非全部"],
      [2, "非任意"],
      [3, "与全部"],
    ],
  },
  { name: "常驻", path: ["constant"], type: "boolean" },
  { name: "向量化", path: ["vectorized"], type: "boolean" },
  { name: "启用", path: ["disable"], type: "boolean", invert: true },
  { name: "注入位置", path: ["position"], type: "number", labels: positions },
  { name: "深度", path: ["depth"], type: "number" },
  { name: "角色", path: ["role"], type: "number", nullable: true, labels: roles },
  { name: "顺序", path: ["order"], type: "number" },
  { name: "概率", path: ["probability"], type: "number" },
  { name: "启用概率", path: ["useProbability"], type: "boolean" },
  { name: "扫描深度", path: ["scanDepth"], type: "number", nullable: true },
  { name: "粘性", path: ["sticky"], type: "number", nullable: true },
  { name: "冷却", path: ["cooldown"], type: "number", nullable: true },
  { name: "延迟", path: ["delay"], type: "number", nullable: true },
  { name: "包含组", path: ["group"], type: "string" },
  { name: "组权重", path: ["groupWeight"], type: "number" },
  { name: "覆盖包含组", path: ["groupOverride"], type: "boolean" },
  { name: "分组评分", path: ["useGroupScoring"], type: "boolean", nullable: true },
  { name: "排除递归", path: ["excludeRecursion"], type: "boolean" },
  { name: "阻止后续递归", path: ["preventRecursion"], type: "boolean" },
  { name: "仅递归时触发", path: ["delayUntilRecursion"], type: "any" },
  { name: "匹配完整单词", path: ["matchWholeWords"], type: "boolean", nullable: true },
  { name: "区分大小写", path: ["caseSensitive"], type: "boolean", nullable: true },
];

/** SillyTavern's new-entry template (world-info.js newWorldInfoEntryDefinition). */
function template(uid: number): Data {
  return {
    uid,
    key: [],
    keysecondary: [],
    comment: "",
    content: "",
    constant: false,
    vectorized: false,
    selective: true,
    selectiveLogic: 0,
    addMemo: true,
    order: 100,
    position: 0,
    disable: false,
    ignoreBudget: false,
    excludeRecursion: false,
    preventRecursion: false,
    matchPersonaDescription: false,
    matchCharacterDescription: false,
    matchCharacterPersonality: false,
    matchCharacterDepthPrompt: false,
    matchScenario: false,
    matchCreatorNotes: false,
    delayUntilRecursion: 0,
    probability: 100,
    useProbability: true,
    depth: 4,
    outletName: "",
    group: "",
    groupOverride: false,
    groupWeight: 100,
    scanDepth: null,
    caseSensitive: null,
    matchWholeWords: null,
    useGroupScoring: null,
    automationId: "",
    role: 0,
    sticky: null,
    cooldown: null,
    delay: null,
    triggers: [],
    displayIndex: uid,
  };
}

const entriesOf = (book: Data): [string, Data][] =>
  Object.entries((book?.entries ?? {}) as Record<string, Data>).sort(
    ([a, x], [b, y]) =>
      (x.displayIndex ?? Number(a)) - (y.displayIndex ?? Number(b)) || Number(a) - Number(b),
  );
function names(book: Data) {
  return uniqueNames(
    entriesOf(book),
    ([key]) => key,
    ([, e]) => String(e.comment ?? ""),
    ([key]) => `条目 ${key}`,
  );
}
const stemOf = (file: string) => {
  if (!/^[^/]+\.md$/.test(file)) throw new SyncError("世界书条目是书名目录下的 .md 文件。");
  return file.slice(0, -3);
};

/** One book as `<条目标题>.md` files: trigger settings in frontmatter, the content as the body. */
export const worldCodec = {
  files(book: Data) {
    const files = new Map<string, string>(),
      map = names(book);
    for (const [key, entry] of entriesOf(book)) {
      const name = map.get(key)!,
        front: Data = { uid: entry.uid ?? Number(key) };
      if (name.explicit) front.标题 = String(entry.comment ?? "");
      files.set(`${name.stem}.md`, joinFront(writeFields(fields, entry, front), String(entry.content ?? "")));
    }
    return files;
  },
  write(book: Data, file: string, text: string): Data {
    const stem = stemOf(file),
      { yaml, body } = splitFront(text),
      map = names(book),
      byFile = [...map].find(([, n]) => n.stem === stem)?.[0],
      uid = yaml.data.uid;
    if (uid !== undefined && (typeof uid !== "number" || !Number.isInteger(uid)))
      throw new SyncError("uid 应为整数。", yaml.line("uid"));
    if (yaml.data.标题 !== undefined && typeof yaml.data.标题 !== "string")
      throw new SyncError("「标题」应为文本。", yaml.line("标题"));
    const entries = entriesOf(book);
    let key = uid === undefined ? byFile : entries.find(([k, e]) => (e.uid ?? Number(k)) === uid)?.[0];
    if (uid !== undefined && !key)
      throw new SyncError(`uid ${uid} 不在这本世界书里；新建条目请删去 uid。`, yaml.line("uid"));
    if (key && byFile !== key)
      throw new SyncError(
        `uid ${uid} 属于「${map.get(key)!.stem}.md」；新建条目请删去 uid，改名请重命名文件。`,
        yaml.line("uid"),
      );
    let entry: Data;
    if (key) entry = book.entries[key];
    else {
      const next = Math.max(-1, ...entries.map(([k, e]) => Number(e.uid ?? k))) + 1;
      key = String(next);
      entry = template(next);
    }
    const updated = readFields(fields, yaml, entry, ["uid", "标题"]);
    // Without 标题 the title is the file name, unless the name was only derived from it.
    updated.comment =
      typeof yaml.data.标题 === "string"
        ? yaml.data.标题
        : key === byFile && map.get(key)!.explicit
          ? entry.comment
          : stem;
    updated.content = body;
    return { ...book, entries: { ...book.entries, [key]: updated } };
  },
  remove(book: Data, file: string): Data {
    const stem = stemOf(file),
      key = [...names(book)].find(([, n]) => n.stem === stem)?.[0];
    if (!key) throw new SyncError("条目不存在。");
    const entries = { ...book.entries };
    delete entries[key];
    return { ...book, entries };
  },
  rename(book: Data, from: string, to: string): Data {
    const map = names(book),
      key = [...map].find(([, n]) => n.stem === stemOf(from))?.[0],
      stem = stemOf(to);
    if (!key) throw new SyncError("条目不存在。");
    if ([...map].some(([k, n]) => k !== key && n.stem === stem)) throw new SyncError(`已有条目「${stem}」。`);
    return { ...book, entries: { ...book.entries, [key]: { ...book.entries[key], comment: stem } } };
  },
};
