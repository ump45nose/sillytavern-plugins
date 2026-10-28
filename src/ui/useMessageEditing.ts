import { useEffect, useRef } from "react";
import type { HostAdapter } from "../host/adapter";

/** Keep the message at its current reading position across ST's native edit transitions. */
export function useMessageEditing(host: HostAdapter) {
  const pending = useRef<{
    node: HTMLElement;
    top: number;
    entering: boolean;
  } | null>(null);
  useEffect(() => {
    const chat = document.getElementById("chat")!;
    let frame = 0;
    const clear = () => {
      pending.current = null;
      cancelAnimationFrame(frame);
      frame = 0;
    };
    const restore = () => {
      const saved = pending.current;
      if (!saved || !chat.contains(saved.node)) return clear();
      chat.scrollTo({
        top: chat.scrollTop + saved.node.getBoundingClientRect().top - saved.top,
        behavior: "instant",
      });
    };
    const settle = () => {
      const saved = pending.current;
      if (!saved || !chat.contains(saved.node)) return clear();
      const field = saved.node.querySelector<HTMLTextAreaElement>(".edit_textarea");
      if (saved.entering !== !!field) return;
      if (field) {
        field.focus({ preventScroll: true });
        field.setSelectionRange(0, 0);
        field.scrollTop = 0;
      }
      restore();
      cancelAnimationFrame(frame);
      // ReadingPresentation updates the header in this frame; account for its final height too.
      frame = requestAnimationFrame(() => {
        if (saved.entering && field && document.activeElement !== field) {
          field.focus({ preventScroll: true });
          field.setSelectionRange(0, 0);
          field.scrollTop = 0;
        }
        restore();
        clear();
      });
    };
    const capture = (event: Event) => {
      if (document.body.classList.contains("wb-rp") && !document.body.hasAttribute("data-wb-rp-history"))
        return;
      const control = (event.target as Element)?.closest<HTMLElement>(
        ".mes_edit,.mes_edit_done,.mes_edit_cancel",
      );
      const node = control?.closest<HTMLElement>(".mes");
      if (!node) return;
      clear();
      pending.current = {
        node,
        top: node.getBoundingClientRect().top,
        entering: control!.classList.contains("mes_edit"),
      };
    };
    const off = host.chatObserver.subscribe((change) => {
      if (change.nodes || change.editing) settle();
    });
    chat.addEventListener("click", capture, true);
    chat.addEventListener("wheel", clear, { passive: true });
    chat.addEventListener("touchmove", clear, { passive: true });
    return () => {
      clear();
      off();
      chat.removeEventListener("click", capture, true);
      chat.removeEventListener("wheel", clear);
      chat.removeEventListener("touchmove", clear);
    };
  }, [host]);
}
