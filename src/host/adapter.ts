import { clone } from "./model";
import { assertContext, ctx, internal, nativeNodes } from "./internals";
import { ChatObserver, MediaObserver } from "./chat-observer";
import { CastRuntime } from "./cast-runtime";
import { OptionsRuntime } from "./options-runtime";
import { DatabaseRuntime } from "./database-runtime";
import { SyncRelay } from "./sync-relay";
import { PlaceholderRuntime } from "./placeholder-runtime";
import { guards, type Guard } from "./bus";
import { HostCore, defaults } from "./core";
import type { Slice } from "./types";
import { draftsMethods } from "./domains/drafts";
import { chatMethods } from "./domains/chat";
import { presetMethods } from "./domains/preset";
import { resourcesMethods } from "./domains/resources";
import { worldMethods } from "./domains/world";
import { characterMethods } from "./domains/character";
import { groupMethods } from "./domains/group";
import { extensionsMethods } from "./domains/extensions";
import { personaMethods } from "./domains/persona";
import { connectionMethods } from "./domains/connection";
import { nativeMethods } from "./domains/native";
import { organizeMethods } from "./domains/organize";
export { nativeNodes } from "./internals";

/** Domain methods are written with `this: HostAdapter`; the mixed-in surface drops that parameter. */
type Mixin<T> = { [K in keyof T]: OmitThisParameter<T[K]> };

/**
 * Facade over SillyTavern for the workbench UI. State and infrastructure live in HostCore, domain
 * behaviour in ./domains; callers keep using one object.
 */
