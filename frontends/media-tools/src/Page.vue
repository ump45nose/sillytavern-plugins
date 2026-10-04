<script setup>
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
const props=defineProps({api:Object,pluginId:{type:String,default:__PLUGIN_ID__},settingsOnly:Boolean})
const remux=computed(()=>props.pluginId==='DiscRemux')
const tab=ref(props.settingsOnly?'设置':'任务'),config=ref({}),jobs=ref([]),users=ref([])
const error=ref(''),notice=ref(''),busy=ref(false),directory=ref(''),entries=ref([]),roots=ref([])
const source=ref(''),kind=ref('movie'),title=ref(''),season=ref(1),episodeText=ref(''),runtime=ref(null)
const candidates=ref([]),selectedUnit=ref('')
const chosen=ref({}),mapped=ref({}),jsonFields=ref({}),loading=ref(false)
let timer
const labels={CHECKING:'待核实',SEED_WAIT:'保种等待',PREVIEW:'预览',PREPARING:'文件准备',
  UPLOADING:'上传',CLOUD_VERIFY:'云端校验',STRM_VERIFY:'STRM 校验',MIGRATING:'状态迁移',
  CLEANING:'等待清理',DONE:'已完成',ANALYZING:'原盘分析',MANUAL:'待人工选择',CONVERTING:'转换中',
  COMMITTING:'提交产物',FAILED:'失败'}
const unwrap=r=>r?.data??r
const base=()=>`plugin/${props.pluginId}/`
const get=async(path,params)=>unwrap(await(props.api||window.MoviePilotAPI).get(base()+path,params?{params}:undefined))
const post=async(path,data)=>unwrap(await(props.api||window.MoviePilotAPI).post(base()+path,data))
async function safe(fn){error.value='';loading.value=true;try{return await fn()}catch(e){error.value=e?.response?.data?.detail||e.message||'操作失败'}finally{loading.value=false}}
function hydrate(c){config.value=c;jsonFields.value={};for(const[k,v]of Object.entries(c))if(Array.isArray(v)||v&&typeof v==='object')jsonFields.value[k]=JSON.stringify(v,null,2)}
async function refresh(){const r=await get('jobs');jobs.value=Object.values(r.jobs||{}).reverse();busy.value=r.busy;if(r.error||r.scan_error)error.value=r.error||r.scan_error}
async function initialize(){const r=await get('settings');hydrate(r.config);if(r.error)error.value=r.error;await refresh()}
async function save(){const payload={...config.value};for(const[k,v]of Object.entries(jsonFields.value))payload[k]=JSON.parse(v);if(!remux.value)payload.users=config.value.users||[];const r=await post('settings',payload);hydrate(r.config);notice.value='设置已保存';if(r.error)error.value=r.error;await refresh()}
async function loadUsers(){const r=await get('users');users.value=r.users}
async function browse(path){const r=await get('browse',{directory:path});roots.value=r.roots;entries.value=r.items;directory.value=path||r.roots[0]}
async function loadCandidates(){const r=await get('candidates');candidates.value=r.units||[]}
async function runSelected(){if(!selectedUnit.value)throw Error('请选择收藏作品');await post('run',{backfill:true,unit_keys:[selectedUnit.value]});notice.value='已提交所选收藏作品';await refresh()}
async function run(backfill=false){await post('run',{backfill});notice.value=backfill?'已提交补处理':'已提交扫描';await refresh()}
async function submitDisc(){const episodes=episodeText.value.trim()?episodeText.value.split(',').map(e=>Number(e.trim())):[];if(episodes.some(e=>!Number.isInteger(e)||e<1))throw Error('集序请输入正整数，用英文逗号分隔');const r=await post('jobs',{source:source.value,kind:kind.value,title:title.value||undefined,season:kind.value==='tv'?season.value:null,episodes,runtime_seconds:runtime.value?runtime.value*60:null});notice.value=`已提交 ${r.job_id.slice(0,10)}`;tab.value='任务';await refresh()}
async function selectJob(job){const choices=job.titles.filter(t=>chosen.value[`${job.id}:${t.id}`]).map(t=>({id:t.id,episode:job.request.kind==='tv'?Number(mapped.value[`${job.id}:${t.id}`]):null}));await post('select',{job_id:job.id,choices});notice.value='已提交人工选择';await refresh()}
const settingsLabels={emby_url:'Emby 地址',emby_token_path:'Emby token 文件路径',cron:'每日任务 Cron',
  output_dir:'REMUX 产物保存目录',movie_path:'115 电影目录',tv_path:'115 剧集目录',strm_root:'STRM 保存目录',
  remux_output_dir:'归档允许读取的 REMUX 产物目录',makemkvcon:'MakeMKV 命令路径',ffprobe:'FFprobe 命令路径',
  timeout_seconds:'单标题转换超时（秒）',high_ratio:'高分享率保留阈值',high_days:'高分享率观察窗口（天）'}
