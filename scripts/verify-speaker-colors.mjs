// W6 speaker colors: a character's color set in its editor tints only its quoted dialogue, persona
// colors tint the user's, pale colors stay readable in both themes, and clearing restores the theme color.
import assert from "node:assert/strict";
import { artifacts, chooseLayout, createCharacter, launch, parseColor, ready, session, urls } from "./browser.mjs";

const browser = await launch();
const { page } = await session(browser);
const check = (name) => console.log("PASS", name);
const original = await (async () => {
  await ready(page, urls.validation, { probe: true });
  // Left over from an interrupted run would hide the theme color this check starts from.
  const value = await page.evaluate(() => structuredClone(workbench.host.prefs().speakerColors));
  return value && Object.keys(value).length ? value : undefined;
})();
try {
  await createCharacter(page);
  // One quoted line from each side, rendered by SillyTavern itself.
  await page.evaluate(async () => {
    const c = SillyTavern.getContext();
    for (const m of [
      { name: c.name2, is_user: false, mes: '她说"今晚有雾。"' },
      { name: c.name1, is_user: true, mes: '我回答"那就点灯。"' },
    ]) {
      c.chat.push({ ...m, send_date: Date.now(), extra: {} });
      c.addOneMessage(c.chat.at(-1));
    }
  });
  // Computed colors come back as oklch; a canvas pixel gives comparable sRGB.
  const quoteColor = (user) =>
    page.evaluate((user) => {
      const q = [...document.querySelectorAll(`#chat .mes[is_user="${user}"] .mes_text q`)].at(-1);
      const g = document.createElement("canvas").getContext("2d");
      g.fillStyle = getComputedStyle(q).color;
      g.fillRect(0, 0, 1, 1);
      const [r, gr, b] = g.getImageData(0, 0, 1, 1).data;
      return `rgb(${r}, ${gr}, ${b})`;
    }, user);
  const before = await quoteColor(false);

  await page.getByRole("button", { name: "角色与资源侧栏", exact: true }).click();
  await page.locator(".wb-panel-tabs").getByRole("button", { name: "角色", exact: true }).click();
  await page.locator(".wb-character-profile").waitFor();
  await page.getByRole("button", { name: "编辑角色", exact: true }).click();
  await page.getByLabel("对白颜色", { exact: true }).fill("#c0392b");
  await page.waitForFunction(() => document.getElementById("wb-speaker-colors"));
  const tinted = parseColor(await quoteColor(false));
  assert.notDeepEqual(tinted, parseColor(before), "character quote takes its color");
  assert.ok(tinted[0] > tinted[1] + 40, "character quote is red-ish: " + tinted);
  assert.equal(await quoteColor(true), before, "user quote keeps the theme color");
  check("character color set in the editor tints only that character's dialogue");

  // A pale persona color is darkened on paper and kept light on the dark theme.
  const persona = await page.evaluate(async () => (await import("/scripts/personas.js")).user_avatar);
  await page.evaluate((id) => {
    const p = workbench.host.prefs();
    workbench.host.preference({ speakerColors: { ...p.speakerColors, ["persona:" + id]: "#fff700" } });
  }, persona);
  await page.waitForTimeout(100);
  const light = parseColor(await quoteColor(true));
  assert.notDeepEqual(light, parseColor(before), "user quote takes the persona color");
  const lum = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
  assert.ok(lum(light) < 150, "pale persona color is darkened on paper: " + light);
  await page.evaluate(() => (document.documentElement.dataset.wbTheme = "dark"));
  const dark = parseColor(await quoteColor(true));
  assert.ok(lum(dark) > 170, "pale persona color stays light on dark: " + dark);
  await page.evaluate(() => delete document.documentElement.dataset.wbTheme);
  check("persona colors tint the user's dialogue and stay readable in both themes");
  await page.screenshot({ path: artifacts + "/speaker-colors.png" });

  await page.getByRole("button", { name: "清除", exact: true }).first().click();
  await page.waitForTimeout(100);
  assert.equal(await quoteColor(false), before, "cleared character follows the theme again");
  check("clearing a color restores the theme color");

  // The RP stage shows the same native message nodes, so the same rule reaches it.
  await page.evaluate(() => {
    const id = workbench.host.snapshot().character.id;
    workbench.host.preference({ speakerColors: { ["character:" + id]: "#c0392b" } });
  });
  await chooseLayout(page, "RP");
  assert.deepEqual(parseColor(await quoteColor(false)), tinted, "RP stage keeps the character color");
  await page.screenshot({ path: artifacts + "/speaker-colors-rp.png" });
  await chooseLayout(page, "Noval");
  check("the RP layout shows the same speaker colors");

} finally {
  // Saved at once: the debounced save would not run before the browser closes.
  await page.evaluate(async (value) => {
    workbench.host.preference({ speakerColors: value });
    await (await import("/script.js")).saveSettings();
    await SillyTavern.getContext().reloadCurrentChat();
  }, original ?? undefined);
  await browser.close();
}
