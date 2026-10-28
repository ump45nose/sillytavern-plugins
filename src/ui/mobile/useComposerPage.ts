import { useEffect, useLayoutEffect, useRef, type RefObject, type HTMLAttributes } from "react";
import { flushSync } from "react-dom";
import { motionAllowed } from "../Motion";
import type { MobileState } from "./types";
import { bus } from "../../host/bus";

export function useComposerPage(
  rp: boolean,
  editor: boolean,
  latest: RefObject<MobileState>,
  headerRef: RefObject<HTMLElement | null>,
  onEditing: (value: boolean) => void,
) {
  const input = document.getElementById("send_textarea") as HTMLTextAreaElement,
    form = document.getElementById("send_form")!,
    dock = document.getElementById("form_sheld")!,
    stage = document.getElementById("sheld")!;
  const action = useRef(onEditing);
  action.current = onEditing;
  const setEditing = (value: boolean) => action.current(value);
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
  // The page lets go of the native nodes whenever the editor closes without its motion (a chat or
  // layout change), and on unmount.
  useLayoutEffect(() => {
    if (!editor && !motion.current.length) letGo();
  }, [editor]);
  useEffect(
    () => () => {
      settle();
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
  const grip: HTMLAttributes<HTMLDivElement> = {
    onPointerDown(event) {
      if (event.button !== 0 || (event.target as Element).closest("button")) return;
      if (event.pointerType === "mouse") event.currentTarget.setPointerCapture(event.pointerId);
      pullFrom(event.pointerId, event.clientY, event.timeStamp);
    },
    onPointerMove(event) {
      if (event.pointerId === pull.current?.pointer) pullTo(event.clientY, event.timeStamp);
    },
    onPointerUp(event) {
      if (event.pointerId === pull.current?.pointer) letPull();
    },
    onPointerCancel: dropPull,
  };
  return {
    grip,
    edit,
    letGo: () => {
      settle();
      letGo();
    },
  };
}
