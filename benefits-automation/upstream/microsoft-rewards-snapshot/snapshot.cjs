const fs=require('fs');const {DatabaseSync}=require('node:sqlite');
const {chromium}=require(require('path').join(process.env.REWARDS_ROOT || process.cwd(),'node_modules/patchright'));
(async()=>{let browser;try{fs.mkdirSync(process.env.REWARDS_EVIDENCE_DIR || './evidence',{recursive:true,mode:0o700});
 const db=new DatabaseSync(require('path').join(process.env.REWARDS_ROOT || process.cwd(),'sessions/sessions.db'),{readOnly:true});
 const row=db.prepare('SELECT storage_state FROM sessions WHERE email=? AND platform=?').get(process.env.ACCOUNT_1_EMAIL,'desktop');db.close();
 browser=await chromium.launch({headless:true,args:['--no-sandbox'],...(process.env.REWARDS_PROXY?{proxy:{server:process.env.REWARDS_PROXY,bypass:'r.bing.com'}}:{})});
 const c=await browser.newContext({storageState:JSON.parse(row.storage_state)});const p=await c.newPage();
 await p.goto('https://rewards.bing.com/dashboard',{waitUntil:'domcontentloaded',timeout:45000});
 if(!p.url().includes('/dashboard'))await p.goto('https://rewards.bing.com/auth/login?ru=%2Fdashboard',{waitUntil:'domcontentloaded',timeout:45000});
 const balanceLink=p.getByRole('link',{name:/^(Available points|可用积分)/i});await balanceLink.waitFor({timeout:20000});
 const pendingButton=p.getByRole('button',{name:/^(Ready to claim|可领取)/i});await pendingButton.waitFor({timeout:20000});
 const report={time:new Date().toISOString(),balance:await balanceLink.innerText(),pending:await pendingButton.innerText(),items:await p.locator('a,button,[role=button]').evaluateAll(xs=>xs.map(x=>({text:x.innerText.slice(0,200),href:x.getAttribute('href')})).filter(x=>x.text))};
 const n=s=>Number((s.match(/[\d,]+/)||['0'])[0].replaceAll(',',''));
 report.progressBars=await p.locator('[role=progressbar][aria-label]').evaluateAll(xs=>xs.map(x=>({label:x.getAttribute('aria-label'),current:Number(x.getAttribute('aria-valuenow')),max:Number(x.getAttribute('aria-valuemax'))})));
 const progress=pattern=>{const x=report.progressBars.find(x=>pattern.test(x.label));return x?{current:x.current,max:x.max}:null;};
 report.metrics={balance:n(report.balance),pending:n(report.pending),bing:progress(/^(Bing|必应)$/i),daily:progress(/^(Daily activit(?:y|ies)|Daily Set|每日活动)$/i),mobile:progress(/^(Mobile app|移动应用)$/i),edge:progress(/^(Microsoft Edge|Edge)$/i),visualSearch:progress(/^(Visual search|视觉搜索)$/i)};
 await p.goto('https://rewards.bing.com/earn',{waitUntil:'domcontentloaded',timeout:45000});await p.locator('main').waitFor({timeout:20000});await p.waitForTimeout(3000);report.earnItems=await p.locator('a,button,[role=button]').evaluateAll(xs=>xs.map(x=>({text:x.innerText.slice(0,500),href:x.getAttribute('href')})).filter(x=>x.text));report.earnText=await p.locator('body').innerText();const React=require(require('path').join(process.env.REWARDS_ROOT || process.cwd(),'dist/browser/ReactFunc')).default;const parsed=new React({logger:{info(){},warn(){},debug(){}},isMobile:false}).snapshotPage(await p.content());report.offers=parsed.offers.map(({offerId,title,points,isCompleted,isLocked,isPromotional,date,reportable,unlockCriteria})=>({offerId,title,points,isCompleted,isLocked,isPromotional,date,reportable,unlockCriteria}));fs.writeFileSync(require('path').join(process.env.REWARDS_EVIDENCE_DIR || './evidence','earn.html'),await p.content(),{mode:0o600});
 // Read fresh counters from the existing authenticated browser context, without recording account data.
 try {
  const response=await c.request.get('https://www.bing.com/rewards/panelflyout/getuserinfo?channel=BingFlyout&partnerId=BingRewards',{timeout:20000});
  const data=await response.json();
  if(!response.ok()||data.isError||!data.userInfo?.isRewardsUser||!data.flyoutResult?.userStatus?.isRewardsUser)throw Error('flyout_unavailable');
  const flyout=data.flyoutResult,counters=flyout.userStatus.counters||{};
  report.desktopSearch=(counters.PCSearch||counters.pcSearch||[]).map(x=>({current:x.pointProgress,max:x.pointProgressMax}));
  report.promotionMeta=[...(flyout.morePromotions||[]),...(flyout.highValueActionPromotions||[])].map(({offerId,priority,exclusiveLockedFeatureStatus})=>({offerId,priority,exclusiveLockedFeatureStatus}));
  report.exploreOnBing=(flyout.exploreOnBingPromotions||[]).map(x=>({offerId:x.offerId,title:x.title,current:x.pointProgress,max:x.pointProgressMax,complete:x.complete,locked:x.exclusiveLockedFeatureStatus!=='unlocked'}));
 }catch{report.counterReadError='fresh_flyout_unavailable';}
 fs.writeFileSync(require('path').join(process.env.REWARDS_EVIDENCE_DIR || './evidence',(process.env.SNAPSHOT_NAME||'snapshot')+'.json'),JSON.stringify(report,null,2),{mode:0o600});
 await p.screenshot({path:require('path').join(process.env.REWARDS_EVIDENCE_DIR || './evidence','snapshot.png')});console.log(JSON.stringify({balance:report.balance,pending:report.pending,items:report.items.length}));
 }catch(e){console.error(e.message.split('\n')[0]);process.exitCode=1;}finally{await browser?.close();}})();
