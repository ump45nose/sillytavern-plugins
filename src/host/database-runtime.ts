import type { HostAdapter } from "./adapter";
import { readTables, type DbLocks, type DbRow, type DbTable } from "./database";

/** The database plug-in's API (龙血玄黄·数据库), as far as the workbench uses it. */
interface DatabaseApi {
  exportTableAsJson: () => unknown;
  registerTableUpdateCallback?: (fn: () => void) => void;
  unregisterTableUpdateCallback?: (fn: () => void) => void;
  registerTableFillStartCallback?: (fn: () => void) => void;
  getTableLockState?: (key: string) => DbLocks | null;
  toggleTableRowLock?: (key: string, row: number) => boolean;
  toggleTableColLock?: (key: string, col: number) => boolean;
  toggleTableCellLock?: (key: string, row: number, col: number) => boolean;
  updateRow?: (table: string, row: number, data: Record<string, string>) => Promise<boolean>;
  insertRow?: (table: string, data: Record<string, string>) => Promise<number>;
  deleteRow?: (table: string, row: number) => Promise<boolean>;
  triggerUpdate?: () => Promise<boolean>;
  openSettings?: () => Promise<boolean>;
  getUpdateConfigParams?: () => { autoUpdateFrequency?: number } | null;
}
const api = () => (window as any).AutoCardUpdaterAPI as DatabaseApi | undefined;
const v2 = () => (window as any).AutoCardUpdaterV2API as { open?: () => Promise<boolean> } | undefined;

export interface DatabaseState {
  /** The plug-in is installed and has published its API. */
  available: boolean;
  tables: DbTable[];
  /** The plug-in is filling tables (between its fill-start and table-update callbacks). */
  filling: boolean;
  /** Auto-fill runs every this many floors; 0 when the plug-in does not say. */
  frequency: number;
  error: string;
}

/**
 * The plug-in keeps callbacks for the page's life and drops duplicates by identity, so one relay
 * per page is registered and forwards to whichever runtime is mounted.
 */
const RELAY = Symbol.for("workbench.database.relay");
interface Relay {
  update: () => void;
  fill: () => void;
  target: DatabaseRuntime | null;
}
function relay(): Relay {
  const w = window as any;
  w[RELAY] ??= {
    target: null,
    update: () => w[RELAY].target?.updated(),
    fill: () => w[RELAY].target?.fillStarted(),
  } satisfies Relay;
  return w[RELAY];
}

/** The chat's database tables: read on every plug-in update, written through the plug-in's API. */
export class DatabaseRuntime {
  state: DatabaseState = { available: false, tables: [], filling: false, frequency: 0, error: "" };
  private listeners = new Set<() => void>();
  private hooked: DatabaseApi | null = null;
  constructor(host: HostAdapter) {
    relay().target = this;
    // The plug-in may load after the workbench; it is in place by the time a chat opens.
    for (const name of ["APP_READY", "CHAT_CHANGED"]) host.listen(name, () => this.updated());
    this.read();
  }
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  private set(patch: Partial<DatabaseState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn());
  }
  /** Re-reads every table and its locks; hooks the plug-in's callbacks the first time it is seen. */
  read() {
    const db = api();
    if (!db || typeof db.exportTableAsJson !== "function") {
      if (this.state.available) this.set({ available: false, tables: [], error: "" });
      return;
    }
    if (this.hooked !== db) {
      this.hooked = db;
      db.registerTableUpdateCallback?.(relay().update);
      db.registerTableFillStartCallback?.(relay().fill);
    }
    try {
      const tables = readTables(db.exportTableAsJson(), (key) => db.getTableLockState?.(key) ?? null);
      this.set({
        available: true,
        tables,
        frequency: Number(db.getUpdateConfigParams?.()?.autoUpdateFrequency) || 0,
        error: "",
      });
    } catch (error) {
      this.set({
        available: true,
        error: `读取数据库失败：${error instanceof Error ? error.message : String(error)}`,
      });
    }
  }
  fillStarted() {
    this.set({ filling: true });
  }
  /** The plug-in reports changed tables, which also ends a fill. */
  updated() {
    this.state = { ...this.state, filling: false };
    this.read();
  }
  table(key: string) {
    return this.state.tables.find((t) => t.key === key);
  }
  private need<K extends keyof DatabaseApi>(name: K): NonNullable<DatabaseApi[K]> {
    const fn = api()?.[name];
    if (typeof fn !== "function") throw new Error("数据库插件不支持此操作，请更新插件。");
    return fn.bind(api()) as NonNullable<DatabaseApi[K]>;
  }
  /** The row's current position: fills and deletes elsewhere can move it since it was read. */
  private position(table: DbTable, row: DbRow) {
    const current = this.table(table.key)?.rows.find((r) =>
      row.id ? r.id === row.id : r.index === row.index,
    );
    if (!current) throw new Error("这一行已不在表中，可能刚被插件改写。");
    return current.index;
  }
  /** Writes the changed columns of a row. */
  async saveRow(table: DbTable, row: DbRow, patch: Record<string, string>) {
    if (!Object.keys(patch).length) return;
    const ok = await this.need("updateRow")(table.name, this.position(table, row), patch);
    this.read();
    if (!ok) throw new Error("数据库拒绝了这次写入：目标可能已被锁定，或插件正在填表。");
  }
  /** Appends a row; returns its row_id once the plug-in has stored it. */
  async insertRow(table: DbTable, data: Record<string, string>) {
    const index = await this.need("insertRow")(table.name, data);
    this.read();
    if (index < 0) throw new Error("数据库没有接受新行，插件可能正在填表。");
    return this.table(table.key)?.rows.find((r) => r.index === index)?.id ?? "";
  }
  async deleteRow(table: DbTable, row: DbRow) {
    const ok = await this.need("deleteRow")(table.name, this.position(table, row));
    this.read();
    if (!ok) throw new Error("数据库拒绝删除：这一行或其中的格子已被锁定。");
  }
  /** Locks are stored by the plug-in at once; they do not notify, so the tables are read again. */
  toggleLock(table: DbTable, target: { row?: DbRow; col?: number }) {
    const { row, col } = target;
    const ok =
      row && col !== undefined
        ? this.need("toggleTableCellLock")(table.key, this.position(table, row) - 1, col)
        : row
          ? this.need("toggleTableRowLock")(table.key, this.position(table, row) - 1)
          : this.need("toggleTableColLock")(table.key, col!);
    this.read();
    if (!ok) throw new Error("锁定没有生效，请在数据库插件里检查这张表。");
  }
  /** Asks the plug-in to fill the tables from the latest floors now. */
  async fill() {
    this.fillStarted();
    try {
      await this.need("triggerUpdate")();
    } finally {
      this.updated();
    }
  }
  /** The plug-in's own window: API, prompts, templates and update settings live there. */
  async openSettings() {
    const open = v2()?.open;
    if (typeof open === "function") await open.call(v2());
    else await this.need("openSettings")();
  }
  dispose() {
    if (relay().target === this) relay().target = null;
    this.hooked?.unregisterTableUpdateCallback?.(relay().update);
    this.listeners.clear();
  }
}
