import type { Panel, Resource, SettingsPage } from "../../host/types";
import type { ComposerPopup } from "../ComposerPopovers";

/**
 * The workbench layout as one value. Every exclusion and reset rule lives in `reduce`; App only
 * checks leave guards, dispatches and renders. Pure: no DOM, no host, no timers.
 */

export type AddonPanel = "export" | "outline" | "image-gen";
/** The add-on full editors, which replace the workbench until closed. */
export type Deep = "outline" | "image-gen" | null;
export interface Workspace {
  page: SettingsPage;
  group?: string;
  initial?: string;
}
export interface Env {
  mode: "novel" | "rp";
  mobile: boolean;
  width: number;
  /** Which add-on panels are enabled in the user's settings. */
  addons: Record<AddonPanel, boolean>;
  /** The database plug-in is installed; its panel exists only then. */
  database: boolean;
}
export interface LayoutState {
  env: Env;
  /** The user wants the left sidebar open; whether it fits is `leftVisible`. */
  left: boolean;
  panel: Panel;
  /** Last panel opened, reopened by the right edge arrow. */
  lastPanel: NonNullable<Panel>;
  chooser: Resource | null;
  /** The item the open panel or deep editor starts on. */
  focusId: string;
  deep: Deep;
  focus: boolean;
  popup: ComposerPopup | null;
  workspace: Workspace | null;
  help: boolean;
  railOpen: boolean;
}
/** Hover-revealed sidebars (useSidebarHover) are transient UI state the model reads but does not own. */
export interface Hover {
  left: boolean;
  right: boolean;
}
/** Sidebar widths in px, read from the --wb-*-size tokens. */
export interface Sizes {
  left: number;
  right: number;
  rail: number;
}

export type Action =
  | { type: "env"; env: Partial<Env>; prefLeft: boolean }
  | { type: "panel"; panel: Panel; id?: string }
  | { type: "deep"; deep: Deep; id?: string }
  | { type: "settings"; workspace: Workspace }
  | { type: "close-settings" }
  | { type: "toggle-left"; hover: Hover; sizes: Sizes }
  | { type: "left"; open: boolean }
  | { type: "close-drawers" }
  | { type: "focus"; on?: boolean }
  | { type: "chooser"; chooser: Resource | null }
  | { type: "popup"; popup: ComposerPopup | null }
  | { type: "toggle-popup"; popup: ComposerPopup }
  | { type: "help"; open: boolean }
  | { type: "rail"; open: boolean }
  /** Manual image input began; a narrow RP stage needs both sidebars out of the way. */
  | { type: "image-input" }
  | { type: "layout-menu"; open: boolean };

const addonPanels: readonly string[] = ["export", "outline", "image-gen"];
/** Panels that take the whole right column, without the resource rail. */
const unrailed: readonly string[] = ["trace", ...addonPanels];

export const isAddonPanel = (panel: Panel): panel is AddonPanel => addonPanels.includes(panel as string);
export const available = (env: Env, panel: Panel) =>
  panel === "database" ? env.database : !isAddonPanel(panel) || env.addons[panel];
const rp = (s: LayoutState) => s.env.mode === "rp";
/** RP narrow enough that the sidebars overlay the stage instead of sitting beside it. */
export const compactRp = (s: LayoutState) => rp(s) && s.env.width <= 1100;
const defaultLeft = (env: Env, prefLeft: boolean) => (env.mobile || env.mode === "rp" ? false : prefLeft);

/** Env fields compared field by field: App rebuilds the object every render. */
export const sameEnv = (a: Env, b: Env) =>
  a.mode === b.mode &&
  a.mobile === b.mobile &&
  a.width === b.width &&
  a.database === b.database &&
  addonPanels.every((k) => a.addons[k as AddonPanel] === b.addons[k as AddonPanel]);

export function initial(env: Env, prefLeft: boolean): LayoutState {
  return {
    env,
    left: defaultLeft(env, prefLeft),
    panel: null,
    lastPanel: "character",
    chooser: null,
    focusId: "",
    deep: null,
    focus: false,
    popup: null,
    workspace: null,
    help: false,
    railOpen: true,
  };
}

/** The panel the right edge arrow reopens: the last one, unless its add-on was switched off. */
export const lastAvailablePanel = (s: LayoutState): NonNullable<Panel> =>
  available(s.env, s.lastPanel) ? s.lastPanel : "character";
/** The panel on screen: the pinned one, or the hover-revealed last one. */
export const shownPanel = (s: LayoutState, hover: Hover): Panel =>
  s.panel || (hover.right ? lastAvailablePanel(s) : null);
const pinnedRail = (s: LayoutState) => !!s.panel && !unrailed.includes(s.panel) && s.railOpen && !s.focus;

/** Whether the pinned left sidebar is on screen: it gives way to panels when the reading column would get too narrow. */
export function leftVisible(s: LayoutState, sizes: Sizes) {
  // A phone's focus only hides the chrome; its drawers still slide over the page.
  if (!s.left || (s.focus && !s.env.mobile)) return false;
  if (!s.panel) return true;
  if (s.env.mobile) return false;
  const reading = s.env.width - sizes.left - sizes.right - (pinnedRail(s) ? sizes.rail : 0);
  return !compactRp(s) && reading >= 420;
}
export const railVisible = (s: LayoutState, hover: Hover) => {
  const shown = shownPanel(s, hover);
  return !s.env.mobile && !!shown && !unrailed.includes(shown) && s.railOpen && !s.focus;
};
export const navigationVisible = (s: LayoutState, hover: Hover, sizes: Sizes) =>
  leftVisible(s, sizes) || (hover.left && !s.focus);

