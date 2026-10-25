/**
 * The database plug-in's tables as the workbench reads them. Pure: the runtime feeds it the
 * plug-in's export and lock states. An export is an object of `sheet_*` tables plus bookkeeping
 * entries; a table's content is a header row, then rows, and column 0 always holds the row_id.
 */

export interface DbRow {
  id: string;
  /** Position in the table's content: 1 is the first row, as updateRow / deleteRow count. */
  index: number;
  /** One per column, without the row_id. */
  cells: string[];
}
/** Locks as the plug-in reports them: 0-based data rows and columns, cells as "row:col". */
export interface DbLocks {
  rows: number[];
  cols: number[];
  cells: string[];
}
export interface DbTable {
  key: string;
  name: string;
  note: string;
  columns: string[];
  rows: DbRow[];
  locks: DbLocks;
}
export type LockLevel = "row" | "col" | "cell" | null;

const text = (value: unknown) => (value == null ? "" : String(value));
const noLocks: DbLocks = { rows: [], cols: [], cells: [] };

/** The tables of an export in the plug-in's order (orderNo, then export order). */
export function readTables(
  exported: unknown,
  locksOf: (key: string) => DbLocks | null = () => null,
): DbTable[] {
  if (!exported || typeof exported !== "object") return [];
  return Object.entries(exported as Record<string, any>)
    .filter(
      ([key, sheet]) =>
        key.startsWith("sheet_") && typeof sheet?.name === "string" && Array.isArray(sheet.content),
    )
    .map(([key, sheet], order) => ({ key, sheet, order }))
    .sort((a, b) => (a.sheet.orderNo ?? a.order) - (b.sheet.orderNo ?? b.order) || a.order - b.order)
    .map(({ key, sheet }) => {
      const [header = [], ...rows] = sheet.content as unknown[][];
      const width = Math.max(0, (Array.isArray(header) ? header.length : 1) - 1);
      const locks = locksOf(key);
      return {
        key,
        name: sheet.name,
        note: typeof sheet.sourceData?.note === "string" ? sheet.sourceData.note.trim() : "",
        columns: Array.from(
          { length: width },
          (_, i) => text((header as unknown[])[i + 1]).trim() || `列 ${i + 1}`,
        ),
        rows: rows.map((row, i) => ({
          id: text(Array.isArray(row) ? row[0] : "").trim(),
          index: i + 1,
          cells: Array.from({ length: width }, (_, c) => text(Array.isArray(row) ? row[c + 1] : "")),
        })),
        locks: locks
          ? {
              rows: (locks.rows || []).filter(Number.isInteger),
              cols: (locks.cols || []).filter(Number.isInteger),
              cells: (locks.cells || []).map(String),
            }
          : noLocks,
      };
    });
}

/** The row's title and summary: its first two filled cells. */
export function rowLabel(row: DbRow) {
  const filled = row.cells.map((c) => c.trim()).filter(Boolean);
  return { title: filled[0] ?? "", summary: filled[1] ?? "" };
}

/** Rows whose cells contain the query, ignoring case. */
export function matchRows(table: DbTable, query: string) {
  const q = query.trim().toLowerCase();
  return q ? table.rows.filter((row) => row.cells.some((c) => c.toLowerCase().includes(q))) : table.rows;
}

/** Which lock, if any, holds a cell; a row lock wins over a column lock, which wins over the cell's own. */
export function lockOf(table: DbTable, row: DbRow | null, col: number): LockLevel {
  const at = row ? row.index - 1 : -1;
  if (row && table.locks.rows.includes(at)) return "row";
  if (table.locks.cols.includes(col)) return "col";
  if (row && table.locks.cells.includes(`${at}:${col}`)) return "cell";
  return null;
}

/** How many targets of a table are locked. */
export const lockCount = (table: DbTable) =>
  table.locks.rows.length + table.locks.cols.length + table.locks.cells.length;

/** Whether a row holds any lock (the row itself or one of its cells). */
export const rowLocked = (table: DbTable, row: DbRow) =>
  table.locks.rows.includes(row.index - 1) ||
  table.locks.cells.some((key) => key.startsWith(`${row.index - 1}:`));

/** Columns whose draft differs from the base, as the column-name map updateRow takes. */
export function changedCells(columns: string[], base: string[], draft: string[]) {
  const patch: Record<string, string> = {};
  columns.forEach((name, i) => {
    if ((draft[i] ?? "") !== (base[i] ?? "")) patch[name] = draft[i] ?? "";
  });
  return patch;
}

/** Columns whose cells run long get a wide grid column. */
export function wideColumns(table: DbTable) {
  return table.columns.map((_, c) => {
    const lengths = table.rows.map((row) => row.cells[c]?.length ?? 0);
    return lengths.length > 0 && lengths.reduce((a, b) => a + b, 0) / lengths.length > 28;
  });
}
