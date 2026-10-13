import React, { useEffect, useReducer } from "react";
import { FlaskConical, PlugZap, RefreshCw } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import { useHost, useTask, Field, Notice } from "../ui/common";
import DesignedSettings from "./DesignedSettings";
import { Select } from "../ui/Select";

export function ConnectionRuntime({host}: {host:HostAdapter}) {
  const snap=useHost(host), task=useTask(), [,redraw]=useReducer(n=>n+1,0);
  const state=host.connectionControls();
  useEffect(()=>host.watchConnectionControls(redraw),[host]);
  useEffect(()=>host.decorateConnectionControls(),[host,state.main.id,state.provider?.value,state.model?.id]);
  const field=(control:NonNullable<typeof state.model>,label:string)=>control.type==="select"
    ? <Select aria-label={label} value={control.value} disabled={control.disabled||snap.busy} onChange={e=>task.run(()=>host.setConnectionControl(control.id,e.target.value))}>{control.options.map(o=><option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}</Select>
    : <input aria-label={label} value={control.value} disabled={control.disabled||snap.busy} placeholder="输入模型 ID" onChange={e=>host.setConnectionControl(control.id,e.target.value)}/>;
  return <>
    <section className="wb-connection-quick">
      <div className="wb-section-title">API 连接配置<span className="wb-grow"/><span className={`wb-dot ${snap.online?"online":""}`}/><small>{snap.online?"已连接":"未连接"}</small></div>
      <Field label="模型"><div className="wb-connection-model">{state.model?field(state.model,"运行模型"):<input aria-label="运行模型" value="由后端选择，可在下方配置" readOnly/>}<button className="wb-icon" title="刷新模型" aria-label="刷新模型" disabled={snap.busy||task.busy||state.connecting} onClick={()=>task.run(()=>host.click(`#${state.connect}`))}><RefreshCw size={17}/></button></div></Field>
      <div className="wb-connection-actions"><button className="wb-primary" disabled={snap.busy||task.busy||state.connecting} onClick={()=>task.run(()=>host.click(`#${state.connect}`))}><PlugZap size={15}/>{state.connecting?"连接中…":"连接"}</button>{state.test&&<button disabled={snap.busy||task.busy||state.connecting} title="发送测试消息，使用当前 API" onClick={()=>task.run(()=>host.click(`#${state.test}`))}><FlaskConical size={15}/>测试</button>}<span className="wb-grow"/><small>使用当前 API 配置</small></div>
      <Notice error={task.error}/>
      <div className="wb-form-pair"><Field label="接口类型">{field(state.main,"接口类型")}</Field>{state.provider&&<Field label="服务商">{field(state.provider,"服务商")}</Field>}</div>
    </section>
    <DesignedSettings host={host} page="connection" group="服务与凭据"/>
  </>;
}
