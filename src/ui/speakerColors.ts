/** Keys of `Preferences.speakerColors`: a character by its avatar file, a persona by its avatar id. */
export const speakerKey = (kind: "character" | "persona", id: string) => `${kind}:${id}`;

const quote = (value: string) => `"${value.replace(/["\\]/g, "\\$&")}"`;

/**
 * Colors the quoted dialogue (`<q>`, which SillyTavern renders for quotes) of each speaker that has
 * a color; the color is clamped to stay readable on the paper and dark themes. A character's messages
 * carry its name as `ch_name`; a user message is told by its persona avatar, which survives renames
 * and appears as `User Avatars/<file>` or `/thumbnail?type=persona&file=<file>`.
 */
export function speakerCss(
  colors: Record<string, string>,
  characters: { id: string; name: string }[],
  personas: { id: string }[],
) {
  const rules: string[] = [];
  const add = (target: string, color: string | undefined) => {
    if (color && /^#[0-9a-f]{6}$/i.test(color))
      rules.push(`#chat ${target} .mes_text q{--wb-speaker:${color};color:var(--wb-speaker-ink)}`);
  };
  for (const c of characters)
    if (c.name) add(`.mes[is_user="false"][ch_name=${quote(c.name)}]`, colors[speakerKey("character", c.id)]);
  for (const p of personas)
    add(
      `.mes[is_user="true"]:has(.avatar img:is([src*=${quote("Avatars/" + p.id)}],[src*=${quote("file=" + encodeURIComponent(p.id))}]))`,
      colors[speakerKey("persona", p.id)],
    );
  if (!rules.length) return "";
  return (
    `#chat .mes .mes_text q{--wb-speaker-ink:oklch(from var(--wb-speaker) min(l,0.55) c h)}` +
    `:root[data-wb-theme="dark"] #chat .mes .mes_text q{--wb-speaker-ink:oklch(from var(--wb-speaker) max(l,0.75) c h)}` +
    rules.join("")
  );
}
