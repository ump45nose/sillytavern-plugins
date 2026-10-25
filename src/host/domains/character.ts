import type { HostAdapter } from "../adapter";
import type { Data, Item } from "../types";
import { clone, deepMerge, mergeEdits, sameData } from "../model";
import { ctx } from "../internals";

/** Characters: selection, creation/import, card data and bulk actions. */
export const characterMethods = {
  async selectCharacter(this: HostAdapter, id: string) {
    if (this.isBusy()) throw new Error("生成完成后再切换角色。");
    const index = ctx().characters.findIndex((x: Data) => x.avatar === id);
    if (index < 0) throw new Error("角色已不存在。");
    await ctx().selectCharacterById(index);
  },
  async createCharacter(this: HostAdapter, name: string) {
    const form = new FormData();
    form.append("ch_name", name);
    form.append("description", "");
    form.append("first_mes", "");
    const response = await this.upload("/api/characters/create", form);
    if (!response.ok) throw new Error(`创建角色失败 (${response.status})`);
    const avatar = await response.text();
    await ctx().getCharacters();
    this.invalidate("characters");
    return avatar.replace(/^"|"$/g, "");
  },
  async importCharacter(this: HostAdapter, file: File) {
    const form = new FormData();
    form.append("avatar", file);
    form.append("file_type", file.name.split(".").pop() || "");
    form.append("user_name", ctx().name1 || "User");
    const response = await this.upload("/api/characters/import", form);
    if (!response.ok) throw new Error(`导入角色失败 (${response.status})`);
    const data = await response.json();
    if (data.error) throw new Error("角色文件无法解析。");
    await ctx().getCharacters();
    this.invalidate("characters");
    return data.file_name;
  },
  async characterAvatar(this: HostAdapter, id: string, file: File) {
    const form = new FormData();
    form.append("avatar", file);
    form.append("avatar_url", id);
    const response = await this.upload("/api/characters/edit-avatar", form);
    if (!response.ok) throw new Error(`头像保存失败 (${response.status})`);
    await ctx().getCharacters();
    this.invalidate("characters");
  },
  async duplicateCharacter(this: HostAdapter, id: string) {
    const data = await (await this.request("/api/characters/duplicate", { avatar_url: id })).json();
    await ctx().getCharacters();
    this.invalidate("characters");
    return data.path;
  },
  /** Tokens for a card field with the active tokenizer; null when the host has none. */
  async tokenCount(this: HostAdapter, text: string): Promise<number | null> {
    if (!text) return 0;
    const count = ctx().getTokenCountAsync;
    return typeof count === "function" ? Number(await count(text)) : null;
  },
  /** The context window the next prompt is cut to. */
  contextLimit(this: HostAdapter): number | null {
    const c = ctx();
    return (
      Number(c.mainApi === "openai" ? c.chatCompletionSettings?.openai_max_context : c.maxContext) || null
    );
  },
  async characterData(this: HostAdapter, id: string) {
    const i = ctx().characters.findIndex((x: Data) => x.avatar === id);
    if (i < 0) throw new Error("角色已不存在。");
    const response = await this.request("/api/characters/get", {
      avatar_url: id,
    });
    return response.json();
  },
  /** Saves the fields changed from base to draft and returns the card as saved, without reading it again. */
  async saveCharacter(this: HostAdapter, id: string, base: Data, draft: Data) {
    const latest = await this.characterData(id),
      merged = mergeEdits(base, draft, latest.data ?? {});
    const patch: Data = {};
    for (const k of Object.keys(draft)) if (!sameData(base[k], draft[k])) patch[k] = merged[k];
    if (!Object.keys(patch).length) return latest;
    await this.request("/api/characters/merge-attributes", { avatar: id, data: patch });
    await ctx().getCharacters();
    // Rebuilds the character slice through the adapter's event table.
    await ctx().eventSource.emit(ctx().eventTypes.CHARACTER_EDITED);
    return { ...latest, data: deepMerge(latest.data ?? {}, patch) };
  },
  async favorite(this: HostAdapter, item: Item) {
    const c = await this.characterData(item.id),
      base = clone(c.data ?? {}),
      draft = clone(base);
    draft.extensions = { ...draft.extensions, fav: !draft.extensions?.fav };
    return this.saveCharacter(item.id, base, draft);
  },
  async exportCharacter(this: HostAdapter, id: string) {
    const response = await this.request("/api/characters/export", {
      avatar_url: id,
      format: "png",
    });
    this.download(await response.blob(), id);
  },
  async deleteCharacters(this: HostAdapter, ids: string[]) {
    if (!ids.length) return;
    if (ids.includes(this.snapshot().character?.id ?? ""))
      throw new Error("请先切换到未被选中的角色，再删除当前角色。");
    for (const id of ids) {
      await this.request("/api/characters/delete", {
        avatar_url: id,
        delete_chats: false,
      });
    }
    await ctx().getCharacters();
    this.invalidate("characters");
  },
  /** One merge request per card, from the tags in the loaded list; one reload and event at the end. */
  async tagCharacters(this: HostAdapter, ids: string[], tag: string) {
    const name = tag.trim();
    if (!ids.length || !name) return;
    const c = ctx();
    let saved = false;
    try {
      for (const id of ids) {
        const card = c.characters.find((x: Data) => x.avatar === id);
        if (!card) throw new Error("角色已不存在。");
        const tags: string[] = card.data?.tags ?? [];
        if (tags.includes(name)) continue;
        await this.request("/api/characters/merge-attributes", {
          avatar: id,
          data: { tags: [...new Set([...tags, name])] },
        });
        saved = true;
      }
    } finally {
      if (saved) {
        await c.getCharacters();
        await c.eventSource.emit(c.eventTypes.CHARACTER_EDITED);
      }
    }
  },
};
