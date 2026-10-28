/**
 * The Markdown editor behind every Markdown field (loaded on first use): CodeMirror 6 with a live
 * preview — marks are hidden and their effect shown on every line but the ones being edited, which
 * show their source — plus list continuation, Chinese pairs, wrap shortcuts and URL-over-text paste.
 * Styles come from the editor's own theme (scoped classes) on the workbench's colour tokens: its root
 * is a native-embedded node, outside the workbench's layer isolation.
 */
import {
  Annotation,
  Compartment,
  EditorSelection,
  EditorState,
  Prec,
  RangeSetBuilder,
  type Extension,
} from "@codemirror/state";
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  WidgetType,
  keymap,
  placeholder as placeholderText,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, insertNewline } from "@codemirror/commands";
import { Language, LanguageSupport, defineLanguageFacet, syntaxTree } from "@codemirror/language";
import { GFM, parser } from "@lezer/markdown";
import { PAIRS, continueItem, indentItem, pair, pasteLink, toggleWrap } from "./commands";

export interface MdOptions {
  doc: string;
  label: string;
  placeholder?: string;
  onChange: (text: string) => void;
  /** Enter on an ordinary line (not a list, quote or code block); true when it was handled. */
  onEnter?: () => boolean;
  onFocus?: () => void;
  onBlur?: () => void;
  /** Extra behaviour for one field (the composer adds its event relays here). */
  extensions?: Extension[];
}
export interface MdHandle {
  view: EditorView;
  /** Replaces the text from outside, optionally with a selection; does not call onChange. */
  set: (text: string, selection?: { anchor: number; head: number }) => void;
  setDisabled: (disabled: boolean) => void;
  focus: (caret?: number) => void;
  destroy: () => void;
}

const externalAnnotation = Annotation.define<boolean>();
/** GitHub-flavoured Markdown, parsed only: embedded HTML and code stay plain text. */
const markdown = new LanguageSupport(
  new Language(defineLanguageFacet(), parser.configure(GFM), [], "markdown"),
);

class Bullet extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-md-bullet";
    span.textContent = "•";
    return span;
  }
}
class Rule extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-md-rule";
    return span;
  }
}
const hidden = Decoration.replace({}),
  bullet = Decoration.replace({ widget: new Bullet() }),
  rule = Decoration.replace({ widget: new Rule() });
const marks: Record<string, Decoration> = {
  StrongEmphasis: Decoration.mark({ class: "cm-md-strong" }),
  Emphasis: Decoration.mark({ class: "cm-md-em" }),
  InlineCode: Decoration.mark({ class: "cm-md-code" }),
  Strikethrough: Decoration.mark({ class: "cm-md-strike" }),
  Link: Decoration.mark({ class: "cm-md-link" }),
};
const lines: Record<string, string> = {
  ATXHeading1: "cm-md-h1",
  ATXHeading2: "cm-md-h2",
  ATXHeading3: "cm-md-h3",
  ATXHeading4: "cm-md-h4",
  ATXHeading5: "cm-md-h4",
  ATXHeading6: "cm-md-h4",
  SetextHeading1: "cm-md-h1",
  SetextHeading2: "cm-md-h2",
  Blockquote: "cm-md-quote",
  FencedCode: "cm-md-fence",
  CodeBlock: "cm-md-fence",
  HorizontalRule: "cm-md-hr",
};
const markNodes = new Set([
  "HeaderMark",
  "EmphasisMark",
  "CodeMark",
  "StrikethroughMark",
  "LinkMark",
  "URL",
  "QuoteMark",
  "CodeInfo",
]);

/** Lines holding a selection end show their source; every other line shows its effect. */
function activeLines(state: EditorState) {
  const active = new Set<number>();
  for (const range of state.selection.ranges) {
    const from = state.doc.lineAt(range.from).number,
      to = state.doc.lineAt(range.to).number;
    for (let n = from; n <= to; n++) active.add(n);
  }
  return active;
}

