import { Select } from "../ui/Select";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Copy, Download, Image, Maximize2, Plus, Save, Trash2, BookmarkPlus, SlidersHorizontal, PencilLine, X, RefreshCw, ChartNoAxesColumn, Upload } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import type { Resource, Data } from "../host/types";
import { clone, validatePreset } from "../host/model";
import { useHost, useTask, Notice, Empty, Field, IconButton } from "../ui/common";
import { Check, Fold, useDraft } from "../ui/ResourceControls";
import { ResourcePicker } from "../ui/ResourcePicker";
import { ConnectionRuntime } from "./Connection";
export const labels: Record<Resource, string> = { connection: "连接", preset: "预设", world: "世界书", persona: "用户设定" };
const safeToLeave = () => window.dispatchEvent(new Event("wb-before-close", { cancelable: true }));
export default function Resources({ host, kind, initial, deep, onDeep, onSelection, view }: {
  host: HostAdapter; kind: Exclude<Resource, "world">; initial?: string; deep?: boolean; onDeep?: (id: string) => void; onSelection?: (id: string) => void; view?:"prompts";
}) {
  const snap = useHost(host), task = useTask();
  const [id, setId] = useState(initial || snap.current[kind] || snap.resources[kind][0]?.id || "");
  const pendingCreation = useRef<Set<string> | null>(null);
  useEffect(() => { onSelection?.(id); }, [id]);
  useEffect(() => {
    // Native create/delete actions can change the collection while this editor is open.
    const created = pendingCreation.current && snap.resources[kind].find(x => !pendingCreation.current!.has(x.id));
    if (created) { pendingCreation.current = null; setId(created.id); return; }
    if (id && !snap.resources[kind].some(x => x.id === id)) setId(snap.current[kind] || snap.resources[kind][0]?.id || "");
  }, [snap.resources[kind], id, kind]);
  const current = snap.resources[kind].find(x => x.id === id);
  const choose = (next: string) => { if (deep ? window.dispatchEvent(new CustomEvent("wb-before-close",{cancelable:true,detail:{preserveDrafts:true}})) : safeToLeave()) { pendingCreation.current = null; setId(next); } };
  const apply = (next:string) => { if(safeToLeave())task.run(async()=>{pendingCreation.current=null;await host.select(kind,next);setId(next);}); };
  const nativeAction = (selector:string) => { if(safeToLeave())task.run(async()=>{pendingCreation.current=/create_|duplicate/.test(selector)?new Set(snap.resources[kind].map(x=>x.id)):null;if(kind==="persona"&&!/create_/.test(selector)&&current&&snap.current.persona!==id)await host.select("persona",id);host.click(selector);}); };
  return <div className={`wb-resources wb-resource-v3 kind-${kind} ${deep ? "is-deep" : ""}`}>
    <header className="wb-resource-heading">
      <div className="wb-resource-title-line">
        {kind==="persona" && current?.image && <img className="wb-heading-avatar" src={current.image} alt=""/>}
        <div className="wb-resource-title-copy"><small>{labels[kind]}</small><ResourcePicker label={labels[kind]} items={snap.resources[kind]} id={id} active={snap.current[kind]} choose={choose} use={apply} sortable={kind==="persona"} disabled={snap.busy||task.busy}/></div>
        {current && snap.current[kind]!==id && <button className="wb-use-resource" aria-label={`使用此${labels[kind]}`} title={`使用此${labels[kind]}`} disabled={snap.busy||task.busy} onClick={()=>apply(id)}>使用</button>}
        {onDeep && <IconButton title="独立深度编辑" onClick={()=>onDeep(id)}><Maximize2 size={18}/></IconButton>}
      </div>
      {kind==="connection" && <div className="wb-native-profile-actions">{[["create_connection_profile","新建",Plus],["update_connection_profile","记录",BookmarkPlus],["delete_connection_profile","删除",Trash2]].map(([selector,text,Icon]:any)=><button key={selector} title={selector!=="create_connection_profile"&&snap.current.connection!==id?"使用此连接后可操作":undefined} disabled={snap.busy||task.busy||(selector!=="create_connection_profile"&&(!current||snap.current.connection!==id))} onClick={()=>nativeAction(`#${selector}`)}><Icon size={15}/>{text}</button>)}</div>}
      {kind==="persona" && <div className="wb-persona-header-actions">{[["persona_set_image_button","更换头像",Image],["create_dummy_persona","新建",Plus],["persona_duplicate_button","复制",Copy]].map(([selector,text,Icon]:any)=><button key={selector} disabled={snap.busy||task.busy||(!current&&selector!=="create_dummy_persona")} onClick={()=>nativeAction(`#${selector}`)}><Icon size={15}/>{text}</button>)}</div>}
    </header>
    <Notice error={task.error}/>
    {kind === "preset" ? (current ? <PresetEditor key={id} host={host} id={id} deep={deep} view={view} onSelect={setId}/> : <><Empty>暂无预设</Empty><button onClick={()=>{const name=prompt("新预设名称");if(name)task.run(async()=>setId(await host.createPreset(name)));}}>创建预设</button></>) : kind === "connection" ? <div className="wb-resource-detail wb-connection-detail">
      <ConnectionRuntime host={host}/>
      {current && <ProfileEditor key={id} host={host} id={id}/>}
    </div> : current ? <PersonaEditor key={id} host={host} id={id} deep={deep}/> : <div className="wb-fields"><Empty>选择用户身份，或创建一个新身份</Empty><button onClick={()=>host.click("#create_dummy_persona")}>创建用户设定</button></div>}
  </div>;
}
function Footer({ dirty, message, busy, reset, save }: { dirty: boolean; message: string; busy: boolean; reset: () => void; save: () => void }) {
  return <footer className="wb-save-footer"><small role="status">{dirty ? "未保存修改" : message || "已同步"}</small><span className="wb-grow" /><button disabled={!dirty || busy} onClick={reset}>还原</button><button className="wb-primary" disabled={!dirty || busy} onClick={save}><Save size={15} />保存</button></footer>;
}
function ProfileEditor({ host, id }: { host: HostAdapter; id: string }) {
  const task = useTask(), edit = useDraft(() => clone(host.snapshot().resources.connection.find(x => x.id === id)?.data || {}), host.resourceVersions.connection,{host,key:"connection:"+id});
  const { draft, change } = edit;
  return <fieldset disabled={task.busy} className="wb-profile-editor"><Notice error={task.error} />
    <Fold title="连接记录与绑定"><div className="wb-form-pair"><Field label="连接名称"><input value={draft.name || ""} onChange={e => change("name", e.target.value)} /></Field><Field label="记录模型"><input value={draft.model || ""} onChange={e => change("model", e.target.value)} /></Field></div>
    <button disabled={edit.dirty} onClick={()=>task.run(()=>host.select("connection",id))}>应用此连接记录</button>
    <Field label="模型分组"><input value={host.prefs().groups[id] || ""} placeholder="按模型自动分组" onChange={e => host.preference({ groups: { ...host.prefs().groups, [id]: e.target.value } })} /></Field>
    <Field label="绑定预设"><Select value={draft.preset || ""} onChange={e => change("preset", e.target.value)}><option value="">不绑定</option>{host.snapshot().resources.preset.map(p => <option key={p.id}>{p.name}</option>)}</Select></Field>
    <Fold title="连接配置记录">
      <Field label="记录接口类型"><Select value={draft.mode || "cc"} onChange={e => change("mode", e.target.value)}><option value="cc">Chat Completion</option><option value="tc">Text Completion</option></Select></Field>
      {[["api","服务类型"],["api-url","服务地址"],["proxy","代理配置"],["secret-id","凭据引用"],["reasoning-template","思考模板"],["prompt-post-processing","提示词后处理"],["regex-preset","正则预设"],["stop-strings","停止字符串"],["start-reply-with","回复前缀"], ...(draft.mode === "tc" ? [["sysprompt","系统提示词"],["context","上下文模板"],["instruct","指令模板"],["tokenizer","分词器"]] : [])].map(([key,label]) => <Field key={key} label={label}><input value={draft[key] ?? ""} onChange={e => change(key,e.target.value)} /></Field>)}
      <Field label="应用时跳过的字段（每行一个）"><textarea value={(draft.exclude || []).join("\n")} onChange={e => change("exclude", e.target.value.split("\n").filter(Boolean))} /></Field>
    </Fold>
    </Fold><Footer {...edit} busy={task.busy} save={() => task.run(async () => { await host.saveProfile(id, edit.base, draft); edit.saved(clone(host.snapshot().resources.connection.find(x => x.id === id)!.data!)); })} />
  </fieldset>;
}
function PersonaEditor({ host, id, deep }: { host: HostAdapter; id: string; deep?:boolean }) {
  const snap = useHost(host), task = useTask(), edit = useDraft(() => host.personaData(id), host.resourceVersions.persona,{host,key:"persona:"+id});
  const { draft, change } = edit, options = host.personaOptions(id);
  const action = (selector: string) => task.run(async () => { if (id !== snap.current.persona) await host.select("persona", id); host.click(selector); });
  const positionField=<Field label="注入位置"><Select value={draft.position ?? 0} onChange={e => change("position", Number(e.target.value))}>{[[0,"提示词 / 故事模板"],[2,"作者注释之前"],[3,"作者注释之后"],[4,"指定深度"],[9,"停用"]].map(([v,n]) => <option key={v} value={v}>{n}</option>)}</Select></Field>;
  return <fieldset className="wb-persona-editor" disabled={task.busy}><Notice error={task.error} />
    <div className="wb-persona-actions wb-persona-top-actions"><button disabled={edit.dirty} onClick={()=>host.download(new Blob([JSON.stringify({name:draft.name,description:draft.description,position:draft.position,depth:draft.depth,role:draft.role,lorebook:draft.lorebook,title:draft.title},null,2)],{type:"application/json"}),`${draft.name||"persona"}.json`)}><Download size={15}/>导出</button><button disabled={edit.dirty} onClick={()=>action("#sync_name_button")}><RefreshCw size={15}/>同步名称</button><button disabled={edit.dirty} onClick={()=>action("#PersonaManagement .user_stats_button")}><ChartNoAxesColumn size={15}/>统计</button><button disabled={edit.dirty} onClick={()=>action("#persona_delete_button")}><Trash2 size={15}/>删除</button><details className="wb-persona-more"><summary>更多</summary><div><button onClick={()=>action("#personas_backup")}><Download size={15}/>备份全部身份</button><button onClick={()=>action("#personas_restore")}><Upload size={15}/>恢复备份</button></div></details></div>
    <div className="wb-resource-detail wb-persona-fields">
    <div className="wb-persona-short-fields"><Field label="用户名称"><input value={draft.name ?? ""} onChange={e => change("name", e.target.value)} /></Field>{deep?positionField:<Field label="说明标题"><input value={draft.title ?? ""} onChange={e => change("title", e.target.value)} /></Field>}{deep&&<><Field label="深度"><input type="number" min={0} max={9999} value={draft.depth ?? 2} onChange={e => change("depth", Number(e.target.value))}/></Field><Field label="注入角色"><Select value={draft.role ?? 0} onChange={e => change("role",Number(e.target.value))}><option value={0}>System</option><option value={1}>User</option><option value={2}>Assistant</option></Select></Field></>}</div>
    <Field label="用户描述"><textarea rows={5} value={draft.description ?? ""} onChange={e => change("description", e.target.value)} /></Field>
    {!deep&&<><h4>注入设置</h4>{positionField}</>}
    {!deep&&<div className="wb-form-pair"><Field label="深度"><input type="number" min={0} max={9999} value={draft.depth ?? 2} onChange={e => change("depth", Number(e.target.value))} /></Field><Field label="注入角色"><Select value={draft.role ?? 0} onChange={e => change("role", Number(e.target.value))}><option value={0}>System</option><option value={1}>User</option><option value={2}>Assistant</option></Select></Field></div>}
    <Field label="绑定世界书"><Select value={draft.lorebook || ""} onChange={e => change("lorebook", e.target.value)}><option value="">不绑定</option>{snap.resources.world.map(w => <option key={w.id}>{w.name}</option>)}</Select></Field>
    <h4>默认与锁定</h4>{!options.current && <p className="wb-native-caption">切换到此身份后可调整锁定关系。</p>}
    <div className="wb-lock-grid">{([ ["default", "默认身份"], ["character", "锁定当前角色"], ["chat", "锁定当前对话"] ] as const).map(([key,label]) => <Check key={key} label={label} disabled={!options.current || edit.dirty} checked={!!options.locks[key]} onChange={v => task.run(() => host.personaLock(key,v))} />)}{!deep&&<Check label="自动锁定到当前对话" checked={options.preferences.persona_auto_lock} onChange={v => task.run(() => host.personaPreference("persona_auto_lock",v))}/>}</div>
    {!deep&&<><h4>全局偏好</h4>{[["persona_show_notifications","切换身份时显示通知"],["persona_allow_multi_connections","允许角色关联多个身份"]].map(([key,label]) => <Check key={key} label={label} checked={options.preferences[key]} onChange={v => task.run(() => host.personaPreference(key,v))} />)}</>}
    {deep&&<Fold title="说明标题"><Field label="说明标题"><input value={draft.title ?? ""} onChange={e=>change("title",e.target.value)}/></Field></Fold>}

    </div><Footer {...edit} busy={task.busy} save={() => task.run(async () => edit.saved(await host.savePersona(id,edit.base,draft)))} />
  </fieldset>;
}
const parameterNames: Record<string,string> = { temperature:"温度", top_p:"Top P", top_k:"Top K", frequency_penalty:"频率惩罚", presence_penalty:"存在惩罚", repetition_penalty:"重复惩罚", openai_max_tokens:"最大回复 Token", openai_max_context:"上下文 Token 上限", stream_openai:"流式传输", show_thoughts:"请求思维链", reasoning_effort:"思考强度",seed:"随机种子",n:"回复数量" };
function PresetEditor({ host, id, deep, onSelect, view }: { host: HostAdapter; id: string; deep?: boolean; onSelect: (id: string) => void;view?:"prompts" }) {
  const task = useTask(), edit = useDraft(() => host.presetData(id), host.resourceVersions.preset,{host,key:"preset:"+id});
  const { draft, change } = edit, [entry, setEntry] = useState(""), [editorOpen,setEditorOpen] = useState(!!deep), [scope, setScope] = useState(0), [advanced, setAdvanced] = useState(host.drafts.get("preset:"+id)?.extra?.advanced??"");
  useLayoutEffect(()=>{const cached=host.drafts.get("preset:"+id);if(cached)cached.extra={...cached.extra,advanced};},[advanced,edit.base,draft]);
  const prompts: Data[] = draft.prompts || [], scopes: Data[] = draft.prompt_order || [], order: Data[] = scopes[scope]?.order || [];
  const selected = prompts.find(p => p.identifier === entry) || prompts.find(p => p.identifier === order[0]?.identifier) || prompts[0];
  const setOrder = (value: Data[]) => { const next = clone(scopes); if (!next[scope]) next[scope] = { character_id:100000, order:[] }; next[scope].order = value; change("prompt_order",next); };
  const updatePrompt = (patch: Data) => change("prompts",prompts.map(p => p.identifier === selected.identifier ? { ...p,...patch } : p));
  const pins = host.prefs().presetPins ?? ["temperature","openai_max_tokens"];
  const always = ["stream_openai","show_thoughts"];
  const field = (key: string) => typeof draft[key] === "boolean" || always.includes(key) ? <Check key={key} label={parameterNames[key] || key} checked={!!draft[key]} onChange={v => change(key,v)} /> : <Field key={key} label={parameterNames[key] || key}><input type={typeof draft[key] === "number" ? "number" : "text"} step="any" value={draft[key] ?? ""} onChange={e => change(key,typeof draft[key] === "number" ? Number(e.target.value) : e.target.value)} /></Field>;
  const parameters = Object.keys(draft).filter(k => ["number","boolean"].includes(typeof draft[k]) || k === "reasoning_effort");
  return <fieldset disabled={task.busy} className={`wb-preset-editor ${deep&&view!=="prompts"?"is-parameter-view":""}`}>
    <Notice error={task.error} />
    <section className="wb-preset-common"><Fold title="自定义常用项" icon={<SlidersHorizontal size={15}/>} toolbar={<div className="wb-check-pair">{always.map(field)}</div>}><div className="wb-parameter-options">{parameters.filter(k => !always.includes(k)).map(k => <Check key={k} label={parameterNames[k] || k} checked={pins.includes(k)} onChange={v => host.preference({ presetPins: v ? [...pins,k] : pins.filter(p => p !== k) })} />)}</div></Fold>{pins.some(k=>k in draft&&!always.includes(k))&&<div className="wb-parameter-strip">{pins.filter(k => k in draft && !always.includes(k)).map(field)}</div>}</section>
    {deep&&view!=="prompts"&&<section className="wb-deep-parameters">{[["常用参数",["temperature","openai_max_tokens","top_p","openai_max_context"]],["采样与高级配置",["frequency_penalty","presence_penalty","seed","n"]]].map(([title,keys])=><section className="wb-designed-section" key={String(title)}><h3>{title}</h3><div className="wb-designed-fields">{(keys as string[]).filter(k=>k in draft).map(k=>["temperature","top_p","frequency_penalty","presence_penalty"].includes(k)?<Field key={k} label={parameterNames[k]}><input aria-label={parameterNames[k]} type="range" min={k.includes("penalty")?-2:0} max={k==="top_p"?1:2} step={.01} value={draft[k]} onChange={e=>change(k,Number(e.target.value))}/><output>{draft[k]}</output></Field>:field(k))}</div></section>)}<Fold title="当前后端的其他参数"><div className="wb-designed-fields">{parameters.filter(k=>![...always,"temperature","openai_max_tokens","top_p","openai_max_context","frequency_penalty","presence_penalty","seed","n"].includes(k)).map(field)}</div></Fold></section>}
    <div className="wb-preset-columns"><section className="wb-prompt-list"><div className="wb-section-title">提示词 · {order.length || prompts.length}<IconButton title="新增提示词" onClick={() => { const identifier = crypto.randomUUID?.() || `wb-${Date.now()}`; change("prompts",[...prompts,{identifier,name:"新提示词",role:"system",content:""}]); setOrder([...order,{identifier,enabled:true}]); setEntry(identifier);setEditorOpen(true); }}><Plus size={16} /></IconButton>{scopes.length > 1 && <Select aria-label="提示词作用范围" value={scope} onChange={e => setScope(Number(e.target.value))}>{scopes.map((s,i) => <option key={i} value={i}>{s.character_id === 100000 ? "全局" : `角色 ${s.character_id}`}</option>)}</Select>}</div>
      {(order.length ? order : prompts.map(p => ({identifier:p.identifier,enabled:true}))).map((item,i) => { const p = prompts.find(p => p.identifier === item.identifier);return <div className={`wb-prompt-row ${selected?.identifier === item.identifier ? "is-active" : ""}`} key={`${item.identifier}-${i}`}><input type="checkbox" aria-label={`启用提示词 ${p?.name || item.identifier}`} checked={item.enabled !== false} onChange={e => setOrder((order.length ? order : prompts.map(p => ({identifier:p.identifier,enabled:true}))).map((v,j) => j === i ? {...v,enabled:e.target.checked} : v))} /><button onClick={() => setEntry(item.identifier)} onDoubleClick={()=>{setEntry(item.identifier);setEditorOpen(true);}}><span>{p?.name || item.identifier}</span><small>{p?.marker ? "动态内容" : p?.role || "system"}</small></button><IconButton title={`编辑提示词 ${p?.name||item.identifier}`} onClick={()=>{setEntry(item.identifier);setEditorOpen(true);}}><PencilLine size={14}/></IconButton></div>; })}
    </section></div>
    <div className={`wb-preset-scroll ${editorOpen?"is-editor-open":""}`}>
      {selected ? <div className={`wb-prompt-collapse ${editorOpen?"is-open":""}`} inert={!editorOpen}><div className="wb-prompt-collapse-body"><section className="wb-prompt-editor"><IconButton title="收起提示词编辑" onClick={()=>setEditorOpen(false)}><X size={15}/></IconButton><div className="wb-editor-heading"><input aria-label="提示词名称" value={selected.name || ""} onChange={e=>updatePrompt({name:e.target.value})}/><Select aria-label="提示词角色" value={selected.role || "system"} onChange={e=>updatePrompt({role:e.target.value})}><option>system</option><option>user</option><option>assistant</option></Select>{[-1,1].map(dir => <IconButton key={dir} title={dir < 0 ? "上移提示词" : "下移提示词"} disabled={!order.length || order.findIndex(p=>p.identifier===selected.identifier)+dir<0 || order.findIndex(p=>p.identifier===selected.identifier)+dir>=order.length} onClick={() => { const next=clone(order), i=next.findIndex(p=>p.identifier===selected.identifier); [next[i],next[i+dir]]=[next[i+dir],next[i]];setOrder(next); }}>{dir<0?<ArrowUp size={15}/>:<ArrowDown size={15}/>}</IconButton>)}</div>

        {selected.marker ? <p className="wb-note">此项由酒馆动态组装，可在上方控制启用与顺序。</p> : <Field label="提示词正文"><textarea rows={4} value={selected.content || ""} onChange={e=>updatePrompt({content:e.target.value})}/></Field>}

      </section></div></div> : <Empty>此类预设没有提示词子条目</Empty>}
      <Fold title="更多预设设置" initial={!!deep}>        {selected && !selected.marker && <Fold title="注入与触发">
          <Field label="提示词注入位置"><Select value={selected.injection_position ?? 0} onChange={e=>updatePrompt({injection_position:Number(e.target.value)})}><option value={0}>按列表顺序</option><option value={1}>指定聊天深度</option></Select></Field>
          <div className="wb-form-pair"><Field label="提示词深度"><input type="number" min={0} value={selected.injection_depth ?? 4} onChange={e=>updatePrompt({injection_depth:Number(e.target.value)})}/></Field><Field label="提示词顺序"><input type="number" value={selected.injection_order ?? 100} onChange={e=>updatePrompt({injection_order:Number(e.target.value)})}/></Field></div>
          <Check label="禁止角色覆盖" checked={!!selected.forbid_overrides} onChange={v=>updatePrompt({forbid_overrides:v})}/>
          <Field label="生成类型（每行一个，留空为全部）"><textarea value={(selected.injection_trigger || []).join("\n")} placeholder="normal / continue / regenerate / impersonate" onChange={e=>updatePrompt({injection_trigger:e.target.value.split("\n").map(v=>v.trim()).filter(Boolean)})}/></Field>
        </Fold>}
        {selected && !selected.marker && <button className="wb-link" onClick={()=>{ if(confirm("删除这个提示词？保存后生效。")){ change("prompts",prompts.filter(p=>p.identifier!==selected.identifier));setOrder(order.filter(p=>p.identifier!==selected.identifier));setEntry("");} }}><Trash2 size={14}/>删除提示词</button>}<Fold title="其他生成参数">{parameters.filter(k=>!pins.includes(k)&&!always.includes(k)).map(field)}</Fold>
      <Fold title="提示格式">{[["impersonation_prompt","AI 帮答指令"],["new_chat_prompt","新对话提示"],["new_group_chat_prompt","新群聊提示"],["new_example_chat_prompt","对话示例提示"],["continue_nudge_prompt","续写提示"],["send_if_empty","空输入替代文本"],["wi_format","世界书格式"],["scenario_format","场景格式"],["personality_format","性格格式"]].filter(([key])=>key in draft).map(([key,label])=><Field key={key} label={label}><textarea value={draft[key] || ""} onChange={e=>change(key,e.target.value)}/></Field>)}</Fold>
      <Fold title="模型 / 连接绑定">{(["connection","model"] as const).map(scope=><Check key={scope} label={`绑定当前${scope==="connection"?"连接":"模型"}`} disabled={scope==="connection"&&!host.snapshot().current.connection} checked={host.prefs().bindings[host.bindingKey(scope)]===id} onChange={v=>{ const bindings={...host.prefs().bindings};if(v)bindings[host.bindingKey(scope)]=id;else delete bindings[host.bindingKey(scope)];host.preference({bindings}); }}/>)}</Fold>
      <Fold title="文件与高级编辑" initial={!!deep}><div className="wb-persona-actions"><button onClick={()=>{const name=prompt("新预设名称");if(name)task.run(async()=>onSelect(await host.createPreset(name)));}}><Plus size={15}/>新建预设</button><button onClick={()=>{const name=prompt("副本名称",`${id} 副本`);if(name)task.run(async()=>{const next=await host.createPreset(name,draft);edit.saved(draft);onSelect(next);});}}><Copy size={15}/>另存为</button><button onClick={()=>{if(confirm(`删除预设「${id}」？`))task.run(async()=>{await host.deletePreset(id);onSelect(host.snapshot().current.preset);});}}><Trash2 size={15}/>删除预设</button></div><button onClick={()=>host.download(new Blob([JSON.stringify(draft,null,2)],{type:"application/json"}),`${id}.json`)}><Download size={15}/>导出预设</button><Field label="导入预设到草稿"><input type="file" accept=".json,application/json" onChange={e=>{const file=e.target.files?.[0];if(file)task.run(async()=>{const value=JSON.parse(await file.text());validatePreset(value);edit.setDraft(value);});}}/></Field>
        <Field label="预设 JSON"><textarea className="wb-code" value={advanced || JSON.stringify(draft,null,2)} onChange={e=>{setAdvanced(e.target.value);try{const value=JSON.parse(e.target.value);validatePreset(value);edit.setDraft(value);setAdvanced("");}catch{/* retain invalid input */}}}/></Field>

      </Fold></Fold>
    </div>
    <Footer {...edit} dirty={edit.dirty || !!advanced} busy={task.busy} reset={()=>{setAdvanced("");edit.reset();}} save={()=>task.run(async()=>{if(advanced)throw new Error("JSON 无法解析，请先修正。");edit.saved(await host.savePreset(id,edit.base,draft));})}/>
  </fieldset>;
}
