/** Shared action identities for buttons, keyboard bindings and later mobile layouts. */
export class Operations {
  private handlers = new Map<string, () => unknown>();
  register(id: string, handler: () => unknown) {
    this.handlers.set(id, handler);
    return () => this.handlers.delete(id);
  }
  run(id: string) {
    const handler = this.handlers.get(id);
    if (!handler) throw new Error(`操作不可用：${id}`);
    return handler();
  }
  clear() {
    this.handlers.clear();
  }
}
export const shortcutActions = [
  { id: "outline.editor", label: "完整大纲编辑", binding: "" },
  { id: "open.outline", label: "打开大纲工作区", binding: "Alt+Shift+KeyO" },
  { id: "outline.insert", label: "插入当前大纲节点", binding: "Alt+Shift+KeyI" },
  { id: "outline.pause", label: "暂停／继续自动写作", binding: "Alt+Shift+KeyP" },
  { id: "open.image-gen", label: "打开生图工作区", binding: "Alt+Shift+KeyG" },
  { id: "open.connection", label: "打开连接", binding: "Alt+Shift+Digit1" },
  { id: "open.preset", label: "打开预设", binding: "Alt+Shift+Digit2" },
  { id: "open.world", label: "打开世界书", binding: "Alt+Shift+Digit3" },
  { id: "open.persona", label: "打开用户设定", binding: "Alt+Shift+Digit4" },
  { id: "open.character", label: "打开角色侧栏", binding: "" },
  { id: "open.trace", label: "打开 Trace", binding: "Alt+Shift+KeyT" },
  { id: "toggle.left", label: "展开／收纳左栏", binding: "Alt+Shift+KeyL" },
  { id: "toggle.focus", label: "进入／退出专注", binding: "Alt+Shift+KeyF" },
  { id: "next.connection", label: "切换下一个连接", binding: "Alt+Shift+KeyN" },
] as const;

type KeyEvent = Pick<KeyboardEvent, "code" | "ctrlKey" | "altKey" | "shiftKey" | "metaKey">;
const codePattern = /^(Key[A-Z]|Digit[0-9]|F([1-9]|1[0-9]|2[0-4])|Arrow(Up|Down|Left|Right)|PageUp|PageDown|Home|End|Space|Enter|Backspace|Delete|Tab|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash|Minus|Equal|Backquote|Numpad([0-9]|Add|Subtract|Multiply|Divide|Decimal|Enter))$/;
export function bindingFromEvent(e: KeyEvent) {
  if (!codePattern.test(e.code)) return "";
  return [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Meta", e.code].filter(Boolean).join("+");
}
/** Preserve browser navigation, native send/formatting, and ordinary typing. */
export function bindingError(binding: string): string | null {
  if (!binding) return null;
  const parts = binding.split("+"), code = parts.pop()!;
  if (!codePattern.test(code) || parts.some(p => !["Ctrl", "Alt", "Shift", "Meta"].includes(p)) || new Set(parts).size !== parts.length)
    return "这组按键暂不支持。";
  if (!parts.some(p => ["Ctrl", "Alt", "Meta"].includes(p))) return "请加入 Ctrl、Alt 或 Command 修饰键，避免影响输入。";
  const ctrl = parts.includes("Ctrl") || parts.includes("Meta"), alt = parts.includes("Alt");
  if ((code === "Tab" || code === "F5") || (ctrl&&!alt&&/^Digit[0-9]$/.test(code)) || (alt && ["F4", "ArrowLeft", "ArrowRight"].includes(code)) ||
      (ctrl && !alt && ["KeyA", "KeyB", "KeyC", "KeyD", "KeyF", "KeyH", "KeyI", "KeyJ", "KeyK", "KeyL", "KeyN", "KeyO", "KeyP", "KeyQ", "KeyR", "KeyS", "KeyT", "KeyU", "KeyV", "KeyW", "KeyX", "KeyY", "KeyZ", "Enter", "Backspace", "Delete", "Space", "Home", "End", "Equal", "Minus", "Digit0"].includes(code)))
    return "这组按键用于浏览器或输入操作，请换一组。";
  return null;
}
export function shortcutFor(id: string, overrides?: Record<string, string>) {
  const custom = overrides?.[id];
  return typeof custom === "string" && !bindingError(custom) ? custom : shortcutActions.find(a => a.id === id)?.binding || "";
}
export function shortcutAction(e: KeyEvent, overrides?: Record<string, string>) {
  const binding = bindingFromEvent(e);
  return binding && !bindingError(binding) ? shortcutActions.find(a => shortcutFor(a.id, overrides) === binding)?.id : undefined;
}
export function bindingParts(binding: string) {
  return binding.split("+").filter(Boolean).map(p => p.replace(/^Key/, "").replace(/^Digit/, "").replace("Meta", "⌘").replace("Arrow", "").replace("Space", "空格"));
}
export function shortcutHint(id: string, overrides?: Record<string, string>) {
  return bindingParts(shortcutFor(id, overrides)).join("+");
}
