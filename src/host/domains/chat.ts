import type { HostAdapter } from "../adapter";
import type { Data } from "../types";
import { ctx, internal, nativeNodes } from "../internals";
import { bus } from "../bus";
import { castTagsAsNames } from "../cast";
import { stripOptions } from "../options";

/** Chat files, floors, quick replies, input and RP presentation. */
export const chatMethods = {
  quickReplies(this: HostAdapter) {
    const api = (window as any).quickReplyApi;
    if (!api?.settings.isEnabled) return [];
    return [
      ...api.settings.config.setList,
      ...(api.settings.chatConfig?.setList ?? []),
      ...(api.settings.charConfig?.setList ?? []),
    ]
      .filter((item: any) => item.isVisible)
      .flatMap((item: any) =>
        item.set.qrList
          .filter((qr: any) => !qr.isHidden)
          .map((qr: any) => ({
            id: qr.id,
            set: item.set.name,
            label: qr.label,
            message: qr.message,
            insertOnly: item.set.disableSend,
            key: `${item.set.name}:${qr.id}`,
            execute: () => qr.onExecute(),
          })),
      );
  },
  messageTime(this: HostAdapter, value: string | number | undefined) {
    if (!value) return "";
    const time = ctx().timestampToMoment(value);
    return time?.isValid() ? time.format("MM-DD HH:mm") : "";
  },
  rpPresentation(this: HostAdapter, speaker?: string) {
    const c = ctx(),
      snap = this.snapshot();
    const actor = c.characters.find((item: Data) => item.name === speaker) ?? snap.character?.data;
    const holder =
      [...document.querySelectorAll<HTMLElement>(".expression-holder")].find(
        (n) => actor?.avatar && n.dataset.avatar === actor.avatar,
      ) ?? (snap.groupId ? null : document.getElementById("expression-holder"));
    const image = holder?.querySelector<HTMLImageElement>("img.expression[src]");
    const sprite = image?.getAttribute("src") || "";
    const characterSprite =
      !snap.groupId && typeof c.chatMetadata?.workbenchRP?.characterSprite === "string"
        ? c.chatMetadata.workbenchRP.characterSprite
        : "";
    const scene = c.chatMetadata?.workbenchRP?.scene;
    return {
      name: actor?.name || snap.groupName || "选择角色",
      portrait:
        actor?.avatar && actor.avatar !== "none" ? "/characters/" + encodeURIComponent(actor.avatar) : "",
      // Keep native expressions live; a chat-specific sprite fills in when none is available.
      // Native emoji fallbacks are icons, not full-size character artwork.
      sprite: sprite && !sprite.includes("/expressions/images/") ? sprite : characterSprite,
      userName: c.name1 || "你",
      userPortrait: snap.current.persona ? "/User%20Avatars/" + encodeURIComponent(snap.current.persona) : "",
      // A chat can supply a transparent user sprite without replacing its persona avatar.
      userSprite:
        typeof c.chatMetadata?.workbenchRP?.userSprite === "string"
          ? c.chatMetadata.workbenchRP.userSprite
          : "",
      scene: scene && typeof scene === "object" ? (scene as Record<string, unknown>) : {},
    };
  },
  async recentChats(this: HostAdapter) {
    if (ctx().groupId)
      return this.sortChats(await (await internal("groupChats")).getGroupPastChats(ctx().groupId));
    const c = this.snapshot().character;
    if (!c) return [];
    const r = await this.request("/api/characters/chats", { avatar_url: c.id });
    const data = await r.json();
    return data.error ? [] : this.sortChats(Object.values(data) as Data[]);
  },
  sortChats(this: HostAdapter, chats: Data[]) {
    const date = (value: any) => {
      if (!value) return 0;
      const time = typeof value === "number" ? value : ctx().timestampToMoment(value)?.valueOf();
      return Number.isFinite(time) ? time : 0;
    };
    return chats.sort((a, b) => date(b.last_mes) - date(a.last_mes));
  },
  async openChat(this: HostAdapter, name: string) {
    if (this.isBusy()) throw new Error("请先停止生成，再切换对话。");
    const script = await internal("script");
    await script.saveChatConditional();
    if (ctx().groupId)
      await (await internal("groupChats")).openGroupChat(ctx().groupId, name.replace(/\.jsonl$/, ""));
    else await ctx().openCharacterChat(name.replace(/\.jsonl$/, ""));
  },
  async jump(this: HostAdapter, id: number) {
    const selector = `#chat .mes[mesid="${id}"]`;
    let node = document.querySelector(selector);
    for (let i = 0; !node && i < 50; i++) {
      const button = document.querySelector<HTMLElement>("#show_more_messages");
      if (!button) break;
      button.click();
      await new Promise((r) => setTimeout(r, 20));
      node = document.querySelector(selector);
    }
    if (this.prefs().layout === "rp") {
      bus.emit("rp-jump", id);
      return;
    }
    node?.scrollIntoView({
      block: "center",
      behavior:
        matchMedia("(prefers-reduced-motion:reduce)").matches ||
        document.body.classList.contains("reduced-motion")
          ? "auto"
          : "smooth",
    });
    bus.emit("floor-jump", id);
  },
  async renameChat(this: HostAdapter, name: string, next: string) {
    if (this.isBusy()) throw new Error("生成中不能重命名聊天。");
    await ctx().renameChat(name.replace(/\.jsonl$/, ""), next.trim().replace(/\.jsonl$/, ""));
  },
  async newChat(this: HostAdapter) {
    if (this.isBusy()) throw new Error("请先停止生成。");
    const script = await internal("script");
    await script.saveChatConditional();
    await script.doNewChat();
  },
  async deleteChat(this: HostAdapter, name: string) {
    if (this.isBusy()) throw new Error("请先停止生成。");
    const file = name.replace(/\.jsonl$/, ""),
      c = ctx(),
      script = await internal("script");
    await script.saveChatConditional();
    if (c.groupId) {
      const module = await internal("groupChats"),
        group = c.groups.find((g: Data) => g.id === c.groupId);
      if (!group?.chats.includes(file)) throw new Error("群聊文件已不存在。");
      await this.request("/api/chats/group/delete", { id: file });
      group.chats = group.chats.filter((id: string) => id !== file);
      if (group.chat_id === file) {
        if (group.chats.length) await module.openGroupChat(c.groupId, group.chats.at(-1));
        else await module.createNewGroupChat(c.groupId);
      }
      await module.editGroup(c.groupId, true, true);
      await c.eventSource.emit(c.eventTypes.GROUP_CHAT_DELETED, file);
    } else {
      const character = this.snapshot().character;
      if (!character) throw new Error("请先选择角色。");
      await this.request("/api/chats/delete", { avatar_url: character.id, chatfile: file + ".jsonl" });
      if (this.snapshot().chatName === file) await script.replaceCurrentChat();
      await c.eventSource.emit(c.eventTypes.CHAT_DELETED, file);
    }
  },
  async importChat(this: HostAdapter, file: File) {
    if (this.isBusy()) throw new Error("请先停止生成。");
    const c = ctx(),
      format = file.name.split(".").pop()?.toLowerCase();
    if (!["json", "jsonl"].includes(format || "")) throw new Error("请选择 JSON 或 JSONL 聊天文件。");
    if (c.groupId && format !== "jsonl") throw new Error("群聊仅支持酒馆原生 JSONL 格式。");
    if (!c.groupId && !this.snapshot().character) throw new Error("请先选择角色。");
    const form = new FormData();
    form.append("user_name", c.name1 || "User");
    form.append("avatar_url", this.snapshot().character?.id || "");
    form.append("character_name", this.snapshot().character?.name || "");
    form.append("file_type", format!);
    form.append("avatar", file);
    const imported = c.groupId
      ? await (await internal("groupChats")).importGroupChat(form)
      : await (await internal("script")).importCharacterChat(form);
    if (!imported?.length) throw new Error("导入未成功，请检查文件格式和服务连接。");
    this.chatsVersion++;
    this.invalidate("session");
  },
  async exportChat(this: HostAdapter, name: string) {
    const script = await internal("script");
    await script.saveChatConditional();
    const data = await (
      await this.request("/api/chats/export", {
        is_group: !!ctx().groupId,
        avatar_url: this.snapshot().character?.id,
        file: name.replace(/\.jsonl$/, "") + ".jsonl",
        exportfilename: name,
        format: "jsonl",
      })
    ).json();
    if (typeof data.result !== "string") throw new Error("聊天导出未返回内容。");
    this.download(
      new Blob([data.result], { type: "application/jsonl" }),
      name.replace(/\.jsonl$/, "") + ".jsonl",
    );
  },
  exportSnapshot(this: HostAdapter) {
    const c = ctx();
    return {
      key: `${c.groupId || this.snapshot().character?.id || ""}:${c.getCurrentChatId() || ""}`,
      timestamp: Date.now(),
      messages: c.chat.map((message: Data, id: number) => ({
        id,
        name: String(message.name || ""),
        // Cast tags (名字|表情:) export as the reader sees them: the speaker's name.
        text: message.is_user
          ? String(message.mes || "")
          : castTagsAsNames(stripOptions(String(message.mes || ""))),
        role: message.is_system
          ? ("system" as const)
          : message.is_user
            ? ("user" as const)
            : ("assistant" as const),
      })),
    };
  },
  setInput(this: HostAdapter, text: string) {
    const node = nativeNodes.input as HTMLTextAreaElement;
    node.value = text;
    node.dispatchEvent(new Event("input", { bubbles: true }));
    this.focusInput(text.length);
  },
  /** Puts the caret in the native input. The phone leaves it to the user's tap, so the keyboard
   *  opens when they start typing instead of covering the page each time the input is entered. */
  focusInput(this: HostAdapter, caret?: number) {
    if (document.body.classList.contains("wb-mobile")) return;
    const node = nativeNodes.input as HTMLTextAreaElement;
    node.focus();
    if (caret !== undefined) node.setSelectionRange(caret, caret);
  },
};
