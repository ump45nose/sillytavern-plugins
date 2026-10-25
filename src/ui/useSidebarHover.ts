import { useEffect, useRef, useState } from "react";

/**
 * Edge reveals are temporary overlays. Only explicit clicks change saved layout.
 *
 * The trigger is the --wb-edge-lane strip at each window edge; #chat is inset past it, so its
 * scrollbar never sits in the lane. A reveal also needs intent: no button held (dragging a
 * scrollbar, selecting text), no wheel scrolling in the last 500 ms, and a 180 ms dwell.
 */
export function useSidebarHover(
  enabled: boolean,
  leftPinned: boolean,
  rightPinned: boolean,
  canClose: () => boolean,
) {
  const [hot, setHot] = useState({ left: false, right: false });
  const live = useRef({ enabled, leftPinned, rightPinned, hot, canClose });
  live.current = { enabled, leftPinned, rightPinned, hot, canClose };
  const suppressed = useRef({ left: false, right: false });
  const blocked = useRef({ left: false, right: false });
  const dismiss = (side: "left" | "right") => {
    suppressed.current[side] = true;
    setHot((v) => ({ ...v, [side]: false }));
  };
  useEffect(() => {
    if (!enabled) {
      setHot({ left: false, right: false });
      return;
    }
    const timers: Partial<Record<"left" | "right", ReturnType<typeof setTimeout>>> = {};
    const lane =
      parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--wb-edge-lane")) || 36;
    let pressed = false,
      scrolled = 0;
    const busy = () => pressed || performance.now() - scrolled < 500;
    // Wheel only: SillyTavern scrolls #chat itself while streaming, and a scrollbar drag is
    // already a held button.
    const scroll = () => {
      scrolled = performance.now();
    };
    const cancel = (side: "left" | "right") => {
      clearTimeout(timers[side]);
      delete timers[side];
    };
    const schedule = (side: "left" | "right", open: boolean) => {
      if (timers[side]) return;
      timers[side] = setTimeout(
        () => {
          delete timers[side];
          const current = live.current;
          if (
            !current.enabled ||
            (side === "left" ? current.leftPinned : current.rightPinned) ||
            (open && (suppressed.current[side] || busy())) ||
            (!open && !current.hot[side])
          )
            return;
          if (
            !open &&
            document.activeElement?.matches(":focus-visible") &&
            document.activeElement.closest(
              side === "left" ? ".wb-left,.wb-popover" : ".wb-right,.wb-resource-rail,.wb-popover",
            )
          )
            return;
          if (!open && !current.canClose()) {
            blocked.current[side] = true;
            return;
          }
          setHot((v) => ({ ...v, [side]: open }));
        },
        open ? 180 : 280,
      );
    };
    const move = (event: PointerEvent) => {
      // Read from every move: a press on the native scrollbar may never send pointerup here.
      pressed = event.buttons !== 0;
      if (event.pointerType === "touch" || !live.current.enabled) return;
      const element = event.target instanceof Element ? event.target : null;
      for (const side of ["left", "right"] as const) {
        const inside =
          !!element?.closest(
            side === "left" ? ".wb-left,.wb-edge-left" : ".wb-right,.wb-resource-rail,.wb-edge-right",
          ) || !!(live.current.hot[side] && element?.closest(".wb-popover"));
        const edge =
          event.clientY > 74 &&
          (side === "left" ? event.clientX <= lane : event.clientX >= innerWidth - lane);
        if (!inside && !edge) suppressed.current[side] = false;
        const pinned = side === "left" ? live.current.leftPinned : live.current.rightPinned;
        if (pinned) {
          cancel(side);
          if (live.current.hot[side]) setHot((v) => ({ ...v, [side]: false }));
          continue;
        }
        const over = inside || edge;
        // Passing through the lane mid-drag or mid-scroll is not a request to open.
        if (over && !live.current.hot[side] && busy()) {
          cancel(side);
          continue;
        }
        if (over && !suppressed.current[side]) {
          blocked.current[side] = false;
          if (live.current.hot[side]) cancel(side);
          else schedule(side, true);
        } else {
          cancel(side);
          if (live.current.hot[side] && !blocked.current[side]) schedule(side, false);
        }
      }
    };
    const leave = () => {
      for (const side of ["left", "right"] as const) {
        cancel(side);
        if (live.current.hot[side]) schedule(side, false);
      }
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("wheel", scroll, { capture: true, passive: true });
    document.documentElement.addEventListener("pointerleave", leave);
    return () => {
      cancel("left");
      cancel("right");
      document.removeEventListener("pointermove", move);
      document.removeEventListener("wheel", scroll, true);
      document.documentElement.removeEventListener("pointerleave", leave);
    };
  }, [enabled]);
  return { ...hot, dismiss };
}
