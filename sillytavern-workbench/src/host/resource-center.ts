import type { Data } from './types';
export interface RpConnection { id:string; version:number; name:string; baseUrl:string; protocol:string; models:string[]; enabled:boolean; apply:string; key?:string|null }
export interface RpBinding { channelId:string; version:number; enabled:boolean; signature?:string }
export interface CenterLinkSettings { url:string; token:string; device:string; bindings:Record<string,RpBinding>; outbox:Array<{eventId:string; profileId:string; channelId:string; expectedVersion:number; patch:Data; current?:boolean}>; error?:string; lastAck?:string }
const randomId = () => [...crypto.getRandomValues(new Uint8Array(16))].map(x => x.toString(16).padStart(2,'0')).join('');
export const centerDefaults = ():CenterLinkSettings => ({url:'',token:'',device:randomId(),bindings:{},outbox:[]});
export function profileConnection(profile:Data, proxies:Data[]) {
  const protocol = profile.api === 'claude' ? 'Anthropic' : profile.api === 'makersuite' ? 'Gemini' : 'OpenAI';
  const baseUrl = protocol === 'OpenAI' ? profile['api-url'] : proxies.find(p => p.name === profile.proxy)?.url;
  if (!baseUrl || !/^https?:\/\//.test(baseUrl)) throw new Error('该原生连接尚无明确 API 地址，请先在酒馆保存地址');
  return {name:profile.name,baseUrl,protocol,models:[String(profile.model || '')].filter(Boolean)};
}
export class ResourceCenterLink {
  delivering = false;
  persisting = false;
  private saves:Promise<void> = Promise.resolve();
  connections:RpConnection[] = [];
  constructor(private settings:()=>CenterLinkSettings,private profiles:()=>Data[],private proxies:()=>Data[],private persist:()=>Promise<void>,private refresh:()=>void,private selected:()=>string) {}
  async request(path:string, body?:Data) {
    const s = this.settings();
    if (!s.url || !s.token) throw new Error('请先设置资源中心地址与 RP 凭据');
    const r = await fetch(s.url.replace(/\/$/,'')+'/api/v1/rp/'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',Authorization:'Bearer '+s.token},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(15000)});
    const result = await r.json();
    if (!r.ok) throw new Error(result.error || `资源中心 HTTP ${r.status}`);
    return result;
  }
  async saveSettings() {
    this.persisting = true;
    const run = this.saves.catch(()=>{}).then(()=>this.persist());
    this.saves = run;
    try { await run; } finally { if (this.saves === run) this.persisting = false; }
    this.refresh();
  }
  async read() {
    try { this.connections = await this.request('connections'); this.settings().error = undefined; }
    catch(e) { this.settings().error = e instanceof Error ? e.message : String(e); }
    this.refresh();
  }
  async queueSavedProfiles() {
    if (this.persisting) return;
    const s = this.settings();
    if (!s.url || !s.token) return;
    let changed = false;
    for (const [profileId,binding] of Object.entries(s.bindings)) {
      const profile = this.profiles().find(p=>p.id===profileId);
      if (!profile) continue;
      const patch = profileConnection(profile,this.proxies()), current = this.selected() === profileId;
      const signature = JSON.stringify([patch,current]);
      if (signature === binding.signature) continue;
      if (s.outbox.length >= 2000) throw new Error('RP 上报队列已满，请先处理同步错误；原生保存不受影响');
      // Each saved version is immutable, including while a request is in flight.
      s.outbox.push({eventId:randomId(),profileId,channelId:binding.channelId,expectedVersion:binding.version,patch,current});
      binding.signature = signature;
      changed = true;
    }
    if (changed) { await this.saveSettings(); await this.deliver(); }
  }
  async deliver() {
    if (this.delivering) return;
    this.delivering = true;
    const s = this.settings();
    try {
      while (s.outbox.length) {
        const event = s.outbox[0];
        const result = await this.request(event.channelId+'/saved',{...event,device:s.device});
        const binding = s.bindings[event.profileId];
        if (binding) binding.version = result.acceptedVersion;
        s.outbox = s.outbox.filter(x=>x.eventId!==event.eventId);
        for (const queued of s.outbox) if (queued.channelId===event.channelId && queued.expectedVersion===event.expectedVersion) queued.expectedVersion=result.acceptedVersion;
        s.lastAck = new Date().toISOString(); s.error = undefined;
        await this.saveSettings();
      }
    } catch(e) { s.error=e instanceof Error?e.message:String(e); await this.saveSettings(); }
    finally { this.delivering=false; this.refresh(); }
  }
}
