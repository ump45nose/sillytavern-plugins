# 原生实现检查点（以下保留分轮历史）

当前：Rewards full 已改为显式能力清单驱动的原生顺序编排；缺少清单不执行，未接入的请求能力明确pending。APP/目标有可信调用方接口，CLI授权桥与完整业务/真实端到端仍pending。Epic公共claim仍未开放。下文早期轮次中的“full门禁”等描述是历史状态。

## 已完成并离线验证

共享标准库 runner、六个独立目录/入口、环境白名单、同账号 flock、跨平台 browser flock、总超时/中断进程组清理、流式有界日志、精确凭据脱敏、严格结果身份/大小/schema、原子发布、独立签到确认缓存和未知收益退出码。

SMZDM：复用原签名/请求顺序；已签到、验证码、风控、查询失败分别表示。写请求不自动重试。签到后读回失败仍保留签到确认，奖励标记 unknown。

V2EX：从 MIT 的 dailycheckin 25.12.9 单独提取 V2ex.sign，保留原许可证和 wheel/module hash；避免其 __init__ 全平台 eager import。假 Session 与原函数对照验证已签到、新签到、无效 cookie 三条路径。旧 provider 会传 verify=False，新 BoundedSession 强制证书验证。日期判定保留 Asia/Shanghai。最小 HTTP 依赖锁固定 requests 2.32.5 和传递依赖，独立 venv 安装；不再依赖整个 dailycheckin/RSA/PyCryptodome。

Aliyun：外部 daily.py 取自 WillpowerJin/ql-scripts，候选提交 37f42204a8eea3a489e67e866a2b356bed4b9b22；SHA256 286563810a780f06edaa0eea2dd0633480b403d6634ab3357d0890df77b696c3。完整源码未再发布（该来源无明确 LICENSE）。仅验证字节后导入，cookie 登录、签到、明确资格的领取、积分读回；不调用上游 main/run、通知、清理、视频或场景互动。ALIYUN_UPSTREAM_PATH、ALIYUN_COOKIE、ALIYUN_PROXY 是入口环境变量。未验证真实 API。

Laowang：原签到读回、持久 profile、只读 status；人工 login 支持受监督 TTY stdin 并持有双锁。已尝试本地真实 Firefox smoke：官方 fallback 下载成功，Firefox155/revision1543 启动后报 Could not find profile folder，在 /tmp、共享目录与独立 HOME 均复现；未通过浏览器验收。未执行 GUI 登录。验证码自动求解已从活跃路径移除，默认停止交给人工。

## Epic 的具体阻塞

已有确切上游源码候选与文件 hash；原生 preflight 不导入未知应用、不启动服务器。已有 AST 必需方法检查、零价/购物车纯函数测试。

执行前仍须解决：

1. settings.py 导入模型配置及补丁，默认创建源目录 volumes；统一外部账号 state/evidence 路径
2. browser_context 默认录屏且支持 Camoufox→Firefox 后备及虚拟 Xvfb；需关闭默认录屏，证明上下文/Xvfb 全生命周期和本地页面 smoke
3. 上游认证/订单路径能自动触发 CAPTCHA、条款和 SSO 页面动作；需审查全部调用链并默认 human_required，不能只补丁三个方法就宣称覆盖
4. 完整 uv.lock 安装、Python/native/browser 版本和有许可证的上游组合确认
5. 订单提交、全部零价路径、已有购物车保护、最终所有权读回的完整 mocked integration

当前入口明确返回 native_paths_challenge_and_checkout_audit_required。不会领取、登录、支付、解验证码或调用模型。

## Rewards 的具体阻塞

已取得官方 v4.3.2 候选 f61f4e982bbb435f37133bed0dc5b4c582ed1e73（GPL-3.0+），这不能证明它与旧 NAS local image 内容完全相同。官方要求 Node >=24。已有 package/source hash 和资源配置验证器，严格区分 null/0/未知资格/真实空清单。

执行前仍须解决：

