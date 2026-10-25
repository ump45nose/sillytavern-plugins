import { SyncError } from "./text";

/**
 * One database table as the page reports it. `index` is the row's 1-based position, which the
 * plug-in's updateRow / deleteRow count by; a new row in a draft has id "" and index 0.
 */
export interface SyncTable {
  key: string;
  name: string;
  columns: string[];
  rows: { id: string; index: number; cells: string[] }[];
}

const ID = "row_id";
const ESCAPES: Record<string, string> = { "\\": "\\", "|": "|", n: "\n", r: "\r", t: "\t", " ": " " };

/** A cell's text inside a Markdown table: pipes, backslashes and line breaks escaped, edge spaces kept. */
function writeCell(value: string) {
  const escaped = value.replace(/[\\|\n\r\t]/g, (c) =>
    c === "\n" ? "\\n" : c === "\r" ? "\\r" : c === "\t" ? "\\t" : "\\" + c,
  );
  return escaped.replace(/^ +| +$/g, (spaces) => "\\ ".repeat(spaces.length));
}
/** The cells of one table line; whitespace around a cell is padding unless escaped. */
function readCells(line: string): string[] {
  const cells: string[] = [];
  let out = "",
    keep = 0,
    started = false,
    // Whether the line so far starts / ends with an unescaped pipe, ignoring spaces.
    leading: boolean | undefined,
    trailing = false;
  const end = () => {
    cells.push(out.slice(0, keep));
    out = "";
    keep = 0;
    started = false;
  };
  for (let i = 0; i < line.length; i++) {
    const c = line[i],
      space = c === " " || c === "\t";
    if (!space) {
      leading ??= c === "|";
      trailing = c === "|";
    }
    if (c === "\\" && i + 1 < line.length) {
      const next = line[++i];
      // Unknown escapes (Markdown's \* and the like) stay as written.
      out += ESCAPES[next] ?? "\\" + next;
      keep = out.length;
      started = true;
    } else if (c === "|") end();
    else if (!started && space) continue;
    else {
      out += c;
      started = true;
      if (!space) keep = out.length;
    }
  }
  end();
  // The outer pipes are optional.
  if (leading) cells.shift();
  if (trailing && cells.length) cells.pop();
  return cells;
}
const rowLine = (cells: string[]) => `| ${cells.map(writeCell).join(" | ")} |`;
/** Rows without a row_id are named by position, as `#3`. */
const keyOf = (row: SyncTable["rows"][number]) => row.id || `#${row.index}`;

/**
 * 数据库/<角色>/<聊天>/<表名>.md: a Markdown table whose first column is row_id. Editing cells
 * updates rows, a row with an empty row_id is inserted, and a removed line deletes its row. Columns
 * come from the plug-in's template and cannot change here.
 */
export const tableCodec = {
  render(table: SyncTable) {
    const header = [ID, ...table.columns];
    return [
      rowLine(header),
      `|${header.map(() => " --- ").join("|")}|`,
      ...table.rows.map((row) => rowLine([keyOf(row), ...row.cells])),
      "",
    ].join("\n");
  },
  parse(base: SyncTable, text: string): SyncTable {
    const lines = text.replace(/\r\n/g, "\n").split("\n"),
      header = [ID, ...base.columns],
      byKey = new Map(base.rows.map((row) => [keyOf(row), row])),
      seen = new Set<string>(),
      kept = new Map<string, string[]>(),
      added: string[][] = [];
    let state: "header" | "rule" | "rows" = "header";
    for (const [i, line] of lines.entries()) {
      const at = i + 1;
      if (!line.trim()) continue;
      if (state === "rule") {
        if (!/^[\s|:-]+$/.test(line) || !line.includes("-"))
          throw new SyncError("表头下一行应是分隔行，例如 | --- | --- |。", at);
        state = "rows";
        continue;
      }
      if (!line.includes("|")) throw new SyncError("表格之外不能写其他内容。", at);
      const cells = readCells(line);
      if (state === "header") {
        if (cells.length !== header.length || cells.some((c, j) => c !== header[j]))
          throw new SyncError(`表头应为「${header.join(" | ")}」；列由数据库插件的模板决定。`, at);
        state = "rule";
        continue;
      }
      if (cells.length !== header.length)
        throw new SyncError(`这一行有 ${cells.length} 列，表格有 ${header.length} 列。`, at);
      const [key, ...values] = cells;
      if (!key) {
        added.push(values);
        continue;
      }
      if (!byKey.has(key)) throw new SyncError(`没有 row_id 为「${key}」的行；新行请把 row_id 留空。`, at);
      if (seen.has(key)) throw new SyncError(`row_id「${key}」出现了两次。`, at);
      seen.add(key);
      kept.set(key, values);
    }
    if (state !== "rows") throw new SyncError("缺少表头和分隔行。", lines.length);
    return {
      ...base,
      rows: [
        // Rows keep the plug-in's order: there is no call to move a row.
        ...base.rows
          .filter((row) => kept.has(keyOf(row)))
          .map((row) => ({ ...row, cells: kept.get(keyOf(row))! })),
        ...added.map((cells) => ({ id: "", index: 0, cells })),
      ],
    };
  },
};
