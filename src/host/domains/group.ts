import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { clone, mergeEdits } from "../model";
import { ctx, internal } from "../internals";

/** Groups: membership, media policy and per-chat overrides. */
export const groupMethods = {
  groups(this: HostAdapter) {
    return clone(ctx().groups || []);
  },
  async groupAvatar(this: HostAdapter, file: File, id: string) {
    const utils = await internal("utils"),
      image = await utils.createThumbnail(await utils.getBase64Async(file), 300, 300);
    return utils.saveBase64AsFile(
      image.replace(/^data:image\/[a-z]+;base64,/, ""),
      id,
      "workbench-group-" + Date.now(),
      "jpg",
    );
  },
  groupMedia(this: HostAdapter, id: string) {
    const p = ctx().powerUserSettings;
    return p.external_media_allowed_overrides.includes(id)
      ? "allow"
      : p.external_media_forbidden_overrides.includes(id)
        ? "forbid"
        : "global";
  },
  async setGroupMedia(this: HostAdapter, id: string, value: string) {
    const c = ctx(),
      p = c.powerUserSettings;
    p.external_media_allowed_overrides = p.external_media_allowed_overrides.filter((x: string) => x !== id);
    p.external_media_forbidden_overrides = p.external_media_forbidden_overrides.filter(
      (x: string) => x !== id,
    );
    if (value === "allow") p.external_media_allowed_overrides.push(id);
    if (value === "forbid") p.external_media_forbidden_overrides.push(id);
    await this.persistSettings();
    if (c.groupId === id) await c.reloadCurrentChat();
  },
  groupOverrides(this: HostAdapter) {
    const m = ctx().chatMetadata;
    return {
      scenario: m.scenario || "",
      mes_example: m.mes_example || "",
      system_prompt: m.system_prompt || "",
    };
  },
  groupChatId(this: HostAdapter) {
    return String(ctx().chatId || "");
  },
  async saveGroupOverrides(this: HostAdapter, id: string, chatId: string, base: Data, draft: Data) {
    const c = ctx();
    if (String(c.groupId) !== id || String(c.chatId) !== chatId)
      throw new Error("当前群聊已切换，草稿仍保留。");
    if (this.isBusy()) throw new Error("请等待生成结束后保存。");
    const edited = mergeEdits(base, draft, this.groupOverrides()),
      metadata = { ...c.chatMetadata, ...edited };
    await this.request("/api/chats/group/save", {
      id: chatId,
      chat: [{ chat_metadata: metadata, user_name: "unused", character_name: "unused" }, ...c.chat],
      force: false,
    });
    Object.assign(c.chatMetadata, edited);
    return edited;
  },
  async openGroup(this: HostAdapter, id: string) {
    if (this.isBusy()) throw new Error("生成完成后再切换群组。");
    await (await internal("groupChats")).openGroupById(id);
  },
  async saveGroup(this: HostAdapter, base: Data | null, draft: Data) {
    const module = await internal("groupChats");
    if (base) {
      const latest = ctx().groups.find((g: Data) => g.id === base.id);
      if (!latest) throw new Error("群组已不存在。");
      await this.request("/api/groups/edit", mergeEdits(base, draft, latest));
    } else {
      const cached = this.drafts.get("group:new"),
        created = cached?.extra?.createdId
          ? ctx().groups.find((g: Data) => g.id === cached.extra!.createdId)
          : await (await this.request("/api/groups/create", draft)).json();
      if (!created) throw new Error("刚创建的群组已不存在，草稿仍保留。");
      if (cached) cached.extra = { ...cached.extra, createdId: created.id };
      // The official create endpoint only accepts its standard fields. Preserve
      // additional group preferences through its existing edit endpoint.
      try {
        await this.request("/api/groups/edit", {
          ...created,
          ...draft,
          id: created.id,
          chat_id: created.chat_id,
          chats: created.chats,
        });
      } catch (e) {
        await module.getGroups();
        this.invalidate("session");
        throw e;
      }
    }
    await module.getGroups();
    this.invalidate("session");
    return this.groups();
  },
  async deleteGroup(this: HostAdapter, id: string) {
    await this.request("/api/groups/delete", { id });
    const module = await internal("groupChats");
    if (ctx().groupId === id) await module.resetSelectedGroup();
    await module.getGroups();
    this.invalidate("session");
  },
};
