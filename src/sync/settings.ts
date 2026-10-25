import {
  SyncError,
  joinFront,
  otherKeys,
  parseYaml,
  readFields,
  renderYaml,
  splitFront,
  uniqueNames,
  writeFields,
  type Data,
  type Field,
} from "./text";
import { roles } from "./world";

/** Connection profile fields with the labels of the connection editor. 「凭据引用」 is a secret id, never a key. */
const profileFields: Field[] = [
  {
    name: "接口类型",
    path: ["mode"],
    type: "string",
    labels: [
      ["cc", "Chat Completion"],
      ["tc", "Text Completion"],
    ],
  },
  ...(
    [
      ["api", "服务类型"],
      ["api-url", "服务地址"],
      ["model", "模型"],
      ["preset", "绑定预设"],
      ["proxy", "代理配置"],
      ["secret-id", "凭据引用"],
      ["reasoning-template", "思考模板"],
      ["prompt-post-processing", "提示词后处理"],
      ["regex-preset", "正则预设"],
      ["stop-strings", "停止字符串"],
      ["start-reply-with", "回复前缀"],
      ["sysprompt", "系统提示词"],
      ["sysprompt-state", "启用系统提示词"],
      ["context", "上下文模板"],
      ["instruct", "指令模板"],
      ["instruct-state", "指令模式"],
      ["tokenizer", "分词器"],
    ] as const
  ).map(([key, name]): Field => ({ name, path: [key], type: "any" })),
  { name: "应用时跳过的字段", path: ["exclude"], type: "strings" },
];

/** File names of the connection profiles, by profile id. */
export const profileNames = (profiles: Data[]) =>
  uniqueNames(
    profiles,
    (p) => String(p.id),
    (p) => String(p.name ?? ""),
    (p) => String(p.id),
  );

/** One connection profile as 连接/<名称>.yaml. */
export const profileCodec = {
  render(profile: Data, explicit: boolean) {
    const out: Data = { id: profile.id };
    if (explicit) out.名称 = profile.name;
    writeFields(profileFields, profile, out);
    const other = otherKeys(profileFields, profile, ["id", "name"]);
    if (Object.keys(other).length) out.其他 = other;
    return renderYaml(out);
  },
  parse(profile: Data, stem: string, explicit: boolean, text: string): Data {
    const yaml = parseYaml(text.replace(/\r\n/g, "\n"));
    if (yaml.data.id !== undefined && yaml.data.id !== profile.id)
      throw new SyncError("id 不能修改；新建连接配置请在酒馆中操作。", yaml.line("id"));
    const next = readFields(profileFields, yaml, profile, ["id", "名称", "其他"]),
      other = yaml.data.其他 ?? {};
    if (!other || typeof other !== "object" || Array.isArray(other))
      throw new SyncError("「其他」应是「键: 值」的映射。", yaml.line("其他"));
    for (const key of Object.keys(other))
      if (key === "id" || key === "name" || profileFields.some((f) => f.path[0] === key))
        throw new SyncError(`「其他」里不能写 ${key}。`, yaml.line(`其他.${key}`));
    const name = typeof yaml.data.名称 === "string" ? yaml.data.名称 : explicit ? profile.name : stem;
    if (!String(name).trim()) throw new SyncError("连接名称不能为空。", yaml.line("名称"));
    return { ...next, ...other, name };
  },
};

const personaFields: Field[] = [
  { name: "说明标题", path: ["title"], type: "string" },
  {
    name: "注入位置",
    path: ["position"],
    type: "number",
    labels: [
      [0, "提示词 / 故事模板"],
      [2, "作者注释之前"],
      [3, "作者注释之后"],
      [4, "指定深度"],
      [9, "停用"],
    ],
  },
  { name: "深度", path: ["depth"], type: "number" },
  { name: "注入角色", path: ["role"], type: "number", labels: roles },
  { name: "绑定世界书", path: ["lorebook"], type: "string" },
];

/** File names of the personas (`{id, name}`), by avatar id. */
export const personaNames = (personas: Data[]) =>
  uniqueNames(
    personas,
    (p) => String(p.id),
    (p) => String(p.name ?? ""),
    (p) => String(p.id).replace(/\.[^.]+$/, ""),
  );

/**
 * One persona (`{name, ...description}`, the shape savePersona takes) as 用户设定/<名称>.md: the
 * description is the body.
 */
export const personaCodec = {
  render(persona: Data, id: string, explicit: boolean) {
    const front: Data = { id };
    if (explicit) front.名称 = persona.name;
    writeFields(personaFields, persona, front);
    const other = otherKeys(personaFields, persona, ["name", "description"]);
    if (Object.keys(other).length) front.其他 = other;
    return joinFront(front, String(persona.description ?? ""));
  },
  parse(persona: Data, id: string, stem: string, explicit: boolean, text: string): Data {
    const { yaml, body } = splitFront(text);
    if (yaml.data.id !== undefined && yaml.data.id !== id)
      throw new SyncError("id 不能修改；新建用户设定请在酒馆中操作。", yaml.line("id"));
    const next = readFields(personaFields, yaml, persona, ["id", "名称", "其他"]),
      other = yaml.data.其他 ?? {};
    if (!other || typeof other !== "object" || Array.isArray(other))
      throw new SyncError("「其他」应是「键: 值」的映射。", yaml.line("其他"));
    for (const key of Object.keys(other))
      if (["name", "description"].includes(key) || personaFields.some((f) => f.path[0] === key))
        throw new SyncError(`「其他」里不能写 ${key}。`, yaml.line(`其他.${key}`));
    const name = typeof yaml.data.名称 === "string" ? yaml.data.名称 : explicit ? persona.name : stem;
    return {
      ...next,
      ...other,
      name,
      ...(body === "" && persona.description === undefined ? {} : { description: body }),
    };
  },
};
