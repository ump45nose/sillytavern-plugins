import { useSyncExternalStore } from "react";
import { ChevronRight, UsersRound } from "./icons";
import type { HostAdapter } from "../host/adapter";
import { useHostSlices } from "./common";
import { Select } from "./Select";

const useCast = (host: HostAdapter) => useSyncExternalStore(host.cast.subscribe, () => host.cast.state);

/** The books this chat and its card are bound to come first. */
function books(host: HostAdapter, current?: string) {
  const all = host.snapshot().resources.world.map((book) => book.name),
    bound = [host.worldBindings().chat, ...host.characterBooks()].filter((name) => all.includes(name));
  return [...new Set([...bound, ...all, ...(current ? [current] : [])])];
}

/** RP 外观 › 立绘来源: this chat plays its character card, or a world book's cast. */
export function CastSource({ host, onOpen }: { host: HostAdapter; onOpen: () => void }) {
  useHostSlices(host, ["resources", "session"]);
  const cast = useCast(host),
    config = cast.config,
    list = books(host, config?.book),
    run = (pending: Promise<unknown>) => pending.catch((error) => host.report(error));
  return (
    <>
      <span className="wb-pop-label">立绘来源 · 本聊天</span>
      <div className="wb-font-choices">
        <button aria-pressed={!config} onClick={() => config && run(host.cast.save(undefined))}>
          角色卡 · 单人
        </button>
        <button
          aria-pressed={!!config}
          disabled={!config && !list.length}
          title={list.length ? undefined : "还没有世界书"}
          onClick={() => !config && run(host.cast.save({ book: list[0], entries: [] }).then(onOpen))}
        >
          世界书 · 多人
        </button>
      </div>
      {config && (
        <div className="wb-cast-source">
          <Select
            aria-label="立绘世界书"
            value={config.book}
            onChange={(e) => run(host.cast.save({ book: e.target.value, entries: [] }))}
          >
            {list.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
          <button className="wb-cast-open" onClick={onOpen}>
            <UsersRound size={15} aria-hidden="true" />
            <span>阵容 · {cast.members.length} 人</span>
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        </div>
      )}
      {cast.error && <p className="wb-cast-note is-error">{cast.error}</p>}
    </>
  );
}

/** Which entries play; each one's images are managed in its world-book entry. */
export function CastPanel({
  host,
  onManage,
}: {
  host: HostAdapter;
  onManage: (book: string, title: string) => void;
}) {
  const cast = useCast(host),
    config = cast.config,
    run = (pending: Promise<unknown>) => pending.catch((error) => host.report(error));
  if (!config) return null;
  const chosen = new Set(config.entries),
    save = (entries: string[]) => run(host.cast.save({ book: config.book, entries }));
  return (
    <div className="wb-pop-form wb-cast">
      <p className="wb-cast-note">
        勾选上场的条目。模型会在每段开头写「名字|表情:」，立绘在世界书条目的「立绘」页管理。
      </p>
      {!cast.entries.length ? (
        <p className="wb-cast-note">{cast.loading ? "正在读取世界书…" : "这本世界书还没有带标题的条目。"}</p>
      ) : (
        <ul className="wb-cast-list" aria-label="世界书条目">
          {cast.entries.map((entry) => {
            const member = cast.members.find((m) => m.name === entry.name),
              on = chosen.has(entry.name);
            return (
              <li key={entry.name} className={on ? "is-on" : ""}>
                <label className="wb-cast-entry">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={!entry.safe}
                    onChange={(e) =>
                      save(
                        e.target.checked
                          ? [...config.entries, entry.name]
                          : config.entries.filter((x) => x !== entry.name),
                      )
                    }
                  />
                  <strong>{entry.name}</strong>
                  {!!entry.aliases.length && <small>{entry.aliases.join("、")}</small>}
                </label>
                {member && (
                  <span className="wb-cast-count">
                    {member.sprites.length ? `${member.sprites.length} 张` : "无立绘"}
                  </span>
                )}
                <button
                  className="wb-cast-manage"
                  aria-label={`管理 ${entry.name} 的立绘`}
                  onClick={() => onManage(config.book, entry.name)}
                >
                  立绘
                  <ChevronRight size={13} aria-hidden="true" />
                </button>
                {!entry.safe && (
                  <small className="wb-cast-hint">
                    标题含 / \ : * ? " &lt; &gt; | 或首尾的点、空格，改名后可上场
                  </small>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {!!cast.missing.length && (
        <p className="wb-cast-note">
          已不在世界书中：{cast.missing.join("、")}
          <button onClick={() => save(config.entries.filter((name) => !cast.missing.includes(name)))}>
            移除
          </button>
        </p>
      )}
      <p className="wb-cast-note">
        没有标注的旧回复，由酒馆「表情」扩展当前的分类器判断表情；分类器设为 LLM 时，每条旧回复会多一次请求。
      </p>
    </div>
  );
}
