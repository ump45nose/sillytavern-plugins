/** One folding section of the left column, as measured: its title row and its body's natural height. */
export interface NavSectionSize {
  id: string;
  /** The user has it expanded. */
  open: boolean;
  head: number;
  body: number;
}

/**
 * "open" shows the body, at most `max` px tall (null: its natural height); "auto" is a section the user
 * expanded that is folded to its title row for lack of room; "closed" is folded by the user.
 */
export interface NavSectionPlan {
  state: "open" | "auto" | "closed";
  max: number | null;
}

/**
 * Fit the expanded sections into a column `available` px tall. Sections that fit keep their natural
 * height. Otherwise each is held to `cap` of the column and the room left over goes back to the held
 * ones in order; if even that overflows, only the focus — the first open id in `recent` — stays open,
 * filling the room, and the other expanded sections fold to their title rows until it closes.
 * An unmeasured column (`available` <= 0) constrains nothing.
 */
export function planSections(
  sections: NavSectionSize[],
  available: number,
  recent: string[],
  { cap = 0.45, gap = 0 } = {},
): Record<string, NavSectionPlan> {
  const plan: Record<string, NavSectionPlan> = {};
  for (const s of sections) plan[s.id] = { state: s.open ? "open" : "closed", max: null };
  const open = sections.filter((s) => s.open);
  if (available <= 0 || !open.length) return plan;
  const room = available - sections.reduce((sum, s) => sum + s.head, 0) - gap * (sections.length - 1);
  const total = (sizes: number[]) => sizes.reduce((sum, n) => sum + n, 0);
  if (total(open.map((s) => s.body)) <= room) return plan;
  const limit = cap * available,
    held = open.map((s) => Math.min(s.body, limit));
  if (open.length > 1 && total(held) <= room) {
    let left = room - total(held);
    open.forEach((s, i) => {
      if (s.body <= limit) return;
      const extra = Math.min(left, s.body - held[i]);
      left -= extra;
      plan[s.id].max = held[i] + extra;
    });
    return plan;
  }
  const focus = open.find((s) => s.id === recent.find((id) => open.some((o) => o.id === id))) || open[0];
  for (const s of open)
    plan[s.id] = s === focus ? { state: "open", max: Math.max(0, room) } : { state: "auto", max: null };
  return plan;
}
