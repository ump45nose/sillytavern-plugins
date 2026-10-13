import React from "react";
import { Activity, BookOpen, ChevronDown, ChevronRight, ScanLine, SlidersHorizontal, UserRound, X } from "lucide-react";
import {createPortal} from "react-dom";
import type { HostSnapshot, Panel, Resource } from "../host/types";
import { Empty, IconButton } from "./common";
import {usePresence} from "./Motion";
export const resourceLabels = { connection: "连接", preset: "预设", world: "世界书", persona: "用户设定" };
const icons = { preset: SlidersHorizontal, world: BookOpen, persona: UserRound };
export function Header({ snap, panel, chooser, setChooser, goPanel, next, select, model, focus, focused, focusShortcut, actions }: {
  snap: HostSnapshot; panel: Panel; chooser: Resource | null;
  setChooser: (value: Resource | null) => void; goPanel: (panel: Panel, id?: string) => void;
  next: (kind: Resource) => void; select: (kind: Resource, id: string, enabled: boolean) => void;
  model: string; focus: () => void; focused: boolean; focusShortcut:string;
  actions?: React.ReactNode;
}) {
  return <header className="wb-top">
    <button className="wb-identity" onClick={() => goPanel("character")} title={snap.character?.name || "选择角色"}>
      {snap.character?.image ? <img src={snap.character.image} alt="" /> : <span className="wb-avatar-fallback">N</span>}
      <strong>{snap.character?.name || "选择角色"}</strong>
    </button>
    <ResourceControls snap={snap} panel={panel} chooser={chooser} setChooser={setChooser} goPanel={goPanel} next={next} select={select} model={model}/>
    <div className="wb-top-right">
      <button className={`wb-top-action ${panel === "trace" ? "is-active" : ""}`} title="Trace" aria-label="Trace" aria-pressed={panel === "trace"} onClick={() => goPanel(panel === "trace" ? null : "trace")}><Activity size={24} /></button>
      {actions ?? <button className={`wb-top-action wb-focus-toggle ${focused ? "is-active" : ""}`} title={`专注模式${focusShortcut?" · "+focusShortcut:""}`} aria-label="专注模式" aria-pressed={focused} onClick={focus}><ScanLine size={24} /></button>}
      <span className="wb-layout-space" aria-hidden="true"/>
    </div>
  </header>;
}

/** Both desktop and PWA configuration rows share the same resource actions and selection UI. */
export function ResourceControls({snap,panel,chooser,setChooser,goPanel,next,select,model,mobile=false}:Pick<Parameters<typeof Header>[0],"snap"|"panel"|"chooser"|"setChooser"|"goPanel"|"next"|"select"|"model">&{mobile?:boolean}){
 const presence=usePresence(chooser);
 const overlay=(children:React.ReactNode)=>mobile?createPortal(<div className="wb-ui wb-mobile-resource-popup">{children}</div>,document.body):children;
 return <div className="wb-contexts">
      {(Object.keys(resourceLabels) as Resource[]).map(kind => {
        const items = snap.resources[kind], selected = items.find(x => x.id === snap.current[kind]);
        const Icon = kind === "connection" ? null : icons[kind];
        const value = selected?.name || (kind === "connection" ? model : "未选择");
        const count = kind === "world" ? items.filter(x => x.active).length : 0;
        return <div className={`wb-selector ${panel === kind || chooser === kind ? "is-active" : ""}`} key={kind}>
          <button className="wb-selector-detail" title={`${resourceLabels[kind]}详情`} aria-label={`${resourceLabels[kind]}详情`} onClick={() => goPanel(kind)}>
            {Icon ? <Icon size={17} /> : <span className={`wb-dot ${snap.online ? "online" : ""}`} />}
          </button>
          <button className="wb-selector-value" title={`${resourceLabels[kind]}：${value}`} aria-expanded={chooser === kind} aria-controls={`wb-choices-${kind}`} onClick={() => setChooser(chooser === kind ? null : kind)}>
            <span key={value + count} className="wb-value-text">{value}{count > 1 ? ` +${count - 1}` : ""}</span><ChevronDown size={13} />
          </button>
          <IconButton title={`下一个${resourceLabels[kind]}`} disabled={snap.busy} onClick={() => next(kind)}><ChevronRight size={16} /></IconButton>
          {presence.value === kind && overlay(<>
            <button className="wb-pop-dismiss" aria-label="关闭选择框" onClick={() => setChooser(null)} />
            <div className="wb-popover" role={mobile?"dialog":undefined} aria-label={mobile?`${resourceLabels[kind]}选择`:undefined} inert={presence.exiting} data-wb-exiting={presence.exiting||undefined} id={`wb-choices-${kind}`}>
              <div className="wb-section-title">{resourceLabels[kind]}<small>选择 · 查看详情</small>{mobile&&<button className="wb-icon" aria-label="关闭资源选择" onClick={()=>setChooser(null)}><X size={18}/></button>}</div>
              {items.map(item => <div className={`wb-quick-row ${(kind === "world" ? item.active : item.id === snap.current[kind]) ? "is-active" : ""}`} key={item.id}>
                <input type="checkbox" aria-label={`${kind === "world" ? "启用" : "选择"} ${item.name}`} checked={kind === "world" ? !!item.active : item.id === snap.current[kind]} disabled={snap.busy} onChange={e => select(kind, item.id, e.target.checked)} />
                <button onClick={() => goPanel(kind, item.id)}><strong>{item.name}</strong>{item.detail && <small>{item.detail}</small>}</button>
                <IconButton title={`查看 ${item.name} 详情`} onClick={() => goPanel(kind, item.id)}><ChevronRight size={15} /></IconButton>
              </div>)}
              {!items.length && <Empty>暂无配置</Empty>}
              <button className="wb-link" onClick={() => goPanel(kind)}>查看全部与编辑 <ChevronRight size={14} /></button>
            </div>
          </>)}
        </div>;
      })}
    </div>;
}
