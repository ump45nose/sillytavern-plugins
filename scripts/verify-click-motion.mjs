import assert from 'node:assert/strict';
import fs from 'node:fs';
import {launch,session,ready,urls,createCharacter,withReducedMotion,openResource,openSettings,fieldValue} from './browser.mjs';

const dir='artifacts/click-motion';fs.mkdirSync(dir,{recursive:true});
const checks=[],pass=(name,details)=>{checks.push({name,passed:true,details});console.log('PASS',name);};
const browser=await launch();let page,context,errors=[],passed=false,videoPath,videoStart;
try{
 const started=Date.now();({page,context,errors}=await session(browser,{recordVideo:{dir,size:{width:1496,height:817}}}));
 await page.setViewportSize({width:1496,height:817});await ready(page,urls.validation,{probe:true});await createCharacter(page);
 await page.evaluate(()=>workbench.host.preference({left:true,userCollapsed:true}));assert(!await page.evaluate(()=>SillyTavern.getContext().powerUserSettings.reduced_motion));
 videoStart=(Date.now()-started)/1000;
 const settle=()=>page.waitForTimeout(350);
 let capture=0;
 const sample=async(button,target)=>{
  const key='__clickMotion'+(++capture);
  await button.evaluate((n,{target,key})=>{
   const old=document.querySelector(target);
   const read=()=>{const node=document.querySelector(target)||old;if(!node?.isConnected)return {present:false,height:0,opacity:0,scale:1};const r=node.getBoundingClientRect(),s=getComputedStyle(node),message=node.closest('.mes')?.getBoundingClientRect(),heading=node.closest('.mes')?.querySelector('.wb-user-heading span')?.getBoundingClientRect();return {present:true,height:r.height,opacity:Number(s.opacity),scale:s.scale,labelX:heading&&message?heading.x-message.x:undefined,labelY:heading&&message?heading.y-message.y:undefined,exiting:node.dataset.wbExiting,animations:node.getAnimations().length};};
   const before=read();window[key]=new Promise((resolve,reject)=>{const timeout=setTimeout(()=>{document.removeEventListener('click',capture,true);reject(new Error('No captured click on '+target));},5000);const capture=async event=>{if(!n.contains(event.target))return;clearTimeout(timeout);document.removeEventListener('click',capture,true);const start=performance.now(),frames=[];let appeared=before.present,seenAt=start;while(performance.now()-start<2000){await new Promise(requestAnimationFrame);const frame=read();if(frame.present&&!appeared){appeared=true;seenAt=performance.now();}frames.push({elapsed:performance.now()-start,...frame});if(appeared&&performance.now()-seenAt>=650)break;}resolve({before,frames,after:read()});};document.addEventListener('click',capture,true);});
  },{target,key});
  await button.click();
  return page.evaluate(async key=>{const result=await window[key];delete window[key];return result;},key);
 };
 const interpolate=(data,property)=>data.frames.some(x=>x[property]>Math.min(data.before[property],data.after[property])+.005&&x[property]<Math.max(data.before[property],data.after[property])-.005);
 const verify=async(name,button,target,property)=>{const data=await sample(button,target);fs.writeFileSync(dir+'/latest-action.json',JSON.stringify({name,...data},null,2));assert(interpolate(data,property),name+' must have a visible intermediate '+property);pass(name,data);return data;};
 // Reading is tested with a real pointer as well as frame-level layout checks.
 if(!await page.locator('#chat .mes[is_user=true]').count())await page.evaluate(()=>TavernHelper.createChatMessages([{role:'user',message:'WB_CLICK 我推开窗，朝港口望去。'}]));await settle();
 const user=page.locator('#chat .mes[is_user=true]').last();await user.evaluate(n=>n.dataset.wbClickInput='true');const inputToggle=user.locator('.wb-user-heading button');
 const opening=await verify('user input expands without moving its heading',inputToggle,'[data-wb-click-input] .mes_text','height');assert(opening.frames.every(x=>Math.abs(x.labelX-opening.before.labelX)<1&&Math.abs(x.labelY-opening.before.labelY)<1));
 await verify('user input folds',inputToggle,'[data-wb-click-input] .mes_text','height');await user.evaluate(n=>delete n.dataset.wbClickInput);
 const chooser=page.locator('.wb-pill[aria-controls="wb-choices-connection"]');await verify('header chooser opens',chooser,'#wb-choices-connection','opacity');await verify('header chooser closes',chooser,'#wb-choices-connection','opacity');
 // Use genuine menu controls and check opening AND removal, not only hover color.
 await verify('chat menu opens',page.getByRole('button',{name:'聊天菜单',exact:true}),'.wb-popover[role=dialog]','opacity');
 const close=await verify('chat menu closes',page.getByRole('button',{name:'关闭弹出框',exact:true}),'.wb-popover[role=dialog]','opacity');assert(close.frames.some(x=>x.exiting==='true'&&x.present));assert(!close.after.present);
 for(const name of ['扩展工具','快速回复','阅读设置']){
  await verify(name+' opens',page.getByRole('button',{name,exact:true}),'.wb-popover[role=dialog]','opacity');
  await verify(name+' closes',page.getByRole('button',{name:'关闭弹出框',exact:true}),'.wb-popover[role=dialog]','opacity');
 }
 await openResource(page,'世界书详情');await settle();await page.locator('#wb-resource-rail .wb-rail-open').first().click();await settle();
 // The panel keeps one entry card open below the list (board PanelWorld); choosing a row swaps its contents in place.
 const card=page.locator('.wb-right .wb-entry-card');await card.waitFor();const firstText=await fieldValue(card.getByRole('textbox',{name:'世界书正文',exact:true}));
 await page.locator('.wb-right .wb-entry-open').nth(1).click();await settle();assert.notEqual(await fieldValue(card.getByRole('textbox',{name:'世界书正文',exact:true})),firstText);
 await page.screenshot({path:dir+'/world-editor.png'});
 await openResource(page,'预设详情');await settle();
 await verify('prompt editor expands',page.locator('.wb-right .wb-prompt-open').first(),'.wb-right .wb-prompt-sheet','height');
 await page.locator('.wb-right .wb-prompt-card textarea').evaluate(n=>window.__clickPrompt=n);await page.screenshot({path:dir+'/prompt-editor.png'});
 await verify('prompt editor folds',page.getByRole('button',{name:'收起提示词编辑',exact:true}),'.wb-right .wb-prompt-sheet','height');assert(await page.locator('.wb-right .wb-prompt-card textarea').evaluate(n=>n===__clickPrompt));
 await verify('resource rail folds',page.getByRole('button',{name:'收起预设资源列表',exact:true}),'#wb-resource-rail','opacity');
 await verify('resource rail expands',page.getByRole('button',{name:'展开预设资源列表',exact:true}),'#wb-resource-rail','opacity');
 const trigger=page.locator('.wb-right .wb-select-trigger').first();await verify('select opens',trigger,'.wb-select-menu','opacity');
 await verify('select closes',trigger,'.wb-select-menu','opacity');
 const checkbox=page.locator('.wb-right .wb-prompt input[type=checkbox]').first(),was=await checkbox.isChecked();
 const pressing=await sample(checkbox,'.wb-right .wb-prompt input[type=checkbox]');assert(pressing.frames.some(x=>x.scale!==1&&x.scale!=='1'&&x.scale!=='none'));await checkbox.setChecked(was);await settle();pass('short clicks visibly press and release; native check state restored',pressing);
 await page.getByRole('button',{name:'关闭右栏',exact:true}).click();await settle();
 const nav=page.locator('.wb-nav-footer').getByRole('button',{name:'设置',exact:true});await verify('settings workspace opens',nav,'.wb-settings-workspace','opacity');
 await page.locator('.wb-settings-nav').getByRole('button',{name:'回复格式',exact:true}).click();await settle();
 const header=page.locator('.wb-settings-workspace .wb-settings-subnav').getByRole('button',{name:'指令模板',exact:true});const changing=await sample(header,'.wb-settings-body');assert(changing.frames.some(x=>x.present&&x.opacity>.35&&x.opacity<.95),'settings group must visibly fade into place');pass('settings group changes',changing);

 await verify('settings workspace returns',page.getByRole('button',{name:'返回工作台',exact:true}),'.wb-settings-workspace','opacity');
 await openSettings(page,'背景');await page.locator('#bg_thumb_zoom_in').waitFor();await settle();
 const nativePress=await sample(page.locator('#bg_thumb_zoom_in'),'#bg_thumb_zoom_in');assert(nativePress.frames.some(x=>x.scale!=='none'&&x.scale!=='1'),'native icon actions must visibly press');await page.locator('#bg_thumb_zoom_out').click();await settle();pass('native icon action keeps thumbnail zoom and visibly presses',nativePress);
 await page.getByRole('button',{name:'返回工作台',exact:true}).click();await page.locator('.wb-settings-workspace').waitFor({state:'detached'});

 await withReducedMotion(page,async()=>{
  await nav.click();await page.locator('.wb-settings-workspace').waitFor();await settle();assert.equal(await page.locator('.wb-settings-workspace').evaluate(n=>n.getAnimations().length),0);
  await page.getByRole('button',{name:'返回工作台',exact:true}).click();await page.locator('.wb-settings-workspace').waitFor({state:'detached'});
 });assert(!await page.evaluate(()=>SillyTavern.getContext().powerUserSettings.reduced_motion));assert.deepEqual(errors,[]);pass('reduced-motion preference remains respected and restored; no browser errors',{});passed=true;
}catch(error){if(page)await page.screenshot({path:dir+'/failure.png'});throw error;}finally{
 if(page)videoPath=await page.video()?.path();if(context)await context.close();
 fs.writeFileSync(dir+'/verification.json',JSON.stringify({checkedAt:new Date().toISOString(),passed,checks,errors,videoPath,videoStart},null,2));await browser.close();
}
