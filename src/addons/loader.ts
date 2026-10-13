import type { HostAdapter } from "../host/adapter";
import type { AddonId } from "./catalog";
import type { AddonHost, AddonManifest, AddonModule } from "./types";
const loaded = new Map<AddonId, Promise<{ module: AddonModule; css: string }>>();
const failures = new Map<AddonId, number>();
// All build chunks live under dist/. Manifests remain outside build cleanup.
const extensionRoot = new URL("../", import.meta.url);
function assetURL(value: string, manifestURL: URL, version: string, suffix: string) {
  const url = new URL(value, manifestURL);
  if (url.origin !== extensionRoot.origin || !url.pathname.startsWith(extensionRoot.pathname) || !url.pathname.endsWith(suffix))
    throw new Error("附加插件资源路径无效。");
  url.search = `?v=${encodeURIComponent(version)}`;
  return url.href;
}
export function loadAddon(id: AddonId) {
  const existing = loaded.get(id);
  if (existing) return existing;
  const pending = (async () => {
    const manifestURL = new URL(`addons/${id}/manifest.json`, extensionRoot);
    const response = await fetch(manifestURL, { cache: "no-cache", signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error("附加插件文件未找到，请确认完整安装了工作台插件。");
    const manifest = await response.json() as AddonManifest;
    if (manifest.id !== id || manifest.apiVersion !== (id === "record-export" ? 1 : 2) || typeof manifest.version !== "string" || typeof manifest.entry !== "string" || typeof manifest.css !== "string")
      throw new Error("附加插件版本不兼容，请更新工作台。");
    const entryURL = new URL(assetURL(manifest.entry, manifestURL, manifest.version, ".js")), css = assetURL(manifest.css, manifestURL, manifest.version, ".css");
    // Browsers cache failed module imports too. Only retries need a fresh module URL.
    const retry = failures.get(id) || 0;
    if (retry) entryURL.searchParams.set("retry", String(retry));
    // URL import intentionally stays outside the main static dependency graph.
    const module = await import(entryURL.href) as AddonModule;
    if (module.id !== id || module.apiVersion !== manifest.apiVersion || typeof module.Workspace !== "function")
      throw new Error("附加插件入口不兼容，请更新工作台。");
    return { module, css };
  })();
  loaded.set(id, pending);
  void pending.catch(() => { if (loaded.get(id) === pending) { loaded.delete(id); failures.set(id, (failures.get(id) || 0) + 1); } });
  return pending;
}
/** A workspace owns its stylesheet, subscriptions and worker lifetime. */
export function addonStyles(id: AddonId, href: string) {
  const link = document.createElement("link");
  link.rel = "stylesheet"; link.href = href; link.dataset.wbAddonStyle = id;
  let dispose = () => {};
  const ready = new Promise<void>((resolve, reject) => {
    const finish = (error?: Error) => {
      clearTimeout(timer); link.onload = null; link.onerror = null;
      error ? reject(error) : resolve();
    };
    const timer = setTimeout(() => finish(new Error("附加插件样式加载超时，请重试。")), 15000);
    link.onload = () => finish(); link.onerror = () => finish(new Error("附加插件样式加载失败，请重试。"));
    dispose = () => { finish(new Error("附加插件工作区已关闭。")); link.remove(); };
    document.head.append(link);
  });
  return { ready, dispose: () => dispose() };
}
export function addonHost(host: HostAdapter): AddonHost {
  return Object.freeze({
    subscribe: host.subscribe, revision: host.revision,
    snapshot: () => { const snap = host.snapshot(); return { chatKey: `${snap.groupId || snap.character?.id || ""}:${snap.chatName}`, chatName: snap.chatName, busy: snap.busy }; },
    exportSnapshot: () => host.exportSnapshot(), download: (blob: Blob, filename: string) => host.download(blob, filename),
    jump: (id: number) => host.jump(id), exportChat: (name: string) => host.exportChat(name),
  });
}
