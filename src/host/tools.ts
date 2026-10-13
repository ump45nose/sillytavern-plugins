/** Stable identities for native menu entries; never persist a menu position. */
export interface PinnedTool { id: string; label: string }
export interface NativeTool extends PinnedTool { node: HTMLElement; disabled: boolean; pinnable: boolean }
export const exportTool: PinnedTool = { id: "wb:export", label: "记录导出" };
const names: Record<string, string> = {
  option_toggle_AN: "作者注释", option_toggle_CFG: "CFG 引导", option_toggle_logprobs: "Token 概率",
  option_new_bookmark: "保存检查点", option_back_to_main: "返回父对话",
  manageAttachments: "数据银行", sd_gen: "生成图片", send_picture: "图片描述",
  show_gallery_wand_button: "图片画廊", ttsExtensionNarrateAll: "朗读聊天",
  token_counter: "Token 计数", translate_chat: "翻译聊天", translate_input_message: "翻译输入", attachFile: "附件",
};
const excluded = new Set(["option_start_new_chat", "option_select_chat", "option_convert_to_group", "option_close_chat", "option_delete_mes", "option_impersonate", "option_regenerate", "option_continue", "option_settings"]);
export function nativeMenuItems(kind: "menu" | "tools"): NativeTool[] {
  const source = document.querySelector(kind === "menu" ? "#options .options-content" : "#extensionsMenu");
  const selector = kind === "menu" ? "a,button" : ".list-group-item,.menu_button,a,button";
  const nodes = [...(source?.querySelectorAll<HTMLElement>(selector) || [])].filter(node =>
    !excluded.has(node.id) && !node.classList.contains("displayNone") && getComputedStyle(node).display !== "none" &&
    (kind === "menu" || !node.parentElement?.closest(selector)));
  const items = nodes.map(node => {
    const originalLabel = (node.textContent?.trim() || node.title || "扩展工具").replace(/\s+/g, " ");
    // Anonymous helper entries have no DOM ID. A unique original label is stable across reordering.
    const identity = node.id || node.getAttribute("data-action") || node.getAttribute("data-command");
    return { id: identity ? `native:${kind}:${identity}` : `label:${kind}:${originalLabel}`, label: names[node.id] || originalLabel,
      node, disabled: node.matches(":disabled,.disabled,[aria-disabled=true]"), pinnable: true };
  });
  const counts = new Map<string, number>();
  items.forEach(item => counts.set(item.id, (counts.get(item.id) || 0) + 1));
  return items.map(item => ({ ...item, pinnable: counts.get(item.id) === 1 }));
}
export function pinnedTools(value: unknown): PinnedTool[] {
  if (!Array.isArray(value)) return [exportTool];
  const seen = new Set<string>();
  return value.filter((item): item is PinnedTool => !!item && typeof item.id === "string" && typeof item.label === "string" && !seen.has(item.id) && !!seen.add(item.id))
    .map(({ id, label }) => ({ id, label }));
}
export function resolveTool(id: string): NativeTool | undefined {
  const matches = [...nativeMenuItems("menu"), ...nativeMenuItems("tools")].filter(item => item.id === id);
  return matches.length === 1 && matches[0].pinnable ? matches[0] : undefined;
}
