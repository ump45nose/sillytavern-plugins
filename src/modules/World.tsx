import { Select } from "../ui/Select";
import React, { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Plus, Trash2, Search, X, Braces, BookMarked, ChevronLeft } from "../ui/icons";
import { SaveBar } from "../ui/ResourceControls";
import { EntryEditor, useMobileLayout } from "../ui/EntryEditor";
import { useTokenTally } from "../ui/tokens";
import { useWindow, WINDOW_FROM } from "../ui/useWindow";
import { activation, sameData, setActivation, validateBook } from "../host/model";
import type { Data } from "../host/types";
import type { HostAdapter } from "../host/adapter";
import {
  useTask,
  SearchBox,
  Notice,
  Empty,
  Field,
  useHostSlices,
  useLeaveGuard,
  withoutChat,
} from "../ui/common";
import { ResourcePicker } from "../ui/ResourcePicker";
import { EntryPortraits } from "../ui/EntryPortraits";
import { MdField } from "../ui/md/MdField";
import { isPathSafe } from "../host/cast";
import { unarchived } from "../host/organize";
const positions = [
  "角色定义之前",
  "角色定义之后",
  "作者注释之前",
  "作者注释之后",
  "指定深度",
  "示例之前",
  "示例之后",
  "Outlet",
];
const modeName: Record<string, string> = { keyword: "关键词", constant: "常驻", vector: "向量化" };
/** Row heights the windowed entry lists are laid out with (CSS keeps rows exactly this tall). */
const PANEL_ROW = 42,
  TABLE_ROW = 46;
/**
 * Lower-cased search text per entry. Entries are copy-on-write, so an unchanged entry keeps its object
 * and its cached text; a render filters a large book without rebuilding every entry's string.
 */
const titleText = new WeakMap<Data, string>(),
  fullText = new WeakMap<Data, string>();
