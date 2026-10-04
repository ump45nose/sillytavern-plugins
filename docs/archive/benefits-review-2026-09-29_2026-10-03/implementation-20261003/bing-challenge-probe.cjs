const root='/home/yuwk/benefits-automation/platforms/rewards';
const common=require(root+'/browser_common.cjs');
(async()=>{
 await common.withBrowser(common.dependency(root),common.readState(process.env.BENEFITS_STATE_DIR),
 {proxy:process.env.REWARDS_PROXY},async(ctx,page)=>{
  await page.goto('https://www.bing.com/',{waitUntil:'domcontentloaded',timeout:30000});
  await page.waitForTimeout(3000);
  console.log(JSON.stringify(await page.evaluate(()=>({path:location.pathname,title:document.title,
   frames:[...document.querySelectorAll('iframe')].map(x=>{try {const u=new URL(x.src);return {host:u.hostname,path:u.pathname};}catch{return {host:'empty'};}}),
   labels:[...document.querySelectorAll('button,input[type=checkbox],[role=checkbox]')].map(x=>x.innerText||x.getAttribute('aria-label')).filter(x=>/captcha|verify|验证|robot|human/i.test(x||'')),
   providers:['hcaptcha','turnstile','recaptcha','arkose','funcaptcha'].filter(x=>document.documentElement.outerHTML.toLowerCase().includes(x))
  }))))
 });
})().catch(()=>console.log('Challenge inspection unavailable; private transport details suppressed'));