const objectLabels={source_roots:'允许读取的媒体目录',path_mappings:remux.value?'下载器路径映射':'Emby 路径映射',
  downloader_path_mappings:'下载器路径映射',downloaders:'MoviePilot 下载器名称（空列表使用全部 qB）',
  seed_rule:'默认保种规则',site_rules:'站点保种规则覆盖'}
onMounted(()=>{safe(initialize);timer=setInterval(()=>{if(!props.settingsOnly&&document.visibilityState==='visible')refresh().catch(()=>{})},5000)})
onBeforeUnmount(()=>clearInterval(timer))
</script>

<template>
<main class="media-tools">
 <header><div><h2>{{remux?'原盘 REMUX':'媒体收藏归档'}}</h2><p>{{remux?'选择原盘，分析标题，生成无损 MKV。':'按收藏与保种条件归档，校验后迁移媒体状态并清理本地。'}}</p></div><span v-if="busy" role="status">后台处理中</span></header>
 <p v-if="error" class="error" role="alert">{{error}}</p><p v-if="notice" class="notice" role="status">{{notice}}</p>
 <nav v-if="!settingsOnly"><button v-for="name in remux?['选择原盘','任务','设置']:['任务','设置']" :key="name" :class="{active:tab===name}" @click="tab=name;if(name==='选择原盘')safe(()=>browse(directory))">{{name}}</button></nav>
 <section v-if="tab==='选择原盘'&&remux">
  <div class="actions"><button v-for="root in roots" :key="root" @click="safe(()=>browse(root))">{{root}}</button></div>
  <label>浏览目录<input v-model="directory"><button @click="safe(()=>browse(directory))">打开</button></label>
  <ul class="browser"><li v-for="entry in entries" :key="entry.path"><button v-if="entry.directory" @click="safe(()=>browse(entry.path))">📁 {{entry.name}}</button><span v-else>💿 {{entry.name}}</span><button v-if="entry.disc" @click="source=entry.path;title=entry.name.replace(/\.iso$/i,'')">选择原盘</button></li></ul>
  <div class="form-grid"><label>原盘路径<input v-model="source" placeholder="选择 ISO 或包含 BDMV 的目录"></label><label>作品名称<input v-model="title"></label><label>类型<select v-model="kind"><option value="movie">电影</option><option value="tv">剧集</option></select></label><label>参考时长（分钟，可选）<input v-model.number="runtime" type="number" min="1"></label><template v-if="kind==='tv'"><label>季数<input v-model.number="season" type="number" min="1"></label><label>目标集序<input v-model="episodeText" placeholder="1,2,3"></label></template></div>
  <button :disabled="loading||!source" @click="safe(submitDisc)">分析并自动 REMUX</button>
 </section>
 <section v-if="tab==='任务'">
  <div class="actions"><button :disabled="loading" @click="safe(refresh)">刷新</button><template v-if="!remux"><button :disabled="busy||loading" @click="safe(()=>run())">立即扫描</button><button :disabled="busy||loading" @click="safe(()=>run(true))">补处理现有收藏</button><a href="#/plugin-app/DiscRemux/main">打开原盘 REMUX</a></template></div>
  <div v-if="!remux" class="actions"><button :disabled="loading||busy" @click="safe(loadCandidates)">读取收藏作品</button><select v-model="selectedUnit" aria-label="选择收藏作品"><option value="">请选择作品</option><option v-for="unit in candidates" :key="unit.key" :value="unit.key">{{unit.title}}{{unit.season?` 第 ${unit.season} 季`:""}}</option></select><button :disabled="loading||busy||!selectedUnit" @click="safe(runSelected)">仅处理所选收藏</button></div>
  <p v-if="!jobs.length">暂无任务。请先完成设置并启用插件。</p>
  <article v-for="job in jobs" :key="job.id" class="job">
   <div class="job-header"><strong>{{job.unit?.title||job.request?.title||job.request?.source}}</strong><span>{{labels[job.stage]||job.stage}}</span></div>
   <p v-if="job.unit?.season">第 {{job.unit.season}} 季</p><p v-if="job.reason">{{job.reason}}</p><small>{{job.id.slice(0,12)}}</small>
   <progress v-if="remux&&job.stage==='CONVERTING'" :value="job.progress" max="100">{{job.progress}}%</progress>
   <details v-if="remux&&job.titles?.length" :open="job.stage==='MANUAL'"><summary>标题与人工选择</summary><p v-if="job.stage==='MANUAL'">请选择电影主片；剧集需为每个所选标题指定集序。</p><div class="table-scroll"><table><thead><tr><th>选择</th><th>标题</th><th>时长</th><th>章节</th><th>大小</th><th v-if="job.request.kind==='tv'">集序</th></tr></thead><tbody><tr v-for="item in job.titles" :key="item.id"><td><input v-model="chosen[`${job.id}:${item.id}`]" type="checkbox" :disabled="job.stage!=='MANUAL'" :aria-label="`选择标题${item.id}`"></td><td>{{item.id}} {{item.name}}<small>{{item.segments}}</small></td><td>{{(item.duration/60).toFixed(1)}} 分</td><td>{{item.chapters}}</td><td>{{(item.size/1024**3).toFixed(2)}} GiB</td><td v-if="job.request.kind==='tv'"><input v-model.number="mapped[`${job.id}:${item.id}`]" type="number" min="1" :disabled="job.stage!=='MANUAL'"></td></tr></tbody></table></div><button v-if="job.stage==='MANUAL'" :disabled="loading" @click="safe(()=>selectJob(job))">确认选择并继续</button></details>
   <ul v-if="job.outputs?.length"><li v-for="file in job.outputs" :key="file.path">{{file.path}}</li></ul>
   <button v-if="remux&&job.stage==='FAILED'" :disabled="loading" @click="safe(async()=>{await post('retry',{job_id:job.id});await refresh()})">重试当前阶段</button>
   <button v-if="remux&&['DONE','FAILED'].includes(job.stage)&&job.request.owner!=='MediaArchive'" :disabled="loading||busy" @click="safe(async()=>{await post('restart',{job_id:job.id});notice='已提交从原盘重新分析并转换';await refresh()})">重新分析并转换</button>
   <button v-if="!remux&&job.stage==='UPLOADING'&&job.reason" :disabled="loading||busy" @click="safe(async()=>{await post('retry_upload',{job_id:job.id});await refresh()})">云端对账后重试未确认上传</button>
   <details v-if="!remux"><summary>归档详情</summary><p v-if="job.retained?.length">保留做种：{{job.retained.join('、')}}</p><ul><li v-for="file in job.artifacts||[]" :key="file.path">{{file.path}}</li></ul></details>
  </article>
 </section>
 <section v-if="tab==='设置'">
  <div class="actions"><label><input v-model="config.enabled" type="checkbox">启用插件</label><template v-if="!remux"><label><input v-model="config.dry_run" type="checkbox">预览模式</label><label><input v-model="config.cleanup_enabled" type="checkbox">验证完成后清理本地</label><label><input v-model="config.backfill" type="checkbox">允许回溯历史收藏</label></template><label v-else><input v-model="config.delete_original" type="checkbox">验证产物且无做种/共享引用后删除原盘</label></div>
  <div class="form-grid"><label v-for="(label,key) in settingsLabels" v-show="key in config" :key="key">{{label}}<input v-model="config[key]" :type="typeof config[key]==='number'?'number':'text'"></label></div>
  <section v-if="!remux"><h3>收藏用户（可多选）</h3><button :disabled="loading" @click="safe(loadUsers)">读取已保存连接的 Emby 用户</button><label v-for="user in users" :key="user.id" class="user"><input v-model="config.users" type="checkbox" :value="user.id">{{user.name}}</label><p v-if="!users.length">已选择用户 ID：{{(config.users||[]).join('、')||'暂无'}}</p></section>
  <details><summary>目录、路径映射与保种规则</summary><div class="form-grid"><label v-for="(label,key) in objectLabels" v-show="key in jsonFields" :key="key">{{label}}<textarea v-model="jsonFields[key]" rows="5" spellcheck="false"></textarea></label></div></details>
  <button :disabled="loading||busy" @click="safe(save)">保存设置</button>
 </section>
