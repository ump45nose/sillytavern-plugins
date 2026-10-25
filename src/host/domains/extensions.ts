import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { ctx, internal, loadExtensionModule } from "../internals";

/** Installed extensions: listing, toggling, update/delete hooks and install. */
export const extensionsMethods = {
  async installedExtensions(this: HostAdapter) {
    const extensions = await internal("extensions");
    return Promise.all(
      extensions.extensionNames.map(async (id: string) => {
        let manifest: Data = {};
        try {
          const response = await fetch(`/scripts/extensions/${id}/manifest.json`);
          if (response.ok) manifest = await response.json();
        } catch {}
        const key = id.split("/").at(-1)!.toLowerCase();
        const containers = [
          ...document.querySelectorAll<HTMLElement>(
            ".extension_container,#extensions_settings > div,#extensions_settings2 > div",
          ),
        ];
        const container = containers.find(
          (n) =>
            n.id &&
            (n.id.toLowerCase().includes(key) ||
              n.textContent?.toLowerCase().includes(String(manifest.display_name || key).toLowerCase())),
        );
        return {
          id,
          name: manifest.display_name || key,
          version: manifest.version,
          description: manifest.description,
          enabled: !ctx().extensionSettings.disabledExtensions.includes(id),
          container: container?.id,
        };
      }),
    );
  },
  async toggleExtension(this: HostAdapter, id: string, on: boolean) {
    const module = await internal("extensions");
    await (on ? module.enableExtension(id, false) : module.disableExtension(id, false));
  },
  async extensionAction(this: HostAdapter, id: string, action: "update" | "delete") {
    const module = await internal("extensions");
    if (!id.startsWith("third-party/")) throw new Error("内置扩展随酒馆版本更新。");
    if (action === "delete") await this.extensionHook(id, "delete");
    const response = await this.request(`/api/extensions/${action}`, {
      extensionName: id.replace(/^third-party\//, ""),
      global: module.extensionTypes[id] === "global",
    });
    if (action === "delete") await this.persistSettings();
    const data = await response.json();
    if (action === "update" && !data.isUpToDate) await this.extensionHook(id, "update");
    return data;
  },
  async extensionHook(this: HostAdapter, id: string, hook: string) {
    const response = await fetch(`/scripts/extensions/${id}/manifest.json`);
    if (!response.ok) return;
    const manifest = await response.json();
    const method = manifest.hooks?.[hook];
    if (typeof method !== "string" || !manifest.js) return;
    const module = await loadExtensionModule(`/scripts/extensions/${id}/${manifest.js}`);
    if (typeof module[method] === "function")
      await Promise.race([module[method](), new Promise((resolve) => setTimeout(resolve, 5000))]);
  },
  async installExtension(this: HostAdapter, url: string, branch: string, global: boolean) {
    const module = await internal("extensions");
    if (!(await module.installExtension(url, global, branch))) throw new Error("扩展安装未完成。");
  },
};