1. 证明旧私有适配器与候选上游的 ReactFunc、audit 类/方法及 sessions SQLite schema 完整相容
2. 固定依赖安装+构建 dist，禁止运行时猜测缺失模块
3. 账号明确单选；clusters=1、searchSettings.parallelSearching=false、clusterSearch=false、headless=true、workers.doDailySet=false 的完整运行配置验证；关闭外部 webhook/通知
4. 将旧 before→daily→extra→upstream→after 顺序迁到一次性脚本，全部 state/evidence 路径外置，并逐段确认前一浏览器退出
5. 原 snapshot/daily/extra 对完整 body/HTML、长日志、history 的无界写入需要替换；summary 纯函数不能冒充完整任务
6. 本地 SQLite/schema/React fixture、浏览器 smoke 和 upstream 内部并发测量

默认 full 入口明确返回 session_schema_build_and_browser_serialization_audit_required，不会运行完整上游。新增显式 --mode activities：独立单浏览器每日活动卡片流程，读取每账号 storage-state.json，null 进度停止、卡片/循环有界、一次点击后只读回、关闭 popup/context/browser、Chromium sandbox 开启。8 项假浏览器/SQLite/计数测试通过。不会搜索、extra、通知；daily complete 仅表示每日活动，不表示完整 Rewards。尚未真实浏览器/账号验证。

## 尚未完成的公共验收

- cgroup 硬限制、脱离进程组的 child containment、launcher SIGKILL 后自动全树回收：未实现，不能作保证
- 总历史/日志保留数量、每日汇总、CookieCloud 原生同步：未实现；不会擅自删旧数据
- 真实浏览器/账号、峰值 RSS/PSS、长时残留、NAS 架构及代理路径：未验收
- 调度安装、旧容器停用、会话/凭据迁移：本轮未执行


## Rewards 第二轮检查点

已补齐显式 snapshot（只读）与 extra（选定社交/Explore）模式，默认 full 仍保留执行闸门。snapshot 不登录或领取，只读认证 dashboard/flyout；extra 只处理当前明确 unlocked 的已知活动，目标设置始终 blocked，不发外部内容。原始 Main 的完整自动任务未包装。

build.py 对固定全部相关源码 hash 验证，复制到全新外部目录，去掉自主 main，使用原 package-lock 安装168包。TypeScript 6.0.3、Node24.19.0、--module Node20 --moduleResolution Node16 编译+资源复制成功；按完整配方再次构建的 dist 文件 hash 与首次构建一致。模块导入测试阻断 Node 网络和 subprocess，真实 React parser 合成页面通过。未执行上游真实任务。

新增平台说明列出精确构建调整与剩余设计选择。仍未验证当前真实网站/浏览器。Main 的多个潜在兼容替换会增加维护成本，已暂停大范围替换，等待是否转向选定能力轻量重写的决定。

进一步提取：独立 React parser 的生成 JS 无 runtime require/import，已连同原 TypeScript、source map、GPL-3.0 许可和来源证明纳入 vendor/rewards-parser。extra 日常运行不再要求完整上游 build 或168依赖；完整构建只是开发验证。

## 用户确认的后续方向

以独立能力重写并保留原方案合理业务/障碍恢复，内存优化不允许静默删减能力。此前 blocked/限定 mode 是未完成的阶段状态，不是最终减配决定。完整 Rewards 能力、障碍、保留/整合/替换理由与回归映射见 REWARDS_PARITY.md；目标设置、desktop/mobile搜索、APP、claim/punchcards、恢复授权等逐项补齐。


## 第三轮开发检查点：组件与现场绑定分开

Rewards新增独立desktop/mobile搜索执行逻辑及模拟场景，严格desktop/Edge/mobile配额、本地/聚类词队列、延迟入账、停滞、预算、未知/倒退、输入超时只读核验不重放；移动场景需自己的有效state和设备元数据。默认full入口仍有闸门，因为完整编排、claim/APP/punchcard/goal与现场恢复处理器仍未全部接通。

通用interventions只核对请求/可信调用方决策的范围与时效；Rewards子进程信号桥限制8KiB、官方域名、当前run/account/capability、TTL，无任意JSON授权执行。typed障碍/恢复计划已可离线测试，但没有虚构真实solver、条款、年龄或认证插件已可用。

Epic新增可执行的注入driver工作流、当前免费catalog解析、只读purchase candidates、storefront ownership判定及懒加载障碍处理生命周期。40项Epic纯组件测试覆盖已有库、两种checkout驱动契约、零价/已有购物车、提交前journal、模糊提交只读回、不重放、协议/挑战/年龄授权后重探测、部分结果等。真实browser driver、真实挑战提供器和执行入口尚未接通；public claim gate保留，不能称Epic领取完成。purchase历史候选不等于当前持有权。