</main>
</template>

<style scoped>
.media-tools{max-width:1150px;margin:auto;padding:24px;color:inherit;font:inherit}.media-tools header,.job-header,.actions,nav{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}h2{margin:0}header p{opacity:.7}nav,.actions{justify-content:flex-start;margin:18px 0}button,input,select,textarea{font:inherit;color:inherit}button,a{cursor:pointer}button{border:1px solid #8886;border-radius:7px;padding:8px 14px;background:transparent}.active{background:#4778d633}button:disabled{opacity:.5;cursor:default}label{display:block;margin:10px 0}input:not([type=checkbox]),select,textarea{display:block;width:100%;box-sizing:border-box;padding:8px;border:1px solid #8886;border-radius:5px;background:transparent}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px 24px}.error{color:#d44;background:#d441;padding:12px}.notice{padding:12px;background:#398a651a}.job{padding:18px;margin:14px 0;border:1px solid #8885;border-radius:10px}.job-header span{background:#4778d622;padding:4px 10px;border-radius:20px}small{display:block;opacity:.65;word-break:break-all}details{margin:15px 0}summary{cursor:pointer}.table-scroll{overflow:auto}table{width:100%;text-align:left;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #8884}td input[type=number]{min-width:70px}.browser{padding:0;list-style:none}.browser li{display:flex;gap:12px;align-items:center;padding:8px;border-bottom:1px solid #8884}.user{display:inline-block;margin-right:20px}progress{width:100%;margin:12px 0}li{overflow-wrap:anywhere}a{color:#588bd9}
</style>
