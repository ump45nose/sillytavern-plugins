import fs from "node:fs";
import { launch, session, ready, urls, openResource } from "./browser.mjs";

// Visual QA is separate from pointer tests. Art uses the installed official sample,
// projected temporarily through its native nodes; no character/chat edits occur.
const dir = "artifacts/rp-runtime"; fs.mkdirSync(dir, { recursive: true });
const browser = await launch(); let page, original;
try {
  ({ page } = await session(browser)); await page.setViewportSize({ width:1496, height:817 });
  await ready(page, urls.validation, { probe:true });
  original = await page.evaluate(() => ({
    prefs:structuredClone(workbench.host.prefs()), character:workbench.host.snapshot().character?.id,
    input:document.getElementById("send_textarea").value,
    background:document.getElementById("bg1").style.cssText,
    expression:document.querySelector("#expression-holder img.expression")?.getAttribute("src") ?? null,
  }));
  await page.evaluate(async () => {
    const sample = workbench.host.snapshot().characters.find(c => c.name === "Seraphina");
    if (sample) await workbench.host.selectCharacter(sample.id);
    workbench.host.preference({ layout:"rp", rpTopAuto:false, rpDialogWidth:88, rpSpriteScale:91, rpTextSize:19, rpShowPortraits:true });
    workbench.unmount(); await workbench.mount();
  });
  const settle = () => page.waitForTimeout(400), role = name => page.getByRole("button", { name, exact:true });
  await settle(); await page.screenshot({ path:`${dir}/native-default-1496.png` });
  await page.evaluate(async () => {
    const name = workbench.host.snapshot().character?.name;
    const sprites = await fetch("/api/sprites/get?name=" + encodeURIComponent(name)).then(r => r.json());
    const sprite = sprites.find(s => s.label === "joy") || sprites[0];
    if (sprite) document.querySelector("#expression-holder img.expression").setAttribute("src", sprite.path);
    document.getElementById("bg1").style.backgroundImage = 'url("/backgrounds/forest%20treehouse%20fireworks%20air%20baloons%20(by%20kallmeflocc).jpg")';
  });
  await page.waitForFunction(() => [...document.querySelectorAll(".wb-rp-stage img")].every(n => n.complete)); await settle();
  await page.screenshot({ path:`${dir}/native-stage-1496.png` });
  await page.locator("#send_textarea").fill("我推开窗，朝港口望去。\n\n夜色还没有散尽，远处的灯火沿着河岸亮起。");
  await page.screenshot({ path:`${dir}/native-input-1496.png` });
  await role("展开 RP 输入区").click(); await settle(); await page.screenshot({ path:`${dir}/native-expanded-1496.png` });
  await role("还原 RP 输入区").click(); await settle(); await role("上一段对白").click(); await settle();
  await role("展开左边栏").click(); await openResource(page,'世界书详情'); await settle();
  await page.screenshot({ path:`${dir}/native-both-1496.png` });
  await page.setViewportSize({ width:1366, height:768 }); await settle(); await page.screenshot({ path:`${dir}/native-both-1366.png` });
  await role("关闭右栏").click(); await role("收纳左边栏").click(); await page.setViewportSize({ width:1496, height:817 }); await settle();
  await role("固定顶栏").click(); await role("下一段对白或输入").focus(); await page.mouse.move(740,400); await settle();
  await page.screenshot({ path:`${dir}/native-top-hidden-1496.png` });
  await role("隐藏界面").click(); await settle(); await page.screenshot({ path:`${dir}/native-stage-only-1496.png` });
  console.log(`Captured native RP screenshots in ${dir}`);
} finally {
  if (page && original) await page.evaluate(async value => {
    if (value.character) await workbench.host.selectCharacter(value.character);
    document.getElementById("bg1").style.cssText = value.background;
    const expression = document.querySelector("#expression-holder img.expression");
    if (expression) value.expression === null ? expression.removeAttribute("src") : expression.setAttribute("src", value.expression);
    workbench.host.setInput(value.input); workbench.unmount();
    SillyTavern.getContext().extensionSettings.workbench = value.prefs;
    await (await import("/script.js")).saveSettings(); await workbench.mount();
  }, original).catch(() => {});
  await browser.close();
}
