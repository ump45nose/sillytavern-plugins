import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { clone, mergeEdits, sameData, validatePreset } from "../model";
import { ctx } from "../internals";
import { emptyPreset } from "../empty-preset";
import { withPresetGroup } from "../organize";

/** Presets, preset bindings to connections/models, and prompt token composition. */
export const presetMethods = {
  model(this: HostAdapter) {
    const c = ctx();
    return c.mainApi === "openai"
      ? c.getChatCompletionModel()
      : (c.textCompletionSettings?.model ?? c.mainApi);
  },
  bindingKey(this: HostAdapter, kind: "connection" | "model") {
    return kind === "connection"
      ? `connection:${this.snapshot().current.connection}`
      : `model:${ctx().mainApi}:${this.model()}`;
  },
  async applyBinding(this: HostAdapter) {
    if (this.bindingRun) return;
    const p = this.prefs(),
      name = p.bindings[this.bindingKey("connection")] || p.bindings[this.bindingKey("model")];
    if (!name || ctx().getPresetManager().getSelectedPresetName() === name) return;
    const connection = this.connectionControls();
    this.bindingRun = true;
    try {
      await this.select("preset", name);
      // Bindings choose generation settings while keeping the chosen API/model.
      this.restoreConnectionControls(connection);
    } finally {
      this.bindingRun = false;
    }
  },
  presetData(this: HostAdapter, name: string) {
    const m = ctx().getPresetManager();
    const { presets, preset_names } = m.getPresetList();
    const i = Array.isArray(preset_names) ? preset_names.indexOf(name) : preset_names[name];
    if (i === undefined || i < 0) throw new Error("预设不存在");
    return clone(presets[i]);
  },
  async createPreset(this: HostAdapter, name: string, data?: Data) {
    const manager = ctx().getPresetManager();
    name = name.trim();
    if (!name || manager.getAllPresets().includes(name)) throw new Error("预设名称不能为空或重复");
    if (/[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name))
      throw new Error("预设名称不能包含文件路径或特殊文件名字符。");
    if (data) validatePreset(data);
    await manager.savePreset(name, data);
    this.invalidate("resources", "session");
    return manager.getSelectedPresetName();
  },
  async deletePreset(this: HostAdapter, name: string) {
    try {
      await this.removePreset(name);
    } finally {
      this.resourceVersions.preset++;
      this.invalidate("resources", "session");
    }
  },
  /** deletePreset without invalidating, for callers that delete several and invalidate once. */
  async removePreset(this: HostAdapter, name: string) {
    const c = ctx(),
      manager = c.getPresetManager(),
      { presets, preset_names } = manager.getPresetList();
    const value = manager.findPreset(name);
    if (value === undefined || value === null) throw new Error("预设已不存在，请刷新列表。");
    if (value === "gui") throw new Error("GUI 是酒馆内置的运行设置，请新建空白预设后使用。");
    const wasActive = manager.getSelectedPresetName() === name;
    const last = c.mainApi === "openai" && manager.getAllPresets().length === 1;
    const previous = last ? this.livePreset(name) : null;
    // Create the replacement first, so failure cannot leave the last chat preset unselected.
    if (last) {
      await manager.savePreset(name === "Default" ? "空白预设" : "Default", emptyPreset());
    }
    try {
      const response = await fetch("/api/presets/delete", {
        method: "POST",
        headers: c.getRequestHeaders(),
        body: JSON.stringify({ name, apiId: manager.apiId }),
      });
      // A stale Default can still be in the browser after its file has already been removed.
      if (!response.ok && response.status !== 404)
        throw new Error(`删除失败（HTTP ${response.status}），已保留原预设。`);
    } catch (error) {
      if (last && wasActive) {
        await manager.selectPreset(value);
        if (previous) this.applyPreset(previous);
      }
      throw error;
    }
    window
      .jQuery(manager.select)
      .find("option")
      .filter((_: number, option: HTMLOptionElement) => option.text === name)
      .remove();
    if (Array.isArray(preset_names)) {
      const index = preset_names.indexOf(name);
      if (index >= 0) {
        preset_names.splice(index, 1);
        presets.splice(index, 1);
      }
    } else delete preset_names[name];
    const next = manager.getAllPresets()[0];
    if (wasActive && next) await manager.selectPreset(manager.findPreset(next));
    this.drafts.delete("preset:" + name);
    const bindings = { ...this.prefs().bindings };
    for (const key of Object.keys(bindings)) if (bindings[key] === name) delete bindings[key];
    const groupPatch = this.prefs().presetGroups?.[manager.apiId]?.[name]
      ? withPresetGroup(this.prefs(), manager.apiId, [name], "")
      : {};
    this.preference({ bindings, ...groupPatch });
    if (c.eventTypes.PRESET_DELETED)
      await c.eventSource.emit(c.eventTypes.PRESET_DELETED, { apiId: manager.apiId, name });
    c.saveSettingsDebounced();
  },
  /**
   * The running chat-completion settings in the shape of preset `name`, or null when `name` is not
   * the running preset (the editor then works on the file alone). Parameters, toggles and order
   * apply to these settings at once, as in SillyTavern; "更新预设" writes them into the file.
   */
  livePreset(this: HostAdapter, name: string): Data | null {
    return this.runningPreset(name)?.live ?? null;
  },
  /**
   * livePreset beside the preset file it was read from, from one read of the file. Unmapped keys share
   * the file's values, so neither object may be mutated.
   */
  runningPreset(this: HostAdapter, name: string): { live: Data; file: Data } | null {
    const o = this.openai,
      map: Record<string, [string, string, boolean, boolean]> | undefined = o?.settingsToUpdate;
    if (ctx().mainApi !== "openai" || !map || !o.oai_settings || !o.getChatCompletionPreset) return null;
    if (ctx().getPresetManager().getSelectedPresetName() !== name) return null;
    const file = this.presetData(name),
      live: Data = { ...file },
      settings = o.oai_settings;
    for (const key of Object.keys(file)) {
      const setting = map[key]?.[1];
      if (setting && settings[setting] !== undefined) live[key] = clone(settings[setting]);
    }
    return { live, file };
  },
  /** Keys where the running settings differ from the saved preset file. */
  presetChanges(
    this: HostAdapter,
    name: string,
    running: { live: Data; file: Data } | null = this.runningPreset(name),
  ): string[] {
    if (!running) return [];
    const { live, file } = running;
    return Object.keys(file).filter((k) => !sameData(live[k], file[k]));
  },
  /** Applies preset fields to the running settings through SillyTavern's own controls. */
  applyPreset(this: HostAdapter, patch: Data) {
    const o = this.openai,
      map: Record<string, [string, string, boolean, boolean]> = o.settingsToUpdate,
      $ = window.jQuery;
    let prompts = false;
    for (const [key, value] of Object.entries(patch)) {
      const entry = map[key];
      if (!entry) continue;
      const [selector, setting, checkbox] = entry;
      o.oai_settings[setting] = clone(value);
      if (key === "prompts" || key === "prompt_order") prompts = true;
      else if (selector && selector !== "#NULL_SELECTOR")
        // The input handlers keep SillyTavern's own copies (counters, derived limits) in step.
        checkbox
          ? $(selector).prop("checked", value).trigger("input")
          : $(selector).val(value).trigger("input");
    }
    if (prompts) void o.promptManager?.saveServiceSettings().then(() => o.promptManager.renderDebounced());
    ctx().saveSettingsDebounced();
    this.resourceVersions.preset++;
    this.invalidate("resources");
  },
  /** Applies saved prompt-text drafts of the running preset to the running settings. */
  applyPresetDraft(this: HostAdapter, name: string, base: Data, draft: Data) {
    validatePreset(draft);
    const live = this.livePreset(name);
    if (!live) throw new Error("预设已切换，草稿已保留。");
    const merged = mergeEdits(base, draft, live),
      changed = Object.keys(merged).filter((k) => JSON.stringify(merged[k]) !== JSON.stringify(live[k]));
    if (changed.length) this.applyPreset(Object.fromEntries(changed.map((k) => [k, merged[k]])));
    return this.livePreset(name)!;
  },
  /** Writes the running settings into the preset file (SillyTavern's "Update current preset"). */
  async updatePreset(this: HostAdapter, name: string) {
    const o = this.openai;
    // Keys SillyTavern does not map (vendor or extension data) stay as the file has them.
    const preset = { ...this.presetData(name), ...clone(o.getChatCompletionPreset(o.oai_settings)) };
    await ctx().getPresetManager().savePreset(name, preset);
    this.resourceVersions.preset++;
    this.invalidate("resources");
  },
  /** Reapplies the preset file to the running settings, dropping changes not written to it. */
  async revertPreset(this: HostAdapter) {
    const { eventSource, eventTypes } = ctx();
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, 3000);
      eventSource.once(eventTypes.OAI_PRESET_CHANGED_AFTER, () => {
        clearTimeout(timer);
        resolve();
      });
      window.jQuery("#settings_preset_openai").trigger("change");
    });
    this.resourceVersions.preset++;
    this.invalidate("resources");
  },
  async savePreset(this: HostAdapter, name: string, base: Data, draft: Data) {
    validatePreset(draft);
    const merged = mergeEdits(base, draft, this.presetData(name));
    await ctx().getPresetManager().savePreset(name, merged);
    this.invalidate("resources");
    return merged;
  },
  traceComposition(this: HostAdapter) {
    const manager = this.openai?.promptManager;
    if (!manager?.tokenHandler) return null;
    const counts = clone(manager.tokenHandler.getCounts());
    return {
      counts,
      total: manager.tokenHandler.getTotal(),
      limit: ctx().chatCompletionSettings.openai_max_context,
      source: "PromptManager token counts",
      historyIncludesInput: true,
    };
  },
};
