import { Select } from "../ui/Select";
import React, { useEffect, useLayoutEffect, useState } from "react";
import { Plus, Save, Maximize2, Trash2, BookOpen, PencilLine, X } from "lucide-react";
import { clone, activation, setActivation, validateBook } from "../host/model";
import type { Data } from "../host/types";
import type { HostAdapter } from "../host/adapter";
import {
  useHost,
  useTask,
  SearchBox,
  Notice,
  Empty,
  Field,
  IconButton,
} from "../ui/common";
import {ResourcePicker} from "../ui/ResourcePicker";
export default function World({
  host,
  deep,
  onDeep,
  initial,
  managed,
}: {
  host: HostAdapter;
  deep?: boolean;
  onDeep?: (name: string) => void;
  initial?: string;
  managed?:boolean;
}) {
  const snap = useHost(host),
    task = useTask();
  const [name, setName] = useState(
    initial || snap.current.world || snap.resources.world[0]?.id || "",
  );
  const cached=host.drafts.get("world:"+name);
  const [base, setBase] = useState<Data | null>(cached?.base??null),
    [draft, setDraft] = useState<Data | null>(cached?.draft??null),
    [entry, setEntry] = useState<string>(cached?.extra?.entry??""),
    [query, setQuery] = useState(""),
    [bookQuery, setBookQuery] = useState(""),
    [tab, setTab] = useState(cached?.extra?.tab??"content"),
    [json, setJson] = useState(cached?.extra?.json??""),
    [saved, setSaved] = useState(""), [scope,setScope] = useState("global"), [editorOpen,setEditorOpen] = useState(false);
  useLayoutEffect(()=>{if(base&&draft)host.drafts.set("world:"+name,{base:clone(base),draft:clone(draft),extra:{json,tab,entry}});},[name,base,draft,json,tab,entry]);
  const dirty =
    Boolean(base && draft && JSON.stringify(base) !== JSON.stringify(draft)) ||
    (tab === "json" &&
      Boolean(draft) &&
      json !== JSON.stringify(draft, null, 2));
  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);
  useEffect(() => {
    if (dirty) return;
    let live = true;
    if (name)
      host
        .readBook(name)
        .then((data) => {
          if (live) {
            setBase(clone(data));
            setDraft(clone(data));
            setEntry((previous) =>
              data.entries?.[previous]
                ? previous
                : (Object.keys(data.entries ?? {})[0] ?? ""),
            );
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
    host.drafts.delete("world:"+name);
    setTab("content");
    setBase(null);
    setDraft(null);
    setName(next);
  };
  const update = (patch: Data) => {
    if (!draft || !draft.entries[entry]) return;
    const next = clone(draft);
    Object.assign(next.entries[entry], patch);
    setDraft(next);
    setSaved("");
  };
  const save = () =>
    task.run(async () => {
      if (!base || !draft) return;
      const candidate = tab === "json" ? JSON.parse(json) : draft;
      const result = await host.saveBook(name, base, candidate);
      setBase(clone(result));
      setDraft(clone(result));
      setJson(JSON.stringify(result, null, 2));
      setSaved("已保存");
    });
  const modeChange = (id: string, mode: string) => {
    if (!draft) return;
    const next = clone(draft);
    next.entries[id] = setActivation(next.entries[id], mode);
    setDraft(next);
    setSaved("");
  };
  const entries = draft
    ? (Object.entries(draft.entries) as [string, Data][])
    : [];
  const selected = draft?.entries[entry];
  return (
    <fieldset
      disabled={task.busy}
      className={`wb-world ${deep ? "is-deep" : ""} ${managed?"is-managed":""} ${editorOpen||deep?"is-editor-open":""}`}
    >
      <div className="wb-world-tools">
        {deep?<><BookOpen size={18}/><strong>{name||"世界书"}</strong></>:<ResourcePicker label="世界书" items={snap.resources.world} id={name} active={snap.current.world} choose={choose} use={choose} multiple={{selected:scope==="global"?snap.resources.world.filter(x=>x.active).map(x=>x.id):host.characterBooks(),toggle:(id,on)=>task.run(()=>scope==="global"?host.toggleBook(id,on):host.toggleCharacterBook(id,on))}} scopeLabel={scope==="global"?"全局启用":"当前角色卡启用"}/> }
        <span className="wb-grow" />
        {dirty && <small>未保存</small>}
        <button onClick={save} disabled={!dirty || task.busy}>
          <Save size={15} />
          保存
        </button>
        {onDeep && (
          <IconButton title="独立深度编辑" onClick={() => onDeep(name)}><Maximize2 size={17}/></IconButton>
        )}
      </div>
      {!deep&&<div className="wb-world-scope" aria-label="世界书启用范围">{[["global","全局启用"],["character","当前角色卡启用"]].map(([value,label])=><button key={value} aria-pressed={scope===value} disabled={value==="character"&&!snap.character} onClick={()=>setScope(value)}>{label}</button>)}</div>}
      <Notice error={task.error} />
      {saved && (
        <div className="wb-success" role="status">
          {saved}
        </div>
      )}
      <div className="wb-world-grid">
        <section className="wb-book-column">
          <SearchBox
            value={bookQuery}
            onChange={setBookQuery}
            placeholder="搜索世界书"
          />
          <p className="wb-caption">全局启用 · 可多选</p>
          {snap.resources.world
            .filter((x) =>
              x.name.toLowerCase().includes(bookQuery.toLowerCase()),
            )
            .map((book) => (
              <div
                key={book.id}
                className={`wb-book-row ${name === book.id ? "is-active" : ""}`}
              >
                <input
                  type="checkbox"
                  aria-label={`启用世界书 ${book.name}`}
                  checked={book.active}
                  onChange={(e) =>
                    task.run(() => host.toggleBook(book.id, e.target.checked))
                  }
                />
                <button onClick={() => choose(book.id)}>{book.name}</button>
              </div>
            ))}
        </section>
        <section className="wb-entry-column">
          <div className="wb-flex">
            <SearchBox
              value={query}
              onChange={setQuery}
              placeholder="搜索条目"
            />
            {deep && (
              <IconButton
                title="新增条目"
                disabled={tab === "json"}
                onClick={() =>
                  task.run(async () => {
                    if (!draft) return;
                    const next = clone(draft),
                      item = await host.createEntry(name, next);
                    setDraft(next);
                    setEntry(String(item.uid));
                  })
                }
              >
                <Plus size={17} />
              </IconButton>
            )}
          </div>
          {entries
            .filter(([, e]) =>
              `${e.comment} ${e.key?.join(" ")}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map(([id, e]) => (
              <div
                key={id}
                className={`wb-entry-row ${entry === id ? "is-active" : ""} ${e.disable ? "is-disabled" : ""}`}
              >
                <input
                  type="checkbox"
                  className="wb-entry-state"
                  style={{ "--wb-entry-tone": activation(e) === "constant" ? "#5883af" : activation(e) === "vector" ? "#856a9c" : "#628671" } as React.CSSProperties}
                  aria-label={`启用条目 ${e.comment || id}`}
                  disabled={tab === "json"}
                  checked={!e.disable}
                  onChange={(v) => {
                    const next = clone(draft!);
                    next.entries[id].disable = !v.target.checked;
                    setDraft(next);
                  }}
                />
                <div className="wb-entry-copy">
                  <button className="wb-row-main" onClick={() => setEntry(id)} onDoubleClick={()=>{setEntry(id);setEditorOpen(true);}}>
                    <strong>{e.comment || `条目 ${id}`}</strong>
                  </button>
                  <Select
                    aria-label={`${e.comment || id} 激活方式`}
                    title="关键词 / 常驻 / 向量化"
                    className="wb-mode-label"
                    disabled={tab === "json"}
                    value={activation(e)}
                    onChange={(v) => modeChange(id, v.target.value)}
                  >
                    <option value="keyword">关键词</option>
                    <option value="constant">常驻</option>
                    <option value="vector">向量化</option>
                  </Select>
                </div>
                {!deep&&<IconButton title={`编辑条目 ${e.comment||id}`} onClick={()=>{setEntry(id);setEditorOpen(true);}}><PencilLine size={15}/></IconButton>}
              </div>
            ))}
          {!entries.length && <Empty>选择世界书，开始整理条目</Empty>}
        </section>
        <section className="wb-entry-editor" inert={!deep&&!editorOpen}>
          {selected ? (
            <>
              <div className="wb-editor-heading">
                {!deep&&<IconButton title="收起条目编辑" onClick={()=>setEditorOpen(false)}><X size={15}/></IconButton>}
                <input
                  aria-label="条目名称"
                  disabled={tab === "json"}
                  value={selected.comment ?? ""}
                  onChange={(e) => update({ comment: e.target.value })}
                />
                {deep && (
                  <IconButton
                    title="删除条目"
                    disabled={tab === "json"}
                    onClick={() => {
                      if (confirm("删除此条目？保存后生效。")) {
                        const next = clone(draft!);
                        delete next.entries[entry];
                        setDraft(next);
                        setEntry(Object.keys(next.entries)[0] ?? "");
                      }
                    }}
                  >
                    <Trash2 size={16} />
                  </IconButton>
                )}
              </div>
              <div className="wb-tabs">
                {(deep
                  ? ["content", "trigger", "json"]
                  : ["content", "trigger"]
                ).map((t) => (
                  <button
                    key={t}
                    className={tab === t ? "is-active" : ""}
                    onClick={() => {
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
                    }}
                  >
                    {t === "content"
                      ? "正文"
                      : t === "trigger"
                        ? "触发条件"
                        : "完整 JSON"}
                  </button>
                ))}
              </div>
              {tab === "content" ? (
                <textarea
                  className="wb-content-editor"
                  aria-label="世界书正文"
                  value={selected.content ?? ""}
                  onChange={(e) => update({ content: e.target.value })}
                />
              ) : tab === "json" ? (
                <textarea
                  className="wb-content-editor wb-code"
                  aria-label="世界书 JSON"
                  value={json}
                  onChange={(e) => setJson(e.target.value)}
                />
              ) : (
                <div className="wb-fields">
                  <Field label="激活方式">
                    <Select
                      value={activation(selected)}
                      onChange={(e) => modeChange(entry, e.target.value)}
                    >
                      <option value="keyword">关键词</option>
                      <option value="constant">常驻</option>
                      <option value="vector">向量化</option>
                    </Select>
                  </Field>
                  <Field label="关键词（每行一个，支持正则）">
                    <textarea
                      value={(selected.key ?? []).join("\n")}
                      onChange={(e) =>
                        update({
                          key: e.target.value.split("\n").filter(Boolean),
                        })
                      }
                    />
                  </Field>
                  <Field label="辅助关键词（每行一个）">
                    <textarea
                      value={(selected.keysecondary ?? []).join("\n")}
                      onChange={(e) =>
                        update({
                          keysecondary: e.target.value
                            .split("\n")
                            .filter(Boolean),
                        })
                      }
                    />
                  </Field>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!selected.selective}
                      onChange={(e) => update({ selective: e.target.checked })}
                    />
                    使用辅助关键词
                  </label>
                </div>
              )}
            </>
          ) : (
            <Empty>选择一个条目</Empty>
          )}
        </section>
        {deep && selected && tab !== "json" && (
          <aside className="wb-parameters">
            <span className="wb-eyebrow">注入参数</span>
            <Field label="注入位置">
              <Select
                value={selected.position ?? 0}
                onChange={(e) => update({ position: Number(e.target.value) })}
              >
                {[
                  "角色定义之前",
                  "角色定义之后",
                  "作者注释之前",
                  "作者注释之后",
                  "指定深度",
                  "示例之前",
                  "示例之后",
                  "Outlet",
                ].map((v, i) => (
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
            <label>
              <input
                type="checkbox"
                checked={!!selected.useProbability}
                onChange={(e) => update({ useProbability: e.target.checked })}
              />
              启用概率
            </label>
            {[["scanDepth","扫描深度"],["sticky","粘性"],["cooldown","冷却"],["delay","延迟"],["recursionStep","递归步数"],["groupWeight","组权重"]].map(([key,label])=><Field key={key} label={label}><input type="number" value={selected[key]??0} onChange={e=>update({[key]:Number(e.target.value)})}/></Field>)}
            <Field label="包含组"><input value={selected.group??""} onChange={e=>update({group:e.target.value})}/></Field>
            {[["excludeRecursion","排除递归"],["preventRecursion","阻止后续递归"],["delayUntilRecursion","仅递归时触发"],["matchWholeWords","匹配完整单词"],["caseSensitive","区分大小写"],["useGroupScoring","分组评分"],["groupOverride","覆盖包含组"]].map(([key,label])=><label className="wb-check" key={key}><input type="checkbox" checked={!!selected[key]} onChange={e=>update({[key]:e.target.checked})}/>{label}</label>)}
          </aside>
        )}
      </div>
      <footer className="wb-legend">
        <span className="green">● 关键词</span>
        <span className="blue">● 常驻</span>
        <span className="purple">↗ 向量化</span>
        <span className="wb-grow" />
        <small>世界书绑定可在独立管理页调整</small>
      </footer>
    </fieldset>
  );
}
