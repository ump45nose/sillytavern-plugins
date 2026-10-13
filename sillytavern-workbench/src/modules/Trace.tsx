import { Select } from "../ui/Select";
import React, { useEffect, useState } from "react";
import { ArrowUpRight, Download, Trash2 } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import { Dialog, Empty, IconButton } from "../ui/common";
const groups = [ ["system","系统","#9d91e9"], ["preset","预设","#bc82c8"], ["world","世界书","#d99255"], ["character","角色","#d9777b"], ["history","历史（含输入）","#43a4b2"], ["input","输入","#69a78a"] ];
const compact = (n: number | null | undefined) => n == null ? "—" : n >= 1000 ? `${(n/1000).toFixed(1)}k` : String(n);
export default function Trace({ host, trace }: { host: HostAdapter; trace: any }) {
  const [, tick] = useState(0), [id,setId] = useState(""), [full,setFull] = useState(false), [tab,setTab] = useState("messages");
  useEffect(()=>{const timer=setInterval(()=>tick(v=>v+1),750);return()=>clearInterval(timer);},[]);
  const records=[...trace.records].reverse(),record=records.find(x=>x.id===id)||records[0];
  const counts: Record<string,number|null>={system:0,preset:0,world:0,character:0,history:0,input:null};
  for(const [key,value] of Object.entries(record?.composition?.counts || {})) {
    const kind=key==="main" ? "system" : /^worldInfo/.test(key)?"world":/^(charDescription|charPersonality|scenario|personaDescription|dialogueExamples)$/.test(key)?"character":key==="chatHistory"?"history":"preset";
    if(typeof value === "number" && Number.isFinite(value)) counts[kind]=Number(counts[kind])+value;
  }
  const hasCounts=record?.composition?.counts, total=Object.values(counts).reduce<number>((sum,n)=>sum+(n||0),0);
  const hits=Array.isArray(record?.worldInfo)?record.worldInfo:[];
  const time=(offset=0)=>record?.timestamp?new Date(record.timestamp+offset).toLocaleTimeString('zh-CN',{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit',fractionalSecondDigits:3}):'—';
  const details = <><div className="wb-tabs">{[["messages","实际请求"],["world","世界书"],["assembled","组装快照"]].map(([key,label])=><button key={key} className={tab===key?"is-active":""} onClick={()=>setTab(key)}>{label}</button>)}</div><div className="wb-trace-body">{tab==="world"?hits.map((e:any,i:number)=><details key={i} open><summary>{e.world} / {e.comment||e.uid}</summary><pre>{e.content}</pre></details>):tab==="assembled"?<><p className="wb-caption">{record?.assemblyEvent} · 后续插件可能继续修改</p><pre>{JSON.stringify(record?.assembled,null,2)}</pre></>:<>{record?.body?.messages?.map((m:any,i:number)=><details key={i} open={i===0}><summary>{i+1} · {m.role}</summary><pre>{typeof m.content==='string'?m.content:JSON.stringify(m.content,null,2)}</pre></details>)}<details><summary>完整请求与参数</summary><pre>{JSON.stringify(record?.body,null,2)}</pre></details></>}</div></>;
  return <div className="wb-trace wb-trace-v2"><header className="wb-resource-heading"><div><small>可观测性</small><h3>生成 Trace</h3></div><span className="wb-grow"/><IconButton title="清空记录" onClick={()=>{trace.clear();tick(v=>v+1);}}><Trash2 size={17}/></IconButton></header>
    {!record?<Empty>发送消息后，可查看请求与世界书命中。</Empty>:<div className="wb-trace-scroll">
      <Select aria-label="选择请求记录" value={record.id} onChange={e=>setId(e.target.value)}>{records.map((r,i)=><option value={r.id} key={r.id}>{records.length-i} · {r.generation?.type||"生成"} · HTTP {r.status}</option>)}</Select>
      <section className="wb-trace-section"><div className="wb-section-title"><strong>上下文构成</strong><span>{hasCounts?total.toLocaleString():"—"} / {compact(record.composition?.limit)}</span></div>
        <div className="wb-context-bar" aria-label="组装快照的 Token 构成">{groups.map(([key,label,color])=><span key={key} title={`${label} ${compact(hasCounts?counts[key]:null)}`} style={{background:color,flex:counts[key]||0}}/>)}</div>
        <div className="wb-context-legend">{groups.map(([key,label,color])=><div key={key}><i style={{background:color}}/><span>{label}</span><code>{compact(hasCounts?counts[key]:null)}</code></div>)}</div>
        <p className="wb-trace-evidence">{hasCounts?"组装阶段 · 原生分词计数；输入已计入历史，未单独拆分。":"本次请求未取得原生分词构成。"}</p>
      </section>
      <section className="wb-trace-section"><div className="wb-section-title"><strong>世界书触发 · {hits.length}</strong></div>
        {record.worldInfoEvidence!=="WORLD_INFO_ACTIVATED"&&<p className="wb-trace-evidence">未观察到命中事件，不等同于没有命中。</p>}
        {hits.map((entry:any,i:number)=><details className="wb-hit" key={i}><summary><span>{entry.comment||entry.world||`条目 ${entry.uid}`}</span><small>{entry.constant?"常驻":entry.vectorized?"向量化":"关键词"}</small><code>{entry.position===4?`@D${entry.depth??"—"}`:""}</code></summary><p className="wb-trace-evidence">配置关键词：{(entry.key||[]).join(' · ')||"无"}（事件未提供实际命中词）</p><pre>{entry.content}</pre></details>)}
      </section>
      <section className="wb-trace-section"><div className="wb-section-title"><strong>本次请求</strong></div><div className="wb-request-event"><time>{time()}</time><span>发送 · {record.body?.messages?.length??"—"} 条消息</span></div><div className="wb-request-event"><time>{record.elapsedMs==null?"—":time(record.elapsedMs)}</time><span>{record.status==='pending'?"等待响应":`HTTP ${record.status}`} · {record.elapsedMs==null?"—":`${Math.round(record.elapsedMs)} ms 到响应头`}</span></div>
        <p className="wb-trace-evidence">未采集首字时间与流式速率；浏览器请求记录不代表服务端最终出站内容。</p>
        <button className="wb-prompt-link" onClick={()=>{setTab("messages");setFull(true);}}>查看完整 Prompt <ArrowUpRight size={17}/></button>
      </section>
      <button className="wb-link" onClick={()=>host.download(new Blob([JSON.stringify(record,null,2)],{type:"application/json"}),`trace-${record.id}.json`)}><Download size={15}/>导出此条记录</button><p className="wb-trace-evidence">仅本次会话内存 · 最多 20 条 · 敏感字段脱敏</p>
    </div>}
    {full&&record&&<Dialog title="完整 Prompt · 浏览器请求" wide onClose={()=>setFull(false)}><div className="wb-trace-full">{details}</div></Dialog>}
  </div>;
}