export class HostAdapter extends HostCore {
  /** IDE sync through the workbench-sync server plug-in; idle when the plug-in is not loaded. */
  sync!: SyncRelay;
  /** `{@变量}` placeholders in the composer and `/inject`. */
  placeholders!: PlaceholderRuntime;
  async init() {
    this.generating = Boolean(ctx().streamingProcessor);
    [this.world, this.personas, this.openai] = await Promise.all([
      internal("world"),
      internal("personas"),
      internal("openai"),
    ]);
    assertContext();
    this.chatObserver = new ChatObserver(nativeNodes.chat!);
    this.media = new MediaObserver();
    this.cast = new CastRuntime(this);
    this.cleanup.push(
      this.cast.showTags(),
      () => this.chatObserver.disconnect(),
      () => this.media.disconnect(),
    );
    const c = ctx();
    // Which slices each SillyTavern event can change. Native selects all emit one of these, so
    // nothing listens for raw DOM change events.
    const resource: Slice[] = ["resources", "session"];
    const events: Record<string, Slice[]> = {
      // A chat switch can also move persona locks and bound connections.
      CHAT_CHANGED: ["characters", "chat", "resources"],
      CHAT_CREATED: ["session"],
      CHAT_RENAMED: ["session"],
      CHAT_DELETED: ["session"],
      GROUP_CHAT_CREATED: ["session"],
      GROUP_CHAT_DELETED: ["session"],
      GROUP_UPDATED: ["session"],
      MESSAGE_DELETED: ["chat"],
      CHARACTER_EDITED: ["characters"],
      CHARACTER_RENAMED: ["characters"],
      CHARACTER_DELETED: ["characters"],
      CHARACTER_SELECTED: ["characters"],
      MAIN_API_CHANGED: resource,
      OAI_PRESET_CHANGED_AFTER: resource,
      PRESET_CHANGED: resource,
      WORLDINFO_UPDATED: resource,
      WORLDINFO_SETTINGS_UPDATED: resource,
      PERSONA_CHANGED: resource,
      PERSONA_CREATED: resource,
      PERSONA_DELETED: resource,
      PERSONA_UPDATED: resource,
      CONNECTION_PROFILE_LOADED: resource,
      CONNECTION_PROFILE_CREATED: resource,
      CONNECTION_PROFILE_UPDATED: resource,
      CONNECTION_PROFILE_DELETED: resource,
      CHATCOMPLETION_MODEL_CHANGED: resource,
      CHATCOMPLETION_SOURCE_CHANGED: resource,
      ONLINE_STATUS_CHANGED: ["session"],
    };
    const chatList = [
      "CHAT_CHANGED",
      "CHAT_CREATED",
      "CHAT_RENAMED",
      "CHAT_DELETED",
      "GROUP_CHAT_CREATED",
      "GROUP_CHAT_DELETED",
    ];
    for (const [name, slices] of Object.entries(events))
      this.listen(name, () => {
        if (chatList.includes(name)) this.chatsVersion++;
        if (name === "WORLDINFO_UPDATED") this.resourceVersions.world++;
        if (name === "CHARACTER_EDITED") this.resourceVersions.character++;
        if (name === "PRESET_CHANGED" || name === "OAI_PRESET_CHANGED_AFTER") this.resourceVersions.preset++;
        if (name === "PERSONA_UPDATED") this.resourceVersions.persona++;
        if (name === "CONNECTION_PROFILE_UPDATED") this.resourceVersions.connection++;
        this.invalidate(...slices);
      });
    // Fired after every settings write, debounced ones included, which mostly change nothing shown:
    // rebuild what a write may have touched and notify only what changed. Settings never touch ctx().chat.
    this.listen("SETTINGS_UPDATED", () => this.revalidate("characters", "prefs", "session", "resources"));
    // These carry the floor id, so only that entry of the chat index is rebuilt.
    for (const name of [
      "MESSAGE_SENT",
      "MESSAGE_RECEIVED",
      "MESSAGE_UPDATED",
      "MESSAGE_EDITED",
      "MESSAGE_SWIPED",
    ])
      this.listen(name, (id: unknown) => this.updateMessage(Number(id)));
    this.listen("GENERATION_STARTED", (_type: any, _options: any, dry: boolean) => {
      if (!dry) {
        this.generating = true;
        this.invalidate("session");
      }
    });
    for (const name of ["GENERATION_ENDED", "GENERATION_STOPPED"])
      this.listen(name, () => {
        this.generating = false;
        this.invalidate("session");
      });

    for (const name of ["CONNECTION_PROFILE_LOADED", "CHATCOMPLETION_MODEL_CHANGED"])
      this.listen(name, () => {
        if (!this.busy && !this.resourceAction && !this.bindingRun)
          void this.applyBinding().catch((e) => this.report(e));
      });
    this.listen("CHAT_CHANGED", () => void this.cast.load());
    this.listen("WORLDINFO_UPDATED", (name: string) => {
      if (name === this.cast.state.config?.book) void this.cast.load();
    });
    void this.cast.load();
    this.database = new DatabaseRuntime(this);
    this.options = new OptionsRuntime(this);
    this.sync = new SyncRelay(this);
    this.cleanup.push(
      () => this.options.dispose(),
      () => this.database.dispose(),
      () => this.sync.dispose(),
    );
    // Same settings object as the host; this contains no connection credentials.
    c.extensionSettings.workbench ??= clone(defaults);
    // The context limit replaces Extension-MessageLimit: its setting comes over once.
    const messageLimit = c.extensionSettings.messageLimit;
    if (messageLimit && !c.extensionSettings.workbench.contextLimit) {
      c.extensionSettings.workbench.contextLimit = {
        enabled: !!messageLimit.enabled,
        limit: Number(messageLimit.limit) || 10,
        quiet: !!messageLimit.quietPrompts,
      };
      c.saveSettingsDebounced();
    }
    // Speaker colors replace Dialogue-Colorizer: its per-character / per-persona colors come over once.
    const colorizer = c.extensionSettings["SillyTavern-Dialogue-Colorizer"];
    if (colorizer && !c.extensionSettings.workbench.speakerColors) {
      const speakerColors: Record<string, string> = {};
      for (const [kind, settings] of [
        ["character", colorizer.charColorSettings],
        ["persona", colorizer.personaColorSettings],
      ])
        for (const [id, color] of Object.entries<string>(settings?.colorOverrides ?? {}))
          speakerColors[`${kind}:${id}`] = color;
      c.extensionSettings.workbench.speakerColors = speakerColors;
      c.saveSettingsDebounced();
    }
    this.placeholders = new PlaceholderRuntime(this);
    this.cleanup.push(() => this.placeholders.dispose());
    const guard: Guard = ({ preserveDrafts }) => {
      if (this.resourceAction) return false;
      if (preserveDrafts || !this.dirtyDraftKeys().length) return true;
      if (!confirm("有未保存的资源草稿，放弃这些修改？")) return false;
      return () => this.drafts.clear();
    };
    // Cached drafts outlive the editors that made them, so the host keeps its own unload hold.
    this.cleanup.push(
      guards.add(guard),
      guards.hold(() => this.resourceAction || this.dirtyDraftKeys().length > 0),
    );
    this.refresh();
    this.pruneOrganization();
  }
  destroy() {
    this.cleanup.forEach((fn) => fn());
    this.cleanup = [];
    this.listeners.clear();
  }
}
export interface HostAdapter
  extends Mixin<typeof draftsMethods>,
    Mixin<typeof chatMethods>,
    Mixin<typeof presetMethods>,
    Mixin<typeof resourcesMethods>,
    Mixin<typeof worldMethods>,
    Mixin<typeof characterMethods>,
    Mixin<typeof groupMethods>,
    Mixin<typeof extensionsMethods>,
    Mixin<typeof personaMethods>,
    Mixin<typeof connectionMethods>,
    Mixin<typeof nativeMethods>,
    Mixin<typeof organizeMethods> {}

// Non-enumerable, like methods declared in the class body.
for (const methods of [
  draftsMethods,
  chatMethods,
  presetMethods,
  resourcesMethods,
  worldMethods,
  characterMethods,
  groupMethods,
  extensionsMethods,
  personaMethods,
  connectionMethods,
  nativeMethods,
  organizeMethods,
])
  for (const [name, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(methods)))
    Object.defineProperty(HostAdapter.prototype, name, { ...descriptor, enumerable: false });
