import React, {useState} from "react";
import {Keyboard, RotateCcw, X} from "lucide-react";
import type {HostAdapter} from "../host/adapter";
import {bindingError, bindingFromEvent, bindingParts, shortcutActions, shortcutFor} from "../host/operations";
import {useHost} from "./common";
import {Check} from "./ResourceControls";

export function Shortcuts({host}:{host:HostAdapter}) {
 useHost(host);
 const prefs=host.prefs(),[recording,setRecording]=useState<string|null>(null),[error,setError]=useState("");
 const change=(id:string,value:string)=>{host.preference({shortcuts:{...prefs.shortcuts,[id]:value}});setRecording(null);setError("");};
 const record=(e:React.KeyboardEvent,id:string)=>{
  if(recording!==id)return;
  e.preventDefault();e.stopPropagation();
  if(e.key==="Escape"){setRecording(null);setError("");return;}
  if(e.nativeEvent.isComposing||e.repeat||e.getModifierState("AltGraph"))return;
  const binding=bindingFromEvent(e);if(!binding)return;
  const conflict=shortcutActions.find(a=>a.id!==id&&shortcutFor(a.id,prefs.shortcuts)===binding);
  const problem=bindingError(binding)||(conflict?`已用于“${conflict.label}”，请换一组按键。`:"");
  if(problem){setError(problem);return;}
  change(id,binding);
 };
 return <div className="wb-shortcuts">
  <div className="wb-shortcuts-toolbar"><Check label="启用工作台快捷键" checked={prefs.shortcutsEnabled!==false} onChange={v=>host.preference({shortcutsEnabled:v})}/><button onClick={()=>{host.preference({shortcuts:{},shortcutsEnabled:true});setRecording(null);setError("");}}><RotateCcw size={15}/>恢复默认</button></div>
  <p className="wb-shortcuts-help">点击按键区域，按下新的组合。Esc 取消录入。</p>
  <div className="wb-shortcut-list">{shortcutActions.map(action=>{
   const binding=shortcutFor(action.id,prefs.shortcuts),active=recording===action.id;
   return <div className={`wb-shortcut-row ${active?"is-recording":""}`} key={action.id}>
    <span>{action.label}</span>
    <button className="wb-shortcut-record" data-wb-shortcut-recorder aria-label={`修改快捷键 ${action.label}`} aria-pressed={active} onClick={e=>{setRecording(action.id);setError("");e.currentTarget.focus();}} onKeyDown={e=>record(e,action.id)} onBlur={()=>{if(active){setRecording(null);setError("");}}}>
     {active?<span className="wb-recording-label"><Keyboard size={15}/>请按下组合键…</span>:binding?<span className="wb-keycaps">{bindingParts(binding).map((part,i)=><kbd key={i}>{part}</kbd>)}</span>:<span className="wb-shortcut-unbound">未设置</span>}
    </button>
    <button className="wb-icon" aria-label={`清除快捷键 ${action.label}`} title="清除绑定" disabled={!binding} onClick={()=>change(action.id,"")}><X size={14}/></button>
   </div>;
  })}</div>
  <p className={`wb-shortcut-status ${error?"is-error":""}`} role={error?"alert":"status"}>{error||(recording?"请包含 Ctrl、Alt 或 Command；避免使用浏览器和编辑常用组合。":"修改自动保存，清除绑定后该操作仍可点击使用。")}</p>
 </div>;
}
