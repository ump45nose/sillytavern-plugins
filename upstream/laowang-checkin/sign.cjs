const fs=require('fs'),path=require('path'),{firefox}=require('playwright-firefox');
const dataDir=path.resolve(process.env.LAOWANG_DATA_DIR||'./data');fs.mkdirSync(dataDir,{recursive:true,mode:0o700});
const profile=path.join(dataDir,'browser');const proxy=process.env.LAOWANG_PROXY;
(async()=>{let c;const result={time:new Date().toISOString(),status:'failed',sign_in_confirmed:false};try{
 c=await firefox.launchPersistentContext(profile,{headless:true,...(proxy?{proxy:{server:proxy}}:{}),viewport:{width:1280,height:800}});
 const p=c.pages()[0]||await c.newPage();await p.goto('https://laowang.vip/plugin.php?id=k_misign:sign',{waitUntil:'domcontentloaded',timeout:45000});
 await p.waitForTimeout(1000);
 const readStatus=async()=>({signed:await p.locator('.qdleft .btnvisted').count()>0,reward:await p.locator('#lxreward').inputValue().catch(()=>null),streak:await p.locator('#lxdays').inputValue().catch(()=>null),days:await p.locator('#lxtdays').first().inputValue().catch(()=>null)});
 let status=await readStatus();if(status.signed){Object.assign(result,{status:'already_signed',sign_in_confirmed:true,details:status,submitted:false});return;}
 if(process.argv.includes('--status')){Object.assign(result,{status:'not_signed',details:status,submitted:false});return;}
 const html=await p.content();const hash=html.match(/formhash=([a-f0-9]{8})/);if(!hash)throw Error('Missing current authenticated formhash');
 await p.goto('https://laowang.vip/plugin.php?id=k_misign:sign&operation=qiandao&formhash='+hash[1]+'&format=empty',{waitUntil:'domcontentloaded',timeout:45000});
 let text=await p.locator('body').innerText();
 if(await p.locator('#tncode').count()){
  await p.locator('#tncode').click();
  try{await p.waitForFunction(()=>window.tncode?._img_loaded===true,{},{timeout:15000})}
  catch{await p.locator('.tncode_refresh').click();await p.waitForFunction(()=>window.tncode?._img_loaded===true,{},{timeout:15000})}
  const match=await p.evaluate(()=>{
   const t=window.tncode,w=t._img_w,h=t._img_h,m=t._mark_w;
   const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h*3;const ctx=canvas.getContext('2d');ctx.drawImage(t._img,0,0);const d=ctx.getImageData(0,0,w,h*3).data;
   const samples=[];for(let y=8;y<h-20;y+=2)for(let x=8;x<m-8;x+=2){const i=((y+h)*w+x)*4;if(d[i]+d[i+1]+d[i+2]>220)samples.push({x,y,r:d[i],g:d[i+1],b:d[i+2]});}
   if(samples.length<50)throw Error('Insufficient puzzle pixels');
   const scores=[];for(let off=1;off<=w-m;off++){let error=0;for(const q of samples){const i=((q.y+h*2)*w+q.x+off)*4;error+=(d[i]-q.r)**2+(d[i+1]-q.g)**2+(d[i+2]-q.b)**2;}scores.push({x:off,error:error/samples.length});}scores.sort((a,b)=>a.error-b.error);const best=scores[0],second=scores.find(q=>Math.abs(q.x-best.x)>5);return {...best,width:w,markWidth:m,samples:samples.length,ratio:second.error/Math.max(best.error,1)};
  });result.match=match;if(match.ratio<1.08)throw Error('Puzzle difference confidence too low');
  const box=await p.locator('.slide_block').boundingBox();if(!box)throw Error('Slider not visible');
  const x=box.x+box.width/2,y=box.y+box.height/2;await p.mouse.move(x,y);await p.mouse.down();
  for(let i=1;i<=28;i++){const f=i/28,pace=f<0.5?2*f*f:1-Math.pow(-2*f+2,2)/2;await p.mouse.move(x+(match.x+3)*pace,y+Math.sin(f*Math.PI)*2+(i%5===0?1:0));await p.waitForTimeout(9+Math.round(Math.random()*10));}
  for(let i=1;i<=4;i++){await p.mouse.move(x+match.x+3-i*0.75,y+(i%2));await p.waitForTimeout(17+Math.round(Math.random()*10));}
  const check=p.waitForResponse(r=>r.url().includes('/captcha/check.php'),{timeout:15000});await p.mouse.up();const answer=(await (await check).text()).trim();result.captcha_response=answer.includes('_ok')?'ok':answer.slice(0,60);result.track=await p.evaluate(()=>{const t=window.tncode._track_data;return {points:t.length,duration:t.at(-1).t,distance:t.at(-1).x-t[0].x,vertical:t.at(-1).y-t[0].y}});if(!answer.includes('_ok'))throw Error('Captcha rejected: '+answer.slice(0,60));
  result.verification='passed';result.submitted=true;await p.locator('#submit-btn').click();await p.waitForTimeout(3000);text=await p.locator('body').innerText();
 }
 await p.goto('https://laowang.vip/plugin.php?id=k_misign:sign',{waitUntil:'domcontentloaded',timeout:45000});
 status=await readStatus();result.details=status;result.sign_in_confirmed=status.signed;result.status=status.signed?'confirmed':'business_unconfirmed';
 await c.storageState({path:path.join(dataDir,'state.json')});fs.chmodSync(path.join(dataDir,'state.json'),0o600);
 await p.screenshot({path:path.join(dataDir,'result.png')});
 }catch(e){result.error=e.message.split('\n')[0];const p=c?.pages()[0];if(p)await p.screenshot({path:path.join(dataDir,'result.png')}).catch(()=>{});}finally{await c?.close();fs.writeFileSync(path.join(dataDir,'result.json'),JSON.stringify(result,null,2),{mode:0o600});console.log(JSON.stringify(result));if(!result.sign_in_confirmed)process.exitCode=2;}})();
