import {
  SyncError,
  fileStem,
  joinFront,
  otherKeys,
  parseYaml,
  readFields,
  renderYaml,
  splitFront,
  writeFields,
  type Data,
  type Field,
} from "./text";

const PARAMS = "参数.yaml",
  PROMPTS = "提示词";
/** Credentials stay out of the files; they are kept as stored. */
const hidden = ["prompts", "prompt_order", "proxy_password"];
/** Parameters with names on the preset page; the rest go under 「其他」 with their own keys. */
const params: Field[] = (
  [
    ["temperature", "温度", "number"],
    ["top_p", "Top P", "number"],
    ["top_k", "Top K", "number"],
    ["top_a", "Top A", "number"],
    ["min_p", "Min P", "number"],
    ["frequency_penalty", "频率惩罚", "number"],
    ["presence_penalty", "存在惩罚", "number"],
    ["repetition_penalty", "重复惩罚", "number"],
    ["openai_max_tokens", "最大回复 Token", "number"],
    ["openai_max_context", "上下文 Token 上限", "number"],
    ["stream_openai", "流式传输", "boolean"],
    ["show_thoughts", "请求思维链", "boolean"],
    ["reasoning_effort", "思考强度", "string"],
    ["seed", "随机种子", "number"],
    ["n", "回复数量", "number"],
  ] as const
).map(([key, name, type]) => ({ name, path: [key], type }));
const promptFields: Field[] = [
  {
    name: "角色",
    path: ["role"],
    type: "string",
    labels: [
      ["system", "系统"],
      ["user", "用户"],
      ["assistant", "助手"],
    ],
  },
  {
    name: "注入位置",
    path: ["injection_position"],
    type: "number",
    labels: [
      [0, "按列表顺序"],
      [1, "指定聊天深度"],
    ],
  },
  { name: "深度", path: ["injection_depth"], type: "number" },
  { name: "顺序", path: ["injection_order"], type: "number" },
  { name: "标记", path: ["marker"], type: "boolean" },
  { name: "系统提示词", path: ["system_prompt"], type: "boolean" },
  { name: "禁止角色覆盖", path: ["forbid_overrides"], type: "boolean" },
  { name: "生成类型", path: ["injection_trigger"], type: "strings" },
];

/** The prompt order chat completion uses: SillyTavern's global dummy id 100001, else 100000, else the first. */
function orderOf(preset: Data): { identifier: string; enabled?: boolean }[] | undefined {
  const lists: Data[] = Array.isArray(preset.prompt_order) ? preset.prompt_order : [];
  return (
    lists.find((l) => l.character_id === 100001) ??
    lists.find((l) => l.character_id === 100000) ??
    lists[0]
  )?.order;
}
/** Prompts in order: listed ones first, then the rest as stored. */
function promptList(preset: Data) {
  const prompts: Data[] = Array.isArray(preset.prompts) ? preset.prompts : [],
    order = orderOf(preset) ?? [],
    listed = order.map((o) => prompts.find((p) => p.identifier === o.identifier)).filter(Boolean) as Data[];
  return [...listed, ...prompts.filter((p) => !listed.includes(p))].map((prompt, i, all) => {
    const name = String(prompt.name ?? ""),
      stem = fileStem(name);
    return {
      prompt,
      enabled: order.find((o) => o.identifier === prompt.identifier)?.enabled,
      file: `${PROMPTS}/${String(i + 1).padStart(Math.max(2, String(all.length).length), "0")}-${stem || "_"}.md`,
      explicit: stem !== name,
    };
  });
}
function promptName(file: string) {
  const match = file.match(/^提示词\/(?:\d+-)?([^/]+)\.md$/);
  if (!match) throw new SyncError("提示词是「提示词/序号-名称.md」。");
  return match[1];
}

