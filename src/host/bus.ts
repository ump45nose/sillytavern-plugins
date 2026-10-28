import type { MessageTarget } from "../addons/types";
import type { AddonId } from "../addons/catalog";

/** Workbench-internal events and their payloads. */
export interface BusEvents {
  /** A message for the global error toast. */
  error: string;
  /** Open an add-on in the right panel or its full editor. */
  "addon-open": { id: AddonId; view: "workspace" | "editor" };
  /** Enter manual image input for a floor. */
  "image-input": MessageTarget;
  /** Choose an existing or local image for the gap after a floor. */
  "image-insert": { target: MessageTarget; anchor: HTMLElement };
  /** Manual image input began or ended (RP and PWA adjust their chrome). */
  "image-compose": undefined;
  "image-compose-end": undefined;
  /** The layout switcher's menu opened or closed. */
  "layout-menu": boolean;
  /** Show a floor on the RP stage. */
  "rp-jump": number;
  /** The RP stage moved its current line (`.wb-rp-current`) to another floor, or cleared it. */
  "rp-line": undefined;
  /** The reading scrolled to a floor picked from navigation (the phone selects it for editing). */
  "floor-jump": number;
  /** Open a settings group (optionally one extension inside it). */
  "settings-group": { group: string; extension?: string };
  /** The phone's compose band was pulled down: the RP stage returns to the dialogue. */
  "rp-dialogue": undefined;
  /** Show the latest reply's story options (the phone opens its options sheet). */
  "story-options": undefined;
  /** A story option filled the input: the RP band turns into it. */
  "rp-reply": undefined;
  /** A user edited the Markdown composer; native input events are observed separately. */
  "composer-input": undefined;
}
type Name = keyof BusEvents;
type Handler<K extends Name> = (payload: BusEvents[K]) => void;

/**
 * Typed replacement for the workbench's window CustomEvents. The only window event left is
 * `wb-startup-updated`, sent by extension/startup.js, which loads outside this bundle.
 */
class Bus {
  private handlers = new Map<Name, Set<Handler<any>>>();
  on<K extends Name>(name: K, fn: Handler<K>) {
    let set = this.handlers.get(name);
    if (!set) this.handlers.set(name, (set = new Set()));
    set.add(fn);
    return () => {
      set.delete(fn);
    };
  }
  emit<K extends Name>(name: K, ...[payload]: BusEvents[K] extends undefined ? [] : [BusEvents[K]]) {
    // Copy first: a handler may unsubscribe (or subscribe) while we iterate.
    for (const fn of [...(this.handlers.get(name) ?? [])]) fn(payload);
  }
}
export const bus = new Bus();

export interface LeaveOptions {
  /** Leaving one view for another inside the workbench; resource drafts stay. */
  preserveDrafts?: boolean;
}
/** Returns false to keep the user where they are (it may ask first). */
export type Guard = (options: LeaveOptions) => boolean | (() => void);

/** "May the user leave?" checks, run in registration order until one says no. */
class Guards {
  private list = new Set<Guard>();
  private unsaved = new Set<() => boolean>();
  private unload = (e: BeforeUnloadEvent) => {
    if (![...this.unsaved].some((pending) => pending())) return;
    e.preventDefault();
    e.returnValue = "";
  };
  add(fn: Guard) {
    this.list.add(fn);
    return () => {
      this.list.delete(fn);
    };
  }
  /** While `pending()` is true the browser asks before the page unloads; one listener serves every source. */
  hold(pending: () => boolean) {
    if (!this.unsaved.size) window.addEventListener("beforeunload", this.unload);
    this.unsaved.add(pending);
    return () => {
      if (this.unsaved.delete(pending) && !this.unsaved.size)
        window.removeEventListener("beforeunload", this.unload);
    };
  }
  /** True when every guard allows leaving. */
  check(options: LeaveOptions = {}) {
    const commits: (() => void)[] = [];
    for (const fn of [...this.list]) {
      const result = fn(options);
      if (!result) return false;
      if (typeof result === "function") commits.push(result);
    }
    commits.forEach((commit) => commit());
    return true;
  }
}
export const guards = new Guards();
