/**
 * The composer's live Markdown editor, laid over SillyTavern's own #send_textarea.
 *
 * The textarea stays the model and the layout: it keeps its value, size, CSS, listeners and every
 * native reader (send, drafts, extensions, the slash-command autocomplete). The editor sits on its
 * box with its typography and mirrors it both ways:
 * - typing writes the textarea's value and fires `input`, as typing into it would;
 * - any write to the textarea (`value`, `setSelectionRange`, focus) is relayed into the editor.
 * Keys and files the editor does not consume are replayed on the textarea, so SillyTavern's
 * Enter-to-send, empty-input arrow hotkeys, file paste and the workbench's image mode still see
 * their own element. A draft that starts with "/" is a slash command, not Markdown: the native
 * textarea comes back for it, with SillyTavern's autocomplete, until the slash is gone.
 */
import { Compartment, EditorSelection, Prec } from "@codemirror/state";
import { EditorView, placeholder } from "@codemirror/view";
import { createMdEditor } from "./editor";
import { bus } from "../../host/bus";

const valueOf = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!;
const selectRange = HTMLTextAreaElement.prototype.setSelectionRange;
/** What the overlay takes from the textarea's computed style, so every composer mode's CSS applies. */
const TYPE = [
  "fontFamily",
  "fontSize",
  "fontWeight",
  "fontStyle",
  "lineHeight",
  "letterSpacing",
  "color",
  "textAlign",
] as const;
const SIDES = ["Top", "Right", "Bottom", "Left"] as const;
const KEEP_FOCUS = "#send_but, #option_regenerate, #option_continue, #mes_continue, #mes_impersonate";
const ARROWS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);

const command = (text: string) => text.startsWith("/");

