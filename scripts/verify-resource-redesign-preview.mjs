import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {launch} from './browser.mjs';
const dir='artifacts/resource-redesign-preview';fs.mkdirSync(dir,{recursive:true});
const browser=await launch(),checks=[],errors=[];const pass=n=>{checks.push(n);console.log('PASS',n);};
try {
  const page=await browser.newPage({viewport:{width:736,height:1040}});page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file://'+path.resolve('docs/design/novel-desktop/rework/resources-redesign.html'));
  const f=page.frameLocator('iframe');await f.locator('#noval-resource-redesign .nr-title').waitFor();await page.waitForTimeout(500);
  const actions=f.locator('.nr-header-actions');assert.deepEqual(await actions.locator('button').allTextContents(),['新建','记录','删除']);
  assert(await f.getByRole('textbox',{name:'服务地址',exact:true}).isVisible());assert(await f.getByRole('textbox',{name:'API 密钥',exact:true}).isVisible());
  await f.getByRole('combobox',{name:'服务商',exact:true}).click();await f.getByRole('option',{name:'Anthropic',exact:true}).click();assert.equal(await f.getByRole('textbox',{name:'服务地址',exact:true}).inputValue(),'https://api.anthropic.com');
  await f.getByRole('combobox',{name:'服务商',exact:true}).click();await f.getByRole('option',{name:'OpenRouter',exact:true}).click();await f.getByRole('button',{name:'测试',exact:true}).click();assert.equal(await f.locator('.nr-connect-status').textContent(),'预览 · 未发送请求');
  await page.screenshot({path:dir+'/connection.png'});pass('connection API first, three header actions and provider selection');
  await f.getByRole('button',{name:'预设',exact:true}).click();assert.equal(await f.locator('.nr-prompt-row').count(),8);
  await f.getByRole('combobox',{name:'选择预设',exact:true}).click();await f.getByRole('option',{name:'对白 · 克制',exact:true}).click();assert.equal(await f.locator('.nr-title > span').textContent(),'对白 · 克制');
  await f.getByRole('combobox',{name:'选择预设',exact:true}).click();await page.waitForTimeout(200);await page.screenshot({path:dir+'/preset-picker.png'});await page.keyboard.press('Escape');
  const width=await f.getByRole('spinbutton',{name:'温度',exact:true}).evaluate(e=>e.getBoundingClientRect().width);assert(width<80);
  const layout=await f.locator('.nr-panel').evaluate(e=>{const prompt=e.querySelector('.nr-prompts').getBoundingClientRect();const common=e.querySelector('.nr-common').getBoundingClientRect();const editor=e.querySelector('.nr-prompt-editor').getBoundingClientRect();const footer=e.querySelector('.nr-footer').getBoundingClientRect();return {prompt:prompt.height,common:common.height,editor:editor.height,editorBottom:editor.bottom,footerTop:footer.top};});
  assert(layout.prompt>layout.common);assert(layout.prompt>layout.editor);assert(layout.editorBottom<=layout.footerTop);
  await f.getByRole('checkbox',{name:'启用 Main Prompt',exact:true}).uncheck();assert.equal(await f.locator('.nr-prompt-row.is-off').count(),2);
  await f.getByRole('textbox',{name:'提示词正文',exact:true}).fill('保留 **Markdown** <story>{{user}}</story>');await f.getByRole('textbox',{name:'提示词名称',exact:true}).fill('叙事规则');
  await f.getByRole('button',{name:'保存',exact:true}).click();assert.equal(await f.getByRole('status').textContent(),'已保存 · 预览');
  await page.screenshot({path:dir+'/preset.png'});pass('preset title picker, compact numeric controls and dominant full-width prompt list');
  await f.getByRole('button',{name:'配置常用项',exact:true}).click();await f.getByRole('checkbox',{name:'Top P',exact:true}).check();assert(await f.getByRole('spinbutton',{name:'Top P',exact:true}).isVisible());await f.getByRole('button',{name:'配置常用项',exact:true}).click();
  await f.getByRole('button',{name:'新增提示词',exact:true}).click();assert.equal(await f.locator('.nr-prompt-row').count(),9);await f.getByRole('textbox',{name:'提示词名称',exact:true}).fill('新增规则');await f.getByRole('textbox',{name:'提示词正文',exact:true}).fill('<rules>示例</rules>');await f.getByRole('button',{name:'上移提示词',exact:true}).click();assert.equal(await f.locator('.nr-prompt-row.is-selected').innerText(),'新增规则\nsystem');
  pass('prompt raw editing, flags, add/reorder and common parameter configuration');
  await f.getByRole('button',{name:'用户设定',exact:true}).click();await f.getByRole('combobox',{name:'选择用户设定',exact:true}).click();await f.getByRole('option',{name:'作者视角',exact:true}).click();assert.equal(await f.getByRole('textbox',{name:'用户名称',exact:true}).inputValue(),'作者视角');
  for(const label of ['用户描述','深度','注入位置','绑定世界书'])assert(await f.getByLabel(label,{exact:true}).count());
  await f.getByRole('checkbox',{name:'锁定当前角色',exact:true}).check();await f.getByRole('button',{name:'保存',exact:true}).click();await f.locator('.nr-content').evaluate(e=>e.scrollTop=0);await page.waitForTimeout(200);await page.screenshot({path:dir+'/persona.png'});pass('Persona title chooser, description, injection and locks in one surface');
  for(const width of [320,460,736]){await page.setViewportSize({width,height:1100});for(const kind of ['连接','预设','用户设定']){await f.getByRole('button',{name:kind,exact:true}).click();const fits=await f.locator('.nr-panel').evaluate(e=>e.scrollWidth<=e.clientWidth+1);assert(fits,kind+' '+width);const footer=await f.locator('.nr-footer').boundingBox();assert(footer.width>0);}}
  pass('three panels fit narrow and normal preview widths');assert.deepEqual(errors,[]);fs.writeFileSync(dir+'/verification.json',JSON.stringify({checks,errors},null,2));
} catch(e){console.error(e);process.exitCode=1;}finally{await browser.close();}
