import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from "react";

export const motionAllowed = () =>
  !matchMedia("(prefers-reduced-motion: reduce)").matches &&
  !document.body.classList.contains("reduced-motion");

const motionListeners = new Set<() => void>();
let stopMotionWatch: (() => void) | undefined;
function subscribeMotion(listener: () => void) {
  motionListeners.add(listener);
  if (motionListeners.size === 1) {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    let allowed = motionAllowed();
    const changed = () => {
      const next = motionAllowed();
      if (next === allowed) return;
      allowed = next;
      motionListeners.forEach((notify) => notify());
    };
    const observer = new MutationObserver(changed);
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    media.addEventListener("change", changed);
    stopMotionWatch = () => {
      observer.disconnect();
      media.removeEventListener("change", changed);
    };
  }
  return () => {
    motionListeners.delete(listener);
    if (!motionListeners.size) {
      stopMotionWatch?.();
      stopMotionWatch = undefined;
    }
  };
}

/** Follow both the system setting and the workbench preference through a shared observer. */
export const useMotionAllowed = () => useSyncExternalStore(subscribeMotion, motionAllowed);

/** Retain the real component through its exit; do not clone its native inputs or handlers. */
export function usePresence<T>(value: T | null, duration = 200) {
  const allowed = useMotionAllowed(),
    [retained, setRetained] = useState(value),
    [exiting, setExiting] = useState(false);
  useLayoutEffect(() => {
    if (value !== null) {
      setRetained(value);
      setExiting(false);
      return;
    }
    if (retained === null || !allowed || duration <= 0) {
      setRetained(null);
      setExiting(false);
      return;
    }
    setExiting(true);
    const timer = setTimeout(() => {
      setRetained(null);
      setExiting(false);
    }, duration);
    return () => clearTimeout(timer);
  }, [value, retained, duration, allowed]);
  return { value: value ?? retained, exiting: value === null && exiting };
}

/** Make a short click visible after pointer-up, without delaying the native action. */
export function ClickFeedback() {
  useEffect(() => {
    const running = new Map<HTMLElement, Animation>();
    const clear = () => {
      running.forEach((a, node) => {
        delete node.dataset.wbClickMotion;
        a.cancel();
      });
      running.clear();
    };
    const click = (event: MouseEvent) => {
      const node =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>(
              "button,[role=button],.menu_button,.qr--action,input[type=checkbox],input[type=radio]",
            )
          : null;
      if (
        !node ||
        !motionAllowed() ||
        !node.closest(".wb-ui,#send_form,#chat .mes") ||
        node.closest("#tavern_helper,[inert]") ||
        node.matches(":disabled,[aria-disabled=true]")
      )
        return;
      // Tint the existing surface without moving text, icons, or native positioning transforms.
      running.get(node)?.cancel();
      const base = getComputedStyle(node).boxShadow,
        ring = "inset 0 0 0 1px color-mix(in srgb,var(--wb-accent) 28%,transparent)",
        animation = node.animate(
          [
            { boxShadow: base },
            { boxShadow: base === "none" ? ring : `${base}, ${ring}`, offset: 0.35 },
            { boxShadow: base },
          ],
          { duration: 200, easing: "cubic-bezier(0.2,0,0,1)" },
        );
      running.set(node, animation);
      node.dataset.wbClickMotion = "true";
      const finish = () => {
        if (running.get(node) === animation) {
          running.delete(node);
          delete node.dataset.wbClickMotion;
        }
      };
      animation.onfinish = finish;
      animation.oncancel = finish;
    };
    const unsubscribe = subscribeMotion(() => {
      if (!motionAllowed()) clear();
    });
    document.addEventListener("click", click, true);
    return () => {
      document.removeEventListener("click", click, true);
      unsubscribe();
      clear();
    };
  }, []);
  return null;
}
