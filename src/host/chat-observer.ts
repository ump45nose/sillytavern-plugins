/** What changed inside #chat since the last animation frame. */
export interface ChatChange {
  /** `.mes` nodes were added, removed, renumbered or changed role. */
  nodes: boolean;
  /** Inline editing started or ended, or a message's edit controls were replaced. */
  editing: boolean;
  /** Floors (mesid) whose rendered content changed; while streaming this is the last floor. */
  content: Set<number>;
}

const EDITING = ".edit_textarea,.mes_edit";
const touches = (node: Node, selector: string) =>
  node instanceof Element && (node.matches(selector) || !!node.querySelector(selector));

/**
 * The one MutationObserver on #chat. Records are classified once and delivered per frame, so
 * every consumer (reading view, RP stage, message controls) shares a single pass over them.
 */
export class ChatObserver {
  private listeners = new Set<(change: ChatChange) => void>();
  private pending: ChatChange | null = null;
  private frame = 0;
  private observer = new MutationObserver((records) => this.collect(records));
  constructor(private chat: HTMLElement) {
    this.observer.observe(chat, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["mesid", "is_user"],
    });
  }
  subscribe(fn: (change: ChatChange) => void) {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }
  disconnect() {
    this.observer.disconnect();
    cancelAnimationFrame(this.frame);
    this.listeners.clear();
  }
  private collect(records: MutationRecord[]) {
    const change = (this.pending ??= { nodes: false, editing: false, content: new Set() });
    for (const r of records) {
      if (r.type === "attributes") change.nodes = true;
      else if (r.type === "childList")
        for (const node of [...r.addedNodes, ...r.removedNodes]) {
          if (touches(node, ".mes")) change.nodes = true;
          if (touches(node, EDITING)) change.editing = true;
        }
      const target = r.target instanceof Element ? r.target : r.target.parentElement;
      const mes = target?.closest<HTMLElement>(".mes");
      if (mes && this.chat.contains(mes)) change.content.add(Number(mes.getAttribute("mesid")));
    }
    if (!this.frame) this.frame = requestAnimationFrame(() => this.flush());
  }
  private flush() {
    this.frame = 0;
    const change = this.pending;
    this.pending = null;
    if (change) this.listeners.forEach((fn) => fn(change));
  }
}

/**
 * Watches the native expression and visual-novel wrappers for sprite changes. Both are appended
 * straight to <body> by the expressions extension, so body is watched shallowly for their arrival
 * and only the wrappers themselves are watched in depth.
 */
export class MediaObserver {
  private listeners = new Set<() => void>();
  private frame = 0;
  private watched = new Set<Element>();
  private inner = new MutationObserver(() => this.schedule());
  private outer = new MutationObserver(() => this.attach());
  constructor() {
    this.outer.observe(document.body, { childList: true });
    this.attach();
  }
  subscribe(fn: () => void) {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }
  disconnect() {
    this.inner.disconnect();
    this.outer.disconnect();
    cancelAnimationFrame(this.frame);
    this.listeners.clear();
  }
  private attach() {
    for (const node of document.querySelectorAll("#expression-wrapper,#visual-novel-wrapper")) {
      if (this.watched.has(node)) continue;
      this.watched.add(node);
      this.inner.observe(node, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["src", "data-avatar"],
      });
      this.schedule();
    }
  }
  private schedule() {
    if (!this.frame)
      this.frame = requestAnimationFrame(() => {
        this.frame = 0;
        this.listeners.forEach((fn) => fn());
      });
  }
}
