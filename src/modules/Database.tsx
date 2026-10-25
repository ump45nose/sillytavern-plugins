import React, { useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Lock, LockOpen, Plus, RefreshCw, Search, Settings2, Table2, Trash2, X } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import {
  changedCells,
  lockCount,
  lockOf,
  matchRows,
  rowLabel,
  rowLocked,
  wideColumns,
  type DbRow,
  type DbTable,
  type LockLevel,
} from "../host/database";
import type { DatabaseState } from "../host/database-runtime";
import { guards } from "../host/bus";
import { Empty, Notice, useLeaveGuard, useTask } from "../ui/common";
import { SaveBar } from "../ui/ResourceControls";
import { ResourcePicker, ResourceRailContext } from "../ui/ResourcePicker";
import { useDatabase } from "../ui/useDatabase";

/** A row's identity across plug-in updates: its row_id, or its position when it has none. */
const rowKey = (row: DbRow) => row.id || `#${row.index}`;
const NEW = "\u0000new";
const lockName: Record<NonNullable<LockLevel>, string> = { row: "整行", col: "整列", cell: "此格" };
const tableDetail = (t: DbTable) => `${t.rows.length} 行${lockCount(t) ? ` · 锁定 ${lockCount(t)}` : ""}`;

/**
 * The database plug-in's tables. In the right panel: tables in the rail, rows as records, and the
 * open row as a form with its columns stacked. As the settings page (`deep`): a list column and the
 * whole table as a grid whose open row unfolds into the same form.
 */
