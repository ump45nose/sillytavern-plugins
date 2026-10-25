/** Story options: the pure rules, free of the DOM and of SillyTavern. */
import type { DbTable } from "./database";

export interface StoryOption {
  title: string;
  /** Empty when the title is all there is. */
  detail: string;
}

export type OptionSource = "off" | "model" | "db";
/** What a click on an option does: put its text in the input, or send it at once. */
export type OptionAction = "fill" | "send";
/** Chat metadata `workbenchOptions`: where this chat's options come from and what choosing one does. */
export interface OptionsConfig {
  source: OptionSource;
  /** The database table bound for the "db" source. */
  table: string;
  /** Noval reads on and writes back, so it fills; RP plays as a choice, so it sends. */
  novel: OptionAction;
  rp: OptionAction;
}
const DEFAULTS: OptionsConfig = { source: "off", table: "", novel: "fill", rp: "send" };
const action = (value: unknown, fallback: OptionAction): OptionAction =>
  value === "fill" || value === "send" ? value : fallback;

/** A chat's stored config with every field it lacks (or holds wrong) at its default. */
export function readOptionsConfig(value: any): OptionsConfig {
  return {
    source: value?.source === "model" || value?.source === "db" ? value.source : "off",
    table: typeof value?.table === "string" ? value.table : "",
    novel: action(value?.novel, DEFAULTS.novel),
    rp: action(value?.rp, DEFAULTS.rp),
  };
}
/** What the chat stores: nothing while every field is at its default. */
export function storedOptionsConfig(config: Partial<OptionsConfig>): OptionsConfig | undefined {
  const value = readOptionsConfig(config);
  return (Object.keys(DEFAULTS) as (keyof OptionsConfig)[]).every((key) => value[key] === DEFAULTS[key])
    ? undefined
    : value;
}
/** The text an option puts in the input: its detail says the move in full, else its title. */
export const optionText = (option: StoryOption) => option.detail || option.title;

const BLOCK = /<options\b[^>]*>[\s\S]*?<\/options>/gi;
const OPEN = "<options";
const MAX = 6;

function decode(text: string) {
  return text
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

/** The options of the last complete `<options>` block a reply carries. */
export function parseOptions(raw: string): StoryOption[] {
  const block = [...raw.matchAll(BLOCK)].at(-1)?.[0];
  if (!block) return [];
  return [...block.matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/gi)]
    .map(([, attributes, body]) => {
      const title = decode(
          attributes
            .match(/title\s*=\s*(?:"([^"]*)"|'([^']*)')/i)
            ?.slice(1)
            .find((x) => x != null) ?? "",
        ).trim(),
        detail = decode(body).trim();
      return title ? { title, detail } : { title: detail, detail: "" };
    })
    .filter((option) => option.title)
    .slice(0, MAX);
}

/**
 * The reply as a reader sees it: every complete block out, and a block still streaming at the end
 * (or its opening tag half written) out too.
 */
export function stripOptions(text: string) {
  let out = text.replace(BLOCK, "");
  const open = out.search(/<options\b[^>]*>(?![\s\S]*<\/options>)/i);
  if (open >= 0) out = out.slice(0, open);
  else {
    const tail = out.slice(out.lastIndexOf("<"));
    if (tail.length > 1 && OPEN.startsWith(tail.toLowerCase())) out = out.slice(0, -tail.length);
  }
  return out === text ? text : out.replace(/\s+$/, "");
}

/**
 * A text-completion prompt without the options of earlier replies. The instruction asking for them
 * sits at depth 0, after every reply, so its example block is the last one and stays.
 */
export function stripHistory(prompt: string, keepLast: boolean) {
  const blocks = [...prompt.matchAll(BLOCK)];
  if (!blocks.length) return prompt;
  const keep = keepLast ? blocks.at(-1)!.index : -1;
  return prompt.replace(BLOCK, (block, at: number) => (at === keep ? block : ""));
}

const cell = (value: unknown) => (value == null ? "" : String(value).trim());

/**
 * A table's rows as options. One row: each filled cell is an option (a column per option). Several
 * rows: each row is one, titled by its first filled column, the rest as `header：value` lines.
 */
export function tableOptions(table: Pick<DbTable, "columns" | "rows">): StoryOption[] {
  const columns = table.columns
    .map((name, index) => ({ name: cell(name), index }))
    .filter((column) => column.name && column.name.toLowerCase() !== "row_id");
  const filled = table.rows.map((row) => row.cells).filter((row) => columns.some((c) => cell(row[c.index])));
  if (filled.length === 1)
    return columns
      .map((c) => cell(filled[0][c.index]))
      .filter(Boolean)
      .map((title) => ({ title, detail: "" }))
      .slice(0, MAX);
  return filled
    .map((row) => {
      const values = columns.map((c) => ({ name: c.name, value: cell(row[c.index]) })).filter((x) => x.value);
      return {
        title: values[0]?.value ?? "",
        detail: values
          .slice(1)
          .map((x) => `${x.name}：${x.value}`)
          .join("\n"),
      };
    })
    .filter((option) => option.title)
    .slice(0, MAX);
}

/** The instruction injected while a chat takes its options from the model's replies. */
export const DEFAULT_OPTIONS_PROMPT = [
  "[剧情选项] 正文写完后，另起一行输出 3–4 个供 {{user}} 选择的下一步行动，格式如下，整段只出现一次：",
  '<options><option title="四到十个字的标题">一两句话：这个行动是什么、可能把故事带向哪里</option></options>',
  "选项要贴合故事当前的文风与 {{char}} 的处境，方向彼此不同。下面是作者的主线，为空时忽略；有内容时至少一个选项推动它：",
  "{{outline}}",
].join("\n");
