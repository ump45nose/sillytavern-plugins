/* ==========================================================================
   公益 AI 资源中枢 · 演示数据集 (贴合真实使用流程与三类信息约束)
   ========================================================================== */

window.HUB_DATA = {
  now: "19:27",
  dateLabel: "2026年10月21日 周三",

  /* 系统正在检查什么 (Live Background Activity) */
  liveChecks: [
    {
      id: "chk-1",
      type: "任务验证",
      title: "正在执行「强模型 · 推理与防降智探针」实测",
      detail: "目标：凛冬公益 (claude-opus-4-6)、Linux.do 公益枢纽 (gpt-5.2-pro) · 已完成 2/3，正在校验思维链签名与 Tool Call 结构化输出",
      startedAt: "19:26",
      progress: 67,
      targetView: "scan"
    },
    {
      id: "chk-2",
      type: "目录巡检",
      title: "后台增量扫描 2 个新增 Key 的 /v1/models 目录与广场倍率",
      detail: "刚刚发现「凛冬公益」晚间限时分组新开放 claude-opus-4-6 (0.2x 公益倍率)",
      startedAt: "19:24",
      progress: 100,
      targetView: "scan"
    }
  ],

  /* 哪些问题需要自己处理 (Human Triage Queue — 少量人工维护直接可见) */
  triageItems: [
    {
      id: "tri-key",
      kind: "missing_key",
      tone: "clay",
      kicker: "需补 Key · 本次同步新增",
      title: "极光公益站 (aurora.linux.do) 缺可用 API Key",
      desc: "All API Hub 已同步账号 sm5145 ($14.00)，但尚未创建或拉取到 sk- 令牌",
      actionLabel: "立即补 Key",
      siteId: "site-aurora"
    },
    {
      id: "tri-threshold",
      kind: "threshold_blocked",
      tone: "ochre",
      kicker: "签到门槛阻塞 · 明日 08:00 刷新",
      title: "星火公益 账号余额 $10.40 高于签到上限 ($10.00)",
      desc: "需在明早 08:00 前消耗至少 $0.45，否则无法领取明日 +$2.50 每日签到额度",
      actionLabel: "绑定 Cron 削峰",
      siteId: "site-spark"
    },
    {
      id: "tri-merge",
      kind: "duplicate_site",
      tone: "sky",
      kicker: "疑似重复站点 · 跨来源待合并",
      title: "ネコ公益 (nekoapi.com) 与 NekoRelay (relay.nekoapi.com)",
      desc: "浏览器扩展与 NAS New API 指向同一上游证书与 sk-neko 前缀，合并后保留各自账号",
      actionLabel: "对比并合并",
      siteId: "site-neko"
    },
    {
      id: "tri-auth",
      kind: "auth_expiring",
      tone: "rose",
      kicker: "来源凭证预警 · NAS CPA",
      title: "CPA「公益 Claude OAuth #2」刷新令牌 18 小时后过期",
      desc: "浮云公益备用号 #14 同时出现 401 报错，建议刷新凭证或切换主路由",
      actionLabel: "查看来源状态",
      siteId: "src-cpa"
    }
  ],

  /* 1. 来源接入与数据同步 (All API Hub, NAS New API, NAS CPA) */
  sources: [
    {
      id: "src-allhub",
      name: "All API Hub",
      location: "浏览器扩展 · Chrome 130 (MacAir)",
      badgeClass: "hub",
      authStatus: "ok",
      authText: "授权正常 · 本地 Bridge 令牌有效",
      authDetail: "6/6 站点网页 Cookie 有效 · 支持自动签到与多账号余额抓取",
      lastSync: "今天 19:15（12 分钟前）",
      syncFreq: "每 30 分钟增量同步 / 浏览器唤醒即同步",
      capabilities: [
        "站点列表与备用域名",
        "多账号登录态与独立余额",
        "每日自动签到与门槛规则",
        "账号下已创建的 API Key",
        "站点模型广场公开指标快照"
      ],
      latestDiffSummary: "本次新增 1 个站点、1 条限时 Key；更新 6 个账号余额与签到结果",
      diffs: [
        { type: "add", tag: "新增站点", text: "极光公益站 (aurora.linux.do) · 账号 sm5145 初始额度 $12.00 + 今日 $2.00（待补 Key）", time: "19:15" },
        { type: "upd", tag: "签到入账", text: "Linux.do 公益枢纽 (sm5145) 自动签到成功 +$2.50，当日有效额度更新为 $3.50", time: "19:15" },
        { type: "add", tag: "新增 Key", text: "凛冬公益站 同步新增「晚间限时分组 Key」(sk-win...8a1c)", time: "19:15" },
        { type: "warn", tag: "门槛预警", text: "检测到 星火公益 账号余额 $10.40 ≥ 签到上限 $10.00，标记为「需优先消耗」", time: "19:15" }
      ]
    },
    {
      id: "src-newapi",
      name: "New API",
      location: "NAS 容器 · http://nas.local:3000",
      badgeClass: "newapi",
      authStatus: "ok",
      authText: "授权正常 · Root Admin Token 在线 (4ms)",
      authDetail: "Tailscale 内网直连 · 已挂载 24 个上游渠道与 4 个策略分组",
      lastSync: "今天 19:24（3 分钟前）",
      syncFreq: "Webhook 实时推送 + 每 10 分钟状态轮询",
      capabilities: [
        "已挂载渠道 (Channels) 与分组权重",
        "渠道绑定的 Base URL 与密钥映射",
        "近期真实调用状态码 (200/401/429/500)",
        "模型重定向映射 (model_mapping)",
        "按渠道统计的首字延迟与吞吐"
      ],
      latestDiffSummary: "本次更新 24 个渠道健康度；隔离 1 个 401 失效渠道；对齐 3 组模型目录",
      diffs: [
        { type: "err", tag: "异常隔离", text: "渠道 #14「浮云公益-主号」连续 5 次返回 401 Invalid Token，已自动暂停分发", time: "19:24" },
        { type: "upd", tag: "优先路由", text: "将「凛冬公益-晚间限时池」提升至强模型分组优先级 P0（优先消耗今日 $6.00 额度）", time: "19:22" },
        { type: "upd", tag: "目录同步", text: "对齐 Linux.do 公益枢纽 与 星火公益 的可调用模型白名单 (+3 模型)", time: "19:20" }
      ]
    },
    {
      id: "src-cpa",
      name: "CPA (CLI Proxy API)",
      location: "NAS 服务 · http://nas.local:8317",
      badgeClass: "cpa",
      authStatus: "warn",
      authText: "需要注意 · 1 个上游 OAuth 刷新令牌 18h 后过期",
      authDetail: "Management API 正常 · Claude Code / Codex 协议转换池运行中",
      lastSync: "今天 19:26（1 分钟前）",
      syncFreq: "每 5 分钟同步凭证池与会话健康度",
      capabilities: [
        "Claude Code / Codex / Gemini CLI 原生协议代理",
        "OAuth 会话池与逆向渠道凭证健康度",
        "Thinking 思维链签名完整性与 Tool Use 兼容性",
        "并发上限保护与 429 自动退避切换"
      ],
      latestDiffSummary: "本次更新主备故障转移链路；捕获 1 个渠道 Thinking 块降智异常",
      diffs: [
        { type: "warn", tag: "实测拦截", text: "拦截「极客中转」claude-opus-4-6 响应：缺失原生 thinking 签名，疑似映射至轻量模型", time: "19:26" },
        { type: "warn", tag: "凭证预警", text: "上游凭证「Claude-OAuth-Pool-02」将于明日 13:30 到期，需在浏览器刷新授权", time: "19:25" },
        { type: "upd", tag: "链路切换", text: "本地 Claude Code 默认强模型上游已锁定为「凛冬公益 (限时优先) → Linux.do 公益枢纽」", time: "19:20" }
      ]
    }
  ],

  /* 3. 模型选型参谋 (Models divided into 强模型 vs 执行模型; Callers choose, Hub gives Decision Basis) */
  models: [
    {
      id: "claude-opus-4-6",
      tier: "strong",
      name: "claude-opus-4-6",
      roleTag: "复杂架构 · 深度推理 · 疑难重构",
      verdict: "当前最稳强模型 · 2 个真模型渠道可用，1 个限时池优先消耗",
      dailyAvailQuota: "$11.00",
      totalAvailQuota: "$39.60",
      avgTtft: "1.18s",
      avgTps: "46 tok/s",
      verifyBadge: "19:10 推理探针通过 (原生 Thinking + Tool Use)",
      verifyTone: "olive",
      callerHint: "Claude Code / 复杂 Plan 首选。当前「凛冬公益」晚间限时窗口已开（23:00 关），建议优先走该渠道消耗今日 $6.00 额度。",
      routes: [
        {
          rank: "#1 限时优先",
          siteName: "凛冬公益站",
          account: "weikang_main (晚间限时分组)",
          source: "NAS CPA / New API",
          quotaText: "今日有效 $6.00 (23:00 清零)",
          metrics: "0.2x 倍率 · TTFT 1.3s · 42 tok/s",
          evidence: "✓ 实测真模型 · 当日额度优先消耗",
          status: "best"
        },
        {
          rank: "#2 稳定主力",
          siteName: "Linux.do 公益枢纽",
          account: "sm5145@linux.do (Lv.3 主号)",
          source: "NAS CPA / New API",
          quotaText: "今日有效 $3.50 + 永久 $18.40",
          metrics: "0.5x 倍率 · TTFT 1.1s · 48 tok/s",
          evidence: "✓ 连续 14 次任务验证 100% 通过",
          status: "best"
        },
        {
          rank: "已排除",
          siteName: "极客中转 · 公益池",
          account: "wk_geek",
          source: "New API #19",
          quotaText: "账面 $21.50",
          metrics: "广场标称 99% 在线 · 0.5x",
          evidence: "⚠ 19:10 任务验证异常：Thinking 块丢失，响应特征疑似 Haiku 套壳",
          status: "warn"
        }
      ]
    },
    {
      id: "gpt-5.2-pro",
      tier: "strong",
      name: "gpt-5.2-pro",
      roleTag: "跨文件代码推演 · 算法与边界审查",
      verdict: "3 个渠道实测通过 · 星火公益需优先消耗 $0.45 以解除明日签到冻结",
      dailyAvailQuota: "$5.40",
      totalAvailQuota: "$35.00",
      avgTtft: "1.45s",
      avgTps: "54 tok/s",
      verifyBadge: "18:40 AST 补丁修复实测通过",
      verifyTone: "olive",
      callerHint: "Codex CLI 首选。建议当前调用优先路由至「星火公益 (sm5145)」，削减 $0.40 超门槛余额以保住明日 +$2.50 签到。",
      routes: [
        {
          rank: "#1 削峰优先",
          siteName: "星火公益",
          account: "sm5145 (余额 $10.40 / 门槛 $10)",
          source: "NAS New API #08",
          quotaText: "需耗 $0.45 解锁签到 · 总 $10.40",
          metrics: "1.0x 倍率 · TTFT 1.5s · 49 tok/s",
          evidence: "✓ 实测通过 · 优先削峰保明日签到",
          status: "best"
        },
        {
          rank: "#2 限时消耗",
          siteName: "Linux.do 公益枢纽",
          account: "sm5145@linux.do (Lv.3 主号)",
          source: "NAS New API #02",
          quotaText: "今日有效 $3.50 + 永久 $18.40",
          metrics: "0.4x 倍率 · TTFT 1.2s · 58 tok/s",
          evidence: "✓ 实测真模型 · 推理高档位有效",
          status: "best"
        }
      ]
    },
    {
      id: "claude-sonnet-4-6-thinking",
      tier: "strong",
      name: "claude-sonnet-4-6-thinking",
      roleTag: "日常主力开发 · 前后端联调 · 交互设计",
      verdict: "性价比最高 · 4 个站点全天充裕，支持高并发 Tool Calling",
      dailyAvailQuota: "$12.50",
      totalAvailQuota: "$64.20",
      avgTtft: "0.85s",
      avgTps: "68 tok/s",
      verifyBadge: "19:00 多轮工具调用实测 100% 通过",
      verifyTone: "olive",
      callerHint: "适合长会话编码与高频交互。所有主力公益站均验证为原生 Sonnet 4.6。",
      routes: [
        {
          rank: "#1 限时优先",
          siteName: "凛冬公益站",
          account: "weikang_main",
          source: "NAS CPA",
          quotaText: "今日有效 $6.00 (23:00 关)",
          metrics: "0.15x 倍率 · TTFT 0.9s · 64 tok/s",
          evidence: "✓ 实测通过 · 限时倍率极低",
          status: "best"
        },
        {
          rank: "#2 均衡推荐",
          siteName: "Linux.do 公益枢纽",
          account: "sm5145_dev (Lv.2 备号)",
          source: "NAS New API #03",
          quotaText: "今日有效 $1.50 + 永久 $6.20",
          metrics: "0.3x 倍率 · TTFT 0.8s · 71 tok/s",
          evidence: "✓ 备号独立配额 · 不占主号并发",
          status: "best"
        }
      ]
    },
    {
      id: "deepseek-v3.2",
      tier: "exec",
      name: "deepseek-v3.2",
      roleTag: "批量文本处理 · 定时 Cron · 日志摘要与翻译",
      verdict: "零成本主力执行模型 · 2 个站点提供 0.05x~免费公益池",
      dailyAvailQuota: "$18.00+",
      totalAvailQuota: "$88.50",
      avgTtft: "0.52s",
      avgTps: "96 tok/s",
      verifyBadge: "18:30 16k JSON 抽取压测通过",
      verifyTone: "olive",
      callerHint: "适合所有后台 Cron 任务、批量分类、长文档清洗，几乎不消耗宝贵的强模型额度。",
      routes: [
        {
          rank: "#1 零点福利池",
          siteName: "极客中转 · 公益池",
          account: "wk_geek",
          source: "NAS New API #19",
          quotaText: "永久 $21.50 (执行模型极稳)",
          metrics: "0.05x 倍率 · TTFT 0.48s · 104 tok/s",
          evidence: "✓ 虽然 Opus 套壳，但 DeepSeek 为满血官转",
          status: "best"
        },
        {
          rank: "#2 合并站点池",
          siteName: "ネコ公益 (nekoapi.com)",
          account: "neko_wk",
          source: "NAS New API #11",
          quotaText: "今日 $2.00 + 永久 $7.80",
          metrics: "0.1x 倍率 · TTFT 0.6s · 88 tok/s",
          evidence: "✓ 16k 结构化输出零格式错误",
          status: "best"
        }
      ]
    },
    {
      id: "claude-haiku-4-5",
      tier: "exec",
      name: "claude-haiku-4-5",
      roleTag: "子 Agent 快速检索 · 语法检查 · 实时补全",
      verdict: "低延迟高并发 · 适合作为 Claude Code 子任务 (Subagent) 模型",
      dailyAvailQuota: "$14.00",
      totalAvailQuota: "$62.00",
      avgTtft: "0.38s",
      avgTps: "115 tok/s",
      verifyBadge: "19:15 并发 5 路压测零 429",
      verifyTone: "olive",
      callerHint: "在 Claude Code / Antigravity 中配置为轻量检索模型，响应极快且不触发站点 RPM 限制。",
      routes: [
        {
          rank: "#1 高并发池",
          siteName: "Linux.do 公益枢纽",
          account: "sm5145_dev (Lv.2 备号)",
          source: "NAS CPA",
          quotaText: "今日有效 $1.50 + 永久 $6.20",
          metrics: "0.1x 倍率 · TTFT 0.36s · 118 tok/s",
          evidence: "✓ 备号专供高频子任务",
          status: "best"
        },
        {
          rank: "#2 削峰备选",
          siteName: "星火公益",
          account: "spark_guest (小号)",
          source: "NAS New API #09",
          quotaText: "余额 $2.10 (今日已签 +$1.00)",
          metrics: "0.2x 倍率 · TTFT 0.42s · 108 tok/s",
          evidence: "✓ 稳定在线",
          status: "best"
        }
      ]
    },
    {
      id: "qwen-3-coder-plus",
      tier: "exec",
      name: "qwen-3-coder-plus",
      roleTag: "单测批量生成 · 样板代码填充 · 仓库扫描",
      verdict: "夜间与午间 Cron 任务优选 · 代码格式遵循度 99.1%",
      dailyAvailQuota: "$9.50",
      totalAvailQuota: "$45.00",
      avgTtft: "0.55s",
      avgTps: "89 tok/s",
      verifyBadge: "17:50 单元测试生成实测通过",
      verifyTone: "olive",
      callerHint: "已绑定「01:30 夜间单测补全 Cron」，专门消化各站当日剩余签到金。",
      routes: [
        {
          rank: "#1 限时消化",
          siteName: "Linux.do 公益枢纽",
          account: "sm5145@linux.do",
          source: "NAS New API #02",
          quotaText: "今日有效 $3.50",
          metrics: "0.1x 倍率 · TTFT 0.55s · 89 tok/s",
          evidence: "✓ 代码 Diff 零幻觉",
          status: "best"
        }
      ]
    }
  ],

  /* 3 & 5. 聚合站点列表 (同站点多来源聚合 + 保留独立账号及余额 + 辅助人工维护) */
  sites: [
    {
      id: "site-linuxdo",
      name: "Linux.do 公益枢纽",
      url: "https://api.linuxdo.org",
      mirrorUrl: "https://CF-relay.linuxdo.org",
      sources: ["All API Hub", "NAS · New API", "NAS · CPA"],
      status: "ok",
      statusText: "200 OK · 118ms",
      validity: "长期有效 (LinuxDo Connect 绑定)",
      restrictions: "RPM 60 · 并发 5 · 禁批量爬虫 · Opus 仅限 Lv.3 分组",
      signinRule: "每日 00:00 后自动签到 (+$1.50 ~ +$3.00)，余额门槛 < $25.00",
      recentSuccessRate: "99.2%",
      recentLatency: "1.1s 首字 / 48 tok/s",
      probes: ["ok","ok","ok","ok","ok","ok","ok","ok","ok","ok","ok","ok"],
      strongModels: ["claude-opus-4-6", "gpt-5.2-pro", "claude-sonnet-4-6-thinking"],
      execModels: ["deepseek-v3.2", "claude-haiku-4-5", "qwen-3-coder-plus"],
      accounts: [
        {
          id: "acc-ld-1",
          username: "sm5145@linux.do",
          label: "Lv.3 主号",
          permBalance: 18.40,
          dailyQuota: 3.50,
          dailyExpireAt: "24:00 清零",
          signinStatus: "今日已自动签到 (+$2.50)",
          signinTone: "olive",
          thresholdCap: 25.00,
          keysCount: 2,
          keys: [
            { name: "Lv3-全模型主Key", masked: "sk-ldo...9f2a", group: "Lv3-Pro", status: "ok" },
            { name: "CPA-Claude专供", masked: "sk-ldo...3c18", group: "Claude-VIP", status: "ok" }
          ]
        },
        {
          id: "acc-ld-2",
          username: "sm5145_dev",
          label: "Lv.2 备号",
          permBalance: 6.20,
          dailyQuota: 1.50,
          dailyExpireAt: "24:00 清零",
          signinStatus: "今日已自动签到 (+$1.50)",
          signinTone: "olive",
          thresholdCap: 25.00,
          keysCount: 1,
          keys: [
            { name: "Dev-高频执行Key", masked: "sk-ldo...7b44", group: "Default", status: "ok" }
          ]
        }
      ]
    },
    {
      id: "site-winter",
      name: "凛冬公益站",
      url: "https://api.winter-welfare.org",
      mirrorUrl: "",
      sources: ["All API Hub", "NAS · New API", "NAS · CPA"],
      status: "ok",
      statusText: "200 OK · 142ms",
      validity: "秋季公益批次 · 2026-11-15 到期 (剩 25 天)",
      restrictions: "并发 3 · 当日限时额度优先扣减 · 20:30–22:00 高峰易拥塞",
      signinRule: "每日 08:00 签到 (+$2.00) + 18:00 晚间限时包投放 ($6.00，仅 18:00–23:00 可用)",
      recentSuccessRate: "96.8%",
      recentLatency: "1.3s 首字 / 42 tok/s",
      probes: ["ok","ok","ok","ok","w","ok","ok","ok","ok","ok","ok","ok"],
      strongModels: ["claude-opus-4-6", "claude-sonnet-4-6-thinking"],
      execModels: ["claude-haiku-4-5", "gpt-5-mini"],
      accounts: [
        {
          id: "acc-win-1",
          username: "weikang_main",
          label: "主力号",
          permBalance: 4.80,
          dailyQuota: 6.00,
          dailyExpireAt: "23:00 窗口关闭即失效",
          signinStatus: "18:00 晚间投放已领 (+$6.00 限时)",
          signinTone: "clay",
          thresholdCap: 10.00,
          keysCount: 2,
          keys: [
            { name: "晚间限时分组Key", masked: "sk-win...8a1c", group: "Night-Drop", status: "ok" },
            { name: "常规储备Key", masked: "sk-win...110e", group: "Standard", status: "ok" }
          ]
        }
      ]
    },
    {
      id: "site-spark",
      name: "星火公益",
      url: "https://spark.linuxdo.icu",
      mirrorUrl: "",
      sources: ["All API Hub", "NAS · New API"],
      status: "warn",
      statusText: "200 OK · 签到门槛阻塞",
      validity: "长期有效",
      restrictions: "RPM 30 · 严禁自动化脚本压测 · 余额 ≥ $10.00 禁止签到",
      signinRule: "每日 08:00 开放签到 (+$2.50)；硬性门槛：账户余额必须 < $10.00",
      recentSuccessRate: "94.5%",
      recentLatency: "1.5s 首字 / 49 tok/s",
      probes: ["ok","ok","w","ok","ok","ok","ok","w","ok","ok","ok","ok"],
      strongModels: ["gpt-5.2-pro", "claude-sonnet-4-6-thinking"],
      execModels: ["claude-haiku-4-5", "deepseek-v3.2"],
      accounts: [
        {
          id: "acc-spk-1",
          username: "sm5145",
          label: "主号 · 需削峰",
          permBalance: 10.40,
          dailyQuota: 0.00,
          dailyExpireAt: "无当日限时包",
          signinStatus: "⚠ 余额 $10.40 ≥ $10.00 门槛，今日签到被拒",
          signinTone: "ochre",
          thresholdCap: 10.00,
          keysCount: 1,
          keys: [
            { name: "星火主号Key", masked: "sk-spk...55d1", group: "Default", status: "ok" }
          ]
        },
        {
          id: "acc-spk-2",
          username: "spark_guest",
          label: "小号",
          permBalance: 2.10,
          dailyQuota: 1.00,
          dailyExpireAt: "24:00 清零",
          signinStatus: "今日已签到 (+$1.00)",
          signinTone: "olive",
          thresholdCap: 10.00,
          keysCount: 1,
          keys: [
            { name: "星火小号Key", masked: "sk-spk...90a2", group: "Default", status: "ok" }
          ]
        }
      ]
    },
    {
      id: "site-aurora",
      name: "极光公益站",
      url: "https://aurora.linux.do",
      mirrorUrl: "",
      sources: ["All API Hub"],
      status: "warn",
      statusText: "待补 Key · 网页已登录",
      validity: "公测期至 2026-11-30",
      restrictions: "RPM 45 · 仅限个人开发工具调用",
      signinRule: "每日 00:00 自动签到 (+$2.00)，当日有效额度优先扣减",
      recentSuccessRate: "待首次扫描",
      recentLatency: "—",
      probes: ["ok","ok","ok"],
      strongModels: ["claude-sonnet-4-6-thinking", "gpt-5.2-pro"],
      execModels: ["deepseek-v3.2"],
      accounts: [
        {
          id: "acc-aur-1",
          username: "sm5145@linux.do",
          label: "新同步账号",
          permBalance: 12.00,
          dailyQuota: 2.00,
          dailyExpireAt: "24:00 清零",
          signinStatus: "今日已签到 (+$2.00) · 缺 API Key",
          signinTone: "clay",
          thresholdCap: 20.00,
          keysCount: 0,
          keys: []
        }
      ]
    },
    {
      id: "site-geek",
      name: "极客中转 · 公益池",
      url: "https://relay.geekhub.cc",
      mirrorUrl: "",
      sources: ["All API Hub", "NAS · New API"],
      status: "warn",
      statusText: "200 OK · 强模型实测降智",
      validity: "2026-12-31 到期",
      restrictions: "并发 8 · 执行模型满血，Opus 渠道经实测存在模型替换",
      signinRule: "每月 1 日自动发放 $25.00 公益金，无每日签到门槛",
      recentSuccessRate: "执行模型 98.4% / 强模型已拦截",
      recentLatency: "0.48s 首字 (DeepSeek)",
      probes: ["ok","ok","e","ok","ok","ok","e","ok","ok","ok","ok","ok"],
      strongModels: [],
      execModels: ["deepseek-v3.2", "gpt-5-mini"],
      accounts: [
        {
          id: "acc-gk-1",
          username: "wk_geek",
          label: "月度号",
          permBalance: 21.50,
          dailyQuota: 0.00,
          dailyExpireAt: "月底清零",
          signinStatus: "月度额度生效中",
          signinTone: "olive",
          thresholdCap: 50.00,
          keysCount: 1,
          keys: [
            { name: "极客执行模型专供", masked: "sk-gek...44f0", group: "Exec-Only", status: "ok" }
          ]
        }
      ]
    },
    {
      id: "site-neko",
      name: "ネコ公益 (NekoAPI)",
      url: "https://api.nekoapi.com",
      mirrorUrl: "https://relay.nekoapi.com (疑似重复站点待合并)",
      sources: ["All API Hub", "NAS · New API (待合并)"],
      status: "ok",
      statusText: "200 OK · 发现重复条目待合并",
      validity: "长期有效",
      restrictions: "RPM 40 · 凌晨 00:30–07:30 倍率减半 (0.05x)",
      signinRule: "每日 00:30 投放签到池 (+$2.00)，门槛 < $12.00",
      recentSuccessRate: "97.1%",
      recentLatency: "0.62s 首字 / 88 tok/s",
      probes: ["ok","ok","ok","ok","ok","ok","w","ok","ok","ok","ok","ok"],
      strongModels: ["claude-sonnet-4-6-thinking"],
      execModels: ["deepseek-v3.2", "qwen-3-coder-plus"],
      duplicateCandidate: {
        dupSiteId: "site-neko-dup",
        dupName: "NekoRelay (NAS 旧配置条目)",
        dupUrl: "https://relay.nekoapi.com",
        dupSource: "NAS · New API 渠道 #11",
        reason: "TLS 证书 SAN 指纹一致 + 共享 sk-neko- 密钥前缀 + /v1/models 响应哈希 100% 相同",
        dupAccount: "neko_nas_legacy (独立余额 $3.40 · 1 个 Key)"
      },
      accounts: [
        {
          id: "acc-nk-1",
          username: "neko_wk",
          label: "All API Hub 账号",
          permBalance: 7.80,
          dailyQuota: 2.00,
          dailyExpireAt: "24:00 清零",
          signinStatus: "今日已签到 (+$2.00)",
          signinTone: "olive",
          thresholdCap: 12.00,
          keysCount: 1,
          keys: [
            { name: "Neko主Key", masked: "sk-neko...61a9", group: "Default", status: "ok" }
          ]
        }
      ]
    }
  ],

  /* 4. 权益利用：投放时刻 vs 可用窗口 (投放时刻 ≠ 全天可用；当日额度优先消耗) */
  quotaWindows: [
    {
      id: "win-winter-night",
      siteName: "凛冬公益站",
      account: "weikang_main",
      quotaTitle: "晚间 Claude 专属投放包",
      dailyEffective: "$6.00",
      bookBalance: "$4.80",
      priorityRule: "当日额度优先消耗 (P0)",
      dropTime: "18:00 投放",
      dropHour: 18.0,
      winStart: 18.0,
      winEnd: 23.0,
      usableWindowText: "18:00 – 23:00 (实际约 21:45 公共并发池耗尽)",
      whyNotAllDay: "18:00 准时投放额度，但该分组仅开放至 23:00；且晚高峰 21:30 后公共上游池常因总额度耗尽提前返回 429",
      state: "active-now",
      stateLabel: "窗口开放中 · 距关闭剩 3h 33m",
      boundCronId: "cron-daily-draft"
    },
    {
      id: "win-linuxdo-daily",
      siteName: "Linux.do 公益枢纽",
      account: "sm5145@linux.do + sm5145_dev",
      quotaTitle: "每日自动签到有效额度 (双号合计)",
      dailyEffective: "$5.00",
      bookBalance: "$24.60",
      priorityRule: "当日额度优先消耗 (24:00 归零)",
      dropTime: "00:00 投放",
      dropHour: 0.2,
      winStart: 0.2,
      winEnd: 24.0,
      usableWindowText: "00:05 – 24:00 (全天可用，01:00–08:30 零排队)",
      whyNotAllDay: "当日签到金 24:00 未用完直接清零，不滚入永久余额；系统优先路由当日额度，耗尽后再切换永久余额",
      state: "active-now",
      stateLabel: "今日已耗 $1.40 · 剩 $3.60 待消化",
      boundCronId: "cron-night-review"
    },
    {
      id: "win-spark-threshold",
      siteName: "星火公益",
      account: "sm5145",
      quotaTitle: "签到门槛解锁窗口 (< $10.00 门槛)",
      dailyEffective: "需削峰 $0.45",
      bookBalance: "$10.40",
      priorityRule: "超门槛余额优先消耗",
      dropTime: "08:00 签到核验",
      dropHour: 8.0,
      winStart: 19.5,
      winEnd: 24.0,
      usableWindowText: "今晚 19:30 – 明早 07:50 前必须消耗 $0.45",
      whyNotAllDay: "明早 08:00 签到脚本触发时若余额仍 ≥ $10.00，将直接跳过并发放 $0.00，损失明日 $2.50 权益",
      state: "tight",
      stateLabel: "⚠ 签到阻塞中 · 已排入晚间任务削峰",
      boundCronId: "cron-arxiv-morning"
    },
    {
      id: "win-neko-midnight",
      siteName: "ネコ公益 (NekoAPI)",
      account: "neko_wk",
      quotaTitle: "午夜半价与签到投放池",
      dailyEffective: "$2.00",
      bookBalance: "$7.80",
      priorityRule: "00:30–07:30 0.05x 倍率窗口优先",
      dropTime: "00:30 投放",
      dropHour: 0.5,
      winStart: 0.5,
      winEnd: 7.5,
      usableWindowText: "00:30 – 07:30 (夜间低谷专属窗口)",
      whyNotAllDay: "00:30 投放后仅在 07:30 前享受 0.05x 极低倍率且开放满血 coder 模型，白天恢复 1.0x 且限流",
      state: "normal",
      stateLabel: "今日窗口已过 · 5 小时后再次开启",
      boundCronId: "cron-sec-audit"
    },
    {
      id: "win-winter-noon",
      siteName: "凛冬公益站",
      account: "weikang_main",
      quotaTitle: "午间加餐限量池 (1,000 份公共池)",
      dailyEffective: "$3.00 (限量池)",
      bookBalance: "$4.80",
      priorityRule: "窗口内抢先消耗",
      dropTime: "12:30 投放",
      dropHour: 12.5,
      winStart: 12.5,
      winEnd: 14.2,
      usableWindowText: "12:30 – 约 14:10 (投放时刻 ≠ 全天可用，约 100 分钟抢空)",
      whyNotAllDay: "12:30 投放全站共享 $3,000 额度池，通常在 14:10 左右被全站用户耗尽，下午无法再调用该分组",
      state: "normal",
      stateLabel: "今日已利用 $2.40 (14:08 池空关闭)",
      boundCronId: "cron-noon-memo"
    }
  ],

  /* 4. 已有 Cron 任务列表（支持绑定限时资源并校验窗口匹配度） */
  cronJobs: [
    {
      id: "cron-daily-draft",
      name: "每日复盘初稿与今日账单/录音汇总",
      cronExpr: "15 21 * * *",
      runTimeText: "每天 21:15",
      runHour: 21.25,
      tierReq: "强模型 (claude-opus-4-6 / sonnet-4-6)",
      estCost: "$0.85 / 次",
      boundWinId: "win-winter-night"
    },
    {
      id: "cron-night-review",
      name: "夜间全库单测生成与静态缺陷巡检",
      cronExpr: "20 23 * * *",
      runTimeText: "每天 23:20",
      runHour: 23.33,
      tierReq: "执行模型 (qwen-3-coder-plus / deepseek-v3.2)",
      estCost: "$1.20 / 次",
      boundWinId: "win-linuxdo-daily"
    },
    {
      id: "cron-arxiv-morning",
      name: "晚间技术情报预抓取与长文精读 (削峰任务)",
      cronExpr: "45 20 * * *",
      runTimeText: "每天 20:45",
      runHour: 20.75,
      tierReq: "强模型 (gpt-5.2-pro)",
      estCost: "$0.65 / 次",
      boundWinId: "win-spark-threshold"
    },
    {
      id: "cron-noon-memo",
      name: "午间 Plaud 录音逐字稿结构化提炼",
      cronExpr: "45 12 * * *",
      runTimeText: "每天 12:45",
      runHour: 12.75,
      tierReq: "强模型 (claude-sonnet-4-6-thinking)",
      estCost: "$0.50 / 次",
      boundWinId: "win-winter-noon"
    },
    {
      id: "cron-sec-audit",
      name: "凌晨跨仓库依赖安全与死链扫描",
      cronExpr: "10 02 * * *",
      runTimeText: "每天 02:10",
      runHour: 2.16,
      tierReq: "执行模型 (deepseek-v3.2)",
      estCost: "$0.35 / 次",
      boundWinId: "win-neko-midnight"
    }
  ],

  /* 2. 渠道扫描与任务验证 (Stage 1: 网站状态/Key目录/模型广场指标 -> Stage 2: 实际任务验证) */
  scanChannels: [
    {
      id: "ch-winter-night",
      checked: true,
      siteName: "凛冬公益站",
      channelName: "凛冬 · 晚间限时分组 (sk-win...8a1c)",
      source: "All API Hub → NAS CPA",
      webStatus: "200 OK · 142ms (TLS 正常)",
      webTone: "olive",
      keyCatalog: "共 18 个模型 · 本次新增 +2 (claude-opus-4-6, claude-sonnet-4-6-thinking)",
      keyModels: ["claude-opus-4-6", "claude-sonnet-4-6-thinking", "claude-haiku-4-5"],
      plazaMetrics: "广场连通率 98.2% · 倍率 0.2x (限时公益) · 宣称上游 6 节点",
      lastScanAt: "19:24",
      verifyState: "verified_pass",
      verifySummary: "✓ 实测真模型：原生 Thinking 签名通过 · 首字 1.28s · 42.6 tok/s",
      verifyTone: "olive",
      verifyDetail: "探针：多步数论反证 + 2 个嵌套 Tool Call。返回完整 thinking 块 (signature 校验有效)，未出现降智或截断。"
    },
    {
      id: "ch-linuxdo-lv3",
      checked: true,
      siteName: "Linux.do 公益枢纽",
      channelName: "LinuxDo · Lv3主号 (sk-ldo...9f2a)",
      source: "NAS New API #02",
      webStatus: "200 OK · 118ms (CF 免盾直连)",
      webTone: "olive",
      keyCatalog: "共 42 个模型 · 含 Opus 4.6 / GPT-5.2-Pro / DeepSeek V3.2",
      keyModels: ["claude-opus-4-6", "gpt-5.2-pro", "deepseek-v3.2", "qwen-3-coder-plus"],
      plazaMetrics: "广场连通率 99.4% · 倍率 0.4x~0.5x · Lv.3 专属通道",
      lastScanAt: "19:20",
      verifyState: "verified_pass",
      verifySummary: "✓ 实测真模型：AST 代码补丁 100% 编译通过 · 首字 1.12s · 48.4 tok/s",
      verifyTone: "olive",
      verifyDetail: "探针：Swift 并发竞态修复 Diff 生成。一次性通过语法与边界检查，耗时 $0.011。"
    },
    {
      id: "ch-geek-relay",
      checked: true,
      siteName: "极客中转 · 公益池",
      channelName: "极客中转 · 默认分组 (sk-gek...44f0)",
      source: "NAS New API #19",
      webStatus: "200 OK · 95ms",
      webTone: "olive",
      keyCatalog: "共 31 个模型 · 目录包含 claude-opus-4-6 与 deepseek-v3.2",
      keyModels: ["claude-opus-4-6", "deepseek-v3.2", "gpt-5-mini"],
      plazaMetrics: "广场宣称 Opus 连通率 99.0% · 0.5x 倍率（⚠ 与实测严重不符）",
      lastScanAt: "19:10",
      verifyState: "verified_fail",
      verifySummary: "⚠ 广场虚假指标：Opus 实测缺失 Thinking 且逻辑崩塌（疑似 Haiku 映射）；DeepSeek 实测正常",
      verifyTone: "rose",
      verifyDetail: "对比证据：模型广场显示 Opus 99% 绿灯，但实际任务验证中：① 请求 thinking 参数被静默忽略；② 知识截止与推理特征匹配轻量模型。系统已自动将该渠道从「强模型」移除，仅保留其 DeepSeek 执行模型路由。"
    },
    {
      id: "ch-spark-main",
      checked: false,
      siteName: "星火公益",
      channelName: "星火 · 主号渠道 (sk-spk...55d1)",
      source: "NAS New API #08",
      webStatus: "200 OK · 164ms",
      webTone: "olive",
      keyCatalog: "共 25 个模型 · GPT-5.2-Pro / Sonnet 4.6 / DeepSeek V3.2",
      keyModels: ["gpt-5.2-pro", "claude-sonnet-4-6-thinking", "deepseek-v3.2"],
      plazaMetrics: "广场连通率 95.0% · 倍率 1.0x · 每日签到赠金池",
      lastScanAt: "18:40",
      verifyState: "verified_pass",
      verifySummary: "✓ 实测通过：GPT-5.2-Pro 推理档位完整 · 首字 1.48s · 49.1 tok/s",
      verifyTone: "olive",
      verifyDetail: "探针：Python 异步死锁定位与修复。输出结构化 JSON 准确。"
    },
    {
      id: "ch-fuyun-dead",
      checked: false,
      siteName: "浮云公益 (已暂停)",
      channelName: "浮云 · 备用号 #14 (sk-fyn...02c1)",
      source: "NAS New API #14",
      webStatus: "401 Unauthorized · Key 已失效",
      webTone: "rose",
      keyCatalog: "无法读取 /v1/models (返回 invalid_api_key)",
      keyModels: [],
      plazaMetrics: "网页端可打开，但原账号 API 令牌已被站点重置",
      lastScanAt: "19:24",
      verifyState: "blocked",
      verifySummary: "✕ 扫描未通过：Key 401 失效，已自动阻断任务验证以免产生无效告警",
      verifyTone: "rose",
      verifyDetail: "建议操作：前往站点刷新 Key 或在「查看资源」中直接补新 Key。"
    }
  ],

  /* 实际任务验证模板 (Stage 2 Task Verification Templates) */
  verifyTemplates: [
    {
      id: "tpl-reasoning",
      name: "强模型 · 推理与防降智探针",
      targetTier: "强模型 (Opus / GPT-5.2)",
      costEst: "约 1,200 tokens (~$0.015)",
      desc: "检验原生 Thinking 签名有效性、多步反直觉逻辑陷阱与嵌套 Tool Call，精准识别「模型广场绿灯但背后套壳降智」。"
    },
    {
      id: "tpl-codediff",
      name: "强模型 · 真实代码 Diff 修复实测",
      targetTier: "强模型 / 主力编码模型",
      costEst: "约 1,800 tokens (~$0.018)",
      desc: "输入含并发 Bug 的 120 行真实代码片段，要求输出最小化 Unified Diff 补丁并校验 AST 语法正确性。"
    },
    {
      id: "tpl-exec-throughput",
      name: "执行模型 · 16k JSON 抽取与吞吐压测",
      targetTier: "执行模型 (DeepSeek / Haiku / Qwen)",
      costEst: "约 16,500 tokens (~$0.004)",
      desc: "测试长上下文截断阈值、首字延迟 (TTFT)、流式生成速率 (tok/s) 及严格 JSON Schema 遵循率。"
    }
  ]
};