export default function Database({
  host,
  deep = false,
  initial,
  onSelection,
  leave,
}: {
  host: HostAdapter;
  deep?: boolean;
  /** The table key to open on. */
  initial?: string;
  onSelection?: (key: string) => void;
  /** Closes the surface around this page before the plug-in's own window opens; false keeps it. */
  leave?: () => boolean;
}) {
  const db = useDatabase(host),
    rail = useContext(ResourceRailContext);
  const [key, setKey] = useState(initial || ""),
    [open, setOpen] = useState(""),
    [query, setQuery] = useState(""),
    [noteOpen, setNoteOpen] = useState(false);
  const table = db.tables.find((t) => t.key === key) ?? db.tables[0];
  useEffect(() => {
    if (table) onSelection?.(table.key);
  }, [table?.key]);
  // A one-row table (global state, the protagonist) is a form at once.
  const single = !!table && table.rows.length === 1 && open !== NEW;
  const current = table && (single ? table.rows[0] : table.rows.find((r) => rowKey(r) === open));
  const choose = (next: string) => {
    if (next === table?.key || !guards.check({ preserveDrafts: true })) return;
    setKey(next);
    setOpen("");
    setQuery("");
    setNoteOpen(false);
  };
  const openRow = (next: string) => {
    if (next !== open && guards.check({ preserveDrafts: true })) setOpen(next);
  };
  if (!db.available)
    return (
      <Empty icon={<Table2 size={22} />} title="没有检测到数据库插件">
        安装并启用「数据库」插件后，这里会显示本聊天的表格。
      </Empty>
    );
  const status = <DbStatus host={host} db={db} leave={leave} />;
  if (!table)
    return (
      <div className={`wb-db ${deep ? "is-deep" : ""}`}>
        {deep && status}
        <Empty icon={<Table2 size={22} />} title="还没有表格">
          在数据库设置里选择模板，插件会在之后的回复里开始填表。
        </Empty>
        {!deep && status}
      </div>
    );
  const rows = matchRows(table, query),
    meta = `${table.rows.length} 行 · ${table.columns.length} 列${lockCount(table) ? ` · 锁定 ${lockCount(table)}` : ""}`;
  const note = table.note && (
    <button
      className={`wb-db-note ${noteOpen ? "is-open" : ""}`}
      aria-expanded={noteOpen}
      title={noteOpen ? "收起说明" : "展开说明"}
      onClick={() => setNoteOpen(!noteOpen)}
    >
      <span>{table.note}</span>
    </button>
  );
  const editor = (row: DbRow | null, layout: "stack" | "grid") => (
    <RowEditor
      key={`${table.key}:${row ? rowKey(row) : NEW}`}
      host={host}
      table={table}
      row={row}
      layout={layout}
      onClose={single && row ? undefined : () => setOpen("")}
      onCreated={(id) => setOpen(id || "")}
    />
  );
  if (deep)
    return (
      <div className="wb-db is-deep">
        <aside className="wb-db-column" aria-label="数据表">
          <h3>数据库</h3>
          {status}
          <ul className="wb-db-tables">
            {db.tables.map((t) => (
              <li key={t.key} className={t.key === table.key ? "is-active" : ""}>
                <button aria-pressed={t.key === table.key} onClick={() => choose(t.key)}>
                  <strong>{t.name}</strong>
                  <small>{tableDetail(t)}</small>
                </button>
              </li>
            ))}
          </ul>
        </aside>
        <section className="wb-db-sheet" aria-label={`数据表：${table.name}`}>
          <header className="wb-db-sheet-head">
            <h2>{table.name}</h2>
            <small>{meta}</small>
            <span className="wb-grow" />
            <label className="wb-search">
              <Search size={15} />
              <input
                aria-label="搜索行"
                placeholder="搜索行"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <button className="wb-db-add" onClick={() => openRow(NEW)}>
              <Plus size={15} />
              新增行
            </button>
          </header>
          {note}
          <Grid
            host={host}
            table={table}
            rows={rows}
            open={open === NEW ? NEW : current ? rowKey(current) : ""}
            openRow={openRow}
            editor={editor}
          />
        </section>
      </div>
    );
  return (
    <div className="wb-db">
      <header className="wb-panel-heading">
        <div className="wb-panel-heading-copy">
          {rail ? (
            <ResourcePicker
              label="数据表"
              items={db.tables.map((t) => ({ id: t.key, name: t.name, detail: tableDetail(t) }))}
              id={table.key}
              active=""
              choose={choose}
              use={choose}
              extras={{ top: status }}
            />
          ) : (
            <h2 className="wb-panel-title">{table.name}</h2>
          )}
          <p className="wb-panel-sub">{meta}</p>
        </div>
        <button className="wb-panel-action" onClick={() => openRow(NEW)}>
          <Plus size={15} />
          新增行
        </button>
      </header>
      {!rail && (
        <>
          <div className="wb-db-chips" role="group" aria-label="数据表">
            {db.tables.map((t) => (
              <button key={t.key} aria-pressed={t.key === table.key} onClick={() => choose(t.key)}>
                {t.name}
              </button>
            ))}
          </div>
          {status}
        </>
      )}
      {note}
      {!single && table.rows.length > 6 && (
        <label className="wb-panel-search">
          <Search size={15} />
          <input
            aria-label="搜索行"
            placeholder="搜索行"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      )}
      {!single && (
        <ul className={`wb-db-rows ${current || open === NEW ? "is-shared" : ""}`} aria-label="行">
          {rows.map((row) => {
            const { title, summary } = rowLabel(row),
              on = !!current && rowKey(current) === rowKey(row);
            return (
              <li key={rowKey(row)} className={on ? "is-selected" : ""}>
                <button
                  aria-pressed={on}
                  aria-label={`编辑第 ${row.index} 行 ${title}`}
                  onClick={() => openRow(rowKey(row))}
                >
                  <span className="wb-db-no">{row.index}</span>
                  <strong>{title || "（空行）"}</strong>
                  <small>{summary}</small>
                </button>
                {rowLocked(table, row) && (
                  <Lock size={13} className="wb-db-row-lock" aria-label="含锁定内容" />
                )}
              </li>
            );
          })}
          {!table.rows.length && <li className="wb-db-empty">这张表还没有数据</li>}
          {!!table.rows.length && !rows.length && <li className="wb-db-empty">没有符合条件的行</li>}
        </ul>
      )}
      {open === NEW ? editor(null, "stack") : current && editor(current, "stack")}
    </div>
  );
}

/** Fill state and the plug-in's own actions: fill now, and its settings window. */
function DbStatus({ host, db, leave }: { host: HostAdapter; db: DatabaseState; leave?: () => boolean }) {
  const task = useTask();
  return (
    <div className={`wb-db-status ${db.filling ? "is-filling" : ""}`}>
      <p role="status">
        <i aria-hidden="true" />
        {db.filling ? "数据库填表中…" : db.frequency ? `每 ${db.frequency} 层自动填表` : "自动填表"}
      </p>
      <div>
        <button disabled={db.filling || task.busy} onClick={() => task.run(() => host.database.fill())}>
          <RefreshCw size={14} />
          立即填表
        </button>
        <button
          aria-label="数据库设置"
          title="数据库设置 · 插件自己的窗口：API、提示词、模板与更新频率"
          onClick={() =>
            task.run(async () => {
              if (leave && !leave()) return;
              await host.database.openSettings();
            })
          }
        >
          <Settings2 size={15} />
        </button>
      </div>
      <Notice error={task.error || db.error} />
    </div>
  );
}