/** A chat completion preset as 参数.yaml and one 提示词/NN-名称.md per prompt, in prompt order. */
export const presetCodec = {
  dirs: [PROMPTS],
  files(preset: Data) {
    const out: Data = writeFields(params, preset),
      other = otherKeys(params, preset, hidden);
    if (Object.keys(other).length) out.其他 = other;
    const files = new Map<string, string>([[PARAMS, renderYaml(out)]]);
    for (const { prompt, enabled, file, explicit } of promptList(preset)) {
      const front: Data = { identifier: prompt.identifier };
      if (explicit) front.名称 = String(prompt.name ?? "");
      if (enabled !== undefined) front.启用 = enabled;
      files.set(file, joinFront(writeFields(promptFields, prompt, front), String(prompt.content ?? "")));
    }
    return files;
  },
  write(preset: Data, file: string, text: string): Data {
    if (file === PARAMS) {
      const yaml = parseYaml(text.replace(/\r\n/g, "\n")),
        next = readFields(params, yaml, preset, ["其他"]),
        other = yaml.data.其他 ?? {};
      if (!other || typeof other !== "object" || Array.isArray(other))
        throw new SyncError("「其他」应是「键: 值」的映射。", yaml.line("其他"));
      for (const key of Object.keys(other))
        if (hidden.includes(key) || params.some((p) => p.path[0] === key))
          throw new SyncError(`「其他」里不能写 ${key}。`, yaml.line(`其他.${key}`));
      return { ...next, ...other };
    }
    const name = promptName(file),
      { yaml, body } = splitFront(text),
      list = promptList(preset),
      identifier = yaml.data.identifier,
      byFile = list.find((p) => p.file === file);
    if (identifier !== undefined && typeof identifier !== "string")
      throw new SyncError("identifier 应为文本。", yaml.line("identifier"));
    if (yaml.data.名称 !== undefined && typeof yaml.data.名称 !== "string")
      throw new SyncError("「名称」应为文本。", yaml.line("名称"));
    if (yaml.data.启用 !== undefined && typeof yaml.data.启用 !== "boolean")
      throw new SyncError("「启用」应为 true 或 false。", yaml.line("启用"));
    const found = identifier === undefined ? byFile : list.find((p) => p.prompt.identifier === identifier);
    if (found && byFile !== found)
      throw new SyncError(
        `identifier ${identifier} 属于「${found.file}」；新建提示词请删去 identifier，改名请重命名文件。`,
        yaml.line("identifier"),
      );
    const prompts: Data[] = [...(preset.prompts ?? [])],
      base = found?.prompt ?? {
        identifier: identifier ?? globalThis.crypto.randomUUID(),
        role: "system",
        system_prompt: false,
        marker: false,
        injection_position: 0,
        injection_depth: 4,
        forbid_overrides: false,
      };
    const prompt = readFields(promptFields, yaml, base, ["identifier", "名称", "启用"]);
    prompt.name = typeof yaml.data.名称 === "string" ? yaml.data.名称 : found?.explicit ? base.name : name;
    if (!(body === "" && base.content === undefined)) prompt.content = body;
    const index = prompts.indexOf(base);
    index >= 0 ? (prompts[index] = prompt) : prompts.push(prompt);
    let next: Data = { ...preset, prompts };
    if (!found || yaml.data.启用 !== undefined)
      next = withOrder(next, prompt.identifier, yaml.data.启用 ?? true);
    return next;
  },
  remove(preset: Data, file: string): Data {
    const found = promptList(preset).find((p) => p.file === file);
    if (!found) throw new SyncError("提示词不存在。");
    if (found.prompt.marker || found.prompt.system_prompt) throw new SyncError("内置提示词和标记不能删除。");
    const id = found.prompt.identifier;
    return {
      ...preset,
      prompts: preset.prompts.filter((p: Data) => p !== found.prompt),
      prompt_order: (preset.prompt_order ?? []).map((l: Data) => ({
        ...l,
        order: (l.order ?? []).filter((o: Data) => o.identifier !== id),
      })),
    };
  },
  rename(preset: Data, from: string, to: string): Data {
    const found = promptList(preset).find((p) => p.file === from);
    if (!found) throw new SyncError("提示词不存在。");
    const name = promptName(to);
    return { ...preset, prompts: preset.prompts.map((p: Data) => (p === found.prompt ? { ...p, name } : p)) };
  },
};

/** Sets a prompt's switch in the chat completion order, adding it at the end when missing. */
function withOrder(preset: Data, identifier: string, enabled: boolean): Data {
  const order = orderOf(preset);
  if (!order)
    return { ...preset, prompt_order: [{ character_id: 100001, order: [{ identifier, enabled }] }] };
  const next = order.some((o) => o.identifier === identifier)
    ? order.map((o) => (o.identifier === identifier ? { ...o, enabled } : o))
    : [...order, { identifier, enabled }];
  return {
    ...preset,
    prompt_order: preset.prompt_order.map((l: Data) => (l.order === order ? { ...l, order: next } : l)),
  };
}
