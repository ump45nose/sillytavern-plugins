import { useEffect, useMemo, useRef, useState } from "react";
import type { HostAdapter } from "../host/adapter";

/**
 * Debounced token counts for [id, text] pairs with the active tokenizer. Counting is a hint: the map stays
 * empty while the host has no tokenizer, and a failed count leaves the previous numbers in place. A text is
 * counted once (results are kept by text), so editing one entry of a large book counts one text.
 *
 * `only` limits counting to those ids (e.g. the rows on screen); ids counted before keep their numbers.
 * `complete` says whether every item has a count, i.e. whether a sum over the result is the whole total.
 */
export function useTokenTally(
  host: HostAdapter,
  items: [string, string][],
  delay = 400,
  only?: readonly string[] | null,
) {
  const known = useRef(new Map<string, number>()),
    // The last count per id stands in while an edited text waits for its recount.
    lastById = useRef(new Map<string, number>());
  const [version, setVersion] = useState(0);
  const wanted = useMemo(() => {
    if (!only) return items;
    const ids = new Set(only);
    return items.filter(([id]) => ids.has(id));
  }, [items, only]);
  useEffect(() => {
    const missing = wanted.filter(([, text]) => !known.current.has(text));
    if (!missing.length) return;
    let live = true;
    const timer = setTimeout(async () => {
      try {
        for (const [, text] of missing) {
          if (known.current.has(text)) continue;
          const n = text ? await host.tokenCount(text) : 0;
          if (n === null || !live) return;
          known.current.set(text, n);
        }
      } catch {
        /* Keep the last counts. */
      } finally {
        if (live) setVersion((v) => v + 1);
      }
    }, delay);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [wanted]);
  return useMemo(() => {
    const counts: Record<string, number> = {},
      cache = known.current;
    let complete = true;
    for (const [id, text] of items) {
      const n = cache.get(text);
      if (n === undefined) {
        complete = false;
        const last = lastById.current.get(id);
        if (last !== undefined) counts[id] = last;
      } else {
        counts[id] = n;
        lastById.current.set(id, n);
      }
    }
    // Texts no longer in the list (edits typed through) are dropped once the cache grows past it.
    if (cache.size > items.length * 2 + 64) {
      const live = new Set(items.map(([, text]) => text));
      for (const text of cache.keys()) if (!live.has(text)) cache.delete(text);
    }
    return { counts, complete };
  }, [items, version]);
}

/** Counts by id for every item (see useTokenTally). */
export const useTokenCounts = (host: HostAdapter, items: [string, string][], delay = 400) =>
  useTokenTally(host, items, delay).counts;
