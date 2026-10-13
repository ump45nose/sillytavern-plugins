import { randomId } from "../../host/ids";
import type { AddonRuntime, TaskHost, TaskState } from "../types";
import { descendants, emptyOutline, instruction, mergeOutline, moveNode, normalizeOutline, writingQueue, type OutlineData } from "./model";
export function createRuntime(host: TaskHost): AddonRuntime {
    let data = normalizeOutline(host.metadata()), version = 0, task: TaskState = { status: data.job ? 'paused' : 'idle', label: data.job ? '写作进度已恢复 · 等待继续' : '' }, controller: AbortController | undefined, disposed = false, pauseRequested = false, loopActive = false;
    const key = host.snapshot().chatKey, listeners = new Set<() => void>();
    const emit = () => { version++; listeners.forEach(fn => fn()); };
    let mutations: Promise<unknown> = Promise.resolve();
    const save = (change: (current: OutlineData) => OutlineData) => {
        const pending = mutations.then(async () => { if (disposed)
            throw new Error('任务已结束。'); const next = normalizeOutline(change(data)); await host.saveMetadata(next, key); if (disposed)
            return; data = next; emit(); });
        mutations = pending.catch(() => { });
        return pending;
    };
    const pause = () => {
        if (task.status === 'running') {
            pauseRequested = true;
            task = { status: 'pausing', label: '本轮结束后暂停' };
            emit();
        }
    };
    const off = host.onInput(pause);
    async function loop() {
        loopActive = true;
        pauseRequested = false;
        const activeController = new AbortController();
        controller = activeController;
        task = { status: 'running', label: '准备写作' };
        emit();
        try {
            while (!disposed && task.status === 'running' && data.job && data.job.index < data.job.queue.length) {
                const id = data.job.queue[data.job.index], node = data.nodes.find(n => n.id === id);
                if (!node || node.status === 'done') {
                    await save(current => ({ ...current, job: current.job ? { ...current.job, index: current.job.index + 1 } : undefined }));
                    continue;
                }
                await save(current => ({ ...current, nodes: current.nodes.map(n => n.id === id ? { ...n, status: 'active' } : n) }));
                if (disposed || activeController.signal.aborted || pauseRequested)
                    break;
                task = { status: 'running', label: `${node.title} · ${node.completed}/${node.rounds} 轮` };
                emit();
                await host.write(node.completed ? null : instruction(data, id), activeController.signal);
                if (disposed || activeController.signal.aborted)
                    return;
                await save(current => {
                    const latest = current.nodes.find(n => n.id === id);
                    if (!latest)
                        throw new Error('执行节点已删除。');
                    const completed = latest.completed + 1, done = completed >= latest.rounds;
                    return { ...current, nodes: current.nodes.map(n => n.id === id ? { ...n, completed, status: done ? 'done' : 'active' } : n), job: current.job ? { ...current.job, index: current.job.index + (done ? 1 : 0) } : undefined };
                });
                if (pauseRequested)
                    break;
            }
            if (disposed || activeController.signal.aborted)
                return;
            if (data.job && data.job.index >= data.job.queue.length) {
                await save(current => ({ ...current, job: undefined }));
                task = { status: 'idle', label: '全部节点已完成' };
            }
            else
                task = { status: 'paused', label: '写作已暂停 · 进度保留' };
            emit();
        }
        catch (error) {
            if (!disposed && !activeController.signal.aborted) {
                task = { status: 'paused', label: '写作已暂停', error: error instanceof Error ? error.message : String(error) };
                emit();
            }
        }
        finally {
            loopActive = false;
        }
    }
    const stop = () => { controller?.abort(); task = { status: data.job ? 'paused' : 'idle', label: '任务已停止 · 可继续剩余节点' }; emit(); };
    async function action(name: string, ...args: any[]) {
        if (disposed)
            throw new Error('工作区已关闭。');
        if (name === 'pause') {
            pause();
            return;
        }
        if (name === 'stop') {
            stop();
            return;
        }
        if (name === 'run' || name === 'resume') {
            if (loopActive || task.status === 'running' || task.status === 'pausing')
                return;
            if (host.snapshot().busy)
                throw new Error('请等待当前生成完成。');
            if (name === 'run') {
                const queue = writingQueue(data, args[0] || data.selected, !!args[1]);
                if (!queue.length)
                    throw new Error('没有可执行的未完成叶节点。');
                await save(current => ({ ...current, job: { queue, index: 0 } }));
            }
            if (!data.job)
                throw new Error('没有可恢复的写作任务。');
            void loop();
            return;
        }
        if (name === 'select') {
            data = { ...data, selected: args[0] };
            emit();
            return;
        }
        if (name === 'open') {
            host.open(args[0] || 'workspace');
            return;
        }
        if (name === 'insert') {
            pause();
            const id = args[0] || data.selected;
            if (!id)
                return;
            const text = instruction(data, id);
            host.insert(text, data.settings.mode);
            if (data.settings.send)
                await host.write(host.input(), new AbortController().signal, true);
            return;
        }
        pause(); // An edit during a running round prevents dispatch of another round.
        await save(current => {
            let next = structuredClone(current);
            if (name === 'add') {
                const id = randomId();
                next.nodes.push({ id, parent: args[0] || null, title: '新节点', content: '', status: 'todo', rounds: 1, completed: 0 });
                next.selected = id;
            }
            else if (name === 'patch') {
                next.nodes = next.nodes.map(n => n.id === args[0] ? { ...n, ...args[1] } : n);
            }
            else if (name === 'settings')
                next.settings = { ...next.settings, ...args[0] };
            else if (name === 'delete') {
                const ids = new Set([args[0], ...descendants(next, args[0]).map(n => n.id)]);
                next.nodes = next.nodes.filter(n => !ids.has(n.id));
                next.selected = next.nodes[0]?.id || '';
            }
            else if (name === 'duplicate') {
                const nodes = [next.nodes.find(n => n.id === args[0])!, ...descendants(next, args[0])];
                const map = new Map(nodes.map(n => [n.id, randomId()]));
                next.nodes.push(...nodes.map(n => ({ ...n, id: map.get(n.id)!, parent: map.get(n.parent!) || n.parent, title: n.id === args[0] ? n.title + ' · 副本' : n.title, status: 'todo' as const, completed: 0 })));
                next.selected = map.get(args[0])!;
            }
            else if (name === 'move')
                next = moveNode(next, args[0], args[1], !!args[2]);
            else if (name === 'import')
                next = args[1] === 'merge' ? mergeOutline(next, args[0]) : normalizeOutline(args[0]);
            else if (name === 'reset')
                next = emptyOutline();
            else
                return current;
            return normalizeOutline(next);
        });
    }
    return { subscribe: fn => { listeners.add(fn); return () => { listeners.delete(fn); }; }, revision: () => version, state: () => ({ data }), task: () => task, action, stop, dispose: () => { disposed = true; controller?.abort(); off(); listeners.clear(); } };
}
