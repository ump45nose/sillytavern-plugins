import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { clone, mergeEdits } from "../model";
import { ctx, internal } from "../internals";

/** Personas: descriptions, locks and persona preferences. */
export const personaMethods = {
  personaData(this: HostAdapter, id: string) {
    const p = ctx().powerUserSettings;
    return clone({
      name: p.personas[id],
      ...(p.persona_descriptions[id] ?? {}),
    });
  },
  async savePersona(this: HostAdapter, id: string, base: Data, draft: Data) {
    const merged = mergeEdits(base, draft, this.personaData(id)),
      p = ctx().powerUserSettings;
    const previousName = p.personas[id],
      previousDescription = p.persona_descriptions[id],
      current = id === this.personas.user_avatar;
    const script = await internal("script"),
      { name, ...description } = merged;
    const applyCurrent = (userName: string, desc: Data) => {
      p.persona_description = desc?.description ?? "";
      p.persona_description_position = desc?.position ?? 0;
      p.persona_description_depth = desc?.depth ?? 2;
      p.persona_description_role = desc?.role ?? 0;
      p.persona_description_lorebook = desc?.lorebook ?? "";
      script.setUserName(userName, { toastPersonaNameChange: false });
      this.personas.setPersonaDescription();
    };
    p.personas[id] = name;
    p.persona_descriptions[id] = description;
    if (current) applyCurrent(name, description);
    try {
      await this.persistSettings();
    } catch (error) {
      if (p.personas[id] === name) p.personas[id] = previousName;
      if (p.persona_descriptions[id] === description) p.persona_descriptions[id] = previousDescription;
      if (current) applyCurrent(p.personas[id], p.persona_descriptions[id]);
      this.invalidate("resources");
      throw error;
    }
    await this.personas.getUserAvatars();
    await ctx().eventSource.emit(ctx().eventTypes.PERSONA_UPDATED, id);
    return merged;
  },
  personaOptions(this: HostAdapter, id: string) {
    const p = ctx().powerUserSettings,
      current = id === this.personas.user_avatar;
    return {
      current,
      locks: {
        default: p.default_persona === id,
        character: current && this.personas.isPersonaLocked("character"),
        chat: current && this.personas.isPersonaLocked("chat"),
      },
      preferences: Object.fromEntries(
        ["persona_show_notifications", "persona_allow_multi_connections", "persona_auto_lock"].map((k) => [
          k,
          !!p[k],
        ]),
      ),
    };
  },
  async personaLock(this: HostAdapter, type: "default" | "character" | "chat", enabled: boolean) {
    // Locks are saved with a debounce, so no event follows in time for the persona panel.
    await this.personas.setPersonaLockState(enabled, type);
    this.invalidate("resources");
  },
  async personaPreference(this: HostAdapter, key: string, value: boolean) {
    if (!["persona_show_notifications", "persona_allow_multi_connections", "persona_auto_lock"].includes(key))
      throw new Error("未知用户设定");
    const p = ctx().powerUserSettings,
      previous = p[key];
    p[key] = value;
    try {
      await this.persistSettings();
    } catch (e) {
      p[key] = previous;
      throw e;
    }
    const input = document.getElementById(key) as HTMLInputElement;
    if (input) input.checked = value;
  },
};
