/**
 * Plain-text Markdown editing rules shared by every Markdown field. Pure functions over strings so
 * they can be tested without an editor; the CodeMirror bindings in editor.ts apply their results.
 */

/** A list, task or quote marker at the start of a line: its indent, marker and the text after it. */
const ITEM = /^(\s*)((?:[-*+]|\d+[.)])(?: \[[ xX]\])?|>+)(\s+)(.*)$/;

export interface Continuation {
  /** Replace the current line with this (empty-item exit) instead of inserting. */
  replaceLine?: string;
  /** Text inserted at the caret: a line break and the next marker. */
  insert?: string;
}

/**
 * What Enter does at the end of a list, task or quote line: continue with the next marker (numbers
 * count up, tasks start unchecked), or, on an item with nothing after its marker, end the list.
 * null means an ordinary line.
 */
export function continueItem(line: string): Continuation | null {
  const match = line.match(ITEM);
  if (!match) return null;
  const [, indent, marker, gap, text] = match;
  if (!text.trim()) return { replaceLine: indent && !marker.startsWith(">") ? outdent(indent) : "" };
  return { insert: "\n" + indent + nextMarker(marker) + gap };
}

function nextMarker(marker: string): string {
  if (marker.startsWith(">")) return marker;
  const task = marker.match(/^(.+?) \[[ xX]\]$/);
  if (task) return nextMarker(task[1]) + " [ ]";
  const number = marker.match(/^(\d+)([.)])$/);
  return number ? `${Number(number[1]) + 1}${number[2]}` : marker;
}

/** An empty nested item steps out one level (two spaces or a tab) instead of ending the list. */
function outdent(indent: string) {
  return indent.endsWith("\t") ? indent.slice(0, -1) : indent.slice(0, Math.max(0, indent.length - 2));
}

/** True when the line is inside a list or a quote, where Enter continues instead of sending. */
export function inItem(line: string) {
  return ITEM.test(line);
}

/** Opening characters that close themselves; Chinese quotes and brackets included. */
export const PAIRS: Record<string, string> = {
  "「": "」",
  "『": "』",
  "“": "”",
  "‘": "’",
  "（": "）",
  "【": "】",
  "《": "》",
  "(": ")",
  "[": "]",
  "`": "`",
};

const WRAPS = ["*", "_", "~"];

/**
 * Typing an opening character: wrap the selection, or insert the pair with the caret between.
 * Returns the replacement for the selection and the caret offset inside it.
 */
export function pair(open: string, selected: string) {
  // Emphasis marks only wrap a selection; typed alone they are ordinary characters.
  const close = PAIRS[open] ?? (selected && WRAPS.includes(open) ? open : undefined);
  if (!close) return null;
  return {
    text: open + selected + close,
    caret: selected ? open.length + selected.length + close.length : open.length,
  };
}

/** Wraps (or unwraps) the selection in a Markdown mark such as ** or `. */
export function toggleWrap(selected: string, mark: string) {
  const wrapped = selected.startsWith(mark) && selected.endsWith(mark) && selected.length >= mark.length * 2;
  return wrapped ? selected.slice(mark.length, selected.length - mark.length) : mark + selected + mark;
}

const URL_ONLY = /^(https?:\/\/|www\.)\S+$/i;

/** Pasting a lone URL over selected text makes a link of it; anything else pastes as is. */
export function pasteLink(selected: string, pasted: string) {
  const url = pasted.trim();
  if (!selected || selected.includes("\n") || !URL_ONLY.test(url)) return null;
  return `[${selected}](${url})`;
}

/** Tab / Shift+Tab on a list line: indent by two spaces, or remove up to two. */
export function indentItem(line: string, out: boolean) {
  if (!inItem(line)) return null;
  if (!out) return "  " + line;
  return line.startsWith("\t") ? line.slice(1) : line.replace(/^ {1,2}/, "");
}
