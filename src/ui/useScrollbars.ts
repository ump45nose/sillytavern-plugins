import { useEffect } from "react";

/** Marks whatever is scrolling with .wb-scrolling until it has been still for a moment. */
export function useScrollbars() {
  useEffect(() => {
    const timers = new WeakMap<Element, ReturnType<typeof setTimeout>>();
    const scroll = (event: Event) => {
      const target = event.target === document ? document.scrollingElement : event.target;
      if (!(target instanceof Element)) return;
      target.classList.add("wb-scrolling");
      clearTimeout(timers.get(target));
      timers.set(
        target,
        setTimeout(() => target.classList.remove("wb-scrolling"), 900),
      );
    };
    document.addEventListener("scroll", scroll, { capture: true, passive: true });
    return () => document.removeEventListener("scroll", scroll, true);
  }, []);
}
