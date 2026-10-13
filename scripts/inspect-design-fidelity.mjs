import fs from 'node:fs';
import {launch,session,ready,urls} from './browser.mjs';
const dir='artifacts/design-fidelity';fs.mkdirSync(dir,{recursive:true});
const b=await launch();try {const {page}=await session(b);await ready(page,urls.validation,{probe:true});
for(const [name,id] of [['settings','user-settings-block'],['world','WorldInfo'],['background','Backgrounds'],['extensions','rm_extensions_block']]) {const html=await page.locator('#'+id).evaluate(n=>n.outerHTML);fs.writeFileSync(dir+'/'+name+'-structure.html',html.replace(/value="[^"]*"/g,'value=""'));}
await page.getByRole('button',{name:'用户设置',exact:true}).first().click();await page.waitForTimeout(400);await page.screenshot({path:dir+'/before-settings.png'});
const p=await b.newPage({viewport:{width:1440,height:900}});await p.goto('file://'+process.cwd()+'/docs/design/novel-desktop/rework/settings-workspace.html');await p.screenshot({path:dir+'/approved-settings.png'});
}finally {await b.close();}
