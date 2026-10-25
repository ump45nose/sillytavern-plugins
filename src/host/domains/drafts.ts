import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { clone, sameData } from "../model";

/** Resource drafts: dirty tracking and the save-all path used by the close guard. */
export const draftsMethods = {
  dirtyDraftKeys(this: HostAdapter) {
    return [...this.drafts]
      .filter(
        ([, d]) =>
          !!d.extra?.advanced ||
          !sameData(d.base, d.draft) ||
          (d.extra?.tab === "json" && d.extra.json !== JSON.stringify(d.draft, null, 2)),
      )
      .map(([key]) => key);
  },
  async saveDrafts(this: HostAdapter) {
    for (const key of this.dirtyDraftKeys()) {
      const d = this.drafts.get(key)!;
      const colon = key.indexOf(":"),
        kind = key.slice(0, colon),
        id = key.slice(colon + 1);
      let saved: Data;
      if (kind === "world")
        saved = await this.saveBook(id, d.base, d.extra?.tab === "json" ? JSON.parse(d.extra.json) : d.draft);
      else if (kind === "preset") {
        if (d.extra?.advanced) throw new Error("预设 JSON 无法解析，请先修正。");
        saved = this.livePreset(id)
          ? this.applyPresetDraft(id, d.base, d.draft)
          : await this.savePreset(id, d.base, d.draft);
      } else if (kind === "connection") {
        await this.saveProfile(id, d.base, d.draft);
        saved = clone(this.snapshot().resources.connection.find((r) => r.id === id)!.data!);
      } else if (kind === "persona") saved = await this.savePersona(id, d.base, d.draft);
      else if (kind === "group") {
        const groups = await this.saveGroup(id === "new" ? null : d.base, d.draft);
        saved = groups.find((g: Data) => (id === "new" ? g.name === d.draft.name : g.id === id));
        if (!saved) throw new Error("群组保存后无法读取。");
      } else if (kind === "group-overrides") {
        if (!d.extra) throw new Error("群聊草稿缺少绑定信息。");
        saved = await this.saveGroupOverrides(d.extra.groupId, d.extra.chatId, d.base, d.draft);
      } else if (kind === "character") saved = (await this.saveCharacter(id, d.base, d.draft)).data;
      else continue;
      this.drafts.set(key, { base: clone(saved), draft: clone(saved) });
    }
  },
};
