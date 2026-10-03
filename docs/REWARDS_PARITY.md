> 2026-10-03 更新：原部署启用的八项（daily、extra、punchcards、desktop_search、more_promotions、claim、app_daily、app_promotions）已全部绑定独立 CLI。APP 使用已有会话 OAuth；状态在仓库外持久化。当前实测与仍未确认部分见 [实现验收记录](IMPLEMENTATION_ACCEPTANCE_2026-10-03.md)。下文保留历史能力和开发检查点，不能把原本未启用的实验能力当作本次迁移已完成。

# Rewards 能力与障碍处置对照（重写前基线）

更新：2026-10-02。目标是降低同时存活的浏览器、页面、无界数据和空闲进程开销，**不以删减业务能力换取轻量**。本文件是代码/回归映射，不表示尚未迁移的功能已完成。

## 1. 证据基线及未知项

- U：TheNetsky/Microsoft-Rewards-Script v4.3.2，提交 `f61f4e982bbb435f37133bed0dc5b4c582ed1e73`，文件链接基址 https://github.com/TheNetsky/Microsoft-Rewards-Script/tree/f61f4e982bbb435f37133bed0dc5b4c582ed1e73/src
- P：原私有部署 `qinglong-benefits-deployment-private`，提交 `6cf48f1b9dfbe87677c401ca3253b3ec40d88359`，主要为 services/rewards/{worker,audit,daily-activities,extra-activities,summarize}.cjs 和 README.md
- S：原 GPL 快照 microsoft-rewards-snapshot，提交 `f3983e1c6315e994629d23866a744b8f3e44db9b`，snapshot.cjs
- U 是可审查的官方候选版本，不是旧 NAS local image 字节等同证明。旧部署实际启用的完整 config.json 未在这批源码内提供；不能把 U 默认配置当成旧用户设置，也不能因此删除 U 存在的能力
- P README:35–37、64–70 明确：每日活动 UI 替代原生 doDailySet；其他原有任务仍由完整上游执行；extra 每主题最多两次搜索；目标仅选择手动兑换；前后快照与全量任务入口保留

下面“保留”表示需求/实现方向；只有标注“已实现+测试”的行才是当前完成内容。

## 2. 业务能力覆盖

