<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const title = ref(new URLSearchParams(location.search).get('q') || '')
const year = ref(''), mediaType = ref(''), scope = ref('season'), season = ref(1), episode = ref(1)
const policy = ref('quality'), token = ref(''), connected = ref(false), checking = ref(true)
const session = ref(null), error = ref(''), busy = ref(false), downloading = ref(false)
const sourceFilter = ref(''), resolution = ref(''), receipts = ref([])
let searchVersion = 0, searchTimer, taskTimer, lastRequest
const profiles = [
  { id: 'quality', title: '质量优先', text: '优先 Remux 与高质量片源', icon: '◇' },
  { id: 'subtitle', title: '字幕优先', text: '先找明确标注中文字幕的资源', icon: '文' },
  { id: 'balanced', title: '均衡下载', text: '体积适中的 4K，必要时回退 1080p', icon: '≋' },
]
const names = { mteam: 'M-Team', mini4k: 'Mini4K' }
const labels = { pending: '处理中', submitted: '已接收', completed: '下载完成', failed: '失败',
  no_match: '没有合适资源', needs_selection: '请选择作品', unavailable: '服务不可用', invalid_request: '请检查输入',
  OK: '已完成', NO_RESULTS: '暂无结果', UNAVAILABLE: '暂不可用', AUTH_REQUIRED: '需要登录',
  CF_CHALLENGE: '访问验证阻挡', PARSE_CHANGED: '页面解析失败', complete: '查询完成' }
const candidates = computed(() => (session.value?.candidates || []).filter(c =>
  (!sourceFilter.value || c.source_id === sourceFilter.value) &&
  (!resolution.value || c.title.toLowerCase().includes(resolution.value))))
const hasMedia = computed(() => !!session.value?.media)
const isTV = computed(() => mediaType.value === 'tv')
const size = bytes => bytes ? `${(bytes / 1024 ** 3).toFixed(1)} GiB` : '体积待核实'
const subtitleLabel = s => !s?.chinese ? '字幕未知' :
  ({ sidecar: '含中文字幕文件', mediainfo: 'MediaInfo 声明中字', source_claim: '标注中文字幕' }[s.kind] || '中文字幕')

async function api(path, method = 'GET', body) {
  const response = await fetch(path, { method, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-Media-Request': '1' },
    ...(body ? { body: JSON.stringify(body) } : {}) })
  const data = await response.json()
  if (response.status === 401) connected.value = false
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入')
  return data
}

function request() {
  const value = title.value.trim()
  if (!value) throw new Error('请输入作品名称或 IMDb ID')
  const body = { scope: scope.value, season: Number(season.value), policy: policy.value }
  if (/^tt\d+$/.test(value)) body.imdb_id = value
  else body.title = value
  if (mediaType.value) body.media_type = mediaType.value
  if (year.value) body.year = Number(year.value)
  if (scope.value === 'episode') body.episode = Number(episode.value)
  return body
}

async function login() {
  error.value = ''
  try {
    await api('/api/session', 'POST', { token: token.value })
    token.value = ''
    connected.value = true
    if (title.value.trim()) await search()
  } catch (e) { error.value = e.message }
}

async function search(selected) {
  error.value = ''; busy.value = true
  clearInterval(searchTimer)
  const version = ++searchVersion
  session.value = null
  try {
    lastRequest = selected ? { ...request(), title: '', year: selected.year || undefined,
      media_type: selected.media_type, ...(selected.tmdb_id ? { tmdb_id: selected.tmdb_id } : { imdb_id: selected.imdb_id }) } : request()
    const result = await api('/api/search', 'POST', lastRequest)
    if (version !== searchVersion) return
    session.value = result
    if (result.reason) error.value = result.reason
    if (result.status === 'pending') searchTimer = setInterval(() => pollSearch(version), 1000)
    else busy.value = false
    const url = new URL(location.href); url.searchParams.set('q', title.value.trim())
    history.replaceState(null, '', url)
  } catch (e) { if (version === searchVersion) { error.value = e.message; busy.value = false } }
}

async function pollSearch(version) {
  try {
    const id = session.value?.session_id
    if (!id) return
    const result = await api(`/api/search/${id}`)
    if (version !== searchVersion) return
    session.value = result
    if (result.status !== 'pending') { clearInterval(searchTimer); busy.value = false }
    if (result.reason) error.value = result.reason
  } catch (e) { error.value = e.message; clearInterval(searchTimer); busy.value = false }
}

async function more(source) {
  error.value = ''
  try {
    session.value = await api(`/api/search/${session.value.session_id}/more`, 'POST', { source_id: source })
    busy.value = true
    clearInterval(searchTimer)
    searchTimer = setInterval(() => pollSearch(searchVersion), 1000)
  } catch (e) { error.value = e.message }
}

