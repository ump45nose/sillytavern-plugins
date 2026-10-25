import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";
import {
  Activity,
  BookMarked,
  BookOpen,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Expand,
  Eye,
  EyeOff,
  Folder,
  ImagePlus,
  Menu,
  MenuDrawer,
  MoreHorizontal,
  PanelsTopLeft,
  PencilLine,
  Plug,
  ScanLine,
  Plus,
  Settings,
  SlidersHorizontal,
  Theater,
  UserRound,
  Users,
  WandSparkles,
  X,
} from "./icons";
import type { HostAdapter } from "../host/adapter";
import type { HostSnapshot, Panel, Resource, SettingsPage } from "../host/types";
import type { LayoutMode } from "./LayoutSwitcher";
import type { ComposerPopup } from "./ComposerPopovers";
import { ResourceControls } from "./Header";
import { resourceLabels } from "../host/labels";
import { ReadingSettings } from "./Reading";
import { OptionsSheetList } from "./StoryOptions";
import { toolIcon } from "./ToolIcon";
import { useComposerTools } from "./useTools";
import { useDatabase } from "./useDatabase";
import { motionAllowed, usePresence } from "./Motion";
import { bus } from "../host/bus";

type Sheet = "management" | "tools" | "options" | HTMLElement | null;
const resourceIcons = { connection: Plug, preset: SlidersHorizontal, world: BookMarked, persona: UserRound };
const interactive = "button,input,textarea,select,a,[contenteditable=true],iframe,video";
export function MobileShell({
  host,
  snap,
  rp,
  left,
  panel,
  chooser,
  setChooser,
  goPanel,
  toggleLeft,
  closeDrawers,
  onLayout,
  settings,
  open,
  activate,
  select,
  focus,
  toggleFocus,
}: {
  host: HostAdapter;
  snap: HostSnapshot;
  rp: boolean;
  left: boolean;
  panel: Panel;
  chooser: Resource | null;
  setChooser: (kind: Resource | null) => void;
  goPanel: (panel: Panel, id?: string) => void;
  toggleLeft: () => void;
  closeDrawers: () => void;
  onLayout: (mode: LayoutMode) => void;
  settings: (page: SettingsPage, group?: string) => void;
  open: (popup: ComposerPopup) => void;
  activate: (id: string, anchor: HTMLElement) => void;
  select: (kind: Resource, id: string, on: boolean) => void;
  /** Focus mode: Noval keeps only the reading and the composer; RP hides every pane. */
  focus: boolean;
  toggleFocus: () => void;
}) {
  const [sheet, setSheet] = useState<Sheet>(null),
    [editor, setEditor] = useState(false),
    [length, setLength] = useState(0);
  const presence = usePresence(sheet),
    sheetRef = useRef<HTMLDivElement>(null),
    input = document.getElementById("send_textarea") as HTMLTextAreaElement,
    form = document.getElementById("send_form")!,
    dock = document.getElementById("form_sheld")!,
    stage = document.getElementById("sheld")!,
    items = document.getElementById("nonQRFormItems")!;
  const latest = useRef({ left, panel, editor, sheet });
  latest.current = { left, panel, editor, sheet };
  const close = () => {
      setSheet(null);
      setChooser(null);
    },
    setEditing = (value: boolean) => {
      setSheet(null);
      setChooser(null);
      setEditor(value);
    };
  // The pill (Noval) or the compose band (RP) grows into the full-screen editor and shrinks back
  // into it. The page is the native #form_sheld let out of the flow ([data-wb-page]); Noval's #chat
  // keeps its place with a margin where the pill was. While the page moves, #sheld[data-wb-rise]
  // lifts it over the header; once it covers the window, body[data-wb-covered] hides what is
  // underneath. The motion is a Web Animation of the page's translate and horizontal scale from the
  // pill's top edge and width, with its top corners rounded meanwhile: compositor-only, so no
  // repaint per frame, no class changes mid-motion, and the textarea stays the same node.
  const motion = useRef<Animation[]>([]),
    pull = useRef<{
      y: number;
      pointer: number;
      dy: number;
      previous: { y: number; t: number };
      last: { y: number; t: number };
    } | null>(null);
  const settle = () => {
    motion.current.forEach((a) => a.cancel());
    motion.current = [];
  };
  const moving = (on: boolean) => {
    if (on) {
      stage.dataset.wbRise = "";
      delete document.body.dataset.wbCovered;
      dock.style.setProperty("border-radius", "24px 24px 0 0");
    } else {
      delete stage.dataset.wbRise;
      document.body.dataset.wbCovered = "";
      dock.style.removeProperty("border-radius");
    }
  };
  const letGo = () => {
    settle();
    delete dock.dataset.wbPage;
    delete stage.dataset.wbRise;
    delete document.body.dataset.wbCovered;
    dock.style.removeProperty("translate");
    dock.style.removeProperty("border-radius");
    document.getElementById("chat")!.style.removeProperty("margin-bottom");
  };
  // RP's band fades in over its first rows; the page grows from, and folds back to, where it is solid.
  const bandFade = rp ? 40 : 0;
  const pillShape = (page: DOMRect, pill: DOMRect, top = pill.top + bandFade) => ({
    translate: `0 ${top - page.top}px`,
    scale: `${pill.width / page.width} 1`,
  });
  const openPage = (rise = 0) => {
    if (latest.current.editor) return;
    settle();
    const pill = form.getBoundingClientRect(),
      duration = motionAllowed() ? 340 : 0;
    delete dock.dataset.wbDrag;
    dock.style.removeProperty("--wb-rise");
    dock.style.removeProperty("--wb-rise-fade");
    if (!rp) document.getElementById("chat")!.style.setProperty("margin-bottom", `${dock.offsetHeight}px`);
    dock.dataset.wbPage = "";
    moving(true);
    const page = dock.getBoundingClientRect(),
      grow = dock.animate(
        [pillShape(page, pill, pill.top + bandFade - rise), { translate: "0 0", scale: "1 1" }],
        { duration, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" },
      );
    motion.current = [
      grow,
      form.animate([{ opacity: 0 }, { opacity: 1 }], {
        duration: duration * 0.6,
        delay: duration * 0.3,
        easing: "ease-out",
        fill: "backwards",
      }),
    ];
    grow.finished.then(
      () => moving(false),
      () => {},
    );
    flushSync(() => setEditing(true));
  };
  const closePage = (from = 0) => {
    if (!latest.current.editor) return;
    settle();
    dock.style.removeProperty("translate");
    // The pill's place is measured with the page back in the flow for a moment; the reading's
    // scroll is put back, as the shorter chat may have clamped it.
    const chat = document.getElementById("chat")!,
      page = dock.getBoundingClientRect(),
      margin = chat.style.getPropertyValue("margin-bottom"),
      scroll = chat.scrollTop;
    delete dock.dataset.wbPage;
    chat.style.removeProperty("margin-bottom");
    const pill = form.getBoundingClientRect(),
      duration = motionAllowed() ? 300 : 0;
    chat.style.setProperty("margin-bottom", margin);
    chat.scrollTo({ top: scroll, behavior: "instant" });
    dock.dataset.wbPage = "";
    moving(true);
    const shrink = dock.animate([{ translate: `0 ${from}px`, scale: "1 1" }, pillShape(page, pill)], {
      duration,
      easing: "cubic-bezier(0.4, 0, 0.2, 1)",
      fill: "forwards",
    });
    motion.current = [
      shrink,
      form.animate([{ opacity: 1 }, { opacity: 0 }], {
        duration: duration * 0.45,
        easing: "ease-in",
        fill: "forwards",
      }),
    ];
    shrink.finished.then(
      () => {
        letGo();
        motion.current = [
          form.animate([{ opacity: 0 }, { opacity: 1 }], { duration: duration * 0.5, easing: "ease-out" }),
        ];
      },
      () => {},
    );
    flushSync(() => setEditing(false));
  };
  const edit = (value: boolean) => (value ? openPage() : closePage());
  // Pulling the page down: it follows the finger, then folds back into the pill or band past a
  // fifth of its height or on a flick, and otherwise springs back up.
  const pullFrom = (pointer: number, y: number, t: number) => {
    const at = { y, t };
    pull.current = { y, pointer, dy: 0, previous: at, last: at };
    settle();
    moving(true);
  };
  const pullTo = (y: number, t: number) => {
    const current = pull.current!;
    current.dy = Math.max(0, y - current.y);
    current.previous = current.last;
    current.last = { y, t };
    dock.style.setProperty("translate", `0 ${current.dy}px`);
  };
  const letPull = () => {
    const current = pull.current!;
    pull.current = null;
    const speed = (current.last.y - current.previous.y) / Math.max(1, current.last.t - current.previous.t);
    if (speed > 0.5 || current.dy > dock.offsetHeight * 0.18) return closePage(current.dy);
    dock.style.removeProperty("translate");
    const back = dock.animate([{ translate: `0 ${current.dy}px` }, { translate: "0 0" }], {
      duration: motionAllowed() ? 240 : 0,
      easing: "cubic-bezier(0.2, 0.8, 0.2, 1)",
    });
    motion.current = [back];
    back.finished.then(
      () => moving(false),
      () => {},
    );
  };
  const dropPull = () => {
    if (!pull.current) return;
    pull.current = null;
    dock.style.removeProperty("translate");
    moving(false);
  };
  const presentation = host.rpPresentation();
  // Novel names the story; RP names the scene, falling back to the story when the card has none.
  const scene = (key: string) => {
      const value = presentation.scene?.[key];
      return typeof value === "string" || typeof value === "number" ? String(value) : "";
    },
    who = snap.character?.name || snap.groupName || "选择角色",
    title = (rp && scene("location")) || snap.chatName || who,
    subtitle =
      rp && scene("location")
        ? [scene("time"), scene("weather")].filter(Boolean).join(" · ") || who
        : snap.chatName
          ? `${who} · ${snap.messages.length} 层`
          : "开始一段新的故事";
  const worlds = snap.resources.world.filter((x) => x.active),
    summary = [
      snap.resources.preset.find((x) => x.id === snap.current.preset)?.name,
      worlds.length ? worlds[0].name + (worlds.length > 1 ? ` +${worlds.length - 1}` : "") : "",
    ]
      .filter(Boolean)
      .join(" · ");
  // Every class written on <body> makes SillyTavern's keyboard.js rescan the whole page, so these
  // change only when their value does and are removed only on unmount.
  useLayoutEffect(() => {
    document.body.classList.toggle("wb-mobile-busy", snap.busy);
    document.body.classList.toggle("wb-mobile-offline", !snap.online);
  }, [snap.busy, snap.online]);
  useLayoutEffect(() => () => document.body.classList.remove("wb-mobile-busy", "wb-mobile-offline"), []);
  useEffect(() => {
    setSheet(null);
    setEditor(false);
    letGo();
  }, [rp, snap.chatName, snap.character?.id]);
  useEffect(() => {
    // A draft taller than the pill scrolls under the finger; a short one lets the pill be pulled up.
    const changed = () => {
      setLength(input.value.length);
      input.toggleAttribute("data-wb-overflow", input.scrollHeight > input.clientHeight + 1);
    };
    changed();
    input.addEventListener("input", changed);
    const image = () => {
      setSheet(null);
      setEditor(false);
      closeDrawers();
    };
    const off = [
      bus.on("image-compose", image),
      // The story options open over whatever is reading, never over a drawer or the editor.
      bus.on("story-options", () => {
        const now = latest.current;
        if (host.options.state.items.length && !now.left && !now.panel && !now.editor && !now.sheet)
          setSheet("options");
      }),
      // A floor picked in the outline is also selected, so its tools are one tap away.
      bus.on("floor-jump", (id) => {
        const chat = document.getElementById("chat")!;
        chat.querySelectorAll(".wb-mobile-actions").forEach((n) => n.classList.remove("wb-mobile-actions"));
        chat.querySelector(`.mes[mesid="${id}"]`)?.classList.add("wb-mobile-actions");
      }),
    ];
    return () => {
      input.removeEventListener("input", changed);
      input.removeAttribute("data-wb-overflow");
      off.forEach((f) => f());
    };
  }, []);
  // The page lets go of the native nodes whenever the editor closes without its motion (a chat or
  // layout change), and on unmount.
  useLayoutEffect(() => {
    if (!editor && !motion.current.length) letGo();
  }, [editor]);
  useEffect(
    () => () => {
      letGo();
      delete dock.dataset.wbDrag;
      for (const name of ["--wb-rise", "--wb-rise-fade"]) dock.style.removeProperty(name);
    },
    [],
  );
  // Pulling the pill (Noval) or the compose band (RP) up grows it with the finger; past the
  // threshold, or on a flick, it carries on into the full editor, otherwise it settles back. The
  // band grows through RPStage's --wb-rp-pull, its card through --wb-rise. Pulling RP's band down
  // slides it after the finger and, let go far enough, returns to the dialogue. The whole field
  // takes the gesture, the draft included: touch events, since a focused field's own touch
  // handling cancels pointer events. Inside a long draft the finger scrolls it until it reaches
  // the end it is moving toward; a press held before moving is left to text selection.
  useEffect(() => {
    if (editor) return;
    let drag: {
      id: number;
      x: number;
      y: number;
      t: number;
      draft: boolean;
      room: number;
      up: boolean;
      rise: number;
      started: boolean;
      previous: { y: number; t: number };
      last: { y: number; t: number };
    } | null = null;
    const reset = () => {
      delete dock.dataset.wbDrag;
      delete document.body.dataset.wbBandDrag;
      delete document.body.dataset.wbBandLower;
      dock.style.removeProperty("--wb-rise");
      dock.style.removeProperty("--wb-rise-fade");
      document.body.style.removeProperty("--wb-rp-pull");
    };
    const down = (e: TouchEvent) => {
      drag = null;
      const target = e.target as Element;
      if (e.touches.length !== 1 || target.closest("button,a,select")) return;
      if (rp && !document.body.hasAttribute("data-wb-rp-compose")) return;
      const t = e.touches[0],
        at = { y: t.clientY, t: e.timeStamp };
      drag = {
        id: t.identifier,
        x: t.clientX,
        y: t.clientY,
        t: e.timeStamp,
        draft: input.contains(target) || !!target.closest(".wb-composer-md"),
        // RP's band may rise to just under the header.
        room: rp
          ? stage.getBoundingClientRect().top - (headerRef.current?.getBoundingClientRect().bottom ?? 0) - 16
          : form.getBoundingClientRect().top - stage.getBoundingClientRect().top,
        up: true,
        rise: 0,
        started: false,
        previous: at,
        last: at,
      };
    };
    const move = (e: TouchEvent) => {
      const t = [...e.changedTouches].find((touch) => touch.identifier === drag?.id);
      if (!drag || !t) return;
      const dy = drag.y - t.clientY;
      if (!drag.started) {
        const dx = t.clientX - drag.x;
        if (Math.hypot(dx, dy) < 8) return;
        const up = dy > 0,
          scrolls =
            drag.draft &&
            (up ? input.scrollTop + input.clientHeight < input.scrollHeight - 1 : input.scrollTop > 0);
        if (Math.abs(dx) > Math.abs(dy) || e.timeStamp - drag.t > 400 || (!up && !rp) || scrolls)
          return void (drag = null);
        drag.started = true;
        drag.up = up;
        if (rp) document.body.dataset.wbBandDrag = "";
        else dock.dataset.wbDrag = "";
        // Only a downward pull moves the band itself: a translated #sheld would hold the page.
        if (!up) document.body.dataset.wbBandLower = "";
      }
      e.preventDefault();
      drag.previous = drag.last;
      drag.last = { y: t.clientY, t: e.timeStamp };
      if (!drag.up) {
        drag.rise = Math.min(0, dy);
        document.body.style.setProperty("--wb-rp-pull", `${Math.min(160, -dy * 0.6)}px`);
        return;
      }
      drag.rise = Math.min(drag.room, Math.max(0, dy));
      if (rp) document.body.style.setProperty("--wb-rp-pull", `${-drag.rise}px`);
      else {
        dock.style.setProperty("--wb-rise", `${drag.rise}px`);
        dock.style.setProperty("--wb-rise-fade", String(Math.min(0.75, drag.rise / 160)));
      }
    };
    const up = (e: TouchEvent) => {
      const current = drag;
      if (!current || ![...e.changedTouches].some((touch) => touch.identifier === current.id)) return;
      drag = null;
      if (!current.started) return;
      const speed = (current.previous.y - current.last.y) / Math.max(1, current.last.t - current.previous.t);
      if (!current.up) {
        reset();
        if (speed < -0.45 || current.rise < -72) bus.emit("rp-dialogue");
      } else if (speed > 0.45 || current.rise > 72) {
        // The band is already as tall as the finger made it: the page grows from there, and the
        // band settles back under it once it has covered the window.
        openPage(rp ? 0 : current.rise);
        if (rp) motion.current[0]?.finished.then(reset, reset);
      } else reset();
    };
    const cancel = () => {
      drag = null;
      reset();
    };
    form.addEventListener("touchstart", down, { passive: true });
    form.addEventListener("touchmove", move, { passive: false });
    form.addEventListener("touchend", up);
    form.addEventListener("touchcancel", cancel);
    return () => {
      form.removeEventListener("touchstart", down);
      form.removeEventListener("touchmove", move);
      form.removeEventListener("touchend", up);
      form.removeEventListener("touchcancel", cancel);
      reset();
    };
  }, [rp, editor]);
  // The whole upper half of the page pulls it down too, while the draft is scrolled to its top: a
  // downward drag there folds the page instead of scrolling (touch events, which can stop the
  // scroll). A press held before moving is left to text selection.
  useEffect(() => {
    if (!editor) return;
    let start: { id: number; x: number; y: number; t: number } | null = null;
    const down = (e: TouchEvent) => {
      start = null;
      const t = e.touches[0],
        page = dock.getBoundingClientRect();
      if (e.touches.length !== 1 || pull.current || t.clientY > page.top + page.height / 2) return;
      if ((e.target as Element).closest("button,a,select") || input.scrollTop > 0) return;
      start = { id: t.identifier, x: t.clientX, y: t.clientY, t: e.timeStamp };
    };
    const move = (e: TouchEvent) => {
      const t = [...e.changedTouches].find((touch) => touch.identifier === start?.id);
      if (!start || !t) return;
      if (pull.current?.pointer !== -1) {
        const dx = t.clientX - start.x,
          dy = t.clientY - start.y;
        if (Math.hypot(dx, dy) < 8) return;
        if (dy <= 0 || Math.abs(dx) > dy || e.timeStamp - start.t > 400) return void (start = null);
        pullFrom(-1, start.y, start.t);
      }
      e.preventDefault();
      pullTo(t.clientY, e.timeStamp);
    };
    const up = () => {
      start = null;
      if (pull.current?.pointer === -1) letPull();
    };
    const cancel = () => {
      start = null;
      if (pull.current?.pointer === -1) dropPull();
    };
    dock.addEventListener("touchstart", down, { passive: true });
    dock.addEventListener("touchmove", move, { passive: false });
    dock.addEventListener("touchend", up);
    dock.addEventListener("touchcancel", cancel);
    return () => {
      dock.removeEventListener("touchstart", down);
      dock.removeEventListener("touchmove", move);
      dock.removeEventListener("touchend", up);
      dock.removeEventListener("touchcancel", cancel);
    };
  }, [editor]);
  useLayoutEffect(() => {
    const chat = document.getElementById("sheld")!,
      previous = chat.inert;
    chat.inert = left || !!panel || !!sheet;
    return () => {
      chat.inert = previous;
    };
  }, [left, panel, sheet]);
  useLayoutEffect(() => {
    const target = left
      ? document.querySelector<HTMLElement>(".wb-left")
      : panel
        ? document.querySelector<HTMLElement>(".wb-right")
        : sheet
          ? sheetRef.current
          : null;
    if (!target) return;
    const previous = document.activeElement as HTMLElement,
      frame = requestAnimationFrame(() => {
        const close = document.querySelector<HTMLElement>(
          left ? ".wb-mobile-drawer-close" : ".wb-panel-close",
        );
        (sheet ? sheetRef.current?.querySelector<HTMLElement>("button") : close)?.focus({
          preventScroll: true,
        });
      });
    const key = (e: KeyboardEvent) => {
      if (
        (document.activeElement as Element)?.closest(
          ".wb-mobile-resource-popup,.wb-resource-menu,.wb-popover",
        )
      )
        return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        sheet ? close() : closeDrawers();
      }
      if (e.key === "Tab") {
        const nodes = [
          ...(sheet ? target : document.body).querySelectorAll<HTMLElement>(
            sheet
              ? 'button:not(:disabled),input:not([type=hidden]),textarea,select,[tabindex="0"]'
              : ".wb-mobile-drawer-close, .wb-left.is-open button:not(:disabled),.wb-left.is-open input,.wb-right.is-open button:not(:disabled),.wb-right.is-open input,.wb-right.is-open textarea",
          ),
        ].filter((n) => !n.closest("[inert]") && n.getBoundingClientRect().height > 0);
        const index = nodes.indexOf(document.activeElement as HTMLElement);
        if (!nodes.length) return;
        if (e.shiftKey && index <= 0) {
          e.preventDefault();
          nodes.at(-1)?.focus();
        } else if (!e.shiftKey && (index < 0 || index === nodes.length - 1)) {
          e.preventDefault();
          nodes[0].focus();
        }
      }
    };
    document.addEventListener("keydown", key, true);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", key, true);
      if (previous?.isConnected && previous.tagName !== "TEXTAREA") previous.focus({ preventScroll: true });
    };
  }, [left, panel, !!sheet]);
  // The panel's tab row scrolls; keep the open tab in view.
  useEffect(() => {
    if (!panel) return;
    const frame = requestAnimationFrame(() => {
      const tab = document.querySelector<HTMLElement>(".wb-right .wb-panel-tab.is-active"),
        row = tab?.parentElement;
      row?.scrollTo({
        left: tab!.offsetLeft - row.offsetLeft - (row.clientWidth - tab!.offsetWidth) / 2,
        behavior: motionAllowed() ? "smooth" : "auto",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [panel]);
  // RP: a long press on the latest reply opens its actions (the dialogue box itself turns pages).
  useEffect(() => {
    const chat = document.getElementById("chat")!;
    let press: ReturnType<typeof setTimeout> | undefined,
      origin: { x: number; y: number } | null = null;
    const cancel = () => {
      clearTimeout(press);
      press = undefined;
      origin = null;
    };
    const down = (e: PointerEvent) => {
      if (!rp || e.button !== 0 || e.pointerType !== "touch") return;
      const message = (e.target as Element).closest<HTMLElement>(".mes");
      if (
        !message ||
        message !== chat.querySelector(".mes:last-child") ||
        message.getAttribute("is_user") === "true"
      )
        return;
      origin = { x: e.clientX, y: e.clientY };
      press = setTimeout(() => {
        cancel();
        setSheet(message);
      }, 550);
    };
    const move = (e: PointerEvent) => {
      if (origin && Math.hypot(e.clientX - origin.x, e.clientY - origin.y) > 10) cancel();
    };
    const context = (e: MouseEvent) => {
      if (!rp) return;
      const message = (e.target as Element).closest<HTMLElement>(".mes");
      if (message === chat.querySelector(".mes:last-child") && message?.getAttribute("is_user") !== "true") {
        e.preventDefault();
        setSheet(message);
      }
    };
    // Native swipe events normally change reply candidates; on the phone a sideways drag moves the drawers.
    const nativeSwipe = (e: Event) => {
      if ((e.target as Element)?.closest("#chat") && !(e.target as Element).closest(interactive))
        e.stopImmediatePropagation();
    };
    chat.addEventListener("pointerdown", down);
    chat.addEventListener("pointermove", move);
    chat.addEventListener("pointerup", cancel);
    chat.addEventListener("pointercancel", cancel);
    chat.addEventListener("contextmenu", context);
    document.addEventListener("swiped-left", nativeSwipe, true);
    document.addEventListener("swiped-right", nativeSwipe, true);
    return () => {
      cancel();
      chat.removeEventListener("pointerdown", down);
      chat.removeEventListener("pointermove", move);
      chat.removeEventListener("pointerup", cancel);
      chat.removeEventListener("pointercancel", cancel);
      chat.removeEventListener("contextmenu", context);
      document.removeEventListener("swiped-left", nativeSwipe, true);
      document.removeEventListener("swiped-right", nativeSwipe, true);
    };
  }, [rp]);
  // Drawers follow the finger. A sideways drag on the reading (RP: the scene around the dialogue box)
  // pulls the outline out from the left or the panel from the right; a drag on an open drawer or its
  // shade pushes it back. On release, a flick or more than 40% shown decides.
  useEffect(() => {
    type Drag = {
      x: number;
      y: number;
      t: number;
      pointer: number;
      target: Element;
      opening: boolean;
      side?: "left" | "right";
      node?: HTMLElement;
      width?: number;
      shown?: number;
      previous: { x: number; t: number };
      last: { x: number; t: number };
    };
    let drag: Drag | null = null;
    // Drag state lives in data attributes and inline styles on the drawer and its shade only: class
    // writes wake SillyTavern's keyboard observer, and anything on <body> restyles the whole page.
    const shade = () => document.querySelector<HTMLElement>(".wb-mobile-shade");
    const release = (node?: HTMLElement) => {
      if (!node) return;
      delete node.dataset.wbDrag;
      node.style.removeProperty("--wb-drawer-x");
      const veil = shade();
      if (veil) {
        delete veil.dataset.wbDrag;
        veil.style.removeProperty("opacity");
      }
    };
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || e.pointerType !== "touch") return;
      const target = e.target as Element,
        state = latest.current;
      if (state.editor || state.sheet) return;
      const open = state.left || !!state.panel;
      if (open) {
        if (!target.closest(".wb-left,.wb-right,.wb-mobile-shade")) return;
        if (
          target.closest(
            "input,textarea,select,[contenteditable=true],.wb-panel-tabs,.wb-mobile-resource-popup",
          )
        )
          return;
      } else {
        // Selecting text in the reading is not a swipe.
        const selection = getSelection(),
          anchor = selection?.anchorNode,
          inReading = (anchor instanceof Element ? anchor : anchor?.parentElement)?.closest("#chat");
        if (target.closest(interactive) || (selection?.toString() && inReading)) return;
        if (rp ? target.closest(".wb-ui,#sheld,.wb-mobile-header") : !target.closest("#chat")) return;
      }
      const at = { x: e.clientX, t: e.timeStamp };
      drag = {
        x: e.clientX,
        y: e.clientY,
        t: e.timeStamp,
        pointer: e.pointerId,
        target,
        opening: !open,
        side: open ? (state.left ? "left" : "right") : undefined,
        previous: at,
        last: at,
      };
    };
    const move = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.pointer) return;
      const dx = e.clientX - drag.x,
        dy = e.clientY - drag.y;
      if (!drag.node) {
        if (Math.hypot(dx, dy) < 10) return;
        if (Math.abs(dx) < Math.abs(dy) * 1.2) {
          drag = null;
          return;
        }
        drag.side ??= dx > 0 ? "left" : "right";
        drag.node = document.querySelector<HTMLElement>(drag.side === "left" ? ".wb-left" : ".wb-right")!;
        drag.width = drag.node.offsetWidth;
        drag.node.dataset.wbDrag = "";
        const veil = shade();
        if (veil) veil.dataset.wbDrag = "";
      }
      const toward = drag.side === "left" ? dx : -dx,
        shown = Math.min(drag.width!, Math.max(0, drag.opening ? toward : drag.width! + toward));
      drag.shown = shown;
      drag.previous = drag.last;
      drag.last = { x: e.clientX, t: e.timeStamp };
      drag.node.style.setProperty("--wb-drawer-x", `${shown}px`);
      shade()?.style.setProperty("opacity", String(shown / drag.width!));
    };
    const up = (e: PointerEvent) => {
      const current = drag;
      drag = null;
      if (!current?.node || e.pointerId !== current.pointer) return;
      const sign = current.side === "left" ? 1 : -1,
        speed =
          ((current.last.x - current.previous.x) * sign) / Math.max(1, current.last.t - current.previous.t),
        travel = (e.clientX - current.x) * sign,
        quick = e.timeStamp - current.t < 300 && Math.abs(travel) > 40,
        flick = speed > 0.35 ? true : speed < -0.35 ? false : quick ? travel > 0 : null,
        open = flick ?? current.shown! > current.width! * 0.4;
      // The new state and the drag styles leave in one frame, so the slide continues from the finger.
      flushSync(() => {
        if (open && current.opening) current.side === "left" ? toggleLeft() : goPanel("character");
        if (!open && !current.opening) closeDrawers();
      });
      release(current.node);
      // A drag that began on a row or the shade must not also click it.
      const swallow = (click: Event) => {
        document.removeEventListener("click", swallow, true);
        if (!current.target.contains(click.target as Node)) return;
        click.stopPropagation();
        click.preventDefault();
      };
      document.addEventListener("click", swallow, true);
      setTimeout(() => document.removeEventListener("click", swallow, true), 300);
    };
    const cancel = () => {
      release(drag?.node);
      drag = null;
    };
    document.addEventListener("pointerdown", down);
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", cancel);
    return () => {
      cancel();
      document.removeEventListener("pointerdown", down);
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", cancel);
    };
  }, [rp, toggleLeft, goPanel, closeDrawers]);
  // Phones have no hover: a tap on a Novel message shows its tools, a second tap or another message hides them.
  useEffect(() => {
    if (rp) return;
    const chat = document.getElementById("chat")!;
    const tap = (e: MouseEvent) => {
      const target = e.target as Element,
        message = target.closest<HTMLElement>(".mes");
      if (!message || target.closest(`${interactive},[role=button]`) || getSelection()?.toString()) return;
      const shown = message.classList.contains("wb-mobile-actions");
      chat.querySelectorAll(".wb-mobile-actions").forEach((n) => n.classList.remove("wb-mobile-actions"));
      if (!shown) message.classList.add("wb-mobile-actions");
    };
    chat.addEventListener("click", tap);
    return () => {
      chat.removeEventListener("click", tap);
      chat.querySelectorAll(".wb-mobile-actions").forEach((n) => n.classList.remove("wb-mobile-actions"));
    };
  }, [rp]);
  // A sheet follows its handle away from its edge (down for the bottom sheets, up for the session
  // menu that hangs from the top); past a third of its height or on a flick it closes, otherwise it
  // settles back.
  useEffect(() => {
    const node = sheetRef.current;
    if (!node || presence.exiting) return;
    let drag: {
      y: number;
      pointer: number;
      dy: number;
      previous: { y: number; t: number };
      last: { y: number; t: number };
    } | null = null;
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || !(e.target as Element).closest(".wb-mobile-sheet-grip,.wb-mobile-sheet > header"))
        return;
      if ((e.target as Element).closest("button")) return;
      const at = { y: e.clientY, t: e.timeStamp };
      drag = { y: e.clientY, pointer: e.pointerId, dy: 0, previous: at, last: at };
      node.dataset.wbDrag = "";
    };
    const top = node.classList.contains("is-management");
    const move = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.pointer) return;
      drag.dy = top ? Math.min(0, e.clientY - drag.y) : Math.max(0, e.clientY - drag.y);
      drag.previous = drag.last;
      drag.last = { y: e.clientY, t: e.timeStamp };
      node.style.setProperty("--wb-sheet-pull", `${drag.dy}px`);
    };
    const up = (e: PointerEvent) => {
      const current = drag;
      drag = null;
      if (!current || e.pointerId !== current.pointer) return;
      const speed =
        ((current.last.y - current.previous.y) / Math.max(1, current.last.t - current.previous.t)) *
        (top ? -1 : 1);
      delete node.dataset.wbDrag;
      if (speed > 0.5 || Math.abs(current.dy) > node.offsetHeight / 3) close();
      else node.style.removeProperty("--wb-sheet-pull");
    };
    node.addEventListener("pointerdown", down);
    node.addEventListener("pointermove", move);
    node.addEventListener("pointerup", up);
    node.addEventListener("pointercancel", up);
    return () => {
      node.removeEventListener("pointerdown", down);
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerup", up);
      node.removeEventListener("pointercancel", up);
    };
  }, [presence.value, presence.exiting]);
  // Pulling the header down draws the session menu down with the finger. Once the menu is
  // up the header is inert, so the drag is followed on the document.
  const headerRef = useRef<HTMLElement>(null);
  const database = useDatabase(host);
  const { tools, disabled: toolDisabled } = useComposerTools(host, snap.busy);
  useEffect(() => {
    const header = headerRef.current;
    if (!header) return;
    const veil = () => document.querySelector<HTMLElement>(".wb-mobile-sheet-shade");
    let drag: {
      y: number;
      pointer: number;
      dy: number;
      height: number;
      started: boolean;
      previous: { y: number; t: number };
      last: { y: number; t: number };
    } | null = null;
    const move = (e: PointerEvent) => {
      if (!drag || e.pointerId !== drag.pointer) return;
      const dy = e.clientY - drag.y;
      if (!drag.started) {
        if (Math.abs(dy) < 8) return;
        if (dy < 0) return end();
        drag.started = true;
        flushSync(() => setSheet("management"));
        const node = sheetRef.current!;
        node.dataset.wbDrag = "";
        node.style.setProperty("animation", "none");
        veil()?.style.setProperty("animation", "none");
        drag.height = node.offsetHeight;
      }
      drag.dy = Math.min(drag.height, Math.max(0, dy));
      drag.previous = drag.last;
      drag.last = { y: e.clientY, t: e.timeStamp };
      sheetRef.current!.style.setProperty("--wb-sheet-pull", `${drag.dy - drag.height}px`);
      veil()?.style.setProperty("opacity", String(drag.dy / drag.height));
    };
    const up = (e: PointerEvent) => {
      const current = drag;
      end();
      if (!current?.started || e.pointerId !== current.pointer) return;
      dragged = e.timeStamp;
      const node = sheetRef.current!,
        speed = (current.last.y - current.previous.y) / Math.max(1, current.last.t - current.previous.t);
      delete node.dataset.wbDrag;
      if (e.type === "pointerup" && (speed > 0.45 || (speed > -0.45 && current.dy > current.height * 0.35))) {
        node.style.removeProperty("--wb-sheet-pull");
        veil()?.style.setProperty("transition", "opacity 260ms");
        veil()?.style.setProperty("opacity", "1");
      } else close();
    };
    const end = () => {
      drag = null;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
    };
    const down = (e: PointerEvent) => {
      const state = latest.current;
      if (e.button !== 0 || e.pointerType === "mouse") return;
      if ((e.target as Element).closest("button:not(.wb-mobile-title)")) return;
      if (state.sheet || state.left || state.panel || state.editor) return;
      if (document.body.classList.contains("wb-focus")) return;
      const at = { y: e.clientY, t: e.timeStamp };
      drag = { y: e.clientY, pointer: e.pointerId, dy: 0, height: 0, started: false, previous: at, last: at };
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
      document.addEventListener("pointercancel", up);
    };
    // A drag that started on RP's title is not also a tap on it.
    let dragged = -Infinity;
    const swallow = (e: MouseEvent) => {
      if (e.timeStamp - dragged < 400) e.stopPropagation();
    };
    header.addEventListener("pointerdown", down);
    header.addEventListener("click", swallow, true);
    return () => {
      end();
      header.removeEventListener("pointerdown", down);
      header.removeEventListener("click", swallow, true);
    };
  }, []);
  // A sheet that was drawn by the finger hands its motion back to the exit animation.
  useLayoutEffect(() => {
    if (!presence.exiting) return;
    sheetRef.current?.style.removeProperty("animation");
    const shade = document.querySelector<HTMLElement>(".wb-mobile-sheet-shade");
    for (const name of ["animation", "opacity", "transition"]) shade?.style.removeProperty(name);
  }, [presence.exiting]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && editor) {
        e.preventDefault();
        edit(false);
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [editor]);
  const resources = (
    <ResourceControls
      snap={snap}
      panel={panel}
      chooser={chooser}
      setChooser={setChooser}
      goPanel={(next, id) => {
        close();
        goPanel(next, id);
      }}
      select={select}
      model={host.model()}
    />
  );
  const nativeAction = (selector: string) => {
    close();
    const control = (sheet instanceof HTMLElement ? sheet : document).querySelector<HTMLElement>(selector);
    control?.click();
  };
  const goSettings = (page: SettingsPage) => {
    close();
    settings(page);
  };
  return (
    <>
      <header
        ref={headerRef}
        className="wb-mobile-header wb-ui"
        inert={left || !!panel || !!sheet || editor || (focus && !rp)}
      >
        <button
          className="wb-mobile-nav"
          aria-label="打开大纲与导航"
          aria-expanded={left}
          onClick={toggleLeft}
        >
          <MenuDrawer size={21} />
        </button>
        {/* RP: the scene's name is the way to the session menu (as is pulling the header down). */}
        {rp ? (
          <button
            className="wb-mobile-title"
            aria-label="打开会话管理"
            aria-expanded={sheet === "management"}
            onClick={() => setSheet("management")}
          >
            <strong>{title}</strong>
            <small>{subtitle}</small>
          </button>
        ) : (
          <>
            <button
              className="wb-mobile-management"
              aria-label="打开会话管理"
              aria-expanded={sheet === "management"}
              onClick={() => setSheet("management")}
            >
              <MoreHorizontal size={21} strokeWidth={2.4} />
            </button>
            <div className="wb-mobile-title">
              <strong>{title}</strong>
              <small>{subtitle}</small>
            </div>
          </>
        )}
        <button
          className="wb-mobile-person"
          aria-label={rp ? (focus ? "显示界面" : "隐藏界面") : "打开角色与 Trace"}
          aria-pressed={rp ? focus : undefined}
          aria-expanded={rp ? undefined : !!panel}
          onClick={() => (rp ? toggleFocus() : goPanel("character"))}
        >
          {rp ? (
            focus ? (
              <Eye size={20} />
            ) : (
              <EyeOff size={20} />
            )
          ) : snap.character?.image ? (
            <span className="wb-mobile-face">
              <img src={snap.character.image} alt="" />
            </span>
          ) : (
            <span className="wb-avatar-fallback">N</span>
          )}
        </button>
      </header>
      <button
        className={`wb-mobile-shade ${left || panel ? "is-open" : ""}`}
        aria-label="收起边栏"
        aria-hidden={!(left || panel)}
        tabIndex={left || panel ? 0 : -1}
        onClick={closeDrawers}
      />
      {/* The panel closes from the end of its own tab row. */}
      {left && (
        <>
          <span className="wb-mobile-drawer-title wb-ui">大纲与导航</span>
          <button
            className="wb-mobile-drawer-close is-left wb-ui"
            aria-label="关闭边栏"
            onClick={closeDrawers}
          >
            <X size={20} />
          </button>
        </>
      )}
      {/* Noval's quick configuration: what is connected, then one key per resource into its
          right-panel page (switching happens there). */}
      {!rp && (
        <div className="wb-mobile-config wb-ui" inert={left || !!panel || !!sheet || editor || focus}>
          <span className="wb-mobile-status">
            <i className={`wb-dot ${snap.online ? "online" : ""}`} />
            <strong>
              {snap.resources.connection.find((x) => x.id === snap.current.connection)?.name ||
                host.model() ||
                "未连接"}
            </strong>
            {!!summary && <small>{summary}</small>}
          </span>
          <div className="wb-mobile-keys" role="group" aria-label="快捷配置">
            {(Object.keys(resourceLabels) as Resource[]).map((kind) => {
              const Icon = resourceIcons[kind],
                value =
                  snap.resources[kind].find((x) => x.id === snap.current[kind])?.name ||
                  (kind === "connection" ? host.model() : "未选择"),
                count = kind === "world" ? worlds.length : 0;
              return (
                <button
                  key={kind}
                  aria-label={`${resourceLabels[kind]}：${kind === "world" ? `${count} 本已启用` : value}`}
                  aria-pressed={panel === kind}
                  onClick={() => {
                    close();
                    goPanel(kind);
                  }}
                >
                  <Icon size={19} />
                  {count > 0 && <b>{count}</b>}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {!rp && focus && !editor && (
        <button
          type="button"
          className="wb-mobile-focus-exit wb-ui"
          aria-label="退出专注"
          onClick={toggleFocus}
        >
          <ScanLine size={15} />
          退出专注
        </button>
      )}
      {createPortal(
        <button
          type="button"
          className="wb-mobile-plus wb-ui"
          aria-label="打开输入工具"
          aria-expanded={sheet === "tools"}
          onClick={() => setSheet(sheet === "tools" ? null : "tools")}
        >
          <Plus size={23} />
        </button>,
        items,
      )}
      {createPortal(
        <>
          <div
            className="wb-mobile-editor-heading wb-ui"
            onPointerDown={(e) => {
              if (e.button !== 0 || (e.target as Element).closest("button")) return;
              // Touch is captured implicitly; a mouse needs it to keep the bar while dragging.
              if (e.pointerType === "mouse") e.currentTarget.setPointerCapture(e.pointerId);
              pullFrom(e.pointerId, e.clientY, e.timeStamp);
            }}
            onPointerMove={(e) => {
              if (e.pointerId === pull.current?.pointer) pullTo(e.clientY, e.timeStamp);
            }}
            onPointerUp={(e) => {
              if (e.pointerId === pull.current?.pointer) letPull();
            }}
            onPointerCancel={dropPull}
          >
            <button aria-label="返回聊天，保留草稿" onClick={() => edit(false)}>
              <ChevronDown size={22} />
            </button>
            <strong>
              {document.body.classList.contains("wb-image-input-mode") ? "生图提示词" : "编辑草稿"}
            </strong>
            <small>{length} 字</small>
          </div>
        </>,
        form,
      )}
      {presence.value && (
        <>
          <button
            className="wb-mobile-sheet-shade"
            aria-label="关闭工具面板"
            data-wb-exiting={presence.exiting || undefined}
            inert={presence.exiting}
            onClick={close}
          />
          <div
            ref={sheetRef}
            className={`wb-mobile-sheet wb-ui ${presence.value === "management" ? "is-management" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-label={
              sheet === "management"
                ? "会话管理"
                : sheet === "tools"
                  ? "输入工具"
                  : sheet === "options"
                    ? "选择剧情选项"
                    : "最新回复操作"
            }
            inert={presence.exiting}
            data-wb-exiting={presence.exiting || undefined}
          >
            <span className="wb-mobile-sheet-grip" aria-hidden="true" />
            <header>
              <strong>
                {presence.value === "management"
                  ? "会话管理"
                  : presence.value === "tools"
                    ? "输入工具"
                    : presence.value === "options"
                      ? "剧情选项"
                      : "最新回复"}
              </strong>
              <button aria-label="关闭工具面板" onClick={close}>
                <X size={21} />
              </button>
            </header>
            {presence.value === "management" ? (
              <>
                <span className="wb-mobile-sheet-caption" aria-hidden="true">
                  布局模式
                </span>
                <div className="wb-mobile-mode-row" role="group" aria-label="工作台模式">
                  {(
                    [
                      ["novel", "Noval", BookOpen],
                      ["rp", "RP", Theater],
                      ["native", "原生", PanelsTopLeft],
                    ] as const
                  ).map(([mode, name, Icon]) => (
                    <button
                      key={mode}
                      aria-pressed={mode === (rp ? "rp" : "novel")}
                      onClick={() => {
                        close();
                        onLayout(mode);
                      }}
                    >
                      <Icon size={17} />
                      {name}
                    </button>
                  ))}
                </div>
                <div className="wb-mobile-sheet-list">
                  {!rp && (
                    <button
                      aria-pressed={focus}
                      onClick={() => {
                        close();
                        toggleFocus();
                      }}
                    >
                      <ScanLine size={19} />
                      专注模式
                      <ChevronRight size={15} />
                    </button>
                  )}
                  <button
                    onClick={() => {
                      close();
                      goPanel("character");
                    }}
                  >
                    <Users size={19} />
                    角色与资源
                    <ChevronRight size={15} />
                  </button>
                  <button
                    onClick={() => {
                      close();
                      goPanel("trace");
                    }}
                  >
                    <Activity size={19} />
                    Trace
                    <ChevronRight size={15} />
                  </button>
                  <button
                    onClick={(e) => {
                      close();
                      open({ kind: "files", anchor: e.currentTarget });
                    }}
                  >
                    <Folder size={19} />
                    聊天文件
                    <ChevronRight size={15} />
                  </button>
                  <button onClick={() => goSettings("settings")}>
                    <Settings size={19} />
                    用户设置
                    <ChevronRight size={15} />
                  </button>
                  <ReadingSettings host={host} row />
                </div>
              </>
            ) : presence.value === "options" ? (
              <OptionsSheetList
                host={host}
                rp={rp}
                onDone={close}
                onConfig={(anchor) => {
                  close();
                  activate("builtin:options", anchor);
                }}
              />
            ) : presence.value === "tools" ? (
              <>
                {rp && <div className="wb-mobile-tool-config">{resources}</div>}
                <div className="wb-mobile-tool-grid">
                  {tools.map((tool) => {
                    const Icon = toolIcon(tool.id, tool.label);
                    return (
                      <button
                        key={tool.id}
                        data-wb-busy={(tool.id === "builtin:database" && database.filling) || undefined}
                        disabled={toolDisabled(tool.id)}
                        onClick={(e) => {
                          close();
                          activate(tool.id, e.currentTarget);
                        }}
                      >
                        <Icon size={21} />
                        <span>{tool.label}</span>
                      </button>
                    );
                  })}
                  <button
                    onClick={(e) => {
                      close();
                      open({ kind: "menu", anchor: e.currentTarget });
                    }}
                  >
                    <Menu size={21} />
                    聊天菜单
                  </button>
                  <button
                    onClick={(e) => {
                      close();
                      open({ kind: "tools", anchor: e.currentTarget });
                    }}
                  >
                    <WandSparkles size={21} />
                    扩展工具
                  </button>
                  <button onClick={() => edit(true)}>
                    <Expand size={21} />
                    全屏输入
                  </button>
                </div>
              </>
            ) : (
              <div className="wb-mobile-sheet-list">
                <button disabled={snap.busy} onClick={() => nativeAction(".mes_edit")}>
                  <PencilLine size={19} />
                  编辑回复
                </button>
                <button onClick={() => nativeAction(".mes_copy")}>
                  <Copy size={19} />
                  复制回复
                </button>
                <div className="wb-mobile-candidates">
                  <button disabled={snap.busy} onClick={() => nativeAction(".swipe_left")}>
                    <ChevronLeft size={20} />
                    上一个候选
                  </button>
                  <button disabled={snap.busy} onClick={() => nativeAction(".swipe_right")}>
                    下一个候选
                    <ChevronRight size={20} />
                  </button>
                </div>
                {(presence.value as HTMLElement).querySelector(".wb-image-message-button") && (
                  <button disabled={snap.busy} onClick={() => nativeAction(".wb-image-message-button")}>
                    <ImagePlus size={19} />
                    为此回复生图
                  </button>
                )}
                <button
                  onClick={() => {
                    close();
                    goPanel("trace");
                  }}
                >
                  <Activity size={19} />
                  Trace
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
