import { useEffect, useRef, useState } from "react";
import { PencilLine, Plus, Search, Upload, SquareArrowOutUpRight, X } from "../ui/icons";
import { grouped, groupItems, organized, ungroupedLabel } from "../host/organize";
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
    [grouping, setGrouping] = useState<string | null>(null),
    [shelf, setShelf] = useState<"list" | "archived">("list"),
    [message, setMessage] = useState("");
  // Books and profiles split into the working list and the archived shelf; selection follows the shelf shown.
  const org = organized(kind) ? kind : null,
    groupKind = grouped(kind) ? kind : null,
    archivedCount = org ? items.filter((i) => i.archived).length : 0,
    shown = org ? items.filter((i) => !!i.archived === (shelf === "archived")) : items,
    filtered = shown.filter((i) => `${i.name} ${i.group ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const all = useRef<HTMLInputElement>(null),
    valid = selection.filter((s) => shown.some((i) => i.id === s));
  useEffect(() => {
    if (all.current) all.current.indeterminate = valid.length > 0 && valid.length < shown.length;
  }, [valid.length, shown.length]);
  useEffect(() => {
    if (shelf === "archived" && !archivedCount) setShelf("list");
  }, [shelf, archivedCount]);
  /** Items in use cannot be archived; the toolbar says which and why. */
  const blocked =
    org && shelf === "list"
      ? valid
          .map((s) => ({ id: s, uses: host.resourceUsage(org, s) }))
          .filter((x) => x.uses.length)
          .map((x) => `「${items.find((i) => i.id === x.id)?.name ?? x.id}」${x.uses.join("、")}`)
      : [];
  const archive = () =>
    task.run(async () => {
      if (!org) return;
      const on = shelf === "list",
        result = await host.archiveResources(org, valid, on);
      onSelection(result.errors.map((e) => e.id));
      setMessage(`已${on ? "归档" : "恢复"} ${result.done.length} 个${label}`);
      if (result.errors.length)
        task.setError(
          result.errors
            .map((e) => `${items.find((i) => i.id === e.id)?.name || e.id}：${e.message}`)
            .join("；"),
        );
    });
  const groupNames = [...new Set(items.map((i) => i.group).filter(Boolean))] as string[];
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
                checked={!!shown.length && valid.length === shown.length}
                disabled={task.busy || !shown.length}
                onChange={(e) => onSelection(e.target.checked ? shown.map((i) => i.id) : [])}
              />
              {valid.length ? `已选 ${valid.length}` : "全选"}
            </label>
            <small className={valid.length ? "is-selected" : ""} role="status">
              已选 {valid.length} / {shown.length}
            </small>
            <div className="wb-batch-actions">
              {groupKind && shelf === "list" && (
                <button disabled={!valid.length || task.busy} onClick={() => setGrouping("")}>
                  分组
                </button>
              )}
              {org && (
                <button
                  disabled={!valid.length || task.busy || !!blocked.length}
                  title={blocked.length ? "使用中的不能归档" : undefined}
                  onClick={archive}
                >
                  {shelf === "list" ? "归档" : "恢复"}
                </button>
              )}
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
          {!!blocked.length && (
            <p className="wb-batch-hint" role="status">
              正在使用，不能归档：{blocked.join("；")}
            </p>
          )}
          <label className="wb-search">
            <Search size={15} />
            <input
              aria-label={`搜索全部${label}`}
              placeholder={`搜索${label}`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          {org && (
            <div className="wb-rail-segment wb-manager-shelf" role="group" aria-label={`${label}列表范围`}>
              <button aria-pressed={shelf === "list"} onClick={() => setShelf("list")}>
                未归档 {items.length - archivedCount}
              </button>
              <button
                aria-pressed={shelf === "archived"}
                disabled={!archivedCount}
                onClick={() => setShelf("archived")}
              >
                已归档 {archivedCount}
              </button>
            </div>
          )}
          <div className="wb-manager-list">
            {(groupKind && shelf === "list" ? groupItems(filtered) : [{ name: "", items: filtered }]).map(
              (group, _, groups) => (
                <div className="wb-manager-section" key={group.name || "all"}>
                  {groupKind && shelf === "list" && (groups.length > 1 || group.name) && (
                    <GroupHeader
                      host={host}
                      kind={groupKind}
                      name={group.name}
                      ids={group.items.map((i) => i.id)}
                      selection={valid}
                      disabled={task.busy}
                      onSelection={onSelection}
                      run={task.run}
                    />
                  )}
                  {group.items.map((item) => (
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
                        <small>{item.archived ? "已归档" : rowDetail(item)}</small>
                      </button>
                    </div>
                  ))}
                </div>
              ),
            )}
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
      {grouping !== null && groupKind && (
        <Dialog title={`将所选 ${valid.length} 个${label}移入分组`} onClose={() => setGrouping(null)}>
          <form
            className="wb-confirm-body wb-group-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (!grouping.trim()) return;
              setGrouping(null);
              task.run(async () => {
                await host.setResourceGroup(groupKind, valid, grouping);
                setMessage(`已移入分组「${grouping.trim()}」`);
              });
            }}
          >
            <label>
              <span>分组名称</span>
              <input
                autoFocus
                list="wb-group-names"
                value={grouping}
                placeholder="新分组或已有分组"
                onChange={(e) => setGrouping(e.target.value)}
              />
              <datalist id="wb-group-names">
                {groupNames.map((g) => (
                  <option key={g} value={g} />
                ))}
              </datalist>
            </label>
            <div className="wb-flex">
              <button
                type="button"
                onClick={() => {
                  setGrouping(null);
                  task.run(async () => {
                    await host.setResourceGroup(groupKind, valid, "");
                    setMessage("已移出分组");
                  });
                }}
              >
                移出分组
              </button>
              <span className="wb-grow" />
              <button type="button" onClick={() => setGrouping(null)}>
                取消
              </button>
              <button className="wb-primary" type="submit" disabled={!grouping.trim()}>
                移入
              </button>
            </div>
          </form>
        </Dialog>
      )}
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

/** A group heading in the manager list: select the whole group, rename it, or dissolve it. */
function GroupHeader({
  host,
  kind,
  name,
  ids,
  selection,
  disabled,
  onSelection,
  run,
}: {
  host: HostAdapter;
  kind: Kind;
  name: string;
  ids: string[];
  selection: string[];
  disabled: boolean;
  onSelection: (ids: string[]) => void;
  run: (fn: () => Promise<unknown>) => unknown;
}) {
  const title = name || ungroupedLabel,
    picked = ids.filter((i) => selection.includes(i)).length;
  return (
    <div className="wb-manager-group">
      <input
        type="checkbox"
        aria-label={`选择分组 ${title}`}
        checked={picked === ids.length}
        ref={(node) => {
          if (node) node.indeterminate = picked > 0 && picked < ids.length;
        }}
        disabled={disabled}
        onChange={(e) =>
          onSelection(
            e.target.checked
              ? [...new Set([...selection, ...ids])]
              : selection.filter((i) => !ids.includes(i)),
          )
        }
      />
      <strong>{title}</strong>
      <small>{ids.length}</small>
      <span className="wb-grow" />
      {name && (
        <button
          className="wb-manager-icon"
          aria-label={`重命名分组 ${title}`}
          title="重命名分组"
          disabled={disabled}
          onClick={() => {
            const next = prompt("分组名称", name);
            if (next && next.trim() && next.trim() !== name)
              run(() => host.renameResourceGroup(kind, name, next));
          }}
        >
          <PencilLine size={13} />
        </button>
      )}
      {name && (
        <button
          className="wb-manager-icon"
          aria-label={`解散分组 ${title}`}
          title="解散分组"
          disabled={disabled}
          onClick={() => {
            if (confirm(`解散分组「${title}」，其中的${resourceLabels[kind]}变为未分组？`))
              run(() => host.setResourceGroup(kind, ids, ""));
          }}
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}
