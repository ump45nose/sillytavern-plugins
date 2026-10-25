import assert from 'node:assert/strict';
import fs from 'node:fs';
import {launch,session,ready,urls,artifacts,createCharacter} from './browser.mjs';
const browser=await launch(),dir=artifacts+'/sidebar-image-input';fs.mkdirSync(dir,{recursive:true});
const report={checks:[],passed:false};let page;
try{
 const test=await session(browser);page=test.page;
 await page.route('**/api/settings/save',r=>r.fulfill({json:{}}));
 await page.route('**/api/chats/save',r=>r.fulfill({json:{result:'ok'}}));
 await page.route('**/api/settings/get',async r=>{const response=await r.fetch(),data=await response.json(),s=JSON.parse(data.settings);s.active_character=null;s.active_group=null;s.extension_settings.workbench??={};Object.assign(s.extension_settings.workbench,{layout:'novel',left:true,addons:{outline:true,'image-gen':true,'record-export':true}});data.settings=JSON.stringify(s);await r.fulfill({response,json:data});});
 await page.setViewportSize({width:1496,height:817});await ready(page,urls.validation);await page.waitForFunction(()=>window.workbench?.mounted&&workbench.metrics.workbenchReadyMs);
 // Start on the welcome screen: its floors have no chat file to hold image results, so they get no image action.
 await page.locator('#chat>.mes .mes_edit').first().waitFor({state:'attached'});assert.equal(await page.evaluate(()=>SillyTavern.getContext().getCurrentChatId()),undefined);assert.equal(await page.locator('.wb-image-message-button').count(),0);
 await createCharacter(page);await page.waitForFunction(()=>!!SillyTavern.getContext().getCurrentChatId());await page.locator('.wb-image-message-button').first().waitFor({state:'attached'});
 const button=name=>page.getByRole('button',{name,exact:true}),wait=()=>page.waitForTimeout(350),pass=s=>{report.checks.push(s);console.log('PASS',s);};
 const sections=['history','outline','floors'];
 const state=()=>page.locator('.wb-nav-section').evaluateAll(ns=>ns.map(n=>{const b=n.querySelector('.wb-nav-toggle'),c=n.querySelector('.wb-fold-body');return {id:n.id,expanded:b.getAttribute('aria-expanded'),inert:c.inert};}));
 const initial=await state();assert.deepEqual(initial.map(x=>x.expanded),['false','false','true']);
 for(const id of sections){
  const toggle=page.locator(`#wb-nav-${id} .wb-nav-toggle`),before=await state();await toggle.click();await wait();const after=await state();
  after.forEach((node,i)=>{if(node.id===`wb-nav-${id}`){assert.notEqual(node.expanded,before[i].expanded);assert.equal(node.inert,node.expanded==='false');}else assert.deepEqual(node,before[i],'peer sections keep their own state: '+node.id);});
  assert.equal(await page.locator('.wb-nav-card').evaluate(n=>!n.closest('[inert]')),true);const footer=await page.locator('.wb-nav-footer').boundingBox();assert.ok(footer.y+footer.height<=817);
  await page.screenshot({path:dir+`/fold-${id}-1496.png`});await toggle.click();await wait();
 }
 assert.deepEqual(await state(),initial);await page.locator('#wb-nav-outline .wb-nav-toggle').click();await page.getByRole('tree',{name:'当前聊天大纲'}).waitFor();await page.locator('#wb-nav-outline .wb-nav-toggle').click();await wait();
 pass('nav sections fold independently; the current chat card and the settings footer stay reachable');
 await button('大纲').click();await page.getByRole('tree',{name:'当前聊天大纲'}).waitFor();await wait();await page.screenshot({path:dir+'/outline-1496.png'});await button('大纲').click();await wait();
 await page.locator('.wb-edge-left').click();await page.mouse.move(600,350);await wait();
 const reading=await page.locator('#sheld').boundingBox();await page.mouse.move(2,400);await page.waitForFunction(()=>document.body.classList.contains('wb-left-hover-open'));await wait();
 assert.deepEqual(await page.locator('#sheld').boundingBox(),reading);await page.mouse.move(130,430);await wait();assert.equal(await page.locator('.wb-left').getAttribute('aria-hidden'),'false');await page.mouse.move(700,400);await page.waitForFunction(()=>!document.body.classList.contains('wb-left-hover-open'));
 await page.mouse.move(1494,400);await page.waitForFunction(()=>document.body.classList.contains('wb-right-hover-open'));await wait();assert.deepEqual(await page.locator('#sheld').boundingBox(),reading);await page.locator('.wb-edge-right').click();await page.mouse.move(600,400);await wait();assert.equal(await page.locator('.wb-edge-right').getAttribute('aria-label'),'收纳右边栏');assert.equal(await page.evaluate(()=>document.body.classList.contains('wb-right-open')),true);await page.locator('.wb-panel-close').click();await page.mouse.move(600,400);await wait();
 pass('edge hover reveals overlays without moving reading layout; moving within keeps open, leaving closes, click pins');
 const inputStyle=()=>page.locator('#send_textarea').evaluate(n=>{const css=getComputedStyle(n);return Object.fromEntries(['font','padding','backgroundColor','borderRadius'].map(key=>[key,css[key]]));});
 const inputGeometry=()=>page.evaluate(()=>Object.fromEntries(['send_form','send_textarea'].map(id=>{const r=document.getElementById(id).getBoundingClientRect();return[id,{x:r.x,y:r.y,width:r.width,height:r.height}];})));
 const sendStyle=()=>page.locator('#send_but').evaluate(n=>{const css=getComputedStyle(n);return Object.fromEntries(['width','height','padding','borderRadius','backgroundColor'].map(key=>[key,css[key]]));});
 const originalStyle=await inputStyle(),originalGeometry=await inputGeometry(),originalSendStyle=await sendStyle();
 await page.evaluate(()=>{window.__originalInput=document.getElementById('send_textarea');});await page.locator('#send_textarea').fill('保持聊天草稿');await page.locator('#chat>.mes').first().hover();await button('为第 1 层生图').click();await button('取消手动生图').waitFor();
 await page.waitForFunction(()=>document.querySelector('#send_textarea').placeholder.includes('参考图'));await page.locator('#send_textarea').fill('柔和夕阳下的花园，保持参考人物外貌');
 const png=fs.readFileSync('tests/writing-addons.test.mjs','utf8').match(/const png='([^']+)'/)[1];await page.locator('.wb-image-input-anchor input[type=file]').setInputFiles({name:'portrait.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});await page.locator('.wb-image-input-anchor img').waitFor();await wait();
 const geometry=await page.evaluate(()=>{const r=s=>document.querySelector(s).getBoundingClientRect();const label=r('.wb-image-input-label'),input=r('#send_textarea'),refs=r('.wb-image-references'),send=r('#send_but'),form=r('#send_form');return{ordered:input.bottom<=label.top+1&&Math.abs(label.y+label.height/2-(send.y+send.height/2))<3&&Math.abs(refs.y+refs.height/2-(send.y+send.height/2))<3,fits:send.bottom<=form.bottom&&input.height>=55,same:__originalInput===document.getElementById('send_textarea')};});assert.equal(geometry.ordered,true);assert.equal(geometry.fits,true);assert.equal(geometry.same,true);assert.deepEqual(await inputStyle(),originalStyle);assert.deepEqual(await inputGeometry(),originalGeometry);assert.deepEqual(await sendStyle(),originalSendStyle);assert.equal(await page.locator('#send_but .wb-send-icon').count(),1);await page.screenshot({path:dir+'/image-input-reference-1496.png'});
 await button('移除参考图 1').click();assert.equal(await page.locator('.wb-image-input-anchor img').count(),0);
 await page.locator('#send_textarea').evaluate((input,png)=>{const data=new DataTransfer();data.items.add(new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],'pasted.png',{type:'image/png'}));input.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}));},png);await page.locator('.wb-image-input-anchor img').waitFor();
 await button('移除参考图 1').click();await page.locator('#send_textarea').evaluate((input,png)=>{const data=new DataTransfer();data.items.add(new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],'dropped.png',{type:'image/png'}));input.dispatchEvent(new DragEvent('drop',{dataTransfer:data,bubbles:true,cancelable:true}));},png);await page.locator('.wb-image-input-anchor img').waitFor();
 let referenceBody;await page.route('**/wb-mock-images/v1/images/edits',async route=>{referenceBody=route.request().postDataBuffer();await route.fulfill({json:{data:[{b64_json:png}]}});});
 await page.route('**/api/images/upload',route=>route.fulfill({json:{path:'/user/images/wb-reference-check.png'}}));await page.route('**/user/images/wb-reference-check.png',route=>route.fulfill({contentType:'image/png',body:Buffer.from(png,'base64')}));
 const resultCount=await page.evaluate(()=>SillyTavern.getContext().chatMetadata.workbench_addons?.['image-gen']?.results?.length||0);
 await page.evaluate(()=>{const prefs=workbench.host.prefs();workbench.host.preference({addonSettings:{...prefs.addonSettings,'image-gen':{...prefs.addonSettings?.['image-gen'],provider:'openai',url:location.origin+'/wb-mock-images/v1',key:''}}});});
 await page.locator('#send_but').click();await page.waitForFunction(n=>(SillyTavern.getContext().chatMetadata.workbench_addons?.['image-gen']?.results?.length||0)===n+1,resultCount);
 assert.ok(referenceBody.includes(Buffer.from(png,'base64')));assert.ok(referenceBody.includes(Buffer.from('name="image[]"')));assert.equal(await page.locator('#send_textarea').inputValue(),'保持聊天草稿');assert.equal(await page.evaluate(png=>JSON.stringify(SillyTavern.getContext().chatMetadata).includes(png),png),false);
 pass('manual image controls share the original toolbar; textarea/send geometry and styles are unchanged, reference upload/paste/drop still reach the request');
 for(const mode of ['novel','rp'])for(const width of [1024,1496,1920]){
  await page.setViewportSize({width,height:817});await page.evaluate(layout=>workbench.host.preference({layout}),mode);await page.mouse.move(width/2,400);await wait();
  const normalStyle=await inputStyle(),normalGeometry=await inputGeometry(),normalSendStyle=await sendStyle();await page.screenshot({path:dir+`/normal-${mode}-${width}.png`});
  if(mode==='rp')await button('为当前对白生图').click();else{await page.locator('#chat>.mes').first().hover();await button('为第 1 层生图').click();}
  await button('取消手动生图').waitFor();await wait();const same=async()=>{assert.deepEqual(await inputStyle(),normalStyle);assert.deepEqual(await inputGeometry(),normalGeometry);assert.deepEqual(await sendStyle(),normalSendStyle);};if(mode==='rp')assert.equal(await page.evaluate(()=>document.body.hasAttribute('data-wb-rp-compose')),true);else await same();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);await page.screenshot({path:dir+`/image-${mode}-${width}.png`});await button('取消手动生图').click();if(mode==='rp'){await wait();await same();}
 }
 pass('manual image mode preserves the Noval composer; in RP it opens the compose box and cancelling restores the reading row, at narrow/main/wide widths');assert.deepEqual(test.errors,[]);report.passed=true;
}catch(error){report.failure=error.stack;console.error(error);process.exitCode=1;if(page)await page.screenshot({path:dir+'/failure.png'}).catch(()=>{});}finally{fs.writeFileSync(dir+'/verification.json',JSON.stringify(report,null,2));await browser.close();}
