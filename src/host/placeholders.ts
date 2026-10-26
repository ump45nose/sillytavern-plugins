/**
 * Placeholder variables, compatible with the TavernHelper script 「占位符系统」 v4.5.0 that quick-reply
 * sets such as 「👑超级菜单」 were written for. Text in, text out: the caller owns storage and dialogs.
 *
 * - `{@名}` value or empty; `{@名:默认}` value, or the default while unset or empty (nothing stored);
 * - `{@名:默认:提示}` and `{@名:默认:提示:指示数}` ask for the value (or not) by the indicator:
 *   2 (default) asks while the input dialog is on, otherwise uses the stored value or the default and
 *   stores the default; 1 never asks and expands to nothing; -1 always asks, stores, expands to
 *   nothing; -2 always asks, stores, expands to the value. Cancelling leaves the text as it was.
 * - `{@名=值}` stores, `{@名!}` deletes, both expand to nothing;
 * - whole-text commands `{@list}`, `{@clear}` (this scope), `{@reset}` (every scope, confirmed), and
 *   `{@input:toggle}` anywhere (flips the input dialog, expands nothing else);
 * - `{@toast:文本}` and `{@confirm:文本}` show the text. The script ran its `{@名:默认}` pass first,
 *   so these two printed their text instead; here they work as its reserved names intended.
 */
export type PlaceholderVars = Record<string, string>;
export type PlaceholderMode = -2 | -1 | 1 | 2;
export interface PlaceholderInput {
  name: string;
  fallback: string;
  prompt: string;
  mode: PlaceholderMode;
}
export interface PlaceholderIO {
  /** The current scope's variables; never mutated. */
  vars: PlaceholderVars;
  inputOn: boolean;
  /** Asks for every input at once; the entered texts (trimmed, possibly empty) in order, or null when cancelled. */
  ask: (inputs: PlaceholderInput[], vars: PlaceholderVars) => Promise<string[] | null>;
  toast: (message: string, kind?: "info" | "success") => void;
  /** Shows a message; for `{@reset}` its answer decides. */
  confirm: (message: string) => Promise<boolean>;
}
export interface PlaceholderResult {
  text: string;
  vars: PlaceholderVars;
  inputOn: boolean;
  /** `{@clear}` empties this scope, `{@reset}` every scope (vars is then empty too). */
  clear?: "scope" | "all";
}

const NAME = "[\\w\\u4e00-\\u9fa5]+";
const RESERVED = ["list", "clear", "reset", "toast", "confirm", "input"];
const reserved = (name: string) => RESERVED.includes(name.toLowerCase());
const has = (vars: PlaceholderVars, name: string) => Object.prototype.hasOwnProperty.call(vars, name);
const PROMPTED = () => new RegExp(`\\{@(${NAME}):([^:}]*):([^:}]+)(?::(-?[12]))?\\}`, "g");

/** True once the text has no unclosed `{@` and the caret is not inside one (the script's wait-for-typing rule). */
export function placeholderComplete(text: string, caret = text.length) {
  if (/^\s*\{@(list|clear|reset|input:toggle)\}\s*$/i.test(text)) return true;
  if ((text.match(/\{@/g) || []).length > (text.match(/\}/g) || []).length) return false;
  const before = text.slice(0, caret);
  return before.lastIndexOf("{@") <= before.lastIndexOf("}");
}

/** Prompted placeholders in order, one per name; reserved names never ask. */
export function placeholderInputs(text: string): PlaceholderInput[] {
  const found: PlaceholderInput[] = [];
  for (const m of text.matchAll(PROMPTED())) {
    if (reserved(m[1]) || found.some((x) => x.name === m[1])) continue;
    found.push({
      name: m[1],
      fallback: m[2],
      prompt: m[3],
      mode: (m[4] ? Number(m[4]) : 2) as PlaceholderMode,
    });
  }
  return found;
}

export async function expandPlaceholders(text: string, io: PlaceholderIO): Promise<PlaceholderResult> {
  let vars = { ...io.vars },
    inputOn = io.inputOn;
  const done = (result: string, clear?: PlaceholderResult["clear"]) => ({
    text: result,
    vars,
    inputOn,
    clear,
  });
  if (/\{@input:toggle\}/i.test(text)) {
    inputOn = !inputOn;
    io.toast(inputOn ? "输入弹窗已开启" : "输入弹窗已关闭", inputOn ? "success" : "info");
    return done(text.replace(/\{@input:toggle\}/gi, ""));
  }
  const command = text.trim().toLowerCase();
  if (command === "{@list}") {
    const names = Object.keys(vars);
    io.toast(
      names.length
        ? `变量(${names.length}个):\n` +
            names
              .map((n) => `${n}: ${vars[n].length > 20 ? vars[n].slice(0, 20) + "..." : vars[n]}`)
              .join("\n")
        : "当前角色卡没有变量",
    );
    return done("");
  }
  if (command === "{@clear}") {
    vars = {};
    io.toast("已清空当前角色卡变量", "success");
    return done("", "scope");
  }
  if (command === "{@reset}") {
    if (!(await io.confirm("确定要清空所有角色卡的变量吗？此操作不可恢复！"))) return done("");
    vars = {};
    io.toast("已清空所有变量", "success");
    return done("", "all");
  }

  const inputs = placeholderInputs(text),
    values: Record<string, string> = {};
  const asks = (p: PlaceholderInput) => p.mode < 0 || (p.mode === 2 && inputOn);
  for (const p of inputs.filter((p) => !asks(p))) {
    if (p.mode === 1) values[p.name] = "";
    else {
      values[p.name] = vars[p.name] || p.fallback || "";
      if (!vars[p.name] && p.fallback) vars[p.name] = p.fallback;
    }
  }
  const asked = inputs.filter(asks);
  if (asked.length) {
    const entered = await io.ask(asked, { ...vars });
    // The defaults stored above stay stored, as in the script.
    if (!entered) return done(text);
    asked.forEach((p, i) => {
      const value = entered[i] || vars[p.name] || p.fallback || "";
      values[p.name] = p.mode === -1 ? "" : value;
      if (value) vars[p.name] = value;
    });
  }

  let out = text.replace(PROMPTED(), (_, name: string) =>
    has(values, name) ? values[name] : vars[name] || "",
  );
  out = out.replace(new RegExp(`\\{@(${NAME})=([^}]*)\\}`, "g"), (_, name: string, value: string) => {
    if (!reserved(name)) vars[name] = value;
    return "";
  });
  out = out.replace(new RegExp(`\\{@(${NAME})!\\}`, "g"), (_, name: string) => {
    if (!reserved(name)) delete vars[name];
    return "";
  });
  out = out.replace(/\{@toast:([^}]*)\}/gi, (_, message: string) => {
    io.toast(message);
    return "";
  });
  for (const m of [...out.matchAll(/\{@confirm:([^}]*)\}/gi)]) await io.confirm(m[1]);
  out = out.replace(/\{@confirm:([^}]*)\}/gi, "");
  out = out.replace(new RegExp(`\\{@(${NAME}):([^:}]*)\\}`, "g"), (_, name: string, fallback: string) =>
    has(vars, name) && vars[name] !== "" ? vars[name] : fallback,
  );
  out = out.replace(new RegExp(`\\{@(${NAME})\\}`, "g"), (_, name: string) =>
    has(vars, name) ? vars[name] : "",
  );
  return done(out);
}
