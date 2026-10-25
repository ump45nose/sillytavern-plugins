import { useEffect, useRef, useState } from "react";
import { Plus, Search, Upload, SquareArrowOutUpRight, X } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import type { Item } from "../host/types";
import { Dialog, Empty, Notice, useTask, useHostSlices, withoutChat } from "../ui/common";
import Resources from "./Resources";
import World from "./World";
import { guards } from "../host/bus";
import { resourceLabels } from "../host/labels";
type Kind = "preset" | "connection" | "world";
export default function ResourceManager({
  host,
  kind,
  initial,
  onPosition,
  selection,
  onSelection,
  view,
}: {
  host: HostAdapter;
  kind: Kind;
  initial?: string;
  onPosition: (id: string) => void;
  selection: string[];
  onSelection: (ids: string[]) => void;
  view?: "prompts";
}) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    items = snap.resources[kind],
    label = resourceLabels[kind];
  const [id, setId] = useState(initial || snap.current[kind] || items[0]?.id || ""),
    [query, setQuery] = useState(""),
    [confirmDelete, setConfirmDelete] = useState(false),
    [message, setMessage] = useState("");
  const all = useRef<HTMLInputElement>(null),
    valid = selection.filter((s) => items.some((i) => i.id === s));
  useEffect(() => {
    if (all.current) all.current.indeterminate = valid.length > 0 && valid.length < items.length;
  }, [valid.length, items.length]);
  useEffect(() => {
    if (!items.some((i) => i.id === id)) setId(items[0]?.id || "");
  }, [items, id]);
  useEffect(() => {
    onPosition(id);
  }, [id]);
  const browse = (next: string) => {
    if (guards.check({ preserveDrafts: true })) setId(next);
  };
  const batch = (action: "copy" | "delete" | "export") =>
    task.run(async () => {
      const result = await host.batchResource(kind, valid, action);
      onSelection(
        action === "copy"
          ? [...result.created, ...result.errors.map((e) => e.id)]
          : action === "delete"
            ? result.errors.map((e) => e.id)
            : valid,
      );
      setMessage(
        `已${action === "copy" ? "复制" : action === "delete" ? "删除" : "导出"} ${result.done.length} 个${label}`,
      );
      if (result.errors.length)
        task.setError(
          result.errors
            .map((e) => `${items.find((i) => i.id === e.id)?.name || e.id}：${e.message}`)
            .join("；"),
        );
    });
  // The row's second line says what the item is, not that it is open: the highlight already says that.
  const rowDetail = (item: Item) =>
    kind === "connection"
      ? [...new Set([item.detail, item.data?.model].filter(Boolean))].join(" · ")
      : kind === "world"
        ? item.active
          ? "已启用"
          : "未启用"
        : item.id === snap.current.preset
          ? "运行中"
          : item.detail || label;
  const create = () => {
    if (kind === "connection") {
      task.run(() => host.click("#create_connection_profile"));
      return;
    }
    const name = prompt(`新${label}名称`);
    if (name) task.run(async () => setId(await host.createResource(kind, name)));
  };
  return (
    <div className={`wb-resource-manager manage-${kind}`}>
      <Notice error={task.error} />
      {message && (
        <p className="wb-batch-status" role="status">
          {message}
        </p>
      )}
      <div className="wb-manager-grid">
        <aside className="wb-manager-resources">
          <header className="wb-manager-head">
            <h3>{label}</h3>
            <span className="wb-grow" />
            {kind !== "connection" && (
              <label className="wb-upload-button wb-manager-icon" title={`导入${label}`}>
                <Upload size={15} />
                <input
                  type="file"
                  accept=".json"
                  aria-label={`导入${label}`}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file)
                      task.run(async () =>
                        setId(
                          await host.createResource(
                            kind,
                            file.name.replace(/\.json$/i, ""),
                            JSON.parse(await file.text()),
                          ),
                        ),
                      );
                    e.target.value = "";
                  }}
                />
              </label>
            )}
            <button
              className="wb-manager-icon is-raised"
              aria-label={`新建${label}`}
              title={`新建${label}`}
              disabled={task.busy || snap.busy}
              onClick={create}
            >
              <Plus size={15} />
            </button>
          </header>
          <div className={`wb-batch-toolbar ${valid.length ? "is-active" : ""}`}>
            <label className="wb-check">
              <input
                ref={all}
                type="checkbox"
                aria-label={`全选${label}`}
                checked={!!items.length && valid.length === items.length}
                disabled={task.busy || !items.length}
                onChange={(e) => onSelection(e.target.checked ? items.map((i) => i.id) : [])}
              />
              {valid.length ? `已选 ${valid.length}` : "全选"}
            </label>
            <small className={valid.length ? "is-selected" : ""} role="status">
              已选 {valid.length} / {items.length}
            </small>
            <div className="wb-batch-actions">
              <button disabled={!valid.length || task.busy || snap.busy} onClick={() => batch("copy")}>
                复制
              </button>
              <button disabled={!valid.length || task.busy} onClick={() => batch("export")}>
                导出
              </button>
              <button
                className="is-danger"
                disabled={!valid.length || task.busy || snap.busy}
                onClick={() => setConfirmDelete(true)}
              >
                删除
              </button>
              <button
                className="wb-manager-icon"
                aria-label="取消资源选择"
                title="取消选择"
                disabled={!valid.length || task.busy}
                onClick={() => onSelection([])}
              >
                <X size={14} />
              </button>
            </div>
          </div>
          <label className="wb-search">
            <Search size={15} />
            <input
              aria-label={`搜索全部${label}`}
              placeholder={`搜索${label}`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="wb-manager-list">
            {items
              .filter((i) => i.name.toLowerCase().includes(query.toLowerCase()))
              .map((item) => (
                <div
                  key={item.id}
                  className={`wb-manager-row ${id === item.id ? "is-editing" : ""} ${valid.includes(item.id) ? "is-selected" : ""}`}
                >
                  <label>
                    <input
                      type="checkbox"
                      aria-label={`选择 ${item.name}`}
                      checked={valid.includes(item.id)}
                      disabled={task.busy}
                      onChange={(e) =>
                        onSelection(
                          e.target.checked ? [...valid, item.id] : valid.filter((s) => s !== item.id),
                        )
                      }
                    />
                  </label>
                  <button
                    aria-label={`编辑 ${item.name}`}
                    aria-pressed={id === item.id}
                    disabled={task.busy}
                    onClick={() => browse(item.id)}
                  >
                    <strong>{item.name}</strong>
                    <small>{rowDetail(item)}</small>
                  </button>
                </div>
              ))}
            {!items.length && <Empty>还没有{label}</Empty>}
          </div>
          <button className="wb-editor-slot" disabled>
            <SquareArrowOutUpRight size={14} />
            外部编辑器 · 预留
          </button>
        </aside>
        <div className="wb-manager-editor" inert={task.busy}>
          {kind === "world" ? (
            <World key={id} host={host} initial={id} deep managed />
          ) : (
            <Resources
              key={kind + ":" + id}
              host={host}
              kind={kind}
              initial={id}
              deep
              view={view}
              onSelection={(next) => {
                if (next !== id) setId(next);
              }}
            />
          )}
        </div>
      </div>
      {confirmDelete && (
        <Dialog title={`删除所选 ${valid.length} 个${label}？`} onClose={() => setConfirmDelete(false)}>
          <div className="wb-confirm-body">
            <p>以下资源将被删除，失败的项目会保留。</p>
            <p className="wb-confirm-names">
              {valid.map((i) => items.find((x) => x.id === i)?.name).join(" · ")}
            </p>
            <div className="wb-flex">
              <span className="wb-grow" />
              <button onClick={() => setConfirmDelete(false)}>取消</button>
              <button
                className="wb-primary"
                onClick={() => {
                  setConfirmDelete(false);
                  batch("delete");
                }}
              >
                确认删除
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