/** The whole table: sticky header and number column, two-line cells, the open row unfolded below it. */
function Grid({
  host,
  table,
  rows,
  open,
  openRow,
  editor,
}: {
  host: HostAdapter;
  table: DbTable;
  rows: DbRow[];
  open: string;
  openRow: (key: string) => void;
  editor: (row: DbRow | null, layout: "stack" | "grid") => React.ReactNode;
}) {
  const task = useTask(),
    wide = wideColumns(table).map((w) => (w ? 300 : 160));
  // Every row is its own grid at one shared width, so fixed minimums keep the columns aligned.
  const columns = `56px ${wide.map((px) => `minmax(${px}px, ${px / 160}fr)`).join(" ")}`,
    width = 56 + wide.reduce((a, b) => a + b, 0);
  const lock = (target: { row?: DbRow; col?: number }) =>
    task.run(() => host.database.toggleLock(table, target));
  return (
    <div
      className="wb-db-grid"
      style={{ "--wb-db-columns": columns, "--wb-db-width": `${width}px` } as React.CSSProperties}
    >
      <Notice error={task.error} />
      <div className="wb-db-grid-row is-head">
        <span>#</span>
        {table.columns.map((name, c) => {
          const locked = table.locks.cols.includes(c);
          return (
            <span key={c} className={locked ? "is-locked" : ""}>
              <span>{name}</span>
              <button
                className="wb-db-lock"
                aria-pressed={locked}
                aria-label={`${locked ? "解锁" : "锁定"}整列：${name}`}
                title={locked ? "整列已锁定 · 点击解锁" : "锁定整列：AI 和编辑都不再改动这一列"}
                onClick={() => lock({ col: c })}
              >
                {locked ? <Lock size={13} /> : <LockOpen size={13} />}
              </button>
            </span>
          );
        })}
      </div>
      {open === NEW && <div className="wb-db-grid-editor">{editor(null, "grid")}</div>}
      {rows.map((row) => {
        const key = rowKey(row),
          on = open === key,
          locked = table.locks.rows.includes(row.index - 1);
        return (
          <React.Fragment key={key}>
            <div
              className={`wb-db-grid-row ${on ? "is-open" : ""}`}
              role="button"
              tabIndex={0}
              aria-expanded={on}
              aria-label={`第 ${row.index} 行 ${rowLabel(row).title}`}
              onClick={() => openRow(on ? "" : key)}
              onKeyDown={(e) => {
                if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  openRow(on ? "" : key);
                }
              }}
            >
              <span className={locked ? "is-locked" : ""}>
                {row.index}
                <button
                  className="wb-db-lock"
                  aria-pressed={locked}
                  aria-label={`${locked ? "解锁" : "锁定"}第 ${row.index} 行`}
                  title={locked ? "整行已锁定 · 点击解锁" : "锁定整行"}
                  onClick={(e) => {
                    e.stopPropagation();
                    lock({ row });
                  }}
                >
                  {locked ? <Lock size={13} /> : <LockOpen size={13} />}
                </button>
              </span>
              {row.cells.map((cell, c) => (
                <span key={c} className={lockOf(table, row, c) ? "is-locked" : ""}>
                  <span>{cell}</span>
                </span>
              ))}
            </div>
            {on && <div className="wb-db-grid-editor">{editor(row, "grid")}</div>}
          </React.Fragment>
        );
      })}
      {!table.rows.length && <p className="wb-db-empty">这张表还没有数据</p>}
      {!!table.rows.length && !rows.length && <p className="wb-db-empty">没有符合条件的行</p>}
    </div>
  );
}

/**
 * One row as a form: columns stacked (or two across in the grid), each with its lock. Edits stay
 * a draft until saved; locks apply at once. A new row is inserted only when saved.
 */