function preview(view: EditorView): DecorationSet {
  const { state } = view,
    active = activeLines(state),
    focused = view.hasFocus;
  const lineClasses = new Map<number, Set<string>>();
  const inline: { from: number; to: number; deco: Decoration }[] = [];
  const addLine = (from: number, to: number, cls: string) => {
    for (let n = state.doc.lineAt(from).number; n <= state.doc.lineAt(to).number; n++)
      (lineClasses.get(n) ?? lineClasses.set(n, new Set()).get(n)!).add(cls);
  };
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(state).iterate({
      from,
      to,
      enter: (node) => {
        const name = node.name,
          line = state.doc.lineAt(node.from).number,
          editing = focused && active.has(line);
        if (lines[name]) addLine(node.from, node.to, lines[name]);
        if (marks[name]) inline.push({ from: node.from, to: node.to, deco: marks[name] });
        if (name === "HorizontalRule" && !editing) inline.push({ from: node.from, to: node.to, deco: rule });
        if (name === "ListMark" && !editing) {
          const text = state.sliceDoc(node.from, node.to);
          if (/^[-*+]$/.test(text)) inline.push({ from: node.from, to: node.to, deco: bullet });
        }
        if (!markNodes.has(name)) return;
        // Inside fenced code the marks are the fence itself; the fence lines stay as written.
        if (name === "CodeMark" && node.node.parent?.name === "FencedCode") return;
        if (name === "CodeInfo") return;
        if (editing) {
          inline.push({ from: node.from, to: node.to, deco: Decoration.mark({ class: "cm-md-mark" }) });
          return;
        }
        let end = node.to;
        // A heading or quote mark takes its following space with it.
        if ((name === "HeaderMark" || name === "QuoteMark") && state.sliceDoc(end, end + 1) === " ") end++;
        // Links show their text: the URL and its brackets go.
        if (name === "URL" && node.node.parent?.name !== "Link") return;
        inline.push({ from: node.from, to: end, deco: hidden });
      },
    });
  }
  const builder = new RangeSetBuilder<Decoration>();
  const entries: { from: number; to: number; deco: Decoration; line?: boolean }[] = [...inline];
  for (const [n, classes] of lineClasses) {
    const line = state.doc.line(n);
    entries.push({
      from: line.from,
      to: line.from,
      deco: Decoration.line({ class: [...classes].join(" ") }),
      line: true,
    });
  }
  entries.sort((a, b) => a.from - b.from || (a.line ? -1 : b.line ? 1 : 0) || a.to - b.to);
  let last = -1;
  for (const e of entries) {
    // Replacements may not overlap; a later one inside an earlier hidden range is dropped.
    if (!e.line && e.deco === hidden && e.from < last) continue;
    builder.add(e.from, e.to, e.deco);
    if (e.deco === hidden) last = Math.max(last, e.to);
  }
  return builder.finish();
}

const livePreview = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = preview(view);
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged || update.selectionSet || update.focusChanged)
        this.decorations = preview(update.view);
    }
  },
  { decorations: (v) => v.decorations },
);

/** {{macros}} as small chips and <xml> tags dimmed, on every line. */
const token = (regexp: RegExp, cls: string) => {
  const decorator = new MatchDecorator({ regexp, decoration: Decoration.mark({ class: cls }) });
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;
      constructor(view: EditorView) {
        this.decorations = decorator.createDeco(view);
      }
      update(update: ViewUpdate) {
        this.decorations = decorator.updateDeco(update, this.decorations);
      }
    },
    { decorations: (v) => v.decorations },
  );
};

function inFence(state: EditorState, pos: number) {
  for (let node: any = syntaxTree(state).resolveInner(pos, -1); node; node = node.parent)
    if (node.name === "FencedCode" || node.name === "CodeBlock") return true;
  return false;
}

function enter(onEnter?: () => boolean) {
  return (view: EditorView) => {
    const { state } = view,
      range = state.selection.main;
    if (!range.empty || inFence(state, range.head)) return insertNewline(view);
    const line = state.doc.lineAt(range.head),
      before = state.sliceDoc(line.from, range.head);
    const next = continueItem(before);
    if (next?.replaceLine !== undefined) {
      view.dispatch({
        changes: { from: line.from, to: line.to, insert: next.replaceLine },
        scrollIntoView: true,
      });
      return true;
    }
    if (next?.insert) {
      view.dispatch(state.replaceSelection(next.insert), { scrollIntoView: true });
      return true;
    }
    if (onEnter?.()) return true;
    return insertNewline(view);
  };
}

const wrap = (mark: string) => (view: EditorView) => {
  view.dispatch(
    view.state.changeByRange((range) => {
      const text = toggleWrap(view.state.sliceDoc(range.from, range.to), mark);
      const caret = range.empty ? range.from + mark.length : range.from + text.length;
      return {
        changes: { from: range.from, to: range.to, insert: text },
        range: EditorSelection.range(range.empty ? caret : range.from, caret),
      };
    }),
  );
  return true;
};

