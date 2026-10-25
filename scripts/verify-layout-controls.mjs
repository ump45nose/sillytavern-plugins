import assert from "node:assert/strict";
import fs from "node:fs";
import { gunzipSync } from "node:zlib";
import { launch, session, ready, urls, artifacts, chooseLayout, toggleRight } from "./browser.mjs";

// Real validation UI, with settings persisted only inside this browser's response replay.
// The user's saved RP demo, preferences, persona and chats are not changed by verification.
const directory = artifacts + "/layout-controls"; fs.mkdirSync(directory, { recursive:true });
const browser = await launch(), checks = [];
const pass = name => { checks.push(name); console.log("PASS", name); };
try {
  const { page, errors } = await session(browser);
  let settings;
  await page.route("**/api/settings/save", async route => {
    let body = route.request().postDataBuffer();
    if (route.request().headers()["content-encoding"] === "gzip") body = gunzipSync(body);
    settings = JSON.parse(body.toString());
    await route.fulfill({ json:{} });
  });
  await page.route("**/api/settings/get", async route => {
    const response = await route.fetch(), data = await response.json();
    if (settings) data.settings = JSON.stringify(settings);
    await route.fulfill({ response, json:data });
  });
  await page.route("**/api/chats/save", route => route.fulfill({ json:{ result:"ok" } }));
  await page.setViewportSize({ width:1496, height:817 });
  await ready(page, urls.validation, { probe:true }); await page.waitForTimeout(1200);
  const role = name => page.getByRole("button", { name, exact:true });
  const switcher = () => page.getByRole("radiogroup", { name:"切换工作台", exact:true });
  const option = name => switcher().getByRole("radio", { name, exact:true });
  const settle = () => page.waitForTimeout(450);
  const collapsed = () => page.evaluate(() => document.body.classList.contains("wb-rp-top-collapsed"));
  const choose = async name => { await chooseLayout(page, name); await settle(); };
  await page.evaluate(() => { workbench.host.preference({ layout:"rp", rpTopAuto:false }); window.__layoutNative = { chat:document.getElementById("chat"), input:document.getElementById("send_textarea"), form:document.getElementById("send_form") }; }); await settle();
  assert.equal(await role("固定顶栏").getAttribute("aria-pressed"), "true");
  assert.equal(await role("固定顶栏").locator(".wb-i-pin").count(), 1);
  await role("固定顶栏").click(); await page.mouse.move(750, 400); await settle();
  assert.equal(await collapsed(), true); assert.equal(await page.locator(".wb-top-pin").getAttribute("aria-pressed"), "false");
  const strip = await role("显示顶栏").evaluate(node => ({ height:node.getBoundingClientRect().height, background:getComputedStyle(node).backgroundColor }));
  assert.equal(strip.height, 14); assert.equal(strip.background, "rgba(0, 0, 0, 0)");
  pass("pin selection means fixed; unpin hides the header without an opaque reveal strip");

  await page.mouse.move(740, 4); await page.waitForTimeout(70);
  const moving = await page.locator(".wb-top").evaluate(node => ({ opacity:Number(getComputedStyle(node).opacity), y:node.getBoundingClientRect().y }));
  assert.ok(moving.opacity > 0 && moving.opacity < 1, JSON.stringify(moving)); await settle();
  await page.mouse.move(740, 35); await settle(); assert.equal(await collapsed(), false);
  await page.mouse.move(740, 400); await settle(); assert.equal(await collapsed(), true);
  await role("显示顶栏").focus(); await role("显示顶栏").press("Enter"); await settle();
  assert.equal(await collapsed(), false);
  assert.equal(await page.locator(".wb-top").evaluate(node => node.contains(document.activeElement)), true);
  await role("固定顶栏").click(); await page.mouse.move(750, 400); await settle();
  assert.equal(await collapsed(), false); assert.equal(await role("固定顶栏").getAttribute("aria-pressed"), "true");
  assert.equal(await page.locator(".wb-top").evaluate(node => node.getBoundingClientRect().y), 0);
  assert.equal(await role("显示顶栏").count(), 0);
  pass("hover crosses into the full header, keyboard reveals it, and pinning keeps it at the top");

  await role("固定顶栏").click(); await page.mouse.move(740, 400); await settle();
  await page.mouse.move(740, 4); await settle();
  await page.locator(".wb-pill").first().click(); await page.mouse.move(750, 400); await settle();
  assert.equal(await collapsed(), false);
  assert.equal(await option("RP").getAttribute("aria-checked"), "true");
  assert.equal(await switcher().locator('[role="radio"] svg').count(), 3);
  assert.deepEqual(await switcher().locator('[role="radio"]').evaluateAll(ns => ns.map(n => n.tabIndex)), [-1, 0, -1]);
  await page.screenshot({ path:directory + "/rp-switcher.png" });
  await page.keyboard.press("Escape"); await settle(); assert.equal(await collapsed(), true); assert.equal(await page.locator(".wb-layout-switcher").evaluate(n => getComputedStyle(n).visibility), "hidden");
  pass("an open resource popover keeps the floating header visible; every mode has an icon and one tab stop");

  await page.evaluate(() => { window.__denyLayout = workbench.guards.add(() => false); });
  await page.mouse.move(740, 4); await settle(); await option("Noval").click(); await settle();
  assert.equal(await page.evaluate(() => workbench.host.prefs().layout), "rp");
  assert.equal(await option("RP").getAttribute("aria-checked"), "true");
  await page.evaluate(() => window.__denyLayout()); await settle();
  pass("an editor's unsaved-change guard can cancel a layout switch");

  await role("快进到你的回应").click(); await settle();
  await page.locator("#send_textarea").fill("WB_LAYOUT_DRAFT **Markdown**\n{{char}}");
  await choose("Noval");
  assert.equal(await page.locator(".wb-reading-bar").count(), 1);
  assert.equal(await page.locator('.wb-reading-bar .lucide-theater').count(), 0);
  assert.deepEqual(await switcher().locator('[role="radio"]').allInnerTexts(), ["Noval", "", ""]);
  assert.equal(await page.locator("#send_textarea").inputValue(), "WB_LAYOUT_DRAFT **Markdown**\n{{char}}");
  await option("Noval").focus();
  for (const [key, expected] of [["ArrowLeft", "native"], ["ArrowLeft", "rp"], ["ArrowLeft", "novel"], ["ArrowRight", "rp"], ["ArrowRight", "native"], ["ArrowRight", "novel"]]) {
    await page.keyboard.press(key);
    await page.waitForFunction(() => !document.querySelector('.wb-layout-controls[aria-busy="true"]')); await settle();
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-checked")), "true");
    assert.equal(await page.evaluate(() => workbench.mounted ? workbench.host.prefs().layout : "native"), expected);
    assert.equal(await page.locator("#send_textarea").inputValue(), "WB_LAYOUT_DRAFT **Markdown**\n{{char}}");
  }
  pass("only the current mode is labelled; arrow keys cycle modes, keep focus on the choice and preserve drafts");
  await ready(page, urls.validation, { probe:true }); await settle();
  assert.equal(await page.evaluate(() => workbench.host.prefs().layout), "novel");
  await page.screenshot({ path:directory + "/noval.png" });
  // Reload intentionally establishes a fresh set of native references.
  await page.evaluate(() => { window.__layoutNative = { chat:document.getElementById("chat"), input:document.getElementById("send_textarea"), form:document.getElementById("send_form") }; });
  await page.locator("#send_textarea").fill("WB_LAYOUT_NATIVE_DRAFT"); await choose("RP"); await choose("原生");
  assert.equal(await page.evaluate(() => workbench.mounted), false);
  assert.equal(await switcher().count(), 1);
  assert.equal(await page.locator("#send_textarea").inputValue(), "WB_LAYOUT_NATIVE_DRAFT");
  assert.equal(await page.evaluate(() => __layoutNative.chat === document.getElementById("chat") && __layoutNative.input === document.getElementById("send_textarea") && __layoutNative.form === document.getElementById("send_form") && !document.querySelector(".wb-rp-stage,.wb-rp-part")), true);
  await ready(page, urls.validation); await settle();
  assert.equal(await page.evaluate(() => workbench.mounted), false); await page.screenshot({ path:directory + "/native.png" });
  await choose("RP"); assert.equal(await page.locator(".wb-rp-stage").count(), 1);
  assert.equal(await page.locator(".wb-left.is-open,.wb-right.is-open").count(), 0);
  pass("Noval/RP/native switch through one persistent entry; drafts and native nodes survive and choices reload correctly");

  await page.evaluate(() => workbench.host.preference({ rpTopAuto:false })); await settle();
  for (const layout of ["rp", "novel"]) {
    if (layout === "novel") await choose("Noval");
    if (await page.locator('.wb-edge-left[aria-expanded=true]').count()) { await page.locator('.wb-edge-left').click(); await settle(); }
    for (const [width, height] of [[1024,768],[1100,800],[1366,768],[1496,817],[1920,1080],[2992,1634]]) {
      await page.setViewportSize({ width, height }); await settle();
      const rects = await page.evaluate(() => {
        const rect = selector => { const { left,right,top,bottom } = document.querySelector(selector).getBoundingClientRect(); return { left,right,top,bottom }; };
        return { width:innerWidth, contexts:rect(".wb-top-pills"), actions:rect(".wb-top-tools"), pin:rect(".wb-top-tools button:last-of-type"), trigger:rect(".wb-layout-controls"), eye:document.querySelector(".wb-rp-visibility") ? rect(".wb-rp-visibility") : null, overflow:document.documentElement.scrollWidth > innerWidth };
      });
      assert.equal(rects.overflow, false); assert.ok(rects.contexts.right <= rects.actions.left + 1, JSON.stringify(rects));
      assert.ok(rects.pin.right < rects.trigger.left, JSON.stringify(rects)); assert.ok(rects.trigger.right <= width, JSON.stringify(rects));
      if (rects.eye) assert.ok(rects.eye.top >= rects.actions.bottom + 12 && rects.eye.right <= width, JSON.stringify(rects));
      for (const state of ["closed", "left", "right", "closed-again"]) {
        if (state === "left") await page.locator(".wb-edge-left").click();
        if (state === "right") await toggleRight(page);
        if (state === "closed-again") {
          if (await page.locator('.wb-panel-close').isVisible()) { await toggleRight(page); await settle(); }
          if (await page.locator('.wb-edge-left[aria-expanded=true]').count()) await page.locator(".wb-edge-left").click();
        }
        await settle();
        const edges = await page.evaluate(() => {
          const rect = n => {const {left,right,top,bottom}=n.getBoundingClientRect();return {left,right,top,bottom};};
          const mode=rect(document.querySelector('.wb-layout-controls'));
          const handles=[...document.querySelectorAll('.wb-edge-arrow')].map(n=>({ ...rect(n),background:getComputedStyle(n).backgroundColor, hit:document.elementFromPoint(n.getBoundingClientRect().x+n.getBoundingClientRect().width/2,n.getBoundingClientRect().y+26)?.closest('button')===n }));
          return {mode,handles,overflow:document.documentElement.scrollWidth>innerWidth};
        });
        assert.equal(edges.overflow,false);for (const handle of edges.handles) {
          assert.equal(handle.background,"rgba(0, 0, 0, 0)"); assert.equal(handle.hit,true,JSON.stringify({layout,width,state,edges}));
          assert.ok(handle.top >= edges.mode.bottom + 12); assert.ok(handle.left >= 0 && handle.right <= width,JSON.stringify({layout,width,state,edges}));
        }
      }
    }
  }
  pass("six desktop widths in both layouts separate header controls and plain edge arrows, with panels open or closed");
  await page.setViewportSize({width:1496,height:817}); await settle();
  await page.locator('.wb-edge-left').click(); await page.waitForTimeout(70);
  const edgeMotion=await page.locator('.wb-edge-nav').evaluate(n=>n.getBoundingClientRect().left);
  assert.ok(edgeMotion>0&&edgeMotion<260,String(edgeMotion));
  assert.equal(await page.locator('.wb-edge-left').evaluate(n=>n.getAnimations().some(a=>a.playState==='running')),true);
  await settle(); await page.locator('.wb-edge-left').click(); await settle();
  await page.emulateMedia({reducedMotion:'reduce'}); await page.locator('.wb-edge-left').click();
  assert.equal(await page.locator('.wb-edge-nav').evaluate(n=>getComputedStyle(n).transitionDuration),'0s');
  await page.locator('.wb-edge-left').click(); await page.emulateMedia({reducedMotion:'no-preference'}); await settle();
  pass("plain edge controls retain click feedback and sliding animation, and respect reduced motion");
  await page.evaluate(async () => {
    const ctx=SillyTavern.getContext(); window.__layoutRealChat=structuredClone(ctx.chat);
    const long="夕阳穿过樱花，落在白芷手中的书页上。她抬起头，笑着走近。\n\n".repeat(30), short="夕阳穿过樱花，落在白芷手中的书页上。\n\n\"你来了。沿着这条小径走走吧，我有一件事想告诉你。\"";
    ctx.chat.splice(0,ctx.chat.length,{name:ctx.characters[ctx.characterId]?.name || "布局验证",is_user:false,is_system:false,send_date:"2026-10-09T10:57:00",mes:long,swipes:[long,short],swipe_id:0,extra:{}});
    const native = await import("/script.js"); window.__layoutSwipeReady = native.isSwipingAllowed; await native.printMessages();
  }); await settle();
  for (const width of [1024,1496,2992]) {
    await page.setViewportSize({width,height:817}); await settle();
    for (const inset of [24,128]) {
      await page.evaluate(inset=>workbench.host.preference({readingInset:inset,readingSize:24}),inset); await settle();
      await toggleRight(page); await settle();
      for (const variant of [1,0]) {
        await page.waitForFunction(() => window.__layoutSwipeReady());
        await page.locator(`#chat .last_mes .swipe_${variant===1?"right":"left"}`).click();
        try { await page.waitForFunction(variant=>SillyTavern.getContext().chat.at(-1).swipe_id===variant,variant,{timeout:10000}); }
        catch (error) {
          console.log('Swipe diagnostic', {width,inset,variant},await page.evaluate(async()=>({allowed:(await import('/script.js')).isSwipingAllowed(),id:SillyTavern.getContext().chat.at(-1).swipe_id,toast:document.querySelector('#toast-container')?.textContent})));
          await page.screenshot({path:directory+'/swipe-failure.png'});throw error;
        }
        await page.waitForFunction(() => window.__layoutSwipeReady()); await settle();
        const gutters = await page.evaluate(() => {
          const mes=document.querySelector('#chat .last_mes');
          const rect = n => {const {left,right,top,bottom}=n.getBoundingClientRect();return {left,right,top,bottom};};
          return {text:rect(mes.querySelector('.mes_text')),left:rect(mes.querySelector('.swipe_left')),right:rect(mes.querySelector('.swipe_right')),counter:rect(mes.querySelector('.swipes-counter')),padding:Number.parseFloat(getComputedStyle(mes).paddingBottom)};
        });
        assert.ok(gutters.left.right <= gutters.text.left - 7,JSON.stringify({width,inset,variant,gutters}));
        assert.ok(gutters.right.left >= gutters.text.right + 7,JSON.stringify({width,inset,variant,gutters}));
        assert.ok(gutters.counter.left >= gutters.text.right + 7,JSON.stringify({width,inset,variant,gutters}));
        assert.ok(gutters.left.top < gutters.text.bottom && gutters.right.top < gutters.text.bottom,JSON.stringify({width,inset,variant,gutters}));
        assert.ok(gutters.padding <= 25.5,JSON.stringify({width,inset,variant,gutters}));
      }
      await toggleRight(page); await settle();
    }
  }
  pass("native swipe controls stay in side gutters beside short/long text with no extra bottom row; original swipe handlers work at both inset limits");
  await page.evaluate(async () => {
    const ctx=SillyTavern.getContext();ctx.chat.splice(0,ctx.chat.length,...__layoutRealChat);delete window.__layoutRealChat;delete window.__layoutSwipeReady;
    await (await import('/script.js')).printMessages();workbench.host.preference({readingInset:64,readingSize:17});
  }); await page.setViewportSize({width:1496,height:817}); await settle(); await page.screenshot({path:directory+'/noval-edges-gutters.png'});
  await choose("RP");
  await page.evaluate(async () => {
    const ctx=SillyTavern.getContext();window.__layoutRealChat=structuredClone(ctx.chat);
    const mes=Array.from({length:5},(_,i)=>`第 ${i+1} 段。`+"樱花落在书页上，她停下脚步，静静听你讲述这一路遇到的故事。".repeat(7)).join('\n\n');
    ctx.chat.splice(0,ctx.chat.length,{name:ctx.characters[ctx.characterId]?.name || '布局验证',is_user:false,is_system:false,send_date:'2026-10-09T10:57:00',mes,extra:{}});
    await (await import('/script.js')).printMessages();
  }); await settle();
  assert.ok(await page.locator('.wb-rp-dots>button').count()>1);
  const dotLabel=await page.locator('.wb-rp-dots>button').first().getAttribute('aria-label');
  await role(dotLabel).click(); await page.waitForTimeout(70);
  assert.equal(await role(dotLabel).evaluate(n=>n.getAnimations().some(a=>a.playState==='running')),true); await settle();
  assert.equal(await role(dotLabel).getAttribute('aria-current'),'true');
  for(const width of [1024,1496,2992]) {
    await page.setViewportSize({width,height:817});await settle();
    const dots=await page.locator('.wb-rp-dots>button').evaluateAll(nodes=>nodes.map(n=>{
      const dot=getComputedStyle(n,'::before'),matrix=new DOMMatrixReadOnly(dot.transform==='none'?undefined:dot.transform),rect=n.getBoundingClientRect(),caption=n.closest('.wb-rp-foot').getBoundingClientRect();
      return {current:n.getAttribute('aria-current')==='true',width:Number.parseFloat(dot.width)*matrix.a,height:Number.parseFloat(dot.height)*matrix.d,radius:dot.borderRadius,background:getComputedStyle(n).backgroundColor,hitWidth:rect.width,hitHeight:rect.height,inside:rect.left>=caption.left&&rect.right<=caption.right};
    }));
    for(const dot of dots){if(dot.current)assert.ok(dot.width>dot.height*2,JSON.stringify(dot));else{assert.ok(Math.abs(dot.width-dot.height)<.01,JSON.stringify(dot));assert.equal(dot.radius,'50%');}assert.equal(dot.background,'rgba(0, 0, 0, 0)');assert.ok(dot.hitWidth>=15.9&&dot.hitHeight>=23.9);assert.equal(dot.inside,true);}
  }
  await page.setViewportSize({width:1496,height:817});await settle();await page.screenshot({path:directory+'/rp-round-dots.png'});
  pass("RP pagination markers are circles with the current page drawn as a pill, in 16×24px hit areas beside full-size previous/next keys; selecting a dot changes the page and retains click animation");
  await page.evaluate(async () => {const ctx=SillyTavern.getContext();ctx.chat.splice(0,ctx.chat.length,...__layoutRealChat);delete window.__layoutRealChat;await (await import('/script.js')).printMessages();});await settle();
  await role("RP 外观").click();
  const checkbox = page.getByRole("checkbox", {name:"鼠标悬浮显示顶栏",exact:true});
  await checkbox.check(); await page.keyboard.press("Escape"); await page.mouse.move(750,400); await settle();
  assert.equal(await collapsed(), true);
  const floating = await page.evaluate(()=>[...document.querySelectorAll('.wb-edge-arrow')].map(n=>({arrowBottom:n.getBoundingClientRect().bottom,modeBottom:document.querySelector('.wb-layout-controls').getBoundingClientRect().bottom,arrowTop:n.getBoundingClientRect().top})));
  for(const item of floating) assert.ok(item.arrowTop>item.modeBottom+12);
  await page.screenshot({path:directory+'/rp-edges-floating.png'});
  await page.mouse.move(740,4); await settle(); assert.equal(await role("固定顶栏").getAttribute("aria-pressed"), "false");
  await role("固定顶栏").click(); await page.mouse.move(750,400); await settle();
  await role("隐藏界面").click(); await settle(); assert.equal(await switcher().isVisible(), true);
  await role("显示界面").click(); await settle();
  pass("appearance checkbox agrees with pin state and the mode entry remains usable when chrome is hidden");
  assert.deepEqual(errors, []);
  fs.writeFileSync(directory + "/verification.json", JSON.stringify({ url:urls.validation, checks, errors }, null, 2));
} finally { await browser.close(); }
