import { randomId } from "../../host/ids";
export type Status = "todo" | "active" | "done";
export interface OutlineNode {
    id: string;
    parent: string | null;
    title: string;
    content: string;
    status: Status;
    rounds: number;
    completed: number;
}
export interface OutlineData {
    version: 1;
    nodes: OutlineNode[];
    selected: string;
    settings: {
        mode: "replace" | "caret";
        send: boolean;
    };
    job?: {
        queue: string[];
        index: number;
    };
}
export const emptyOutline = (): OutlineData => ({ version: 1, nodes: [], selected: '', settings: { mode: 'caret', send: false } });
export function normalizeOutline(value: any): OutlineData {
    if (!value || !Array.isArray(value.nodes))
        return emptyOutline();
    if (value.nodes.length > 2000)
        throw new Error('大纲最多支持 2000 个节点。');
    const ids = new Set<string>();
    const nodes: OutlineNode[] = value.nodes.map((node: any) => {
        const id = String(node.id || '');
        if (!id || ids.has(id))
            throw new Error('节点标识为空或重复。');
        ids.add(id);
        return { id, parent: node.parent == null ? null : String(node.parent), title: String(node.title || '未命名节点').slice(0, 300), content: String(node.content || '').slice(0, 100000), status: ['todo', 'active', 'done'].includes(node.status) ? node.status : 'todo', rounds: Math.max(1, Math.min(100, Math.floor(Number(node.rounds) || 1))), completed: Math.max(0, Math.min(100, Math.floor(Number(node.completed) || 0))) };
    });
    for (const node of nodes) {
        let next = node.parent, depth = 0;
        const seen = new Set([node.id]);
        while (next) {
            if (!ids.has(next) || seen.has(next) || ++depth > 32)
                throw new Error('大纲层级无效或包含循环。');
            seen.add(next);
            next = nodes.find(n => n.id === next)!.parent;
        }
    }
    return { version: 1, nodes, selected: ids.has(value.selected) ? value.selected : nodes[0]?.id || '', settings: { mode: value.settings?.mode === 'replace' ? 'replace' : 'caret', send: value.settings?.send === true }, job: value.job && Array.isArray(value.job.queue) ? { queue: value.job.queue.filter((id: string) => ids.has(id)), index: Math.max(0, Number(value.job.index) || 0) } : undefined };
}
export function orderedNodes(data: OutlineData, parent: string | null = null): OutlineNode[] { return data.nodes.filter(n => n.parent === parent).flatMap(node => [node, ...orderedNodes(data, node.id)]); }
export function descendants(data: OutlineData, id: string): OutlineNode[] { return orderedNodes(data, id); }
export function writingQueue(data: OutlineData, selected: string, subtree = false) { const ordered = orderedNodes(data); const eligible = (node: OutlineNode) => !data.nodes.some(n => n.parent === node.id) && node.content.trim() && node.status !== 'done'; const start = ordered.findIndex(n => n.id === selected); return (subtree ? ordered.filter(n => n.id === selected || descendants(data, selected).some(d => d.id === n.id)) : ordered.slice(Math.max(0, start))).filter(eligible).map(n => n.id); }
export function instruction(data: OutlineData, id: string) {
    const node = data.nodes.find(n => n.id === id)!;
    const parents: OutlineNode[] = [];
    let parent = node.parent;
    while (parent) {
        const n = data.nodes.find(n => n.id === parent)!;
        parents.unshift(n);
        parent = n.parent;
    }
    return [...parents.filter(n => n.content.trim()).map(n => `背景 · ${n.title}\n${n.content}`), `写作节点 · ${node.title}\n${node.content}`].join('\n\n');
}
export function moveNode(data: OutlineData, id: string, target: string, inside: boolean): OutlineData {
    const node = data.nodes.find(n => n.id === id), destination = data.nodes.find(n => n.id === target);
    if (!node || !destination || id === target || descendants(data, id).some(n => n.id === target))
        throw new Error('无法移入自己的子节点。');
    const block = [node, ...descendants(data, id)], ids = new Set(block.map(n => n.id));
    const nodes = data.nodes.filter(n => !ids.has(n.id));
    node.parent = inside ? target : destination.parent;
    const index = nodes.findIndex(n => n.id === target);
    nodes.splice(index + (inside ? 1 : 0), 0, ...block);
    return normalizeOutline({ ...data, nodes });
}
export function markdownExport(data: OutlineData) { const depth = (n: OutlineNode): number => n.parent ? depth(data.nodes.find(p => p.id === n.parent)!) + 1 : 1; return orderedNodes(data).map(n => `${'#'.repeat(depth(n))} ${n.title}\n\n${n.content}`).join('\n\n') + '\n'; }
export function markdownImport(text: string): OutlineData {
    const data = emptyOutline(), stack: OutlineNode[] = [];
    let current: OutlineNode | undefined;
    let fenced = false;
    for (const line of text.split(/\r?\n/)) {
        if (/^\s*```/.test(line))
            fenced = !fenced;
        const match = !fenced ? line.match(/^(#{1,32})\s+(.+)$/) : null;
        if (match) {
            while (stack.length && stack.length >= match[1].length)
                stack.pop();
            current = { id: randomId(), parent: stack.at(-1)?.id || null, title: match[2], content: '', status: 'todo', rounds: 1, completed: 0 };
            data.nodes.push(current);
            stack.push(current);
        }
        else if (current)
            current.content += (current.content ? '\n' : '') + line;
    }
    data.nodes.forEach(n => n.content = n.content.trim());
    if (!data.nodes.length)
        throw new Error('Markdown 中需要至少一个标题。');
    data.selected = data.nodes[0].id;
    return normalizeOutline(data);
}
export function parseImport(text: string) {
    if (text.length > 4000000)
        throw new Error('导入文件过大。');
    return text.trim().startsWith('{') ? normalizeOutline(JSON.parse(text)) : markdownImport(text);
}
export function mergeOutline(current: OutlineData, incoming: OutlineData) { const map = new Map(incoming.nodes.map(n => [n.id, randomId()])); return normalizeOutline({ ...current, nodes: [...current.nodes, ...incoming.nodes.map(n => ({ ...n, id: map.get(n.id), parent: n.parent ? map.get(n.parent) : null }))] }); }
