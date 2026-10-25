import assert from 'node:assert/strict';
import fs from 'node:fs';
import {launch,session,ready,urls,createCharacter,connect,selectPaper,paperValue,mockApi,exitFocus,sameColor,openResource} from './browser.mjs';
const dir='artifacts/resource-sidebars';fs.mkdirSync(dir,{recursive:true});const b=await launch(),checks=[];const pass=name=>{checks.push(name);console.log('PASS',name)};
try {
 const {page,errors}=await session(b);await ready(page,urls.validation,{probe:true});await createCharacter(page);await connect(page);
 const settle=()=>page.waitForTimeout(300);
 const open=async label=>{await openResource(page,label);await settle();};
 const order=await page.locator('.wb-top-tools button').evaluateAll(es=>es.map(e=>({label:e.getAttribute('aria-label'),text:e.textContent,size:e.querySelector('svg')?.getAttribute('width')})));
 assert.deepEqual(order.map(x=>x.label),['Trace','专注模式']);assert(order.every(x=>x.text===''&&x.size==='18'));
 await page.getByRole('button',{name:'专注模式',exact:true}).click();await settle();assert.equal(await page.getByRole('button',{name:'退出专注'}).getAttribute('aria-pressed'),'true');await exitFocus(page);pass('icon-only header tools in order; focus mode exits from its pill');
 await page.evaluate(async()=>{const h=workbench.host,c=SillyTavern.getContext();const base=h.presetData(c.getPresetManager().getSelectedPresetName());await c.getPresetManager().savePreset('WorkbenchSidebarPreset', {...base,vendor_sidebar_keep:{yes:true}});h.refresh();await h.select('preset','WorkbenchSidebarPreset');});
 await open('预设');
 assert.equal(await page.locator('.wb-resources .wb-resource-list').count(),0);
 assert(await page.locator('#wb-resource-rail .wb-rail').isVisible());
 await page.getByRole('textbox',{name:'搜索预设',exact:true}).fill('WorkbenchSidebarPreset');
 const presetChoice=page.locator('#wb-resource-rail .wb-rail-row').first();await presetChoice.locator('.wb-rail-open').hover();await settle();
 assert.equal(await presetChoice.locator('.wb-rail-open').evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');
 {const bg=await presetChoice.evaluate(e=>getComputedStyle(e).backgroundColor);/* E3: the row being viewed is a lifted paper chip. */assert(sameColor(bg,'rgb(255, 254, 250)'),bg);}
 await presetChoice.locator('.wb-rail-open').click();
 await page.getByLabel('流式传输',{exact:true}).waitFor();
 const first=page.locator('.wb-prompt input[type=checkbox]').first(), was=await first.isChecked();await first.setChecked(!was);
 await page.getByRole('button',{name:'新增提示词',exact:true}).click();const promptName='WB 右栏提示词 '+Date.now();await page.getByLabel('提示词名称',{exact:true}).fill(promptName);await page.getByLabel('提示词正文',{exact:true}).fill('**保留** <xml>{{user}}</xml>');
 await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('已保存',{exact:true}).waitFor();
 // The running preset takes edits at once (P model); "更新预设" writes them into the file.
 const pending=page.getByText('预设有未写入的修改',{exact:true});
 assert.equal(await page.evaluate(name=>workbench.host.presetData('WorkbenchSidebarPreset').prompts.some(p=>p.name===name),promptName),false);
 await pending.waitFor();await page.getByRole('button',{name:'更新预设',exact:true}).click();await pending.waitFor({state:'detached'});
 const preset=await page.evaluate(()=>workbench.host.presetData('WorkbenchSidebarPreset'));assert(preset.prompts.some(p=>p.name===promptName&&p.content.includes('<xml>')));assert.deepEqual(preset.vendor_sidebar_keep,{yes:true});assert.equal(preset.prompt_order[0].order[0].enabled,!was);
 // Keep mock generation normal by restoring the initial enabled bit.
 await first.setChecked(was);await pending.waitFor();await page.getByRole('button',{name:'更新预设',exact:true}).click();await pending.waitFor({state:'detached'});
 await page.getByRole('button',{name:'自定义常用项',exact:true}).click();const pin=page.getByRole('checkbox',{name:'Top P',exact:true});await pin.setChecked(true);await page.getByRole('button',{name:'自定义常用项',exact:true}).click();assert(await page.getByRole('spinbutton',{name:'Top P',exact:true}).isVisible());
 await settle();await page.locator('.wb-preset-editor').evaluate(e=>e.scrollTop=0);await page.screenshot({path:dir+'/preset-1440.png'});pass('preset prompt flags, new raw content and unknown fields persist; pinned parameters update');
 await page.evaluate(async()=>{const h=workbench.host;await h.createPreset('WorkbenchSidebarDelete',h.presetData('WorkbenchSidebarPreset'));});
 await page.route('**/api/presets/delete',r=>r.fulfill({status:500,body:'fixture failure'}));
 const failure=await page.evaluate(async()=>{try{await workbench.host.deletePreset('WorkbenchSidebarDelete');return false;}catch{return SillyTavern.getContext().getPresetManager().getAllPresets().includes('WorkbenchSidebarDelete');}});assert.equal(failure,true);await page.unroute('**/api/presets/delete');
 await page.evaluate(async()=>{await workbench.host.deletePreset('WorkbenchSidebarDelete');await workbench.host.select('preset','WorkbenchSidebarPreset');});
 assert.equal(await page.evaluate(()=>SillyTavern.getContext().getPresetManager().getAllPresets().includes('WorkbenchSidebarDelete')),false);pass('preset creation and deletion; failed delete restores host list');
 await open('用户设定');const oldPosition=await paperValue(page,'注入位置');/* Depth and role only show for an in-chat position (board PanelPersona). */await selectPaper(page,'注入位置','4');const oldDepth=await page.getByLabel('深度',{exact:true}).inputValue();await page.getByLabel('深度',{exact:true}).fill('3');await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('已保存',{exact:true}).waitFor();
 const injection=await page.evaluate(()=>({position:SillyTavern.getContext().powerUserSettings.persona_description_position,depth:SillyTavern.getContext().powerUserSettings.persona_description_depth}));assert.deepEqual(injection,{position:4,depth:3});
 await page.getByLabel('深度',{exact:true}).fill(oldDepth);await selectPaper(page,'注入位置',oldPosition);await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('已保存',{exact:true}).waitFor();
 await page.locator('.wb-resource-detail').evaluate(e=>e.scrollTop=0);await page.screenshot({path:dir+'/persona-1440.png'});pass('Persona injection fields save through host and update active runtime');
 await page.evaluate(()=>{window.__nativeConnection=document.querySelector('#rm_api_block');window.__nativeParent=__nativeConnection.parentNode;});
 await open('连接');assert.equal(await page.locator('.wb-settings-source #main_api').count(),1);assert(await page.locator('.wb-connection-card').getByRole('button',{name:'连接',exact:true}).isVisible());
 assert.deepEqual(await page.locator('.wb-panel-heading-actions button').evaluateAll(ns=>ns.map(n=>n.getAttribute('aria-label')).filter(x=>x!=='使用此连接')),['记录','删除']);assert(await page.getByRole('button',{name:'新建连接配置',exact:true}).isVisible());
 /* Board PanelConnection: interface type and provider first, then the model, then connect/test closing the card. */const sequence=await page.locator('.wb-connection-card').evaluate(e=>{const y=s=>e.querySelector(s).getBoundingClientRect().y;return {type:y('.wb-card-row'),model:y('.wb-connection-pick'),actions:y('.wb-connection-bar')};});assert(sequence.type<sequence.model&&sequence.model<sequence.actions);
 const scrollbar=await page.locator('.wb-connection-detail').evaluate(e=>({width:getComputedStyle(e,'::-webkit-scrollbar').width,track:getComputedStyle(e,'::-webkit-scrollbar-track').backgroundColor}));assert.equal(scrollbar.width,'6px');assert.equal(scrollbar.track,'rgba(0, 0, 0, 0)');
 await selectPaper(page,'接口类型','openai');await page.locator('.wb-resource-detail').evaluate(e=>e.scrollTop=0);await page.screenshot({path:dir+'/connection-1440.png'});
 await selectPaper(page,'服务商','custom');await page.getByRole('textbox',{name:'运行模型',exact:true}).fill('workbench-fixture');
 assert.equal(await page.evaluate(()=>SillyTavern.getContext().chatCompletionSettings.custom_model),'workbench-fixture');
 await page.locator('[data-control=custom_api_url_text] input').fill(mockApi);
 assert(await page.locator('[data-control=api_key_custom] input').isVisible());assert(await page.locator('.page-connection .wb-designed-actions').getByRole('button',{name:"管理 API 凭据",exact:true}).isVisible());
 const quick=page.locator('.wb-connection-card');await quick.getByRole('button',{name:'连接',exact:true}).click();await page.waitForFunction(()=>workbench.host.snapshot().online);await settle();
 const tested=page.waitForResponse(r=>r.url().endsWith('/api/backends/chat-completions/generate')&&r.request().method()==='POST');await quick.getByRole('button',{name:'测试',exact:true}).click();assert.equal((await tested).status(),200);
 pass('API model/connect/test at the front, live native fields and uniform six-pixel scrollbar');
 await page.locator('.wb-connection-card').getByRole('button',{name:'连接',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:dir+'/connection-live-1440.png'});
 const activeProfile=await page.evaluate(()=>workbench.host.snapshot().current.connection), newName='WorkbenchNativeHeader-'+Date.now();
 assert(await page.locator('#wb-resource-rail .wb-rail').isVisible());const inactive=page.locator('#wb-resource-rail .wb-rail-row:not(.is-on)').first();
 if(await inactive.count()){await inactive.locator('.wb-rail-open').click();assert.equal(await page.evaluate(()=>workbench.host.snapshot().current.connection),activeProfile);assert(await page.locator('.wb-panel-heading-actions').getByRole('button',{name:'记录',exact:true}).isDisabled());}
 await page.getByRole('button',{name:'新建连接配置',exact:true}).click();
 const popup=page.locator('dialog.popup[open]');await popup.locator('.popup-input').fill(newName);await popup.locator('.popup-button-ok').click();
 await page.waitForFunction(name=>workbench.host.snapshot().resources.connection.some(x=>x.name===name),newName);
 await page.waitForFunction(name=>document.querySelector('.wb-right .wb-panel-title')?.textContent.includes(name),newName);
 await page.locator('.wb-panel-heading-actions').getByRole('button',{name:'记录',exact:true}).click();
 await page.waitForFunction(name=>workbench.host.snapshot().resources.connection.find(x=>x.name===name)?.data.model==='workbench-fixture',newName);
 await page.locator('.wb-panel-heading-actions').getByRole('button',{name:'删除',exact:true}).click();await popup.locator('.popup-button-ok').click();
 await page.waitForFunction(name=>!workbench.host.snapshot().resources.connection.some(x=>x.name===name),newName);
 if(activeProfile)await page.evaluate(id=>workbench.host.select('connection',id),activeProfile);
 pass('rail creates, heading records and deletes connection profiles through the official manager');
 await open('世界书');assert(await page.evaluate(()=>__nativeConnection===document.querySelector('#rm_api_block')&&__nativeConnection.parentNode===__nativeParent));
 assert.equal(await page.locator('#rm_api_block .wb-connection-bridged,#rm_api_block .wb-connection-profile-original').count(),0);
 assert.equal(await page.getByRole('button',{name:'编辑条目',exact:true}).count(),0);assert.equal(await page.getByLabel('世界书正文',{exact:true}).getAttribute('readonly'),null);await page.screenshot({path:dir+'/world-1440.png'});pass('complete native connection form is reachable and same nodes restore on panel switch');
 await page.getByRole('button',{name:'关闭右栏',exact:true}).click();await settle();await connect(page);await page.evaluate(()=>workbench.clear());await page.locator('#send_textarea').fill('wb_lore WB 右栏 Trace');await page.locator('#send_but').click();await page.waitForFunction(()=>workbench.records.at(-1)?.status===200&&!SillyTavern.getContext().streamingProcessor);
 await page.locator('.wb-top-tools').getByRole('button',{name:'Trace',exact:true}).click();await settle();assert.equal(await page.locator('.wb-top-tools [aria-label=Trace]').getAttribute('aria-pressed'),'true');
 const r=await page.evaluate(()=>({composition:workbench.records.at(-1).composition,timestamp:workbench.records.at(-1).timestamp}));assert(r.composition?.counts);assert(r.timestamp>0);assert.equal(await page.locator('.wb-tr-parts > div').count(),6);await page.screenshot({path:dir+'/trace-1440.png'});
 await page.getByRole('button',{name:'查看完整 Prompt'}).click();await page.getByRole('dialog').waitFor();assert(await page.getByRole('dialog').getByText('完整请求与参数',{exact:true}).isVisible());await page.getByRole('button',{name:'返回工作台',exact:true}).click();pass('real trace composition, request time and full prompt; active Trace indicator');
 for(const [width,height] of [[1366,768],[1440,900],[1920,1080]]){await page.setViewportSize({width,height});for(const kind of ['预设','用户设定','连接','世界书']){await open(kind);const overflow=await page.locator('.wb-right').evaluate(e=>[e,...e.querySelectorAll('.wb-resource-detail,.wb-native-slot')].some(n=>n.scrollWidth>n.clientWidth+1));assert.equal(overflow,false,kind+' '+width);if(kind==='预设'){const balance=await page.locator('.wb-preset-editor').evaluate(e=>e.querySelector('.wb-prompts').getBoundingClientRect().height-e.querySelector('.wb-preset-more').getBoundingClientRect().height);assert(balance>0,'prompt list remains dominant '+width);}await page.screenshot({path:`${dir}/${kind}-${width}.png`});}}
 pass('resource layouts at 1366, 1440 and 1920 without horizontal overflow');assert.deepEqual(errors,[]);fs.writeFileSync(dir+'/verification.json',JSON.stringify({checks,errors},null,2));
}catch(e){console.error(e);process.exitCode=1;}finally{await b.close();}
