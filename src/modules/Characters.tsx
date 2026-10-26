import { Select } from "../ui/Select";
import React, { useContext, useState, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  BookMarked,
  Star,
  Plus,
  Upload,
  Users,
  Grid2X2,
  Download,
  PencilLine,
  PanelLeftClose,
  PanelLeftOpen,
  MessageSquarePlus,
  ImagePlus,
  X,
  Search,
} from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import type { Data, Item } from "../host/types";
import { clone } from "../host/model";
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
import { ResourceRailContext } from "../ui/ResourcePicker";
import { SaveBar } from "../ui/ResourceControls";
import { useTokenCounts } from "../ui/tokens";
import { guards } from "../host/bus";
import { MdField } from "../ui/md/MdField";
import { SpeakerColor } from "../ui/SpeakerColor";

export default function Characters(props: {
  host: HostAdapter;
  management?: boolean;
  onManage?: (group?: string) => void;
}) {
  return props.management ? <CharacterLibrary host={props.host} /> : <CharacterPanel {...props} />;
}
const favorite = (x: Item) => Boolean(x.data?.data?.extensions?.fav ?? x.data?.fav);
const fieldTabs = [
  ["description", "描述"],
  ["personality", "性格"],
  ["scenario", "场景"],
  ["first_mes", "第一条消息"],
] as const;
const plain = (text: unknown) =>
  String(text ?? "")
    .replace(/<[^>]*>/g, "")
    .trim();