export function bindComposer(input: HTMLTextAreaElement): () => void {
  const box = document.createElement("div");
  box.className = "wb-md wb-composer-md wb-native-embedded";
  input.after(box);
  const text = () => valueOf.get!.call(input) as string;
  const hint = new Compartment();
  let native = command(text()),
    replaying = false;

  /** Hands an event to the textarea as if it had happened there; true when something took it. */
  const replay = (event: Event) => {
    replaying = true;
    try {
      input.focus({ preventScroll: true });
      input.dispatchEvent(event);
    } finally {
      replaying = false;
    }
    if (!native && document.activeElement === input) editor.focus();
    return event.defaultPrevented;
  };
  const files = (list?: FileList | null) => !!list?.length;

  const editor = createMdEditor(box, {
    doc: text(),
    label: input.getAttribute("aria-label") || "输入框",
    onChange(value) {
      valueOf.set!.call(input, value);
      const range = editor.view.state.selection.main;
      selectRange.call(input, range.from, range.to);
      if (command(value)) toNative(box.contains(document.activeElement));
      input.dispatchEvent(new Event("input", { bubbles: true }));
      bus.emit("composer-input");
    },
    // An ordinary line's Enter is SillyTavern's (send on Enter) or the image mode's to take.
    onEnter: () =>
      replay(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true })),
    extensions: [
      hint.of(placeholder(input.placeholder)),
      EditorView.theme({ "&": { color: "inherit" } }),
      EditorView.updateListener.of((update) => {
        if (!update.selectionSet || update.docChanged) return;
        const range = update.state.selection.main;
        selectRange.call(input, range.from, range.to);
      }),
      Prec.highest(
        EditorView.domEventHandlers({
          // An empty draft's arrows are SillyTavern's: swipes and editing the last message.
          keydown(event, view) {
            if (view.state.doc.length || !ARROWS.has(event.key) || event.shiftKey || event.altKey)
              return false;
            const handled = replay(
              new KeyboardEvent("keydown", { ...pick(event), bubbles: true, cancelable: true }),
            );
            if (handled) event.preventDefault();
            return handled;
          },
          paste(event) {
            if (!files(event.clipboardData?.files)) return false;
            event.preventDefault();
            event.stopPropagation();
            replay(
              new ClipboardEvent("paste", {
                clipboardData: event.clipboardData,
                bubbles: true,
                cancelable: true,
              }),
            );
            return true;
          },
          drop(event) {
            if (!files(event.dataTransfer?.files)) return false;
            event.preventDefault();
            event.stopPropagation();
            input.dispatchEvent(
              new DragEvent("drop", { dataTransfer: event.dataTransfer, bubbles: true, cancelable: true }),
            );
            return true;
          },
          // The textarea's scroll follows, so gestures that ask whether the draft scrolls still know.
          scroll(_, view) {
            input.scrollTop = view.scrollDOM.scrollTop;
          },
        }),
      ),
    ],
  });

  const toNative = (moveFocus: boolean) => {
    if (native) return;
    native = true;
    show();
    if (moveFocus) {
      const range = editor.view.state.selection.main;
      input.focus({ preventScroll: true });
      selectRange.call(input, range.from, range.to);
    }
  };
  const toEditor = (moveFocus: boolean) => {
    if (!native) return;
    native = false;
    pull();
    show();
    if (moveFocus) editor.focus();
  };
  const show = () => {
    box.hidden = native;
    input.toggleAttribute("data-wb-md", !native);
    if (!native) place();
  };
  /** Textarea → editor: its text and selection. */
  const pull = () => {
    if (command(text()))
      return toNative(document.activeElement === input || box.contains(document.activeElement));
    if (native) return toEditor(document.activeElement === input);
    editor.set(text(), { anchor: input.selectionStart, head: input.selectionEnd });
  };

  // Writes from SillyTavern, extensions and the workbench go through the instance's own `value`.
  Object.defineProperty(input, "value", {
    configurable: true,
    get: () => text(),
    set(value: string) {
      valueOf.set!.call(input, value);
      pull();
    },
  });
  input.setSelectionRange = (start, end, direction) => {
    selectRange.call(input, start, end, direction);
    if (!native)
      editor.view.dispatch({ selection: EditorSelection.range(clamp(start), clamp(end ?? start)) });
  };
  input.select = () => input.setSelectionRange(0, text().length);
  const clamp = (n: number | null) => Math.max(0, Math.min(n ?? 0, editor.view.state.doc.length));
  // Input written into the textarea itself (slash commands, automation) reaches the editor too; the
  // editor's own writes leave nothing to change.
  const typed = () => pull();
  // Focus given to the textarea (SillyTavern, the workbench) passes to the editor once the caller is
  // done. Heard in capture on the document: jQuery's focus trigger stops the native event at the
  // textarea and focuses it again inside its own handler.
  const focused = (event: FocusEvent) => {
    if (event.target !== input || replaying) return;
    queueMicrotask(() => {
      if (native || replaying || document.activeElement !== input) return;
      editor.focus();
      // With the selection the caller left (scripts in other worlds do not see the overrides above).
      editor.set(text(), { anchor: input.selectionStart, head: input.selectionEnd });
    });
  };
  // SillyTavern returns focus to its textarea after these buttons when it had focus; so does the editor.
  let editing = false;
  const press = () => {
    editing = box.contains(document.activeElement);
  };
  const click = (event: MouseEvent) => {
    if (editing && !native && (event.target as Element).closest?.(KEEP_FOCUS)) editor.focus();
  };
  input.addEventListener("input", typed);
  document.addEventListener("focusin", focused, true);
  document.addEventListener("pointerdown", press, true);
  document.addEventListener("click", click);

  /** The overlay's box and typography, read from the textarea once per frame on any change. */
  let frame = 0;
  const place = () => {
    if (frame || native) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const style = getComputedStyle(input),
        s = box.style;
      s.left = `${input.offsetLeft}px`;
      s.top = `${input.offsetTop}px`;
      s.width = `${input.offsetWidth}px`;
      s.height = `${input.offsetHeight}px`;
      for (const key of TYPE) s[key] = style[key];
      for (const side of SIDES)
        s[`padding${side}`] =
          `${parseFloat(style[`padding${side}`]) + parseFloat(style[`border${side}Width`])}px`;
    });
  };
  const resize = new ResizeObserver(place);
  resize.observe(input);
  if (input.parentElement) resize.observe(input.parentElement);
  const watch = new MutationObserver((records) => {
    if (records.some((r) => r.attributeName === "placeholder"))
      editor.view.dispatch({ effects: hint.reconfigure(placeholder(input.placeholder)) });
    place();
  });
  watch.observe(input, { attributes: true, attributeFilter: ["placeholder", "class", "style"] });
  watch.observe(document.body, { attributes: true, attributeFilter: ["class"] });
  show();
  if (document.activeElement === input && !native) editor.focus();

  return () => {
    cancelAnimationFrame(frame);
    resize.disconnect();
    watch.disconnect();
    input.removeEventListener("input", typed);
    document.removeEventListener("focusin", focused, true);
    document.removeEventListener("pointerdown", press, true);
    document.removeEventListener("click", click);
    delete (input as { value?: string }).value;
    delete (input as { setSelectionRange?: unknown }).setSelectionRange;
    delete (input as { select?: unknown }).select;
    const had = box.contains(document.activeElement);
    editor.destroy();
    box.remove();
    input.removeAttribute("data-wb-md");
    if (had) input.focus({ preventScroll: true });
  };
}

function pick(event: KeyboardEvent): KeyboardEventInit {
  const { key, code, ctrlKey, metaKey, shiftKey, altKey, repeat } = event;
  return { key, code, ctrlKey, metaKey, shiftKey, altKey, repeat };
}
