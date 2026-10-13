import { useEffect, useState } from "react";
/** Observe only the two native menus; avoid rescanning chat when a plugin updates a tool. */
export function useTools() {
  const [, update] = useState(0);
  useEffect(() => {
    let frame = 0;
    const observer = new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => update(n => n + 1)); });
    for (const node of document.querySelectorAll("#options,#extensionsMenu")) observer.observe(node, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class", "style", "disabled", "aria-disabled", "title", "id", "data-action", "data-command"] });
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, []);
}
