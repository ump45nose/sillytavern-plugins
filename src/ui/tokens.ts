import { useEffect, useMemo, useRef, useState } from "react";
import type { HostAdapter } from "../host/adapter";

/**
 * Debounced token counts for [id, text] pairs with the active tokenizer. Counting is a hint: the map stays
 * empty while the host has no tokenizer, and a failed count leaves the previous numbers in place. Texts
 * counted last time are not counted again, so editing one entry of a large book counts one text.
 */
export function useTokenCounts(host: HostAdapter, items: [string, string][], delay = 400) {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const known = useRef(new Map<string, number>());
  const source = useMemo(() => items.map(([id, text]) => id + "\u0001" + text).join("\u0000"), [items]);
  useEffect(() => {
    if (!items.length) return;
    let live = true;
    const timer = setTimeout(async () => {
      try {
        const next: Record<string, number> = {},
          seen = new Map<string, number>();
        for (const [id, text] of items) {
          let n = seen.get(text) ?? known.current.get(text);
          if (n === undefined) {
            const counted = await host.tokenCount(text);
            if (counted === null || !live) return;
            n = counted;
          }
          seen.set(text, n);
          next[id] = n;
        }
        known.current = seen;
        if (live) setCounts(next);
      } catch {
        /* Keep the last counts. */
      }
    }, delay);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [source]);
  return counts;
}
