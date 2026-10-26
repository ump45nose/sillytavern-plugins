import type { Item, Preferences } from "./types";

/** Resources the workbench can group and archive. Connections were grouped before archiving came. */
export type Organized = "connection" | "world";
export const organized = (kind: string): kind is Organized => kind === "connection" || kind === "world";

/** Shown for books without a group; groups may not take this name. */
export const ungroupedLabel = "未分组";

export interface ItemGroup {
  /** "" for items without a group. */
  name: string;
  items: Item[];
}

export const unarchived = (items: Item[]) => items.filter((x) => !x.archived);

/** Groups by `item.group`: named groups in Chinese collation, ungrouped last; each keeps the items' order. */
export function groupItems(items: Item[]): ItemGroup[] {
  const groups = new Map<string, Item[]>();
  for (const item of items) {
    const name = item.group ?? "";
    const rows = groups.get(name);
    if (rows) rows.push(item);
    else groups.set(name, [item]);
  }
  return [...groups]
    .map(([name, items]) => ({ name, items }))
    .sort((a, b) => Number(!a.name) - Number(!b.name) || a.name.localeCompare(b.name, "zh"));
}

/** Unarchived items in the order the lists show them, for "next". */
export const listOrder = (items: Item[]) => groupItems(unarchived(items)).flatMap((g) => g.items);

/** Explicit group per id: connection profiles in `groups`, books (by name) in `worldGroups`. */
const groupKey = (kind: Organized) => (kind === "connection" ? "groups" : "worldGroups");

export function groupName(name: string) {
  const value = name.trim();
  if (value === ungroupedLabel) throw new Error(`分组不能命名为「${ungroupedLabel}」。`);
  return value;
}

/** Preference patch putting `ids` into `group`; "" takes them out of any explicit group. */
export function withGroup(
  prefs: Preferences,
  kind: Organized,
  ids: string[],
  group: string,
): Partial<Preferences> {
  const key = groupKey(kind),
    next = { ...(prefs[key] ?? {}) };
  for (const id of ids)
    if (group) next[id] = group;
    else delete next[id];
  return { [key]: next };
}

export function withArchived(
  prefs: Preferences,
  kind: Organized,
  ids: string[],
  on: boolean,
): Partial<Preferences> {
  const set = new Set(prefs.archived?.[kind] ?? []);
  for (const id of ids) on ? set.add(id) : set.delete(id);
  return { archived: { ...prefs.archived, [kind]: [...set] } };
}

/**
 * Drops group and archive keys whose resource no longer exists. A kind whose live list is undefined
 * is left alone (not loaded yet); an empty list is trusted. Returns null when nothing is stale.
 */
export function withoutStale(
  prefs: Preferences,
  live: Partial<Record<Organized, string[] | undefined>>,
): Partial<Preferences> | null {
  const patch: Partial<Preferences> = {};
  let archived = prefs.archived;
  for (const kind of ["connection", "world"] as const) {
    const ids = live[kind];
    if (!ids) continue;
    const exists = new Set(ids),
      key = groupKey(kind),
      groups = prefs[key] ?? {};
    const stale = Object.keys(groups).filter((id) => !exists.has(id));
    if (stale.length)
      patch[key] = Object.fromEntries(Object.entries(groups).filter(([id]) => exists.has(id)));
    const list = archived?.[kind] ?? [];
    if (list.some((id) => !exists.has(id)))
      archived = { ...archived, [kind]: list.filter((id) => exists.has(id)) };
  }
  if (archived !== prefs.archived) patch.archived = archived;
  return Object.keys(patch).length ? patch : null;
}