| ID | 原业务及源码证据 | 重写保留方式 | 当前状态 / 回归映射 |
|---|---|---|---|
| C01 | P worker:12–20：before → daily → extra → upstream → after → summary；daily=3/3 不是全量完成 | 单次入口顺序阶段，各阶段独立结果，最后按当前有效全清单聚合；部分失败不丢已证实事实 | full.cjs 已实现显式能力清单、顺序执行、前后观察、有界报告和partial聚合；未绑定的请求能力明确pending，可信宿主CLI桥及全部业务仍未完成 |
| C02 | P daily-activities：Dashboard 活动展开、可见卡片、popup、积分读回 | 保留 UI 路径，避免原 reportActivity ACK 假完成；已完成不再点 | 已实现；rewards-activities.test.cjs：already complete、one click/readback、失败无重放 |
| C03 | P extra-activities：SocialMedia 卡片，明确 TikTok/YouTube/Rewards 目标；确认该 offer 完成 | 保留已有导航行为，不发帖、不点赞；限定来源与 URL；逐项读回 | 已实现；rewards-native.test.cjs：social flow、destination guard、unknown eligibility |
| C04 | P extra-activities：Explore 激活 + 8 类主题，每类最多2个查询，去重，不在手机/电脑阶段重复执行 | 保留主题、激活、查询、读回和上限；按 offer ID 去重，与常规搜索分别记账 | 已实现基本流程；缺完整 Explore 分支模拟与真实验证，不算已验收 |
| C05 | P extra-activities / README:70：设置兑换目标，只选 Track and manually redeem；可自定义官方 SKU | 必须恢复这一原有能力：准确目标/既有状态检查→需要时请求该设置授权→执行手动兑换选项→读回；不启用 auto-redeem，不提交订单 | goal.cjs 真实目标控件绑定及5个fixture已实现：可信授权缺失、已有目标、手动选项缺失、Next超时读回、URL拒绝；extra已接入。可信授权调用方尚未部署，CLI只生成待处理checkpoint |
| C06 | U search/SearchManager:19–69、BrowserSearch:30–203：desktop/mobile Bing quota 搜索、更新 counter、边界条件 | 两平台都保留；按用户原配置启用；顺序 context 而非两浏览器并行；每次动作后读回，终止于完成/明确上限/停滞状态 | 基本独立driver已实现，desktop/mobile/Edge、无积分/提交不确定/重复词/延迟counter已有fixture；真实设备/会话/现场验证与完整编排仍pending |
| C07 | U SearchProgress：桌面与 Edge quota 分离；BrowserSearch PointsTracker | 保留真实分项，不把缺失/null 当0完成；Edge 搜索 bonus 与 Edge duration 分开 | 严格 counters 与桌面/Edge拆分已实现；仍需真实账号读回证明 |
| C08 | U BonusTracker、BrowserSearch.doBonusSearches：额外搜索 offer 与 maxSearches、offer 消失、停滞上限 | 保留可配置额外搜索；限定当前 offer，offer 消失→重新获取/未知，不伪造完成 | 待实现；保留接口和覆盖项，不能直接关闭为节省内存 |
| C09 | U MorePromotions、PromotionActivityRunner、UrlReward：URL reward / SearchOnBing 分类，资格/零积分/未来日期检查 | 保留完整分类及账号资格；只省略重复的自定义 Explore；零积分/试用类仍按原显式设置处理，不猜测订阅或付款授权 | 待实现；当前 extra 只覆盖一部分，不能冒充 MorePromotions |
| C10 | U PunchCards；P audit：仅 onboarding 指定 parent，可领取 child、search quota child、missing hash | 保留旧私有白名单与父子任务关系；不放大到所有 punchcards；领取与任务完成分开读回 | punchcards.cjs/server_actions.cjs 独立mode及10项fixture已实现：父白名单、子资格/搜索延期、claim开关、journal、延迟/超时、协议路径；现场验收pending |
| C11 | U ClaimBonusPoints：reportClaimAllPoints；ClaimReward：child reward | 恢复待领积分和已授权奖励领取；只有 ACK 不足；前后余额、pending 或 child 完成读回，未知不重放 | child claim 已由punchcard开关和逐项读回实现；全局pending-points claim缺少可归因待领/完成字段仍pending，不能用ACK或余额变化替代完成 |
| C12 | U ActivateSearchPerk：倍率 perk 识别、当前 live offer、reportable/已激活 | 保留；按当次资格/已启用去重，明确账户设置/动作授权边界 | 待实现；perk missing/already active/no action ID/ACK-but-unconfirmed |
| C13 | U EnsureStreakProtection：已开启/剩余0/功能未发现/设置后读回 | 保留合理防断签设置流程；请求需要的设置授权，幂等检查优先 | 待实现；未知页面不点击通用 primary button |
| C14 | U app/DailyCheckIn、AppPromotions、AppReward、ReadToEarn：APP token、签到 type103、活动、文章读取 | 不删除。能力按需加载，复用当前有效认证；token 失效进入认证恢复而非假成功；手机/HTTP阶段不常驻浏览器 | app.cjs 实际HTTP/caller API及10个fixture已实现：token缺失/失效、sapphire活动、journal、未知完成、限额/限流、最多10次阅读/停滞。type103提交后归因证据缺失保持unknown；APP CLI/认证恢复调用方及全链路pending |
| C15 | U VisualSearch：图像搜索及 Browser helper | 保留为按原配置启用的可选能力；记录图片来源与运行前提，不强制加载图像/模型库 | 待实现；原部署是否启用未知，不擅自默认为开启 |
| C16 | U experimental/{ApiSearch,ApiSearchOnBing,EdgeBrowsing}：明确 experimental/unsafe 提示 | 不默默删接口，也不默认启用或把原本排除的 Edge duration 加入成功目标。保留原配置/风险确认边界；与正常 browser 搜索独立 | 尚未核实旧部署是否启用，作为可选能力待迁移；不能声称官方所有实验功能是旧业务范围 |
| C17 | S snapshot；P summarize/audit：新鲜 dashboard/flyout、有限历史回退、balance delta、eligible tasks/blocked 分离 | 全类别记录完成/未知/受限/不适用；旧状态只有同 run 或明确当前时间证据才能回退；余额变化不单独归因 | snapshot 已实现部分；完整 summary/audit、pending claim/Edge分项待补齐 |
| C18 | U session/account/proxy/locale；P 文档：已有地区链路、r.bing.com 例外 | 保留账户/代理/地区参数，不改主机路由；每账号独立状态、顺序执行与最少浏览器数 | 隔离/锁已实现；多账号 orchestrator 和 mobile store / locale 迁移待补齐 |

