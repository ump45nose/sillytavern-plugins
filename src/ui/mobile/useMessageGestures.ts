import { useEffect } from "react";
import { interactive } from "./types";

export function useMessageGestures(rp: boolean, setSheet: (node: HTMLElement) => void) {
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
      if (
        message &&
        message === chat.querySelector(".mes:last-child") &&
        message.getAttribute("is_user") !== "true"
      ) {
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
}
