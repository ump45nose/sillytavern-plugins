const fs = require('fs');
const {DatabaseSync} = require('node:sqlite');
const {chromium} = require('/usr/src/microsoft-rewards-script/node_modules/patchright');
(async () => {
  const db = new DatabaseSync('/usr/src/microsoft-rewards-script/sessions/sessions.db', {readOnly:true});
  const row = db.prepare('SELECT storage_state FROM sessions WHERE email=? AND platform=?').get(process.env.ACCOUNT_1_EMAIL, 'desktop');
  db.close();
  const browser = await chromium.launch({headless:true,args:['--no-sandbox'],proxy:{server:'http://192.168.31.201:7890',bypass:'r.bing.com'}});
  try {
    const context = await browser.newContext({storageState:JSON.parse(row.storage_state)});
    const page = await context.newPage();
    await page.goto('https://rewards.bing.com/dashboard',{waitUntil:'domcontentloaded',timeout:45000});
    await page.getByRole('link',{name:/^(Available points|可用积分)/i}).waitFor({timeout:20000});
    await page.waitForTimeout(2000);
    const links = await page.locator('a,button').evaluateAll(xs=>xs.map((x,i)=>({i,text:x.innerText,href:x.getAttribute('href'),testid:x.getAttribute('data-testid'),html:x.outerHTML.slice(0,6000)})).filter(x=>/音乐|投票|极速问答|live music|Supersonic|Daily poll/.test(x.text)));
    fs.writeFileSync('/evidence/daily-links.json',JSON.stringify(links,null,2),{mode:0o600});
    console.log(JSON.stringify(links.map(({text,href,testid})=>({text,testid,route:href?new URL(href,page.url()).origin+new URL(href,page.url()).pathname:null}))));
    await page.screenshot({path:'/evidence/daily-before.png'});
    if (process.argv[2]) {
      const disclosure=page.getByRole('button',{name:/^(每日活动|Daily activities)$/i,exact:true});
      if(await disclosure.getAttribute('aria-expanded')==='false')await disclosure.click();
      const target = links[Number(process.argv[2])-1];
      if (!target) throw Error('Target missing');
      const popupPromise = page.waitForEvent('popup',{timeout:15000}).catch(()=>null);
      const card=page.locator('a').filter({hasText:target.text.split('\n')[0]});
      console.log('MATCHES',await card.count());
      await card.first().click({timeout:12000});
      const destination = await popupPromise || page;
      await destination.waitForLoadState('domcontentloaded').catch(()=>{});
      await destination.waitForTimeout(10000);
      const u = new URL(destination.url());
      console.log('DESTINATION',u.origin+u.pathname);
      const body = await destination.locator('body').innerText();
      console.log(body.slice(0,7000).replace(/[\w.+-]+@[\w.-]+/g,'[account]').replace(/\d{7,}/g,'[number]'));
      fs.writeFileSync('/evidence/daily-target.html',await destination.content(),{mode:0o600});
      await destination.screenshot({path:'/evidence/daily-target.png'});
      const verify = await context.newPage();
      await verify.goto('https://rewards.bing.com/dashboard',{waitUntil:'domcontentloaded',timeout:45000});
      await verify.waitForTimeout(4000);
      console.log('PROGRESS',await verify.locator('[role=progressbar]').evaluateAll(xs=>xs.map(x=>({label:x.getAttribute('aria-label'),current:x.getAttribute('aria-valuenow'),max:x.getAttribute('aria-valuemax')}))));
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e.name, String(e.message).slice(0,2200).replace(/https?:\/\/\S+/g,'[url]'));process.exitCode=1;});
