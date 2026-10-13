import React, { useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import { Empty, Select } from "../ui/common";
const seconds = (value?: number) => Number.isFinite(value) ? `${(value! / 1000).toFixed(2)} s` : "—";
export default function StartupDiagnostics({ host }: { host: HostAdapter }) {
  const [, update] = useState(0), [selected, setSelected] = useState("");
  useEffect(() => { const changed = () => update(value => value + 1); window.addEventListener("wb-startup-updated", changed); return () => window.removeEventListener("wb-startup-updated", changed); }, []);
  const history = window.workbenchStartup?.history || [], report = history.find((item: any) => item.id === selected) || history[0];
  if (!report) return <Empty>刷新网页后即可记录本次加载耗时。</Empty>;
  const m = report.milestones, mountMs = m.workbenchReadyMs && m.appReadyMs ? m.workbenchReadyMs - m.appReadyMs : undefined;
  const stages = [["首字节", report.navigation.firstByteMs], ["页面结构", report.navigation.domContentLoadedMs], ["工作台脚本", m.extensionLoadedMs], ["酒馆就绪", m.appReadyMs], ["工作台可见", m.workbenchReadyMs]] as const;
  const total = Math.max(...stages.map(([, value]) => Number(value) || 0), 1);
  return <section className="wb-startup-diagnostics" aria-label="加载诊断">
    <header className="wb-utility-heading"><div><h3>加载诊断</h3><p>当前浏览器的实际耗时，保留本标签页最近五次加载。</p></div><button onClick={() => update(value => value + 1)}><RefreshCw size={15} />刷新数据</button><button onClick={() => host.download(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }), `Workbench-startup-${new Date(report.startedAt).toLocaleDateString("sv-SE")}.json`)}><Download size={15} />导出报告</button></header>
    <Select aria-label="选择加载记录" value={report.id} onChange={e => setSelected(e.target.value)}>{history.map((item: any, index: number) => <option value={item.id} key={item.id}>{index === 0 ? "本次" : "之前"} · {new Date(item.startedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}{item.ready ? "" : " · 未完成初始化"}</option>)}</Select>
    <div className="wb-startup-cards">{[["酒馆就绪", seconds(m.appReadyMs)], ["工作台可见", seconds(m.workbenchReadyMs)], ["工作台挂载", seconds(mountMs)], ["已记录资源", `${report.requestCount}${report.incompleteResources ? "+" : ""}`]].map(([label, value]) => <div key={label}><small>{label}</small><strong>{value}</strong></div>)}</div>
    <div className="wb-startup-columns"><section><h4>加载时间线</h4><p>从打开网页开始计算；各阶段时间不相加。</p><div className="wb-startup-stages">{stages.map(([label, value]) => <div key={label}><span>{label}</span><i><span style={{ width: `${Math.max(0, Number(value) || 0) / total * 100}%` }} /></i><output>{seconds(value)}</output></div>)}</div><h4>优先排查</h4><ul>{report.navigation.firstByteMs > 1000 && <li>首字节等待较长，优先检查访问网络及服务响应。</li>}{m.extensionLoadedMs > 2000 && <li>工作台执行前已等待 {seconds(m.extensionLoadedMs)}，需结合资源请求、原生初始化及其他扩展定位。</li>}{mountMs && mountMs > 500 ? <li>工作台挂载超过 0.5 秒，检查界面初始化和重复渲染。</li> : <li>工作台挂载耗时 {seconds(mountMs)}，与酒馆整体初始化分开判断。</li>}{report.longTasks[0]?.durationMs > 200 && <li>记录到超过 200ms 的主线程任务，需要进一步分析脚本执行栈。</li>}</ul><p className="wb-caption">{report.counts.characters} 个角色 · {report.counts.messages} 条当前消息 · {(report.transferredBytes / 1024 / 1024).toFixed(2)} MB 已记录传输。{report.incompleteResources && "早期资源缓冲可能已满，资源列表不完整。"}</p><p className="wb-caption">本页只记录耗时，不修改加载流程；报告不含密钥或聊天正文。</p></section>
    <section><h4>耗时最长的已完成请求</h4><div className="wb-startup-table">{report.slowResources.map((resource: any, index: number) => <div key={index}><code title={resource.path}>{resource.path}</code><span>{seconds(resource.durationMs)}</span><small>{resource.transferredBytes > 0 ? `${Math.round(resource.transferredBytes / 1024)} KB` : resource.cacheKnown ? "缓存" : "未提供传输数据"}</small></div>)}</div><h4>主线程长任务</h4><div className="wb-startup-long-tasks">{report.longTasks.slice(0, 6).map((task: any, index: number) => <span key={index}>{seconds(task.startMs)} 处 · {Math.round(task.durationMs)} ms</span>)}{!report.longTasks.length && <small>没有捕获到长任务，或浏览器不支持此指标。</small>}</div></section></div>
  </section>;
}
