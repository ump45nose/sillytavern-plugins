import type { ContextLimit } from "./context-limit";
export type Resource = "connection" | "preset" | "world" | "persona";
export type Panel = Resource | "character" | "trace" | "export" | "outline" | "database" | "image-gen" | null;
export type SettingsPage =
  | "generation"
  | "connection"
  | "formatting"
  | "world"
  | "settings"
  | "background"
  | "extensions"
  | "persona"
  | "character"
  | "database";
export type Data = Record<string, any>;
export interface Item {
  id: string;
  name: string;
  detail?: string;
  active?: boolean;
  image?: string;
  data?: Data;
  /** The list group the user chose; "" when it has none. */
  group?: string;
  /** Hidden from the side rail, top choosers and "next"; listed under 已归档 in the manager. */
  archived?: boolean;
}
export interface Preferences {
  left: boolean;
  layout?: "novel" | "rp";
  rpTopAuto?: boolean;
  rpTextSize?: number;
  rpSpriteScale?: number;
  rpDialogWidth?: number;
  rpShowPortraits?: boolean;
  inputRatio?: number;
  presetPins?: string[];
  readingFont?: "serif" | "sans";
  readingSize?: number;
  readingLeading?: number;
  readingInset?: number;
  shortcuts?: Record<string, string>;
  shortcutsEnabled?: boolean;
  addons?: Record<string, boolean>;
  addonSettings?: Record<string, Data>;
  pinnedTools?: { id: string; label: string }[];
  userCollapsed?: boolean;
  messageMeta?: "hover" | "always" | "never";
  /** Workbench color scheme; "system" follows prefers-color-scheme (default light). */
  theme?: "light" | "dark" | "system";
  /** The instruction asking the model for story options; empty is the default one. */
  optionsPrompt?: string;
  /** Noval's story options card is folded to its title line. */
  optionsCollapsed?: boolean;
  /** Reveal a sidebar while the pointer rests at the window edge (default on). */
  edgeHover?: boolean;
  /** Markdown fields (composer, outline, long character / world / persona text) preview as you type (default on). */
  mdLive?: boolean;
  /** How many chat messages a generation sends (replaces Extension-MessageLimit). */
  contextLimit?: ContextLimit;
  /** Dialogue (quote) colors by `character:<avatar>` / `persona:<avatar>`; unset speakers follow the theme. */
  speakerColors?: Record<string, string>;
  bindings: Record<string, string>;
  /** Connection profile id → group name; profiles without one group by model. */
  groups: Record<string, string>;
  /** Placeholder variables by scope: a character's avatar file, `group:<id>`, or "default". */
  placeholders?: Record<string, { name: string; vars: Record<string, string> }>;
  /** World book name → group name (one group per book). */
  worldGroups?: Record<string, string>;
  /** Preset API id → preset name → group name. Names can repeat across APIs. */
  presetGroups?: Record<string, Record<string, string>>;
  /** Archived connection profile ids and world book names. */
  archived?: { connection?: string[]; world?: string[] };
}
/** One chat floor as the workbench lists it; the message body stays in SillyTavern's chat array. */
export interface MessageIndex {
  id: number;
  name: string;
  is_user: boolean;
  send_date?: string | number;
  hidden?: boolean;
  /** Plain text start of the message (tags stripped, whitespace collapsed), at most 120 characters. */
  preview: string;
}
export interface SessionState {
  chatName: string;
  groupId?: string;
  groupName?: string;
  character: Item | null;
  current: Record<Resource, string>;
  online: boolean;
  busy: boolean;
}
/** Host state split by how often it changes; each slice has its own version and subscribers. */
export interface Slices {
  session: SessionState;
  characters: Item[];
  resources: Record<Resource, Item[]>;
  chat: MessageIndex[];
  prefs: Preferences;
}
export type Slice = keyof Slices;
/** All slices at once, for callers that have not moved to useHostSlice. */
export interface HostSnapshot extends SessionState {
  characters: Item[];
  resources: Record<Resource, Item[]>;
  messages: MessageIndex[];
}
declare global {
  interface Window {
    SillyTavern: { getContext: () => any };
    jQuery: any;
    workbench: any;
    workbenchProbe: any;
    workbenchStartup?: any;
    storyWorkspace?: any;
  }
}
