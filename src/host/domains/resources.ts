import type { HostAdapter } from "../adapter";
import type { Data, Resource } from "../types";
import { clone, validateBook } from "../model";
import { ctx } from "../internals";

/** Cross-resource actions: switching, batch copy/delete/export and creation. */
export const resourcesMethods = {
  async select(this: HostAdapter, kind: Resource, id: string) {
    if (this.isBusy()) throw new Error("请等待当前生成或切换完成。");
    this.busy = true;
    this.invalidate("session");
    try {
      if (kind === "connection") {
        const select = document.querySelector<HTMLSelectElement>("#connection_profiles");
        if (!select || ![...select.options].some((x) => x.value === id))
          throw new Error("连接不存在，请刷新列表。");
        await new Promise<void>((resolve, reject) => {
          const c = ctx(),
            event = c.eventTypes.CONNECTION_PROFILE_LOADED;
          const done = () => {
            clearTimeout(timer);
            c.eventSource.removeListener(event, done);
            resolve();
          };
          const timer = setTimeout(() => {
            c.eventSource.removeListener(event, done);
            reject(new Error("连接切换超时，请检查原生连接状态。"));
          }, 15000);
          c.eventSource.on(event, done);
          select.value = id;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        });
      } else if (kind === "preset") {
        const m = ctx().getPresetManager();
        const value = m?.findPreset(id);
        if (value === undefined || value === null) throw new Error("当前 API 没有此预设。");
        await m.selectPreset(value);
      } else if (kind === "persona") {
        await this.personas.setUserAvatar(id);
      }
      // Worldbooks are multi-select: navigation never disables another book.
    } finally {
      // Selection lives in session; the switch's own events rebuild anything else it touched.
      this.busy = false;
      this.invalidate("session");
    }
    if (kind === "connection") await this.applyBinding();
  },
  async batchResource(
    this: HostAdapter,
    kind: "preset" | "connection" | "world",
    ids: string[],
    action: "copy" | "delete" | "export",
  ) {
    if (this.isBusy()) throw new Error("请等待生成或切换完成。");
    const connection = this.connectionControls();
    const done: string[] = [],
      created: string[] = [],
      errors: { id: string; message: string }[] = [],
      originalPreset = ctx().getPresetManager().getSelectedPresetName(),
      exports: { name: string; data: Data }[] = [];
    this.resourceAction = true;
    this.invalidate("session");
    try {
      for (const id of [...new Set(ids)])
        try {
          const item = this.snapshot().resources[kind].find((r) => r.id === id);
          if (!item) throw new Error("资源已不存在。");
          const cache = this.drafts.get(kind + ":" + id);
          if (cache?.extra?.advanced && action !== "delete")
            throw new Error("预设 JSON 草稿无法解析，请先修正。");
          const data =
            cache && action !== "delete"
              ? cache.extra?.tab === "json"
                ? JSON.parse(cache.extra.json)
                : clone(cache.draft)
              : kind === "preset"
                ? this.presetData(id)
                : kind === "world"
                  ? await this.readBook(id)
                  : clone(item.data!);
          if (action === "export") {
            exports.push({ name: item.name, data });
          } else if (kind === "world") {
            if (action === "delete") {
              if (!(await this.world.deleteWorldInfo(id))) throw new Error("世界书删除失败。");
            } else {
              const name = this.copyName(kind, item.name);
              await this.createResource("world", name, data);
              created.push(name);
            }
            this.resourceVersions.world++;
          } else if (kind === "preset") {
            if (action === "delete") await this.removePreset(id);
            else {
              const name = this.copyName(kind, item.name);
              await ctx().getPresetManager().savePreset(name, data);
              created.push(name);
            }
            this.resourceVersions.preset++;
          } else {
            const c = ctx(),
              cm = c.extensionSettings.connectionManager,
              previous = clone(cm),
              select = document.getElementById("connection_profiles") as HTMLSelectElement;
            let copy: Data | undefined;
            if (action === "delete") {
              cm.profiles = cm.profiles.filter((p: Data) => p.id !== id);
              if (cm.selectedProfile === id) cm.selectedProfile = null;
            } else {
              copy = { ...data, id: ctx().uuidv4(), name: this.copyName(kind, item.name) };
              cm.profiles.push(copy);
            }
            try {
              await this.persistSettings();
            } catch (e) {
              Object.assign(cm, previous);
              throw e;
            }
            if (action === "delete") {
              [...select.options].find((o) => o.value === id)?.remove();
              if (previous.selectedProfile === id) {
                select.value = "";
                select.dispatchEvent(new Event("change", { bubbles: true }));
              }
            } else {
              select.add(new Option(copy!.name, copy!.id));
              created.push(copy!.id);
            }
            await c.eventSource.emit(
              c.eventTypes[action === "delete" ? "CONNECTION_PROFILE_DELETED" : "CONNECTION_PROFILE_CREATED"],
              action === "delete" ? data : copy,
            );
            this.resourceVersions.connection++;
          }
          if (action === "delete") this.drafts.delete(kind + ":" + id);
          done.push(id);
        } catch (e) {
          errors.push({ id, message: e instanceof Error ? e.message : String(e) });
        }
      if (kind === "preset" && action === "copy") {
        const manager = ctx().getPresetManager();
        if (manager.getAllPresets().includes(originalPreset))
          await manager.selectPreset(manager.findPreset(originalPreset));
        this.restoreConnectionControls(connection);
      }
      if (exports.length === 1)
        this.download(
          new Blob([JSON.stringify(exports[0].data, null, 2)], { type: "application/json" }),
          exports[0].name + ".json",
        );
      else if (exports.length > 1) {
        const { zipSync, strToU8 } = await import("fflate"),
          files: Record<string, Uint8Array> = {};
        exports.forEach((item, i) => {
          files[`${i + 1}-${item.name.replace(/[\\/:]/g, "_")}.json`] = strToU8(
            JSON.stringify(item.data, null, 2),
          );
        });
        this.download(
          new Blob([new Uint8Array(zipSync(files, { level: 0 }))], { type: "application/zip" }),
          `Workbench-${kind}.zip`,
        );
      }
      return { done, created, errors };
    } finally {
      // One rebuild for the whole batch.
      this.resourceAction = false;
      this.invalidate("resources", "session");
    }
  },
  async createResource(
    this: HostAdapter,
    kind: "preset" | "connection" | "world",
    name: string,
    data?: Data,
  ) {
    name = name.trim();
    if (!name || this.snapshot().resources[kind].some((r) => r.name === name))
      throw new Error("名称不能为空或重复。");
    if (kind === "world") {
      const book = data ?? { entries: {} };
      validateBook(book);
      await this.request("/api/worldinfo/edit", { name, data: book });
      this.world.worldInfoCache.set(name, clone(book));
      await this.world.updateWorldInfoList();
      await ctx().eventSource.emit(ctx().eventTypes.WORLDINFO_UPDATED, name, clone(book));
      this.resourceVersions.world++;
      return name;
    }
    if (kind === "preset") return this.createPreset(name, data);
    throw new Error("连接请使用原生新建配置控件。");
  },
  copyName(this: HostAdapter, kind: Resource, name: string) {
    const names = new Set(this.snapshot().resources[kind].map((r) => r.name));
    let next = name + " · 副本",
      i = 2;
    while (names.has(next)) next = name + " · 副本 " + i++;
    return next;
  },
};