const searchTitle = (e: Data) => {
  let text = titleText.get(e);
  if (text === undefined) titleText.set(e, (text = `${e.comment} ${e.key?.join(" ")}`.toLowerCase()));
  return text;
};
const searchFull = (e: Data) => {
  let text = fullText.get(e);
  if (text === undefined)
    fullText.set(e, (text = `${e.comment} ${e.key?.join(" ")} ${e.content}`.toLowerCase()));
  return text;
};
/** Copy-on-write: only the book, its entry map and the one entry are new objects. */
const withEntry = (book: Data, id: string, entry: Data) => ({
  ...book,
  entries: { ...book.entries, [id]: entry },
});
export default function World({
  host,
  deep,
  initial,
  entryTitle,
  managed,
  onSelection,
}: {
  host: HostAdapter;
  deep?: boolean;
  initial?: string;
  /** Opens on the entry with this title, at its portraits. */
  entryTitle?: string;
  managed?: boolean;
  onSelection?: (name: string) => void;
}) {
  const mobile = useMobileLayout();
  const snap = useHostSlices(host, withoutChat),
    task = useTask();
  const [name, setName] = useState(initial || snap.current.world || snap.resources.world[0]?.id || "");
  const cached = host.drafts.get("world:" + name);
  const [base, setBase] = useState<Data | null>(cached?.base ?? null),
    [draft, setDraft] = useState<Data | null>(cached?.draft ?? null),
    [entry, setEntry] = useState<string>(cached?.extra?.entry ?? ""),
    [query, setQuery] = useState(""),
    [bookQuery, setBookQuery] = useState(""),
    [tab, setTab] = useState(cached?.extra?.tab ?? "content"),
    [json, setJson] = useState(cached?.extra?.json ?? ""),
    [saved, setSaved] = useState(""),
    [scope, setScope] = useState("global"),
    [newKey, setNewKey] = useState<string | null>(null),
    [filter, setFilter] = useState("all"),
    [target, setTarget] = useState(entryTitle),
    [entryOpen, setEntryOpen] = useState(false);
  useEffect(() => {
    onSelection?.(name);
  }, [name]);
  // Edits never mutate base or draft, so the cache can hold them as they are.
  useLayoutEffect(() => {
    if (base && draft) host.drafts.set("world:" + name, { base, draft, extra: { json, tab, entry } });
  }, [name, base, draft, json, tab, entry]);
  const changed = useMemo(() => !!base && !!draft && !sameData(base, draft), [base, draft]),
    pretty = useMemo(() => (tab === "json" && draft ? JSON.stringify(draft, null, 2) : ""), [tab, draft]);
  const dirty = changed || (tab === "json" && Boolean(draft) && json !== pretty);
  useLeaveGuard(dirty);
  /** The book version base was read at; a clean editor rereads only when the book has changed since. */
  const loaded = useRef<{ name: string; version: number } | null>(null);
  const workspace = useRef<HTMLElement>(null);
  useEffect(() => {
    if (dirty) return;
    const version = host.resourceVersions.world;
    if (loaded.current?.name === name && loaded.current.version === version) return;
    let live = true;
    if (name)
      host
        .readBook(name)
        .then((data) => {
          if (live) {
            loaded.current = { name, version };
            setBase(data);
            setDraft(data);
            const wanted =
              target &&
              Object.entries<Data>(data.entries ?? {}).find(
                ([, e]) => String(e.comment ?? "").trim() === target,
              )?.[0];
            // Where the detail covers the table (phones, a narrow workspace) a book opens on its list.
            const covered =
              deep &&
              (document.body.classList.contains("wb-mobile") ||
                (workspace.current?.clientWidth ?? 1e4) <= 520);
            setEntry(
              (previous) =>
                wanted ||
                (data.entries?.[previous]
                  ? previous
                  : covered
                    ? ""
                    : (Object.keys(data.entries ?? {})[0] ?? "")),
            );
            if (target) {
              setTarget(undefined);
              if (wanted) setTab("portraits");
            }
            setJson(JSON.stringify(data, null, 2));
          }
        })
        .catch((e) => {
          if (live) task.setError(e.message);
        });
    return () => {
      live = false;
    };
  }, [name, host.resourceVersions.world, dirty]);
  const choose = (next: string) => {
    if (next === name) return;
    if (dirty && !confirm("切换世界书将放弃未保存修改，继续？")) return;
    host.drafts.delete("world:" + name);
    setTab("content");
    setEntryOpen(false);
    setBase(null);
    setDraft(null);
    setName(next);
  };
  const update = (patch: Data) => {
    if (!draft || !draft.entries[entry]) return;
    setDraft(withEntry(draft, entry, { ...draft.entries[entry], ...patch }));
    setSaved("");
  };
  const save = () =>
    task.run(async () => {
      if (!base || !draft) return;
      const candidate = tab === "json" ? JSON.parse(json) : draft;
      const result = await host.saveBook(name, base, candidate);
      // A renamed entry's portraits follow its title to the new folder; the book is saved either way.
      let moved = 0;
      try {
        for (const [id, before] of Object.entries<Data>(base.entries ?? {})) {
          const from = String(before.comment ?? "").trim(),
            to = String(result.entries?.[id]?.comment ?? "").trim();
          if (from && to && from !== to && isPathSafe(from) && isPathSafe(to))
            moved += await host.cast.move(name, from, to);
        }
        setSaved(moved ? `已保存 · ${moved} 张立绘随改名移动` : "已保存");
      } finally {
        // The saved book is current: saving must not trigger a reread of it.
        loaded.current = { name, version: host.resourceVersions.world };
        setBase(result);
        setDraft(result);
        setJson(JSON.stringify(result, null, 2));
      }
    });
  // Stable, so list rows that did not change skip rendering.
  const modeChange = useCallback((id: string, mode: string) => {
    setDraft((d) => d && withEntry(d, id, setActivation(d.entries[id], mode)));
    setSaved("");
  }, []);
  const toggleEntry = useCallback(
    (id: string, on: boolean) => setDraft((d) => d && withEntry(d, id, { ...d.entries[id], disable: !on })),
    [],
  );
  const entries = useMemo(
    () => (draft ? (Object.entries(draft.entries) as [string, Data][]) : []),
    [draft?.entries],
  );
  const selected = draft?.entries[entry];
  const needle = query.toLowerCase();
  /** The side panel searches titles and keywords; the table also searches text and filters by mode. */
  const panelShown = useMemo(
    () => (deep ? [] : entries.filter(([, e]) => searchTitle(e).includes(needle))),
    [deep, entries, needle],
  );
  const shown = useMemo(
    () =>
      deep
        ? entries.filter(
            ([, e]) => (filter === "all" || activation(e) === filter) && searchFull(e).includes(needle),
          )
        : [],
    [deep, entries, filter, needle],
  );
  const counts = useMemo(
    () =>
      entries.reduce<Record<string, number>>((n, [, e]) => {
        n[activation(e)] = (n[activation(e)] ?? 0) + 1;
        return n;
      }, {}),
    [entries],
  );
  const panelWindow = useWindow<HTMLUListElement>(panelShown.length, PANEL_ROW),
    tableWindow = useWindow<HTMLDivElement>(shown.length, TABLE_ROW);
  const tokenItems = useMemo(
    () => (deep ? entries.map(([id, e]) => [id, String(e.content ?? "")] as [string, string]) : []),
    [deep, entries],
  );
  // A long book counts the rows on screen and the open entry; its total waits for 统计 to count the rest.
  const [countAll, setCountAll] = useState(false);
  const counted = useMemo(
    () =>
      countAll || entries.length <= WINDOW_FROM
        ? null
        : [...shown.slice(tableWindow.first, tableWindow.last).map(([id]) => id), entry],
    [countAll, entries.length, shown, tableWindow.first, tableWindow.last, entry],
  );
  const { counts: entryTokens, complete: tokensComplete } = useTokenTally(host, tokenItems, 500, counted);
  // The open entry stays in view when it is opened from elsewhere (a portrait link, a new entry).
  const { reveal } = deep ? tableWindow : panelWindow,
    list = deep ? shown : panelShown;
  useEffect(() => {
    if (entry) reveal(list.findIndex(([id]) => id === entry));
  }, [entry, reveal]);
  const switchTab = (t: string) => {
    if (tab === "json") {
      try {
        const data = JSON.parse(json);
        validateBook(data);
        setDraft(data);
      } catch {
        task.setError("JSON 无法解析，请先修正。");
        return;
      }
    }
    if (t === "json") setJson(JSON.stringify(draft, null, 2));
    setTab(t);
  };
  const addEntry = () =>
    task.run(async () => {
      if (!draft) return;
      // SillyTavern adds the entry to the map it is given.
      const next = { ...draft, entries: { ...draft.entries } },
        item = await host.createEntry(name, next);
      setDraft(next);
      setEntry(String(item.uid));
      setEntryOpen(true);
    });
  const removeEntry = () => {
    if (!confirm("删除此条目？")) return;
    const { [entry]: _removed, ...rest } = draft!.entries;
    setDraft({ ...draft!, entries: rest });
    setEntry(Object.keys(rest)[0] ?? "");
  };
  const enabledBooks =
    scope === "global"
      ? snap.resources.world.filter((x) => x.active).map((x) => x.id)
      : host.characterBooks();
  const saveBar = (
    <SaveBar
      dirty={dirty}
      busy={task.busy}
      message={saved}
      reset={() => {
        if (!base) return;
        setDraft(base);
        setJson(JSON.stringify(base, null, 2));
        setSaved("");
      }}
      save={save}
    />
  );
  if (!deep) {
    const book = snap.resources.world.find((x) => x.id === name);
    return (
      <fieldset disabled={task.busy} className="wb-world-panel">
        <header className="wb-panel-heading">
          <div className="wb-panel-heading-copy">
            <ResourcePicker
              label="世界书"
              items={snap.resources.world}
              id={name}
              active={snap.current.world}
              choose={choose}
              use={choose}
              multiple={{
                selected: enabledBooks,
                toggle: (id, on) =>
                  task.run(() =>
                    scope === "global" ? host.toggleBook(id, on) : host.toggleCharacterBook(id, on),
                  ),
              }}
              extras={{
                grouped: true,
                groupToggle: (ids, on) =>
                  task.run(() =>
                    scope === "global" ? host.toggleBooks(ids, on) : host.toggleCharacterBooks(ids, on),
                  ),
                restore: (id) => task.run(() => host.archiveResources("world", [id], false)),
                top: (
                  <div className="wb-rail-segment" role="group" aria-label="世界书启用范围">
                    {[
                      ["global", "全局", "全局启用"],
                      ["character", "当前角色", "当前角色卡启用"],
                    ].map(([value, text, label]) => (
                      <button
                        key={value}
                        aria-label={label}
                        aria-pressed={scope === value}
                        disabled={value === "character" && !snap.character}
                        onClick={() => setScope(value)}
                      >
                        {text}
                      </button>
                    ))}
                  </div>
                ),
                caption: `已启用 ${enabledBooks.length} · 共 ${unarchived(snap.resources.world).length} 本`,
                create: {
                  label: "新建世界书",
                  run: () => {
                    const next = prompt("新世界书名称");
                    if (next) task.run(async () => choose(await host.createResource("world", next)));
                  },
                },
              }}
            />
            <p className="wb-panel-sub">
              {entries.length} 个条目 · {book?.active ? "全局启用" : "未全局启用"}
            </p>
          </div>
          <button className="wb-panel-action" disabled={!draft || tab === "json"} onClick={addEntry}>
            <Plus size={15} />
            新增条目
          </button>
        </header>
        <Notice error={task.error} />
        <label className="wb-panel-search">
          <Search size={15} />
          <input
            aria-label="搜索条目"
            placeholder="搜索条目名或关键词"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <ul className="wb-entries" aria-label="条目" ref={panelWindow.ref}>
          {panelWindow.before > 0 && <li className="wb-entries-gap" style={{ height: panelWindow.before }} />}
          {panelShown.slice(panelWindow.first, panelWindow.last).map(([id, e]) => (
            <EntryItem
              key={id}
              id={id}
              entry={e}
              selected={entry === id}
              locked={tab === "json"}
              onToggle={toggleEntry}
              onMode={modeChange}
              onOpen={(id) => {
                setEntry(id);
                setEntryOpen(true);
              }}
            />
          ))}
          {panelWindow.after > 0 && <li className="wb-entries-gap" style={{ height: panelWindow.after }} />}
          {!entries.length && (
            <li className="wb-entries-empty">{name ? "这本世界书还没有条目" : "选择或新建一本世界书"}</li>
          )}
        </ul>
        {selected && (
          <EntryEditor
            open={!mobile || entryOpen}
            title={`世界书条目：${selected.comment || entry}`}
            onClose={() => {
              setEntryOpen(false);
              if (!mobile) setEntry("");
            }}
            busy={task.busy}
            footer={
              mobile ? (
                <>
                  <Notice error={task.error} />
                  {saveBar}
                </>
              ) : undefined
            }
          >
            <article className="wb-entry-card" aria-label={`编辑条目：${selected.comment || entry}`}>
              <div className="wb-entry-card-head">
                <div className="wb-entry-tabs" role="tablist" aria-label="条目内容">
                  {["content", "trigger", "portraits", "json"].map((t) => (
                    <button key={t} role="tab" aria-selected={tab === t} onClick={() => switchTab(t)}>
                      {t === "content"
                        ? "正文"
                        : t === "trigger"
                          ? "触发条件"
                          : t === "portraits"
                            ? "立绘"
                            : "完整 JSON"}
                    </button>
                  ))}
                </div>
                <button
                  className="wb-entry-delete"
                  aria-label="删除条目"
                  title="删除条目"
                  disabled={tab === "json"}
                  onClick={removeEntry}
                >
                  <Trash2 size={15} />
                </button>
              </div>
              {tab === "portraits" ? (
                <EntryPortraits
                  host={host}
                  book={name}
                  title={String(base?.entries?.[entry]?.comment ?? "").trim()}
                  draftTitle={String(selected.comment ?? "")}
                />
              ) : tab === "json" ? (
                <textarea
                  className="wb-entry-text is-code"
                  aria-label="世界书 JSON"
                  value={json}
                  onChange={(e) => setJson(e.target.value)}
                />
              ) : tab === "trigger" ? (
                <div className="wb-entry-trigger">
                  <label>
                    <span>条目名称</span>
                    <input
                      value={selected.comment ?? ""}
                      onChange={(e) => update({ comment: e.target.value })}
                    />
                  </label>
                  <label>
                    <span>辅助关键词（每行一个）</span>
                    <textarea
                      value={(selected.keysecondary ?? []).join("\n")}
                      onChange={(e) => update({ keysecondary: e.target.value.split("\n").filter(Boolean) })}
                    />
                  </label>
                  <label className="wb-entry-check">
                    <input
                      type="checkbox"
                      checked={!!selected.selective}
                      onChange={(e) => update({ selective: e.target.checked })}
                    />
                    使用辅助关键词
                  </label>
                </div>
              ) : (
                <>
                  <MdField
                    className="wb-entry-text"
                    label="世界书正文"
                    value={selected.content ?? ""}
                    onChange={(content) => update({ content })}
                  />
                  <div className="wb-entry-keys">
                    <span>关键词</span>
                    {(selected.key ?? []).map((k: string, i: number) => (
                      <span className="wb-key" key={k + i}>
                        {k}
                        <button
                          aria-label={`移除关键词 ${k}`}
                          onClick={() =>
                            update({ key: (selected.key ?? []).filter((_: string, j: number) => j !== i) })
                          }
                        >
                          <X size={11} />
                        </button>
                      </span>
                    ))}
                    {newKey === null ? (
                      <button className="wb-key-add" onClick={() => setNewKey("")}>
                        + 添加
                      </button>
                    ) : (
                      <input
                        className="wb-key-input"
                        aria-label="新关键词"
                        autoFocus
                        value={newKey}
                        onChange={(e) => setNewKey(e.target.value)}
                        onBlur={() => setNewKey(null)}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") setNewKey(null);
                          if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
                          e.preventDefault();
                          const value = newKey.trim();
                          if (value) update({ key: [...(selected.key ?? []), value] });
                          setNewKey("");
                        }}
                      />
                    )}
                  </div>
                </>
              )}
              {(tab === "content" || tab === "trigger") && (
                <div className="wb-entry-params">
                  <label>
                    注入位置
                    <Select
                      value={selected.position ?? 0}
                      onChange={(e) => update({ position: Number(e.target.value) })}
                    >
                      {positions.map((v, i) => (
                        <option key={v} value={i}>
                          {v}
                        </option>
                      ))}
                    </Select>
                  </label>
                  {[
                    ["depth", "深度"],
                    ["order", "顺序"],
                    ["probability", "触发概率 %"],
                  ].map(([key, label]) => (
                    <label key={key}>
                      {label}
                      <input
                        type="number"
                        min={0}
                        max={key === "probability" ? 100 : undefined}
                        value={selected[key] ?? 0}
                        onChange={(e) => update({ [key]: Number(e.target.value) })}
                      />
                    </label>
                  ))}
                </div>
              )}
            </article>
          </EntryEditor>
        )}
        {(!mobile || !entryOpen) && saveBar}
      </fieldset>
    );
  }
  const book = snap.resources.world.find((x) => x.id === name),
    bound = host.characterBooks().includes(name),
    totalTokens = tokensComplete ? Object.values(entryTokens).reduce((n, x) => n + x, 0) : 0;
  const closeDetail = () => setEntry("");
  /** Up and down move the open entry through the shown rows while focus is in the table. */
  const tableKey = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    if ((event.target as HTMLElement).closest("input, textarea, select, [contenteditable]")) return;
    const at = shown.findIndex(([id]) => id === entry),
      next = Math.min(shown.length - 1, Math.max(0, at < 0 ? 0 : at + (event.key === "ArrowDown" ? 1 : -1)));
    if (!shown[next]) return;
    event.preventDefault();
    setEntry(shown[next][0]);
    // The focused row may leave the rendered window; the table keeps the keys.
    (event.currentTarget as HTMLElement).focus({ preventScroll: true });
    tableWindow.reveal(next);
  };
  const params = selected && (
    <aside className="wb-wt-params" aria-label="注入参数">
      <h4>注入参数</h4>
      <div className="wb-wt-param-grid">
        <Field label="注入位置">
          <Select
            value={selected.position ?? 0}
            onChange={(e) => update({ position: Number(e.target.value) })}
          >
            {positions.map((v, i) => (
              <option key={v} value={i}>
                {v}
              </option>
            ))}
          </Select>
        </Field>
        {[
          ["order", "顺序"],
          ["depth", "深度"],
          ["probability", "概率 %"],
          ["scanDepth", "扫描深度"],
          ["sticky", "粘性"],
          ["cooldown", "冷却"],
          ["delay", "延迟"],
          ["recursionStep", "递归步数"],
          ["groupWeight", "组权重"],
        ].map(([key, label]) => (
          <Field label={label} key={key}>
            <input
              type="number"
              min={0}
              max={key === "probability" ? 100 : undefined}
              value={selected[key] ?? 0}
              onChange={(e) => update({ [key]: Number(e.target.value) })}
            />
          </Field>
        ))}
        <Field label="包含组">
          <input value={selected.group ?? ""} onChange={(e) => update({ group: e.target.value })} />
        </Field>
      </div>
      <div className="wb-wt-flags">
        {[
          ["useProbability", "启用概率"],
          ["excludeRecursion", "排除递归"],
          ["preventRecursion", "阻止后续递归"],
          ["delayUntilRecursion", "仅递归时触发"],
          ["matchWholeWords", "匹配完整单词"],
          ["caseSensitive", "区分大小写"],
          ["useGroupScoring", "分组评分"],
          ["groupOverride", "覆盖包含组"],
        ].map(([key, label]) => (
          <label className="wb-check" key={key}>
            <input
              type="checkbox"
              checked={!!selected[key]}
              onChange={(e) => update({ [key]: e.target.checked })}
            />
            {label}
          </label>
        ))}
      </div>
    </aside>
  );
  const editorContent = selected && (
    <aside className="wb-wt-detail" aria-label={`条目详情：${selected.comment || entry}`}>
      <div className="wb-wt-editor-main">
        <header>
          <button
            className="wb-wt-icon wb-wt-back"
            aria-label="返回条目列表"
            title="返回条目列表"
            onClick={closeDetail}
          >
            <ChevronLeft size={16} />
          </button>
          <input
            className="wb-wt-name"
            aria-label="条目名称"
            value={selected.comment ?? ""}
            placeholder={`条目 ${entry}`}
            onChange={(e) => update({ comment: e.target.value })}
          />
          <div className="wb-wt-tabs" role="group" aria-label="条目内容">
            {[
              ["content", "正文"],
              ["trigger", "触发条件"],
              ["portraits", "立绘"],
            ].map(([t, label]) => (
              <button key={t} aria-pressed={tab === t} onClick={() => switchTab(t)}>
                {label}
              </button>
            ))}
          </div>
          <button
            className="wb-wt-icon is-danger"
            aria-label="删除条目"
            title="删除条目"
            onClick={removeEntry}
          >
            <Trash2 size={15} />
          </button>
          <button
            className="wb-wt-icon wb-wt-close"
            aria-label="收起条目详情"
            title="收起详情"
            onClick={closeDetail}
          >
            <X size={15} />
          </button>
        </header>
        {tab === "portraits" ? (
          <EntryPortraits
            host={host}
            book={name}
            title={String(base?.entries?.[entry]?.comment ?? "").trim()}
            draftTitle={String(selected.comment ?? "")}
          />
        ) : tab === "trigger" ? (
          <div className="wb-wt-trigger">
            <Field label="激活方式">
              <Select value={activation(selected)} onChange={(e) => modeChange(entry, e.target.value)}>
                <option value="keyword">关键词</option>
                <option value="constant">常驻</option>
                <option value="vector">向量化</option>
              </Select>
            </Field>
            <KeyChips label="关键词" keys={selected.key ?? []} onChange={(key) => update({ key })} />
            <KeyChips
              label="辅助关键词"
              keys={selected.keysecondary ?? []}
              onChange={(keysecondary) => update({ keysecondary })}
            />
            <label className="wb-check">
              <input
                type="checkbox"
                checked={!!selected.selective}
                onChange={(e) => update({ selective: e.target.checked })}
              />
              使用辅助关键词
            </label>
          </div>
        ) : (
          <MdField
            className="wb-wt-content"
            label="世界书正文"
            value={selected.content ?? ""}
            onChange={(content) => update({ content })}
          />
        )}
      </div>
      {tab !== "portraits" && params}
    </aside>
  );
  const editor =
    mobile && selected ? (
      <EntryEditor
        open={!!entry}
        title={`世界书条目：${selected.comment || entry}`}
        onClose={closeDetail}
        busy={task.busy}
        footer={
          <>
            <Notice error={task.error} />
            {saveBar}
          </>
        }
      >
        {editorContent}
      </EntryEditor>
    ) : (
      editorContent
    );
  return (
    <fieldset disabled={task.busy} className={`wb-world is-deep ${managed ? "is-managed" : ""}`}>
      {/* In the settings workspace its list column picks books, so this column stays hidden there. */}
      <section className="wb-book-column">
        <h3>世界书</h3>
        <SearchBox value={bookQuery} onChange={setBookQuery} placeholder="搜索世界书" />
        <p className="wb-caption">全局启用 · 可多选</p>
        {snap.resources.world
          .filter((x) => x.name.toLowerCase().includes(bookQuery.toLowerCase()))
          .map((b) => (
            <div key={b.id} className={`wb-book-row ${name === b.id ? "is-active" : ""}`}>
              <input
                type="checkbox"
                aria-label={`启用世界书 ${b.name}`}
                checked={b.active}
                onChange={(e) => task.run(() => host.toggleBook(b.id, e.target.checked))}
              />
              <button onClick={() => choose(b.id)}>{b.name}</button>
            </div>
          ))}
      </section>
      <section className="wb-wt" ref={workspace}>
        <header className="wb-wt-head">
          <h2>{name || "世界书"}</h2>
          {(book?.active || bound) && <span className="wb-wt-status">已启用</span>}
          <small>
            {[book?.active ? "全局" : bound ? "角色绑定" : "未启用", `${entries.length} 条`]
              .concat(totalTokens ? [`${totalTokens.toLocaleString()} tokens`] : [])
              .join(" · ")}
          </small>
          {!tokensComplete && entries.length > WINDOW_FROM && (
            <button
              className="wb-wt-count"
              disabled={countAll}
              title="逐条统计整本世界书的 tokens"
              onClick={() => setCountAll(true)}
            >
              {countAll ? `统计中 ${Object.keys(entryTokens).length} / ${entries.length}` : "统计 tokens"}
            </button>
          )}
          <span className="wb-grow" />
          <button
            className={`wb-wt-text ${tab === "json" ? "is-on" : ""}`}
            aria-pressed={tab === "json"}
            onClick={() => switchTab(tab === "json" ? "content" : "json")}
          >
            <Braces size={15} />
            完整 JSON
          </button>
        </header>
        <Notice error={task.error} />
        {tab === "json" ? (
          <textarea
            className="wb-wt-json"
            aria-label="世界书 JSON"
            value={json}
            onChange={(e) => setJson(e.target.value)}
          />
        ) : (
          <>
            <div className="wb-wt-tools">
              <SearchBox value={query} onChange={setQuery} placeholder="搜索条目" />
              <div className="wb-wt-chips" role="radiogroup" aria-label="条目筛选">
                {(["all", "keyword", "constant", "vector"] as const).map((m) => (
                  <button
                    key={m}
                    role="radio"
                    aria-checked={filter === m}
                    className={`is-${m}`}
                    onClick={() => setFilter(m)}
                  >
                    {m === "all" ? "全部" : modeName[m]}
                    <small>{m === "all" ? entries.length : (counts[m] ?? 0)}</small>
                  </button>
                ))}
              </div>
              <span className="wb-grow" />
              <button className="wb-wt-add" onClick={addEntry}>
                <Plus size={15} />
                新增条目
              </button>
            </div>
            <div className={`wb-wt-body ${selected && !mobile ? "has-detail" : ""}`}>
              <div className="wb-wt-table" role="table" aria-label="条目" tabIndex={-1} onKeyDown={tableKey}>
                <div className="wb-wt-row is-head" role="row">
                  <span role="columnheader" aria-label="启用" />
                  <span role="columnheader">条目</span>
                  <span role="columnheader">触发关键词</span>
                  <span role="columnheader">位置</span>
                  <span role="columnheader">深度</span>
                  <span role="columnheader">顺序</span>
                  <span role="columnheader">Tokens</span>
                </div>
                <div role="rowgroup" ref={tableWindow.ref}>
                  {tableWindow.before > 0 && (
                    <div className="wb-wt-gap" style={{ height: tableWindow.before }} />
                  )}
                  {shown.slice(tableWindow.first, tableWindow.last).map(([id, e]) => (
                    <EntryRow
                      key={id}
                      id={id}
                      entry={e}
                      open={entry === id}
                      tokens={entryTokens[id]}
                      onToggle={toggleEntry}
                      onOpen={setEntry}
                    />
                  ))}
                  {tableWindow.after > 0 && (
                    <div className="wb-wt-gap" style={{ height: tableWindow.after }} />
                  )}
                </div>
                {!entries.length &&
                  (name ? (
                    <Empty
                      icon={<BookMarked size={18} />}
                      title="这本世界书还没有条目"
                      action={{ label: "新增条目", onClick: addEntry }}
                    >
                      条目在关键词出现时注入上下文，常驻条目每次都会带上。
                    </Empty>
                  ) : (
                    <Empty>选择世界书，开始整理条目</Empty>
                  ))}
                {!!entries.length && !shown.length && (
                  <Empty
                    icon={<Search size={18} />}
                    title="没有符合条件的条目"
                    action={{
                      label: "清除筛选",
                      onClick: () => {
                        setQuery("");
                        setFilter("all");
                      },
                    }}
                  >
                    换个关键词，或清除筛选。
                  </Empty>
                )}
              </div>
              {editor}
            </div>
          </>
        )}
        {(!mobile || !selected || tab === "json") && saveBar}
      </section>
    </fieldset>
  );
}
type EntryActions = {
  onToggle: (id: string, on: boolean) => void;
  onOpen: (id: string) => void;
};
/** One entry in the sidebar list; an edit elsewhere in the book leaves it untouched. */
const EntryItem = memo(function EntryItem({
  id,
  entry: e,
  selected,
  locked,
  onToggle,
  onMode,
  onOpen,
}: EntryActions & {
  id: string;
  entry: Data;
  selected: boolean;
  locked: boolean;
  onMode: (id: string, mode: string) => void;
}) {
  const mode = activation(e),
    title = e.comment || `条目 ${id}`;
  return (
    <li className={`wb-entry mode-${mode} ${selected ? "is-selected" : ""} ${e.disable ? "is-off" : ""}`}>
      <input
        type="checkbox"
        aria-label={`启用条目 ${title}`}
        disabled={locked}
        checked={!e.disable}
        onChange={(v) => onToggle(id, v.target.checked)}
      />
      <span className="wb-entry-mode">
        <Select
          aria-label={`${title} 激活方式`}
          title="关键词 / 常驻 / 向量化"
          disabled={locked}
          value={mode}
          onChange={(v) => onMode(id, v.target.value)}
        >
          <option value="keyword">关键词</option>
          <option value="constant">常驻</option>
          <option value="vector">向量化</option>
        </Select>
      </span>
      <button
        className="wb-entry-open"
        aria-label={`编辑条目 ${title}`}
        aria-pressed={selected}
        onClick={() => onOpen(id)}
      >
        <strong>{title}</strong>
        <small>
          {mode === "constant"
            ? "始终注入"
            : mode === "vector"
              ? "语义匹配"
              : (e.key ?? []).join("、") || "未设置关键词"}
        </small>
      </button>
    </li>
  );
});
/** One row of the deep editor's entry table. */
const EntryRow = memo(function EntryRow({
  id,
  entry: e,
  open,
  tokens,
  onToggle,
  onOpen,
}: EntryActions & { id: string; entry: Data; open: boolean; tokens?: number }) {
  const mode = activation(e);
  return (
    <div
      role="row"
      className={`wb-wt-row is-${mode} ${open ? "is-open" : ""} ${e.disable ? "is-disabled" : ""}`}
      onClick={(v) => {
        if (!(v.target as HTMLElement).closest("input, button")) onOpen(open ? "" : id);
      }}
    >
      <span role="cell">
        <input
          type="checkbox"
          aria-label={`启用条目 ${e.comment || id}`}
          checked={!e.disable}
          onChange={(v) => onToggle(id, v.target.checked)}
        />
        <i title={modeName[mode]} />
      </span>
      <span role="cell">
        <button className="wb-wt-open" aria-expanded={open} onClick={() => onOpen(open ? "" : id)}>
          {e.comment || `条目 ${id}`}
        </button>
      </span>
      <span role="cell" className="wb-wt-keys">
        {mode === "constant" ? "—" : mode === "vector" ? "向量匹配" : (e.key ?? []).join(", ") || "—"}
      </span>
      <span role="cell">{positions[e.position ?? 0]}</span>
      <span role="cell" className="is-num">
        {(e.position ?? 0) === 4 ? (e.depth ?? 4) : "—"}
      </span>
      <span role="cell" className="is-num">
        {e.order ?? 0}
      </span>
      <span role="cell" className="is-num">
        {tokens ?? ""}
      </span>
    </div>
  );
});
/** Keyword chips with an inline add field (Enter adds, Backspace on empty removes the last). */
function KeyChips({
  label,
  keys,
  onChange,
}: {
  label: string;
  keys: string[];
  onChange: (keys: string[]) => void;
}) {
  const [text, setText] = useState("");
  const add = () => {
    const value = text.trim();
    if (value && !keys.includes(value)) onChange([...keys, value]);
    setText("");
  };
  return (
    <div className="wb-wt-keychips">
      <span>{label}</span>
      <div>
        {keys.map((k, i) => (
          <span className="wb-key" key={k + i}>
            {k}
            <button aria-label={`移除${label} ${k}`} onClick={() => onChange(keys.filter((_, j) => j !== i))}>
              <X size={11} />
            </button>
          </span>
        ))}
        <input
          aria-label={`添加${label}`}
          placeholder="+ 添加"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={add}
          onKeyDown={(e) => {
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            } else if (e.key === "Backspace" && !text && keys.length) onChange(keys.slice(0, -1));
          }}
        />
      </div>
    </div>
  );
}
