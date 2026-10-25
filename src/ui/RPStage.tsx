import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  CloudSun,
  FastForward,
  History,
  MapPin,
  Maximize2,
  Minimize2,
  PanelBottom,
  Pause,
  PencilLine,
  Play,
  RotateCcw,
  Square,
  X,
  ImagePlus,
  Lightbulb,
} from "./icons";
import type { HostAdapter } from "../host/adapter";
import { boundedPreference } from "../host/rp";
import { matchSpeaker, pickSprite } from "../host/cast";
import { useHostSlices } from "./common";
import { ReadingPresentation } from "./Reading";
import { beginImage } from "./AddonControls";
import { addonEnabled } from "../addons/catalog";
import { RPAppearance } from "./RPAppearance";
import { OptionsPopover, useRPChoices } from "./StoryOptions";
import { motionAllowed } from "./Motion";
import { bus } from "../host/bus";
import { actionLabels } from "../host/labels";

type Message = {
  node: HTMLElement;
  id: number;
  name: string;
  user: boolean;
  editing: boolean;
};
type Cursor = { id: number; page: number; compose: boolean };
/** A cast tag in the current message, and the page it falls on. */
type Mark = { page: number; speaker: string; expr: string };
/** The world-book cast on stage: who holds the left and right places, and the face each last wore. */
type Stage = { slots: [string | null, string | null]; last: string | null; faces: Record<string, string> };
const emptyStage: Stage = { slots: [null, null], last: null, faces: {} };

/** Keep native message, media, iframe, textarea and event-handler identities intact. */
function useNativeDialogue(host: HostAdapter) {
  const [messages, setMessages] = useState<Message[]>([]);
  useLayoutEffect(() => {
    const chat = document.getElementById("chat")!;
    const read = (node: HTMLElement): Message => {
      const id = Number(node.getAttribute("mesid"));
      return {
        node,
        id,
        name: host.slice("chat")[id]?.name || node.querySelector(".name_text")?.textContent || "",
        user: node.getAttribute("is_user") === "true",
        editing: !!node.querySelector(".edit_textarea"),
      };
    };
    const scan = () => setMessages([...chat.querySelectorAll<HTMLElement>(".mes")].map(read));
    scan();
    const off = host.chatObserver.subscribe((change) => {
      if (change.nodes || change.editing) scan();
      // Streaming only touches the last floor: re-read just the floors that changed.
      else if (change.content.size)
        setMessages((prev) => prev.map((m) => (change.content.has(m.id) ? read(m.node) : m)));
    });
    return off;
  }, [host]);
  return messages;
}

/** Space between the columns a message is laid out in; one column is one page. */
const PAGE_GAP = 48;

