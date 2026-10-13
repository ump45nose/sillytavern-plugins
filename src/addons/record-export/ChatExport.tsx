import React, { useEffect, useRef, useState } from "react";
import { Download, FileOutput, RefreshCw, Search, Square, Trash2 } from "lucide-react";
import type { AddonHost } from "../types";
import type { ExportOptions, ExportRole, ExportSummary, TagStat } from "./xml-export";
import { Check, Fold } from "../../ui/ResourceControls";
import { Empty, Notice, Select, useHost, useTask } from "../../ui/common";
const htmlTags = new Set("a b br button code div em h1 h2 h3 h4 h5 h6 hr i iframe img input li link meta ol p pre script small span strong style table tbody td th thead tr u ul video audio".split(" "));
export default function ChatExport({ host }: { host: AddonHost }) {
  const snap = useHost(host), task = useTask(), chatKey = snap.chatKey;
  const [scanRevision, setScanRevision] = useState(0), [readyVersion, setReadyVersion] = useState(0), [phase, setPhase] = useState("scan");
  const [progress, setProgress] = useState({ done: 0, total: 0 }), [stats, setStats] = useState<TagStat[]>([]), [error, setError] = useState("");
  const [result, setResult] = useState<(ExportSummary & { id: number; warningCount: number }) | null>(null), [filtering, setFiltering] = useState(false), [downloading, setDownloading] = useState(false);
  const [retained, setRetained] = useState<string[]>([]), [excluded, setExcluded] = useState<string[]>([]), [custom, setCustom] = useState<string[]>([]), [tagQuery, setTagQuery] = useState(""), [manual, setManual] = useState("");
  const mode: ExportOptions["mode"] = retained.length ? "include" : excluded.length ? "exclude" : "all";
  const [roles, setRoles] = useState<ExportRole[]>(["user", "assistant"]), [from, setFrom] = useState(1), [to, setTo] = useState(1);
  const [keyword, setKeyword] = useState(""), [keepTags, setKeepTags] = useState(false), [metadata, setMetadata] = useState(true), [html, setHtml] = useState(false), [tab, setTab] = useState("structure"), [format, setFormat] = useState<"txt" | "md">("txt");
  const [timestamp, setTimestamp] = useState(0), [sourceCount, setSourceCount] = useState(0);
  const worker = useRef<Worker | null>(null), sequence = useRef(0), pending = useRef(-1), ready = useRef(false), lastChat = useRef(chatKey), download = useRef<{ id: number; resultId: number; filename: string } | null>(null);
  useEffect(() => {
    const snapshot = host.exportSnapshot(), id = ++sequence.current;
    if (lastChat.current !== chatKey) { setRetained([]); setExcluded([]); setCustom([]); setTagQuery(""); setManual(""); setKeyword(""); setFrom(1); setTo(snapshot.messages.length || 1); lastChat.current = chatKey; }
    else setTo(value => value === sourceCount || !sourceCount ? snapshot.messages.length || 1 : Math.min(value, snapshot.messages.length || 1));
    ready.current = false; pending.current = -1; download.current = null;
    setPhase("scan"); setFiltering(false); setDownloading(false); setError(""); setResult(null); setStats([]); setTimestamp(snapshot.timestamp); setSourceCount(snapshot.messages.length); setProgress({ done: 0, total: snapshot.messages.length });
    let instance: Worker;
    try { instance = new Worker(new URL("./export-worker.js", import.meta.url), { type: "module" }); }
    catch (failure) { setError(String(failure)); setPhase("error"); return; }
    worker.current = instance;
    instance.onmessage = event => {
      const data = event.data;
      if (data.type === "progress" && data.id === id) setProgress({ done: data.done, total: data.total });
      if (data.type === "scanned" && data.id === id) { ready.current = true; setStats(data.tags); setPhase("ready"); setReadyVersion(value => value + 1); }
      if (data.type === "result" && data.id === pending.current) { setResult(data); setFiltering(false); }
      const currentDownload = download.current;
      if (data.type === "download" && currentDownload && data.id === currentDownload.id && data.blob instanceof Blob) {
        if (currentDownload.resultId === pending.current) host.download(data.blob, currentDownload.filename);
        download.current = null; setDownloading(false);
      }
      if (data.type === "error" && (data.id === id || data.id === pending.current || data.id === download.current?.id)) { setError(data.message); setFiltering(false); setDownloading(false); if (data.id === id) setPhase("error"); }
    };
    instance.onerror = () => { setError("分析任务载入失败，请重新分析。"); setPhase("error"); setFiltering(false); setDownloading(false); };
    instance.postMessage({ type: "scan", id, messages: snapshot.messages });
    return () => { instance.terminate(); if (worker.current === instance) worker.current = null; ready.current = false; };
  }, [host, chatKey, scanRevision]);
  useEffect(() => {
    if (!ready.current || !worker.current) return;
    const id = ++sequence.current; pending.current = id; setFiltering(true); setResult(null); setError("");
    const options: ExportOptions = { mode, tags: retained.length ? retained : excluded, excludeTags: excluded, roles, from, to, keyword: keyword.trim(), keepTags };
    worker.current.postMessage({ type: "filter", id, options });
  }, [readyVersion, retained, excluded, roles, from, to, keyword, keepTags, chatKey]);
  const choose = (name: string, rule: "retain" | "exclude") => {
    const update = rule === "retain" ? setRetained : setExcluded, clear = rule === "retain" ? setExcluded : setRetained;
    update(value => value.includes(name) ? value.filter(tag => tag !== name) : [...value, name]);
    clear(value => value.filter(tag => tag !== name));
  };
  const preset = (rule: "retain" | "exclude") => {
    if (rule === "retain") { setRetained(["content", "after"]); setExcluded(value => value.filter(tag => tag !== "content" && tag !== "after")); }
    else { setExcluded(value => [...new Set([...value, "think"])]); setRetained(value => value.filter(tag => tag !== "think")); }
  };
  const absent = [...new Set([...custom, ...retained, ...excluded])].filter(name => !stats.some(stat => stat.name === name));
  const visibleTags = [...stats, ...absent.map(name => ({ name, path: name, depth: 0, count: 0, floors: 0, characters: 0 }))]
    .filter(stat => (html || !htmlTags.has(stat.name.toLowerCase()) || custom.includes(stat.name) || retained.includes(stat.name) || excluded.includes(stat.name)) && stat.path.toLowerCase().includes(tagQuery.toLowerCase()));
  const addManual = () => {
    const names = manual.split(/[,，\s]+/).map(name => name.replace(/^<\/?|\/?\s*>$/g, "")).filter(name => /^[\p{L}_][\p{L}\p{N}_.:\-]*$/u.test(name));
    if (!names.length) { setError("请输入有效的 XML 标签名，如 content, after。"); return; }
    setCustom(value => [...new Set([...value, ...names])]); setManual(""); setTagQuery(""); setError("");
  };
  const removeCustom = (name: string) => { setCustom(value => value.filter(tag => tag !== name)); setRetained(value => value.filter(tag => tag !== name)); setExcluded(value => value.filter(tag => tag !== name)); };
  const hint = mode === "all" ? "未设置 XML 规则，导出完整原文。" : `保留 ${retained.length} 个标签 · 排除 ${excluded.length} 个标签；排除规则优先。`;
  const save = () => {
    if (!result?.matched || filtering || !worker.current) return;
    const id = ++sequence.current, name = (snap.chatName || "聊天记录").replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").slice(0, 120), date = new Date(timestamp).toLocaleDateString("sv-SE");
    download.current = { id, resultId: result.id, filename: `${name}_${date}_${mode === "include" ? "提取" : mode === "exclude" ? "过滤" : "全文"}.${format}` };
    setDownloading(true); worker.current.postMessage({ type: "download", id, resultId: result.id, format, metadata });
  };
  return <section className="wb-export-workspace" aria-label="聊天记录分析与导出" data-wb-filter-mode={mode}>
    <header className="wb-export-heading"><FileOutput size={18} /><div><strong>分析与导出</strong><small>{sourceCount} 层 · {timestamp ? new Date(timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : ""} 快照</small></div><span className="wb-grow" /><button className="wb-icon" aria-label="重新分析聊天" title="重新分析当前聊天" onClick={() => setScanRevision(value => value + 1)}><RefreshCw size={17} /></button></header>
    <Notice error={error || task.error} />
    {phase === "scan" ? <div className="wb-export-progress" role="status"><progress value={progress.done} max={progress.total || 1} /><span>分析 {progress.done} / {progress.total} 层</span><button onClick={() => { worker.current?.terminate(); worker.current = null; ready.current = false; setPhase("cancelled"); }}><Square size={13} />取消</button></div> : phase === "cancelled" ? <Empty>分析已取消，点击右上角重新分析。</Empty> : phase === "error" ? <Empty>请重新分析后再导出。</Empty> : <>
      <nav className="wb-export-tabs" aria-label="导出工作区视图"><button aria-pressed={tab === "structure"} onClick={() => setTab("structure")}>XML 结构 <small>{stats.length}</small></button><button aria-pressed={tab === "preview"} onClick={() => setTab("preview")}>结果预览 <small>{filtering ? "…" : result?.matched ?? 0} 层</small></button></nav>
      <div className="wb-export-scroll">
        {tab === "structure" ? <>
          <div className="wb-export-tree-tools"><span>对标签选择保留或排除，再次点击取消。</span><button disabled={!retained.length && !excluded.length} onClick={() => { setRetained([]); setExcluded([]); }}>清空规则</button></div>
          <label className="wb-export-search"><Search size={15} /><input aria-label="搜索 XML 标签" placeholder="搜索标签或层级" value={tagQuery} onChange={e => setTagQuery(e.target.value)} /></label>
          <div className="wb-export-presets"><button onClick={() => preset("retain")}>仅 content / after</button><button onClick={() => preset("exclude")}>排除 think</button></div>
          <p className="wb-export-hint">{hint}</p>
          <div className="wb-export-tree">{visibleTags.map(stat => {
            const rule = retained.includes(stat.name) ? "retain" : excluded.includes(stat.name) ? "exclude" : "";
            return <div key={stat.path} title={`${stat.path} · ${stat.floors} 层 · ${stat.characters.toLocaleString()} 字符`} className={rule ? `is-selected is-${rule}` : ""} style={{ paddingLeft: 10 + Math.min(stat.depth, 5) * 10 }}>
              <span className={`wb-export-tag-dot ${rule ? "is-active" : ""}`} aria-hidden="true" /><code>{stat.name}</code><span className="wb-grow" /><small>{stat.count ? `${stat.count} 块` : "手动"}</small>
              <div className="wb-export-tag-actions"><button aria-label={`保留 ${stat.path}`} aria-pressed={rule === "retain"} onClick={() => choose(stat.name, "retain")}>保留</button><button aria-label={`排除 ${stat.path}`} aria-pressed={rule === "exclude"} onClick={() => choose(stat.name, "exclude")}>排除</button></div>
              {custom.includes(stat.name) && !stat.count && <button className="wb-icon" aria-label={`移除手动标签 ${stat.name}`} onClick={() => removeCustom(stat.name)}><Trash2 size={13} /></button>}
            </div>;
          })}</div>
          {!visibleTags.length && <Empty>{stats.length ? "没有匹配的 XML 标签，可显示 HTML 标签或手动添加。" : "没有检测到 XML 块，可直接全文导出。"}</Empty>}
          <form className="wb-export-manual" onSubmit={e => { e.preventDefault(); addManual(); }}><input aria-label="手动添加 XML 标签" placeholder="添加标签：content, after" value={manual} onChange={e => setManual(e.target.value)} /><button type="submit">添加</button></form><Check label="显示 HTML 标签" checked={html} onChange={setHtml} />
        </> : <><p className="wb-export-hint">{hint} <button className="wb-export-edit-rules" onClick={() => setTab("structure")}>编辑 XML 规则</button></p><label className="wb-export-search"><Search size={15} /><input aria-label="搜索导出内容" placeholder="在筛选后的内容中搜索" value={keyword} onChange={e => setKeyword(e.target.value)} /></label>{result?.preview.map(message => <article className="wb-export-message" key={message.id}><header><strong>{message.id + 1} 层 · {message.name}</strong><button onClick={() => host.jump(message.id)}>定位</button></header><pre>{message.text}</pre></article>)}{!filtering && !result?.matched && <Empty>没有匹配内容。请检查标签、消息类型和楼层范围。</Empty>}{filtering && <Empty>正在更新预览…</Empty>}{!!result?.matched && <p className="wb-export-hint">预览前 30 层，单层最多 12,000 字符；下载包含全部匹配内容。</p>}</>}
        {!!result?.warningCount && <details className="wb-export-warnings"><summary>{result.warningCount} 处 XML 结构提示</summary>{result.warnings.map((warning, index) => <button key={index} onClick={() => host.jump(warning.id)}>{warning.id + 1} 层 · {warning.message}</button>)}</details>}
        <Fold title="范围与导出选项"><div className="wb-export-options"><label>起始楼层<input aria-label="导出起始楼层" type="number" min={1} max={sourceCount || 1} value={from} onChange={e => setFrom(Math.max(1, Number(e.target.value) || 1))} /></label><label>结束楼层<input aria-label="导出结束楼层" type="number" min={1} max={sourceCount || 1} value={to} onChange={e => setTo(Math.max(1, Number(e.target.value) || 1))} /></label>{([["user", "用户消息"], ["assistant", "角色消息"], ["system", "系统消息"]] as const).map(([role, label]) => <Check key={role} label={label} checked={roles.includes(role)} onChange={selected => setRoles(value => selected ? [...value, role] : value.filter(r => r !== role))} />)}<Check label="附带说话者与楼层" checked={metadata} onChange={setMetadata} /><Check label="保留所选块的外层标签" checked={keepTags} disabled={mode !== "include"} onChange={setKeepTags} /></div></Fold>
      </div>
    </>}
    <footer className="wb-export-footer"><div className="wb-export-totals" role="status">{filtering ? "更新中…" : `${result?.matched ?? 0} 层 · ${(result?.characters ?? 0).toLocaleString()} 字符`}{snap.busy && <small>生成中 · 导出当前快照</small>}</div><div><Select aria-label="记录导出格式" value={format} onChange={e => setFormat(e.target.value as "txt" | "md")}><option value="txt">TXT</option><option value="md">Markdown</option></Select><button className="wb-primary" disabled={!result?.matched || filtering || downloading || phase !== "ready"} onClick={save}><Download size={15} />{downloading ? "准备中…" : "导出"}</button></div><small>仅处理导出副本，聊天原文保持不变。<button disabled={!snap.chatName || snap.busy || task.busy} onClick={() => task.run(() => host.exportChat(snap.chatName))}>原文 JSONL 备份</button></small></footer>
  </section>;
}