## 3. 自动化障碍与合理恢复分支

| ID | 障碍/原处理证据 | 保留、整合或替换依据 | 新状态/回归要求 |
|---|---|---|---|
| O01 | U Login:178–866 的全状态机：EMAIL_INPUT/PASSWORD_INPUT/FOOTER_ACTION/SIGN_IN_METHOD_PICKER/PASSKEY_ERROR/PASSKEY_VIDEO/KMSI_PROMPT/LOGGED_IN/EMAIL_VERIFICATION_INPUT/RECOVERY_EMAIL_INPUT/ACCOUNT_LOCKED/ERROR_ALERT/2FA_TOTP/LOGIN_PASSWORDLESS/PASSWORDLESS_SEND_CODE/OTP_CODE_ENTRY/UNKNOWN/CHROMEWEBDATA_ERROR | 保留识别和合适恢复能力，不把所有失效状态永久折为 unsupported。优先复用已有登录态；凭据、passkey/安全因素、真实用户信息依安全流程交接。不得自动猜密码/验证码或扩大长期授权 | typed authentication obstacle + resumable checkpoint；逐个状态 fixture，完成后先只读验证两端会话 |
| O02 | Login:92–174：25次有界循环、同状态停滞；PasswordlessLogin：等待/过期/最多重发次数 | 保留有限等待、无变化退出；重发认证请求不是无害读，只在明确授权与仍需时触发，不无限骚扰 | auth_pending/auth_expired/auth_stagnant；fake clock 与取消/超时/迟到回调 |
| O03 | EmailLogin/GetACode/TOTP/RecoveryEmail：旧新 selector、输入/提交、非TTY、手动输入超时 | 保留选择器与反馈分支；凭据由安全 handoff，不落普通日志或 checkpoint。缺少必要值明确等待，不填虚构值 | interaction_required（具体字段类别，不保存值）；控件缺失/错误提示/重复提交测试 |
| O04 | Login.finalizeLogin/verifyBingSession:867–1015：Rewards SSO→Bing home、#id_n、最多5次核验；原有 assume valid / continuing anyway | 保留 redirects/双端会话核验；移除“未验证也当有效”的错误判断，不移除恢复能力 | session_partial/session_expired；redirected success、其中一端失效、循环重定向 |
| O05 | MobileAccessLogin + Login.getAppAccessToken：OAuth/APP token 引导 | 按需加载认证组件；既有 token 可复用，失效时走授权恢复，不持续启动第二浏览器。不把 token 创建/新权限当普通重试 | token_expired / permission_required；scope变化、跳转完成、超时 |
| O06 | BrowserUtils.tryDismissAllMessages:14–89：cookie、欢迎页、Skip for now、泛化 Accept/Next/Primary并行点击 | 保留明确非绑定 cookie/欢迎遮罩消除；**替换宽泛按钮并行点击**为按页面语义单步识别。新条款、年龄、账户更改不是普通遮罩 | cookie_notice 可按既有规则处理；terms/age/account_change 请求准确授权/真实数据；控件同名误点回归 |
| O07 | 原 Rewards 未找到通用 CAPTCHA 求解模块；当前 common.guard 只检测 challenge iframe 等 | 增加可恢复 challenge 分类、来源识别、能力插件契约；不得把“检测到”伪装成“已有成熟求解”。在获得该挑战/范围授权后才加载/调用插件；完成后重新读状态 | challenge_detected/approval_required/challenge_retry/verified；未授权零动作、批准对象变更、失败/过期/重新出现 |
| O08 | 新条款、年龄提示可能被旧泛化 Accept/Next 涵盖，未有独立可靠语义验证 | 保留解决阻碍的目标，补正确 gate：确切协议文本/链接指纹；年龄用真实已提供信息；变更则重新确认，不把许可文件存在当用户授权 | terms_changed/age_required；exact grant、过期、账号/目标错配、真实值缺失、读回失败 |
| O09 | BrowserUtils.reloadBadPage:112–133，Login CHROMEWEBDATA_ERROR；BrowserSearch refresh | 保留只读坏页重载和有限重新导航；上一操作若写入不确定，先 reconcile，再决定是否可重试 | navigation_failed / reconciliation_required；网络错误页、空页、write timeout后已成功 |
| O10 | BrowserUtils.getLatestTab/closeTabs；P popupPromise、finally关闭；分阶段上下文 | 保留 tab/popup回收、主窗口替换、迟到 popup 处理；只操作所属 context，不关用户其他浏览器 | popup_missing/late_popup/context_lost；parent早退/弹窗超时/关闭异常 |
| O11 | P daily：DOM标题中英匹配、折叠 section、progressbar null；U React/Flyout映射 | 保留中英别名、展开、最新 aria/React/flyout；缺字段/新枚举不是0/0。超过上限应unknown，不截断后报complete | layout_changed/inventory_incomplete；已通过 null、unknownenum、overflow fixtures；更多 locale 待补齐 |
| O12 | U Locale、UserAgent、proxy；P README:68 地区一致性，extra拒绝 Bing region redirect | 保留明确账号区域/语言与代理参数；检测不一致，不自动改VPN/主机规则或虚构地区。用最新读回区分重定向与限制 | region_mismatch；同账号不同region、proxy断连、重定向成功/越域 |
| O13 | Browser launch/native libs、saved fingerprint；SessionStore 过期Cookie清理与独立 platform | 保留可复用状态与有界持久化；旧有效 state 在新验证失败时保留，不静默清空/重建；不混账号/设备 | dependency_unavailable/session_schema_mismatch/profile_incompatible；缺浏览器/损坏JSON/迁移中断 |
| O14 | BrowserFunc.bootstrap:273–497：earn+dashboard、RSC chunks、buildId、action ID；UrlReward无 action/hash跳过 | 保留动态协议解析和只读刷新，不硬编码过期 action ID；解析器已独立提取，不导入整个应用 | protocol_changed/action_id_missing；合成 flight/chunk、未来offer、missinghash、同run刷新 |
| O15 | BrowserFunc.checkpointActiveSession/synchronizeActiveBrowserCookies/applyResponseCookies；index.refreshCurrentRewardsContext | 保留 cookie/session同步和一次安全修复；修复后重新核验，不把刷新成功当业务成功 | session_repaired/reconciliation_required；cookie轮换、过期、失败不覆盖有效快照 |
| O16 | Http.send 默认三次重试；UrlReward.retryAfterRequestFailure 重新认证后再提交 | 保留网络恢复目标，**替换无区别写重放**：读请求可有限退避；写超时/429/5xx先查业务状态，只有确证未执行且授权仍有效才重试 | action_uncertain/readback_pending/retry_eligible；请求到达后超时、不确定ACK、读回失败，不新增二次领取 |
| O17 | P每日活动10次读回、extra4次确认；U AppReward/ClaimReward/ClaimBonusPoints 余额+ACK | 保留异步入账等待，分离 submitted/acknowledged/credited；单次balance delta可能混入用户活动，不能单独归因 | delayed_credit/credit_unconfirmed；先无积分后到账、ACK无到账、他处余额变化 |
| O18 | BrowserSearch max/stagnant/queryAttempts；P audit把stagnantLimit限3；BonusTracker offerLost | 保留合理节制和停滞退出，已到上限不继续；offer消失/未知不能假完成；无积分时不无限搜索 | quota_complete/stagnant/offer_changed/deferred；预算用尽、连续零收益、返回counter倒退 |
| O19 | SearchQueryQueue/QueryEngine：词池、去重、外部词源fallback；P不逐次GitHub下载词 | 保留可用词源与去重，优先本地/按次缓存；不可用则有限回退，不运行下载常驻服务 | query_source_unavailable/exhausted；空词池、重复词、网络源不可用 |
| O20 | MorePromotions/React/PunchCards：锁定、未来日期、zero points、unsupportedtype、父子quota/claim | 保留资格过滤和原允许列表，未知资格不会扩大授权；缺失和not_applicable分开。unsupported新类型成为明确待支持能力，不静默忽略 | eligibility_unknown/restricted/future/unsupported_variant；新枚举、父子关系缺失 |
| O21 | index:665–700、FlyoutDashboard.detectFlyoutBotWarning：bot warning、折叠配额 | 保留风险停止/冷却提示与只读再检查，不自动“绕过限制”或更改地区继续刷；保留当前业务事实 | account_restricted/cooldown；restriction优先于缺积分、解除后新鲜核验 |
| O22 | P goal：手动兑换 radio确认、Next/Okay、reload toggle核验；绝不 auto-redeem | 保留目标完整流程，恢复当前临时blocked的能力；只针对明确授权目标与手动兑换选项，变化即暂停 | goal_change_required/goal_already_set/goal_unconfirmed；自动兑换选项不能被误选 |
| O23 | P worker重启不重放running；launcher timeout/groupcleanup；结果run_id/schema/date | 保留残留/中断审计、过期任务拒绝；不靠进程exit0判成功。恢复从checkpoint只读再核验，不能直接续点上次按钮 | interrupted/timeout/previous_action_uncertain；跨日、旧run结果、SIGTERM/leader提前退出 |
| O24 | U Logger/diagnostics/webhooks；P现有集中日报不额外通知 | 保留必要可观察性和日报信息，不把关闭重复外部通知称为业务删减；失败证据脱敏/有界，保存策略显式 | result/report schema +有限证据；未知供应商异常不带密钥/URL token |
| O25 | Browser.ts sandbox/TLS ignore选项、BrowserUtils.disableFido | 不默认移植降低安全性的实现：保持sandbox/TLS；用正常账户方法选择/用户handoff解决passkey，不篡改身份能力请求。不是移除认证恢复能力 | security_sensitive_change_required；不得以本机测试失败为由关闭安全保护 |

