import React, { useEffect, useId, useLayoutEffect, useRef, useState, createContext, useContext } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { Item } from "../host/types";
import { Empty, SearchBox } from "./common";
import { Select } from "./Select";
import {usePresence} from "./Motion";

export const ResourceRailContext = createContext<{open:boolean;setOpen:(open:boolean)=>void;target:HTMLElement|null}|null>(null);
/** Sidebar lists occupy a separate rail; independent editors keep their title picker. */
export function ResourcePicker({ label, items, id, active, choose, use, sortable = false, disabled = false, multiple, scopeLabel }: {
  label: string; items: Item[]; id: string; active: string; choose: (id: string) => void; use: (id: string) => void; sortable?: boolean; disabled?: boolean; multiple?:{selected:string[];toggle:(id:string,on:boolean)=>void}; scopeLabel?:string;
}) {
  const rail = useContext(ResourceRailContext);
  const [popupOpen, setPopupOpen] = useState(false), [query, setQuery] = useState(""), [sort, setSort] = useState("name");
  const open=rail?rail.open:popupOpen, setOpen=rail?rail.setOpen:setPopupOpen;
  const presence=usePresence(open?true:null);
  const button = useRef<HTMLButtonElement>(null), popup = useRef<HTMLDivElement>(null), popupId = useId();
  const [position, setPosition] = useState({ left:0, top:0, width:300, maxHeight:500 });
  const current = items.find(x => x.id === id);
  useLayoutEffect(() => {
    if (!open || rail) return;
    const place = () => { const r=button.current!.getBoundingClientRect(), width=Math.min(340,innerWidth-24);setPosition({left:Math.max(12,Math.min(r.left,innerWidth-width-12)),top:r.bottom+8,width,maxHeight:Math.min(500,innerHeight-r.bottom-20)}); };
    place(); window.addEventListener("resize",place); window.addEventListener("scroll",place,true);
    return () => { window.removeEventListener("resize",place);window.removeEventListener("scroll",place,true); };
  }, [open, rail]);
  useEffect(() => {
    if (!open || rail) return;
    const outside=(e:PointerEvent)=>{if(!button.current?.contains(e.target as Node)&&!popup.current?.contains(e.target as Node))setOpen(false);};
    document.addEventListener("pointerdown",outside);popup.current?.querySelector("input")?.focus();
    return () => document.removeEventListener("pointerdown",outside);
  }, [open, rail]);
  const close=()=>{if(!rail){setOpen(false);button.current?.focus();}};
  const list=items.filter(x=>`${x.name} ${x.detail}`.toLowerCase().includes(query.toLowerCase())).sort((a,b)=>sortable?a.name.localeCompare(b.name,"zh")*(sort==="name"?1:-1):0);
  return <div className="wb-resource-picker">
    <button ref={button} className="wb-resource-title" aria-label={rail?`${open?"收起":"展开"}${label}资源列表`:`选择${label}`} aria-expanded={open} aria-controls={open?popupId:undefined} disabled={disabled} onClick={()=>{setOpen(!open);setQuery("");}}><span>{current?.name||`选择${label}`}</span>{rail?(open?<PanelLeftClose size={16}/>:<PanelLeftOpen size={16}/>):<ChevronDown size={14}/>}</button>
    {presence.value&&(!rail||rail.target)&&createPortal(<div ref={popup} id={popupId} className={`wb-ui wb-resource-menu ${rail?"is-rail":""}`} data-wb-exiting={presence.exiting||undefined} inert={presence.exiting} role={rail?"region":"dialog"} aria-label={`${label}选择`} style={rail?undefined:position} onKeyDown={e=>{if(!rail&&e.key==="Escape"){e.preventDefault();e.stopPropagation();close();}}}>
      {rail&&<header className="wb-rail-heading"><strong>{label}</strong><button className="wb-icon" aria-label={`收起${label}资源列表`} title="收起资源列表" onClick={()=>setOpen(false)}><PanelLeftClose size={16}/></button></header>}
      <SearchBox value={query} onChange={setQuery} placeholder={`搜索${label}`}/>
      {sortable&&<Select aria-label={`${label}排序`} value={sort} onChange={e=>setSort(e.target.value)}><option value="name">名称 A–Z</option><option value="reverse">名称 Z–A</option></Select>}
      {multiple&&<p className="wb-caption">{scopeLabel||"启用世界书"} · 可多选，点击名称浏览条目</p>}
      <div className="wb-picker-list">
        {list.map((x,i)=><React.Fragment key={x.id}>{!sortable&&x.detail&&(i===0||list[i-1].detail!==x.detail)&&label==="连接"&&<p className="wb-caption">{x.detail}</p>}
          <div className={`wb-resource-choice ${id===x.id?"is-active":""}`}>
            {x.image&&<img src={x.image} alt=""/>}
            {multiple?<input type="checkbox" aria-label={`启用世界书 ${x.name}`} checked={multiple.selected.includes(x.id)} disabled={disabled} onChange={e=>multiple.toggle(x.id,e.target.checked)}/>:<button className="wb-picker-apply" title={`使用 ${x.name}`} aria-label={`使用 ${x.name}`} disabled={disabled} onClick={()=>{use(x.id);close();}}><span className={`wb-choice-state ${active===x.id?"is-current":""}`}/></button>}
            <button className="wb-picker-copy" title={x.name} onClick={()=>{choose(x.id);close();}}><strong>{x.name}</strong>{x.detail&&<small>{x.detail}</small>}</button>
            <ChevronRight size={13}/>
          </div></React.Fragment>)}
        {!list.length&&<Empty>没有符合条件的{label}</Empty>}
      </div>
    </div>,rail?.target??button.current?.closest("dialog[open]")??document.body)}
  </div>;
}