任何已有confirmed journal与当前unknown/not_owned矛盾都不自动再次提交；缺失promotions/无效discount/不完整库存保持unknown。账号登录、领取、搜索、CAPTCHA、新协议、年龄、NAS改动均未实际执行。

Epic另外有懒加载HCaptchaHandler兼容桥的合成loader测试，复用原AgentV.wait_for_challenge调用契约；没有在模块导入时加载模型/读取API密钥/联网，仍需可信授权及注入配置。真实provider/browser绑定、拖拽/GLM扩展仍pending；不能据此声称现场验证码已解决。

## 第四轮进行中

Rewards新增原onboarding白名单punchcard的真实浏览器/Next-action绑定（单独mode），提交前持久journal、超时读回、禁止盲重放；APP保存token的调用方HTTP绑定和任务读回；原手动goal浏览器流程及可信授权回调接口。新增25个Node离线测试。APP、goal的授权调用方和完整full编排尚未接通；type103签到目前无法从上游响应获得可归因完成证据，保持unknown。旧任务能力继续按矩阵补齐。

默认单次总预算恢复为旧部署初始值：SMZDM180、V2EX240、Aliyun480、Laowang360、Rewards7500、Epic1300秒。不是测量得到的最优值；可显式覆盖，阶段/重试不另起预算。内存优化依靠顺序执行和关闭资源，不缩短原业务窗口。

本轮另尝试 Rewards 官方 patchright Chromium1228 下载；其官方CDN连续返回无法解压的0MiB内容，安装器有限重试后失败。tests/rewards_browser_smoke.cjs 已准备为本地HTML/阻断页面网络的真实浏览器smoke，但Chromium未安装，尚未运行。没有关闭sandbox或修改系统安全设置。

Epic本轮增加具体Playwright对象驱动：官方catalog读取、storefront所有权、即时/购物车checkout路径、零价与匹配offer证据核验；文本/控件溢出拒绝。共50项Epic离线fixture已通过。非空购物车的语义价格读取器与checkout具体商品身份读取器仍需现场绑定，未绑定就unknown；公共claim入口仍有门禁，尚无真实浏览器端到端验收。


## 恢复后的原生编排检查点

云执行环境重建后，从私有GitHub连接器恢复 checkpoint 915211b，逐个验证112个blob、完整tree及原commit哈希；旧依赖缓存、浏览器下载与外部上游构建目录并未恢复。重写未提交的full编排并补齐初始快照timeout/busy停止、desktop状态前置校验两项审阅修复。

本轮16项编排fixture覆盖严格manifest、顺序执行、partial保留、缺失绑定、快照不覆盖业务、阻碍/超时停止、可信调用方前置账号状态、成功session仅进程内传递。真实浏览器/平台端到端、完整宿主授权桥及剩余能力没有因此变成已验收。


## Laowang tncode 恢复检查点（待审阅分支）

已恢复原MIT实现的具体像素匹配与滑动/响应处理，按需加载，先由可信宿主验证当前挑战授权。图片重新观察、低置信度停止、精确来源/响应核验、最多两次拖动跨重启预算、签到前后只读核验和意图记录均有离线回归。17项新增Node用例及Laowang checkpoint范围测试已加入。

普通CLI的真实授权传递仍未接通。正常跨进程恢复没有来源证明：只在新鲜base页面实际仍有挑战和唯一提交控件时，才允许按新授权继续；假页面测试不证明站点会保留该页面。不确定拖动/提交只读核验、不重发qiandao。未访问平台或解决真实验证码，不能把这一批称作完整业务验收。详情见 platforms/laowang/README.md。


## 2026-10-02 架构审查修复检查点

已修复一次性运行器业务结果保留、浏览器后代回收与不确定清理阻断、各平台动作级恢复、Rewards 输入及元数据/状态边界、HTTP 有界读取、Epic/Laowang 挑战及只读核验边界。独立复审的三项补充问题也已修复。

最终本地全套 187 项 Python 和 163 项 Node 测试通过、无跳过，Ruff/Prettier/diff 检查通过。具体范围与验证方法见 [本轮修复记录](FIX_STATUS_2026-10-02.md)。真实 Hermes 版本/交互入口待确认；真实账号、NAS 与浏览器现场能力仍未验收，不能称作生产闭环已完成。