## 4. 统一恢复与授权边界（与 common/interventions 对齐）

1. 探测只读状态并确定具体 obstacle/capability/action，而不是整个任务只输出 generic human_required
2. 保存小型 checkpoint：run/账号/阶段、动作目标与指纹、有限证据、已确认业务事实、过期时间、恢复时需执行的只读核验。不存 Cookie、密码、token、年龄值或完整网页
3. 若动作不需要新授权且可安全恢复（只读刷新、关闭所属弹窗、明确非绑定 cookie banner），做有限恢复
4. 涉及 CAPTCHA、确切新协议、年龄真实信息、新持久权限、凭据输入等，交由对应授权/安全handoff。可选能力插件只在获得可信授权器确认后按需加载；不常驻加载模型或浏览器
5. grant 必须匹配当前账号/目标/动作/指纹且未过期；普通 JSON 文件不能自行证明用户批准
6. 恢复时先只读重新探测；页面/协议/挑战变化则旧批准不覆盖。已执行但结果未知先查业务事实，不能无条件重放
7. 能力模块产生具体结果；主入口再基于完整请求范围判断是否完成。尚未迁移的能力必须列为 pending，不因为某个 mode 成功就隐藏

## 5. 当前回归与待补齐清单

第四轮新增25项 Rewards Node离线测试；总数以最新测试输出为准；独立 parser 与可重复 upstream 构建对照通过；所有测试使用合成/本地数据。

