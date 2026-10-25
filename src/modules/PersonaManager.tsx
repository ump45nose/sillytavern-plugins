import { Download, Plus, Upload } from "../ui/icons";
import { useState } from "react";
import type { HostAdapter } from "../host/adapter";
import { Empty, Notice, SearchBox, useTask, useHostSlices, withoutChat } from "../ui/common";
import Resources from "./Resources";
import { Check } from "../ui/ResourceControls";
export default function PersonaManager({
  host,
  group,
  initial,
  onPosition,
}: {
  host: HostAdapter;
  group?: string;
  initial?: string;
  onPosition: (id: string) => void;
}) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    [id, setId] = useState(initial || snap.current.persona || snap.resources.persona[0]?.id || ""),
    [query, setQuery] = useState("");
  if (group === "全局偏好") {
    const p = host.personaOptions(snap.current.persona).preferences;
    return (
      <div className="wb-designed-settings">
        <header className="wb-designed-page-head">
          <div>
            <h2>用户身份全局偏好</h2>
            <small>切换、关联与锁定行为</small>
          </div>
        </header>
        <Notice error={task.error} />
        <section className="wb-designed-section">
          <h3>身份切换</h3>
          <div className="wb-designed-fields">
            {[
              ["persona_auto_lock", "自动锁定到当前对话"],
              ["persona_show_notifications", "切换身份时显示通知"],
              ["persona_allow_multi_connections", "允许角色关联多个身份"],
            ].map(([key, label]) => (
              <Check
                key={key}
                label={label}
                checked={p[key]}
                disabled={task.busy}
                onChange={(v) => task.run(() => host.personaPreference(key, v))}
              />
            ))}
          </div>
        </section>
        <div className="wb-designed-actions">
          <button onClick={() => host.click("#personas_backup")}>
            <Download size={15} />
            备份全部身份
          </button>
          <button onClick={() => host.click("#personas_restore")}>
            <Upload size={15} />
            恢复身份备份
          </button>
        </div>
      </div>
    );
  }
  const items = snap.resources.persona.filter((x) => x.name.toLowerCase().includes(query.toLowerCase()));
  // Board "WsPersona": the same list column as the other resource pages, then the persona's own desk.
  return (
    <div className="wb-persona-page">
      <div className="wb-manager-grid wb-persona-manager">
        <aside className="wb-manager-resources">
          <header className="wb-manager-head">
            <h3>用户设定</h3>
            <span className="wb-grow" />
            <button
              className="wb-manager-icon"
              aria-label="恢复身份备份"
              title="恢复身份备份"
              disabled={snap.busy}
              onClick={() => host.click("#personas_restore")}
            >
              <Upload size={15} />
            </button>
            <button
              className="wb-manager-icon is-raised"
              aria-label="新建用户设定"
              title="新建用户设定"
              disabled={snap.busy}
              onClick={() => host.click("#create_dummy_persona")}
            >
              <Plus size={15} />
            </button>
          </header>
          <SearchBox value={query} onChange={setQuery} placeholder="搜索用户设定" />
          <div className="wb-manager-list">
            {items.map((x) => {
              const current = snap.current.persona === x.id;
              return (
                <div
                  key={x.id}
                  className={`wb-manager-row wb-persona-row ${id === x.id ? "is-editing" : ""}`}
                >
                  <button
                    aria-pressed={id === x.id}
                    onClick={() => {
                      setId(x.id);
                      onPosition(x.id);
                    }}
                  >
                    <span className="wb-persona-row-avatar">
                      {x.image ? <img src={x.image} alt="" /> : x.name.slice(0, 1)}
                    </span>
                    <span className="wb-persona-row-copy">
                      <strong>
                        {x.name}
                        {current && <i className="wb-choice-state is-current" aria-label="当前身份" />}
                      </strong>
                      <small>{current ? "当前身份" : x.detail || "用户设定"}</small>
                    </span>
                  </button>
                </div>
              );
            })}
            {!items.length && <Empty>{query ? "没有符合的用户设定" : "还没有用户设定"}</Empty>}
          </div>
        </aside>
        <div className="wb-manager-editor">
          <Resources
            key={id}
            host={host}
            kind="persona"
            initial={id}
            deep
            onSelection={(next) => {
              setId(next);
              onPosition(next);
            }}
          />
        </div>
      </div>
    </div>
  );
}
