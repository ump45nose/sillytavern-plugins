import type { Panel, Resource, SettingsPage } from "./types";

/**
 * The workbench's terms, in SillyTavern's own words. Names of resources, panels, settings pages
 * and actions come from here, so a rename happens in one place. Logic keys on ids, never on text.
 */
export const resourceLabels: Record<Resource, string> = {
  connection: "连接",
  preset: "预设",
  world: "世界书",
  persona: "用户设定",
};

export const panelLabels: Record<NonNullable<Panel>, string> = {
  character: "角色",
  ...resourceLabels,
  trace: "Trace",
  export: "记录导出",
  outline: "大纲",
  database: "数据库",
  "image-gen": "生图",
};

export const settingsLabels: Record<SettingsPage, string> = {
  generation: "预设",
  connection: "连接",
  formatting: "回复格式",
  world: "世界书",
  settings: "用户设置",
  background: "背景",
  extensions: "扩展",
  persona: "用户设定",
  character: "角色管理",
  database: "数据库",
};

export const actionLabels = {
  continue: "续写",
  regenerate: "重新生成",
  impersonate: "AI 帮答",
  /** A saved connection (SillyTavern's Connection Profile). */
  connectionProfile: "连接配置",
  updatePreset: "更新预设",
  updateConnectionProfile: "更新连接配置",
} as const;
