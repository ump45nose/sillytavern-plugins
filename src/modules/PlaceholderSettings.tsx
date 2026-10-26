import { useState, useSyncExternalStore } from "react";
import { Plus, Trash2 } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import { Empty, useHostSlices } from "../ui/common";
import { Select } from "../ui/Select";

/** 「用户设置 → 占位符变量」: each scope's `{@变量}` values, editable in place. */
export default function PlaceholderSettings({ host }: { host: HostAdapter }) {
  useHostSlices(host, ["session"]);
  const runtime = host.placeholders;
  const scopes = useSyncExternalStore(runtime.subscribe, () => runtime.scopes());
  const inputOn = useSyncExternalStore(runtime.subscribe, () => runtime.inputOn);
  const current = runtime.scope();
  const [picked, setPicked] = useState(current.key);
  const key = picked in scopes || picked === current.key ? picked : current.key;
  const vars = scopes[key]?.vars ?? {},
    name = scopes[key]?.name ?? current.name;
  const [draft, setDraft] = useState({ name: "", value: "" });
  const options = [
    { value: current.key, label: `${current.name}（当前）` },
    ...Object.entries(scopes)
      .filter(([k]) => k !== current.key)
      .map(([k, s]) => ({ value: k, label: `${s.name} · ${Object.keys(s.vars).length} 个` })),
  ];
  const save = (next: Record<string, string>) => runtime.setVars(key, next, name);
  const add = () => {
    const n = draft.name.trim();
    if (!/^[\w一-龥]+$/.test(n)) return;
    save({ ...vars, [n]: draft.value });
    setDraft({ name: "", value: "" });
  };
  return (
    <section className="wb-placeholder-settings" aria-label="占位符变量">
      <header className="wb-utility-heading">
        <div>
          <h3>占位符变量</h3>
          <p>
            输入框、快速回复写入输入框的文本和 /inject 中的{" "}
            <span className="wb-placeholder-name">{"{@变量}"}</span> 按角色卡保存，随酒馆设置跨设备同步。
          </p>
        </div>
        <label className="wb-check">
          <input type="checkbox" checked={inputOn} onChange={(e) => runtime.setInputOn(e.target.checked)} />
          输入弹窗（本页有效，同 <span className="wb-placeholder-name">{"{@input:toggle}"}</span>）
        </label>
      </header>
      <div className="wb-placeholder-scope">
        <Select aria-label="变量所属角色" value={key} onChange={(e) => setPicked(e.target.value)}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <button
          disabled={!Object.keys(vars).length}
          onClick={() => confirm(`清空「${name}」的变量？`) && save({})}
        >
          <Trash2 size={15} />
          清空
        </button>
      </div>
      <div className="wb-placeholder-table" role="group" aria-label="变量">
        {Object.entries(vars).map(([n, v]) => (
          <div key={n} className="wb-placeholder-row">
            <span className="wb-placeholder-name">{n}</span>
            <input
              aria-label={`变量 ${n} 的值`}
              value={v}
              onChange={(e) => save({ ...vars, [n]: e.target.value })}
            />
            <button
              title={`删除 ${n}`}
              aria-label={`删除 ${n}`}
              onClick={() => {
                const { [n]: _, ...rest } = vars;
                save(rest);
              }}
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        {!Object.keys(vars).length && (
          <Empty>这里还没有变量；快速回复或输入框里的占位符展开后会出现在此。</Empty>
        )}
        <form
          className="wb-placeholder-row is-new"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <input
            aria-label="新变量名"
            placeholder="变量名"
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
          <input
            aria-label="新变量值"
            placeholder="值"
            value={draft.value}
            onChange={(e) => setDraft((d) => ({ ...d, value: e.target.value }))}
          />
          <button
            type="submit"
            title="添加变量"
            aria-label="添加变量"
            disabled={!/^[\w一-龥]+$/.test(draft.name.trim())}
          >
            <Plus size={15} />
          </button>
        </form>
      </div>
    </section>
  );
}
