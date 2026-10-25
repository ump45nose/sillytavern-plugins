import { LineCounter, isMap, isPair, isScalar, parseDocument, stringify, type Node } from "yaml";

/** A parse or validation failure; `line` is 1-based within the file. */
export class SyncError extends Error {
  constructor(
    message: string,
    readonly line?: number,
  ) {
    super(message);
  }
}

export type Data = Record<string, any>;

/** A parsed YAML map with the line of each top-level key and of nested keys, as "a.b". */
export interface Yaml {
  data: Data;
  line(key: string): number | undefined;
}

/** Parses a YAML map; `offset` is the number of file lines before the YAML starts. */
export function parseYaml(text: string, offset = 0): Yaml {
  const counter = new LineCounter();
  const doc = parseDocument(text, { lineCounter: counter, uniqueKeys: true, prettyErrors: false });
  const error = doc.errors[0];
  if (error) {
    // Unclosed brackets are reported at the end of input; the last YAML line is nearer the cause.
    const last = Math.max(1, text.replace(/\n$/, "").split("\n").length);
    throw new SyncError(
      `YAML 无法解析：${error.message.split("\n")[0]}`,
      Math.min(counter.linePos(error.pos[0]).line, last) + offset,
    );
  }
  const lines = new Map<string, number>();
  const walk = (node: Node | null | undefined, prefix: string) => {
    if (!isMap(node)) return;
    for (const pair of node.items) {
      if (!isPair(pair) || !isScalar(pair.key)) continue;
      const key = prefix + String(pair.key.value);
      if (pair.key.range) lines.set(key, counter.linePos(pair.key.range[0]).line + offset);
      walk(pair.value as Node, key + ".");
    }
  };
  walk(doc.contents as Node, "");
  const data = doc.contents === null ? {} : doc.toJS({ maxAliasCount: 50 });
  if (!data || typeof data !== "object" || Array.isArray(data))
    throw new SyncError("YAML 顶层应是「键: 值」的映射。", offset + 1);
  return { data, line: (key) => lines.get(key) };
}

export function renderYaml(data: Data) {
  return Object.keys(data).length ? stringify(data, { lineWidth: 0, minContentWidth: 0 }) : "";
}

/** The YAML header between `---` lines and the body after it, which is kept byte for byte. */
export function splitFront(text: string): { yaml: Yaml; body: string } {
  text = text.replace(/\r\n/g, "\n");
  if (!text.startsWith("---\n")) return { yaml: parseYaml(""), body: text };
  const end = text.indexOf("\n---\n", 3),
    tail = text.endsWith("\n---") ? text.length - 4 : -1,
    close = end >= 0 ? end : tail;
  if (close < 0) throw new SyncError("frontmatter 缺少结束的 ---。", 1);
  return { yaml: parseYaml(text.slice(4, close + 1), 1), body: text.slice(close + 5) };
}

export function joinFront(data: Data, body: string) {
  return `---\n${renderYaml(data)}---\n${body}`;
}

