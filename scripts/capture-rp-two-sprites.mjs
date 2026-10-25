import assert from "node:assert/strict";
import fs from "node:fs";
import { launch, session, ready, urls } from "./browser.mjs";

// Session-only visual demonstration using approved artwork and real RP components.
// Block persistence: selecting the official sample and changing visual preferences
// must not replace the user's saved character, persona, background or chat.
const directory = "docs/design/rp-desktop/two-sprites";
const assets = "http://192.168.31.201:33080/sillytavern/rp-desktop/assets/";
fs.mkdirSync(directory, { recursive:true });
const browser = await launch();
try {
  const { page, errors } = await session(browser);
  await page.route("**/api/settings/save", route => route.fulfill({ json:{} }));
  await page.route("**/api/chats/save", route => route.fulfill({ json:{ result:"ok" } }));
  await page.setViewportSize({ width:1496, height:817 });
  await ready(page, urls.validation, { probe:true });
  await page.evaluate(async () => {
    const sample = workbench.host.snapshot().characters.find(c => c.name === "Seraphina");
    if (sample) await workbench.host.selectCharacter(sample.id);
    workbench.host.preference({ layout:"rp", rpTopAuto:false, rpDialogWidth:88, rpSpriteScale:91, rpTextSize:19, rpShowPortraits:true });
    workbench.unmount(); await workbench.mount();
  });
  await page.evaluate(url => {
    const context = SillyTavern.getContext();
    context.chatMetadata.workbenchRP = {
      ...context.chatMetadata.workbenchRP,
      userSprite:url + "r-user-character.webp",
      scene:{ day:"12", location:"樱花小径", weather:"晴 · 微风", time:"16:40" },
    };
    document.querySelector("#expression-holder img.expression").setAttribute("src", url + "r-character.webp");
    document.getElementById("bg1").style.backgroundImage = `url("${url}r-background.webp")`;
    workbench.host.preference({ rpSpriteScale:91 });
  }, assets);
  const role = name => page.getByRole("button", { name, exact:true });
  const settle = () => page.waitForTimeout(450);
  await page.waitForFunction(() => document.querySelectorAll(".wb-rp-stage .is-sprite img").length === 2 && [...document.querySelectorAll(".wb-rp-stage img")].every(i => i.complete && i.naturalWidth > 0));
  await settle();
  const measure = () => page.evaluate(() => {
    const rect = n => { const { x,y,width,height } = n.getBoundingClientRect(); return { x,y,width,height }; };
    return {
      sprites:[...document.querySelectorAll(".wb-rp-stage .is-sprite img")].map(i => ({ ...rect(i), naturalWidth:i.naturalWidth, naturalHeight:i.naturalHeight })),
      portraitCount:document.querySelectorAll(".wb-rp-stage .is-portrait").length,
      viewport:{ width:innerWidth, height:innerHeight },
    };
  });
  const report = [];
  const capture = async name => {
    await settle();
    const result = await measure();
    assert.equal(result.sprites.length, 2); assert.equal(result.portraitCount, 0);
    for (const sprite of result.sprites) {
      assert.ok(sprite.x >= 0 && sprite.x + sprite.width <= result.viewport.width + 1);
      assert.ok(sprite.y >= 0 && sprite.y + sprite.height <= result.viewport.height + 1);
      assert.ok(sprite.naturalHeight > sprite.naturalWidth);
    }
    report.push({ name, ...result });
    await page.screenshot({ path:`${directory}/${name}.png` });
  };
  await capture("dialogue");
  assert.equal(await page.locator(".wb-rp-actor.is-speaking").count(), 1);
  await page.locator("#send_textarea").fill("我接过信封，望向小径尽头的樱花。\n\n“明天这个时候，我们还在这里见面。”");
  await capture("input");
  await role("展开 RP 输入区").click(); await capture("expanded");
  await role("还原 RP 输入区").click();
  await role("隐藏界面").click(); await capture("stage-only");
  await role("显示界面").click();
  await page.setViewportSize({ width:1366, height:768 }); await capture("compact");
  await page.evaluate(() => {
    delete SillyTavern.getContext().chatMetadata.workbenchRP.userSprite;
    workbench.host.preference({ rpSpriteScale:91 });
  });
  await settle();
  assert.equal(await page.locator(".wb-rp-user.is-portrait").count(), 1);
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${directory}/verification.json`, JSON.stringify({ source:urls.validation, checks:report, speakingStates:true, portraitFallback:true, errors }, null, 2));
  console.log(`Captured ${report.length} actual RP views with two approved sprites; no settings or chat data saved.`);
} finally {
  await browser.close();
}
