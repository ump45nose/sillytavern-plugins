import React, { useEffect, useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import type { HostAdapter } from "../host/adapter";
import { addonEnabled, type AddonId } from "../addons/catalog";
import { addonHost, addonStyles, loadAddon } from "../addons/loader";
import { addonManager } from "../addons/runtime";
import type { AddonModule, AddonRuntime } from "../addons/types";
import { Loading, Notice, useHost } from "./common";
class AddonBoundary extends React.Component<{
    children: React.ReactNode;
    retry: () => void;
}, {
    failed: boolean;
}> {
    state = { failed: false };
    static getDerivedStateFromError() { return { failed: true }; }
    render() { return this.state.failed ? <div className="wb-addon-message"><Notice error="附加插件发生错误，请重新载入。"/><button onClick={this.props.retry}><RotateCcw size={15}/>重新载入</button></div> : this.props.children; }
}
export default function AddonWorkspace({ host, id, active, view = 'workspace' }: {
    host: HostAdapter;
    id: AddonId;
    active: boolean;
    view?: 'workspace' | 'sidebar' | 'editor';
}) {
    useHost(host);
    const enabled = addonEnabled(host.prefs(), id), api = useMemo(() => addonHost(host), [host]);
    const [module, setModule] = useState<AddonModule | null>(null), [runtime, setRuntime] = useState<AddonRuntime | null>(null), [error, setError] = useState(''), [attempt, setAttempt] = useState(0);
    useEffect(() => {
        if (!active || !enabled) {
            setModule(null);
            return;
        }
        let closed = false, styles: ReturnType<typeof addonStyles> | undefined;
        setModule(null);
        setError('');
        void (async () => { try {
            const loaded = await loadAddon(id);
            if (closed)
                return;
            styles = addonStyles(id, loaded.css);
            await styles.ready;
            if (closed)
                return;
            const runtime = loaded.module.apiVersion === 2 ? await addonManager(host).ensure(id) : null;
            if (!closed) {
                setRuntime(runtime);
                setModule(loaded.module);
            }
        }
        catch (failure) {
            styles?.dispose();
            if (!closed)
                setError(failure instanceof Error ? failure.message : String(failure));
        } })();
        return () => { closed = true; styles?.dispose(); };
    }, [id, active, enabled, attempt, host]);
    if (!active || !enabled)
        return null;
    if (error)
        return <div className="wb-addon-message" role="region" aria-label="附加插件加载失败"><Notice error={error}/><button onClick={() => setAttempt(n => n + 1)}><RotateCcw size={15}/>重新载入</button></div>;
    if (!module)
        return <Loading />;
    if (module.apiVersion === 1) {
        const Workspace = module.Workspace;
        return <AddonBoundary key={`${id}:${attempt}`} retry={() => setAttempt(n => n + 1)}><Workspace host={api}/></AddonBoundary>;
    }
    if (!runtime)
        return <Loading />;
    const View = view === 'sidebar' && module.Sidebar ? module.Sidebar : module.Workspace;
    return <AddonBoundary key={`${id}:${attempt}`} retry={() => setAttempt(n => n + 1)}><View host={addonManager(host).api(id)} runtime={runtime} editor={view === 'editor'}/></AddonBoundary>;
}
