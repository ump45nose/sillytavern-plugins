import type { Data } from "./types";
export const clone = <T>(value: T): T => structuredClone(value);
const isRecord = (value: unknown): value is Data =>
  !!value && typeof value === "object" && !Array.isArray(value);
/**
 * Deep equality for JSON data that trusts shared references: a draft edited copy-on-write only costs
 * the comparison of the branches it replaced. Arrays and scalars compare by their JSON.
 */
export function sameData(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!isRecord(a) || !isRecord(b)) return JSON.stringify(a) === JSON.stringify(b);
  for (const key of new Set([...Object.keys(a), ...Object.keys(b)]))
    if (!sameData(a[key], b[key])) return false;
  return true;
}
/** SillyTavern's server-side merge for card updates: plain objects merge, anything else replaces. */
export function deepMerge(target: Data, source: Data): Data {
  const output = { ...target };
  for (const [key, value] of Object.entries(source))
    output[key] = isRecord(value) && isRecord(target[key]) ? deepMerge(target[key], value) : value;
  return output;
}
export function activation(entry: Data) {
  return entry.constant ? "constant" : entry.vectorized ? "vector" : "keyword";
}
export function setActivation(entry: Data, mode: string) {
  return {
    ...entry,
    constant: mode === "constant",
    vectorized: mode === "vector",
  };
}
/** Patch only fields changed against the editor's base. Never overwrite an external edit silently. */
export function mergeEdits(base: Data, draft: Data, latest: Data): Data {
  const result = clone(latest);
  for (const key of new Set([...Object.keys(base), ...Object.keys(draft)])) {
    if (JSON.stringify(base[key]) === JSON.stringify(draft[key])) continue;
    if (
      JSON.stringify(latest[key]) !== JSON.stringify(base[key]) &&
      JSON.stringify(latest[key]) !== JSON.stringify(draft[key])
    )
      throw new Error(`“${key}”已在其他页面修改。草稿已保留，请重新载入后合并。`);
    if (Object.hasOwn(draft, key))
      Object.defineProperty(result, key, {
        value: clone(draft[key]),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    else delete result[key];
  }
  return result;
}
export function validateBook(data: Data) {
  if (
    !data ||
    Array.isArray(data) ||
    typeof data.entries !== "object" ||
    !data.entries ||
    Array.isArray(data.entries)
  )
    throw new Error("世界书需要 entries 对象。");
  for (const [id, e] of Object.entries(data.entries) as [string, Data][]) {
    if (
      !e ||
      typeof e !== "object" ||
      !Number.isInteger(e.uid) ||
      e.uid < 0 ||
      String(e.uid) !== id ||
      typeof e.content !== "string" ||
      !Array.isArray(e.key)
    )
      throw new Error(`条目 ${id} 的 uid、content 或 key 无效。`);
  }
}
export function mergeBook(base: Data, draft: Data, latest: Data) {
  validateBook(draft);
  const result = mergeEdits(
    { ...base, entries: undefined },
    { ...draft, entries: undefined },
    { ...latest, entries: undefined },
  );
  result.entries = clone(latest.entries);
  for (const id of new Set([...Object.keys(base.entries), ...Object.keys(draft.entries)])) {
    if (JSON.stringify(base.entries[id]) === JSON.stringify(draft.entries[id])) continue;
    if (!base.entries[id]) {
      if (latest.entries[id]) throw new Error("条目编号冲突，请重新载入。");
      result.entries[id] = clone(draft.entries[id]);
    } else if (!draft.entries[id]) {
      if (JSON.stringify(base.entries[id]) !== JSON.stringify(latest.entries[id]))
        throw new Error("待删除条目已变更。");
      delete result.entries[id];
    } else {
      if (!latest.entries[id]) throw new Error("条目已被其他页面删除。");
      result.entries[id] = mergeEdits(base.entries[id], draft.entries[id], latest.entries[id]);
    }
  }
  return result;
}

/** Validate editable preset structure before handing it back to the host. */
export function validatePreset(value: any): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("预设必须是 JSON 对象");
  if (value.prompts !== undefined) {
    if (!Array.isArray(value.prompts)) throw new Error("提示词必须是列表");
    const ids = new Set();
    for (const prompt of value.prompts) {
      if (
        !prompt ||
        typeof prompt.identifier !== "string" ||
        !prompt.identifier ||
        ids.has(prompt.identifier)
      )
        throw new Error("提示词标识不能为空或重复");
      if (prompt.content !== undefined && typeof prompt.content !== "string")
        throw new Error("提示词正文必须是文本");
      ids.add(prompt.identifier);
    }
  }
  if (
    value.prompt_order !== undefined &&
    (!Array.isArray(value.prompt_order) ||
      value.prompt_order.some(
        (scope: any) =>
          !scope ||
          !Array.isArray(scope.order) ||
          scope.order.some(
            (item: any) =>
              !item ||
              typeof item.identifier !== "string" ||
              (item.enabled !== undefined && typeof item.enabled !== "boolean"),
          ),
      ))
  )
    throw new Error("提示词顺序或启用状态无效");
}
