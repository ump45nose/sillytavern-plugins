import assert from 'node:assert/strict';
import fs from 'node:fs';
import { launch, session, ready, urls, createCharacter } from './browser.mjs';

// D2: dragging #chat's scrollbar or wheel-scrolling near the edge must not reveal the right
// sidebar; resting in the edge lane still does, and the preference turns the lane off.
const dir='artifacts/edge-lane';fs.mkdirSync(dir,{recursive:true});
const checks=[],pass=(name,details)=>{checks.push({name,passed:true,details});console.log('PASS',name,JSON.stringify(details??{}));};
const browser=await launch();let page,errors=[],passed=false;
try {
 ({page,errors}=await session(browser));await page.setViewportSize({width:1496,height:817});await ready(page,urls.validation,{probe:true});await createCharacter(page);
 const settle=()=>page.waitForTimeout(330);
 await page.evaluate(()=>workbench.host.preference({edgeHover:true}));
 if(await page.locator('#chat .mes').count()<30)await page.evaluate(()=>TavernHelper.createChatMessages(Array.from({length:30},(_,i)=>({role:i%2?'assistant':'user',message:`WB_EDGE 第 ${i+1} 段：`+'港口的风吹过灯塔。'.repeat(12)}))));
 // Close both sidebars so #chat reaches as far as the lane allows.
 await page.evaluate(()=>workbench.host.preference({left:false}));await settle();
 if(await page.evaluate(()=>document.body.classList.contains('wb-right-open')))await page.getByRole('button',{name:'关闭右栏',exact:true}).click();
 if(await page.evaluate(()=>document.body.classList.contains('wb-left-open')))await page.getByRole('button',{name:/收纳左边栏/}).click();
 await page.mouse.move(700,400);await settle();
 const hot=()=>page.evaluate(()=>document.body.classList.contains('wb-right-hover-open'));
 const geometry=await page.evaluate(()=>{const lane=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--wb-edge-lane'));const chat=document.getElementById('chat');const r=chat.getBoundingClientRect();return {lane,right:r.right,left:r.left,width:innerWidth,scrollable:chat.scrollHeight>chat.clientHeight,edge:document.body.classList.contains('wb-edge-hover')};});
 assert(geometry.edge,'edge hover class must be on');assert(geometry.scrollable,'fixture chat must scroll');
 assert(geometry.right<=geometry.width-geometry.lane+0.5,`#chat must end before the right lane: ${JSON.stringify(geometry)}`);
 assert(geometry.left>=geometry.lane-0.5,`#chat must start after the left lane: ${JSON.stringify(geometry)}`);
 const arrows=await page.evaluate(()=>({right:document.querySelector('.wb-edge-right').getBoundingClientRect().left,left:document.querySelector('.wb-edge-left').getBoundingClientRect().right}));
 assert(arrows.right>=geometry.right-0.5&&arrows.left<=geometry.left+0.5,`edge arrows must stay in the lanes: ${JSON.stringify(arrows)}`);
 pass('#chat and its scrollbar sit inside both edge lanes; the arrows stay in the lanes',{...geometry,arrows});
 // Drag the scrollbar thumb and overshoot into the lane, as a hurried user does.
 const y=420,thumbX=geometry.right-3;
 await page.mouse.move(thumbX,y);await page.mouse.down();
 for(const x of [thumbX,geometry.width-geometry.lane/2,geometry.width-4])await page.mouse.move(x,y+40,{steps:4});
 await page.waitForTimeout(450);assert.equal(await hot(),false,'scrollbar drag into the lane must not reveal the sidebar');
 await page.mouse.up();await page.waitForTimeout(450);assert.equal(await hot(),false,'releasing in the lane without moving must not reveal');
 // Releasing over the edge arrow makes Chromium click it; that click must not pin the sidebar.
 assert.equal(await page.evaluate(()=>document.body.classList.contains('wb-right-open')),false,'releasing a drag over the edge arrow must not open the sidebar');
 pass('scrollbar drag overshooting into the lane keeps the sidebar closed');
 await page.mouse.move(700,400);await settle();
 await page.mouse.wheel(0,600);await page.mouse.move(geometry.width-6,400,{steps:3});await page.waitForTimeout(300);
 assert.equal(await hot(),false,'pointer arriving right after wheel scrolling must not reveal');
 await page.waitForTimeout(400);await page.mouse.move(geometry.width-8,404);await page.waitForTimeout(450);
 assert.equal(await hot(),true,'resting in the lane once scrolling has settled reveals the sidebar');
 pass('wheel scrolling suppresses the reveal for 500 ms, resting afterwards reveals');
 await page.mouse.move(700,400);await page.waitForTimeout(700);assert.equal(await hot(),false);
 await page.mouse.move(geometry.width-5,500);await page.mouse.move(700,500);await page.waitForTimeout(400);
 assert.equal(await hot(),false,'passing through the lane without dwelling must not reveal');
 pass('a brief pass through the lane does not reveal');
 await page.evaluate(()=>workbench.host.preference({edgeHover:false}));await settle();
 const off=await page.evaluate(()=>({edge:document.body.classList.contains('wb-edge-hover'),right:document.getElementById('chat').getBoundingClientRect().right,width:innerWidth}));
 assert.equal(off.edge,false);assert(Math.abs(off.right-(off.width-12))<2,'with edge reveal off #chat reaches the sheet edge, one 12px desk gutter from the window');
 await page.mouse.move(geometry.width-6,400);await page.mouse.move(geometry.width-8,404);await page.waitForTimeout(500);assert.equal(await hot(),false,'edge reveal off');
 await page.evaluate(()=>workbench.host.preference({edgeHover:true}));await settle();
 const arrow=page.getByRole('button',{name:'角色与资源侧栏',exact:true});await arrow.click();await page.waitForFunction(()=>document.body.classList.contains('wb-right-open'));await settle();
 const open=await page.evaluate(()=>{const panel=document.querySelector('.wb-right.is-open').getBoundingClientRect().left;return {panel,chat:document.getElementById('chat').getBoundingClientRect().right,arrow:document.querySelectorAll('.wb-edge-right').length}});
 // The pinned panel is a card on the desk: one gutter separates the sheet from it; the edge arrow stays beside it to fold it again.
 assert(Math.abs(open.panel-12-open.chat)<1.5&&open.arrow===1,`a pinned sidebar takes no lane and keeps its edge arrow: ${JSON.stringify(open)}`);
 // A scrollbar drag released over the gutter beside the card must not close the panel.
 await page.mouse.move(open.chat-3,320);await page.mouse.down();await page.mouse.move(open.chat+6,400,{steps:6});await page.mouse.up();await settle();
 assert.equal(await page.evaluate(()=>document.body.classList.contains('wb-right-open')),true,'releasing a scrollbar drag beside the card must not close the sidebar');
 await page.getByRole('button',{name:'收纳右边栏',exact:true}).click();await page.waitForFunction(()=>!document.body.classList.contains('wb-right-open'));
 pass('the preference turns the lane and the reveal off together; a pinned sidebar takes no lane; edge arrows toggle on click only and fold a pinned sidebar');
 assert.deepEqual(errors,[]);passed=true;
}catch(error){if(page)await page.screenshot({path:dir+'/failure.png'});throw error;}finally{fs.writeFileSync(dir+'/verification.json',JSON.stringify({checkedAt:new Date().toISOString(),passed,checks,errors},null,2));await browser.close();}
