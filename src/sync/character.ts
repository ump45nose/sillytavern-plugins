import { SyncError, parseYaml, readFields, renderYaml, writeFields, type Data, type Field } from "./text";

/** Card fields kept as whole .md files, named as the character editor labels them. */
const texts: [string, string][] = [
  ["角色描述.md", "description"],
  ["性格.md", "personality"],
  ["场景.md", "scenario"],
  ["第一条消息.md", "first_mes"],
  ["对话示例.md", "mes_example"],
  ["系统提示词.md", "system_prompt"],
  ["历史后指令.md", "post_history_instructions"],
  ["创作者注释.md", "creator_notes"],
];
const CARD = "角色卡.yaml",
  GREETINGS = "备选开场白";
const fields: Field[] = [
  { name: "名称", path: ["name"], type: "string" },
  { name: "标签", path: ["tags"], type: "strings" },
  { name: "创建者", path: ["creator"], type: "string" },
  { name: "角色版本", path: ["character_version"], type: "string" },
  { name: "世界书", path: ["extensions", "world"], type: "string" },
  { name: "收藏", path: ["extensions", "fav"], type: "boolean" },
  { name: "发言积极性", path: ["extensions", "talkativeness"], type: "any" },
  { name: "深度提示词.内容", path: ["extensions", "depth_prompt", "prompt"], type: "string" },
  { name: "深度提示词.深度", path: ["extensions", "depth_prompt", "depth"], type: "number" },
  {
    name: "深度提示词.注入角色",
    path: ["extensions", "depth_prompt", "role"],
    type: "string",
    labels: [
      ["system", "系统"],
      ["user", "用户"],
      ["assistant", "助手"],
    ],
  },
];
const greetingFile = (i: number, count: number) =>
  `${GREETINGS}/${String(i + 1).padStart(Math.max(2, String(count).length), "0")}.md`;
function greetingIndex(file: string) {
  const match = file.match(/^备选开场白\/(\d+)\.md$/);
  return match ? Number(match[1]) - 1 : -1;
}

/** A character card's `data` (V2) as 角色卡.yaml, one .md per long field and 备选开场白/NN.md. */
export const characterCodec = {
  dirs: [GREETINGS],
  files(data: Data) {
    const files = new Map<string, string>([[CARD, renderYaml(writeFields(fields, data))]]);
    for (const [file, key] of texts) files.set(file, String(data[key] ?? ""));
    const greetings: unknown[] = Array.isArray(data.alternate_greetings) ? data.alternate_greetings : [];
    greetings.forEach((text, i) => files.set(greetingFile(i, greetings.length), String(text ?? "")));
    return files;
  },
  write(data: Data, file: string, text: string): Data {
    text = text.replace(/\r\n/g, "\n");
    if (file === CARD) {
      const next = readFields(fields, parseYaml(text), data);
      if (typeof next.name !== "string" || !next.name.trim()) throw new SyncError("「名称」不能为空。", 1);
      return next;
    }
    const field = texts.find(([name]) => name === file)?.[1];
    if (field) return text === "" && data[field] === undefined ? data : { ...data, [field]: text };
    const index = greetingIndex(file),
      greetings = [...(Array.isArray(data.alternate_greetings) ? data.alternate_greetings : [])];
    if (index < 0) throw new SyncError("角色目录里只能写已有的文件和「备选开场白/NN.md」。");
    if (index > greetings.length)
      throw new SyncError(
        `备选开场白请按顺序编号：下一个是 ${greetingFile(greetings.length, greetings.length + 1)}。`,
      );
    greetings[index] = text;
    return { ...data, alternate_greetings: greetings };
  },
  remove(data: Data, file: string): Data {
    const index = greetingIndex(file),
      greetings = [...(data.alternate_greetings ?? [])];
    if (index < 0 || index >= greetings.length) throw new SyncError("只能删除备选开场白。");
    greetings.splice(index, 1);
    return { ...data, alternate_greetings: greetings };
  },
};

/** Top-level fields of a V2 card file that mirror `data`, as SillyTavern's charaFormatData writes them. */
export function mirrorCard(card: Data, data: Data): Data {
  return {
    ...card,
    name: data.name,
    description: data.description ?? "",
    personality: data.personality ?? "",
    scenario: data.scenario ?? "",
    first_mes: data.first_mes ?? "",
    mes_example: data.mes_example ?? "",
    creatorcomment: data.creator_notes ?? "",
    tags: data.tags ?? [],
    talkativeness: data.extensions?.talkativeness ?? card.talkativeness,
    fav: data.extensions?.fav ?? card.fav,
    data,
  };
}
