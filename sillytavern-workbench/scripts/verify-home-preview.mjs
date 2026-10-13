import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
const directory=resolve('artifacts/noval-rework');
await mkdir(directory,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.WB_CHROMIUM||'/home/yuwk/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox','--disable-dev-shm-usage','--no-proxy-server']});
const errors=[],results=[];
try{
const page=await browser.newPage({viewport:{width:1440,height:900}});
page.on('pageerror',e=>errors.push(String(e)));
await page.goto('file://'+resolve('docs/design/novel-desktop/rework/preview.html'));
const frame=page.frames().find(f=>f.parentFrame());
await frame.waitForSelector('#noval-rework');
const root=frame.locator('#noval-rework');
const settle=()=>page.waitForTimeout(260);
if(await root.getAttribute('data-right')==='true'){await frame.getByRole('button',{name:'收起右栏',exact:true}).click();await settle();}
const checkToolbar=async()=>{
 const m=await frame.locator('.nv-tools').evaluate(el=>{
  const rect=x=>x.getBoundingClientRect();const send=el.querySelector('[data-action=send]'),actions=el.querySelector('.nv-tool-actions'),r=rect(el),s=rect(send),a=rect(actions);
  const buttons=[...actions.querySelectorAll('button')].map(rect);
  return {sendCenter:s.y+s.height/2,actionCenter:a.y+a.height/2,rightGap:r.right-s.right,overlap:a.right>s.left,buttonsInside:buttons.every(b=>b.left>=a.left-.5&&b.right<=a.right+.5),sendText:send.textContent.trim(),sendIcons:send.querySelectorAll('svg,i').length};
 });
 assert.ok(Math.abs(m.sendCenter-m.actionCenter)<1);assert.ok(Math.abs(m.rightGap)<1,JSON.stringify({viewport:page.viewportSize(),...m}));assert.equal(m.overlap,false);assert.equal(m.buttonsInside,true);assert.equal(m.sendText,'');assert.equal(m.sendIcons,1);
};
for(const [width,height] of [[1366,768],[1440,900],[1920,1080]]){
 await page.setViewportSize({width,height});await settle();assert.ok(Math.abs((await root.boundingBox()).height-height)<1);await checkToolbar();
 const metrics=await root.evaluate(el=>{const r=s=>el.querySelector(s).getBoundingClientRect();const h=r('.nv-header'),p=r('.nv-pickers'),l=r('.nv-left'),main=r('.nv-main'),compose=r('.nv-compose-wrap');return {width:el.clientWidth,overflow:el.scrollWidth>el.clientWidth,pickerCenter:Math.abs(p.x+p.width/2-(h.x+h.width/2)),left:l.width,main:main.width,compose:compose.height,textarea:el.querySelector('.nv-draft').getBoundingClientRect().height,floors:el.querySelectorAll('.nv-floor').length,settings:el.querySelectorAll('.nv-settings button').length};});
 assert.equal(metrics.overflow,false);assert.ok(metrics.pickerCenter<1);assert.equal(metrics.floors,5);assert.equal(metrics.settings,9);assert.ok(metrics.textarea>30);
 results.push({name:'layout '+width,passed:true,metrics});
 await page.mouse.move(0,0);await page.screenshot({path:directory+'/home-'+width+'.png'});
 await frame.getByRole('button',{name:'展开右栏',exact:true}).click();await settle();
 await checkToolbar();const w=await frame.locator('.nv-main').evaluate(el=>el.getBoundingClientRect().width);assert.ok(w>=640);assert.equal(await frame.locator('.nv-panel-tabs button').count(),6);
 await page.mouse.move(0,0);await page.screenshot({path:directory+'/roles-'+width+'.png'});
 await frame.getByRole('button',{name:'收起右栏',exact:true}).click();await settle();
}
await page.setViewportSize({width:1440,height:900});await settle();
await frame.getByRole('button',{name:'展开右栏',exact:true}).click();await settle();
await frame.getByRole('button',{name:'专注模式',exact:true}).click();await settle();
assert.equal(await root.getAttribute('data-focus'),'true');assert.equal(await frame.locator('.nv-header').evaluate(el=>el.inert),true);
await page.mouse.move(0,0);await page.screenshot({path:directory+'/focus-1440.png'});
await frame.getByRole('button',{name:'退出专注',exact:true}).click();await settle();
assert.equal(await root.getAttribute('data-right'),'true');assert.equal(await root.getAttribute('data-left'),'true');
await frame.getByRole('button',{name:'收起右栏',exact:true}).click();await settle();
results.push({name:'focus restores both panels',passed:true});
const draft=frame.getByRole('textbox',{name:'消息输入',exact:true});await draft.fill('## 待续\n\n“那封信，你还没有拆开吗？”\n<scene>{{char}}</scene>');
const grip=frame.getByRole('slider');const oldHeight=await draft.evaluate(el=>el.clientHeight);const box=await grip.boundingBox();
await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2,box.y-180,{steps:12});await page.mouse.up();
assert.ok((await draft.evaluate(el=>el.clientHeight))>oldHeight+120);assert.match(await draft.inputValue(),/<scene>/);
await page.mouse.move(0,0);await page.screenshot({path:directory+'/composer-expanded-1440.png'});
await grip.press('End');assert.equal(await grip.getAttribute('aria-valuenow'),'60');await grip.press('Home');assert.equal(await grip.getAttribute('aria-valuenow'),'20');
results.push({name:'composer drag + keyboard preserves source',passed:true});
await frame.getByRole('button',{name:'快速回复',exact:true}).click();await frame.getByRole('button',{name:'放慢节奏',exact:true}).click();assert.match(await draft.inputValue(),/放慢节奏/);assert.equal(await frame.locator('[data-pop]').isVisible(),false);
await frame.getByRole('button',{name:'展开全部',exact:true}).click();assert.equal(await frame.locator('.nv-floor').count(),12);await frame.getByRole('button',{name:'收起至五条',exact:true}).click();assert.equal(await frame.locator('.nv-floor').count(),5);
await frame.getByRole('button',{name:'选择连接',exact:true}).click();await frame.getByRole('button',{name:'使用Claude Sonnet',exact:true}).click();assert.equal(await frame.locator('[data-value=connection]').textContent(),'Claude Sonnet');
await frame.getByRole('button',{name:'下一个连接',exact:true}).click();assert.match(await frame.locator('[data-value=connection]').textContent(),/Qwen/);
await frame.getByRole('button',{name:'编辑预设',exact:true}).click();assert.equal(await frame.locator('[data-panel=preset][role=tab]').getAttribute('aria-selected'),'true');
await frame.getByRole('tab',{name:'角色',exact:true}).click();await frame.getByRole('textbox',{name:'搜索角色',exact:true}).fill('夏禾');assert.equal(await frame.locator('.nv-role-row').count(),1);
await frame.getByRole('textbox',{name:'搜索角色',exact:true}).fill('');
await frame.getByRole('tab',{name:'世界书',exact:true}).click();await page.mouse.move(0,0);await page.screenshot({path:directory+'/world-sidebar-1440.png'});
await frame.getByRole('button',{name:'激活方式：关键词',exact:true}).first().click();await frame.locator('[data-pop]').getByRole('button',{name:'常驻',exact:true}).click();assert.equal(await frame.getByRole('button',{name:'激活方式：常驻',exact:true}).count(),2);
results.push({name:'quick replies, floor toggle, selectors, icon detail, search and world mode',passed:true});
await frame.locator('[data-toast]').waitFor({state:'hidden'});
await page.setViewportSize({width:1100,height:800});await settle();assert.equal(await root.getAttribute('data-left'),'false');assert.equal(await root.getAttribute('data-right'),'true');await frame.getByRole('button',{name:'收起右栏',exact:true}).click();await settle();assert.equal(await root.getAttribute('data-left'),'true');
results.push({name:'narrow desktop auto collapses left and restores',passed:true});
for(const width of [1024,736,375,320]){await page.setViewportSize({width,height:820});await settle();await checkToolbar();assert.equal(await root.evaluate(el=>el.scrollWidth>el.clientWidth),false);await page.mouse.move(0,0);await page.screenshot({path:directory+'/inline-'+width+'.png'});}
await page.setViewportSize({width:1024,height:820});await settle();
await frame.getByRole('button',{name:'展开右栏',exact:true}).click();await settle();await checkToolbar();
await page.mouse.move(0,0);await page.screenshot({path:directory+'/narrow-composer-1024.png'});
const inheritedTheme=await frame.addStyleTag({content:'svg.lucide, svg.lucide *{color:white!important;stroke:white!important;fill:white!important}'});
const contrast=await frame.locator('.nv-resource-icon svg').first().evaluate(el=>({color:getComputedStyle(el).color,stroke:getComputedStyle(el).stroke,fill:getComputedStyle(el).fill}));
assert.equal(contrast.color,'rgb(108, 98, 84)');assert.equal(contrast.stroke,'rgb(108, 98, 84)');assert.equal(contrast.fill,'none');
await inheritedTheme.evaluate(el=>el.remove());
await frame.getByRole('button',{name:'选择用户设定',exact:true}).click();
await frame.locator('.nv-pop-row.selected .nv-pop-main').hover();await page.waitForTimeout(200);
assert.equal(await frame.locator('.nv-pop-row.selected .nv-pop-main').evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');
await page.screenshot({path:directory+'/selector-hover.png'});
await frame.locator('[data-picker=persona]').press('Escape');
results.push({name:'toolbar alignment, icon-only send, icon contrast under inherited light strokes, soft whole-row hover',passed:true});
await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await frame.locator('.nv-body').evaluate(el=>getComputedStyle(el).transitionDuration),'0s');
results.push({name:'inline sizes + reduced motion',passed:true});assert.deepEqual(errors,[]);
await writeFile(directory+'/verification.json',JSON.stringify({passed:true,scope:'local visual preview; no host integration or user visual approval',results,errors},null,2));
console.log(JSON.stringify({passed:true,checks:results.length,errors},null,2));
}catch(e){console.error(e);process.exitCode=1;}finally{await browser.close();}