当前有现成覆盖：每日卡片、popup关闭、单次点击、空/缺失/未知资格、重复inventory、超过30项拒绝、精确来源parser、状态文件上限、challenge/login停止、进程/锁/超时、原V2EX行为等。

当前 desktop/mobile 的独立本地fixture已有覆盖，但**尚无**完整 Rewards/APP/punchcard/claim/goal现场恢复链路验证，新增typed checkpoint与可信授权恢复也尚待集成。不会把这些写成完成或永久删除。后续实现顺序：类型化障碍与断点→完整阶段清单/结果覆盖→desktop/mobile搜索→claim/goal/punchcards→APP/原配置可选能力→全链路延迟/重入/资源回归。

真实账号/认证/验证码/条款/年龄/领取/搜索及NAS部署仍未执行；到真实执行时按具体动作取得对应授权。


## 6. 2026-10-02 审阅修复

已补真实绑定/入口回归：默认7000条搜索词库进入有界队列；punchcard的搜索/claim分类元数据不再在binding投影中丢失；缺失action ID在journal之前拒绝；同chunk冲突ID拒绝；future extra不提交；snapshot及原生动作共同识别BotScore限制；extra后续阻碍保留已确认分类；full逐阶段保存标准中间结果，以便监督者保留同run已确认事实。

full按enabled所需设备预检并懒加载parser；APP-only可信调用方不再依赖桌面会话/Chromium/快照。普通CLI没有可信APP客户端时仍pending，不能将缺少binding改为完成。每日APP/read journal限定当前业务日最多11项、拒绝日期倒退，并保留旧journal的当天不确定提交；多日promotion journal不按天清空，仍有明确容量/恢复限制。

仍未进行现场业务验收。这些修复不代表新增APP授权桥、验证码执行器、完整能力迁移或NAS上线。
