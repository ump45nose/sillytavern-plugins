import assert from 'node:assert/strict';
import fs from 'node:fs';
import { launch, session, ready, urls, createCharacter, connect, withReducedMotion } from './browser.mjs';
const dir = 'artifacts/home-implementation'; fs.mkdirSync(dir,{recursive:true});
const checks=[], pass=(name, details={})=>{checks.push({name,details,passed:true});console.log('PASS',name);};
const b=await launch();
try {
 const {page,errors}=await session(b);
 await ready(page,urls.validation,{probe:true}); await createCharacter(page); await connect(page);
 await page.evaluate(()=>{ workbench.host.preference({left:true,inputRatio:.2}); });
 // Remount to load persisted layout preferences without mutating the user's messages.
 await page.evaluate(async()=>{workbench.unmount();await workbench.mount();});
 const settle=()=>page.waitForTimeout(300);
 await settle();
 assert.equal(await page.locator('.wb-left-bottom button').count(),9);
 assert.equal(await page.locator('.wb-panel-tabs button').count(),6);
 assert.equal(await page.locator('.wb-floor-list > button').count(),Math.min(5,await page.evaluate(()=>workbench.host.snapshot().messages.length)));
 assert.equal(await page.locator('.wb-chat-name').textContent(),await page.evaluate(()=>String(SillyTavern.getContext().chatId).replace(/\.jsonl$/,'')));
 assert.equal(await page.locator('.wb-outline-placeholder').count(),1);
 pass('real chat name, recent five floors, outline placeholder and complete navigation');
 const geometry=async()=>page.evaluate(()=>{
  const r=s=>{const b=document.querySelector(s).getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height,right:b.right,bottom:b.bottom};};
  const actions=[...document.querySelectorAll('.wb-composer-actions button')].map(x=>x.getBoundingClientRect());
  return {viewport:innerWidth,header:r('.wb-contexts'),main:r('#sheld'),input:r('#send_textarea'),form:r('#send_form'),send:r('#send_but'),tools:r('.wb-composer-actions'),left:r('#leftSendForm'),right:r('#rightSendForm'),chat:r('#chat'),scroll:document.documentElement.scrollWidth,actionsInside:actions.every(a=>a.x>=r('.wb-composer-actions').x-1&&a.right<=r('.wb-composer-actions').right+1)};
 });
 const verifyGeometry=async()=>{
  const g=await geometry(); assert.equal(g.scroll,g.viewport);
  assert((await page.locator(".wb-focus-toggle").boundingBox()).height<=44);assert(Math.abs(g.header.x+g.header.w/2-g.viewport/2)<1);
  assert(g.tools.x>=g.left.right-1);assert(g.tools.right<=g.right.x+1);assert(g.actionsInside,JSON.stringify(g));
  assert(g.tools.y>=g.input.bottom-1);assert(g.send.bottom<=page.viewportSize().height);assert(Math.abs(g.send.y+g.send.h/2-(g.tools.y+g.tools.h/2))<1);
  assert(g.chat.bottom<=g.form.y+1);assert.equal(g.send.w,40);
  const handle=await page.getByRole("separator",{name:"调整输入框高度"}).boundingBox();assert(handle.y-g.form.y<5);return g;
 };
 for(const [width,height] of [[1366,768],[1440,900],[1496,817],[1920,1080]]){
  await page.setViewportSize({width,height});await settle();let g=await verifyGeometry();
  await page.screenshot({path:`${dir}/home-${width}.png`});
  await page.getByRole('button',{name:'角色与资源侧栏',exact:true}).click();await settle();g=await verifyGeometry();assert.equal(g.main.w,width-(width<=1400?240:260)-(width<=1400?440:460)-180);
  await page.screenshot({path:`${dir}/roles-${width}.png`});
  await page.getByRole('button',{name:'关闭右栏',exact:true}).click();await settle();pass('desktop geometry '+width,g);
 }
 for(const width of [1024,1100]) {
  await page.setViewportSize({width,height:820});await settle();
  await page.getByRole('button',{name:'角色与资源侧栏',exact:true}).click();await settle();await verifyGeometry();
  await page.screenshot({path:`${dir}/narrow-${width}.png`});
  await page.getByRole('button',{name:'关闭右栏',exact:true}).click();await settle();
 }
 pass('minimum desktop widths keep menu, tools and send aligned');
 await page.setViewportSize({width:1200,height:820});await settle();
 await page.getByRole('button',{name:'角色与资源侧栏',exact:true}).click();await settle();
 assert.equal(await page.evaluate(()=>document.body.classList.contains('wb-left-open')),false);await verifyGeometry();
 await page.keyboard.press('Alt+Shift+F');await settle();assert.equal(await page.evaluate(()=>document.body.classList.contains('wb-focus')),true);
 await page.screenshot({path:`${dir}/focus.png`});
 await page.getByRole('button',{name:'退出专注',exact:true}).click();await settle();
 assert.equal(await page.locator('.wb-panel-tabs button.is-active').textContent(),'角色');
 await page.getByRole('button',{name:'关闭右栏',exact:true}).click();await settle();
 assert.equal(await page.evaluate(()=>document.body.classList.contains('wb-left-open')),true);
 pass('auto collapse and restore; focus restores prior resource and layout');
 await page.setViewportSize({width:1440,height:900});await settle();
 const input=page.locator('#send_textarea'), draft='**原文草稿**\n<story>{{char}}</story>';await input.fill(draft);
 const grip=page.getByRole('separator',{name:'调整输入框高度'}), pos=await grip.boundingBox(), before=await input.boundingBox();
 await page.mouse.move(pos.x+pos.width/2,pos.y+pos.height/2);await page.mouse.down();await page.mouse.move(pos.x+pos.width/2,pos.y-190,{steps:12});await page.mouse.up();
 assert((await input.boundingBox()).height>before.height+150);assert.equal(await input.inputValue(),draft);await verifyGeometry();
 await page.screenshot({path:`${dir}/composer-expanded.png`});
 await grip.press('End');assert.equal(await grip.getAttribute('aria-valuenow'),'60');await grip.press('Home');assert.equal(await grip.getAttribute('aria-valuenow'),'20');
 pass('pointer and keyboard resize 20–60%; native raw draft preserved');
 await page.getByRole('button',{name:'预设详情',exact:true}).click();await settle();
 assert.equal(await page.locator('.wb-panel-tabs button.is-active').textContent(),'预设');
 const selector=page.locator('.wb-selector').nth(1);assert.match(await selector.getAttribute('class'),/is-active/);
 await selector.locator('.wb-selector-value').click();await page.locator('.wb-popover').waitFor();
 const motion=await page.locator('.wb-popover').evaluate(e=>getComputedStyle(e).animationName);assert.equal(motion,'wb-menu');
 await page.screenshot({path:`${dir}/selector.png`});await page.keyboard.press('Escape');
 const color=await page.locator('.wb-selector-detail svg').first().evaluate(e=>getComputedStyle(e).color);assert.equal(color,'rgb(108, 98, 84)');
 pass('detail targets, active selector, menu animation and warm icon contrast');
 await withReducedMotion(page,async()=>assert.equal(await selector.evaluate(e=>getComputedStyle(e).transitionDuration),'0s'));pass('reduced motion honored and preference restored');
 assert.deepEqual(errors,[]);fs.writeFileSync(`${dir}/verification.json`,JSON.stringify({checks,errors},null,2));
} catch(e){console.error(e);process.exitCode=1;} finally {await b.close();}
