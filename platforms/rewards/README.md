# Microsoft Rewards

按启用清单顺序执行一次账号任务，阶段之间关闭浏览器，最后输出通用 JSON 和本次 `rewards-report.json`。Hermes 决定何时运行、如何汇总和推送。统一结果补充进度、余额变化、锁定数量和未确认任务明细，见 [结果契约](../../docs/RESULTS.md)；不把余额差当全天积分收入。

## 安装和账号状态

Python 3.12、Node 24、patchright 1.61.1 和原生 Chromium。保留 sandbox，不导入上游 Main 或其通知/数据库/账号扫描代码。

```sh
cd platforms/rewards
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --ignore-scripts
npx patchright install chromium
```

在仓库外的 `state/rewards/<account>/` 准备 `storage-state.json` 和 `capabilities.json`。NAS 当前启用简单每日活动、搜索、APP 和桌面 App 等已验收项目，停用不记分的探索阶段：

```json
{"schema_version":1,"enabled":["daily","punchcards","desktop_app_weekly","desktop_search","more_promotions","claim","app_daily","app_promotions","daily_streaks"]}
```

可选 `native-config.json` 保存已有稳定地区/设备和搜索配置，例如：

```json
{"region":"US","language":"en-US","search":{"maxSearches":100,"stagnantLimit":3,"delayMs":30000}}
```

请用账号实际地区；不根据示例改变地区。凭据文件不进 Git。

NAS 的微软服务分组选中 DIRECT。2026-10-19 用户确认 Rewards 使用 HK 地区，`www.bing.com`、`rewards.bing.com`、`edgeservices.bing.com` 使用三个显式线路特例。2026-10-20 香港 02 当前路径反复 TLS 失败，已在 HTTPS 及真实账号浏览器验证后，将这三个特例切至既有香港 01；其余微软服务继续遵循原分组。规则由仓库外 ShellCrash 管理，私有地区配置保持 HK，Cookie、token 和任务 journal 继续复用。每日活动及 APP 快照兼容当前香港页面的繁体标签。

```sh
REWARDS_ROOT=/absolute/project/platforms/rewards \
REWARDS_PROXY=http://your-existing-proxy:7890 \
python3 platforms/rewards/run.py --runtime-root /absolute/private/runtime \
  --execute --browser-cache /absolute/browser-cache
```

## 能力与确认

- `daily`：只执行简单 URL 活动。按平台目标中的交互任务标识排除测验与投票，兼容官方 checkuser 跳转；排除项报告 `not_applicable`，不访问目标页、不答题。简单活动复用现有 `reportActivity`，绑定当前 hash、action ID 与部署身份，提交前保存独立的 `report_<offerId>` intent，按同一 offer 的平台完成标记读回确认。旧卡片浏览 intent 保留，未确认上报不重放。每日进度只统计当前范围内的活动，不能当作平台整组 3/3 完成。
- `extra`：保留社交、已配置目标和探索必应的独立入口。NAS 正式能力清单已按成本决定移除该阶段，不再自动执行探索、不因其未记分产生日报异常；历史激活、查询与未确认记录保留。
- `desktop_search`：读取当前账号桌面额度，未满时搜索、等待入账，达到额度或连续停滞则退出；已满不重复搜索。账号、设备和日期各有查询 journal，发出前记录，当天重跑跳过已提交查询，次日重新允许。
- `punchcards`：旧部署白名单 onboarding 任务；完整清单没有分配该任务时不适用。不会把其他任务组冒充同一任务。
- `desktop_app_weekly`：按用户授权模拟桌面 App 请求，复用现有 Cookie、地区、代理与 HTTP 客户端，在原设备 User-Agent 后追加官方客户端 `MSRewards/Desktop/1.4.56` 标识。只处理当前 `RewardsApp_weekly_Exclusive` 周任务中的七个积分子项，跳过锁定项，不提交安装奖励或其它任务卡。当前页面的 action ID、部署 ID 与 hash 绑定；每项仅提交一次，对应子项完成标记与周积分同时读回才确认。按当前周卡持久保存 intent，未确认请求不重放。`complete` 表示当前已开放活动完成；周积分和未来锁定项仍单独保留，不代表本周 70 分已全部获得。无任务分配时为不适用。无需安装桌面客户端或启动 Chromium，资源实测见 [成本记录](../../docs/desktop-app-cost-2026-10-13.md)。
- `more_promotions`：当前可执行 URL 活动，当前 action ID 和任务 hash 绑定，发出前记录 intent。journal 按业务日期保存，避免循环使用的活动 ID 被此前日期的提交永久阻塞；迁移时保留当天已有 intent。
- `claim`：明确有待收积分时提交一次；无待收积分不适用。
- `app_daily` / `app_promotions`：通过已有浏览器登录进行 OAuth，token 存在私有账号目录；随后一次性 HTTP 客户端执行 APP 任务，不保留后台浏览器。APP 签到优先用当前页面进度确认，不能把 1000 分连续签到奖励误认作每日签到。
- `daily_streaks`：在日常阶段完成后核对必应、APP 两项连续打卡的当日完成标记、计数及连续天数。必应仍为 0/1 时，独立进行一次真实搜索并读回，即使桌面搜索积分额度已满；每日活动连续打卡依赖已停做的测验和投票，不再纳入执行与验收。未激活的 Edge、视觉搜索不在本阶段的执行范围。

