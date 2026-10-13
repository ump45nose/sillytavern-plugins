<script setup>
import {ref,computed,onMounted,onBeforeUnmount,nextTick,watch} from 'vue'
const props=defineProps({api:Object,pluginId:{type:String,default:'ThemeStudio'}})
const tab=ref('媒体库'), items=ref([]), jobs=ref([]), candidates=ref([]), selected=ref(null), filter=ref('全部'), text=ref(''), keyword=ref(''), link=ref(''), error=ref(''), notice=ref(''), asset=ref(null), paused=ref(false), adopt=ref(false), detail=ref([]), stats=ref({})
let timer
const currentUrl=ref(null),assetUrl=ref(null),currentPlayer=ref(null),assetPlayer=ref(null),applyingId=ref(null)
const manualFull=ref(null),manualCrop=ref({open:false,start:0,end:45})
const base=()=>`plugin/${props.pluginId}/studio/`
const unwrap=r=>r?.data??r
async function get(path,options){return unwrap(await (props.api||window.MoviePilotAPI).get(base()+path,options))}
async function post(path,body,options){return unwrap(await (props.api||window.MoviePilotAPI).post(base()+path,body,options))}
async function safe(fn){error.value='';try{return await fn()}catch(e){error.value=e?.response?.data?.detail||e.message||'操作失败'}}
const fallback=i=>['local_opening','smart_extract','intro_markers'].includes(i.source)
const visible=computed(()=>items.value.filter(i=>(!text.value||`${i.name} ${i.year}`.includes(text.value))&&(filter.value==='全部'||(filter.value==='已完成'?i.locked:filter.value==='兜底'?fallback(i):filter.value==='待升级'?fallback(i)&&!i.locked:filter.value==='失败'?i.status==='failed':!i.has_file&&!i.emby_visible))))
async function refresh(){const [m,j,s]=await Promise.all([get('media'),get('jobs'),get('status')]);items.value=m.items||[];jobs.value=j.jobs||[];paused.value=j.paused;stats.value=s}
async function task(kind,data={}){const r=await post('jobs',{kind,item_id:selected.value?.id,...data});notice.value=`任务已提交 ${r.job_id.slice(0,8)}`;return r.job_id}
const watched=new Map()
const page=ref(1)
const previews=ref({}), searchTitles=computed(()=>[selected.value?.name,selected.value?.original_title,...(selected.value?.aliases||[])].filter(Boolean))
const searchQueries=computed(()=>[...new Set(detail.value.map(d=>{try{return JSON.parse(d.evidence||'{}').query}catch{return null}}).filter(Boolean))])
const players=new Map()
function pauseOthers(active){for(const player of [...players.values(),currentPlayer.value,assetPlayer.value])if(player&&player!==active)player.pause()}
function clearPreviews(){for(const player of players.values())player.pause();players.clear();for(const p of Object.values(previews.value))if(p.url)URL.revokeObjectURL(p.url);previews.value={}}
async function audioBlob(path){const result=await get(path,{responseType:'blob'});if(!(result instanceof Blob)||!result.size||!result.type.startsWith('audio/'))throw Error('未取得可播放音频，请重试');return URL.createObjectURL(result)}
async function readyPreview(candidateId,result,itemId){
 const url=await audioBlob(`audio/${result.asset_id}`)
 if(selected.value?.id!==itemId){URL.revokeObjectURL(url);return}
 const previous=previews.value[candidateId];if(previous?.url)URL.revokeObjectURL(previous.url)
 previews.value[candidateId]={...previous,state:'ready',url,asset:result,error:'',applied:false,pending:false}
 if(result.mode==='full'){previews.value[candidateId].fullAsset=result;previews.value[candidateId].start=0;previews.value[candidateId].end=Math.floor(result.info.duration)}
 await nextTick();const player=players.get(candidateId);if(player){pauseOthers(player);try{await player.play()}catch{notice.value='试听已准备好，请点击结果卡片内的播放按钮'}}
}
async function previewCandidate(c){
 const id=c.candidate_id,itemId=selected.value.id,previous=previews.value[id]
 if(previous?.state==='loading')return
 if(previous?.url){const player=players.get(id);pauseOthers(player);await player?.play();return}
 previews.value[id]={state:'loading',error:''}
 try{
  const cached=jobs.value.find(j=>j.item_id===itemId&&j.kind==='prepare'&&j.status==='complete'&&(j.candidate_id===id||JSON.parse(j.result||'{}')?.source_hash===c.source_hash))
  const cachedAsset=cached?JSON.parse(cached.result):null
  if(cachedAsset?.mode==='full'){await readyPreview(id,cachedAsset,itemId);return}
  const jobId=await task('prepare',cachedAsset?{asset_id:cachedAsset.asset_id}:{candidate_id:id});watched.set(jobId,{kind:'prepare',item:itemId,candidate:id})
 }catch(e){previews.value[id]={state:'failed',error:e?.response?.data?.detail||e.message||'试听加载失败'}}
}
async function trimCandidate(c){
 const p=previews.value[c.candidate_id],start=Number(p.start),end=Number(p.end)
 if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end-start<1||end>p.fullAsset.info.duration){p.error='请输入曲目范围内的开始、结束时间（至少 1 秒）';return}
 p.state='loading';p.error=''
 try{const id=await task('trim',{asset_id:p.fullAsset.asset_id,basis:'prepared',start,end});watched.set(id,{kind:'trim',item:selected.value.id,candidate:c.candidate_id})}
 catch(e){p.state='ready';p.error=e.message||'裁剪失败'}
}
async function restoreFull(c){const p=previews.value[c.candidate_id];await readyPreview(c.candidate_id,p.fullAsset,selected.value.id);previews.value[c.candidate_id].cropOpen=false}
async function trimManual(){const {start,end}=manualCrop.value;if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end-start<1||end>manualFull.value.info.duration)throw Error('请输入曲目范围内的开始、结束时间（至少 1 秒）');await submit('trim',{asset_id:manualFull.value.asset_id,basis:'prepared',start,end})}
async function restoreManual(){asset.value=manualFull.value;manualCrop.value.open=false;await playAsset(asset.value.asset_id)}
watch(asset,value=>{if(value?.mode==='full'){manualFull.value=value;manualCrop.value={open:false,start:0,end:Math.floor(value.info.duration)}}else if(value?.mode==='extracted'){manualFull.value=null;manualCrop.value.open=false}})
async function applyCandidate(c){
 const preview=previews.value[c.candidate_id];if(!preview?.asset||applyingId.value)return
 if(preview.asset.expected_sha256&&!preview.asset.owned&&!preview.adopt){preview.error='请勾选接管现有主题后应用';return}
 preview.error='';preview.applying=true;applyingId.value=c.candidate_id
 try{const id=await task('apply',{asset_id:preview.asset.asset_id,adopt:!!preview.adopt});watched.set(id,{kind:'apply',item:selected.value.id,candidate:c.candidate_id})}
 catch(e){preview.applying=false;applyingId.value=null;preview.error=e.message||'应用失败'}
}
function audioError(id){const p=previews.value[id];if(p){p.state='failed';p.error='浏览器无法解码此试听音频，请重试或选择其他来源'}}
watch([text,filter],()=>page.value=1)
async function retry(j){const result=await post('retry',{job_id:j.id});watched.set(result.job_id,{kind:j.kind,item:j.item_id});await refresh()}
const pageItems=computed(()=>visible.value.slice((Math.min(page.value,Math.max(1,Math.ceil(visible.value.length/50)))-1)*50,Math.min(page.value,Math.max(1,Math.ceil(visible.value.length/50)))*50))
async function submit(kind,data={}){if(kind==='apply'){if(applyingId.value)return;applyingId.value='manual'}try{const id=await task(kind,data);watched.set(id,{kind,item:selected.value?.id})}catch(e){if(kind==='apply')applyingId.value=null;throw e}}
async function poll(){await safe(async()=>{const r=await get('jobs');jobs.value=r.jobs||[];paused.value=r.paused;for(const j of jobs.value){const w=watched.get(j.id);if(!w||!['complete','failed','interrupted'].includes(j.status))continue;watched.delete(j.id);if(w.kind==='apply')applyingId.value=null;if(w.item&&w.item!==selected.value?.id)continue;const preview=w.candidate?previews.value[w.candidate]:null;if(j.status!=='complete'){if(preview){preview.applying=false;preview.error=j.error||'操作失败，请重试';if(w.kind==='prepare')preview.state='failed';else preview.state='ready'}else error.value=`${w.kind}: ${j.error||j.status}`;continue}const result=JSON.parse(j.result||'{}');if(w.kind==='search'){clearPreviews();candidates.value=result.candidates||[];detail.value=result.diagnostics||[]}if(w.candidate&&['prepare','trim'].includes(w.kind)){try{await readyPreview(w.candidate,result,w.item)}catch(e){previews.value[w.candidate]={...preview,state:'failed',error:e.message}}}else if(['prepare','extract','trim'].includes(w.kind)){asset.value=result;await playAsset(result.asset_id)}if(['apply','register'].includes(w.kind)){notice.value=result.registered?'已应用，Emby 已识别并标记完成':'文件已生成，等待 Emby 注册';if(preview){preview.applying=false;preview.applied=!!result.registered;preview.pending=!result.registered}if(result.registered)selected.value.locked=true}await refresh()}})}
function clearAudio(){for(const url of [currentUrl.value,assetUrl.value])if(url)URL.revokeObjectURL(url);currentUrl.value=null;assetUrl.value=null}
async function choose(item){clearPreviews();clearAudio();selected.value=item;keyword.value='';asset.value=null;manualFull.value=null;manualCrop.value.open=false;candidates.value=[];adopt.value=false;tab.value='作品详情';detail.value=(await get(`diagnostics/${item.id}`)).diagnostics||[];const previous=jobs.value.find(j=>j.item_id===item.id&&j.kind==='search'&&j.status==='complete');if(previous)candidates.value=JSON.parse(previous.result||'{}')?.candidates||[]}
async function playAsset(id,current=false){const value=current?currentUrl:assetUrl;if(value.value)URL.revokeObjectURL(value.value);value.value=await audioBlob(`${current?'current':'audio'}/${id}`);await nextTick();const player=current?currentPlayer.value:assetPlayer.value;if(player){pauseOthers(player);try{await player.play()}catch{notice.value='音频已准备好，请点击播放'}}}
async function upload(event){const file=event.target.files[0];if(!file)return;if(file.size>32*1024*1024)throw Error('文件不能超过 32 MiB');const r=await post(`upload/${selected.value.id}`,file,{headers:{'Content-Type':'application/octet-stream'}});await submit('prepare',{asset_id:r.asset_id})}
async function fromLink(){const r=await post('source',{item_id:selected.value.id,url:link.value});await submit('prepare',{candidate_id:r.candidate_id});link.value=''}
async function lock(item){await post('lock',{item_id:item.id,locked:!item.locked});item.locked=!item.locked;await refresh()}
async function feedback(c,verdict){await post('feedback',{item_id:selected.value.id,candidate_hash:c.source_hash,verdict});notice.value='反馈已保存'}
function exportReport(){const data={item:selected.value,diagnostics:detail.value,candidates:candidates.value};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='theme-diagnostics.json';a.click();URL.revokeObjectURL(url)}
onMounted(()=>{safe(refresh);timer=setInterval(poll,2500)})
onBeforeUnmount(()=>{clearInterval(timer);clearPreviews();clearAudio()})
</script>
<template>
<main class="theme-studio">
 <header><div><h2>主题曲管理</h2><p>自动检索 · 智能兜底 · 人工完成锁定</p></div><button @click="safe(()=>submit('sync'))">同步媒体库</button></header>
 <nav><button v-for="name in ['媒体库','作品详情','任务队列','调优']" :key="name" :class="{active:tab===name}" @click="tab=name">{{name}}</button></nav>
 <p v-if="error" role="alert" class="error">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
 <section v-show="tab==='媒体库'"><div class="tools"><input v-model="text" placeholder="搜索片名 / 年份"><select v-model="filter"><option v-for="f in ['全部','兜底','待升级','缺失','失败','已完成']">{{f}}</option></select><span>{{visible.length}} 项</span></div>
 <table><thead><tr><th>作品</th><th>来源 / 质量</th><th>执行状态</th><th>用户完成</th></tr></thead><tbody><tr v-for="i in pageItems" :key="i.id"><td><button @click="safe(()=>choose(i))">{{i.name}} · {{i.year}}</button><small>{{i.type}} · {{i.id}}</small></td><td>{{i.source||'未管理'}}<small>{{i.quality||'待评估'}}</small></td><td>{{i.status||'未处理'}}<small>{{i.emby_visible==null?'Emby 索引待同步':i.emby_visible?'Emby 已收录':'Emby 未收录'}}</small></td><td><button @click="safe(()=>lock(i))">{{i.locked?'已完成 · 解除':'标记完成'}}</button></td></tr></tbody></table><div class="tools"><button :disabled="page<=1" @click="page--">上一页</button><span>{{Math.min(page,Math.max(1,Math.ceil(visible.length/50)))}} / {{Math.max(1,Math.ceil(visible.length/50))}}</span><button :disabled="page*50>=visible.length" @click="page++">下一页</button></div></section>
 <section v-show="tab==='作品详情'"><p v-if="!selected">请先选择作品。</p><template v-else><h3>{{selected.name}} · {{selected.year}}</h3><div class="tools"><button @click="safe(()=>playAsset(selected.id,true))">试听当前主题</button><button @click="safe(()=>submit('extract'))">生成本地提取预览</button><button @click="safe(()=>lock(selected))">{{selected.locked?'解除完成锁定':'标记处理完成'}}</button><button @click="safe(()=>submit('register'))">重新注册至 Emby</button></div>
 <audio v-if="currentUrl" ref="currentPlayer" :src="currentUrl" controls @play="e=>pauseOthers(e.target)"></audio>
 <div class="tools"><input v-model="keyword" placeholder="检索关键词"><button @click="safe(()=>submit('search',{keyword}))">检索候选</button></div>
 <details><summary>检索名称与已执行的查询词</summary><p>名称：{{searchTitles.join(' / ')}}</p><p v-if="!selected.aliases?.length">媒体元数据未提供额外别名；原名并不一定是英文名。</p><ul><li v-for="q in searchQueries" :key="q">{{q}}</li></ul><p>每个搜索来源最多 4 条查询、每条最多 10 个结果；查询记录包含历史检索。</p></details>
 <div class="tools"><input v-model="link" placeholder="YouTube / B站 / 网易云 / QQ 单曲链接"><button @click="safe(fromLink)">准备链接音频</button><label>上传音频<input type="file" accept="audio/*" @change="e=>safe(()=>upload(e))"></label></div>
 <div v-if="asset" class="apply"><p>{{asset.mode==='full'?'完整曲目':asset.mode==='trimmed'?'裁剪片段':'本地提取片段'}} · {{asset.info?.duration?.toFixed(2)}} 秒</p><audio v-if="assetUrl" ref="assetPlayer" :src="assetUrl" controls @play="e=>pauseOthers(e.target)"></audio><label v-if="asset.expected_sha256&&!asset.owned"><input v-model="adopt" type="checkbox">备份并接管现有主题</label><button :disabled="!!applyingId" @click="safe(()=>submit('apply',{asset_id:asset.asset_id,adopt}))">{{asset.mode==='full'?'应用完整曲目':asset.mode==='trimmed'?'应用裁剪片段':'应用本地片段'}}</button><button v-if="manualFull" :aria-expanded="manualCrop.open" @click="manualCrop.open=!manualCrop.open">裁剪（可选）</button><div v-if="manualFull&&manualCrop.open" class="tools"><label>开始（秒）<input v-model.number="manualCrop.start" type="number" min="0" step="0.1"></label><label>结束（秒）<input v-model.number="manualCrop.end" type="number" min="1" step="0.1" :max="manualFull.info.duration"></label><button :disabled="!!applyingId" @click="safe(trimManual)">生成裁剪试听</button><button :disabled="!!applyingId" @click="safe(restoreManual)">恢复完整曲目</button></div></div>
 <article v-for="c in candidates" :key="c.candidate_id" :data-candidate-id="c.candidate_id"><strong>{{c.title}}</strong><p>{{c.provider}} · {{c.score}} 分 · {{c.duration??'未知'}} 秒</p><div class="tools"><button :disabled="previews[c.candidate_id]?.state==='loading'" @click="previewCandidate(c)">{{previews[c.candidate_id]?.state==='loading'?'正在准备试听…':previews[c.candidate_id]?.state==='failed'?'重试试听':'试听'}}</button><button :disabled="!previews[c.candidate_id]?.asset||previews[c.candidate_id]?.state==='loading'||!!applyingId||previews[c.candidate_id]?.applied||previews[c.candidate_id]?.pending" @click="applyCandidate(c)">{{previews[c.candidate_id]?.applying?'正在应用…':previews[c.candidate_id]?.applied?'已应用 · 已完成':previews[c.candidate_id]?.pending?'等待 Emby 识别':previews[c.candidate_id]?.asset?.mode==='trimmed'?'应用裁剪片段':'应用完整曲目'}}</button><button v-if="previews[c.candidate_id]?.fullAsset" :aria-expanded="!!previews[c.candidate_id].cropOpen" @click="previews[c.candidate_id].cropOpen=!previews[c.candidate_id].cropOpen">裁剪（可选）</button></div><div v-if="previews[c.candidate_id]?.cropOpen" class="tools"><label>开始（秒）<input v-model.number="previews[c.candidate_id].start" type="number" min="0" step="0.1"></label><label>结束（秒）<input v-model.number="previews[c.candidate_id].end" type="number" min="1" step="0.1" :max="previews[c.candidate_id].fullAsset.info.duration"></label><button :disabled="previews[c.candidate_id].state==='loading'||!!applyingId" @click="trimCandidate(c)">生成裁剪试听</button><button :disabled="previews[c.candidate_id].state==='loading'||!!applyingId" @click="safe(()=>restoreFull(c))">恢复完整曲目</button></div><p v-if="previews[c.candidate_id]?.asset">当前应用：{{previews[c.candidate_id].asset.mode==='trimmed'?'裁剪片段':'完整曲目'}} · {{previews[c.candidate_id].asset.info.duration.toFixed(2)}} 秒</p><p v-if="previews[c.candidate_id]?.state==='loading'" role="status">正在处理音频。</p><p v-if="previews[c.candidate_id]?.error" class="error" role="alert">{{previews[c.candidate_id].error}}</p><audio v-if="previews[c.candidate_id]?.url" :ref="el=>el?players.set(c.candidate_id,el):players.delete(c.candidate_id)" :src="previews[c.candidate_id].url" controls preload="metadata" @play="e=>pauseOthers(e.target)" @error="audioError(c.candidate_id)"></audio><label v-if="previews[c.candidate_id]?.asset?.expected_sha256&&!previews[c.candidate_id]?.asset?.owned"><input v-model="previews[c.candidate_id].adopt" type="checkbox">备份并接管现有主题</label><details><summary>反馈与匹配详情</summary><div class="tools"><button @click="safe(()=>feedback(c,'correct'))">正确</button><button @click="safe(()=>feedback(c,'wrong'))">错误</button><button @click="safe(()=>feedback(c,'preferred'))">更喜欢这个版本</button></div><pre>{{JSON.stringify(c.evidence,null,2)}}</pre></details></article>
 </template></section>
 <section v-show="tab==='任务队列'"><button @click="safe(async()=>{await post('pause',{paused:!paused});await refresh()})">{{paused?'恢复队列':'暂停队列（当前项完成后）'}}</button><table><thead><tr><th>任务</th><th>作品</th><th>状态</th><th>错误 / 重试</th></tr></thead><tbody><tr v-for="j in jobs" :key="j.id"><td>{{j.kind}}<small>{{j.id.slice(0,8)}}</small></td><td>{{j.item_id}}</td><td>{{j.status}}</td><td>{{j.error}}<button v-if="['failed','interrupted'].includes(j.status)&&!['apply','auto','upgrade'].includes(j.kind)" @click="safe(()=>retry(j))">重试</button></td></tr></tbody></table></section>
 <section v-show="tab==='调优'"><p>请选择作品检索后试听，标记候选正确、错误或偏好。文件生成和用户认可分别统计。</p><button @click="exportReport">导出当前作品脱敏诊断</button><details open><summary>来源与失败统计</summary><pre>{{JSON.stringify(stats,null,2)}}</pre></details><pre>{{JSON.stringify(detail,null,2)}}</pre></section>
</main>
</template>
<style scoped>
.theme-studio{padding:24px;max-width:1400px;margin:auto;color:inherit}.theme-studio header,.tools,nav{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.theme-studio header{justify-content:space-between}.theme-studio nav{margin:20px 0;border-bottom:1px solid #64748b}.theme-studio button{padding:8px 12px;border:1px solid #64748b;border-radius:6px;cursor:pointer;background:transparent;color:inherit}.theme-studio button.active,.apply button{background:#166534;color:white}.theme-studio button:disabled{opacity:.4;cursor:default}.theme-studio input,.theme-studio select{padding:8px;border:1px solid #64748b;border-radius:4px;color:inherit;background:transparent}.theme-studio input[type=number]{width:100px}.theme-studio table{width:100%;border-collapse:collapse;margin-top:16px}.theme-studio th,.theme-studio td{padding:12px;text-align:left;border-bottom:1px solid #64748b55}.theme-studio small{display:block;opacity:.7}.theme-studio article,.apply{padding:16px;margin:12px 0;border:1px solid #64748b55;border-radius:8px}.theme-studio pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.theme-studio .error{color:#ef4444}.theme-studio .wave{margin:20px 0;min-height:90px}.theme-studio .tools{margin:12px 0}
</style>
