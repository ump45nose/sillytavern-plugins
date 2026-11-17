import { useContext, useState } from "react";
import { createPortal } from "react-dom";
import {
  BookMarked,
  Star,
  Plus,
  Upload,
  Users,
  Grid2X2,
  PencilLine,
  PanelLeftClose,
  PanelLeftOpen,
  MessageSquarePlus,
  Search,
  Expand,
  ChevronDown,
} from "../../ui/icons";
import type { HostAdapter } from "../../host/adapter";
import type { Item } from "../../host/types";
import { useTask, Notice, Empty, useHostSlices, withoutChat, Dialog } from "../../ui/common";
import { ResourceRailContext } from "../../ui/ResourcePicker";
import { guards } from "../../host/bus";
import { Popover } from "../../ui/Popover";
import { favorite, plain } from "./shared";
import { CharacterEditor } from "./CharacterEditor";
const fieldTabs = [
  ["description", "描述"],
  ["personality", "性格"],
  ["scenario", "场景"],
  ["first_mes", "第一条消息"],
] as const;
/** The right panel (board "PanelCharacter"): the list lives in the rail; the card shows one character to read, then act on. */
export function CharacterPanel({
  host,
  onManage,
}: {
  host: HostAdapter;
  onManage?: (group?: string) => void;
}) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    rail = useContext(ResourceRailContext);
  const [query, setQuery] = useState(""),
    [viewing, setViewing] = useState(snap.character?.id || ""),
    [field, setField] = useState<(typeof fieldTabs)[number][0]>("description"),
    [editing, setEditing] = useState<string | null>(null),
    [preview, setPreview] = useState(false),
    [pickerAnchor, setPickerAnchor] = useState<HTMLElement | null>(null);
  const item = snap.characters.find((x) => x.id === viewing) ?? snap.character ?? snap.characters[0];
  const data = item?.data?.data ?? item?.data ?? {};
  const portrait = item?.image ? `/characters/${encodeURIComponent(item.id)}` : undefined;
  const list = snap.characters
    .filter((x) =>
      `${x.name} ${x.detail} ${(x.data?.data?.tags || []).join(" ")}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .sort((a, b) => Number(favorite(b)) - Number(favorite(a)) || a.name.localeCompare(b.name, "zh"));
  const create = () => {
    setPickerAnchor(null);
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
                  setPickerAnchor(null);
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
        <button className="wb-rail-new" disabled={task.busy || !!editing} onClick={create}>
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
              e.target.value = "";
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
      <div className="wb-character-switcher">
        <button
          className="wb-character-picker-trigger"
          aria-label="浏览角色"
          aria-haspopup="dialog"
          aria-expanded={!!pickerAnchor}
          onClick={(event) => setPickerAnchor(pickerAnchor ? null : event.currentTarget)}
        >
          <span>
            {snap.characters.find((character) => character.id === editing)?.name || item?.name || "选择角色"}
            {!editing && item?.active ? " · 当前角色" : ""}
          </span>
          <ChevronDown size={16} />
        </button>
        <button
          className="wb-icon"
          aria-label="新建角色"
          title="新建角色"
          disabled={task.busy || !!editing}
          onClick={create}
        >
          <Plus size={19} />
        </button>
      </div>
      {pickerAnchor && (
        <Popover
          anchor={pickerAnchor}
          title="浏览角色"
          className="wb-character-picker"
          onClose={() => setPickerAnchor(null)}
        >
          {listNav}
        </Popover>
      )}
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
        <article
          className={`wb-character-profile ${portrait ? "has-portrait" : ""}`}
          aria-label={`角色 ${item.name}`}
        >
          <header className="wb-character-hero">
            {portrait && (
              <div className="wb-character-hero-art">
                <img src={portrait} alt={`${item.name}上半身`} />
              </div>
            )}
            <div className="wb-character-hero-tools">
              {star(item, "wb-character-hero-tool is-star")}
              {portrait && (
                <button
                  className="wb-character-hero-tool"
                  aria-label="查看完整角色卡"
                  title="查看完整角色卡"
                  onClick={() => setPreview(true)}
                >
                  <Expand size={15} />
                </button>
              )}
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
            </div>
          </header>
          {tags.length > 0 && (
            <div className="wb-character-tags">
              {tags.slice(0, 4).map((t) => (
                <span key={t}>{t}</span>
              ))}
            </div>
          )}
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
          {preview &&
            portrait &&
            createPortal(
              <Dialog title={`${item.name} · 角色原图`} onClose={() => setPreview(false)} wide>
                <div className="wb-character-original">
                  <img src={portrait} alt={`${item.name}完整角色卡`} />
                </div>
              </Dialog>,
              document.body,
            )}
        </article>
      ) : (
        <Empty>还没有角色，先新建或导入一张角色卡</Empty>
      )}
      {rail ? rail.target && rail.open && createPortal(listNav, rail.target) : listNav}
    </div>
  );
}