/** The right panel (board "PanelCharacter"): the list lives in the rail; the card shows one character to read, then act on. */
function CharacterPanel({ host, onManage }: { host: HostAdapter; onManage?: (group?: string) => void }) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    rail = useContext(ResourceRailContext);
  const [query, setQuery] = useState(""),
    [viewing, setViewing] = useState(snap.character?.id || ""),
    [field, setField] = useState<(typeof fieldTabs)[number][0]>("description"),
    [editing, setEditing] = useState<string | null>(null);
  const item = snap.characters.find((x) => x.id === viewing) ?? snap.character ?? snap.characters[0];
  const data = item?.data?.data ?? item?.data ?? {};
  const list = snap.characters
    .filter((x) =>
      `${x.name} ${x.detail} ${(x.data?.data?.tags || []).join(" ")}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .sort((a, b) => Number(favorite(b)) - Number(favorite(a)) || a.name.localeCompare(b.name, "zh"));
  const create = () => {
    const name = prompt("角色名称");
    if (name) task.run(async () => setEditing(await host.createCharacter(name)));
  };
  const star = (x: Item, className: string) => (
    <button
      className={className}
      aria-label={favorite(x) ? `取消收藏 ${x.name}` : `收藏 ${x.name}`}
      title={favorite(x) ? "取消收藏" : "收藏"}
      aria-pressed={favorite(x)}
      onClick={() => task.run(() => host.favorite(x))}
    >
      <Star size={14} fill={favorite(x) ? "currentColor" : "none"} />
    </button>
  );
  const listNav = (
    <nav className={`wb-ui wb-rail wb-character-nav ${rail ? "" : "is-inline"}`} aria-label="角色列表">
      <label className="wb-rail-search">
        <Search size={14} />
        <input
          aria-label="搜索角色"
          placeholder="搜索角色或标签"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="wb-rail-scroll">
        <ul className="wb-rail-list">
          {list.map((x) => (
            <li
              key={x.id}
              className={`wb-rail-row ${x.id === item?.id && !editing ? "is-viewing" : ""} ${x.active ? "is-on" : ""}`}
            >
              <button
                className="wb-rail-open"
                aria-current={(x.id === item?.id && !editing) || undefined}
                title={x.active ? `${x.name} · 当前角色` : x.name}
                onClick={() => {
                  if (editing && !guards.check()) return;
                  setEditing(null);
                  setViewing(x.id);
                }}
              >
                <span className="wb-rail-avatar" aria-hidden="true">
                  {x.image ? <img src={x.image} alt="" /> : x.name.slice(0, 1)}
                </span>
                <span className="wb-rail-copy">
                  <span className="wb-rail-name">{x.name}</span>
                  <small>{x.active ? "当前角色" : x.detail || "未分类角色"}</small>
                </span>
              </button>
              {favorite(x) && (
                <Star className="wb-rail-star" size={12} fill="currentColor" aria-label="收藏" role="img" />
              )}
            </li>
          ))}
        </ul>
        {!list.length && <p className="wb-rail-empty">没有符合条件的角色</p>}
      </div>
      <div className="wb-rail-foot">
        <button className="wb-rail-new" disabled={task.busy} onClick={create}>
          <Plus size={15} />
          新建
        </button>
        <label className="wb-rail-tool" title="导入角色卡">
          <Upload size={15} />
          <input
            aria-label="导入角色卡"
            type="file"
            accept=".png,.json,.yaml,.yml,.charx,.byaf"
            multiple
            onChange={(e) => {
              const files = [...(e.target.files || [])];
              task.run(async () => {
                for (const file of files) await host.importCharacter(file);
              });
            }}
          />
        </label>
        <button className="wb-rail-tool" aria-label="群组" title="群组" onClick={() => onManage?.("群组")}>
          <Users size={15} />
        </button>
        {onManage && (
          <button
            className="wb-rail-tool"
            aria-label="独立管理"
            title="打开角色管理"
            onClick={() => onManage()}
          >
            <Grid2X2 size={15} />
          </button>
        )}
      </div>
    </nav>
  );
  const tags: string[] = data.tags || [];
  const text = plain(data[field]);
  return (
    <div className="wb-characters wb-character-panel">
      <Notice error={task.error} />
      {editing ? (
        <div className="wb-character-detail-wrap">
          <button
            className="wb-link"
            onClick={() => {
              if (guards.check()) setEditing(null);
            }}
          >
            ← 返回角色
          </button>
          <CharacterEditor key={editing} id={editing} host={host} />
        </div>
      ) : item ? (
        <article className="wb-character-profile" aria-label={`角色 ${item.name}`}>
          <header className="wb-character-hero">
            {item.image && (
              // The hero is too large for the native thumbnail (a small flattened JPEG); show the card image itself.
              <img src={`/characters/${encodeURIComponent(item.id)}`} alt="" />
            )}
            <div className="wb-character-hero-tools">
              {star(item, "wb-character-hero-tool is-star")}
              {rail && (
                <button
                  className="wb-character-hero-tool"
                  aria-label={rail.open ? "收起角色列表" : "展开角色列表"}
                  title={rail.open ? "收起角色列表" : "展开角色列表"}
                  aria-expanded={rail.open}
                  onClick={() => rail.setOpen(!rail.open)}
                >
                  {rail.open ? <PanelLeftClose size={14} /> : <PanelLeftOpen size={14} />}
                </button>
              )}
            </div>
            <div className="wb-character-hero-copy">
              <h2 title={item.name}>{item.name}</h2>
              <p>{item.active ? "当前对话中" : item.detail || data.creator || "未分类角色"}</p>
              {tags.length > 0 && (
                <div className="wb-character-tags">
                  {tags.slice(0, 4).map((t) => (
                    <span key={t}>{t}</span>
                  ))}
                </div>
              )}
            </div>
          </header>
          <div className="wb-character-fields" role="tablist" aria-label="角色字段">
            {fieldTabs.map(([key, label]) => (
              <button key={key} role="tab" aria-selected={field === key} onClick={() => setField(key)}>
                {label}
              </button>
            ))}
          </div>
          <div className={`wb-character-text ${text ? "" : "is-empty"}`} role="tabpanel">
            {text || "暂无内容"}
          </div>
          <p className="wb-character-world">
            <BookMarked size={14} aria-hidden="true" />
            绑定世界书
            <span>{data.extensions?.world || "未绑定"}</span>
          </p>
          <footer className="wb-character-actions">
            <button
              className={`wb-character-start ${item.active ? "is-current" : ""}`}
              disabled={task.busy || !!item.active}
              onClick={() => task.run(() => host.selectCharacter(item.id))}
            >
              <MessageSquarePlus size={14} />
              {item.active ? "当前角色" : "开始对话"}
            </button>
            <button
              className="wb-character-quiet"
              onClick={() => task.run(() => host.exportCharacter(item.id))}
            >
              导出角色
            </button>
            <button className="wb-character-edit" onClick={() => setEditing(item.id)}>
              <PencilLine size={14} />
              编辑角色
            </button>
          </footer>
        </article>
      ) : (
        <Empty>还没有角色，先新建或导入一张角色卡</Empty>
      )}
      {rail ? rail.target && rail.open && createPortal(listNav, rail.target) : listNav}
    </div>
  );
}
/** "刚刚 / 5 天前 / 上周" for a last-chat timestamp. */
function since(value: unknown) {
  const at = Number(value);
  if (!at) return "";
  const minutes = Math.max(0, (Date.now() - at) / 60000),
    days = Math.floor(minutes / 1440);
  if (minutes < 60) return "刚刚";
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`;
  if (days < 7) return `${days} 天前`;
  if (days < 14) return "上周";
  if (days < 56) return `${Math.floor(days / 7)} 周前`;
  return new Date(at).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}
