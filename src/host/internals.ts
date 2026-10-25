/**
 * The only module that reaches into SillyTavern internals: the public context plus the
 * non-public script modules the workbench depends on. Every export we use is listed here and
 * checked when the module is first loaded, so an incompatible SillyTavern version fails with a
 * named missing export instead of an undefined call deep inside a feature.
 */
const load = (path: string): Promise<any> => import(/* @vite-ignore */ path);

export const ctx = () => window.SillyTavern.getContext();

export const nativeNodes = {
  chat: document.getElementById("chat"),
  input: document.getElementById("send_textarea"),
};

const modules = {
  script: [
    "/script.js",
    [
      "saveSettings",
      "setUserName",
      "saveChatConditional",
      "doNewChat",
      "replaceCurrentChat",
      "importCharacterChat",
    ],
  ],
  world: [
    "/scripts/world-info.js",
    [
      "selected_world_info",
      "world_names",
      "world_info",
      "charSetAuxWorlds",
      "worldInfoCache",
      "createWorldInfoEntry",
      "deleteWorldInfo",
      "updateWorldInfoList",
    ],
  ],
  personas: [
    "/scripts/personas.js",
    [
      "user_avatar",
      "setUserAvatar",
      "setPersonaDescription",
      "getUserAvatars",
      "isPersonaLocked",
      "setPersonaLockState",
    ],
  ],
  openai: ["/scripts/openai.js", ["promptManager"]],
  groupChats: [
    "/scripts/group-chats.js",
    [
      "openGroupById",
      "getGroups",
      "resetSelectedGroup",
      "getGroupPastChats",
      "openGroupChat",
      "createNewGroupChat",
      "editGroup",
      "importGroupChat",
    ],
  ],
  extensions: [
    "/scripts/extensions.js",
    ["extensionNames", "enableExtension", "disableExtension", "extensionTypes", "installExtension"],
  ],
  utils: ["/scripts/utils.js", ["createThumbnail", "getBase64Async", "saveBase64AsFile"]],
  shared: ["/scripts/extensions/shared.js", ["ConnectionManagerRequestService"]],
} as const;
type Name = keyof typeof modules;

const loaded = new Map<Name, Promise<any>>();
/** Loads a SillyTavern script module once and verifies the exports the workbench relies on. */
export function internal(name: Name): Promise<any> {
  let pending = loaded.get(name);
  if (!pending) {
    const [path, exports] = modules[name];
    pending = load(path).then((module) => {
      const missing = exports.filter((key) => !(key in module));
      if (missing.length)
        throw new Error(`当前酒馆的 ${path} 缺少 ${missing.join("、")}，请使用已验证的版本。`);
      return module;
    });
    // A failed request (e.g. offline PWA) must be retryable.
    pending.catch(() => loaded.delete(name));
    loaded.set(name, pending);
  }
  return pending;
}

/** Context functions the workbench cannot run without. */
export function assertContext() {
  const c = ctx();
  for (const key of [
    "getPresetManager",
    "getWorldInfoNames",
    "getRequestHeaders",
    "selectCharacterById",
    "updateMessageBlock",
  ])
    if (typeof c[key] !== "function") throw new Error(`当前酒馆缺少 ${key}，请使用已验证的版本。`);
  if (typeof c.messageFormatter?.addHook !== "function")
    throw new Error("当前酒馆缺少 messageFormatter，请使用已验证的版本。");
}

/** Third-party extension modules are loaded by path; they are not part of the checked surface. */
export const loadExtensionModule = (path: string) => load(path);