每日测验与投票按用户决定停做，已删除专用答题执行器。简单活动上报失败时仍保留已观察到的进度、任务清单与脱敏诊断，完整报告不丢弃阶段返回的诊断；不能通过排除交互任务掩盖简单活动的真实失败。

桌面 App 周卡按数值读取进度，不依赖任务标签的页面语言。已完成卡片兼容 React Flight 的独立记录、嵌套节点和共享勾选图标引用；仍须逐天的明确完成标记与周积分共同确认，加载占位内容和缺失引用不能作为完成。已提交但未确认的周任务只做读回，不重放请求。

当前可见每日卡片与平台清单共同确定任务周期，结果以 `platform_task_cycle` 明细保存，完整报告的前后快照也保存 `cycle`。正式 `full` 入口的每日卡片、探索、更多活动、桌面搜索及必应连续打卡 journal 按该周期归属，业务日期仍按调用方时区用于审计。跨周期调用不能把上一轮完成当作新一轮完成；完整任务期间发生周期切换则返回 `full_task_cycle_changed`。已有 intent 保留，不删除此前记录。

Hermes 既有 Rewards 作业自 2026-10-13 起为北京时间每天 09:30、16:30：上午核查上一轮，下午处理平台重置后的当前任务；没有新增作业或通知入口。账号现场返回 HK，私有配置显式使用 HK 与既有英文语言，账号身份、代理、Cookie 与 token 保留。十月月卡、Edge 激活等其它新增项目按用户要求搁置。

完整任务在开始时也读取 APP 活动的当前清单。中途遇到验证码等人工处理条件时立即停止后续动作，但保留本次开始快照已确认完成的任务。APP 签到只有重新读取到对应页面计数完成后才确认，提交响应或余额上涨不足以确认；APP 授权与限流失败保留固定公开原因，不输出私有响应。

APP token 到期时，先使用同一登录 Cookie、代理和既有 HTTP 客户端完成 OAuth 跳转。只有官方回跳地址、随机 `state` 和授权 code 均有效且没有错误参数时才交换 token；需要页面交互时仍使用原浏览器和障碍检测。浏览器等待导航 commit，并在超时时核查真实回跳，不等待回跳页面的 DOM 加载。同一授权会话及其失败在完整调用内共享，避免快照与各阶段反复启动授权浏览器。已成功的会话在后续 APP 阶段前重新检查 token 有效期，临近到期时关闭旧 HTTP 上下文并通过原会话重新授权；不重放已提交动作。token 交换不自动重放，超时和导航失败有固定公开原因。

