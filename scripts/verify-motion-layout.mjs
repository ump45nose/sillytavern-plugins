import assert from 'node:assert/strict';
import fs from 'node:fs';
import { launch, session, ready, urls, createCharacter, withReducedMotion, openSettings } from './browser.mjs';

const dir='artifacts/motion-layout';fs.mkdirSync(dir,{recursive:true});
const checks=[],pass=(name,details)=>{checks.push({name,passed:true,details});console.log('PASS',name,JSON.stringify(details??{}));};
const browser=await launch();let page,errors=[],passed=false;
try {
 ({page,errors}=await session(browser));await page.setViewportSize({width:1496,height:817});await ready(page,urls.validation,{probe:true});await createCharacter(page);
 const settle=()=>page.waitForTimeout(330),ws=()=>page.getByRole('dialog',{name:'独立设置工作区',exact:true});
 const open=async name=>{await openSettings(page,name);await ws().waitFor();await settle();};
 const close=async()=>{await page.getByRole('button',{name:'返回工作台',exact:true}).click();await page.locator('.wb-settings-workspace').waitFor({state:'detached'});};
 const preference=()=>page.evaluate(()=>({setting:SillyTavern.getContext().powerUserSettings.reduced_motion,body:document.body.classList.contains('reduced-motion')}));
 assert.deepEqual(await preference(),{setting:false,body:false},'normal-motion verification requires the native preference enabled');
 await page.evaluate(()=>workbench.host.preference({left:true,userCollapsed:true}));await settle();
 if(!await page.locator('#chat .mes[is_user=true]').count())await page.evaluate(()=>TavernHelper.createChatMessages([{role:'user',message:'WB_MOTION 我推开窗，朝港口望去。'}]));await settle();
 const user=page.locator('#chat .mes[is_user=true]').last();
 await user.evaluate(n=>{window.__motionMessage=n;window.__motionText=n.querySelector('.mes_text');const f=document.createElement('iframe');f.srcdoc='<p>保留原始阅读内容</p>';f.height='80';__motionText.append(f);window.__motionFrame=f;window.__motionWindow=f.contentWindow;});
 const frames=await user.evaluate(async n=>{
  const body=n.querySelector('.mes_text'),button=n.querySelector('.wb-user-heading button');
  const sample=()=>{const r=n.getBoundingClientRect(),label=n.querySelector('.wb-user-heading span').getBoundingClientRect(),meta=n.querySelector('.ch_name').getBoundingClientRect(),heading=n.querySelector('.wb-user-heading').getBoundingClientRect(),p=body.querySelector('p')?.getBoundingClientRect(),s=getComputedStyle(body);return {height:body.getBoundingClientRect().height,opacity:Number(s.opacity),labelX:label.x-r.x,labelY:label.y-r.y,metaY:meta.y+meta.height/2-r.y,headingY:heading.y+heading.height/2-r.y,bodyX:p?.x-r.x,animations:body.getAnimations().length};};
  const before=sample();button.click();const samples=[];const start=performance.now();let animation;
  while(performance.now()-start<330){await new Promise(requestAnimationFrame);const elapsed=performance.now()-start;if(elapsed>40&&!animation){animation=body.getAnimations()[0];n.setAttribute('mesid',n.getAttribute('mesid'));}samples.push({elapsed,...sample(),sameAnimation:!animation||body.getAnimations().includes(animation)});}
  return {before,samples,after:sample()};
 });
 assert(frames.samples.some(x=>x.height>1&&x.height<frames.after.height-1&&x.opacity>0&&x.opacity<1),'height and opacity must actually interpolate');
 assert(frames.samples.filter(x=>x.elapsed<180&&x.elapsed>70).every(x=>x.sameAnimation),'host scans must not cancel an in-progress fold');
 assert(frames.samples.every(x=>Math.abs(x.labelY-frames.before.labelY)<1&&Math.abs(x.labelX-frames.before.labelX)<1),'heading must stay in place throughout expansion');
 assert(frames.samples.every(x=>Math.abs(x.metaY-x.headingY)<1),'metadata and title must share a fixed vertical baseline');
 assert(Math.abs(frames.after.bodyX-frames.after.labelX)<1,'paragraph must align with heading text');
 assert.equal(frames.after.animations,0);pass('actual input animation frames, fixed heading and paragraph alignment',frames);
 await page.screenshot({path:dir+'/reading-expanded-1496.png'});
 const button=user.locator('.wb-user-heading button');for(let i=0;i<6;i++){await button.click();await page.waitForTimeout(30);}await settle();
 assert(await user.evaluate(n=>n.querySelector('.mes_text')===__motionText&&__motionText.contains(__motionFrame)&&__motionFrame.contentWindow===__motionWindow));pass('rapid reversals preserve original text and iframe browsing context');
 await withReducedMotion(page,async()=>{await button.click();assert.equal(await user.locator('.mes_text').evaluate(n=>n.getAnimations().length),0);await button.click();});
 assert.deepEqual(await preference(),{setting:false,body:false});
 await assert.rejects(withReducedMotion(page,async()=>{throw new Error('test restoration');}),/test restoration/);assert.deepEqual(await preference(),{setting:false,body:false});
 await user.evaluate(()=>__motionFrame.remove());await user.hover();await settle();await page.screenshot({path:dir+'/reading-expanded-1496.png'});pass('reduced-motion checks restore the native preference, including failed checks');
 await button.click();await settle();assert.equal(await user.locator('.wb-user-heading small').evaluate(n=>getComputedStyle(n).opacity),'0');await button.click();await settle();pass('collapsed preview yields to hover metadata without overlapping text');
 const outline=page.locator('#wb-nav-floors');await outline.locator('.wb-nav-toggle').click();await settle();
 const folding=await outline.evaluate(async n=>{const b=n.querySelector('button'),body=n.querySelector('.wb-fold-body');const start=body.getBoundingClientRect().height;b.click();await new Promise(r=>setTimeout(r,60));const mid=body.getBoundingClientRect().height,animations=body.getAnimations().length;await new Promise(r=>setTimeout(r,250));const end=body.getBoundingClientRect().height,s=getComputedStyle(b);return {start,mid,end,animations,caret:getComputedStyle(b.querySelector('.wb-nav-caret')).transform};});
 assert(folding.mid>folding.start&&folding.mid<folding.end);assert(folding.animations>0);assert.equal(folding.caret,'none');await page.screenshot({path:dir+'/home-selection-1496.png'});pass('nav sections fold with animation and an upright caret when open',folding);
 await open('回复格式');
 const chrome=await ws().evaluate(n=>({header:n.querySelector('.wb-settings-header').getBoundingClientRect().height,tabs:n.querySelector('.wb-settings-subnav').getBoundingClientRect().height,repeatedHeading:n.querySelectorAll('.wb-component-settings>.wb-designed-page-head').length,firstControl:n.querySelector('#ContextSettings .wb-select-trigger').getBoundingClientRect().y}));
 assert.equal(chrome.header,56);assert.equal(chrome.tabs,48);assert.equal(chrome.repeatedHeading,0);assert(chrome.firstControl<180);await page.screenshot({path:dir+'/formatting-1496.png'});
 const select=ws().locator('#ContextSettings .wb-select-trigger').first();await select.click();assert(await page.getByRole('listbox').evaluate(n=>n.getAnimations().length>0));await page.keyboard.press('Escape');
 const action=ws().locator('#ContextSettings [data-preset-manager-update]').first();await page.mouse.move(0,0);await settle();const actionBefore=await action.evaluate(n=>getComputedStyle(n).backgroundColor);await action.hover();await page.waitForTimeout(40);const actionMid=await action.evaluate(n=>({color:getComputedStyle(n).backgroundColor,animations:n.getAnimations().length}));await settle();const actionAfter=await action.evaluate(n=>getComputedStyle(n).backgroundColor);assert(actionMid.animations>0&&actionMid.color!==actionBefore&&actionMid.color!==actionAfter);
 pass('compact chrome, animated select popup and native icon hover',chrome);await close();
 await open('用户设置');
 const checkbox=ws().locator('#click_to_edit');await checkbox.scrollIntoViewIfNeeded();
 const checkMotion=await checkbox.evaluate(async n=>{const before=getComputedStyle(n).backgroundColor,original=n.checked;n.click();await new Promise(r=>setTimeout(r,50));const mid=getComputedStyle(n).backgroundColor,animations=n.getAnimations().length;await new Promise(r=>setTimeout(r,220));const after=getComputedStyle(n).backgroundColor,native=SillyTavern.getContext().powerUserSettings.click_to_edit;n.click();return {before,mid,after,animations,native,original};});
 assert(checkMotion.animations>0&&checkMotion.mid!==checkMotion.before&&checkMotion.mid!==checkMotion.after);assert.equal(checkMotion.native,!checkMotion.original);await settle();assert.equal(await checkbox.isChecked(),checkMotion.original);pass('native checkbox animates and preserves its actual input handler',checkMotion);await close();
 await open('背景');
 const bgNodes=await page.locator('#Backgrounds').evaluate(n=>{window.__motionBackground=n;window.__motionTabs=n.querySelector('#bg_tabs');return {sameRoot:!!jQuery(__motionTabs).data('ui-tabs')};});assert(bgNodes.sameRoot);
 for(const [width,height] of [[1366,768],[1440,900],[1496,817],[1920,1080]]){
  await page.setViewportSize({width,height});await settle();
  const row=await ws().evaluate(n=>{const ids=['background_fitting','auto_background','bg_add_folder_button','add_background_button_top','bg-filter','bg-sort'];const elements=[...ids.map(id=>n.querySelector('#'+id)),...n.querySelectorAll('#bg_tabs .bg_tab_button'),n.querySelector('#bg_tabs .heading-controls')];return {controls:elements.map(x=>{const r=x.getBoundingClientRect();return {id:x.id||x.className,x:r.x,y:r.y+r.height/2,width:r.width};}),scroll:document.documentElement.scrollWidth,bodyScroll:n.querySelector('.wb-settings-body').scrollWidth,bodyWidth:n.querySelector('.wb-settings-body').clientWidth};});
  assert.equal(row.scroll,width);assert(row.bodyScroll<=row.bodyWidth+1);const ys=row.controls.map(x=>x.y);assert(Math.max(...ys)-Math.min(...ys)<2,'background toolbar must be one row at '+width);await page.screenshot({path:`${dir}/background-${width}.png`});pass('one native background toolbar at '+width,row);
 }
 await page.setViewportSize({width:1496,height:817});await page.locator('#bg_tabs .bg_tab_button').nth(1).locator('a').click();assert.equal(await page.evaluate(()=>jQuery('#bg_tabs').tabs('option','active')),1);assert(await page.locator('#bg_chat_tab').isVisible());await page.locator('#bg_tabs .bg_tab_button').first().locator('a').click();assert.equal(await page.evaluate(()=>jQuery('#bg_tabs').tabs('option','active')),0);assert(await page.locator('#bg_global_tab').isVisible());
 assert(await page.evaluate(()=>__motionBackground===document.getElementById('Backgrounds')&&__motionTabs===document.getElementById('bg_tabs')));
 const sample=page.locator('#bg_menu_content .bg_example').first(),before=(await sample.boundingBox()).width;await page.locator('#bg_thumb_zoom_in').click();await settle();assert((await sample.boundingBox()).width>before);await page.locator('#bg_thumb_zoom_out').click();await settle();assert.equal((await sample.boundingBox()).width,before);pass('native background tab ownership and thumbnail zoom');await close();
 await page.reload();await page.waitForFunction(()=>document.body.classList.contains('wb-active'));assert.deepEqual(await preference(),{setting:false,body:false});assert.deepEqual(errors,[]);pass('native motion remains enabled after reload; no browser errors');passed=true;
}catch(error){if(page)await page.screenshot({path:dir+'/failure.png'});throw error;}finally{fs.writeFileSync(dir+'/verification.json',JSON.stringify({checkedAt:new Date().toISOString(),passed,checks,errors},null,2));await browser.close();}
