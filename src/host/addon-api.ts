import { randomId } from "./ids";
import type { HostAdapter } from "./adapter";
import type { Data } from "./types";
import type { AddonId } from "../addons/catalog";
import type { MessageTarget, StoryReply, TaskHost } from "../addons/types";
import { ctx as context, internal } from "./internals";
import { bus, guards } from "./bus";
const credentialField = /^(?:key|api[-_]?key|token|secret|password|authorization|credentials?)$/i;
function safeMetadata(value: any): any {
  if (Array.isArray(value)) return value.map(safeMetadata);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !credentialField.test(key))
        .map(([key, v]) => [key, safeMetadata(v)]),
    );
  return value;
}
const copy = <T>(value: T): T => structuredClone(value);
function signature(message: Data) {
  const text = JSON.stringify([message.mes, message.swipe_id ?? 0]);
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
  return String(hash >>> 0);
}
/** One completion bridge per host. No add-on business imports or startup feature requests. */
export class AddonBridge {
  private replies = new Set<(reply: StoryReply) => void>();
  private inputs = new Set<() => void>();
  private chatChanges = new Set<() => void>();
  private idleCancels = new Set<() => void>();
  private disposed = false;
  private cleanup: (() => void)[] = [];
  private tokens = new WeakMap<object, string>();
  private cycle: {
    key: string;
    type: string;
    id: number;
    stopped: boolean;
  } | null = null;
  private saves: Promise<unknown> = Promise.resolve();
  private writing = false;
  private completed: {
    stopped: boolean;
  } | null = null;
  private completionTimers = new Set<ReturnType<typeof setTimeout>>();
  constructor(private host: HostAdapter) {
    const on = (name: string, fn: (...args: any[]) => void) => {
      const c = context(),
        event = c.eventTypes[name];
      if (event) {
        c.eventSource.on(event, fn);
        this.cleanup.push(() => c.eventSource.removeListener(event, fn));
      }
    };
    on("CHAT_CHANGED", () => {
      this.cycle = null;
      this.chatChanges.forEach((fn) => fn());
    });
    on("GENERATION_STARTED", (type: string, _options: unknown, dry: boolean) => {
      if (!dry) this.cycle = { key: this.key(), type, id: -1, stopped: false };
    });
    on("MESSAGE_RECEIVED", (id: number) => {
      if (this.cycle) this.cycle.id = id;
    });
    on("GENERATION_STOPPED", () => {
      if (this.cycle) this.cycle.stopped = true;
      if (this.completed) this.completed.stopped = true;
    });
    on("GENERATION_ENDED", () => {
      const cycle = this.cycle;
      this.cycle = null;
      if (
        !cycle ||
        cycle.stopped ||
        cycle.key !== this.key() ||
        !["normal", "continue"].includes(cycle.type) ||
        cycle.id < 0
      )
        return;
      const message = context().chat[cycle.id];
      if (!message || message.is_user || message.is_system || !String(message.mes || "").trim()) return;
      const reply = { target: this.target(cycle.id), type: cycle.type };
      this.completed = cycle;
      const timer = setTimeout(() => {
        this.completionTimers.delete(timer);
        if (!cycle.stopped && cycle.key === this.key()) this.replies.forEach((fn) => fn(reply));
        if (this.completed === cycle) this.completed = null;
      }, 0);
      this.completionTimers.add(timer);
    });
    const input = (e: Event) => {
      if (e.isTrusted) this.inputs.forEach((fn) => fn());
    };
    document.getElementById("send_textarea")?.addEventListener("input", input);
    this.cleanup.push(() => document.getElementById("send_textarea")?.removeEventListener("input", input));
    this.cleanup.push(bus.on("composer-input", () => this.inputs.forEach((fn) => fn())));
  }
  onChatChange = (fn: () => void) => {
    this.chatChanges.add(fn);
    return () => {
      this.chatChanges.delete(fn);
    };
  };
  key() {
    const c = context();
    return `${c.groupId || c.characters[c.characterId]?.avatar || ""}:${c.getCurrentChatId() || ""}`;
  }
  target(id: number): MessageTarget {
    const message = context().chat[id];
    if (!message) throw new Error("目标楼层已不存在。");
    let token = this.tokens.get(message);
    if (!token) {
      token = randomId();
      this.tokens.set(message, token);
    }
    return { chatKey: this.key(), id, token, version: signature(message) };
  }
  valid = (target: MessageTarget) => {
    const message = context().chat[target.id];
    return (
      target.chatKey === this.key() &&
      !!message &&
      this.tokens.get(message) === target.token &&
      signature(message) === target.version
    );
  };
  onReply = (fn: (reply: StoryReply) => void) => {
    this.replies.add(fn);
    return () => {
      this.replies.delete(fn);
    };
  };
  private async idle(key: string) {
    if (this.disposed) throw new Error("工作台已退出。");
    if (!this.host.snapshot().busy) return;
    await new Promise<void>((resolve, reject) => {
      const finish = (error?: Error) => {
        clearTimeout(timer);
        off();
        this.idleCancels.delete(cancel);
        error ? reject(error) : resolve();
      };
      const cancel = () => finish(new Error("任务已结束。"));
      const timer = setTimeout(() => finish(new Error("当前生成尚未结束，请稍后保存。")), 600000);
      const off = this.host.subscribe(() => {
        if (key !== this.key()) finish(new Error("聊天已切换。"));
        else if (!this.host.snapshot().busy) finish();
      });
      this.idleCancels.add(cancel);
    });
  }
  async persist(key: string, metadata: Data, messages: Data[]) {
    const c = context();
    if (this.disposed || key !== this.key() || !c.getCurrentChatId())
      throw new Error("聊天已切换或尚未保存。");
    const header = { chat_metadata: metadata, user_name: "unused", character_name: "unused" };
    const character = c.characters[c.characterId];
    const body = c.groupId
      ? { id: c.getCurrentChatId(), chat: [header, ...messages], force: false }
      : {
          ch_name: character?.name,
          file_name: c.getCurrentChatId(),
          avatar_url: character?.avatar,
          chat: [header, ...messages],
          force: false,
        };
    const response = await this.host.request(c.groupId ? "/api/chats/group/save" : "/api/chats/save", body);
    if (!response.ok) throw new Error("聊天保存失败，进度未推进。");
    if (this.disposed || key !== this.key()) throw new Error("聊天已切换，结果未写入当前聊天。");
  }
  private serial<T>(fn: () => Promise<T>): Promise<T> {
    const next = this.saves.then(fn, fn);
    this.saves = next.catch(() => {});
    return next;
  }
  insert(text: string, mode: "replace" | "caret") {
    if (document.body.classList.contains("wb-image-input-mode"))
      throw new Error("请先退出手动生图输入，再插入写作指令。");
    const input = document.getElementById("send_textarea") as HTMLTextAreaElement;
    const start = input.selectionStart,
      end = input.selectionEnd;
    input.value = mode === "replace" ? text : input.value.slice(0, start) + text + input.value.slice(end);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    this.host.focusInput(mode === "replace" ? text.length : start + text.length);
    bus.emit("image-compose");
  }
  async write(text: string | null, signal: AbortSignal, allowDraft = false): Promise<StoryReply> {
    if (document.body.classList.contains("wb-image-input-mode"))
      throw new Error("请先退出手动生图输入，再运行自动写作。");
    if (this.writing || this.host.snapshot().busy) throw new Error("请等待当前生成完成。");
    const input = document.getElementById("send_textarea") as HTMLTextAreaElement;
    if (input.value.trim() && !allowDraft) throw new Error("输入框有未发送内容，自动写作已暂停。");
    this.writing = true;
    try {
      return await new Promise<StoryReply>((resolve, reject) => {
        const key = this.key(),
          c = context();
        let ended = false;
        let timer: ReturnType<typeof setTimeout>;
        let off = () => {};
        const finish = (error?: Error, reply?: StoryReply) => {
          if (ended) return;
          ended = true;
          clearTimeout(timer);
          clearTimeout(completionFallback);
          off();
          signal.removeEventListener("abort", abort);
          c.eventSource.removeListener(c.eventTypes.GENERATION_ENDED, end);
          c.eventSource.removeListener(c.eventTypes.GENERATION_STOPPED, stopped);
          error ? reject(error) : resolve(reply!);
        };
        const abort = () => {
          c.stopGeneration();
          finish(new DOMException("任务已停止", "AbortError"));
        };
        let completionFallback: ReturnType<typeof setTimeout> | undefined;
        const end = () => {
          completionFallback = setTimeout(() => {
            if (!ended) finish(new Error("未收到有效剧情回复，写作已暂停。"));
          }, 200);
        };
        const stopped = () => finish(new Error("生成已停止，写作进度保留。"));
        off = this.onReply((reply) => {
          if (reply.target.chatKey === key) finish(undefined, reply);
        });
        c.eventSource.on(c.eventTypes.GENERATION_ENDED, end);
        c.eventSource.on(c.eventTypes.GENERATION_STOPPED, stopped);
        signal.addEventListener("abort", abort, { once: true });
        timer = setTimeout(() => {
          c.stopGeneration();
          finish(new Error("生成超时，写作已暂停。"));
        }, 600000);
        if (signal.aborted) {
          abort();
          return;
        }
        if (text !== null) {
          this.insert(text, "replace");
          document.getElementById("send_but")!.click();
        } else void c.generate("continue").catch((error: Error) => finish(error));
      });
    } finally {
      this.writing = false;
    }
  }
  api(id: AddonId, open: (view: "workspace" | "editor") => void): TaskHost {
    const bridge = this,
      host = this.host;
    const grant = (feature: AddonId) => {
      if (id !== feature) throw new Error("此附加功能未获授该宿主能力。");
    };
    return Object.freeze({
      subscribe: host.subscribe,
      revision: host.revision,
      snapshot: () => ({
        chatKey: bridge.key(),
        chatName: host.snapshot().chatName,
        busy: host.snapshot().busy,
      }),
      exportSnapshot: () => host.exportSnapshot(id === "record-export" ? "raw" : "reading"),
      download: (blob: Blob, filename: string) => host.download(blob, filename),
      jump: (n: number) => host.jump(n),
      exportChat: (name: string) => host.exportChat(name),
      metadata: () => copy(context().chatMetadata.workbench_addons?.[id] || {}),
      saveMetadata: (data: Data, key: string) =>
        bridge.serial(async () => {
          await bridge.idle(key);
          if (key !== bridge.key()) throw new Error("聊天已切换。");
          const c = context(),
            metadata = {
              ...c.chatMetadata,
              workbench_addons: { ...c.chatMetadata.workbench_addons, [id]: safeMetadata(copy(data)) },
            };
          await bridge.persist(key, metadata, copy(c.chat));
          c.chatMetadata.workbench_addons = metadata.workbench_addons;
          // Add-on views re-read metadata on any non-chat change; the chat index is untouched.
          host.invalidate("session");
        }),
      config: () => copy(host.prefs().addonSettings?.[id] || {}),
      saveConfig: async (data: Data) => {
        host.preference({ addonSettings: { ...host.prefs().addonSettings, [id]: copy(data) } });
        await host.persistSettings();
      },
      input: () => (document.getElementById("send_textarea") as HTMLTextAreaElement).value,
      onReply: bridge.onReply,
      onInput: (fn: () => void) => {
        bridge.inputs.add(fn);
        return () => {
          bridge.inputs.delete(fn);
        };
      },
      insert: (text: string, mode: "replace" | "caret") => bridge.insert(text, mode),
      write: (text: string | null, signal: AbortSignal, allowDraft?: boolean) => {
        grant("outline");
        return bridge.write(text, signal, allowDraft);
      },
      target: (n: number) => bridge.target(n),
      validTarget: bridge.valid,
      profiles: () => host.snapshot().resources.connection.map((p) => ({ id: p.id, name: p.name })),
      rewrite: async (prompt: string, profile: string, signal: AbortSignal) => {
        grant("image-gen");
        const { ConnectionManagerRequestService } = await internal("shared");
        const c = context(),
          selected = profile || c.extensionSettings.connectionManager?.selectedProfile;
        if (!selected) throw new Error("请在生图配置中选择独立转写连接，或先保存当前连接配置。");
        const result = await ConnectionManagerRequestService.sendRequest(
          selected,
          [{ role: "user", content: prompt }],
          1500,
          { stream: false, signal, extractData: true, includePreset: false, includeInstruct: false },
        );
        const text = typeof result === "string" ? result : result?.content;
        if (!text) throw new Error("转写模型未返回文本。");
        return text;
      },
      request: (path: string, body: Data, signal: AbortSignal) => {
        grant("image-gen");
        if (!["/api/openai/generate-image", "/api/novelai/generate-image"].includes(path))
          throw new Error("此附加功能未获授该请求能力。");
        return fetch(path, {
          method: "POST",
          headers: context().getRequestHeaders(),
          body: JSON.stringify(body),
          signal,
        });
      },
      saveImage: async (dataUrl: string, signal: AbortSignal) => {
        grant("image-gen");
        const match = dataUrl.match(/^data:image\/(png|jpeg|webp);base64,(.+)$/s);
        if (!match) throw new Error("图片格式不支持。");
        const response = await fetch("/api/images/upload", {
          method: "POST",
          headers: context().getRequestHeaders(),
          body: JSON.stringify({ image: match[2], format: match[1], filename: "wb-" + randomId() }),
          signal,
        });
        if (!response.ok) throw new Error("图片保存失败。");
        const data = await response.json();
        if (typeof data.path !== "string" || !data.path.startsWith("/user/images/"))
          throw new Error("图片保存路径无效。");
        return data.path;
      },
      attach: (target: MessageTarget, url: string, replace?: string) => {
        grant("image-gen");
        return bridge.media(target, url, replace, false);
      },
      removeImage: (target: MessageTarget, url: string) => {
        grant("image-gen");
        return bridge.media(target, url, undefined, true);
      },
      inputMode: (target: MessageTarget) => {
        grant("image-gen");
        bridge.inputs.forEach((fn) => fn());
        bus.emit("image-input", target);
      },
      otherChats: async () => {
        const c = context(),
          current = c.getCurrentChatId();
        if (c.groupId)
          return (c.groups.find((g: Data) => g.id === c.groupId)?.chats || [])
            .filter((name: string) => name !== current)
            .reverse()
            .map((name: string) => ({ name }));
        const avatar = c.characters[c.characterId]?.avatar;
        if (!avatar) return [];
        // The listing reads only each file's first line, so one request carries every chat's metadata.
        const data = await (
          await host.request("/api/characters/chats", { avatar_url: avatar, metadata: true })
        ).json();
        if (data.error) throw new Error("读取聊天列表失败。");
        return host
          .sortChats(Object.values(data) as Data[])
          .map((chat) => ({
            name: String(chat.file_name).replace(/\.jsonl$/, ""),
            data: chat.chat_metadata?.workbench_addons?.[id],
          }))
          .filter((chat) => chat.name !== current && chat.data);
      },
      chatMetadata: async (name: string) => {
        const c = context(),
          character = c.characters[c.characterId];
        const lines = await (
          await host.request(
            c.groupId ? "/api/chats/group/get" : "/api/chats/get",
            c.groupId
              ? { id: name }
              : { ch_name: character?.name, file_name: name, avatar_url: character?.avatar },
          )
        ).json();
        const data = Array.isArray(lines) ? lines[0]?.chat_metadata?.workbench_addons?.[id] : undefined;
        return data ? copy(data) : undefined;
      },
      open,
      beforeClose: () => guards.check(),
    });
  }
  private media(target: MessageTarget, url: string, replace: string | undefined, remove: boolean) {
    return this.serial(async () => {
      await this.idle(target.chatKey);
      if (!this.valid(target)) return false;
      if (!url.startsWith("/user/images/")) throw new Error("仅可插入已保存的图片。");
      const c = context(),
        message = c.chat[target.id],
        extra = copy(message.extra || {});
      if (!Array.isArray(extra.media))
        extra.media = extra.image ? [{ type: "image", url: extra.image, title: extra.title || "" }] : [];
      extra.media = extra.media.filter(
        (m: Data) => !(m.wb_addon === "image-gen" && (m.url === replace || m.url === url)),
      );
      if (!remove) extra.media.push({ type: "image", url, title: "工作台生图", wb_addon: "image-gen" });
      extra.inline_image = true;
      extra.media_index = Math.max(0, extra.media.length - 1);
      const messages = copy(c.chat);
      messages[target.id].extra = extra;
      const swipe = message.swipe_id;
      if (Number.isInteger(swipe) && messages[target.id].swipe_info?.[swipe])
        messages[target.id].swipe_info[swipe].extra = copy(extra);
      await this.persist(target.chatKey, copy(c.chatMetadata), messages);
      await this.idle(target.chatKey);
      if (!this.valid(target)) return false;
      message.extra = extra;
      if (Number.isInteger(swipe) && message.swipe_info?.[swipe])
        message.swipe_info[swipe].extra = copy(extra);
      const element = document.querySelector(`.mes[mesid="${target.id}"]`);
      if (element) c.appendMediaToMessage(message, window.jQuery(element));
      this.host.updateMessage(target.id);
      return true;
    });
  }
  dispose() {
    this.disposed = true;
    this.idleCancels.forEach((cancel) => cancel());
    this.chatChanges.clear();
    this.completionTimers.forEach((timer) => clearTimeout(timer));
    this.completionTimers.clear();
    this.cleanup.forEach((fn) => fn());
    this.replies.clear();
    this.inputs.clear();
  }
}
