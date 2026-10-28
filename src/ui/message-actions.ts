import {
  ArrowDown,
  ArrowUp,
  Bookmark,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Eye,
  EyeOff,
  FileText,
  Flag,
  GitBranch,
  ImagePlus,
  Images,
  Languages,
  Lightbulb,
  Paperclip,
  PencilLine,
  Trash2,
  Volume2,
  WandSparkles,
  X,
} from "./icons";
import { nativeGlyphs } from "./NativeGlyph";

/** One description and native target per action, shared by reading, RP and phone menus. */
export const messageActions = {
  mes_edit: [PencilLine, "编辑消息", true],
  mes_edit_done: [Check, "保存编辑", true],
  mes_edit_cancel: [X, "取消编辑", false],
  mes_copy: [Copy, "复制消息", false],
  mes_translate: [Languages, "翻译消息", true],
  mes_narrate: [Volume2, "朗读消息", false],
  mes_prompt: [FileText, "查看提示词", false],
  mes_hide: [EyeOff, "从提示词中排除此消息", true],
  mes_unhide: [Eye, "将此消息加入提示词", true],
  mes_embed: [Paperclip, "附加文件或图片", true],
  mes_swipe_picker: [Bookmark, "查看候选历史", true],
  mes_create_bookmark: [Flag, "创建检查点", true],
  mes_bookmark: [Flag, "打开检查点对话", true],
  mes_create_branch: [GitBranch, "创建分支", true],
  mes_media_gallery: [Images, "切换媒体展示方式", false],
  mes_media_list: [Images, "切换媒体展示方式", false],
  sd_message_gen: [ImagePlus, "生成图片", true],
  "wb-image-message-button": [ImagePlus, "为此回复生图", true],
  "wb-image-insert-button": [Images, "在此回复后插入图片", true],
  mes_edit_copy: [Copy, "复制消息副本", true],
  mes_edit_add_reasoning: [Lightbulb, "添加思考块", true],
  mes_edit_up: [ArrowUp, "上移消息", true],
  mes_edit_down: [ArrowDown, "下移消息", true],
  mes_edit_delete: [Trash2, "删除消息", true],
  swipe_left: [ChevronLeft, "上一个候选", true],
  swipe_right: [ChevronRight, "下一个候选", true],
} as const;
export type MessageAction = keyof typeof messageActions;

export function messageControl(node: ParentNode | null | undefined, action: MessageAction) {
  return node?.querySelector<HTMLElement>("." + action) ?? null;
}
export function invokeMessageAction(node: ParentNode | null | undefined, action: MessageAction) {
  const control = messageControl(node, action);
  // ST binds copying to pointerup so dragging over the icon cannot copy by accident.
  if (action === "mes_copy")
    control?.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerType: "mouse", button: 0 }));
  else control?.click();
}
export function describeMessageAction(control: HTMLElement) {
  const known = (Object.keys(messageActions) as MessageAction[]).find((name) =>
    control.classList.contains(name),
  );
  if (known)
    return {
      id: known,
      icon: messageActions[known][0],
      label: messageActions[known][1],
      mutates: messageActions[known][2],
    };
  return {
    id: undefined,
    icon: [...control.classList].map((name) => nativeGlyphs[name]).find(Boolean) || WandSparkles,
    label: control.getAttribute("aria-label") || control.title || control.textContent?.trim() || "扩展操作",
    mutates: true,
  };
}
export function messageActionDisabled(control: HTMLElement | null, busy: boolean) {
  return (
    !control ||
    control.classList.contains("disabled") ||
    control.getAttribute("aria-disabled") === "true" ||
    control.matches(":disabled") ||
    (busy && describeMessageAction(control).mutates)
  );
}
export function messageMenuControls(node: HTMLElement, editing: boolean) {
  return [
    ...node.querySelectorAll<HTMLElement>(
      editing
        ? ".mes_edit_buttons > .menu_button:not(.mes_edit_done,.mes_edit_cancel)"
        : ".extraMesButtons > :is(.mes_button,button,[role=button]),.mes_buttons > :is(.mes_button,button,[role=button]):not(.mes_edit,.extraMesButtonsHint),.mes_buttons > .wb-image-slot .wb-image-message-button",
    ),
  ].filter((control) => !control.hidden && getComputedStyle(control).display !== "none");
}