const illegal = /[/\\:*?"<>|\u0000-\u001f\u007f]/g;
/** A title as a file name; empty when nothing usable is left. */
export function fileStem(title: string) {
  const stem = title.replace(illegal, "_").trim();
  return stem === "." || stem === ".." ? "_" : stem;
}

/**
 * File names for titled items. A name is the title when the title can be one; otherwise (empty,
 * illegal characters, a name already taken) it gets a fallback or a ` ~key` suffix, and `explicit`
 * says the title must be written inside the file.
 */
export function uniqueNames<T>(
  items: T[],
  key: (item: T) => string,
  title: (item: T) => string,
  fallback: (item: T) => string,
) {
  const names = new Map<string, { stem: string; explicit: boolean }>(),
    used = new Set<string>();
  for (const item of items) {
    const t = title(item);
    let stem = fileStem(t) || fileStem(fallback(item));
    if (used.has(stem)) stem = `${stem} ~${fileStem(key(item))}`;
    for (let n = 2; used.has(stem); n++) stem = `${fileStem(t) || "_"} ~${fileStem(key(item))}-${n}`;
    used.add(stem);
    names.set(key(item), { stem, explicit: stem !== t });
  }
  return names;
}

/** One field of a resource as a YAML key: where it lives in the source and how it is written. */
export interface Field {
  /** The YAML key; nested keys are joined with ".". */
  name: string;
  /** Property path in the source object. */
  path: string[];
  type: "string" | "number" | "boolean" | "strings" | "any";
  nullable?: boolean;
  /** Source values written as labels; raw values are still accepted when parsing. */
  labels?: [any, string][];
  /** Booleans stored inverted (启用 ⇄ disable). */
  invert?: boolean;
}

const getPath = (source: Data, path: string[]) =>
  path.reduce<any>((v, k) => (v == null ? undefined : v[k]), source);
function setPath(target: Data, path: string[], value: unknown) {
  let node = target;
  for (const key of path.slice(0, -1)) {
    if (node[key] == null || typeof node[key] !== "object") node[key] = {};
    node = node[key];
  }
  node[path.at(-1)!] = value;
}
const setNested = (target: Data, name: string, value: unknown) => setPath(target, name.split("."), value);
const getNested = (source: Data, name: string) => getPath(source, name.split("."));

/** The fields present in `source`, under their YAML keys. */
export function writeFields(fields: Field[], source: Data, out: Data = {}) {
  for (const field of fields) {
    let value = getPath(source, field.path);
    if (value === undefined) continue;
    if (field.invert && typeof value === "boolean") value = !value;
    const label = field.labels?.find(([raw]) => raw === value);
    setNested(out, field.name, label ? label[1] : value);
  }
  return out;
}

function typeError(field: Field, value: unknown) {
  if (value === null) return !field.nullable && field.type !== "any";
  if (field.type === "any") return false;
  if (field.type === "strings") return !Array.isArray(value) || value.some((v) => typeof v !== "string");
  return typeof value !== field.type;
}
const typeNames = {
  string: "文本",
  number: "数字",
  boolean: "true 或 false",
  strings: "文本列表",
  any: "值",
};

/**
 * Applies the YAML keys present to a copy of `base`; keys left out keep their values. Unknown keys
 * are errors unless listed in `allowed`.
 */
export function readFields(fields: Field[], yaml: Yaml, base: Data, allowed: string[] = []) {
  const result = structuredClone(base),
    known = new Set([...fields.map((f) => f.name), ...allowed]);
  const check = (data: Data, prefix: string) => {
    for (const [key, value] of Object.entries(data)) {
      const name = prefix + key;
      if (known.has(name)) continue;
      if (
        [...known].some((k) => k.startsWith(name + ".")) &&
        value &&
        typeof value === "object" &&
        !Array.isArray(value)
      )
        check(value, name + ".");
      else throw new SyncError(`未知的键「${name}」。`, yaml.line(name));
    }
  };
  check(yaml.data, "");
  for (const field of fields) {
    let value = getNested(yaml.data, field.name);
    if (value === undefined) continue;
    if (field.labels && typeof value === "string") {
      const hit = field.labels.find(([, label]) => label === value);
      if (hit) value = hit[0];
      else if (field.type !== "string")
        throw new SyncError(
          `「${field.name}」应为 ${field.labels.map(([, l]) => l).join(" / ")} 之一。`,
          yaml.line(field.name),
        );
    }
    if (typeError(field, value))
      throw new SyncError(
        `「${field.name}」应为${typeNames[field.type]}${field.nullable ? "或 null" : ""}。`,
        yaml.line(field.name),
      );
    if (field.invert && typeof value === "boolean") value = !value;
    setPath(result, field.path, value);
  }
  return result;
}

/** Keys of `source` not covered by `fields` or `hidden`, for an 「其他」 map. */
export function otherKeys(fields: Field[], source: Data, hidden: string[] = []) {
  const covered = new Set([...fields.filter((f) => f.path.length === 1).map((f) => f.path[0]), ...hidden]);
  return Object.fromEntries(Object.entries(source).filter(([k]) => !covered.has(k)));
}

export const sameData = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
