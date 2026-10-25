import fs from 'node:fs';
import {launch,session,ready,urls,createCharacter,openSettings,openResource} from './browser.mjs';
const dir='artifacts/design-fidelity';fs.mkdirSync(dir,{recursive:true});
const b=await launch();try {const {page,errors}=await session(b);await ready(page,urls.validation,{probe:true});await createCharacter(page);await page.evaluate(()=>workbench.host.preference({left:true}));
for (const [name,key] of [['用户设置','settings'],['回复格式','formatting'],['扩展','extensions'],['背景','background'],['用户设定','persona'],['角色管理','character'],['世界书','world'],['预设','generation'],['连接','connection']]){
 await openSettings(page,name);const ws=page.getByRole('dialog',{name:'独立设置工作区',exact:true});await ws.waitFor();await page.waitForTimeout(600);await page.screenshot({path:`${dir}/actual-${key}.png`});
 if(key==='extensions'){await ws.locator('.wb-settings-subnav').getByRole('button',{name:'扩展设置',exact:true}).click();await page.waitForTimeout(600);await page.screenshot({path:`${dir}/actual-extension-fields.png`});}
 if(key==='world'){await ws.getByRole('button',{name:'绑定与全局设置',exact:true}).click();await page.waitForTimeout(300);await page.screenshot({path:`${dir}/actual-world-bindings.png`});}
 if(key==='character'){await ws.locator('.wb-settings-subnav').getByRole('button',{name:'群组',exact:true}).click();await page.waitForTimeout(300);await page.screenshot({path:`${dir}/actual-groups.png`});}
 await page.getByRole('button',{name:'返回工作台',exact:true}).click();console.log(key);
}
for (const kind of ['preset','world','connection']) {await openResource(page,kind==='preset'?"预设":kind==='world'?"世界书":"连接");await page.waitForTimeout(400);await page.screenshot({path:`${dir}/actual-sidebar-${kind}.png`});await page.getByRole('button',{name:'关闭右栏',exact:true}).click();}
console.log('errors',errors);fs.writeFileSync(dir+'/capture-errors.json',JSON.stringify(errors));
}finally{await b.close();}
