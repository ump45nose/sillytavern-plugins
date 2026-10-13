export type Resource = "connection" | "preset" | "world" | "persona";
export type Panel = Resource | "character" | "trace" | "export" | "outline" | "image-gen" | null;
export type SettingsPage = "generation" | "connection" | "formatting" | "world" | "settings" | "background" | "extensions" | "persona" | "character";
export type Data = Record<string, any>;
export interface Item {
  id: string;
  name: string;
  detail?: string;
  active?: boolean;
  image?: string;
  data?: Data;
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
  bindings: Record<string, string>;
  groups: Record<string, string>;
}
export interface HostSnapshot {
  chatName: string;
  groupId?: string;
  groupName?: string;
  character: Item | null;
  characters: Item[];
  resources: Record<Resource, Item[]>;
  current: Record<Resource, string>;
  online: boolean;
  busy: boolean;
  messages: Data[];
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
