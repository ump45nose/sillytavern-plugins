import React, { useEffect, useState, useSyncExternalStore } from "react";
import { ChevronDown, Plus, Expand, Search, Copy, Trash2, CornerDownRight, ArrowDownToLine, Upload, Play, Pause, Square, PanelRightClose, Send, FileText } from "lucide-react";
import type { AddonViewProps } from "../types";
import { Check } from "../../ui/ResourceControls";
import { createRuntime } from "./runtime";
import { orderedNodes, markdownExport, parseImport, type OutlineData, type OutlineNode } from "./model";
import './style.css';
export { createRuntime };
export const apiVersion = 2, id = 'outline';
function useOutline({ runtime }: AddonViewProps) { useSyncExternalStore(runtime.subscribe, runtime.revision); return runtime.state().data as OutlineData; }
function useAction(runtime: AddonViewProps['runtime']) { const [error, setError] = useState(''); return { error, run: (name: string, ...args: any[]) => { setError(''); return runtime.action(name, ...args).catch(e => setError(e.message)); } }; }
function Tree({ data, run, search = '', inline = false }: {
    data: OutlineData;
    run: (name: string, ...args: any[]) => unknown;
    search?: string;
    inline?: boolean;
}) {
    const [open, setOpen] = useState<Record<string, boolean>>({}), [detail, setDetail] = useState<Record<string, boolean>>({});
    const matches = (n: OutlineNode): boolean => (!search || `${n.title}\n${n.content}`.toLowerCase().includes(search.toLowerCase()) || data.nodes.filter(c => c.parent === n.id).some(matches));
    const branch = (parent: string | null) => data.nodes.filter(n => n.parent === parent && matches(n)).map(node => {
        const children = data.nodes.some(n => n.parent === node.id), expanded = search ? true : open[node.id] !== false, shown = detail[node.id] ?? node.id === data.selected;
        return <div className="wb-ot-branch" key={node.id} role="treeitem" aria-selected={data.selected === node.id} aria-expanded={children ? expanded : shown}>
    <div className={`wb-ot-row ${data.selected === node.id ? 'is-selected' : ''}`} draggable onDragStart={e => e.dataTransfer.setData('application/x-wb-outline', node.id)} onDragOver={e => {
                if (e.dataTransfer.types.includes('application/x-wb-outline'))
                    e.preventDefault();
            }} onDrop={e => { e.preventDefault(); void run('move', e.dataTransfer.getData('application/x-wb-outline'), node.id, e.shiftKey); }}>
      <button className="wb-icon wb-ot-fold" aria-label={`${children ? '展开章节' : '展开节点内容'}：${node.title}`} aria-expanded={children ? expanded : shown} onClick={() => children ? setOpen({ ...open, [node.id]: !expanded }) : setDetail({ ...detail, [node.id]: !shown })}><ChevronDown size={14} className={(children ? expanded : shown) ? '' : 'is-closed'}/></button>
      <button className="wb-ot-select" data-outline-node={node.id} onClick={() => {
                run('select', node.id);
                if (inline)
                    run('open', 'workspace');
            }} onKeyDown={e => {
                const ordered = orderedNodes(data), i = ordered.findIndex(n => n.id === node.id);
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    const selected = ordered[Math.max(0, Math.min(ordered.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))].id;
                    const tree = e.currentTarget.closest('.wb-ot-tree');
                    run('select', selected);
                    requestAnimationFrame(() => tree?.querySelector<HTMLButtonElement>(`[data-outline-node="${CSS.escape(selected)}"]`)?.focus());
                }
                if (e.key === 'ArrowRight')
                    setOpen({ ...open, [node.id]: true });
                if (e.key === 'ArrowLeft')
                    setOpen({ ...open, [node.id]: false });
            }}><span className={`wb-ot-status ${node.status}`}/><span>{node.title}</span><small>{node.completed}/{node.rounds}</small></button>
    </div>
    <div className={`wb-ot-collapse ${(children ? expanded : inline && shown) ? 'is-open' : ''}`} inert={!(children ? expanded : inline && shown)}><div>{children ? <div className="wb-ot-children" role="group">{branch(node.id)}</div> : <div className="wb-ot-excerpt"><p>{node.content || '尚未填写节点内容'}</p><footer><button onClick={() => run('insert', node.id)}><Send size={12}/>插入</button><button onClick={() => { run('select', node.id); run('open', 'editor'); }}><FileText size={12}/>编辑</button></footer></div>}</div></div>
  </div>;
    });
    return <div className="wb-ot-tree" role="tree" aria-label="当前聊天大纲">{branch(null)}{!data.nodes.length && <p className="wb-addon-empty">添加第一个节点，开始组织故事。</p>}</div>;
}
export function Sidebar(props: AddonViewProps) {
    const data = useOutline(props), { run, error } = useAction(props.runtime), [search, setSearch] = useState('');
    return <div className="wb-outline-sidebar"><div className="wb-ot-tools"><label className="wb-addon-search"><Search size={13}/><input placeholder="搜索大纲" aria-label="搜索左侧大纲" value={search} onChange={e => setSearch(e.target.value)}/></label><button className="wb-icon" aria-label="完整大纲编辑" onClick={() => run('open', 'editor')}><Expand size={15}/></button></div><Tree data={data} run={(name, ...args) => {
            if (name === 'select' && !props.host.beforeClose())
                return;
            return run(name, ...args);
        }} search={search} inline/><button className="wb-ot-add" onClick={() => run('add', null)}><Plus size={14}/>添加节点<small>{data.nodes.filter(n => n.status === 'done').length}/{data.nodes.length}</small></button>{error && <p role="alert">{error}</p>}</div>;
}
function MarkdownPreview({ text }: {
    text: string;
}) {
    const inline = (line: string) => line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part.startsWith('`') ? <code key={i}>{part.slice(1, -1)}</code> : part);
    let fenced = false;
    return <div className="wb-ot-preview">{text.split('\n').map((line, i) => {
            if (/^```/.test(line)) {
                fenced = !fenced;
                return null;
            }
            if (fenced)
                return <pre key={i}>{line || ' '}</pre>;
            const heading = line.match(/^(#{1,6})\s+(.+)/);
            if (heading)
                return <h4 key={i}>{inline(heading[2])}</h4>;
            if (/^>\s*/.test(line))
                return <blockquote key={i}>{inline(line.replace(/^>\s*/, ''))}</blockquote>;
            if (/^[-*]\s/.test(line))
                return <p className="wb-ot-list-line" key={i}>• {inline(line.slice(2))}</p>;
            return <p key={i}>{inline(line) || '\u00a0'}</p>;
        })}</div>;
}
export function Workspace(props: AddonViewProps) {
    const data = useOutline(props), { run, error } = useAction(props.runtime), node = data.nodes.find(n => n.id === data.selected), [search, setSearch] = useState(''), [preview, setPreview] = useState(true), [pending, setPending] = useState<OutlineData | null>(null), [draft, setDraft] = useState({ title: '', content: '' });
    const task = props.runtime.task();
    useEffect(() => { setDraft({ title: node?.title || '', content: node?.content || '' }); }, [node?.id, node?.title, node?.content]);
    const dirty = !!node && (node.title !== draft.title || node.content !== draft.content);
    useEffect(() => {
        if (!dirty)
            return;
        const guard = (event: Event) => { event.preventDefault(); window.dispatchEvent(new CustomEvent('wb-error', { detail: '大纲节点有未保存内容，请先保存或撤销草稿。' })); };
        const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
        window.addEventListener('wb-before-close', guard);
        window.addEventListener('beforeunload', unload);
        return () => { window.removeEventListener('wb-before-close', guard); window.removeEventListener('beforeunload', unload); };
    }, [dirty]);
    const exportFile = (format: string) => props.host.download(new Blob([format === 'json' ? JSON.stringify(data, null, 2) : markdownExport(data)], { type: 'text/plain;charset=utf-8' }), `大纲.${format === 'json' ? 'json' : 'md'}`);
    return <section className={`wb-outline-workspace wb-addon-view ${props.editor ? 'is-editor' : ''}`} aria-label={props.editor ? '完整大纲编辑' : '大纲节点工作区'}>
    <header className="wb-addon-heading"><strong>大纲 <small>{data.nodes.length} 个节点</small></strong><div><button onClick={() => exportFile('json')} title="导出 JSON"><ArrowDownToLine size={14}/>JSON</button><button onClick={() => exportFile('md')} title="导出 Markdown">MD</button><label className="wb-addon-file"><Upload size={14}/>导入<input type="file" accept=".json,.md,.txt" onChange={async (e) => {
            try {
                const file = e.target.files?.[0];
                if (file)
                    setPending(parseImport(await file.text()));
            }
            catch (error) {
                props.host.open('workspace');
                void run('invalid');
                alert((error as Error).message);
            }
            e.target.value = '';
        }}/></label>{!props.editor && <button aria-label="完整大纲编辑" onClick={() => run('open', 'editor')}><Expand size={15}/></button>}</div></header>
    {pending && <div className="wb-ot-import"><strong>导入预览 · {pending.nodes.length} 个节点</strong><p>{pending.nodes.slice(0, 5).map(n => n.title).join(' / ')}</p><button onClick={() => { run('import', pending, 'merge'); setPending(null); }}>合并</button><button onClick={() => { run('import', pending, 'replace'); setPending(null); }}>替换</button><button onClick={() => setPending(null)}>取消</button></div>}
    <div className="wb-ot-editor-layout">{props.editor && <aside><label className="wb-addon-search"><Search size={14}/><input aria-label="搜索大纲" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索标题或正文"/></label><Tree data={data} run={(name, ...args) => {
                if (name === 'select' && dirty)
                    return;
                return run(name, ...args);
            }} search={search}/><button onClick={() => run('add', null)}><Plus size={14}/>新节点</button><p className="wb-addon-hint">拖动调整顺序 · Shift 拖入调整层级</p></aside>}
    <main>{node ? <><div className="wb-ot-node-heading"><input aria-label="节点标题" value={draft.title} onChange={e => { run('pause'); setDraft({ ...draft, title: e.target.value }); }}/><button aria-label="新建同级节点" disabled={dirty} onClick={() => run('add', node.parent)}><Plus size={14}/></button><button aria-label="新建子节点" disabled={dirty} onClick={() => run('add', node.id)}><CornerDownRight size={14}/></button><button aria-label="复制节点" disabled={dirty} onClick={() => run('duplicate', node.id)}><Copy size={14}/></button><button aria-label="删除节点" disabled={dirty} onClick={() => run('delete', node.id)}><Trash2 size={14}/></button></div>
    <div className="wb-ot-node-controls"><select aria-label="节点状态" value={node.status} onChange={e => run('patch', node.id, { status: e.target.value, completed: e.target.value === 'todo' ? 0 : node.completed })}><option value="todo">待写</option><option value="active">进行中</option><option value="done">完成</option></select><label>轮数<input aria-label="节点写作轮数" type="number" min="1" max="100" value={node.rounds} onChange={e => run('patch', node.id, { rounds: Number(e.target.value) })}/></label><span>{node.completed} 轮已完成</span><button aria-label="收纳 Markdown 预览" aria-pressed={!preview} onClick={() => setPreview(!preview)}><PanelRightClose size={14}/></button></div>
    <div className={`wb-ot-markdown ${preview ? 'with-preview' : ''}`}><textarea aria-label="Markdown 节点内容" value={draft.content} onChange={e => { run('pause'); setDraft({ ...draft, content: e.target.value }); }} placeholder="使用 Markdown 写下这一步发生的事…"/>{preview && <MarkdownPreview text={draft.content}/>}</div>
    <div className="wb-addon-actions"><button className="wb-primary" disabled={!dirty} onClick={() => run('patch', node.id, draft)}>保存节点</button><button disabled={dirty} onClick={() => run('insert', node.id)}><Send size={14}/>插入指令</button><button disabled={!dirty} onClick={() => setDraft({ title: node.title, content: node.content })}>撤销草稿</button></div></> : <button onClick={() => run('add', null)}><Plus size={16}/>添加第一个大纲节点</button>}
    <div className="wb-ot-insert-settings"><label>插入方式<select value={data.settings.mode} onChange={e => run('settings', { mode: e.target.value })}><option value="caret">插入光标处</option><option value="replace">覆盖输入框</option></select></label><Check checked={data.settings.send} label="插入后发送" onChange={send => run('settings', { send })}/></div>
    <section className="wb-ot-auto"><header><strong>自动写作</strong><span>{task.label || '默认关闭 · 按叶节点顺序写作'}</span></header><div className="wb-addon-actions"><button disabled={dirty || !node || task.status === 'running' || task.status === 'pausing'} onClick={() => run('run', data.selected, false)}><Play size={14}/>从此处开始</button><button disabled={dirty || !node || task.status === 'running' || task.status === 'pausing'} onClick={() => run('run', data.selected, true)}>执行子树</button>{task.status === 'running' ? <button onClick={() => run('pause')}><Pause size={14}/>暂停</button> : data.job && <button onClick={() => run('resume')}><Play size={14}/>继续</button>}<button disabled={task.status === 'idle'} onClick={() => run('stop')}><Square size={14}/>停止</button></div><p className="wb-addon-hint">父节点作为背景；空节点与已完成节点跳过。手动输入或编辑大纲后暂停。</p></section>
    {(error || task.error) && <p className="wb-addon-error" role="alert">{error || task.error}</p>}</main></div>
  </section>;
}