/** A portrait that falls back to the name's first character on a soft tint when the image is missing. */
function Portrait({ item, children }: { item: Item; children?: React.ReactNode }) {
  const [broken, setBroken] = useState(false),
    hue = [...item.name].reduce((n, c) => n + c.charCodeAt(0), 0) % 6;
  return (
    <span className={`wb-portrait ${broken ? "is-initial" : ""}`} data-tint={hue}>
      {broken ? (
        <b aria-hidden="true">{[...item.name][0]}</b>
      ) : (
        // The thumbnail is a small flattened JPEG; a portrait this size needs the card image itself.
        <img
          src={`/characters/${encodeURIComponent(item.id)}`}
          alt=""
          loading="lazy"
          onError={() => setBroken(true)}
        />
      )}
      {children}
    </span>
  );
}
/** The independent character library (board "Characters"): a chip-filtered portrait gallery with a selection bar. */
function CharacterLibrary({ host }: { host: HostAdapter }) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask();
  const [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [sort, setSort] = useState("recent"),
    [selected, setSelected] = useState<string[]>([]),
    [editing, setEditing] = useState<string | null>(null);
  const tagsOf = (x: Item) => (x.data?.data?.tags ?? []) as string[];
  const tags = [...new Set(snap.characters.flatMap(tagsOf))];
  const list = snap.characters
    .filter(
      (x) =>
        (filter !== "favorite" || favorite(x)) &&
        (filter !== "current" || x.active) &&
        (!filter.startsWith("tag:") || tagsOf(x).includes(filter.slice(4))) &&
        `${x.name} ${x.detail} ${plain(x.data?.data?.description ?? x.data?.description)}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "recent"
        ? Number(b.data?.date_last_chat ?? 0) - Number(a.data?.date_last_chat ?? 0)
        : a.name.localeCompare(b.name, "zh"),
    );
  const create = () => {
    const name = prompt("角色名称");
    if (name) task.run(async () => setEditing(await host.createCharacter(name)));
  };
  const chips: [string, string][] = [
    ["all", "全部"],
    ["favorite", "收藏"],
    ["current", "当前"],
    ...tags.map((t) => ["tag:" + t, t] as [string, string]),
  ];
  const all = list.length > 0 && list.every((x) => selected.includes(x.id)),
    count = selected.length;
  const batch = (
    <div className={`wb-character-bulk ${count ? "is-active" : ""}`}>
      <label className="wb-check">
        <input
          aria-label="选择当前结果"
          type="checkbox"
          checked={all}
          ref={(n) => {
            if (n) n.indeterminate = count > 0 && !all;
          }}
          onChange={(e) => setSelected(e.target.checked ? list.map((x) => x.id) : [])}
        />
        {count ? `已选 ${count} 个角色` : "全选"}
      </label>
      <span className="wb-grow" />
      <button
        disabled={!count || task.busy}
        onClick={() => {
          const value = prompt("添加标签");
          if (value) task.run(() => host.tagCharacters(selected, value));
        }}
      >
        标签
      </button>
      <button
        disabled={!count || task.busy}
        onClick={() =>
          task.run(async () => {
            for (const id of selected) await host.duplicateCharacter(id);
          })
        }
      >
        复制
      </button>
      <button
        disabled={!count || task.busy}
        onClick={() =>
          task.run(async () => {
            for (const id of selected) await host.exportCharacter(id);
          })
        }
      >
        导出
      </button>
      <button
        className="is-danger"
        disabled={!count || task.busy}
        onClick={() => {
          if (confirm(`删除选中的 ${count} 个角色卡？聊天文件保留。`))
            task.run(async () => {
              await host.deleteCharacters(selected);
              setSelected([]);
            });
        }}
      >
        删除
      </button>
    </div>
  );
  return (
    <div className="wb-characters is-management">
      <Notice error={task.error} />
      {!editing ? (
        <section className="wb-library-content">
          <header className="wb-library-head">
            <h2>角色管理</h2>
            <small>
              {snap.characters.length} 个角色
              {list.length !== snap.characters.length && ` · 显示 ${list.length} 个`}
            </small>
            <span className="wb-grow" />
            <label className="wb-library-import">
              <Download size={15} />
              导入
              <input
                aria-label="导入角色卡"
                type="file"
                accept=".png,.json,.yaml,.yml,.charx,.byaf"
                multiple
                onChange={(e) => {
                  const files = [...(e.target.files || [])];
                  task.run(async () => {
                    for (const file of files) await host.importCharacter(file);
                  });
                }}
              />
            </label>
            <button className="wb-library-create" disabled={task.busy} onClick={create}>
              <Plus size={15} />
              新建
            </button>
          </header>
          <div className="wb-character-search-row is-management">
            <SearchBox value={query} onChange={setQuery} placeholder="搜索角色或标签" />
            <div className="wb-library-chips" role="radiogroup" aria-label="角色筛选">
              {chips.map(([value, label]) => (
                <button
                  key={value}
                  role="radio"
                  aria-checked={filter === value}
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <Select aria-label="角色排序" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="recent">最近对话</option>
              <option value="name">名称排序</option>
            </Select>
          </div>
          {batch}
          <div className={`wb-card-grid ${count ? "has-selection" : ""}`}>
            {list.map((x) => {
              const data = x.data?.data ?? x.data,
                on = selected.includes(x.id);
              return (
                <article
                  key={x.id}
                  className={`wb-character-card ${x.active ? "is-active" : ""} ${on ? "is-selected" : ""}`}
                >
                  <button
                    className="wb-character-main"
                    title={`编辑 ${x.name}`}
                    onClick={() => setEditing(x.id)}
                  >
                    <Portrait item={x}>{x.active && <em>当前</em>}</Portrait>
                    <span className="wb-character-card-body">
                      <span className="wb-character-card-title">
                        <strong>{x.name}</strong>
                        <time>{since(x.data?.date_last_chat)}</time>
                      </span>
                      <span className="wb-character-card-desc">
                        {plain(data?.description) || "暂无角色描述"}
                      </span>
                      {tagsOf(x).length > 0 && (
                        <span className="wb-character-card-tags">
                          {tagsOf(x)
                            .slice(0, 3)
                            .map((t) => (
                              <i key={t}>{t}</i>
                            ))}
                        </span>
                      )}
                    </span>
                  </button>
                  <input
                    type="checkbox"
                    aria-label={`选择 ${x.name}`}
                    checked={on}
                    onChange={(e) =>
                      setSelected((v) => (e.target.checked ? [...v, x.id] : v.filter((id) => id !== x.id)))
                    }
                  />
                  <button
                    className={`wb-character-star ${favorite(x) ? "is-on" : ""}`}
                    aria-label={favorite(x) ? `取消收藏 ${x.name}` : `收藏 ${x.name}`}
                    title={favorite(x) ? "取消收藏" : "收藏"}
                    aria-pressed={favorite(x)}
                    onClick={() => task.run(() => host.favorite(x))}
                  >
                    <Star size={14} fill={favorite(x) ? "currentColor" : "none"} />
                  </button>
                </article>
              );
            })}
          </div>
          {!list.length && (
            <Empty
              icon={<Search size={18} />}
              title="没有符合条件的角色"
              action={{
                label: "清除筛选",
                onClick: () => {
                  setQuery("");
                  setFilter("all");
                },
              }}
            >
              换个名字或标签，或清除筛选。
            </Empty>
          )}
        </section>
      ) : (
        <div className="wb-character-detail-wrap">
          <button
            className="wb-link"
            onClick={() => {
              if (guards.check()) setEditing(null);
            }}
          >
            ← 返回角色库
          </button>
          <CharacterEditor key={editing} id={editing} host={host} />
        </div>
      )}
    </div>
  );
}
const editorTabs = ["人设", "第一条消息", "对话示例", "高级定义", "创作者注释"] as const;
type EditorTab = (typeof editorTabs)[number];
const budgetGroups = [
  ["描述", ["description"], "var(--wb-trace-system)"],
  ["性格与场景", ["personality", "scenario"], "var(--wb-trace-preset)"],
  ["第一条消息", ["first_mes"], "var(--wb-trace-world)"],
  ["对话示例", ["mes_example"], "var(--wb-trace-character)"],
] as const;
const tokenFields = [
  "description",
  "personality",
  "scenario",
  "first_mes",
  "mes_example",
  "system_prompt",
  "post_history_instructions",
];
/** The character card editor (board CharacterEdit): portrait and facts, tabbed fields, then the token budget and greetings. */
function CharacterEditor({ host, id }: { host: HostAdapter; id: string }) {
  const task = useTask(),
    [base, setBase] = useState<Data | null>(host.drafts.get("character:" + id)?.base || null),
    [draft, setDraft] = useState<Data | null>(host.drafts.get("character:" + id)?.draft || null),
    [message, setMessage] = useState(""),
    [tab, setTab] = useState<EditorTab>("人设"),
    [tagText, setTagText] = useState("");
  const dirty = !!base && JSON.stringify(base) !== JSON.stringify(draft);
  const tokens = useTokenCounts(
    host,
    draft ? tokenFields.map((k) => [k, String(draft[k] ?? "")] as [string, string]) : [],
  );
  useEffect(() => {
    if (dirty) return;
    let live = true;
    host
      .characterData(id)
      .then((c) => {
        if (live) {
          setBase(clone(c.data ?? {}));
          setDraft(clone(c.data ?? {}));
        }
      })
      .catch((e) => task.setError(e.message));
    return () => {
      live = false;
    };
  }, [id, host.resourceVersions.character, dirty]);
  useEffect(() => {
    if (base && draft) host.drafts.set("character:" + id, { base: clone(base), draft: clone(draft) });
  }, [base, draft, id]);
  useLeaveGuard(dirty, ({ preserveDrafts }) => preserveDrafts || confirm("角色有未保存修改，放弃这些修改？"));
  if (!draft || !base)
    return (
      <>
        <Notice error={task.error} />
        <Empty>正在读取角色…</Empty>
      </>
    );
  const item = host.snapshot().characters.find((c) => c.id === id);
  const put = (patch: Data) => {
    setDraft({ ...draft, ...patch });
    setMessage("");
  };
  const ext = (patch: Data) => put({ extensions: { ...draft.extensions, ...patch } });
  const depth = (patch: Data) => ext({ depth_prompt: { ...draft.extensions?.depth_prompt, ...patch } });
  const changed = (key: string) => JSON.stringify(draft[key] ?? "") !== JSON.stringify(base[key] ?? "");
  const field = (key: string, label: string, rows = 4, reading = true) => (
    <label className={`wb-ce-field ${reading ? "is-reading" : ""}`} key={key}>
      <span className="wb-ce-label">
        {label}
        {changed(key) && <i className="wb-ce-dirty" aria-label="已修改" />}
        {tokens[key] !== undefined && <small>{tokens[key].toLocaleString()} tokens</small>}
      </span>
      <MdField
        label={label}
        rows={rows}
        value={draft[key] ?? ""}
        onChange={(value) => put({ [key]: value })}
      />
    </label>
  );
  const tags: string[] = draft.tags ?? [];
  const greetings: string[] = [draft.first_mes ?? "", ...(draft.alternate_greetings ?? [])].filter(
    (x, i) => i === 0 || x,
  );
  const examples = String(draft.mes_example ?? "")
    .split(/<START>/i)
    .filter((x) => x.trim()).length;
  const counts: Partial<Record<EditorTab, number>> = {
    人设: ["description", "personality", "scenario"].filter((k) => String(draft[k] ?? "").trim()).length,
    第一条消息: greetings.filter((x) => x.trim()).length,
    对话示例: examples,
  };
  const budget = budgetGroups.map(([label, keys, color]) => ({
      label,
      color,
      value: keys.reduce((n, k) => n + (tokens[k] ?? 0), 0),
    })),
    total = budget.reduce((n, x) => n + x.value, 0),
    limit = host.contextLimit();
  const addTag = () => {
    const value = tagText.trim();
    if (value && !tags.includes(value)) put({ tags: [...tags, value] });
    setTagText("");
  };
  const worlds = host.snapshot().resources.world;
  return (
    <fieldset disabled={task.busy} className="wb-character-editor">
      <aside className="wb-ce-side">
        <figure className="wb-ce-portrait">
          <img
            src={`/characters/${encodeURIComponent(id)}?v=${host.resourceVersions.character ?? 0}`}
            alt=""
          />
          <label className="wb-ce-avatar">
            <ImagePlus size={14} />
            更换头像
            <input
              aria-label="上传角色头像"
              type="file"
              accept="image/*"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) task.run(() => host.characterAvatar(id, file));
              }}
            />
          </label>
        </figure>
        <dl className="wb-ce-meta">
          <div>
            <dt>创建者</dt>
            <dd>
              <input
                aria-label="创建者"
                value={draft.creator ?? ""}
                placeholder="未填写"
                onChange={(e) => put({ creator: e.target.value })}
              />
            </dd>
          </div>
          <div>
            <dt>角色版本</dt>
            <dd>
              <input
                aria-label="角色版本"
                value={draft.character_version ?? ""}
                placeholder="未填写"
                onChange={(e) => put({ character_version: e.target.value })}
              />
            </dd>
          </div>
          <div>
            <dt>角色世界书</dt>
            <dd>
              <Select
                aria-label="角色世界书"
                value={draft.extensions?.world || ""}
                onChange={(e) => ext({ world: e.target.value })}
              >
                <option value="">不绑定</option>
                {worlds.map((w) => (
                  <option key={w.id}>{w.name}</option>
                ))}
              </Select>
            </dd>
          </div>
          <div>
            <dt>对白颜色</dt>
            <dd>
              <SpeakerColor host={host} kind="character" id={id} />
            </dd>
          </div>
          <div>
            <dt>文件</dt>
            <dd title={id}>{id}</dd>
          </div>
        </dl>
      </aside>
      <section className="wb-ce-main">
        <Notice error={task.error} />
        <header className="wb-ce-head">
          <input
            className="wb-ce-name"
            aria-label="角色名称"
            value={draft.name ?? ""}
            onChange={(e) => put({ name: e.target.value })}
          />
          <div className="wb-ce-actions">
            <button onClick={() => task.run(() => host.exportCharacter(id))}>导出角色</button>
            <button onClick={() => task.run(() => host.duplicateCharacter(id))}>复制角色</button>
            <button
              className="is-raised"
              disabled={item?.active}
              onClick={() => task.run(() => host.selectCharacter(id))}
            >
              <MessageSquarePlus size={15} />
              开始对话
            </button>
          </div>
          <div className="wb-ce-tags">
            {tags.map((t) => (
              <span key={t}>
                {t}
                <button
                  aria-label={`移除标签 ${t}`}
                  onClick={() => put({ tags: tags.filter((x) => x !== t) })}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            <input
              aria-label="添加标签"
              placeholder="+ 标签"
              value={tagText}
              size={Math.max(4, tagText.length + 1)}
              onChange={(e) => setTagText(e.target.value.replace(/,|，/g, ""))}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === "," || e.key === "，") {
                  e.preventDefault();
                  addTag();
                }
              }}
              onBlur={addTag}
            />
          </div>
        </header>
        <nav className="wb-ce-tabs" role="tablist" aria-label="角色字段">
          {editorTabs.map((name) => (
            <button key={name} role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>
              {name}
              {!!counts[name] && <small>{counts[name]}</small>}
            </button>
          ))}
        </nav>
        <div className="wb-ce-body" role="tabpanel" aria-label={tab}>
          {tab === "人设" && (
            <>
              {field("description", "角色描述", 8)}
              {field("personality", "性格", 3)}
              {field("scenario", "场景", 3)}
            </>
          )}
          {tab === "第一条消息" && (
            <>
              {field("first_mes", "第一条消息", 7)}
              <label className="wb-ce-field is-reading">
                <span className="wb-ce-label">
                  备选开场白
                  {changed("alternate_greetings") && <i className="wb-ce-dirty" aria-label="已修改" />}
                  <small>以单独一行 --- 分隔</small>
                </span>
                <MdField
                  label="备选开场白（以单独一行 --- 分隔）"
                  rows={8}
                  value={(draft.alternate_greetings || []).join("\n---\n")}
                  onChange={(value) => put({ alternate_greetings: value.split(/\n---\n/).filter(Boolean) })}
                />
              </label>
            </>
          )}
          {tab === "对话示例" && field("mes_example", "对话示例", 14, false)}
          {tab === "高级定义" && (
            <>
              {field("system_prompt", "系统提示词", 4, false)}
              {field("post_history_instructions", "历史后指令", 3, false)}
              <label className="wb-ce-field">
                <span className="wb-ce-label">深度提示词</span>
                <MdField
                  label="深度提示词"
                  rows={3}
                  value={draft.extensions?.depth_prompt?.prompt || ""}
                  onChange={(prompt) => depth({ prompt })}
                />
              </label>
              <div className="wb-ce-row">
                <Field label="深度">
                  <input
                    type="number"
                    min={0}
                    value={draft.extensions?.depth_prompt?.depth ?? 4}
                    onChange={(e) => depth({ depth: Number(e.target.value) })}
                  />
                </Field>
                <Field label="注入角色">
                  <Select
                    value={draft.extensions?.depth_prompt?.role || "system"}
                    onChange={(e) => depth({ role: e.target.value })}
                  >
                    <option>system</option>
                    <option>user</option>
                    <option>assistant</option>
                  </Select>
                </Field>
                <label className="wb-field wb-ce-talk">
                  <span>
                    发言积极性 <output>{Math.round((draft.extensions?.talkativeness ?? 0.5) * 100)}%</output>
                  </span>
                  <input
                    aria-label="发言积极性"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={draft.extensions?.talkativeness ?? 0.5}
                    style={
                      {
                        "--wb-fill": `${(draft.extensions?.talkativeness ?? 0.5) * 100}%`,
                      } as React.CSSProperties
                    }
                    onChange={(e) => ext({ talkativeness: Number(e.target.value) })}
                  />
                </label>
              </div>
            </>
          )}
          {tab === "创作者注释" && field("creator_notes", "创作者注释", 10)}
        </div>
        <SaveBar
          dirty={dirty}
          busy={task.busy}
          message={message}
          detail={[
            ...["description", "personality", "scenario", "first_mes", "mes_example", "creator_notes"].filter(
              changed,
            ),
            ...(changed("name") ? ["name"] : []),
          ]
            .map(
              (k) =>
                ({
                  description: "描述",
                  personality: "性格",
                  scenario: "场景",
                  first_mes: "第一条消息",
                  mes_example: "对话示例",
                  creator_notes: "创作者注释",
                  name: "名称",
                })[k],
            )
            .join(" · ")}
          reset={() => {
            setDraft(clone(base));
            setMessage("");
          }}
          save={() =>
            task.run(async () => {
              const data = await host.saveCharacter(id, base, draft);
              setBase(clone(data.data));
              setDraft(clone(data.data));
              setMessage("已保存");
            })
          }
        />
      </section>
      <aside className="wb-ce-insight">
        {total > 0 && (
          <section className="wb-ce-card">
            <header>
              <h3>Token 预算</h3>
              <small>
                {total.toLocaleString()}
                {limit ? ` / ${limit >= 1024 ? Math.round(limit / 1024) + "k" : limit}` : ""}
              </small>
            </header>
            <div className="wb-ce-budget" aria-hidden="true">
              {budget.map((x) => (
                <i key={x.label} style={{ flexGrow: x.value, background: x.color }} />
              ))}
            </div>
            <ul className="wb-ce-legend">
              {budget.map((x) => (
                <li key={x.label}>
                  <i style={{ background: x.color }} />
                  {x.label}
                  <span>{x.value.toLocaleString()}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        <section className="wb-ce-card">
          <header>
            <h3>第一条消息</h3>
            <small>{greetings.length} 条备选</small>
          </header>
          <ol className="wb-ce-greetings">
            {greetings.map((text, i) => (
              <li key={i}>
                <button onClick={() => setTab("第一条消息")} className={i === 0 ? "is-default" : ""}>
                  <small>
                    #{i + 1}
                    {i === 0 && " · 默认"}
                  </small>
                  <span>{plain(text) || "（空）"}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      </aside>
    </fieldset>
  );
}
