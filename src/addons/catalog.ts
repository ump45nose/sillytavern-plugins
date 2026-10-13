import type { Preferences } from "../host/types";
/** Metadata only: importing the catalog never imports a feature or fetches its manifest. */
export const addons = [{
  id: "record-export", label: "记录导出", version: "1.0.0", toolId: "wb:export",
  description: "在右栏分析聊天 XML，按标签保留或排除内容，预览并下载 TXT / Markdown。",
}, {
  id: "outline", label: "大纲", version: "1.0.0", toolId: "wb:outline",
  description: "左栏大纲树、Markdown 编辑、节点进度与多轮自动写作。",
}, {
  id: "image-gen", label: "生图", version: "1.0.0", toolId: "wb:image-gen",
  description: "正文铅笔旁手动生图、独立提示词转写及每隔数轮自动插图。",
}] as const;
export type AddonId = typeof addons[number]["id"];
export function addonEnabled(prefs: Pick<Preferences, "addons">, id: AddonId) {
  return prefs.addons?.[id] !== false;
}
