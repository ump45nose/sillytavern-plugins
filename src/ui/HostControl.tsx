import React,{useEffect,useLayoutEffect,useReducer,useRef} from "react";
import {Select} from "./Select";
import type {HostAdapter} from "../host/adapter";
export type FormControl=HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement;
/** Presentation is ours; values, listeners, credentials and saves remain owned by the host. */
export function HostControl({host,node,label,presentation}:{host:HostAdapter;node:FormControl;label:string;presentation?:"number"}){
 const [,redraw]=useReducer(n=>n+1,0);
 useEffect(()=>{let frame=0;const sync=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(redraw);};const observer=new MutationObserver(sync);observer.observe(node,{attributes:true,childList:true,subtree:true});node.addEventListener("input",sync);node.addEventListener("change",sync);const unsub=host.subscribe(sync);return()=>{observer.disconnect();cancelAnimationFrame(frame);node.removeEventListener("input",sync);node.removeEventListener("change",sync);unsub();};},[host,node]);
 const update=(value:string)=>{node.value=value;node.dispatchEvent(new Event("input",{bubbles:true}));node.dispatchEvent(new Event("change",{bubbles:true}));redraw();host.refresh();};
 const common={"aria-label":label,disabled:node.disabled};
 if(node instanceof HTMLSelectElement){
  if(node.multiple)return <div className="wb-host-multiple">{[...node.options].map((o,i)=><label className="wb-check" key={o.value+":"+i}><input type="checkbox" aria-label={o.text} checked={o.selected} disabled={o.disabled||node.disabled} onChange={e=>{o.selected=e.target.checked;node.dispatchEvent(new Event("change",{bubbles:true}));redraw();host.refresh();}}/>{o.text}</label>)}</div>;
  return <Select {...common} value={node.value} onChange={e=>update(e.target.value)}>{[...node.options].map((o,i)=><option key={o.value+":"+i} value={o.value} disabled={o.disabled}>{o.text}</option>)}</Select>;
 }
 if(node instanceof HTMLTextAreaElement)return <textarea {...common} rows={node.rows||4} value={node.value} placeholder={node.placeholder} onChange={e=>update(e.target.value)}/>;
 if(node.type==="checkbox"||node.type==="radio")return <input {...common} type={node.type} checked={node.checked} onChange={()=>{node.click();redraw();host.refresh();}}/>;
 if(node.type==="file")return <input {...common} type="file" accept={node.accept} multiple={node.multiple} onChange={e=>{node.files=e.target.files;node.dispatchEvent(new Event("change",{bubbles:true}));}}/>;
 // Passwords use the original node. Never copy a credential into a React draft or attribute.
 if(node.type==="password"||/api_key|access_token|auth_token/.test(node.id))return <input {...common} type="password" autoComplete="new-password" placeholder="沿用已保存凭据；输入以替换" onChange={e=>update(e.target.value)}/>;
 return <input {...common} type={presentation||node.type||"text"} value={node.value} placeholder={node.placeholder} min={node.min} max={node.max} step={node.step||undefined} onChange={e=>update(e.target.value)}/>;
}
export function BoundControl({host,id,label,presentation}:{host:HostAdapter;id:string;label:string;presentation?:"number"}){
 const node=document.getElementById(id) as FormControl|null;
 return node?<HostControl host={host} node={node} label={label} presentation={presentation}/>:<small>当前宿主未提供此配置</small>;
}
/** Keep third-party custom-element state and handlers; only replace its surrounding layout. */
export function HostWidget({node}:{node:HTMLElement}){
 const ref=useRef<HTMLDivElement>(null);
 useLayoutEffect(()=>{const mark=document.createComment("Workbench custom control origin");node.before(mark);ref.current!.append(node);return()=>{mark.replaceWith(node);};},[node]);
 return <div className="wb-host-widget" ref={ref}/>;
}
