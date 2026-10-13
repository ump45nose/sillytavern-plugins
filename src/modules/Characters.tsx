import { Select } from "../ui/Select";
import React, { useContext, useState, useEffect } from "react";
import {createPortal} from "react-dom";
import {Star,Plus,Upload,Users,Grid2X2,Download,Trash2,Tag,Save,Copy,PencilLine,PanelLeftClose,PanelLeftOpen} from "lucide-react";
import type {HostAdapter} from "../host/adapter";
import type {Data,Item} from "../host/types";
import {clone} from "../host/model";
import {useHost,useTask,SearchBox,Notice,Empty,Field,IconButton} from "../ui/common";
import {ResourceRailContext} from "../ui/ResourcePicker";

function CharacterInfo({item,onEdit}:{item?:Item;onEdit:(id:string)=>void}){
 const data=item?.data?.data??item?.data;
 return <div className="wb-character-info"><p className="wb-caption">角色信息</p>{item?<><img src={item.image} alt=""/><h3 title={item.name}>{item.name}</h3><small>{(data?.tags||[]).join(" · ")||item.detail||"未分类角色"}</small><p>{String(data?.description||"暂无角色描述").replace(/<[^>]*>/g,"")}</p>{data?.personality&&<p>{data.personality}</p>}<button onClick={()=>onEdit(item.id)}><PencilLine size={14}/>编辑角色</button></>:<p>悬浮或聚焦角色，查看介绍。</p>}</div>;
}
export default function Characters({host,management,onManage}:{host:HostAdapter;management?:boolean;onManage?:(group?:string)=>void}){
 const snap=useHost(host),task=useTask(),rail=useContext(ResourceRailContext);
 const [query,setQuery]=useState(""),[tab,setTab]=useState("all"),[filter,setFilter]=useState("all"),[tag,setTag]=useState(""),[sort,setSort]=useState("name"),[selected,setSelected]=useState<string[]>([]),[editing,setEditing]=useState<string|null>(null),[preview,setPreview]=useState<string>("");
 const favorite=(x:Item)=>Boolean(x.data?.data?.extensions?.fav??x.data?.fav),favorites=snap.characters.filter(favorite);
 const tags=[...new Set(snap.characters.flatMap(x=>x.data?.data?.tags??[]))] as string[];
 const list=snap.characters.filter(x=>(filter!=="favorite"||favorite(x))&&(filter!=="current"||x.active)&&(!tag||x.data?.data?.tags?.includes(tag))&&`${x.name} ${x.detail} ${(x.data?.data?.tags||[]).join(" ")}`.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>sort==="recent"?Number(b.data?.date_last_chat??0)-Number(a.data?.date_last_chat??0):a.name.localeCompare(b.name,"zh"));
 const open=(item:Item)=>management?setEditing(item.id):task.run(async()=>{await host.selectCharacter(item.id);setTab("current");});
 const edit=(id:string)=>setEditing(id),info=<CharacterInfo item={snap.characters.find(x=>x.id===preview)} onEdit={edit}/>;
 const importCard=<label className="wb-import-character"><Upload size={15}/>导入<input aria-label="导入角色卡" type="file" accept=".png,.json,.yaml,.yml,.charx,.byaf" multiple onChange={e=>{const files=[...e.target.files||[]];task.run(async()=>{for(const file of files)await host.importCharacter(file);});}}/></label>;
 const create=()=>{const name=prompt("角色名称");if(name)task.run(async()=>setEditing(await host.createCharacter(name)));};
 const batch=<div className="wb-character-bulk"><label className="wb-check"><input aria-label="选择当前结果" type="checkbox" checked={list.length>0&&list.every(x=>selected.includes(x.id))} onChange={e=>setSelected(e.target.checked?list.map(x=>x.id):[])}/>全选</label><small>{selected.length} 已选</small><span className="wb-grow"/><button disabled={!selected.length||task.busy} onClick={()=>{const value=prompt("添加标签");if(value)task.run(()=>host.tagCharacters(selected,value));}}><Tag size={15}/>标签</button><button disabled={!selected.length||task.busy} onClick={()=>task.run(async()=>{for(const id of selected)await host.exportCharacter(id);})}><Download size={15}/>导出</button><button disabled={!selected.length||task.busy} onClick={()=>task.run(async()=>{for(const id of selected)await host.duplicateCharacter(id);})}><Copy size={15}/>复制</button><button disabled={!selected.length||task.busy} onClick={()=>{if(confirm(`删除选中的 ${selected.length} 个角色卡？聊天文件保留。`))task.run(async()=>{await host.deleteCharacters(selected);setSelected([]);});}}><Trash2 size={15}/>删除</button><button disabled={task.busy} onClick={create}><Plus size={15}/>新建</button>{importCard}</div>;
 return <div className={`wb-characters ${management?"is-management":""}`}><Notice error={task.error}/>
  {!management&&<><div className="wb-section-title"><span>收藏角色</span><span className="wb-grow"/>{onManage&&<button className="wb-link" onClick={()=>onManage()}>管理<Grid2X2 size={14}/></button>}</div><div className="wb-favorites">{favorites.map(x=><button key={x.id} title={x.name} className={x.active?"is-active":""} onClick={()=>open(x)} onMouseEnter={()=>setPreview(x.id)} onFocus={()=>setPreview(x.id)}><span className="wb-portrait"><img src={x.image} alt=""/></span><span>{x.name}</span></button>)}{!favorites.length&&<small>收藏常用角色，便于快速切换</small>}</div><div className="wb-tabs"><button className={tab==="all"?"is-active":""} onClick={()=>setTab("all")}>全部角色</button><button className={tab==="current"?"is-active":""} onClick={()=>setTab("current")}>当前角色</button><span className="wb-grow"/>{rail&&<IconButton title={rail.open?"收起角色信息":"展开角色信息"} onClick={()=>rail.setOpen(!rail.open)}>{rail.open?<PanelLeftClose size={16}/>:<PanelLeftOpen size={16}/>}</IconButton>}</div></>}
  {(tab==="all"||management)&&!editing?<section className="wb-library-content">
   {management&&<><header className="wb-designed-page-head"><div><h2>角色管理</h2><small>{list.length} 个角色 · 悬浮查看介绍</small></div></header>{batch}</>}
   <div className={`wb-character-search-row ${management?"is-management":""}`}><SearchBox value={query} onChange={setQuery} placeholder="搜索角色或标签"/>{management&&<><Select aria-label="角色筛选" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部角色</option><option value="favorite">我的收藏</option><option value="current">当前角色</option></Select><Select aria-label="标签筛选" value={tag} onChange={e=>setTag(e.target.value)}><option value="">所有标签</option>{tags.map(t=><option key={t}>{t}</option>)}</Select></>}<Select aria-label="角色排序" value={sort} onChange={e=>setSort(e.target.value)}><option value="name">名称排序</option><option value="recent">最近对话</option></Select></div>
   <div className={`wb-character-browse ${management?"has-info":""}`}>{management&&<aside>{info}</aside>}<div><div className={management?"wb-card-grid":"wb-character-list"}>{list.map(x=><article key={x.id} className={`wb-character-card ${x.active?"is-active":""} ${selected.includes(x.id)?"is-selected":""}`} onMouseEnter={()=>setPreview(x.id)} onFocus={()=>setPreview(x.id)}>
    {management&&<input type="checkbox" aria-label={`选择 ${x.name}`} checked={selected.includes(x.id)} onChange={e=>setSelected(v=>e.target.checked?[...v,x.id]:v.filter(id=>id!==x.id))}/>}
    <button className="wb-character-main" title={x.name} onClick={()=>open(x)}><span className="wb-portrait"><img src={x.image} alt=""/></span><span><strong>{x.name}</strong><small>{x.detail||"未分类角色"}</small></span>{x.active&&<em>当前</em>}</button>
    <IconButton title={favorite(x)?`取消收藏 ${x.name}`:`收藏 ${x.name}`} onClick={()=>task.run(()=>host.favorite(x))}><Star size={15} fill={favorite(x)?"currentColor":"none"}/></IconButton>
    {management&&<IconButton title={`编辑角色 ${x.name}`} onClick={()=>edit(x.id)}><PencilLine size={14}/></IconButton>}
   </article>)}</div>{!list.length&&<Empty>没有符合条件的角色</Empty>}</div></div>
  </section>:<div className="wb-character-detail-wrap">{editing&&<button className="wb-link" onClick={()=>{if(window.dispatchEvent(new Event("wb-before-close",{cancelable:true})))setEditing(null);}}>← 返回角色库</button>}{editing||snap.character?<CharacterEditor key={editing||snap.character!.id} id={editing||snap.character!.id} host={host}/>:<Empty>先选择角色</Empty>}</div>}
  {!management&&<footer className="wb-resource-footer"><button onClick={create}><Plus size={16}/>新建</button>{importCard}<button onClick={()=>onManage?.("群组")}><Users size={16}/>群组</button>{onManage&&<button onClick={()=>onManage()}><Grid2X2 size={16}/>独立管理</button>}</footer>}
  {rail?.open&&rail.target&&createPortal(<div className="wb-character-rail"><header className="wb-rail-heading"><strong>角色信息</strong><IconButton title="收起角色信息" onClick={()=>rail.setOpen(false)}><PanelLeftClose size={16}/></IconButton></header>{info}</div>,rail.target)}
 </div>;
}
function CharacterEditor({ host, id }: { host: HostAdapter; id: string }) {
  const task = useTask(),
    [base, setBase] = useState<Data | null>(host.drafts.get("character:"+id)?.base||null),
    [draft, setDraft] = useState<Data | null>(host.drafts.get("character:"+id)?.draft||null),
    [message, setMessage] = useState("");
  const dirty = !!base && JSON.stringify(base) !== JSON.stringify(draft);
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
  useEffect(()=>{if(base&&draft)host.drafts.set("character:"+id,{base:clone(base),draft:clone(draft)});},[base,draft,id]);
  useEffect(() => {
    const guard = (e: Event) => {
      if ((e as CustomEvent).detail?.preserveDrafts)return;
      if (dirty && !confirm("角色有未保存修改，放弃这些修改？"))
        e.preventDefault();
    };
    const unload = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("wb-before-close", guard);
    window.addEventListener("beforeunload", unload);
    return () => {
      window.removeEventListener("wb-before-close", guard);
      window.removeEventListener("beforeunload", unload);
    };
  }, [dirty]);
  if (!draft || !base)
    return (
      <>
        <Notice error={task.error} />
        <Empty>正在读取角色…</Empty>
      </>
    );
  const field = (key: string, label: string, rows = 4) => (
    <Field label={label}>
      <textarea
        rows={rows}
        value={draft[key] ?? ""}
        onChange={(e) => {
          setDraft({ ...draft, [key]: e.target.value });
          setMessage("");
        }}
      />
    </Field>
  );
  return (
    <fieldset disabled={task.busy} className="wb-character-editor">
      <Notice error={task.error} />
      <div className="wb-role-heading">
        <img src={host.snapshot().characters.find((c) => c.id === id)?.image} />
        <Field label="角色名称">
          <input
            value={draft.name ?? ""}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </Field>
      </div>
      <div className="wb-designed-actions"><button onClick={()=>task.run(()=>host.selectCharacter(id))}><Users size={15}/>开始对话</button><label className="wb-import-character"><Upload size={15}/>更换头像<input aria-label="上传角色头像" type="file" accept="image/*" onChange={e=>{const file=e.target.files?.[0];if(file)task.run(()=>host.characterAvatar(id,file));}}/></label><button onClick={()=>task.run(()=>host.exportCharacter(id))}><Download size={15}/>导出角色</button><button onClick={()=>task.run(()=>host.duplicateCharacter(id))}><Copy size={15}/>复制角色</button></div>
      <Field label="标签（逗号分隔）">
        <input
          value={(draft.tags ?? []).join(", ")}
          onChange={(e) =>
            setDraft({
              ...draft,
              tags: e.target.value
                .split(",")
                .map((x) => x.trim())
                .filter(Boolean),
            })
          }
        />
      </Field>
      {field("description", "角色描述", 7)}
      {field("first_mes", "第一条消息", 6)}
      <Field label="备选开场白（以单独一行 --- 分隔）"><textarea value={(draft.alternate_greetings||[]).join("\n---\n")} onChange={e=>setDraft({...draft,alternate_greetings:e.target.value.split(/\n---\n/).filter(Boolean)})}/></Field>
      <details>
        <summary>高级定义</summary>
        {field("personality", "性格")}
        {field("scenario", "场景")}
        {field("mes_example", "对话示例")}
        {field("system_prompt", "系统提示词")}
        {field("post_history_instructions", "历史后指令")}
        {field("creator_notes","创作者注释")}
        <div className="wb-designed-fields">{[["creator","创建者"],["character_version","角色版本"]].map(([key,label])=><Field key={key} label={label}><input value={draft[key]||""} onChange={e=>setDraft({...draft,[key]:e.target.value})}/></Field>)}</div>
        <Field label="角色世界书"><Select value={draft.extensions?.world||""} onChange={e=>setDraft({...draft,extensions:{...draft.extensions,world:e.target.value}})}><option value="">不绑定</option>{host.snapshot().resources.world.map(w=><option key={w.id}>{w.name}</option>)}</Select></Field>
        <Field label="发言积极性"><input type="range" min={0} max={1} step={.05} value={draft.extensions?.talkativeness??.5} onChange={e=>setDraft({...draft,extensions:{...draft.extensions,talkativeness:Number(e.target.value)}})}/></Field>
        <Field label="深度提示词"><textarea value={draft.extensions?.depth_prompt?.prompt||""} onChange={e=>setDraft({...draft,extensions:{...draft.extensions,depth_prompt:{...draft.extensions?.depth_prompt,prompt:e.target.value}}})}/></Field>
        <div className="wb-form-pair"><Field label="深度"><input type="number" min={0} value={draft.extensions?.depth_prompt?.depth??4} onChange={e=>setDraft({...draft,extensions:{...draft.extensions,depth_prompt:{...draft.extensions?.depth_prompt,depth:Number(e.target.value)}}})}/></Field><Field label="注入角色"><Select value={draft.extensions?.depth_prompt?.role||"system"} onChange={e=>setDraft({...draft,extensions:{...draft.extensions,depth_prompt:{...draft.extensions?.depth_prompt,role:e.target.value}}})}><option>system</option><option>user</option><option>assistant</option></Select></Field></div>
      </details>
      <div className="wb-editor-footer">
        <small>{dirty ? "未保存修改" : message}</small>
        <span className="wb-grow" />
        <button
          disabled={!dirty || task.busy}
          className="wb-primary"
          onClick={() =>
            task.run(async () => {
              const data = await host.saveCharacter(id, base, draft);
              setBase(clone(data.data));
              setDraft(clone(data.data));
              setMessage("已保存");
            })
          }
        >
          <Save size={15} />
          保存
        </button>
      </div>
    </fieldset>
  );
}