function RowEditor({
  host,
  table,
  row,
  layout,
  onClose,
  onCreated,
}: {
  host: HostAdapter;
  table: DbTable;
  row: DbRow | null;
  layout: "stack" | "grid";
  onClose?: () => void;
  onCreated: (id: string) => void;
}) {
  const task = useTask(),
    source = row?.cells ?? table.columns.map(() => ""),
    [base, setBase] = useState(source),
    [draft, setDraft] = useState(source),
    [confirming, setConfirming] = useState(false),
    [saved, setSaved] = useState("");
  const dirty = draft.some((value, i) => value !== base[i]),
    wide = wideColumns(table);
  // The plug-in rewrites rows while filling: fields the user has not touched follow it.
  const sourceKey = JSON.stringify(source);
  const last = useRef(sourceKey);
  useLayoutEffect(() => {
    if (last.current === sourceKey) return;
    last.current = sourceKey;
    setDraft((d) => source.map((value, i) => (d[i] !== base[i] ? d[i] : value)));
    setBase(source);
  }, [sourceKey]);
  useLeaveGuard(dirty, () => confirm("这一行有未保存的修改，放弃这些修改？"));
  const save = () =>
    task.run(async () => {
      if (!row) {
        const data = Object.fromEntries(
          table.columns.map((name, i) => [name, draft[i]] as const).filter(([, value]) => value.trim()),
        );
        if (!Object.keys(data).length) throw new Error("新行至少要填写一列。");
        const id = await host.database.insertRow(table, data);
        setBase(draft);
        onCreated(id);
        return;
      }
      await host.database.saveRow(table, row, changedCells(table.columns, base, draft));
      setBase(draft);
      setSaved("已保存");
    });
  const lock = (target: { row?: DbRow; col?: number }) =>
    task.run(() => host.database.toggleLock(table, target));
  const title = rowLabel({ id: "", index: 0, cells: draft }).title,
    wholeRow = !!row && table.locks.rows.includes(row.index - 1),
    undeletable = !!row && rowLocked(table, row);
  return (
    <article className={`wb-db-editor is-${layout}`} aria-label={row ? `编辑第 ${row.index} 行` : "新增一行"}>
      <header>
        <strong>{row ? title || `第 ${row.index} 行` : "新增一行"}</strong>
        {row && !confirming && (
          <>
            <button
              className={`wb-db-chip ${wholeRow ? "is-on" : ""}`}
              aria-pressed={wholeRow}
              title={
                wholeRow
                  ? "整行已锁定：AI 和编辑都不会改动 · 点击解锁"
                  : "锁定整行：AI 和编辑都不再改动这一行"
              }
              disabled={task.busy}
              onClick={() => lock({ row })}
            >
              {wholeRow ? <Lock size={13} /> : <LockOpen size={13} />}
              {wholeRow ? "整行已锁定" : "锁定整行"}
            </button>
            <button
              className="wb-db-icon is-danger"
              aria-label="删除这一行"
              title={undeletable ? "这一行含锁定内容，解锁后才能删除" : "删除这一行"}
              disabled={undeletable || task.busy}
              onClick={() => setConfirming(true)}
            >
              <Trash2 size={15} />
            </button>
          </>
        )}
        {confirming && (
          <span className="wb-db-confirm" role="group" aria-label="确认删除">
            删除这一行？
            <button onClick={() => setConfirming(false)}>取消</button>
            <button
              className="is-danger"
              disabled={task.busy}
              onClick={() =>
                task.run(async () => {
                  await host.database.deleteRow(table, row!);
                  onClose?.();
                })
              }
            >
              删除
            </button>
          </span>
        )}
        {onClose && !confirming && (
          <button className="wb-db-icon" aria-label="收起这一行" title="收起" onClick={onClose}>
            <X size={15} />
          </button>
        )}
      </header>
      <Notice error={task.error} />
      <div className="wb-db-fields">
        {table.columns.map((name, c) => {
          const level = row ? lockOf(table, row, c) : null,
            long = wide[c] || draft[c].length > 40;
          return (
            <div key={c} className={`wb-db-field ${level ? "is-locked" : ""} ${long ? "is-long" : ""}`}>
              <div className="wb-db-field-head">
                <span>{name}</span>
                {row && (
                  <button
                    className="wb-db-lock"
                    aria-pressed={!!level}
                    aria-label={`${level ? "解锁" : "锁定"}${lockName[level ?? "cell"]}：${name}`}
                    title={level ? `${lockName[level]}已锁定 · 点击解锁` : "锁定此格：AI 和编辑都不再改动它"}
                    disabled={task.busy}
                    onClick={() =>
                      lock(level === "row" ? { row } : level === "col" ? { col: c } : { row, col: c })
                    }
                  >
                    {level ? <Lock size={13} /> : <LockOpen size={13} />}
                  </button>
                )}
              </div>
              <textarea
                aria-label={name}
                rows={1}
                value={draft[c]}
                readOnly={!!level}
                onChange={(e) => setDraft(draft.map((v, i) => (i === c ? e.target.value : v)))}
              />
              {level && <small>{lockName[level]}已锁定，AI 和编辑都不会改动</small>}
            </div>
          );
        })}
      </div>
      <SaveBar
        dirty={dirty}
        busy={task.busy}
        message={saved}
        label={row ? "保存" : "添加这一行"}
        title={row ? "未保存的修改" : "新行尚未添加"}
        reset={() => {
          if (row) setDraft(base);
          else onClose?.();
        }}
        save={save}
      />
    </article>
  );
}
