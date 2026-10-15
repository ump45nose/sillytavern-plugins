import {ResourceCenterLink,centerDefaults,profileConnection} from './host/resource-center';
import {applyNativeConnection,activateSavedConnection} from './host/resource-center-native';
import type {Data} from './host/types';
const load=(path:string):Promise<any>=>import(/* @vite-ignore */ path);
const ctx=()=>window.SillyTavern.getContext();
const openai=await load('/scripts/openai.js');
const script=await load('/script.js');
const settings=()=>{const c=ctx();c.extensionSettings.aiResourceCenter??=centerDefaults();return c.extensionSettings.aiResourceCenter;};
const profiles=()=>ctx().extensionSettings.connectionManager?.profiles||[];
const selected=()=>ctx().extensionSettings.connectionManager?.selectedProfile||'';
let generating=false;
const persist=async()=>{let confirmed=false;const c=ctx(),event=c.eventTypes.SETTINGS_UPDATED;const done=()=>{confirmed=true;};c.eventSource.on(event,done);try{await script.saveSettings();if(!confirmed)throw new Error('原生设置保存未确认');}finally{c.eventSource.removeListener(event,done);}};
const panel=document.createElement('div');panel.className='inline-drawer';panel.id='ai-resource-center-rp';
panel.innerHTML='<div class="inline-drawer-toggle inline-drawer-header"><b>AI 资源中心 · RP</b><div class="inline-drawer-icon fa-solid fa-circle-chevron-down down"></div></div><div class="inline-drawer-content"><label>中心地址<input data-field="url" class="text_pole" placeholder="http://192.168.31.201:18321"></label><label>限定 RP 连接的凭据<input data-field="token" type="password" class="text_pole" autocomplete="off"></label><button data-action="configure" class="menu_button">保存并读取</button><button data-action="read" class="menu_button">读取中心</button><div data-state style="white-space:pre-wrap;overflow-wrap:anywhere"></div><label>绑定当前酒馆连接<select data-channels class="text_pole"></select></label><button data-action="bind" class="menu_button">关联当前连接</button><button data-action="apply" class="menu_button">应用中心配置到原生连接</button><button data-action="send" class="menu_button">上报酒馆已保存配置</button><button data-action="retry" class="menu_button">重交保存结果</button><div data-error style="color:#f58a86;white-space:pre-wrap"></div><small>禁测活。保存、排序和同步只访问中心与酒馆原生设置。暂停从下一次生成生效。冲突在中心选择两侧配置。</small></div>';
const container=document.querySelector('#extensions_settings2')||document.querySelector('#extensions_settings');
if(!container)throw new Error('缺少酒馆扩展设置入口');container.append(panel);
const field=(name:string)=>panel.querySelector<HTMLInputElement>(`[data-field="${name}"]`)!;
field('url').value=settings().url;field('token').value=settings().token;
const connectionSelect=panel.querySelector<HTMLSelectElement>('[data-channels]')!;
const refresh=()=>{
  const s=settings(),profile=profiles().find((p:Data)=>p.id===selected()),binding=s.bindings[selected()],remote=link.connections.find(c=>c.id===binding?.channelId);
  panel.querySelector('[data-state]')!.textContent=`当前：${profile?.name||'未选择原生连接'}\n${binding?`酒馆 v${binding.version} · ${binding.enabled?'启用':'暂停'} · 禁测活`:'尚未绑定'}${remote?`\n中心 v${remote.version}：${remote.baseUrl} · ${remote.models.join(', ')}`:''}\n待交保存 ${s.outbox.length} 条 · 最近确认 ${s.lastAck||'无'}`;
  panel.querySelector('[data-error]')!.textContent=s.error||'';
  const value=connectionSelect.value;connectionSelect.replaceChildren(new Option('请选择',''),...link.connections.map(c=>new Option(`${c.name} · ${c.baseUrl}`,c.id)));connectionSelect.value=value;
};
const link=new ResourceCenterLink(settings,profiles,()=>openai.proxies,persist,refresh,selected);
const apply=async()=>{
  if(generating||ctx().streamingProcessor)throw new Error('请在当前生成结束后应用');
  const id=selected(),s=settings(),binding=s.bindings[id],current=profiles().find((p:Data)=>p.id===id);
  if(!binding||!current)throw new Error('请先绑定当前原生连接');
  const remote=await link.request(binding.channelId+'/config');
  const patch=await applyNativeConnection(current,remote,ctx(),openai);
  await activateSavedConnection(patch,ctx(),openai);
  Object.assign(current,patch);binding.version=remote.version;binding.enabled=remote.enabled;binding.signature=undefined;
  s.outbox=s.outbox.filter((e:any)=>e.profileId!==id);
  const option=document.querySelector<HTMLOptionElement>(`#connection_profiles option[value="${CSS.escape(id)}"]`);if(option)option.textContent=patch.name;
  await persist();await link.queueSavedProfiles();await link.read();
};
let busy=false;
panel.addEventListener('click',async(event)=>{
  const button=(event.target as Element).closest<HTMLButtonElement>('button[data-action]');if(!button||busy)return;
  busy=true;panel.querySelectorAll<HTMLButtonElement>("button[data-action]").forEach(b=>b.disabled=true);
  try{
    const s=settings();
    if(button.dataset.action==='configure'){s.url=field('url').value.trim();s.token=field('token').value.trim();await link.saveSettings();await link.read();}
    if(button.dataset.action==='read')await link.read();
    if(button.dataset.action==='bind'){
      const profile=profiles().find((p:Data)=>p.id===selected()),remote=link.connections.find(c=>c.id===connectionSelect.value);
      if(!profile||!remote)throw new Error('请选择原生连接和中心 RP 连接');
      s.bindings[profile.id]={channelId:remote.id,version:remote.version,enabled:remote.enabled,signature:JSON.stringify([profileConnection(profile,openai.proxies),true])};await link.saveSettings();
    }
    if(button.dataset.action==='apply')await apply();
    if(button.dataset.action==='send'){const b=s.bindings[selected()];if(!b)throw new Error('尚未绑定');b.signature=undefined;await link.queueSavedProfiles();}
    if(button.dataset.action==='retry')await link.deliver();
  }catch(e){settings().error=e instanceof Error?e.message:String(e);}finally{busy=false;panel.querySelectorAll<HTMLButtonElement>("button[data-action]").forEach(b=>b.disabled=false);refresh();}
});
const c=ctx();
c.eventSource.on(c.eventTypes.SETTINGS_UPDATED,()=>{if(!link.persisting)void link.queueSavedProfiles().catch(e=>{settings().error=String(e);refresh();});});
c.eventSource.on(c.eventTypes.GENERATION_STARTED,(_type:any,_options:any,dry:boolean)=>{if(!dry)generating=true;});
for(const name of ['GENERATION_ENDED','GENERATION_STOPPED'])c.eventSource.on(c.eventTypes[name],()=>{generating=false;});
c.eventSource.on(c.eventTypes.CONNECTION_PROFILE_LOADED,()=>{refresh();});
window.addEventListener('online',()=>void link.deliver());
(globalThis as any).aiResourceCenterRpGuard=(_chat:any,_size:any,abort:(immediately:boolean)=>void)=>{
  if(settings().bindings[selected()]?.enabled===false){abort(true);generating=false;settings().error='当前 RP 连接已暂停，请在资源中心恢复或选择其他连接';refresh();}
};
refresh();if(settings().url)void link.deliver();
