import {
  launch,
  session,
  ready,
  urls,
  createCharacter,
  connect,
  artifacts,
} from "./browser.mjs";
const browser = await launch();
try {
  const { page } = await session(browser);
  await ready(page, urls.validation, { probe: true });
  await createCharacter(page);
  await connect(page);
  await page.evaluate(async()=>{
    const c=SillyTavern.getContext();
    if(!c.chat.some(m=>String(m.mes).includes('# 第一章 · 雾中的来信'))){
      await TavernHelper.createChatMessages([{role:'assistant',message:'# 第一章 · 雾中的来信\n\n雨停在黄昏之前。沿河的旧书店亮起一盏灯，暖光落在窗边那封没有署名的信上。\n\n林间把书页折回原处，抬头看向门口。\n\n“你终于来了。”\n\n## 灯塔与旧码头\n\n远处传来一声雾笛。她没有追问，只将信推到桌边，像是把一个尚未讲完的故事交还给你。\n\n> 信封背面，写着一个早已从地图上消失的地名。'}]);
      await c.saveChat();
    }
  });
  await page.waitForTimeout(300);
  if (!(await page.locator(".wb-left").isVisible()))
    await page
      .getByRole("button", { name: "展开左边栏", exact: true })
      .click();
  for (const [width, height] of [
    [1366, 768],
    [1440, 900],
    [1920, 1080],
  ]) {
    await page.setViewportSize({ width, height });
    const floors = page.locator(".wb-floor-list button");
    if (await floors.count()) await floors.last().click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${artifacts}/noval-home-${width}.png` });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page
    .getByRole("button", { name: "角色与资源侧栏", exact: true })
    .click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: artifacts + "/noval-character-sidebar.png" });
} catch (e) {
  console.error(e);
  process.exitCode = 1;
} finally {
  await browser.close();
}