/** Classes the native-bridge CSS keys off, toggled on <body>. */
export function bodyClasses(s: LayoutState, hover: Hover, sizes: Sizes): Record<string, boolean> {
  const visible = leftVisible(s, sizes),
    mobile = s.env.mobile;
  return {
    // Phones keep drawer state off <body>: every class write there makes SillyTavern's keyboard
    // observer rescan the whole document, which stalls the slide.
    "wb-left-open": visible && !mobile,
    "wb-left-hover-open": hover.left && !visible,
    "wb-right-hover-open": hover.right && !s.panel,
    "wb-right-open": !!s.panel && !s.focus && !mobile,
    "wb-focus": s.focus,
    "wb-rail-open": railVisible(s, hover) && !!s.panel,
    "wb-mobile": mobile,
    "wb-mobile-rp": mobile && rp(s),
    "wb-rp": rp(s) && !mobile,
    "wb-rp-overlay-open": !mobile && compactRp(s) && !!(visible || (s.panel && !s.focus)),
  };
}

function openPanel(s: LayoutState, panel: Panel, id?: string): LayoutState {
  if (!available(s.env, panel)) return s;
  if (!panel) return { ...s, panel, chooser: null };
  return {
    ...s,
    panel,
    lastPanel: panel,
    chooser: null,
    railOpen: true,
    focusId: id ?? "",
    left: s.env.mobile || compactRp(s) ? false : s.left,
  };
}

export function reduce(s: LayoutState, a: Action): LayoutState {
  switch (a.type) {
    case "env": {
      const env = { ...s.env, ...a.env };
      let next: LayoutState = { ...s, env };
      if (env.mode !== s.env.mode)
        next = {
          ...next,
          left: defaultLeft(env, a.prefLeft),
          panel: null,
          chooser: null,
          popup: null,
          workspace: null,
          deep: null,
          focus: false,
        };
      else if (env.mobile !== s.env.mobile)
        next = {
          ...next,
          left: defaultLeft(env, a.prefLeft),
          panel: null,
          chooser: null,
          popup: null,
          focus: false,
        };
      // An add-on switched off takes its panel and editor with it.
      if (!available(env, next.panel)) next.panel = null;
      if (!available(env, next.deep)) next.deep = null;
      return next;
    }
    case "panel":
      return openPanel(s, a.panel, a.id);
    case "deep":
      if (!a.deep) return { ...s, deep: null };
      if (!available(s.env, a.deep)) return s;
      return {
        ...s,
        deep: a.deep,
        focusId: a.id ?? s.focusId,
        panel: null,
        chooser: null,
        workspace: null,
        left: s.env.mobile ? false : s.left,
      };
    case "settings":
      return {
        ...s,
        workspace: a.workspace,
        popup: null,
        panel: null,
        chooser: null,
        deep: null,
        left: s.env.mobile ? false : s.left,
      };
    case "close-settings":
      return { ...s, workspace: null };
    case "toggle-left": {
      if (s.env.mobile) return { ...s, left: !s.left, panel: null, chooser: null, popup: null };
      const visible = leftVisible(s, a.sizes);
      // Pin a hover-revealed sidebar, closing a panel that would crowd it out.
      if (a.hover.left && !visible) return { ...openPanel(s, null), left: true };
      if (compactRp(s) && !s.left) return { ...openPanel(s, null), left: true };
      // Wanted but crowded out by a panel: make room rather than flipping the preference.
      if (s.left && !visible && !s.focus) return openPanel(s, null);
      return { ...s, left: !s.left };
    }
    case "left":
      return { ...s, left: a.open };
    case "close-drawers":
      return { ...openPanel(s, null), left: false };
    case "focus":
      return { ...s, chooser: null, focus: a.on ?? !s.focus };
    case "chooser":
      return { ...s, chooser: a.chooser };
    case "popup":
      return { ...s, popup: a.popup };
    case "toggle-popup": {
      const same = s.popup?.kind === a.popup.kind && s.popup.anchor === a.popup.anchor;
      return { ...s, popup: same ? null : a.popup };
    }
    case "help":
      return { ...s, help: a.open, left: a.open && s.env.mobile ? false : s.left };
    case "rail":
      return { ...s, railOpen: a.open };
    case "image-input":
      return compactRp(s) ? { ...s, panel: null, left: false } : s;
    case "layout-menu":
      return a.open ? { ...s, chooser: null } : s;
  }
}

/**
 * Whether going from `prev` to `next` leaves the view the user is looking at, so leave guards
 * (unsaved drafts, running resource actions) must agree first. `shown` is the panel on screen,
 * which may be hover-revealed: pinning it is not leaving it.
 */
export function leaves(prev: LayoutState, next: LayoutState, shown: Panel) {
  if (next.panel !== prev.panel && next.panel !== shown) return true;
  if (next.panel && next.focusId !== prev.focusId) return true;
  if (next.deep !== prev.deep) return true;
  if (next.workspace && next.workspace !== prev.workspace) return true;
  // PWA drawers replace the whole screen.
  return prev.env.mobile && next.left !== prev.left;
}