export function RPStage({
  host,
  hidden,
  blocked,
  width,
  readingLayout,
  openPortraits,
  run,
  mobile = false,
}: {
  host: HostAdapter;
  hidden: boolean;
  blocked: boolean;
  width: number;
  readingLayout: () => void;
  openPortraits: (book: string, title: string) => void;
  run: (fn: () => unknown) => unknown;
  /** Board "RpPwa": one figure, the dialogue box above the bottom edge, no separate input. */
  mobile?: boolean;
}) {
  const snap = useHostSlices(host, ["session", "chat", "prefs"]),
    prefs = host.prefs();
  const textSize = boundedPreference(prefs.rpTextSize, 19, 14, 26),
    dialogWidth = boundedPreference(prefs.rpDialogWidth, 72, 65, 94);
  const messages = useNativeDialogue(host),
    [cursor, setCursor] = useState<Cursor>({ id: -1, page: -1, compose: false });
  const inertBefore = useRef<{ sheld: boolean; form: boolean } | null>(null);
  const beforeImage = useRef<Cursor | null>(null),
    cursorNow = useRef(cursor);
  cursorNow.current = cursor;
  const [history, setHistory] = useState(false),
    [expanded, setExpanded] = useState(false),
    [mediaRevision, setMediaRevision] = useState(0),
    [, setCastRevision] = useState(0);
  // The current message is laid out in page-wide columns; this is how many it took.
  const [paging, setPaging] = useState<{ node: HTMLElement | null; count: number; marks: Mark[] }>({
      node: null,
      count: 1,
      marks: [],
    }),
    [auto, setAuto] = useState(false);
  const originals = useRef(new Map<HTMLElement, { inert: boolean; aria: string | null }>());
  const focusInput = useRef(false),
    live = useRef(true),
    lastChat = useRef(snap.chatName),
    lastCount = useRef(0),
    lastTurn = useRef(""),
    lastLine = useRef<HTMLElement | null>(null),
    animation = useRef<Animation | null>(null);
  const current = messages.find((m) => m.id === cursor.id) || messages.at(-1);
  const pageCount = current && paging.node === current.node ? paging.count : 1,
    page = Math.min(pageCount - 1, Math.max(0, cursor.page < 0 ? pageCount - 1 : cursor.page)),
    atEnd = !current || (current === messages.at(-1) && page === pageCount - 1);
  const compose = cursor.compose || !current,
    presentation = host.rpPresentation(current?.user ? undefined : current?.name);
  void mediaRevision;
  // A world-book cast: who speaks on this page, in reading order; a page with no tag continues the
  // last one before it (or opens with the message's first). An untagged reply goes by the names in
  // its text, with the expression the host's classifier reads.
  const [classified, setClassified] = useState({ key: "", label: "" }),
    [stage, setStage] = useState<Stage>(emptyStage);
  const cast = host.cast.state,
    castOn = !!cast.config && cast.members.some((member) => member.sprites.length),
    castReply = castOn && !!current && !current.user,
    marks = current && paging.node === current.node ? paging.marks : [],
    onPage = marks.filter((m) => m.page === page),
    lead = onPage[0] ?? marks.filter((m) => m.page < page).at(-1) ?? marks[0],
    passage = castReply && !lead ? current!.node.querySelector(".mes_text")?.textContent || "" : "",
    guessed = passage ? matchSpeaker(passage, cast.members) : null,
    classifyKey =
      guessed && host.cast.member(guessed)?.sprites.length
        ? `${snap.chatName}:${current!.id}:${passage.length}`
        : "",
    lines = !castReply
      ? []
      : onPage.length
        ? onPage
        : lead
          ? [lead]
          : guessed
            ? [{ speaker: guessed, expr: classified.key === classifyKey ? classified.label : "" }]
            : [];
  const voices: { name: string; face: string }[] = [];
  for (const line of lines) {
    const member = host.cast.member(line.speaker),
      face = member && pickSprite(member.sprites, line.expr || null, host.cast.fallbackExpression())?.path;
    if (member && face && !voices.some((voice) => voice.name === member.name))
      voices.push({ name: member.name, face });
  }
  const shown = voices[0],
    voiceKey = voices.map((voice) => voice.name + "\n" + voice.face).join("\n");
  useEffect(() => host.cast.subscribe(() => setCastRevision((v) => v + 1)), [host]);
  // A reply still streaming in is read once it is complete.
  const streaming = snap.busy && current?.id === snap.messages.length - 1;
  useEffect(() => {
    if (!classifyKey || streaming) return;
    let live = true;
    void host.cast
      .expression(classifyKey, passage)
      .then((label) => live && setClassified({ key: classifyKey, label }));
    return () => {
      live = false;
    };
  }, [host, classifyKey, streaming]);
  // Two places on stage, taken in reading order: a new voice takes the empty one, else the one not
  // held by the voice before. The page's first voice is the one speaking.
  useLayoutEffect(() => {
    if (!voices.length) return;
    setStage((old) => {
      const names = new Set(cast.members.map((member) => member.name));
      let next: Stage = {
        ...old,
        slots: old.slots.map((slot) => (slot && names.has(slot) ? slot : null)) as Stage["slots"],
      };
      for (const { name, face } of voices.slice(0, 2)) {
        const held = next.slots,
          slots: Stage["slots"] = held.includes(name)
            ? held
            : !held[0]
              ? [name, held[1]]
              : !held[1]
                ? [held[0], name]
                : held[0] === next.last
                  ? [held[0], name]
                  : [name, held[1]];
        next = { slots, last: name, faces: { ...next.faces, [name]: face } };
      }
      next.last = voices[0].name;
      return JSON.stringify(next) === JSON.stringify(old) ? old : next;
    });
  }, [voiceKey, cast.members]);
  useEffect(() => {
    if (!castOn) setStage(emptyStage);
  }, [castOn]);
  const isHidden = hidden || blocked;
  useEffect(() => {
    if (lastChat.current !== snap.chatName) {
      lastChat.current = snap.chatName;
      live.current = true;
      setCursor({ id: -1, page: -1, compose: false });
      setHistory(false);
      setExpanded(false);
      setStage(emptyStage);
    }
  }, [snap.chatName]);
  useEffect(() => {
    if (!messages.length) {
      lastCount.current = 0;
      return;
    }
    const newest = messages.at(-1)!;
    if (live.current && newest.id !== cursor.id && (messages.length !== lastCount.current || cursor.id < 0))
      setCursor({ id: newest.id, page: 0, compose: false });
    lastCount.current = messages.length;
  }, [messages, cursor.id]);
  useEffect(() => {
    const jump = (id: number) => {
      live.current = false;
      setHistory(false);
      setCursor({ id, page: 0, compose: false });
    };
    const imageCompose = () => {
      beforeImage.current ??= { ...cursorNow.current };
      live.current = false;
      setHistory(false);
      setCursor((old) => ({ ...old, compose: true }));
    };
    const imageEnd = () => {
      if (beforeImage.current) {
        setCursor(beforeImage.current);
        beforeImage.current = null;
      }
    };
    const off = [
      bus.on("image-compose", imageCompose),
      bus.on("image-compose-end", imageEnd),
      bus.on("rp-jump", jump),
      bus.on("rp-dialogue", () => turnNow.current(-1)),
    ];
    return () => off.forEach((f) => f());
  }, []);
  useEffect(() => host.media.subscribe(() => setMediaRevision((v) => v + 1)), [host]);
  useLayoutEffect(() => {
    // Data attributes, not classes: SillyTavern's keyboard.js rescans the whole document on every
    // class written on <body>, which stalled each switch into and out of these states.
    document.body.toggleAttribute("data-wb-rp-compose", compose && !history);
    document.body.toggleAttribute("data-wb-rp-expanded", expanded && compose && !history);
    document.body.toggleAttribute("data-wb-rp-history", history);
    document.body.toggleAttribute("data-wb-rp-editing", !!current?.editing && !compose && !history);
    const sheld = document.getElementById("sheld")!,
      form = document.getElementById("form_sheld")!;
    // Written only when they change: on a phone MobileShell also makes the box inert under drawers.
    if (inertBefore.current?.sheld !== isHidden) sheld.inert = isHidden;
    if (inertBefore.current?.form !== (history || isHidden)) form.inert = history || isHidden;
    inertBefore.current = { sheld: isHidden, form: history || isHidden };
    if (focusInput.current && compose && !history) host.focusInput();
    focusInput.current = false;
    document.body.style.setProperty("--wb-rp-text", textSize + "px");
    document.body.style.setProperty("--wb-rp-width", String(dialogWidth / 100));
    document.body.style.setProperty(
      "--wb-rp-sprite",
      boundedPreference(prefs.rpSpriteScale, 91, 55, 100) + "vh",
    );
    document.body.style.setProperty(
      "--wb-rp-font",
      prefs.readingFont === "sans"
        ? "system-ui,sans-serif"
        : "'Noto Serif CJK SC','Source Han Serif SC','Songti SC',SimSun,serif",
    );
    for (const message of messages) {
      const visible = history || (message === current && !compose);
      if (!originals.current.has(message.node))
        originals.current.set(message.node, {
          inert: message.node.inert,
          aria: message.node.getAttribute("aria-hidden"),
        });
      message.node.classList.toggle("wb-rp-current", message === current);
      message.node.inert = !visible;
      message.node.setAttribute("aria-hidden", String(!visible));
    }
    for (const [node, previous] of originals.current)
      if (!node.isConnected) {
        node.inert = previous.inert;
        previous.aria === null
          ? node.removeAttribute("aria-hidden")
          : node.setAttribute("aria-hidden", previous.aria);
        node.classList.remove("wb-rp-current");
        originals.current.delete(node);
      }
    if ((current?.node ?? null) !== lastLine.current) {
      lastLine.current = current?.node ?? null;
      bus.emit("rp-line");
    }
    const turn = `${current?.id}:${page}:${compose}:${history}`;
    if (turn !== lastTurn.current) {
      lastTurn.current = turn;
      const text = current?.node.querySelector<HTMLElement>(".mes_block");
      if (text && !history && !compose) {
        animation.current?.cancel();
        if (motionAllowed())
          animation.current = text.animate(
            [
              { opacity: 0.2, transform: "translateX(14px)" },
              { opacity: 1, transform: "translateX(0)" },
            ],
            { duration: 240, easing: "cubic-bezier(.22,.8,.3,1)" },
          );
      }
    }
  }, [
    messages,
    current,
    page,
    compose,
    history,
    expanded,
    isHidden,
    textSize,
    dialogWidth,
    prefs.rpSpriteScale,
    prefs.readingFont,
  ]);
  useEffect(
    () => () => {
      animation.current?.cancel();
      originals.current.forEach((previous, node) => {
        node.inert = previous.inert;
        previous.aria === null
          ? node.removeAttribute("aria-hidden")
          : node.setAttribute("aria-hidden", previous.aria);
        node.classList.remove("wb-rp-current");
      });
      bus.emit("rp-line");
      document.getElementById("sheld")!.inert = false;
      document.getElementById("form_sheld")!.inert = false;
      for (const name of ["compose", "expanded", "history", "editing"])
        document.body.removeAttribute("data-wb-rp-" + name);
      for (const name of ["text", "width", "sprite", "font"])
        document.body.style.removeProperty("--wb-rp-" + name);
    },
    [],
  );
  // Pages are columns of the native message block: lines never split, nothing scrolls inside the
  // box, and media stay in one column. Measured again when the text, its size or the box change.
  const block =
    !history && !compose && !current?.editing ? current?.node.querySelector<HTMLElement>(".mes_block") : null;
  useLayoutEffect(() => {
    if (!block || !current) return;
    const node = current.node;
    const measure = () => {
      block.style.setProperty("--wb-rp-column", block.clientWidth + "px");
      block.style.setProperty("--wb-rp-gap", PAGE_GAP + "px");
      block.style.setProperty("--wb-rp-page", block.clientHeight + "px");
      const count = Math.max(1, Math.round((block.scrollWidth + PAGE_GAP) / (block.clientWidth + PAGE_GAP))),
        origin = block.getBoundingClientRect().left - block.scrollLeft,
        tags = [...block.querySelectorAll<HTMLElement>("[data-wb-speaker]")],
        marks = tags.map((mark) => ({
          page: Math.floor((mark.getBoundingClientRect().left - origin + 1) / (block.clientWidth + PAGE_GAP)),
          speaker: mark.dataset.wbSpeaker!,
          expr: mark.dataset.wbExpr!,
        }));
      // The band's name plate already names a page's first voice; later voices carry their own.
      tags.forEach((tag, i) =>
        tag.toggleAttribute("data-wb-lead", !i || marks[i - 1].page !== marks[i].page),
      );
      setPaging((old) =>
        old.node === node && old.count === count && JSON.stringify(old.marks) === JSON.stringify(marks)
          ? old
          : { node, count, marks },
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(block);
    block.addEventListener("load", measure, true);
    return () => {
      observer.disconnect();
      block.removeEventListener("load", measure, true);
      block.style.removeProperty("--wb-rp-column");
      block.style.removeProperty("--wb-rp-gap");
      block.style.removeProperty("--wb-rp-page");
      block.scrollLeft = 0;
    };
  }, [block, current, textSize, dialogWidth, prefs.readingFont]);
  useLayoutEffect(() => {
    if (block) block.scrollLeft = page * (block.clientWidth + PAGE_GAP);
  }, [block, page, pageCount]);
  const turn = (delta: number) => {
    if (current?.editing) return;
    if (compose) {
      if (delta < 0) leaveCompose();
      return;
    }
    if (!current) return;
    live.current = false;
    const index = messages.indexOf(current),
      nextPage = page + delta;
    if (nextPage >= 0 && nextPage < pageCount) setCursor({ id: current.id, page: nextPage, compose: false });
    else if (delta < 0 && index > 0) setCursor({ id: messages[index - 1].id, page: -1, compose: false });
    else if (delta > 0 && index < messages.length - 1)
      setCursor({ id: messages[index + 1].id, page: 0, compose: false });
    else if (delta > 0) reply();
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        e.defaultPrevented ||
        e.isComposing ||
        e.ctrlKey ||
        e.altKey ||
        e.metaKey ||
        isHidden ||
        history ||
        document.querySelector("dialog[open],.wb-popover,[role=listbox]")
      )
        return;
      // Buttons elsewhere may own arrow keys (menus, radio groups); the deck's own keys page on.
      const target = e.target as Element | null;
      if (
        target?.closest("input,textarea,select,[contenteditable=true]") ||
        (target?.closest("button") && !target.closest(".wb-rp-deck"))
      )
        return;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        turn(e.key === "ArrowLeft" ? -1 : 1);
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  });
  const turnNow = useRef(turn);
  turnNow.current = turn;
  const deck = useRef<HTMLElement>(null);
  // Phone: the log opens at its newest line. Leaving it, the band and its deck take their places
  // at once (they rise in by animation) instead of transitioning top and height through every
  // layout in between.
  useLayoutEffect(() => {
    if (!mobile || !history) return;
    const chat = document.getElementById("chat")!;
    chat.scrollTop = chat.scrollHeight;
    return () => {
      const box = document.getElementById("sheld")!,
        band = deck.current;
      box.style.setProperty("transition", "none");
      band?.style.setProperty("transition", "opacity 180ms, visibility 180ms");
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          box.style.removeProperty("transition");
          band?.style.removeProperty("transition");
        }),
      );
    };
  }, [mobile, history]);
  // Phone gestures on the dialogue box: sideways turns the page, pulling up past the end of the
  // text opens the log, and pulling the log down from its top closes it. The box follows the
  // finger through --wb-rp-pull while the pull lasts.
  useEffect(() => {
    if (!mobile || compose || current?.editing) return;
    const box = document.getElementById("sheld")!,
      chat = document.getElementById("chat")!,
      body = document.body;
    let start: { x: number; y: number; axis: "x" | "y" | null; edge: boolean } | null = null,
      pull = 0;
    const setPull = (value: number) => {
      pull = value;
      body.style.setProperty("--wb-rp-pull", `${value}px`);
      body.toggleAttribute("data-wb-rp-pulling", value !== 0);
    };
    const down = (e: TouchEvent) => {
      start = null;
      if (
        e.touches.length !== 1 ||
        (e.target as Element).closest("button,a,input,textarea,select,iframe,video")
      )
        return;
      const t = e.touches[0];
      start = {
        x: t.clientX,
        y: t.clientY,
        axis: null,
        edge: history ? chat.scrollTop <= 2 : chat.scrollTop + chat.clientHeight >= chat.scrollHeight - 2,
      };
    };
    const move = (e: TouchEvent) => {
      if (!start) return;
      const t = e.touches[0],
        dx = t.clientX - start.x,
        dy = t.clientY - start.y;
      if (!start.axis) {
        if (Math.hypot(dx, dy) < 10) return;
        start.axis = !history && Math.abs(dx) > Math.abs(dy) * 1.3 ? "x" : "y";
      }
      if (start.axis === "x") e.preventDefault();
      else if (start.edge && (history ? dy > 0 : dy < 0)) {
        e.preventDefault();
        setPull(Math.sign(dy) * Math.min(180, Math.abs(dy) * 0.55));
      }
    };
    const up = (e: TouchEvent) => {
      if (!start) return;
      const t = e.changedTouches[0],
        dx = t.clientX - start.x;
      if (start.axis === "x" && Math.abs(dx) > 48) turnNow.current(dx < 0 ? 1 : -1);
      if (start.axis === "y" && Math.abs(pull) > 44) setHistory(!history);
      start = null;
      setPull(0);
    };
    const cancel = () => {
      start = null;
      setPull(0);
    };
    box.addEventListener("touchstart", down, { passive: true });
    box.addEventListener("touchmove", move, { passive: false });
    box.addEventListener("touchend", up);
    box.addEventListener("touchcancel", cancel);
    return () => {
      cancel();
      box.removeEventListener("touchstart", down);
      box.removeEventListener("touchmove", move);
      box.removeEventListener("touchend", up);
      box.removeEventListener("touchcancel", cancel);
      body.style.removeProperty("--wb-rp-pull");
    };
  }, [mobile, compose, history, current?.editing]);
  const nativeAction = (selector: string) =>
    run(() => {
      const button = current?.node.querySelector<HTMLElement>(selector);
      if (!button) throw new Error("当前消息没有此操作。");
      button.click();
    });
  const enterCompose = () => {
    if (current?.editing) return;
    live.current = true;
    setAuto(false);
    setHistory(false);
    setCursor({ id: current?.id ?? -1, page: -1, compose: true });
  };
  const leaveCompose = () => {
    setExpanded(false);
    setCursor({ id: current?.id ?? -1, page: -1, compose: false });
  };
  /** Reading shows no input: replying turns the dialogue band into the native input. */
  const reply = () => {
    focusInput.current = true;
    enterCompose();
  };
  /** Jump to the newest line of the conversation and follow it again. */
  const skip = () => {
    live.current = true;
    setCursor({ id: messages.at(-1)?.id ?? -1, page: -1, compose: false });
  };
  // Auto play turns pages after a reading pause sized to the page; it stops at the newest line,
  // and waits there while a reply is still streaming in.
  useEffect(() => {
    // Wait for the new message's pages to be measured before deciding it is the end.
    if (!auto || !block || isHidden || current?.editing || paging.node !== current?.node) return;
    if (atEnd) {
      if (!snap.busy) setAuto(false);
      return;
    }
    const chars = (block.textContent?.length || 0) / pageCount;
    const timer = setTimeout(() => turnNow.current(1), Math.min(9000, Math.max(2600, 1800 + chars * 45)));
    return () => clearTimeout(timer);
  }, [auto, block, page, pageCount, atEnd, isHidden, current?.editing, snap.busy, paging.node]);
  // A press on the text turns the page, as in a visual novel (on a phone the left half turns back).
  useEffect(() => {
    if (!block) return;
    const chat = document.getElementById("chat")!;
    const press = (e: MouseEvent) => {
      if (
        // Native actions the deck triggers are scripted clicks bubbling out of the message.
        !e.isTrusted ||
        e.button !== 0 ||
        !getSelection()?.isCollapsed ||
        (e.target as Element).closest(
          "a,button,[role=button],.mes_button,.mes_buttons,.mes_edit_buttons,input,textarea,select,summary,iframe,video,audio,img,[contenteditable=true]",
        )
      )
        return;
      const rect = chat.getBoundingClientRect();
      turnNow.current(mobile && e.clientX < rect.left + rect.width / 2 ? -1 : 1);
    };
    chat.addEventListener("click", press);
    return () => chat.removeEventListener("click", press);
  }, [block, mobile]);
  // The wheel over the band turns pages too, one turn per gesture however many events it sends;
  // composing, turning back returns to the dialogue. A text field scrolls first: only a gesture
  // that begins with the field already at the end it is moving toward turns the page.
  useEffect(() => {
    if (mobile || history) return;
    const band = document.getElementById("sheld")!;
    let travel = 0,
      quietUntil = 0,
      lastTurn = 0,
      fieldUntil = 0;
    const wheel = (e: WheelEvent) => {
      const now = performance.now(),
        delta = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX,
        direction = Math.sign(delta),
        hit = (e.target as Element).closest<HTMLElement>("textarea,input,select,[contenteditable=true]"),
        // A Markdown editor scrolls in its scroller, not in its content node.
        field = hit?.closest<HTMLElement>(".cm-scroller") ?? hit;
      if (field) {
        const scrolls =
          direction > 0 ? field.scrollTop + field.clientHeight < field.scrollHeight - 1 : field.scrollTop > 0;
        // Once the field has scrolled, the rest of that gesture stays with it.
        if (scrolls || now < fieldUntil) {
          fieldUntil = now + 300;
          return;
        }
      }
      e.preventDefault();
      // A gesture's trailing events keep the wheel quiet; turning the other way starts a new one.
      if (now < quietUntil && direction === lastTurn) {
        quietUntil = now + 160;
        return;
      }
      if (direction !== Math.sign(travel)) travel = 0;
      travel += delta;
      if (Math.abs(travel) < 40) return;
      turnNow.current(direction);
      lastTurn = direction;
      travel = 0;
      quietUntil = now + 260;
    };
    band.addEventListener("wheel", wheel, { passive: false });
    return () => band.removeEventListener("wheel", wheel);
  }, [mobile, history]);
  // A story option that fills the input from the phone's sheet turns the band into it, as 回应 does.
  const replyNow = useRef(reply);
  replyNow.current = reply;
  useEffect(() => bus.on("rp-reply", () => replyNow.current()), []);
  const options = useRPChoices(host, {
      ending: atEnd && !compose && !!current && !current.user,
      blocked: isHidden || history || !!current?.editing || expanded,
      mobile,
      onFill: reply,
    }),
    [optionsAnchor, setOptionsAnchor] = useState<HTMLElement | null>(null);
  const tools = (
    <div className="wb-rp-tools" role="toolbar" aria-label="对白工具">
      {host.isGenerating() && (
        <button
          className="wb-rp-tool"
          aria-label="停止生成"
          title="停止生成"
          onClick={() => run(() => host.click("#mes_stop"))}
        >
          <Square size={16} />
        </button>
      )}
      {compose ? (
        <>
          <button
            className="wb-rp-tool is-labelled"
            aria-label="返回对白"
            title="返回对白"
            disabled={!current}
            onClick={leaveCompose}
          >
            <ChevronLeft size={16} />
            对白
          </button>
          {!mobile && (
            <button
              className="wb-rp-tool"
              aria-label={expanded ? "还原 RP 输入区" : "展开 RP 输入区"}
              title={expanded ? "还原输入区" : "展开输入区"}
              aria-expanded={expanded}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          )}
          {options.tag}
        </>
      ) : current?.editing ? (
        <>
          <button
            className="wb-rp-tool is-labelled"
            aria-label="取消对白编辑"
            title="取消对白编辑"
            onClick={() => nativeAction(".mes_edit_cancel")}
          >
            <X size={16} />
            取消
          </button>
          <button
            className="wb-rp-tool is-labelled is-primary"
            aria-label="保存对白编辑"
            title="保存对白编辑"
            onClick={() => nativeAction(".mes_edit_done")}
          >
            <Check size={16} />
            保存
          </button>
        </>
      ) : (
        <>
          <button
            className="wb-rp-tool"
            aria-label={auto ? "停止自动播放" : "自动播放"}
            title={auto ? "停止自动播放" : "自动播放"}
            aria-pressed={auto}
            disabled={!auto && atEnd}
            onClick={() => setAuto(!auto)}
          >
            {auto ? <Pause size={16} /> : <Play size={16} />}
          </button>
          <button
            className="wb-rp-tool"
            aria-label="快进到最新对白"
            title="快进到最新对白"
            disabled={atEnd}
            onClick={skip}
          >
            <FastForward size={16} />
          </button>
          <span className="wb-rp-tools-rule" aria-hidden="true" />
          <button
            className="wb-rp-tool"
            aria-label={`${actionLabels.regenerate}当前回复`}
            title={`${actionLabels.regenerate}当前回复`}
            disabled={snap.busy || !current || current.user || current.id !== snap.messages.length - 1}
            onClick={() => run(() => host.click("#option_regenerate"))}
          >
            <RotateCcw size={16} />
          </button>
          <button
            className="wb-rp-tool"
            aria-label="编辑当前对白"
            title="编辑当前对白"
            disabled={snap.busy || !current}
            onClick={() => nativeAction(".mes_edit")}
          >
            <PencilLine size={16} />
          </button>
          {addonEnabled(prefs, "image-gen") && !!snap.chatName && (
            <button
              className="wb-rp-tool"
              aria-label="为当前对白生图"
              title="为当前对白生图"
              disabled={snap.busy || !current}
              onClick={() => beginImage(host, current!.id)}
            >
              <ImagePlus size={16} />
            </button>
          )}
          <span className="wb-rp-tools-rule" aria-hidden="true" />
          <button
            className="wb-rp-tool"
            aria-label="剧情选项"
            title="剧情选项"
            aria-expanded={!!optionsAnchor}
            onClick={(e) => setOptionsAnchor(optionsAnchor ? null : e.currentTarget)}
          >
            <Lightbulb size={16} />
          </button>
          <RPAppearance host={host} openPortraits={openPortraits} />
          <button
            className="wb-rp-tool"
            aria-label="切换阅读布局"
            title="切换阅读布局"
            onClick={readingLayout}
          >
            <PanelBottom size={16} />
          </button>
        </>
      )}
    </div>
  );
  const visibleDots = Array.from({ length: pageCount }, (_, i) => i).filter((i) => Math.abs(i - page) <= 3);
  const dots = (
    <div className="wb-rp-dots">
      {visibleDots.map((index) => (
        <button
          key={index}
          aria-label={`对白第 ${index + 1} 段`}
          aria-current={index === page ? "true" : undefined}
          onClick={() => {
            live.current = false;
            setCursor({ id: current!.id, page: index, compose: false });
          }}
        />
      ))}
    </div>
  );
  const replies = [...new Map(host.quickReplies().map((qr: any) => [qr.key, qr])).values()].slice(
    0,
    3,
  ) as any[];
  const scene = presentation.scene,
    sceneValue = (key: string) =>
      typeof scene[key] === "string" || typeof scene[key] === "number" ? String(scene[key]) : "";
  const sendRow = document.getElementById("rightSendForm");
  const sceneHidden = isHidden || width < 1000 || (expanded && compose) || history;
  return (
    <>
      {createPortal(
        <div className="wb-rp-stage" aria-label="RP 舞台">
          <div className="wb-rp-atmosphere" />
          {castOn && (stage.slots[0] || stage.slots[1])
            ? stage.slots.map((name, place) => {
                // The phone has room for one figure: whoever spoke last.
                if (!name || !stage.faces[name] || (mobile && name !== stage.last)) return null;
                const speaking = name === shown?.name && !compose && !current?.user;
                return (
                  <div
                    key={name}
                    className={`wb-rp-actor is-sprite is-cast ${place && !mobile ? "is-right" : "is-left"} ${speaking ? "is-speaking" : "is-listening"}`}
                  >
                    <img src={stage.faces[name]} alt={name} />
                    <span>{name}</span>
                  </div>
                );
              })
            : (presentation.sprite || (prefs.rpShowPortraits !== false && presentation.portrait)) && (
                <div
                  className={`wb-rp-actor ${presentation.sprite ? "is-sprite" : "is-portrait"} ${current?.user || compose ? "is-listening" : "is-speaking"}`}
                >
                  <img src={presentation.sprite || presentation.portrait} alt={presentation.name} />
                  <span>{presentation.name}</span>
                </div>
              )}
          {!mobile &&
            !(castOn && stage.slots[1]) &&
            (presentation.userSprite || (prefs.rpShowPortraits !== false && presentation.userPortrait)) && (
              <div
                className={`wb-rp-user ${presentation.userSprite ? "is-sprite" : "is-portrait"} ${current?.user || compose ? "is-speaking" : "is-listening"}`}
              >
                <img src={presentation.userSprite || presentation.userPortrait} alt={presentation.userName} />
                <span>{presentation.userName}</span>
              </div>
            )}
        </div>,
        document.body,
      )}
      {/* Board "RpDesktop": glass cards over the scene; the native message is the dialogue box itself. */}
      {!mobile && (
        <aside
          className={`wb-rp-scene ${sceneHidden ? "is-hidden" : ""}`}
          inert={sceneHidden}
          aria-label="当前场景信息"
        >
          <div className="wb-rp-scene-head">
            <strong>{sceneValue("day") ? "DAY " + sceneValue("day") : "当前对话"}</strong>
            <span>
              {sceneValue("time") ||
                host.messageTime(snap.messages.find((m) => m.id === current?.id)?.send_date)}
            </span>
          </div>
          <span>
            <MapPin size={14} aria-hidden="true" />
            {sceneValue("location") || snap.groupName || snap.character?.name || "等待故事开始"}
          </span>
          {sceneValue("weather") && (
            <span>
              <CloudSun size={14} aria-hidden="true" />
              {sceneValue("weather")}
            </span>
          )}
        </aside>
      )}
      <section
        ref={deck}
        className={`wb-rp-deck ${mobile ? "is-mobile" : width < 800 ? "is-compact" : ""} ${compose ? "is-compose" : current?.editing ? "is-editing" : ""} ${isHidden || history ? "is-hidden" : ""}`}
        inert={isHidden || history}
        aria-label="RP 对白与输入"
      >
        {!expanded && !!replies.length && (
          <div className="wb-rp-replies" role="group" aria-label="建议回应">
            {replies.map((qr) => (
              <button
                key={qr.key}
                title={qr.message}
                disabled={snap.busy}
                onClick={() => {
                  host.setInput(qr.message || "");
                  reply();
                }}
              >
                {qr.label || qr.message?.slice(0, 45)}
              </button>
            ))}
          </div>
        )}
        {/* The speaker's name heads the band; every control rides its bottom line. */}
        <div className="wb-rp-head">
          <div className="wb-rp-plate">
            {(compose || current?.user ? presentation.userPortrait : presentation.portrait) && (
              <img
                src={compose || current?.user ? presentation.userPortrait : presentation.portrait}
                alt=""
              />
            )}
            <strong>
              {compose ? presentation.userName : shown?.name || current?.name || presentation.name}
            </strong>
          </div>
          {/* Phone: the page marks sit by the name, the quick menu along the foot; composing and
              editing keep their own keys here. */}
          {mobile && (compose || current?.editing ? tools : dots)}
        </div>
        {/* Turning pages: back, the page marks, forward (past the last page is your reply), then the
            quick menu and the reply key. Editing keeps only its own keys; composing moves them into
            the input's tool row, just before send. */}
        {!compose && (
          <div className="wb-rp-foot">
            {!current?.editing && !mobile && (
              <>
                <button
                  className="wb-rp-tool"
                  aria-label="上一段对白"
                  title="上一段对白"
                  disabled={!current || (current === messages[0] && page === 0)}
                  onClick={() => turn(-1)}
                >
                  <ChevronLeft size={16} />
                </button>
                {dots}
                <button
                  className="wb-rp-tool"
                  aria-label="下一段对白或输入"
                  title={atEnd ? "轮到你回应" : "下一段对白"}
                  onClick={() => turn(1)}
                >
                  <ChevronRight size={16} />
                </button>
              </>
            )}
            {(!mobile || !current?.editing) && tools}
            {!current?.editing && options.tag}
            {!current?.editing && (
              <button className="wb-rp-reply" aria-label="快进到你的回应" title="直接回应" onClick={reply}>
                <PencilLine size={15} />
                回应
              </button>
            )}
          </div>
        )}
        {compose && !mobile && sendRow && createPortal(tools, sendRow)}
      </section>
      {options.overlay}
      {optionsAnchor && (
        <OptionsPopover host={host} anchor={optionsAnchor} onClose={() => setOptionsAnchor(null)} />
      )}
      {!isHidden && !mobile && (
        <button
          className="wb-rp-corner wb-rp-log-toggle"
          aria-label={history ? "关闭对话记录" : "查看对话记录"}
          title={history ? "回到对白" : "对话记录"}
          aria-pressed={history}
          onClick={() => setHistory(!history)}
        >
          <History size={18} aria-hidden="true" />
        </button>
      )}
      {history && (
        <>
          <div className="wb-rp-log-head">
            <h2>对话记录</h2>
            <small>
              {snap.chatName}
              {messages.length ? ` · ${messages.length} 层` : ""}
            </small>
            <button aria-label="返回 RP 对白" onClick={() => setHistory(false)}>
              <ChevronLeft size={15} aria-hidden="true" />
              返回对白
            </button>
          </div>
          <ReadingPresentation host={host} chatStyle />
        </>
      )}
    </>
  );
}