探索使用 [上游完整主题词库](https://github.com/TheNetsky/Microsoft-Rewards-Script/blob/f61f4e982bbb435f37133bed0dc5b4c582ed1e73/src/functions/bing-search-activity-queries.json)，固定 commit `f61f4e9`、GPL-3.0-or-later，共 74 个标题词条。原始 JSON 随源码保存在 `vendor/rewards-parser/src/functions/bing-search-activity-queries.json`，来源及 SHA-256 记录在 `PROVENANCE.json`；加载时校验字节摘要，无运行时下载或模型调用。匹配标题时清除零宽字符、统一大小写和空白；31 个稳定 offer ID 也映射到该词库，支持标题本地化。酒店、珠宝、房产、体育等新轮换任务可直接按上游标题匹配。未识别主题仍显示 `search_topic_unsupported`，每个任务最多使用词库中的 10 个查询，逐项读回任务自身进度。

搜索导航可能销毁正在读取的 DOM；仅对明确的导航上下文失效等待后重做一次只读 guard。登录、验证码等障碍仍立即停止，搜索 intent 和激活请求不重放。

APP 签到在正式 `full` 入口使用独立的 `app-checkin-journal.json` 记录轮次，发出请求前原子保存 intent。北京时间日期只作审计，不在午夜清除未确认提交。开始快照和签到阶段重新读取的对应 1/1 计数会持久确认当前轮次；之后只有两次独立页面读取（间隔 3 秒）均确认 0/1，才开启下一轮并允许一次提交。这样同一本地日的平台重置不再被旧日记录阻塞，长任务也会在签到阶段重新核查进度。单次旧读数、缺失计数、非 1 上限、POST 响应和余额变化均不能开启或确认轮次；不确定提交等待真实读回，不自动重放。

迁移导入 `app-daily-journal.json` / `app-journal.json` 中最近的签到 intent，并先持久保存，避免后续阅读任务轮换日记录时遗忘未确认请求。旧文件保持原样；阅读和 APP 活动仍使用原来的记录。新文件保留当前轮次及上一轮确认摘要，长度固定，不累积每日文件。没有可用页面签到进度的 APP 单独调用返回未确认，不提交。

搜索提交后遇到真实登录或验证码条件时保留具体原因并停止后续动作。导航超时或浏览器错误先只读核对额度，不重复同一次提交；完整回执保留各阶段的诊断条目。

积分 flyout 查询遇到传输失败或临时 HTTP 跳转时，最多请求原 URL 两次，不跟随跳转、不重发搜索。指向已知登录域时立即报告登录阻塞；持续跳转明确失败，并记录 HTTP 状态与脱敏路由分类，不保存 Location 或授权参数。

验证码 iframe 的识别只检查解析后的主机名和路径，不把 URL 查询参数中的 OAuth PKCE `code_challenge` 当作验证码。`#captcha` 标记和真正的 captcha/challenge iframe 仍会停止任务。仅凭 iframe URL 中出现单词 challenge 不足以确认验证码。

当前页面的活动提交使用 `/earn`，携带从当前页面读取的 `X-Deployment-Id`、action ID 和任务 hash；时区偏移取实际浏览器或已有显式配置，以字符串发送。缺少部署身份时停止提交，不自动重放 POST。2026-10-09 的实际浏览器请求及原生适配提交均已读回确认。

能力汇总只包含平台已分配、当前可执行的任务。平台明确锁定或不适用的项目保留在明细中；缺少授权、主题不支持或积分未确认的可执行任务仍报告未完成。

## 当前现场验收

2026-10-21 成本范围修复后的完整执行 `67bc4094-24a9-4ef0-a98f-9b5b6fdd377f` 返回当前启用能力全部完成：简单每日活动 1/1，电脑搜索 200/200、更多活动 100/100、APP 签到 1/1、APP 活动 4/4、必应与 APP 连续打卡完成。简单活动使用一次上报后独立确认完成，余额 76278→76288（+10）。测验与投票为范围排除，不代表已完成平台整组 3/3；探索阶段未执行，也不要求其积分。该运行使用正式 Hermes 身份和账号状态，验证分区独立保存，不手写正式 delivery。

合入后原 Hermes 调度入口复核 `4e711cca-2ebc-488d-91f2-d73bfcb2af8a`，正式 delivery 已自然更新为当前启用能力全部完成。每日活动仍 1/1、余额 76288→76288，本次没有重复上报；正式完整输出不再携带停用探索的未完成明细。

专属回归、合成浏览器夹具及构建冒烟已按用户要求删除；此前的用例数量不作为当前能力验收。逐项现场状态和未完成项见 [能力与现场验收](../../docs/REWARDS_PARITY.md)，历史排查证据保留在 [持续排查记录](../../docs/plans/2026-10-20-benefits-followup.md)。

## 操作节奏与诊断日志

默认按顺序执行：阶段间等待 2–5 秒；提交或点击前等待 1.5–3.5 秒；搜索框逐字输入，每字间隔 40–110 毫秒；搜索导航后等待 1.2–2.8 秒，入账等待 30–42 秒。每完成 8 次搜索，在下一次前休息 45–75 秒；活动页面轻滚动后停留 10–15 秒。已配置更长的搜索等待仍生效。APP 提交也有动作间隔，阅读任务保留至少 30 秒等待。额度已满或活动已完成时只读确认；搜索和网页任务在等待结束后重新检查页面障碍，再持久记录 intent 并提交。已有账号、设备、地区、代理及防重复提交规则继续使用。

`native-config.json` 可选 `interaction` 覆盖对应范围，单位为毫秒；无需配置即可使用上述默认值。`enabled:false` 关闭新增随机等待与逐字输入，但保留调用方原有安全等待。配置只接受以下字段，范围必须为两个非负整数，终值不小于起值：

```json
{"interaction":{"enabled":true,"stage":[2000,5000],"action":[1500,3500],"settle":[1200,2800],"typing":[40,110],"reading":[10000,15000],"searchJitter":[0,12000],"batch":[45000,75000],"breakEvery":8}}
```

每次实际调用在 `<runtime-root>/runs/<run_id>/rewards-events.jsonl` 写独立结构化日志，与该运行的 `result.json`、`rewards-report.json` 同目录。日志同步写入，开始事件在等待操作之前落盘；进程被终止时，可从最后一条尚无结束事件的操作定位卡住阶段。每行包含 UTC 时间、运行 ID、账号代号和业务日期，并按情况记录阶段、操作、耗时、HTTP 状态、等待时长、进度、授权缓存是否到期、错误分类、固定原因及 Rewards 源码文件/行号。浏览器启动、上下文、页面导航、OAuth 跳转与交换、API、提交 intent、读回、阶段和最终结果均有埋点；阶段边界附进程 RSS、系统内存、交换空间和负载。

日志最多 512 KiB，以 `0600` 创建；生产访问权沿用既有私有运行目录的 FnOS ACL。达到上限记录一次 `log.truncated` 后停止增长。仅允许固定字段与值，不记录 Cookie、token、授权 code/state、完整 URL、搜索词、请求体、原始错误消息或完整堆栈；活动/查询标识只存摘要。写日志失败只输出固定诊断提示，不改变业务动作或结果。排查时先看本次回执，再按同一运行 ID 查看 `error` 和对应的 `start`/`finish`，从而区分授权超时、网络/TLS、导航上下文失效、限流或业务未确认。完整回执还保留失败阶段的诊断条目；阶段抛出异常时，`stages.<capability>.diagnostic` 独立保存同一套脱敏错误字段，不受事件日志上限影响。

## 独立模式与边界

`--mode activities / snapshot / extra / desktop-search / mobile-search / punchcards / desktop-app-weekly` 可单独调用。snapshot 只读，结果按 mode 保存，避免覆盖 full 日报事实。

移动搜索需要自己的 `storage-state.mobile.json`，以及 `native-config.json` 中 `mobile.isMobile=true` 和稳定 userAgent；不拿桌面会话冒充移动设备。read_to_earn 有独立 APP 组件，但不是当前旧部署启用项。Edge 时长、视觉搜索、实验 API 搜索等未绑定的请求会明确保持未完成，不静默跳过。

登录失效、验证码、地区不一致、账号限制等会返回明确原因。新增兑换目标需真实目标 URL 和对应操作授权；没有默认目标、自动兑换或伪造年龄数据。

HTML 最多 2 MiB，flyout 最多 4 MiB，账号状态最多 1 MiB。有限活动、查询、轮询和总时限共同限制运行；结果不保存网页/截图/完整 API 响应。实际浏览器内存不是硬限额。

解析器仅加载 `vendor/rewards-parser/` 中固定的约 26 KiB JS，无运行时依赖；不安装完整上游应用。协议适配参考 TheNetsky/Microsoft-Rewards-Script v4.3.2，GPL-3.0-or-later；来源、编译证明和完整许可证保留。当前能力与现场验收见 [REWARDS_PARITY](../../docs/REWARDS_PARITY.md)。
