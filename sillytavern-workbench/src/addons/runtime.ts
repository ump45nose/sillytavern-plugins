import type { HostAdapter } from "../host/adapter";
import { AddonBridge } from "../host/addon-api";
import { addonEnabled, type AddonId } from "./catalog";
import { loadAddon } from "./loader";
import type { AddonRuntime, TaskHost } from "./types";
const managers = new WeakMap<HostAdapter, AddonManager>();
export class AddonManager {
    readonly bridge: AddonBridge;
    private runtimes = new Map<AddonId, AddonRuntime>();
    private pending = new Map<AddonId, Promise<AddonRuntime>>();
    private listeners = new Set<() => void>();
    private cleanups: (() => void)[] = [];
    private key: string;
    private version = 0;
    private disposed = false;
    constructor(private host: HostAdapter) {
        this.bridge = new AddonBridge(host);
        this.key = this.bridge.key();
        this.cleanups.push(this.bridge.onChatChange(() => { this.key = this.bridge.key(); this.reset(); }));
        this.cleanups.push(host.subscribe(() => {
            const key = this.bridge.key();
            if (key !== this.key) {
                this.key = key;
                this.reset();
            }
            for (const [id, runtime] of this.runtimes)
                if (!addonEnabled(host.prefs(), id)) {
                    runtime.dispose();
                    this.runtimes.delete(id);
                    this.emit();
                }
        }));
        this.cleanups.push(this.bridge.onReply(reply => {
            const api = this.api('image-gen'), rule = api.metadata().auto;
            if (!addonEnabled(host.prefs(), 'image-gen') || !rule?.enabled)
                return;
            void this.ensure('image-gen').then(runtime => runtime.action('reply', reply)).catch(error => host.report(error));
        }));
    }
    subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
    revision = () => this.version;
    private emit = () => { this.version++; this.listeners.forEach(fn => fn()); };
    api(id: AddonId): TaskHost { return this.bridge.api(id, view => window.dispatchEvent(new CustomEvent('wb-addon-open', { detail: { id, view } }))); }
    get(id: AddonId) { return this.runtimes.get(id); }
    async ensure(id: AddonId): Promise<AddonRuntime> {
        if (this.disposed || !addonEnabled(this.host.prefs(), id))
            throw new Error('附加功能已停用。');
        const runtime = this.get(id);
        if (runtime)
            return runtime;
        const existing = this.pending.get(id);
        if (existing)
            return existing;
        const key = this.key;
        const pending = loadAddon(id).then(({ module }) => {
            if (this.disposed || this.key !== key || !addonEnabled(this.host.prefs(), id))
                throw new Error('聊天已切换或功能已停用。');
            if (module.apiVersion !== 2)
                throw new Error('此插件没有后台任务。');
            const runtime = module.createRuntime(this.api(id));
            this.runtimes.set(id, runtime);
            this.cleanups.push(runtime.subscribe(this.emit));
            this.emit();
            return runtime;
        }).finally(() => {
            if (this.pending.get(id) === pending)
                this.pending.delete(id);
        });
        this.pending.set(id, pending);
        return pending;
    }
    tasks() { return [...this.runtimes].map(([id, runtime]) => ({ id, runtime, ...runtime.task() })).filter(task => task.status !== 'idle'); }
    private reset() { this.runtimes.forEach(runtime => runtime.dispose()); this.runtimes.clear(); this.pending.clear(); this.emit(); }
    dispose() { this.disposed = true; this.reset(); this.cleanups.forEach(fn => fn()); this.bridge.dispose(); this.listeners.clear(); managers.delete(this.host); }
}
export function addonManager(host: HostAdapter) {
    let manager = managers.get(host);
    if (!manager) {
        manager = new AddonManager(host);
        managers.set(host, manager);
    }
    return manager;
}
export function disposeAddons(host: HostAdapter) { managers.get(host)?.dispose(); }
