import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { clone, mergeBook } from "../model";
import { ctx } from "../internals";

/** World books: global activation, character books, bindings and entry persistence. */
export const worldMethods = {
  async toggleBook(this: HostAdapter, name: string, on: boolean) {
    const select = window.jQuery("#world_info");
    const values = new Set<string>(this.world.selected_world_info);
    on ? values.add(name) : values.delete(name);
    select.val([...values].map((value) => String(this.world.world_names.indexOf(value)))).trigger("change");
    // SillyTavern's WORLDINFO_SETTINGS_UPDATED is not awaited by the change trigger; callers read at once.
    this.invalidate("resources", "session");
  },
  characterBooks(this: HostAdapter) {
    const character = this.snapshot().character;
    if (!character) return [] as string[];
    const fileName = character.id.replace(/\.[^.]+$/, "");
    const primary = character.data?.data?.extensions?.world;
    return [
      ...new Set<string>(
        [
          primary,
          ...(this.world.world_info?.charLore?.find((x: Data) => x.name === fileName)?.extraBooks || []),
        ].filter(Boolean),
      ),
    ];
  },
  async toggleCharacterBook(this: HostAdapter, name: string, on: boolean) {
    const character = this.snapshot().character;
    if (!character) throw new Error("请先选择角色，再设置角色卡世界书。");
    const books = new Set(this.characterBooks());
    on ? books.add(name) : books.delete(name);
    const primary = character.data?.data?.extensions?.world;
    if (!on && primary === name) {
      const data = await this.characterData(character.id);
      await this.saveCharacter(character.id, data.data, {
        ...data.data,
        extensions: { ...data.data.extensions, world: "" },
      });
    }
    this.world.charSetAuxWorlds(
      character.id.replace(/\.[^.]+$/, ""),
      [...books].filter((x) => x !== primary),
    );
    await this.persistSettings();
  },
  async readBook(this: HostAdapter, name: string) {
    const response = await this.request("/api/worldinfo/get", { name });
    return response.json();
  },
  async saveBook(this: HostAdapter, name: string, base: Data, draft: Data) {
    const latest = await this.readBook(name),
      data = mergeBook(base, draft, latest);
    await this.request("/api/worldinfo/edit", { name, data });
    this.world.worldInfoCache.set(name, clone(data));
    await ctx().eventSource.emit(ctx().eventTypes.WORLDINFO_UPDATED, name, clone(data));
    ctx().reloadWorldInfoEditor(name);
    return clone(data);
  },
  async createEntry(this: HostAdapter, name: string, data: Data) {
    return this.world.createWorldInfoEntry(name, data);
  },
  worldBindings(this: HostAdapter) {
    return {
      chat: ctx().chatMetadata.world_info || "",
      persona: this.personaData(this.snapshot().current.persona)?.lorebook || "",
      character: this.snapshot().character?.data?.data?.extensions?.world || "",
    };
  },
  async bindWorld(this: HostAdapter, scope: "character" | "chat", name: string) {
    if (scope === "chat") {
      ctx().chatMetadata.world_info = name;
      await ctx().saveMetadata();
      this.invalidate("session");
    } else {
      const character = this.snapshot().character;
      if (!character) throw new Error("请先选择角色。");
      const data = await this.characterData(character.id);
      await this.saveCharacter(character.id, data.data, {
        ...data.data,
        extensions: { ...data.data.extensions, world: name },
      });
    }
  },
};
