/** A world book's cast on the RP stage: the pure rules, free of the DOM and of SillyTavern. */

/** One image in `characters/<book>/<entry>/`; the label is the file name up to its first - or . */
export interface Sprite {
  label: string;
  path: string;
}
export interface CastName {
  /** The entry title, which is also the folder name. */
  name: string;
  /** The entry's keywords. */
  aliases: string[];
}

/** `张三|joy:` or `张三|joy：` opening a line: who speaks it, and with which expression. */
const TAG = /^\s*([^|\n:：]{1,24}?)[ \t]*\|[ \t]*([a-z_]+)[ \t]*[:：][ \t　]?/i;

export function parseCastTag(line: string) {
  const match = TAG.exec(line);
  if (!match || !match[1].trim()) return null;
  return { speaker: match[1].trim(), expr: match[2].toLowerCase(), length: match[0].length };
}

/** The raw message as a reader sees it: each line-opening tag becomes the speaker's name. */
export function castTagsAsNames(text: string) {
  return text
    .split("\n")
    .map((line) => {
      const tag = parseCastTag(line);
      return tag ? `${tag.speaker}：${line.slice(tag.length)}` : line;
    })
    .join("\n");
}

/**
 * The same tags in a rendered reply (SillyTavern's HTML after Markdown): a line starts the text, a
 * newline, a <br> or a block, perhaps under inline tags. The name stays as text in a marker
 * carrying the speaker and expression, so it reads even without the workbench's styles. Data
 * attributes, not a class, because the message sanitizer renames every class.
 */
const HTML_TAG =
  /(^|\n|<br\s*\/?>|<(?:p|li|div|blockquote|h[1-6]|td|th)\b[^>]*>)((?:\s|<[a-z][^>]*>)*)([^|\n:：<>"&]{1,24}?)[ \t]*\|[ \t]*([a-z_]+)[ \t]*[:：][ \t　]?/gi;

export function markCastTags(html: string) {
  if (!html.includes("|")) return html;
  return html.replace(HTML_TAG, (whole, line: string, open: string, name: string, expr: string) => {
    const speaker = name.trim();
    if (!speaker) return whole;
    return `${line}${open}<span data-wb-speaker="${speaker}" data-wb-expr="${expr.toLowerCase()}">${speaker}</span>`;
  });
}

const QUOTES = '「『“"';

/**
 * Who a passage without tags belongs to: a line that opens with a cast name (`张三：`, `【张三】`),
 * else the last cast name just before the first quotation. Names and keywords both count.
 */
export function matchSpeaker(text: string, cast: CastName[]) {
  const names = cast
    .flatMap((member) => [member.name, ...member.aliases].map((word) => ({ word: word.trim(), member })))
    .filter((x) => x.word)
    // The longest first, so 张三丰 is not read as 张三.
    .sort((a, b) => b.word.length - a.word.length);
  for (const line of text.split("\n")) {
    const opening = line.trim().replace(/^[【\[]/, "");
    for (const { word, member } of names)
      if (opening.startsWith(word) && /^[】\]]?[ \t]*[:：]|^[】\]]/.test(opening.slice(word.length)))
        return member.name;
  }
  for (const line of text.split("\n")) {
    const quote = [...line].findIndex((ch) => QUOTES.includes(ch));
    if (quote < 0) continue;
    const before = [...line].slice(Math.max(0, quote - 24), quote).join("");
    let best: { at: number; name: string } | null = null;
    for (const { word, member } of names) {
      const at = before.lastIndexOf(word);
      if (at >= 0 && (!best || at > best.at)) best = { at, name: member.name };
    }
    if (best) return best.name;
  }
  return null;
}

/** The expression asked for, else neutral, else SillyTavern's fallback expression, else any image. */
export function pickSprite(sprites: Sprite[], expr: string | null | undefined, fallback?: string) {
  for (const label of [expr, "neutral", fallback])
    if (label) {
      const hit = sprites.find((sprite) => sprite.label === label);
      if (hit) return hit;
    }
  return sprites[0] ?? null;
}

/** The instruction injected while a chat plays a world book's cast. */
export function castPrompt(cast: { name: string; labels: string[] }[]) {
  if (!cast.length) return "";
  const list = cast
    .map((member) => (member.labels.length ? `${member.name}（${member.labels.join("、")}）` : member.name))
    .join("；");
  return [
    `[多角色立绘] 登场角色：${list}。`,
    "某个角色说话或有明显动作的段落，以「名字|表情:」开头，例如：张三|joy:「……」。",
    "名字只用上面列出的；表情从该角色括号里选最接近的一个，没有括号时写 neutral。旁白段落不加前缀。",
  ].join("\n");
}

/** Names the server keeps as they are when it makes them folders (the rules of sanitize-filename). */
export function isPathSafe(name: string) {
  return (
    !!name &&
    new TextEncoder().encode(name).length <= 255 &&
    !/[/?<>\\:*|"]/.test(name) &&
    // eslint-disable-next-line no-control-regex
    !/[\x00-\x1f\x80-\x9f]/.test(name) &&
    !/^\.+$/.test(name) &&
    !/^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$/i.test(name) &&
    !/[. ]+$/.test(name)
  );
}

/** SillyTavern's built-in expressions; any other label is the user's own. */
export const EXPRESSIONS = [
  "admiration",
  "amusement",
  "anger",
  "annoyance",
  "approval",
  "caring",
  "confusion",
  "curiosity",
  "desire",
  "disappointment",
  "disapproval",
  "disgust",
  "embarrassment",
  "excitement",
  "fear",
  "gratitude",
  "grief",
  "joy",
  "love",
  "nervousness",
  "neutral",
  "optimism",
  "pride",
  "realization",
  "relief",
  "remorse",
  "sadness",
  "surprise",
];

/** The labels a file name gives, as SillyTavern reads them: `joy.png`, `joy-2.png`, `joy.alt.png`. */
export function spriteLabel(fileName: string) {
  const stem = fileName.replace(/\.[^.]+$/, "").toLowerCase();
  return stem.match(/^(.+?)(?:[-.].*?)?$/)?.[1] ?? stem;
}

/** The label a new image starts with: its file name's, kept to the letters a tag can carry. */
export function suggestLabel(fileName: string) {
  return spriteLabel(fileName).replace(/[^a-z_]+/g, "");
}

/**
 * What uploading a batch under these labels would do: a label a tag cannot carry, a label twice in
 * the batch, an image it replaces (the folder holds `<label>.*`), a label of the user's own.
 */
export function stagedNotes(labels: string[], stems: string[]) {
  return labels.map((label, i) =>
    !/^[a-z_]+$/.test(label)
      ? "invalid"
      : labels.indexOf(label) !== i || labels.lastIndexOf(label) !== i
        ? "repeat"
        : stems.includes(label)
          ? "replace"
          : EXPRESSIONS.includes(label)
            ? ""
            : "custom",
  );
}