function saveReceipts() {
  sessionStorage.setItem('media-search-receipts', JSON.stringify(receipts.value.slice(0, 20)))
}

async function download(candidate) {
  error.value = ''; downloading.value = true
  const taskId = crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('')
  try {
    let body = { ...lastRequest, policy: policy.value, request_id: taskId }
    const media = session.value?.media
    if (!candidate && media?.tmdb_id) body = { ...body, title: '', imdb_id: undefined,
      tmdb_id: media.tmdb_id, media_type: media.media_type, year: media.year || undefined }
    if (candidate) body = { candidate_id: candidate.candidate_id, scope: lastRequest.scope,
      season: lastRequest.season, ...(lastRequest.episode ? { episode: lastRequest.episode } : {}),
      policy: policy.value, request_id: taskId }
    const entry = { task_id: taskId, status: 'pending', resource: { title: candidate?.title || session.value?.media?.title },
      reason: '正在选源、核验并提交，响应超时后仍可续查' }
    receipts.value.unshift(entry); saveReceipts()
    const result = await api('/api/download', 'POST', body)
    receipts.value = receipts.value.map(r => r.task_id === taskId ? { ...entry, ...result } : r)
    saveReceipts()
  } catch (e) { error.value = e.message + '；已有任务 ID 可继续核实提交状态' }
  finally { downloading.value = false }
}

async function pollTasks() {
  if (!connected.value) return
  for (const task of receipts.value.filter(r => ['pending', 'submitted'].includes(r.status))) {
    try {
      const result = await api(`/api/download/${task.task_id}`)
      if (!['not_found', 'unavailable'].includes(result.status)) Object.assign(task, result)
    } catch { /* Keep the last confirmed receipt during a temporary outage. */ }
  }
  saveReceipts()
}