const link = (view: EditorView) => {
  view.dispatch(
    view.state.changeByRange((range) => {
      const text = view.state.sliceDoc(range.from, range.to),
        insert = `[${text}]()`;
      return {
        changes: { from: range.from, to: range.to, insert },
        range: EditorSelection.cursor(range.from + insert.length - 1),
      };
    }),
  );
  return true;
};

const indent = (out: boolean) => (view: EditorView) => {
  const line = view.state.doc.lineAt(view.state.selection.main.head),
    next = indentItem(line.text, out);
  if (next === null) return false;
  const delta = next.length - line.text.length;
  view.dispatch({
    changes: { from: line.from, to: line.to, insert: next },
    selection: EditorSelection.cursor(Math.max(line.from, view.state.selection.main.head + delta)),
  });
  return true;
};

const closers = new Set(Object.values(PAIRS));
/** Opening characters insert their pair; a typed closer over the same closer steps past it. */
const pairs = EditorView.inputHandler.of((view, from, to, text) => {
  if (view.composing) return false;
  const next = view.state.sliceDoc(from, from + 1);
  if (from === to && closers.has(text) && next === text && !PAIRS[text]) {
    view.dispatch({ selection: EditorSelection.cursor(from + 1) });
    return true;
  }
  // ` both opens and closes: over a closing one it steps past.
  if (text === "`" && next === "`" && from === to) {
    view.dispatch({ selection: EditorSelection.cursor(from + 1) });
    return true;
  }
  const selected = view.state.sliceDoc(from, to),
    paired = pair(text, selected);
  if (!paired) return false;
  // A wrapped selection stays selected, so typing * twice makes it bold.
  const selection = selected
    ? EditorSelection.range(from + text.length, from + text.length + selected.length)
    : EditorSelection.cursor(from + paired.caret);
  view.dispatch({ changes: { from, to, insert: paired.text }, selection });
  return true;
});
/** Backspace between an empty pair removes both halves. */
const unpair = (view: EditorView) => {
  const range = view.state.selection.main;
  if (!range.empty) return false;
  const before = view.state.sliceDoc(range.from - 1, range.from),
    after = view.state.sliceDoc(range.from, range.from + 1);
  if (!PAIRS[before] || PAIRS[before] !== after) return false;
  view.dispatch({ changes: { from: range.from - 1, to: range.from + 1 } });
  return true;
};

const theme = EditorView.theme({
  "&": {
    color: "var(--wb-ink-1, #2f2c27)",
    background: "transparent",
    fontSize: "inherit",
    // The field is a flex column: the editor grows with its text up to the field's max-height.
    flex: "1 1 auto",
    minHeight: "0",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "inherit", lineHeight: "inherit", overflow: "auto" },
  ".cm-content": {
    padding: "0",
    minHeight: "calc(var(--wb-md-rows, 1) * 1lh)",
    caretColor: "var(--wb-accent, #b76449)",
    whiteSpace: "pre-wrap",
  },
  ".cm-line": { padding: "0" },
  ".cm-cursor": { borderLeftColor: "var(--wb-accent, #b76449)", borderLeftWidth: "1.5px" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    background: "color-mix(in srgb, var(--wb-accent, #b76449) 22%, transparent) !important",
  },
  ".cm-placeholder": { color: "var(--wb-ink-3, #8b857a)" },
  ".cm-md-h1": { fontSize: "1.5em", fontWeight: "650", lineHeight: "1.35" },
  ".cm-md-h2": { fontSize: "1.3em", fontWeight: "650", lineHeight: "1.35" },
  ".cm-md-h3": { fontSize: "1.15em", fontWeight: "650" },
  ".cm-md-h4": { fontWeight: "650" },
  ".cm-md-strong": { fontWeight: "650" },
  ".cm-md-em": { fontStyle: "italic" },
  ".cm-md-strike": { textDecoration: "line-through", color: "var(--wb-ink-3, #8b857a)" },
  ".cm-md-code": {
    fontFamily: "var(--wb-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
    fontSize: "0.9em",
    background: "var(--wb-well, rgba(47,44,39,.06))",
    borderRadius: "4px",
    padding: "0 3px",
  },
  ".cm-md-fence": {
    fontFamily: "var(--wb-font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
    fontSize: "0.9em",
    background: "var(--wb-well, rgba(47,44,39,.06))",
  },
  ".cm-md-quote": {
    borderLeft: "3px solid var(--wb-line-2, #d3cec3)",
    paddingLeft: "10px !important",
    color: "var(--wb-ink-2, #5c574e)",
  },
  ".cm-md-link": {
    color: "var(--wb-accent-text, #9a4f37)",
    textDecoration: "underline",
    textUnderlineOffset: "2px",
  },
  ".cm-md-mark": { color: "var(--wb-ink-3, #8b857a)" },
  ".cm-md-bullet": { color: "var(--wb-ink-3, #8b857a)", padding: "0 0.25em" },
  ".cm-md-rule": {
    display: "inline-block",
    width: "100%",
    height: "0",
    borderTop: "1px solid var(--wb-line-2, #d3cec3)",
    verticalAlign: "middle",
  },
  ".cm-md-macro": {
    color: "var(--wb-accent-text, #9a4f37)",
    background: "color-mix(in srgb, var(--wb-accent, #b76449) 10%, transparent)",
    borderRadius: "4px",
    padding: "0 2px",
  },
  ".cm-md-tag": { color: "var(--wb-ink-3, #8b857a)" },
});

