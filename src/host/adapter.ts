import type { Data, HostSnapshot, Item, Preferences, Resource } from "./types";
import { clone, mergeBook, mergeEdits, validateBook, validatePreset } from "./model";
import { nativeMenuItems } from "./tools";
const load = (path: string): Promise<any> => import(/* @vite-ignore */ path);
const ctx = () => window.SillyTavern.getContext();
export const nativeNodes = {
  chat: document.getElementById("chat"),
  input: document.getElementById("send_textarea"),
};
const defaults: Preferences = { left: true, bindings: {}, groups: {} };
let generating = false;
export class HostAdapter {
  drafts = new Map<string, {base: Data; draft: Data; extra?: Data}>();
  private listeners = new Set<() => void>();
  private cleanup: (() => void)[] = [];
  resourceVersions = {
    world: 0,
    character: 0,
    preset: 0,
    persona: 0,
    connection: 0,
  };
  private version = 0;
  private cache: HostSnapshot | null = null;
  private world: any;
  private personas: any;
  private openai: any;
  private busy = false;
  resourceAction = false;
  chatsVersion = 0;
  private bindingRun = false;
  private suspendedDialogs: HTMLDialogElement[] = [];
  async init() {
    generating = Boolean(ctx().streamingProcessor);
    [this.world, this.personas, this.openai] = await Promise.all([
      load("/scripts/world-info.js"),
      load("/scripts/personas.js"),
      load("/scripts/openai.js"),
    ]);
    const c = ctx();
    for (const key of [
      "getPresetManager",
      "getWorldInfoNames",
      "getRequestHeaders",
      "selectCharacterById",
    ])
      if (typeof c[key] !== "function")
        throw new Error(`当前酒馆缺少 ${key}，请使用已验证的版本。`);
    const events = [
      "CHAT_CHANGED",
      "CHAT_RENAMED",
      "CHAT_DELETED",
      "GROUP_CHAT_DELETED",
      "MESSAGE_RECEIVED",
      "MESSAGE_SENT",
      "MESSAGE_UPDATED",
      "MESSAGE_DELETED",
      "CHARACTER_EDITED",
      "CHARACTER_DELETED",
      "CHARACTER_SELECTED",
      "SETTINGS_UPDATED",
      "OAI_PRESET_CHANGED_AFTER",
      "PRESET_CHANGED",
      "WORLDINFO_UPDATED",
      "WORLDINFO_SETTINGS_UPDATED",
      "PERSONA_CHANGED",
      "PERSONA_CREATED",
      "PERSONA_DELETED",
      "PERSONA_UPDATED",
      "CONNECTION_PROFILE_LOADED",
      "CONNECTION_PROFILE_CREATED",
      "CONNECTION_PROFILE_UPDATED",
      "CONNECTION_PROFILE_DELETED",
      "ONLINE_STATUS_CHANGED",
      "CHATCOMPLETION_MODEL_CHANGED",
      "CHATCOMPLETION_SOURCE_CHANGED",
    ];
    for (const name of events)
      this.listen(name, () => {
        if (["CHAT_CHANGED","CHAT_RENAMED","CHAT_DELETED","GROUP_CHAT_DELETED"].includes(name))this.chatsVersion++;
        if (name === "WORLDINFO_UPDATED") this.resourceVersions.world++;
        if (name === "CHARACTER_EDITED") this.resourceVersions.character++;
        if (name === "PRESET_CHANGED" || name === "OAI_PRESET_CHANGED_AFTER")
          this.resourceVersions.preset++;
        if (name === "PERSONA_UPDATED") this.resourceVersions.persona++;
        if (name === "CONNECTION_PROFILE_UPDATED")
          this.resourceVersions.connection++;
        this.refresh();
      });
    this.listen(
      "GENERATION_STARTED",
      (_type: any, _options: any, dry: boolean) => {
        if (!dry) {
          generating = true;
          this.refresh();
        }
      },
    );
    for (const name of ["GENERATION_ENDED", "GENERATION_STOPPED"])
      this.listen(name, () => {
        generating = false;
        this.refresh();
      });

    for (const name of [
      "CONNECTION_PROFILE_LOADED",
      "CHATCOMPLETION_MODEL_CHANGED",
    ])
      this.listen(name, () => {
        if (!this.busy && !this.resourceAction && !this.bindingRun)
          void this.applyBinding().catch((e) => this.report(e));
      });
    const handler = (e: Event) => {
      if (!(e.target as Element)?.closest?.("#wb-root")) this.refresh();
    };
    document.addEventListener("change", handler);
    this.cleanup.push(() => document.removeEventListener("change", handler));
    // Same settings object as the host; this contains no connection credentials.
    c.extensionSettings.workbench ??= clone(defaults);
    const guard=(e:Event)=>{
      if(this.resourceAction){e.preventDefault();return;}
      if((e as CustomEvent).detail?.preserveDrafts)return;
      if(this.dirtyDraftKeys().length){if(!confirm("有未保存的资源草稿，放弃这些修改？"))e.preventDefault();else this.drafts.clear();}
    };
    const unload=(e:BeforeUnloadEvent)=>{if(this.dirtyDraftKeys().length||this.resourceAction){e.preventDefault();e.returnValue="";}};
    window.addEventListener("wb-before-close",guard);window.addEventListener("beforeunload",unload);
    this.cleanup.push(()=>{window.removeEventListener("wb-before-close",guard);window.removeEventListener("beforeunload",unload);});
    this.refresh();
  }
  dirtyDraftKeys(){return [...this.drafts].filter(([,d])=>!!d.extra?.advanced||JSON.stringify(d.base)!==JSON.stringify(d.draft)||(d.extra?.tab==="json"&&d.extra.json!==JSON.stringify(d.draft,null,2))).map(([key])=>key);}
  async saveDrafts(){
    for(const key of this.dirtyDraftKeys()){
      const d=this.drafts.get(key)!;const colon=key.indexOf(":"),kind=key.slice(0,colon),id=key.slice(colon+1);let saved:Data;
      if(kind==="world")saved=await this.saveBook(id,d.base,d.extra?.tab==="json"?JSON.parse(d.extra.json):d.draft);
      else if(kind==="preset"){if(d.extra?.advanced)throw new Error("预设 JSON 无法解析，请先修正。");saved=await this.savePreset(id,d.base,d.draft);}
      else if(kind==="connection"){await this.saveProfile(id,d.base,d.draft);saved=clone(this.snapshot().resources.connection.find(r=>r.id===id)!.data!);}
      else if(kind==="persona")saved=await this.savePersona(id,d.base,d.draft);
      else if(kind==="group"){const groups=await this.saveGroup(id==="new"?null:d.base,d.draft);saved=groups.find((g:Data)=>id==="new"?g.name===d.draft.name:g.id===id);if(!saved)throw new Error("群组保存后无法读取。");}
      else if(kind==="group-overrides"){if(!d.extra)throw new Error("群聊草稿缺少绑定信息。");saved=await this.saveGroupOverrides(d.extra.groupId,d.extra.chatId,d.base,d.draft);}
      else if(kind==="character")saved=(await this.saveCharacter(id,d.base,d.draft)).data;
      else continue;
      this.drafts.set(key,{base:clone(saved),draft:clone(saved)});
    }
  }
  private listen(name: string, fn: (...args: any[]) => void) {
    const c = ctx(),
      event = c.eventTypes[name];
    if (event) {
      c.eventSource.on(event, fn);
      this.cleanup.push(() => c.eventSource.removeListener(event, fn));
    }
  }
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  revision = () => this.version;
  refresh = () => {
    this.cache = null;
    this.version++;
    this.listeners.forEach((fn) => fn());
  };
  report(error: unknown) {
    window.dispatchEvent(
      new CustomEvent("wb-error", {
        detail: error instanceof Error ? error.message : String(error),
      }),
    );
  }
  prefs(): Preferences {
    return { ...clone(defaults), ...ctx().extensionSettings.workbench };
  }
  preference(patch: Partial<Preferences>) {
    if (
      Object.entries(patch).every(
        ([k, v]) =>
          JSON.stringify(this.prefs()[k as keyof Preferences]) ===
          JSON.stringify(v),
      )
    )
      return;
    Object.assign(ctx().extensionSettings.workbench, patch);
    ctx().saveSettingsDebounced();
    this.refresh();
  }
  async persistSettings() {
    const c = ctx(),
      event = c.eventTypes.SETTINGS_UPDATED;
    let saved = false;
    const done = () => {
      saved = true;
    };
    c.eventSource.on(event, done);
    try {
      const script = await load("/script.js");
      await script.saveSettings();
      if (!saved) throw new Error("酒馆设置未确认保存，草稿已保留，请重试。");
    } finally {
      c.eventSource.removeListener(event, done);
    }
  }
  quickReplies() {
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
  }
  async request(path: string, body: Data) {
    const response = await fetch(path, {
      method: "POST",
      headers: ctx().getRequestHeaders(),
      body: JSON.stringify(body),
    });
    if (!response.ok)
      throw new Error(
        `保存或读取失败（HTTP ${response.status}），草稿已保留。`,
      );
    return response;
  }
  snapshot(): HostSnapshot {
    if (this.cache) return this.cache;
    const c = ctx(),
      manager = c.getPresetManager(),
      profiles = c.extensionSettings.connectionManager?.profiles ?? [];
    const characters: Item[] = c.characters.map((x: Data, i: number) => ({
      id: x.avatar,
      name: x.name,
      detail: (x.data?.tags ?? []).join(" · "),
      image: c.getThumbnailUrl("avatar", x.avatar),
      active:
        c.characterId !== undefined &&
        c.characterId !== null &&
        c.characterId !== "" &&
        i === Number(c.characterId),
      data: x,
    }));
    const personas = c.powerUserSettings.personas ?? {};
    const resources: Record<Resource, Item[]> = {
      connection: profiles
        .map((p: Data) => ({
          id: p.id,
          name: p.name,
          detail: this.prefs().groups[p.id] || p.model || p.api || "其他模型",
          data: p,
        }))
        .sort(
          (a: Item, b: Item) =>
            (a.detail ?? "").localeCompare(b.detail ?? "") ||
            a.name.localeCompare(b.name),
        ),
      preset: (manager?.getAllPresets() ?? []).map((name: string) => ({
        id: name,
        name,
        detail: c.mainApi,
      })),
      world: c
        .getWorldInfoNames()
        .map((name: string) => ({
          id: name,
          name,
          active: this.world?.selected_world_info.includes(name),
        })),
      persona: Object.entries(personas).map(([id, name]) => ({
        id,
        name: String(name),
        image: c.getThumbnailUrl("persona", id),
        detail: c.powerUserSettings.persona_descriptions?.[id]?.title ?? "",
      })),
    };
    return (this.cache = {
      chatName: String(c.chatId ?? "").replace(/\.jsonl$/, ""),
      groupId: c.groupId || undefined,
      groupName: c.groups?.find((g: Data) => g.id === c.groupId)?.name,
      character: characters.find((x) => x.active) ?? null,
      characters,
      resources,
      current: {
        connection:
          c.extensionSettings.connectionManager?.selectedProfile ?? "",
        preset: manager?.getSelectedPresetName() ?? "",
        world: this.world?.selected_world_info[0] ?? "",
        persona: this.personas?.user_avatar ?? "",
      },
      online: c.onlineStatus !== "no_connection",
      busy: this.busy || this.resourceAction || generating,
      messages: c.chat.map((m: Data, i: number) => ({
        id: i,
        name: m.name,
        text: m.mes,
        is_user: m.is_user,
        send_date: m.send_date,
      })),
    });
  }
  messageTime(value: string | number | undefined) {
    if(!value)return "";const time=ctx().timestampToMoment(value);return time?.isValid()?time.format("MM-DD HH:mm"):"";
  }
  rpPresentation(speaker?: string) {
    const c = ctx(), snap = this.snapshot();
    const actor = c.characters.find((item: Data) => item.name === speaker) ?? snap.character?.data;
    const holder = [...document.querySelectorAll<HTMLElement>(".expression-holder")].find(n => actor?.avatar && n.dataset.avatar === actor.avatar)
      ?? (snap.groupId ? null : document.getElementById("expression-holder"));
    const image = holder?.querySelector<HTMLImageElement>("img.expression[src]");
    const sprite = image?.getAttribute("src") || "";
    const characterSprite = !snap.groupId && typeof c.chatMetadata?.workbenchRP?.characterSprite === "string" ? c.chatMetadata.workbenchRP.characterSprite : "";
    const scene = c.chatMetadata?.workbenchRP?.scene;
    return {
      name: actor?.name || snap.groupName || "选择角色",
      portrait: actor?.avatar && actor.avatar !== "none" ? "/characters/" + encodeURIComponent(actor.avatar) : "",
      // Keep native expressions live; a chat-specific sprite fills in when none is available.
      // Native emoji fallbacks are icons, not full-size character artwork.
      sprite: sprite && !sprite.includes("/expressions/images/") ? sprite : characterSprite,
      userName: c.name1 || "你",
      userPortrait: snap.current.persona ? "/User%20Avatars/" + encodeURIComponent(snap.current.persona) : "",
      // A chat can supply a transparent user sprite without replacing its persona avatar.
      userSprite: typeof c.chatMetadata?.workbenchRP?.userSprite === "string" ? c.chatMetadata.workbenchRP.userSprite : "",
      scene: scene && typeof scene === "object" ? scene as Record<string, unknown> : {},
    };
  }
  isGenerating() { return generating; }
  model() {
    const c = ctx();
    return c.mainApi === "openai"
      ? c.getChatCompletionModel()
      : (c.textCompletionSettings?.model ?? c.mainApi);
  }
  bindingKey(kind: "connection" | "model") {
    return kind === "connection"
      ? `connection:${this.snapshot().current.connection}`
      : `model:${ctx().mainApi}:${this.model()}`;
  }
  async applyBinding() {
    if (this.bindingRun) return;
    const p = this.prefs(),
      name =
        p.bindings[this.bindingKey("connection")] ||
        p.bindings[this.bindingKey("model")];
    if (!name || ctx().getPresetManager().getSelectedPresetName()===name) return;
    const connection=this.connectionControls();
    this.bindingRun = true;
    try {
      await this.select("preset", name);
      // Bindings choose generation settings while keeping the chosen API/model.
      for(const control of [connection.main,connection.provider,connection.model]){if(!control)continue;const node=document.getElementById(control.id) as HTMLInputElement|HTMLSelectElement|null;if(node&&node.value!==control.value)this.setConnectionControl(control.id,control.value);}
    } finally {
      this.bindingRun = false;
    }
  }
  async select(kind: Resource, id: string) {
    if (this.snapshot().busy) throw new Error("请等待当前生成或切换完成。");
    this.busy = true;
    this.refresh();
    try {
      if (kind === "connection") {
        const select = document.querySelector<HTMLSelectElement>(
          "#connection_profiles",
        );
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
        if (value === undefined || value === null)
          throw new Error("当前 API 没有此预设。");
        await m.selectPreset(value);
      } else if (kind === "persona") {
        await this.personas.setUserAvatar(id);
      }
      // Worldbooks are multi-select: navigation never disables another book.
    } finally {
      this.busy = false;
      this.refresh();
    }
    if (kind === "connection") await this.applyBinding();
  }
  async toggleBook(name: string, on: boolean) {
    const select = window.jQuery("#world_info");
    const values = new Set<string>(this.world.selected_world_info);
    on ? values.add(name) : values.delete(name);
    select
      .val(
        [...values].map((value) =>
          String(this.world.world_names.indexOf(value)),
        ),
      )
      .trigger("change");
    this.refresh();
  }
  characterBooks() {
    const character = this.snapshot().character;
    if (!character) return [] as string[];
    const fileName = character.id.replace(/\.[^.]+$/, "");
    const primary = character.data?.data?.extensions?.world;
    return [...new Set<string>([primary, ...(this.world.world_info?.charLore?.find((x:Data)=>x.name===fileName)?.extraBooks || [])].filter(Boolean))];
  }
  async toggleCharacterBook(name:string,on:boolean) {
    const character=this.snapshot().character;
    if(!character)throw new Error("请先选择角色，再设置角色卡世界书。");
    const books=new Set(this.characterBooks());on?books.add(name):books.delete(name);
    const primary=character.data?.data?.extensions?.world;
    if(!on&&primary===name){const data=await this.characterData(character.id);await this.saveCharacter(character.id,data.data,{...data.data,extensions:{...data.data.extensions,world:""}});}
    this.world.charSetAuxWorlds(character.id.replace(/\.[^.]+$/, ""),[...books].filter(x=>x!==primary));
    await this.persistSettings();this.refresh();
  }
  async readBook(name: string) {
    const response = await this.request("/api/worldinfo/get", { name });
    return response.json();
  }
  async saveBook(name: string, base: Data, draft: Data) {
    const latest = await this.readBook(name),
      data = mergeBook(base, draft, latest);
    await this.request("/api/worldinfo/edit", { name, data });
    this.world.worldInfoCache.set(name, clone(data));
    await ctx().eventSource.emit(
      ctx().eventTypes.WORLDINFO_UPDATED,
      name,
      clone(data),
    );
    ctx().reloadWorldInfoEditor(name);
    this.refresh();
    return clone(data);
  }
  async createEntry(name: string, data: Data) {
    return this.world.createWorldInfoEntry(name, data);
  }
  async selectCharacter(id: string) {
    if (this.snapshot().busy) throw new Error("生成完成后再切换角色。");
    const index = ctx().characters.findIndex((x: Data) => x.avatar === id);
    if (index < 0) throw new Error("角色已不存在。");
    await ctx().selectCharacterById(index);
    this.refresh();
  }
  async createCharacter(name:string) {
    const form=new FormData();form.append("ch_name",name);form.append("description","");form.append("first_mes","");
    const headers={...ctx().getRequestHeaders()};delete headers["Content-Type"];
    const response=await fetch("/api/characters/create",{method:"POST",headers,body:form});
    if(!response.ok)throw new Error(`创建角色失败 (${response.status})`);
    const avatar=await response.text();await ctx().getCharacters();this.refresh();return avatar.replace(/^"|"$/g,"");
  }
  async importCharacter(file:File) {
    const form=new FormData();form.append("avatar",file);form.append("file_type",file.name.split(".").pop()||"");form.append("user_name",ctx().name1||"User");
    const headers={...ctx().getRequestHeaders()};delete headers["Content-Type"];
    const response=await fetch("/api/characters/import",{method:"POST",headers,body:form});
    if(!response.ok)throw new Error(`导入角色失败 (${response.status})`);const data=await response.json();if(data.error)throw new Error("角色文件无法解析。");await ctx().getCharacters();this.refresh();return data.file_name;
  }
  async characterAvatar(id:string,file:File){const form=new FormData();form.append("avatar",file);form.append("avatar_url",id);const headers={...ctx().getRequestHeaders()};delete headers["Content-Type"];const response=await fetch("/api/characters/edit-avatar",{method:"POST",headers,body:form});if(!response.ok)throw new Error(`头像保存失败 (${response.status})`);await ctx().getCharacters();this.refresh();}
  async duplicateCharacter(id:string){const data=await (await this.request("/api/characters/duplicate",{avatar_url:id})).json();await ctx().getCharacters();this.refresh();return data.path;}
  groups(){return clone(ctx().groups||[]);}
  async groupAvatar(file:File,id:string){const utils=await load("/scripts/utils.js"),image=await utils.createThumbnail(await utils.getBase64Async(file),300,300);return utils.saveBase64AsFile(image.replace(/^data:image\/[a-z]+;base64,/,""),id,"workbench-group-"+Date.now(),"jpg");}
  groupMedia(id:string){const p=ctx().powerUserSettings;return p.external_media_allowed_overrides.includes(id)?"allow":p.external_media_forbidden_overrides.includes(id)?"forbid":"global";}
  async setGroupMedia(id:string,value:string){const c=ctx(),p=c.powerUserSettings;p.external_media_allowed_overrides=p.external_media_allowed_overrides.filter((x:string)=>x!==id);p.external_media_forbidden_overrides=p.external_media_forbidden_overrides.filter((x:string)=>x!==id);if(value==="allow")p.external_media_allowed_overrides.push(id);if(value==="forbid")p.external_media_forbidden_overrides.push(id);await this.persistSettings();if(c.groupId===id)await c.reloadCurrentChat();this.refresh();}
  groupOverrides(){const m=ctx().chatMetadata;return {scenario:m.scenario||"",mes_example:m.mes_example||"",system_prompt:m.system_prompt||""};}
  groupChatId(){return String(ctx().chatId||"");}
  async saveGroupOverrides(id:string,chatId:string,base:Data,draft:Data){const c=ctx();if(String(c.groupId)!==id||String(c.chatId)!==chatId)throw new Error("当前群聊已切换，草稿仍保留。");if(this.snapshot().busy)throw new Error("请等待生成结束后保存。");const edited=mergeEdits(base,draft,this.groupOverrides()),metadata={...c.chatMetadata,...edited};await this.request("/api/chats/group/save",{id:chatId,chat:[{chat_metadata:metadata,user_name:"unused",character_name:"unused"},...c.chat],force:false});Object.assign(c.chatMetadata,edited);this.refresh();return edited;}
  async openGroup(id:string){if(this.snapshot().busy)throw new Error("生成完成后再切换群组。");await (await load("/scripts/group-chats.js")).openGroupById(id);this.refresh();}
  async saveGroup(base:Data|null,draft:Data){
    const module=await load("/scripts/group-chats.js");
    if(base){const latest=ctx().groups.find((g:Data)=>g.id===base.id);if(!latest)throw new Error("群组已不存在。");await this.request("/api/groups/edit",mergeEdits(base,draft,latest));}
    else {
      const cached=this.drafts.get("group:new"),created=cached?.extra?.createdId?ctx().groups.find((g:Data)=>g.id===cached.extra!.createdId):await (await this.request("/api/groups/create",draft)).json();
      if(!created)throw new Error("刚创建的群组已不存在，草稿仍保留。");
      if(cached)cached.extra={...cached.extra,createdId:created.id};
      // The official create endpoint only accepts its standard fields. Preserve
      // additional group preferences through its existing edit endpoint.
      try{await this.request("/api/groups/edit",{...created,...draft,id:created.id,chat_id:created.chat_id,chats:created.chats});}catch(e){await module.getGroups();this.refresh();throw e;}
    }
    await module.getGroups();this.refresh();return this.groups();
  }
  async deleteGroup(id:string){await this.request("/api/groups/delete",{id});const module=await load("/scripts/group-chats.js");if(ctx().groupId===id)await module.resetSelectedGroup();await module.getGroups();this.refresh();}
  async installedExtensions(){
    const extensions=await load("/scripts/extensions.js");
    return Promise.all(extensions.extensionNames.map(async(id:string)=>{let manifest:Data={};try{const response=await fetch(`/scripts/extensions/${id}/manifest.json`);if(response.ok)manifest=await response.json();}catch{}const key=id.split("/").at(-1)!.toLowerCase();const containers=[...document.querySelectorAll<HTMLElement>(".extension_container,#extensions_settings > div,#extensions_settings2 > div")];const container=containers.find(n=>n.id&&(n.id.toLowerCase().includes(key)||n.textContent?.toLowerCase().includes(String(manifest.display_name||key).toLowerCase())));return {id,name:manifest.display_name||key,version:manifest.version,description:manifest.description,enabled:!ctx().extensionSettings.disabledExtensions.includes(id),container:container?.id};}));
  }
  async toggleExtension(id:string,on:boolean){const module=await load("/scripts/extensions.js");await (on?module.enableExtension(id,false):module.disableExtension(id,false));this.refresh();}
  async extensionAction(id:string,action:"update"|"delete"){const module=await load("/scripts/extensions.js");if(!id.startsWith("third-party/"))throw new Error("内置扩展随酒馆版本更新。");if(action==="delete")await this.extensionHook(id,"delete");const response=await this.request(`/api/extensions/${action}`,{extensionName:id.replace(/^third-party\//,""),global:module.extensionTypes[id]==="global"});if(action==="delete")await this.persistSettings();const data=await response.json();if(action==="update"&&!data.isUpToDate)await this.extensionHook(id,"update");this.refresh();return data;}
  private async extensionHook(id:string,hook:string){const response=await fetch(`/scripts/extensions/${id}/manifest.json`);if(!response.ok)return;const manifest=await response.json();const method=manifest.hooks?.[hook];if(typeof method!=="string"||!manifest.js)return;const module=await load(`/scripts/extensions/${id}/${manifest.js}`);if(typeof module[method]==="function")await Promise.race([module[method](),new Promise(resolve=>setTimeout(resolve,5000))]);}
  async installExtension(url:string,branch:string,global:boolean){const module=await load("/scripts/extensions.js");if(!await module.installExtension(url,global,branch))throw new Error("扩展安装未完成。");this.refresh();}
  worldBindings(){return {chat:ctx().chatMetadata.world_info||"",persona:this.personaData(this.snapshot().current.persona)?.lorebook||"",character:this.snapshot().character?.data?.data?.extensions?.world||""};}
  async bindWorld(scope:"character"|"chat",name:string){if(scope==="chat"){ctx().chatMetadata.world_info=name;await ctx().saveMetadata();}else{const character=this.snapshot().character;if(!character)throw new Error("请先选择角色。");const data=await this.characterData(character.id);await this.saveCharacter(character.id,data.data,{...data.data,extensions:{...data.data.extensions,world:name}});}this.refresh();}
  async characterData(id: string) {
    const i = ctx().characters.findIndex((x: Data) => x.avatar === id);
    if (i < 0) throw new Error("角色已不存在。");
    const response = await this.request("/api/characters/get", {
      avatar_url: id,
    });
    return response.json();
  }
  async saveCharacter(id: string, base: Data, draft: Data) {
    const latest = await this.characterData(id),
      merged = mergeEdits(base, draft, latest.data ?? {});
    const patch: Data = {};
    for (const k of Object.keys(draft))
      if (JSON.stringify(base[k]) !== JSON.stringify(draft[k]))
        patch[k] = merged[k];
    if (Object.keys(patch).length) {
      await this.request("/api/characters/merge-attributes", {
        avatar: id,
        data: patch,
      });
      await ctx().getCharacters();
      await ctx().eventSource.emit(ctx().eventTypes.CHARACTER_EDITED);
    }
    this.refresh();
    return this.characterData(id);
  }
  async favorite(item: Item) {
    const c = await this.characterData(item.id),
      base = clone(c.data ?? {}),
      draft = clone(base);
    draft.extensions = { ...draft.extensions, fav: !draft.extensions?.fav };
    return this.saveCharacter(item.id, base, draft);
  }
  async exportCharacter(id: string) {
    const response = await this.request("/api/characters/export", {
      avatar_url: id,
      format: "png",
    });
    this.download(await response.blob(), id);
  }
  async deleteCharacters(ids: string[]) {
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
    this.refresh();
  }
  async tagCharacters(ids: string[], tag: string) {
    if (!ids.length || !tag.trim()) return;
    for (const id of ids) {
      const c = await this.characterData(id),
        base = clone(c.data ?? {});
      await this.saveCharacter(id, base, {
        ...base,
        tags: [...new Set([...(base.tags ?? []), tag.trim()])],
      });
    }
  }
  presetData(name: string) {
    const m = ctx().getPresetManager();
    const { presets, preset_names } = m.getPresetList();
    const i = Array.isArray(preset_names)
      ? preset_names.indexOf(name)
      : preset_names[name];
    if (i === undefined || i < 0) throw new Error("预设不存在");
    return clone(presets[i]);
  }
  async createPreset(name: string, data?: Data) {
    const manager = ctx().getPresetManager(); name = name.trim();
    if (!name || manager.getAllPresets().includes(name)) throw new Error("预设名称不能为空或重复");
    if (data) validatePreset(data);
    await manager.savePreset(name, data);
    this.refresh();
    return manager.getSelectedPresetName();
  }
  async deletePreset(name: string) {
    const manager = ctx().getPresetManager(), { presets, preset_names } = manager.getPresetList();
    const wasActive = manager.getSelectedPresetName() === name;
    const previousPresets = clone(presets), previousNames = clone(preset_names), previousSelection = manager.getSelectedPreset();
    const select = window.jQuery(manager.select), previousOptions = select.html();
    try { if (!await manager.deletePreset(name)) throw new Error("删除失败，已保留预设。"); }
    catch (error) {
      presets.splice(0, presets.length, ...previousPresets);
      if (Array.isArray(preset_names)) preset_names.splice(0, preset_names.length, ...previousNames);
      else { for (const key of Object.keys(preset_names)) delete preset_names[key]; Object.assign(preset_names, previousNames); }
      select.html(previousOptions); await manager.selectPreset(previousSelection); this.refresh(); throw error;
    }
    if (wasActive && manager.getAllPresets().length) await manager.selectPreset(manager.getSelectedPreset());
    this.refresh();
  }
  async savePreset(name: string, base: Data, draft: Data) {
    validatePreset(draft);
    const merged = mergeEdits(base, draft, this.presetData(name));
    await ctx().getPresetManager().savePreset(name, merged);
    this.refresh();
    return merged;
  }
  async saveProfile(id: string, base: Data, patch: Data) {
    const cm = ctx().extensionSettings.connectionManager,
      profile = cm.profiles.find((x: Data) => x.id === id);
    if (!profile) throw new Error("连接已删除。");
    patch.name = String(patch.name ?? "").trim();
    if (
      !patch.name ||
      cm.profiles.some((p: Data) => p.id !== id && p.name === patch.name)
    )
      throw new Error("连接名称不能为空或与其他连接重复。");
    const previous = clone(profile),
      next = mergeEdits(base, { ...base, ...patch }, profile);
    Object.assign(profile, next);
    try {
      await this.persistSettings();
    } catch (error) {
      for (const key of Object.keys(patch))
        if (profile[key] === next[key]) profile[key] = previous[key];
      this.refresh();
      throw error;
    }
    const option = [
      ...document.querySelectorAll<HTMLOptionElement>(
        "#connection_profiles option",
      ),
    ].find((x) => x.value === id);
    if (option) option.textContent = profile.name;
    await ctx().eventSource.emit(
      ctx().eventTypes.CONNECTION_PROFILE_UPDATED,
      profile,
    );
    this.refresh();
  }
  personaData(id: string) {
    const p = ctx().powerUserSettings;
    return clone({
      name: p.personas[id],
      ...(p.persona_descriptions[id] ?? {}),
    });
  }
  async savePersona(id: string, base: Data, draft: Data) {
    const merged = mergeEdits(base, draft, this.personaData(id)),
      p = ctx().powerUserSettings;
    const previousName = p.personas[id],
      previousDescription = p.persona_descriptions[id],
      current = id === this.personas.user_avatar;
    const script = await load("/script.js"),
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
      if (p.persona_descriptions[id] === description)
        p.persona_descriptions[id] = previousDescription;
      if (current) applyCurrent(p.personas[id], p.persona_descriptions[id]);
      this.refresh();
      throw error;
    }
    await this.personas.getUserAvatars();
    await ctx().eventSource.emit(ctx().eventTypes.PERSONA_UPDATED, id);
    this.refresh();
    return merged;
  }
  personaOptions(id: string) {
    const p = ctx().powerUserSettings, current = id === this.personas.user_avatar;
    return {
      current,
      locks: { default: p.default_persona === id, character: current && this.personas.isPersonaLocked("character"), chat: current && this.personas.isPersonaLocked("chat") },
      preferences: Object.fromEntries(["persona_show_notifications", "persona_allow_multi_connections", "persona_auto_lock"].map(k => [k, !!p[k]])),
    };
  }
  async personaLock(type: "default" | "character" | "chat", enabled: boolean) {
    await this.personas.setPersonaLockState(enabled, type);
    this.refresh();
  }
  async personaPreference(key: string, value: boolean) {
    if (!["persona_show_notifications", "persona_allow_multi_connections", "persona_auto_lock"].includes(key)) throw new Error("未知用户设定");
    const p = ctx().powerUserSettings, previous = p[key]; p[key] = value;
    try { await this.persistSettings(); } catch (e) { p[key] = previous; throw e; }
    const input = document.getElementById(key) as HTMLInputElement; if (input) input.checked = value;
    this.refresh();
  }
  leaseConnection(container: HTMLElement) {
    const node = document.getElementById("rm_api_block");
    if (!node) throw new Error("此版本未提供连接设置控件");
    const placeholder = document.createComment("Workbench connection panel origin");
    node.before(placeholder); node.classList.add("wb-native-embedded"); container.append(node);
    let restored = false;
    const restore = () => { if (restored) return; restored = true; node.classList.remove("wb-native-embedded"); placeholder.replaceWith(node); };
    this.cleanup.push(restore);
    return () => { restore(); this.cleanup = this.cleanup.filter(fn => fn !== restore); };
  }
  /** Only non-secret fields are mirrored into the quick API controls. */
  connectionControls() {
    const main = document.getElementById("main_api") as HTMLSelectElement;
    const api = main?.value || "openai";
    const provider = document.getElementById(api === "openai" ? "chat_completion_source" : "textgen_type") as HTMLSelectElement;
    const source = provider?.value || "";
    const control = (node: HTMLSelectElement | HTMLInputElement | null) => node ? {
      id: node.id, value:node.value, disabled:node.disabled,
      type:node instanceof HTMLSelectElement ? "select" : "text",
      options:node instanceof HTMLSelectElement ? [...node.options].map(o=>({value:o.value,label:o.textContent||o.value,disabled:o.disabled})) : [],
    } : null;
    let model: HTMLSelectElement | HTMLInputElement | null = null;
    const root = document.getElementById(api === "openai" ? "openai_api" : api === "textgenerationwebui" ? "textgenerationwebui_api" : "rm_api_block");
    if (api === "openai" && source === "custom") model = document.getElementById("custom_model_id") as HTMLInputElement;
    else if (api === "textgenerationwebui" && source === "generic") model = document.getElementById("generic_model_textgenerationwebui") as HTMLInputElement;
    else if (api === "novel") model = document.getElementById("model_novel_select") as HTMLSelectElement;
    else if (api === "openai" || api === "textgenerationwebui") {
      model = [...(root?.querySelectorAll<HTMLSelectElement>("select") || [])].find(n => {
        const scope = n.closest<HTMLElement>(api === "openai" ? "[data-source]" : "[data-tg-type]");
        return /^(model_.+_select|azure_openai_model|openrouter_model|mancer_model|vllm_model|aphrodite_model|llamacpp_model|ollama_model|tabby_model)$/.test(n.id) && !n.multiple && !!scope && (scope.dataset[api === "openai" ? "source" : "tgType"] || "").split(/,\s*/).includes(source);
      }) || null;
    }
    const connect = ({openai:"api_button_openai",textgenerationwebui:"api_button_textgenerationwebui",novel:"api_button_novel",kobold:"api_button",koboldhorde:"horde_api_key_button"} as Record<string,string>)[api];
    const loading=document.querySelector<HTMLElement>(`#${connect}`)?.parentElement?.querySelector<HTMLElement>(".api_loading");
    return { main:control(main)!, provider:api === "openai" || api === "textgenerationwebui" ? control(provider) : null, model:control(model), connect, test:api === "openai" ? "test_api_button" : null, connecting:!!loading&&getComputedStyle(loading).display!=="none" };
  }
  setConnectionControl(id: string, value: string) {
    const allowed = this.connectionControls();
    if (![allowed.main,allowed.provider,allowed.model].some(x=>x?.id===id)) throw new Error("当前连接不支持此字段");
    const node = document.getElementById(id) as HTMLSelectElement | HTMLInputElement;
    node.value = value;
    node.dispatchEvent(new Event("input",{bubbles:true}));
    node.dispatchEvent(new Event("change",{bubbles:true}));
    this.refresh();
  }
  watchConnectionControls(callback: () => void) {
    const node=document.getElementById("rm_api_block");if(!node)return()=>{};
    let frame=0;
    const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(callback);};
    const observer=new MutationObserver(schedule);
    observer.observe(node,{subtree:true,childList:true,attributes:true,attributeFilter:["style","disabled"]});
    node.addEventListener("change",schedule);node.addEventListener("input",schedule);
    return()=>{observer.disconnect();cancelAnimationFrame(frame);node.removeEventListener("change",schedule);node.removeEventListener("input",schedule);};
  }
  decorateConnectionControls() {
    const state=this.connectionControls(), marked:HTMLElement[]=[];
    for(const field of [state.main,state.provider,state.model]) {
      const node=field&&document.getElementById(field.id);if(!node)continue;
      const heading=node.previousElementSibling?.matches("h4") ? node.previousElementSibling : node.parentElement?.previousElementSibling?.matches("h4") ? node.parentElement.previousElementSibling : null;
      for(const target of [node,heading]) if(target instanceof HTMLElement&&!target.classList.contains("wb-connection-bridged")){target.classList.add("wb-connection-bridged");marked.push(target);}
    }
    const actions=document.querySelector<HTMLElement>(`#${state.connect}`)?.parentElement;
    if(actions&&actions.querySelector(".api_loading")&&!actions.classList.contains("wb-connection-actions-original")){actions.classList.add("wb-connection-actions-original");marked.push(actions);}
    const profiles=document.getElementById("connection_profiles")?.parentElement?.parentElement;
    if(profiles?.querySelector("#create_connection_profile")&&!profiles.classList.contains("wb-connection-profile-original")){profiles.classList.add("wb-connection-profile-original");marked.push(profiles);}
    return()=>marked.forEach(n=>n.classList.remove("wb-connection-bridged","wb-connection-actions-original","wb-connection-profile-original"));
  }
  traceComposition() {
    const manager = this.openai?.promptManager;
    if (!manager?.tokenHandler) return null;
    const counts = clone(manager.tokenHandler.getCounts());
    return { counts, total: manager.tokenHandler.getTotal(), limit: ctx().chatCompletionSettings.openai_max_context, source: "PromptManager token counts", historyIncludesInput: true };
  }
  async recentChats() {
    if (ctx().groupId) return this.sortChats(await (await load("/scripts/group-chats.js")).getGroupPastChats(ctx().groupId));
    const c = this.snapshot().character;
    if (!c) return [];
    const r = await this.request("/api/characters/chats", { avatar_url: c.id });
    const data = await r.json();
    return data.error ? [] : this.sortChats(Object.values(data) as Data[]);
  }
  private sortChats(chats: Data[]) {
    const date=(value:any)=>{if(!value)return 0;const time=typeof value==="number"?value:ctx().timestampToMoment(value)?.valueOf();return Number.isFinite(time)?time:0;};
    return chats.sort((a,b)=>date(b.last_mes)-date(a.last_mes));
  }
  async openChat(name: string) {
    if (this.snapshot().busy) throw new Error("请先停止生成，再切换对话。");
    const script = await load("/script.js");
    await script.saveChatConditional();
    if (ctx().groupId) await (await load("/scripts/group-chats.js")).openGroupChat(ctx().groupId, name.replace(/\.jsonl$/, ""));
    else await ctx().openCharacterChat(name.replace(/\.jsonl$/, ""));
    this.refresh();
  }
  async jump(id: number) {
    const selector = `#chat .mes[mesid="${id}"]`;
    let node = document.querySelector(selector);
    for (let i = 0; !node && i < 50; i++) {
      const button = document.querySelector<HTMLElement>("#show_more_messages");
      if (!button) break;
      button.click();
      await new Promise((r) => setTimeout(r, 20));
      node = document.querySelector(selector);
    }
    if (this.prefs().layout === "rp" && !document.body.classList.contains("wb-mobile")) {
      window.dispatchEvent(new CustomEvent("wb-rp-jump", { detail: id }));
      return;
    }
    node?.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion:reduce)").matches||document.body.classList.contains("reduced-motion")?"auto":"smooth" });
  }
  click(selector: string) {
    const nodes = [...document.querySelectorAll<HTMLElement>(selector)];
    const element = nodes.find(n => !n.classList.contains("displayNone") && getComputedStyle(n).display !== "none") ?? nodes[0];
    if (!element) throw new Error("当前酒馆未提供此入口。");
    element.click();
  }
  setInput(text: string) {
    const node = nativeNodes.input as HTMLTextAreaElement;
    node.value = text; node.dispatchEvent(new Event("input", {bubbles:true})); node.focus(); node.setSelectionRange(text.length,text.length);
  }
  menuItems(kind: "menu" | "tools") {
    return nativeMenuItems(kind);
  }
  async renameChat(name: string, next: string) { if(this.snapshot().busy)throw new Error("生成中不能重命名聊天。");await ctx().renameChat(name.replace(/\.jsonl$/,""),next.trim().replace(/\.jsonl$/,""));this.refresh(); }
  async newChat() {if(this.snapshot().busy)throw new Error("请先停止生成。");const script=await load("/script.js");await script.saveChatConditional();await script.doNewChat();this.refresh();}
  async deleteChat(name:string) {
    if(this.snapshot().busy)throw new Error("请先停止生成。");
    const file=name.replace(/\.jsonl$/,""),c=ctx(),script=await load("/script.js");
    await script.saveChatConditional();
    if(c.groupId){
      const module=await load("/scripts/group-chats.js"),group=c.groups.find((g:Data)=>g.id===c.groupId);
      if(!group?.chats.includes(file))throw new Error("群聊文件已不存在。");
      await this.request("/api/chats/group/delete",{id:file});group.chats=group.chats.filter((id:string)=>id!==file);
      if(group.chat_id===file){if(group.chats.length)await module.openGroupChat(c.groupId,group.chats.at(-1));else await module.createNewGroupChat(c.groupId);}
      await module.editGroup(c.groupId,true,true);await c.eventSource.emit(c.eventTypes.GROUP_CHAT_DELETED,file);
    }
    else{const character=this.snapshot().character;if(!character)throw new Error("请先选择角色。");await this.request("/api/chats/delete",{avatar_url:character.id,chatfile:file+".jsonl"});if(this.snapshot().chatName===file)await script.replaceCurrentChat();await c.eventSource.emit(c.eventTypes.CHAT_DELETED,file);}
    this.refresh();
  }
  async importChat(file:File) {
    if(this.snapshot().busy)throw new Error("请先停止生成。");
    const c=ctx(),format=file.name.split(".").pop()?.toLowerCase();
    if(!["json","jsonl"].includes(format||""))throw new Error("请选择 JSON 或 JSONL 聊天文件。");
    if(c.groupId&&format!=="jsonl")throw new Error("群聊仅支持酒馆原生 JSONL 格式。");
    if(!c.groupId&&!this.snapshot().character)throw new Error("请先选择角色。");
    const form=new FormData();form.append("user_name",c.name1||"User");form.append("avatar_url",this.snapshot().character?.id||"");form.append("character_name",this.snapshot().character?.name||"");form.append("file_type",format!);form.append("avatar",file);
    const imported=c.groupId?await (await load("/scripts/group-chats.js")).importGroupChat(form):await (await load("/script.js")).importCharacterChat(form);if(!imported?.length)throw new Error("导入未成功，请检查文件格式和服务连接。");this.chatsVersion++;this.refresh();
  }
  async exportChat(name: string) {
    const script=await load("/script.js");await script.saveChatConditional();
    const data=await (await this.request("/api/chats/export",{is_group:!!ctx().groupId,avatar_url:this.snapshot().character?.id,file:name.replace(/\.jsonl$/,"")+".jsonl",exportfilename:name,format:"jsonl"})).json();
    if(typeof data.result!=="string")throw new Error("聊天导出未返回内容。");this.download(new Blob([data.result],{type:"application/jsonl"}),name.replace(/\.jsonl$/,"")+".jsonl");
  }
  exportSnapshot() {
    const c = ctx();
    return { key: `${c.groupId || this.snapshot().character?.id || ""}:${c.getCurrentChatId() || ""}`, timestamp: Date.now(),
      messages: c.chat.map((message: Data, id: number) => ({ id, name: String(message.name || ""), text: String(message.mes || ""), role: message.is_system ? "system" as const : message.is_user ? "user" as const : "assistant" as const })) };
  }
  /** Lease original controls with their handlers intact; every lease restores its exact origin. */
  leaseNative(id: string, container: HTMLElement) {
    const node=document.getElementById(id);if(!node)throw new Error(`酒馆未提供 ${id} 控件。`);
    if(node.closest(".wb-native-settings-slot,.wb-native-slot"))throw new Error("此设置已在其他编辑区打开。");
    const placeholder=document.createComment("Workbench native settings origin");node.before(placeholder);container.append(node);node.classList.add("wb-native-embedded");
    let restored=false;const restore=()=>{if(restored)return;restored=true;node.classList.remove("wb-native-embedded");placeholder.replaceWith(node);};this.cleanup.push(restore);
    return()=>{restore();this.cleanup=this.cleanup.filter(fn=>fn!==restore);};
  }
  async batchResource(kind: "preset" | "connection" | "world", ids: string[], action: "copy" | "delete" | "export") {
    if(this.snapshot().busy)throw new Error("请等待生成或切换完成。");
    const connection=this.connectionControls();
    const done:string[]=[],created:string[]=[],errors:{id:string;message:string}[]=[],originalPreset=ctx().getPresetManager().getSelectedPresetName(),exports:{name:string;data:Data}[]=[];
    this.resourceAction=true;this.refresh();
    try{
    for(const id of [...new Set(ids)])try {
      const item=this.snapshot().resources[kind].find(r=>r.id===id);if(!item)throw new Error("资源已不存在。");
      const cache=this.drafts.get(kind+":"+id);
      if(cache?.extra?.advanced&&action!=="delete")throw new Error("预设 JSON 草稿无法解析，请先修正。");
      const data=cache&&action!=="delete"?(cache.extra?.tab==="json"?JSON.parse(cache.extra.json):clone(cache.draft)):kind==="preset"?this.presetData(id):kind==="world"?await this.readBook(id):clone(item.data!);
      if(action==="export"){exports.push({name:item.name,data});}
      else if(kind==="world"){
        if(action==="delete"){if(!await this.world.deleteWorldInfo(id))throw new Error("世界书删除失败。");}
        else{const name=this.copyName(kind,item.name);await this.createResource("world",name,data);created.push(name);}
        this.resourceVersions.world++;
      }else if(kind==="preset"){
        if(action==="delete")await this.deletePreset(id);else{const name=this.copyName(kind,item.name);await ctx().getPresetManager().savePreset(name,data);created.push(name);}
        this.resourceVersions.preset++;
      }else{
        const c=ctx(),cm=c.extensionSettings.connectionManager,previous=clone(cm),select=document.getElementById("connection_profiles") as HTMLSelectElement;
        let copy:Data|undefined;
        if(action==="delete"){cm.profiles=cm.profiles.filter((p:Data)=>p.id!==id);if(cm.selectedProfile===id)cm.selectedProfile=null;}
        else{copy={...data,id:ctx().uuidv4(),name:this.copyName(kind,item.name)};cm.profiles.push(copy);}
        try{await this.persistSettings();}catch(e){Object.assign(cm,previous);throw e;}
        if(action==="delete"){[...select.options].find(o=>o.value===id)?.remove();if(previous.selectedProfile===id){select.value="";select.dispatchEvent(new Event("change",{bubbles:true}));}}
        else{select.add(new Option(copy!.name,copy!.id));created.push(copy!.id);}
        await c.eventSource.emit(c.eventTypes[action==="delete"?"CONNECTION_PROFILE_DELETED":"CONNECTION_PROFILE_CREATED"],action==="delete"?data:copy);
        this.resourceVersions.connection++;
      }
      if(action==="delete")this.drafts.delete(kind+":"+id);done.push(id);this.refresh();
    }catch(e){errors.push({id,message:e instanceof Error?e.message:String(e)});}
    if(kind==="preset"&&action==="copy"){
      const manager=ctx().getPresetManager();if(manager.getAllPresets().includes(originalPreset))await manager.selectPreset(manager.findPreset(originalPreset));
      for(const control of [connection.main,connection.provider,connection.model]){if(!control)continue;const node=document.getElementById(control.id) as HTMLInputElement|HTMLSelectElement|null;if(node&&node.value!==control.value)this.setConnectionControl(control.id,control.value);}
    }
    if(exports.length===1)this.download(new Blob([JSON.stringify(exports[0].data,null,2)],{type:"application/json"}),exports[0].name+".json");
    else if(exports.length>1){
      const {zipSync,strToU8}=await import("fflate"),files:Record<string,Uint8Array>={};
      exports.forEach((item,i)=>{files[`${i+1}-${item.name.replace(/[\\/:]/g,"_")}.json`]=strToU8(JSON.stringify(item.data,null,2));});
      this.download(new Blob([new Uint8Array(zipSync(files,{level:0}))],{type:"application/zip"}),`Workbench-${kind}.zip`);
    }
    return {done,created,errors};
    }finally{this.resourceAction=false;this.refresh();}
  }
  async createResource(kind:"preset"|"connection"|"world",name:string,data?:Data){
    name=name.trim();if(!name||this.snapshot().resources[kind].some(r=>r.name===name))throw new Error("名称不能为空或重复。");
    if(kind==="world"){const book=data??{entries:{}};validateBook(book);await this.request("/api/worldinfo/edit",{name,data:book});this.world.worldInfoCache.set(name,clone(book));await this.world.updateWorldInfoList();await ctx().eventSource.emit(ctx().eventTypes.WORLDINFO_UPDATED,name,clone(book));this.resourceVersions.world++;this.refresh();return name;}
    if(kind==="preset")return this.createPreset(name,data);
    throw new Error("连接请使用原生新建配置控件。");
  }
  private copyName(kind: Resource,name:string) {const names=new Set(this.snapshot().resources[kind].map(r=>r.name));let next=name+" · 副本",i=2;while(names.has(next))next=name+" · 副本 "+i++;return next;}
  native(kind: string) {
    this.suspendedDialogs = [
      ...document.querySelectorAll<HTMLDialogElement>(".wb-dialog[open],.wb-settings-workspace[open]"),
    ];
    this.suspendedDialogs.forEach((d) => d.close());
    document.body.classList.add("wb-native-panel");
    const selectors: Record<string, string> = {
      connection: "#rm_api_block .drawer-toggle",
      preset: "#left-nav-panel .drawer-toggle",
      world: "#WI-SP-button .drawer-toggle",
      persona: "#persona-management-button .drawer-toggle",
      character: "#rightNavDrawerIcon",
      settings: "#user-settings-button .drawer-icon",
      quickreply: "#extensions-settings-button .drawer-icon",
      formatting: "#advanced-formatting-button .drawer-icon",
      background: "#backgrounds-button .drawer-icon",
      extensions: "#extensions-settings-button .drawer-icon",
    };
    // Drawer container names differ from the contents; selectors are isolated here.
    const fallback: Record<string, string> = {
      connection: "#API-status-top",
      preset: "#leftNavDrawerIcon",
      world: "#WIDrawerIcon",
      persona: "#persona-management-button .drawer-icon",
    };
    let el =
      document.querySelector<HTMLElement>(
        selectors[kind] ?? selectors.settings,
      ) ?? document.querySelector<HTMLElement>(fallback[kind]);
    if (!el) throw new Error("原生面板不可用，请返回原界面。");
    if (!el.classList.contains("openIcon")) el.click();
  }
  closeNative() {
    document
      .querySelectorAll<HTMLElement>(
        "#top-settings-holder .drawer-icon.openIcon",
      )
      .forEach((x) => x.click());
    document.body.classList.remove("wb-native-panel");
    this.suspendedDialogs
      .filter((d) => d.isConnected)
      .forEach((d) => d.showModal());
    this.suspendedDialogs = [];
  }
  download(blob: Blob, name: string) {
    const url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  destroy() {
    this.cleanup.forEach((fn) => fn());
    this.cleanup = [];
    this.listeners.clear();
    this.closeNative();
  }
}