watch([mediaType, scope, season, episode, title, year], () => {
  ++searchVersion; clearInterval(searchTimer); session.value = null; busy.value = false
})
onMounted(async () => {
  try { receipts.value = JSON.parse(sessionStorage.getItem('media-search-receipts') || '[]') } catch { receipts.value = [] }
  try { await api('/api/session'); connected.value = true } catch { connected.value = false }
  checking.value = false
  if (connected.value && title.value) await search()
  taskTimer = setInterval(pollTasks, 3000)
})
onUnmounted(() => { clearInterval(searchTimer); clearInterval(taskTimer) })
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="寻片首页"><span class="brand-mark">◫</span><span>寻片<small>MEDIA SEARCH</small></span></a>
      <div class="connection"><span :class="['dot', { live: connected }]"></span>{{ connected ? '已连接你的媒体服务' : checking ? '连接中' : '尚未连接' }}</div>
    </header>

    <main>
      <section class="intro"><span class="eyebrow">你的下一部好片，从这里开始</span>
        <h1>找到想看的，<br /><span>选择合适的版本。</span></h1>
        <p>一起查询 M-Team 与 Mini4K，选好资源，直接下载。</p>
      </section>

      <form v-if="!connected && !checking" class="login-panel" @submit.prevent="login">
        <div><strong>连接你的查询服务</strong><p>输入此服务的访问令牌，登录后即可查询与下载。</p></div>
        <label class="sr-only" for="token">访问令牌</label>
        <input id="token" v-model="token" type="password" autocomplete="current-password" placeholder="访问令牌" required />
        <button class="primary" type="submit">连接</button>
      </form>

      <section class="search-panel">
        <form @submit.prevent="search()">
          <label class="input-label" for="title">作品名称</label>
          <div class="search-line"><span class="search-icon" aria-hidden="true">⌕</span>
            <input id="title" v-model="title" placeholder="输入片名、剧名或 IMDb ID" autocomplete="off" required />
            <button class="primary" type="submit" :disabled="!connected || busy">{{ busy ? '查询中…' : '搜索资源' }}<span aria-hidden="true"> ↗</span></button>
          </div>
          <div class="options">
            <label>类型<select v-model="mediaType"><option value="">自动识别</option><option value="movie">电影</option><option value="tv">剧集</option></select></label>
            <label>年份<input v-model="year" type="number" min="1888" max="2200" placeholder="不限" /></label>
            <template v-if="isTV">
              <label>下载范围<select v-model="scope"><option value="season">整季</option><option value="episode">单集</option><option value="series">已完结整剧</option></select></label>
              <label v-if="scope !== 'series'">季号<input v-model="season" type="number" min="1" required /></label>
              <label v-if="scope === 'episode'">集号<input v-model="episode" type="number" min="1" required /></label>
            </template>
          </div>
        </form>
        <p v-if="scope === 'series' && isTV" class="scope-note">只选覆盖全剧的一个完整 BT 资源，不拆季下载。</p>
        <div class="profile-grid" role="radiogroup" aria-label="下载策略">
          <button v-for="p in profiles" :key="p.id" type="button" role="radio" :aria-checked="policy === p.id"
            :class="['profile', { selected: policy === p.id }]" @click="policy = p.id">
            <span class="profile-icon">{{ p.icon }}</span><span><strong>{{ p.title }}</strong><small>{{ p.text }}</small></span><span class="radio"></span>
          </button>
        </div>
      </section>

      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <section v-if="session?.choices?.length" class="results">
        <div class="section-heading"><h2>找到多个作品</h2><span>请选择你想下载的版本</span></div>
        <button v-for="m in session.choices" :key="`${m.media_type}-${m.tmdb_id}-${m.imdb_id}`" class="choice" @click="search(m)">
          <strong>{{ m.title }}</strong><span>{{ m.year || '年份未知' }} · {{ m.media_type === 'movie' ? '电影' : '剧集' }}</span><span>查看资源 →</span>
        </button>
      </section>

      <section v-if="session && !session.choices?.length" class="results">
        <div class="section-heading"><div><span class="eyebrow">搜索结果</span><h2>{{ session.media?.title || '正在确认作品' }}<small v-if="session.media?.year">{{ session.media.year }}</small></h2></div>
          <button class="primary" :disabled="!hasMedia || downloading" @click="download()">{{ downloading ? '正在核验与提交…' : '自动选源下载' }}</button>
        </div>
        <div class="source-status">
          <div v-for="(state, source) in session.sources" :key="source" class="source-chip"><span :class="['dot', { live: state.status === 'OK' }]"></span>
            <strong>{{ names[source] || source }}</strong><span>{{ labels[state.status] || state.status }}</span>
            <small v-if="state.elapsed_ms">{{ (state.elapsed_ms / 1000).toFixed(1) }}s</small>
            <button v-if="state.has_more" :disabled="busy" @click="more(source)">更多 →</button>
          </div>
          <span v-if="session.first_result_ms" class="timing">首批结果 {{ (session.first_result_ms / 1000).toFixed(1) }}s</span>
        </div>
        <div v-if="session.candidates?.length" class="result-controls"><span>{{ candidates.length }} 个候选资源 · 体积与字幕以预检结果为准</span>
          <select v-model="sourceFilter" aria-label="筛选站点"><option value="">全部站点</option><option value="mteam">M-Team</option><option value="mini4k">Mini4K</option></select>
          <select v-model="resolution" aria-label="筛选分辨率"><option value="">全部分辨率</option><option value="2160p">2160p</option><option value="1080p">1080p</option></select>
        </div>
        <article v-for="c in candidates" :key="c.candidate_id" class="resource">
          <div class="resource-icon" aria-hidden="true">▷</div><div class="resource-info"><h3>{{ c.title }}</h3>
            <div class="metadata"><span class="site-label">{{ names[c.source_id] }}</span><span>{{ size(c.size_bytes) }}</span><span v-if="c.seeders">{{ c.seeders }} 做种</span>
              <span :class="['subtitle', { known: c.subtitles?.chinese }]" :title="c.subtitles?.text">{{ subtitleLabel(c.subtitles) }}</span></div>
          </div><button class="secondary" :disabled="downloading" @click="download(c)">下载此资源 ↗</button>
        </article>
        <div v-if="!candidates.length" class="empty"><span>{{ busy ? '◌' : '◇' }}</span><p>{{ busy ? '各站结果会陆续出现在这里' : session.reason || '暂时没有匹配资源，可以调整名称、年份或范围再试' }}</p></div>
      </section>

      <section v-if="receipts.length" class="tasks"><div class="section-heading"><h2>下载回执</h2><span>受理状态与下载进度</span></div>
        <article v-for="r in receipts" :key="r.task_id" class="task">
          <div class="task-top"><strong>{{ r.resource?.title || r.media?.title || '下载请求' }}</strong><span class="task-state">{{ labels[r.status] || r.status }}</span></div>
          <p v-if="r.reason">{{ r.reason }}</p><p v-for="warning in r.warnings || []" :key="warning" class="warning">{{ warning }}</p>
          <small>任务 {{ r.task_id }}<template v-if="r.route"> · {{ r.route === 'pt' ? 'MoviePilot 下载器' : '115' }}</template><template v-if="r.reused"> · 已复用现有回执</template></small>
          <progress v-if="typeof r.progress === 'number'" :value="r.progress <= 1 ? r.progress * 100 : r.progress" max="100" aria-label="下载进度"></progress>
          <button v-if="r.status === 'pending'" class="text-button" @click="pollTasks">核实状态 →</button>
        </article>
      </section>
    </main>
    <footer><span>寻片 · 让选择更简单</span><span>M-Team / Mini4K</span></footer>
  </div>
</template>
