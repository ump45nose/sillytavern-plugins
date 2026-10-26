/** How many chat messages a generation sends; examples and injections are not chat messages. */
export interface ContextLimit {
  enabled: boolean;
  limit: number;
  /** Also trim background (quiet) generations: extensions, /commands. */
  quiet: boolean;
}

export const defaultContextLimit: ContextLimit = { enabled: false, limit: 10, quiet: false };

/**
 * SillyTavern's generate interceptor: `chat` is the generation's own copy of the messages it sends
 * (hidden floors already left out), so dropping its oldest entries changes nothing that is saved.
 */
export function trimContext(chat: unknown[], setting: ContextLimit | undefined, type: string) {
  if (!setting?.enabled || (type === "quiet" && !setting.quiet)) return;
  const limit = Math.max(1, Math.floor(setting.limit));
  if (chat.length > limit) chat.splice(0, chat.length - limit);
}

/** The oldest floor still sent, or -1 when nothing is trimmed; hidden floors are never sent or counted. */
export function firstSentFloor(
  floors: { id: number; hidden?: boolean }[],
  setting: ContextLimit | undefined,
) {
  if (!setting?.enabled) return -1;
  const sent = floors.filter((f) => !f.hidden);
  const limit = Math.max(1, Math.floor(setting.limit));
  return sent.length > limit ? sent[sent.length - limit].id : -1;
}
