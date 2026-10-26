import type { HostAdapter } from "../adapter";
import type { Data, Preferences } from "../types";
import { ctx } from "../internals";
import { groupName, withArchived, withGroup, withoutStale, type Organized } from "../organize";

/** Grouping and archiving of world books and connection profiles; both live in workbench preferences. */
export const organizeMethods = {
  /** Where a book or profile is in use; archiving is refused while this is not empty. */
  resourceUsage(this: HostAdapter, kind: Organized, id: string): string[] {
    const c = ctx();
    if (kind === "connection")
      return c.extensionSettings.connectionManager?.selectedProfile === id ? ["当前连接"] : [];
    const uses: string[] = [];
    if (this.world?.selected_world_info?.includes(id)) uses.push("全局启用");
    const characters: Data[] = c.characters ?? [];
    for (const x of characters) if (x.data?.extensions?.world === id) uses.push(`角色卡「${x.name}」`);
    for (const lore of (this.world?.world_info?.charLore ?? []) as Data[])
      if (lore.extraBooks?.includes(id)) {
        const owner = characters.find((x) => String(x.avatar).replace(/\.[^.]+$/, "") === lore.name);
        uses.push(`角色卡「${owner?.name ?? lore.name}」附加`);
      }
    if (c.chatMetadata?.world_info === id) uses.push("当前聊天绑定");
    for (const [avatar, d] of Object.entries<Data>(c.powerUserSettings.persona_descriptions ?? {}))
      if (d?.lorebook === id) uses.push(`人设「${c.powerUserSettings.personas?.[avatar] ?? avatar}」`);
    return uses;
  },
  /** Archives or restores; items in use stay unarchived and come back as errors. */
  async archiveResources(this: HostAdapter, kind: Organized, ids: string[], on: boolean) {
    const done: string[] = [],
      errors: { id: string; message: string }[] = [];
    for (const id of ids) {
      const uses = on ? this.resourceUsage(kind, id) : [];
      if (uses.length) errors.push({ id, message: `正在使用（${uses.join("、")}），不能归档` });
      else done.push(id);
    }
    if (done.length) await this.savePreference(withArchived(this.prefs(), kind, done, on));
    return { done, errors };
  },
  /** Moves items into `group`; "" takes them out of any group. */
  async setResourceGroup(this: HostAdapter, kind: Organized, ids: string[], group: string) {
    await this.savePreference(withGroup(this.prefs(), kind, ids, groupName(group)));
  },
  /** Renames a group: moves every item in it to the new name. */
  async renameResourceGroup(this: HostAdapter, kind: Organized, from: string, to: string) {
    const ids = this.snapshot()
      .resources[kind].filter((x) => (x.group ?? "") === from)
      .map((x) => x.id);
    await this.setResourceGroup(kind, ids, to);
  },
  /**
   * Explicit organizing actions are saved at once and confirmed, unlike the debounced UI preferences:
   * a reload right after archiving must not lose it. A failed save puts the previous values back.
   */
  async savePreference(this: HostAdapter, patch: Partial<Preferences>) {
    const settings = ctx().extensionSettings.workbench,
      previous = Object.fromEntries(Object.keys(patch).map((k) => [k, settings[k]]));
    Object.assign(settings, patch);
    this.invalidate("prefs");
    try {
      await this.persistSettings();
    } catch (error) {
      Object.assign(settings, previous);
      this.invalidate("prefs");
      throw error;
    }
  },
  /** Forgets groups and archive marks of books and profiles that no longer exist. */
  pruneOrganization(this: HostAdapter) {
    const c = ctx(),
      books: string[] = c.getWorldInfoNames(),
      profiles: Data[] | undefined = c.extensionSettings.connectionManager?.profiles;
    // An empty book list at start-up may simply not be loaded yet; dropping every group on it would be unrecoverable.
    const patch = withoutStale(this.prefs(), {
      world: books.length ? books : undefined,
      connection: profiles?.map((p) => p.id),
    });
    if (patch) this.preference(patch);
  },
};