export function createMdEditor(parent: HTMLElement, options: MdOptions): MdHandle {
  const access = new Compartment();
  let disabled = false;
  const permissions = (blocked: boolean) => [
    EditorState.readOnly.of(blocked),
    EditorView.editable.of(!blocked),
    EditorView.contentAttributes.of({ "aria-disabled": String(blocked), tabindex: blocked ? "-1" : "0" }),
  ];
  const listeners: Extension[] = [
    EditorView.updateListener.of((update) => {
      if (update.docChanged && !update.transactions.some((t) => t.annotation(externalAnnotation)))
        options.onChange(update.state.doc.toString());
      if (update.focusChanged) (update.view.hasFocus ? options.onFocus : options.onBlur)?.();
    }),
  ];
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: options.doc,
      extensions: [
        access.of(permissions(false)),
        EditorState.transactionFilter.of((transaction) =>
          transaction.startState.readOnly &&
          transaction.docChanged &&
          !transaction.annotation(externalAnnotation)
            ? []
            : transaction,
        ),
        history(),
        EditorView.lineWrapping,
        markdown,
        livePreview,
        token(/\{\{[^{}\n]{1,80}\}\}/g, "cm-md-macro"),
        token(/<\/?[A-Za-z][\w:-]*(?:\s[^<>\n]*)?\/?>/g, "cm-md-tag"),
        pairs,
        Prec.high(
          keymap.of([
            { key: "Enter", run: enter(options.onEnter) },
            { key: "Shift-Enter", run: insertNewline },
            { key: "Mod-b", run: wrap("**") },
            { key: "Mod-i", run: wrap("*") },
            { key: "Mod-e", run: wrap("`") },
            { key: "Mod-k", run: link },
            { key: "Tab", run: indent(false) },
            { key: "Shift-Tab", run: indent(true) },
            { key: "Backspace", run: unpair },
          ]),
        ),
        keymap.of([...historyKeymap, ...defaultKeymap]),
        EditorView.domEventHandlers({
          paste: (event, view) => {
            const range = view.state.selection.main,
              text = event.clipboardData?.getData("text/plain") ?? "",
              linked = pasteLink(view.state.sliceDoc(range.from, range.to), text);
            if (!linked) return false;
            event.preventDefault();
            view.dispatch(view.state.replaceSelection(linked));
            return true;
          },
        }),
        EditorView.contentAttributes.of({
          "aria-label": options.label,
          "aria-multiline": "true",
          spellcheck: "false",
        }),
        options.placeholder ? placeholderText(options.placeholder) : [],
        theme,
        listeners,
        options.extensions ?? [],
      ],
    }),
  });
  return {
    view,
    setDisabled(value) {
      if (value === disabled) return;
      disabled = value;
      view.dispatch({ effects: access.reconfigure(permissions(value)) });
    },
    set(text, selection) {
      const clamp = (n: number) => Math.max(0, Math.min(n, text.length));
      const range = selection
        ? EditorSelection.range(clamp(selection.anchor), clamp(selection.head))
        : EditorSelection.cursor(clamp(view.state.selection.main.head));
      if (text === view.state.doc.toString()) {
        if (selection && !range.eq(view.state.selection.main)) view.dispatch({ selection: range });
        return;
      }
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
        selection: range,
        annotations: externalAnnotation.of(true),
      });
    },
    focus(caret) {
      view.focus();
      if (caret !== undefined)
        view.dispatch({
          selection: EditorSelection.cursor(Math.max(0, Math.min(caret, view.state.doc.length))),
        });
    },
    destroy: () => view.destroy(),
  };
}
