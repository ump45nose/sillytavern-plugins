# Microsoft Rewards

按启用清单顺序执行一次账号任务，阶段之间关闭浏览器，最后输出通用 JSON 和本次 `rewards-report.json`。Hermes 决定何时运行、如何汇总和推送。统一结果补充进度、余额变化、锁定数量和未确认任务明细，见 [结果契约](../../docs/RESULTS.md)；不把余额差当全天积分收入。

## 安装和账号状态

Python 3.12、Node 24、patchright 1.61.1 和原生 Chromium。保留 sandbox，不导入上游 Main 或其通知/数据库/账号扫描代码。

```sh
cd platforms/rewards
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --ignore-scripts
npx patchright install chromium
```

在仓库外的 `state/rewards/<account>/` 准备 `storage-state.json` 和 `capabilities.json`。当前迁移保留旧部署启用的八项：

```json
{"schema_version":1,"enabled":["daily","extra","punchcards","desktop_search","more_promotions","claim","app_daily","app_promotions"]}
```

可选 `native-config.json` 保存已有稳定地区/设备和搜索配置，例如：

```json
{"region":"US","language":"en-US","search":{"maxSearches":100,"stagnantLimit":3,"delayMs":30000}}
```

请用账号实际地区；不根据示例改变地区。凭据文件不进 Git。

```sh
REWARDS_ROOT=/absolute/project/platforms/rewards \
REWARDS_PROXY=http://your-existing-proxy:7890 \
python3 platforms/rewards/run.py --runtime-root /absolute/private/runtime \
  --execute --browser-cache /absolute/browser-cache
```

## 能力与确认

- `daily`：逐个执行当前每日活动卡片，重新读进度到上限。
- `extra`：社交、已配置目标和探索必应。探索先用当前任务 hash 激活，再用对应主题搜索，以该任务自身的完成/积分读回确认。锁定任务保留 blocked。
- `desktop_search`：读取当前账号桌面额度，未满时搜索、等待入账，达到额度或连续停滞则退出；已满不重复搜索。账号、设备和日期各有查询 journal，发出前记录，当天重跑跳过已提交查询，次日重新允许。
- `punchcards`：旧部署白名单 onboarding 任务；完整清单没有分配该任务时不适用。不会把其他任务组冒充同一任务。
- `more_promotions`：当前可执行 URL 活动，当前 action ID 和任务 hash 绑定，发出前记录 intent。journal 按业务日期保存，避免循环使用的活动 ID 被此前日期的提交永久阻塞；迁移时保留当天已有 intent。
- `claim`：明确有待收积分时提交一次；无待收积分不适用。
- `app_daily` / `app_promotions`：通过已有浏览器登录进行 OAuth，token 存在私有账号目录；随后一次性 HTTP 客户端执行 APP 任务，不保留后台浏览器。APP 签到优先用当前页面进度确认，不能把 1000 分连续签到奖励误认作每日签到。

完整任务在开始时也读取 APP 活动的当前清单。中途遇到验证码等人工处理条件时立即停止后续动作，但保留本次开始快照已确认完成的任务。APP 签到只有重新读取到对应页面计数完成后才确认，提交响应或余额上涨不足以确认；APP 授权与限流失败保留固定公开原因，不输出私有响应。

APP token 到期时，先使用同一登录 Cookie、代理和既有 HTTP 客户端完成 OAuth 跳转。只有官方回跳地址、随机 `state` 和授权 code 均有效且没有错误参数时才交换 token；需要页面交互时仍使用原浏览器和障碍检测。浏览器等待导航 commit，并在超时时核查真实回跳，不等待回跳页面的 DOM 加载。一次完整调用共享授权尝试及其失败，避免快照与各阶段反复启动授权浏览器；token 交换不自动重放，超时和导航失败有固定公开原因。

探索使用 [上游完整主题词库](https://github.com/TheNetsky/Microsoft-Rewards-Script/blob/f61f4e982bbb435f37133bed0dc5b4c582ed1e73/src/functions/bing-search-activity-queries.json)，固定 commit `f61f4e9`、GPL-3.0-or-later，共 74 个标题词条。原始 JSON 随源码保存在 `vendor/rewards-parser/src/functions/bing-search-activity-queries.json`，来源及 SHA-256 记录在 `PROVENANCE.json`；加载时校验字节摘要，无运行时下载或模型调用。匹配标题时清除零宽字符、统一大小写和空白；原有 27 个稳定 offer ID 也映射到该词库，支持标题本地化。酒店、珠宝、房产、体育等新轮换任务可直接按上游标题匹配。未识别主题仍显示 `search_topic_unsupported`，每个任务最多使用词库中的 10 个查询，逐项读回任务自身进度。

搜索导航可能销毁正在读取的 DOM；仅对明确的导航上下文失效等待后重做一次只读 guard。登录、验证码等障碍仍立即停止，搜索 intent 和激活请求不重放。

APP 签到在正式 `full` 入口使用独立的 `app-checkin-journal.json` 记录轮次，发出请求前原子保存 intent。北京时间日期只作审计，不在午夜清除未确认提交。开始快照和签到阶段重新读取的对应 1/1 计数会持久确认当前轮次；之后只有两次独立页面读取（间隔 3 秒）均确认 0/1，才开启下一轮并允许一次提交。这样同一本地日的平台重置不再被旧日记录阻塞，长任务也会在签到阶段重新核查进度。单次旧读数、缺失计数、非 1 上限、POST 响应和余额变化均不能开启或确认轮次；不确定提交等待真实读回，不自动重放。

迁移导入 `app-daily-journal.json` / `app-journal.json` 中最近的签到 intent，并先持久保存，避免后续阅读任务轮换日记录时遗忘未确认请求。旧文件保持原样；阅读和 APP 活动仍使用原来的记录。新文件保留当前轮次及上一轮确认摘要，长度固定，不累积每日文件。没有可用页面签到进度的 APP 单独调用返回未确认，不提交。

搜索提交后遇到真实登录或验证码条件时保留具体原因并停止后续动作。导航超时或浏览器错误先只读核对额度，不重复同一次提交；完整回执保留各阶段的诊断条目。

验证码 iframe 的识别只检查解析后的主机名和路径，不把 URL 查询参数中的 OAuth PKCE `code_challenge` 当作验证码。`#captcha` 标记和真正的 captcha/challenge iframe 仍会停止任务。仅凭 iframe URL 中出现单词 challenge 不足以确认验证码。

当前页面的活动提交使用 `/earn`，携带从当前页面读取的 `X-Deployment-Id`、action ID 和任务 hash；时区偏移取实际浏览器或已有显式配置，以字符串发送。缺少部署身份时停止提交，不自动重放 POST。2026-10-09 的实际浏览器请求及原生适配提交均已读回确认。

能力汇总只包含平台已分配、当前可执行的任务。平台明确锁定或不适用的项目保留在明细中；缺少授权、主题不支持或积分未确认的可执行任务仍报告未完成。

2026-10-09 原 Hermes 完整入口实跑成功，run ID 为 `f9562bcd-89dd-493f-ab67-3615f9903613`：每日 3/3、桌面搜索 100/100、探索 40/40、当前可执行更多活动 155/155、APP 签到 1/1、APP 活动 4/4。八项已启用能力均为 complete 或 not_applicable，四项平台锁定任务仍保留 blocked 明细。本次正式复跑前已完成修复验证，复跑余额差为 0，不代表当日收入为 0。

2026-10-10 17:30（北京时间）原 Hermes 完整入口读回成功，run ID 为 `1be5dd00-e5b5-4b95-9625-8ebb206e356c`：每日 3/3、桌面搜索 100/100、探索 40/40、更多活动 125/125、APP 签到 1/1、APP 活动 4/4；八项启用能力均完成或不适用，余额 72,623。正式 delivery、full latest 和历史回执一致，异常日报不再报告 Rewards 问题。65 项相关测试通过。探索实跑记录到 `locator.count` 导航上下文失效，复查后完成。

上午告警中的鲜花、招聘和餐馆活动在下午补跑前已被平台轮换移除，因此仅确认主题支持修复，不声称补领了这些旧活动。当前探索清单为信用分、床垫、宠物用品和天气。APP 同日从已确认的 1/1 重置为 0/1 后，用私有独立恢复 journal 记录新轮次的单次签到，保留原日 journal；恢复 run `43d6744b-39b7-4b2d-b406-11e24df5109d` 重新读回 1/1。

2026-10-10 17:59（北京时间）完整词库和签到轮次逻辑接入后，原 Hermes 入口实跑 `b3e4f5d1-32ed-4dbd-b773-e3b76e3278eb` 成功：探索 40/40、桌面搜索 100/100、每日 3/3、APP 签到 1/1、APP 活动 4/4，八项能力均完成或不适用。新轮次记录已持久确认为 confirmed，旧日记录 SHA-256 未变；正式 delivery、full latest、历史回执一致，异常日报无 Rewards 问题。这次调用只执行正式脚本，没有调用一次性恢复脚本。92 项相关测试通过；新轮次提交分支由重置模拟测试验证，本次平台已完成，未再次真实重置。

2026-10-11 上午正式运行 `6a46851e-8643-4a29-98a7-508c604f39e5` 的 APP 活动未确认。旧 token 在运行开始后到期，现场诊断重现刷新路径的 `page.goto` 超时；上午原汇总仅显示 `capability_failed`，没有保存底层异常。修复后，14:22（北京时间）原 Hermes 完整入口 `7b2e10a5-302c-41a3-92f4-f5d7f672f08d` 成功：每日 3/3、桌面搜索 100/100、探索 40/40、更多活动 115/115、APP 签到 1/1、APP 活动 4/4；八项启用能力均完成或不适用，正式 delivery、full latest 和历史回执一致，异常日报无问题。14:25 的独立诊断 `7234a234-635e-4015-b561-d7a4dc03f190` 在进程内模拟 token 到期，真实 HTTP 授权、token 交换及 APP 活动读回在 7.4 秒内完成，没有启动 Chromium；诊断结果独立保存，没有覆盖正式 full 结果。41 项授权与完整任务测试通过。现场主机内存/交换压力使完整复跑耗时约 42 分钟；超时诊断留下的清理标记经过运行 ID、执行器和全量账号进程核查后恢复，正式复跑结束无清理阻塞。

2026-10-03 实测每日活动、桌面搜索、APP 签到与 APP 活动确认；无分配的 onboarding 和无待收积分均不适用。更多活动有平台锁定项；探索必应仍按 [验收记录](../../docs/IMPLEMENTATION_ACCEPTANCE_2026-10-03.md) 报告，不用部分成功代表全部完成。

同日 14:58（北京时间）接入日志和操作节奏后，原 Hermes 完整入口 `7e91f6ea-c44d-4e54-9dd7-fe380cbf815b` 再次成功，耗时 92.2 秒：每日 3/3、桌面搜索 100/100、探索 40/40、更多活动 115/115、APP 签到 1/1、APP 活动 4/4。八项启用能力均完成或不适用，正式 delivery、full latest 和历史回执一致，异常日报为空。本次已完成任务只读确认，余额差为 0；七次阶段等待实际为 2.256–4.972 秒。日志共 213 行、64,423 字节，包含完整阶段及导航/API 埋点，私有 token/Cookie 值扫描没有命中，结束无清理阻塞。

真实 Chromium 本地隔离验证 `435973a2-c735-4d29-888d-b987cd8da171` 使用空登录状态并拦截所有网络，确认真实按键事件、单次 Enter 提交、单次点击及滚动阅读；实际搜索等待 40.533 秒、阅读等待 12.224 秒。独立 HTTP 诊断 `3a0bc85a-8851-4fd4-9fe5-a851c217b294` 仅在进程内把 token 读数设为到期，真实 HTTP 授权、交换及 APP 4/4 读回用时 7.9 秒，未启动 Chromium，也未提交 APP 活动。两项诊断不覆盖正式 full 结果。157 项相关测试全部通过；关闭浏览器取消请求的日志分类补充后，59 项针对性测试再次通过，其中包含 1 项新增用例，累计覆盖 158 项不同用例。

## 操作节奏与诊断日志

默认按顺序执行：阶段间等待 2–5 秒；提交或点击前等待 1.5–3.5 秒；搜索框逐字输入，每字间隔 40–110 毫秒；搜索导航后等待 1.2–2.8 秒，入账等待 30–42 秒。每完成 8 次搜索，在下一次前休息 45–75 秒；活动页面轻滚动后停留 10–15 秒。已配置更长的搜索等待仍生效。APP 提交也有动作间隔，阅读任务保留至少 30 秒等待。额度已满或活动已完成时只读确认；搜索和网页任务在等待结束后重新检查页面障碍，再持久记录 intent 并提交。已有账号、设备、地区、代理及防重复提交规则继续使用。

`native-config.json` 可选 `interaction` 覆盖对应范围，单位为毫秒；无需配置即可使用上述默认值。`enabled:false` 关闭新增随机等待与逐字输入，但保留调用方原有安全等待。配置只接受以下字段，范围必须为两个非负整数，终值不小于起值：

```json
{"interaction":{"enabled":true,"stage":[2000,5000],"action":[1500,3500],"settle":[1200,2800],"typing":[40,110],"reading":[10000,15000],"searchJitter":[0,12000],"batch":[45000,75000],"breakEvery":8}}
```

每次实际调用在 `<runtime-root>/runs/<run_id>/rewards-events.jsonl` 写独立结构化日志，与该运行的 `result.json`、`rewards-report.json` 同目录。日志同步写入，开始事件在等待操作之前落盘；进程被终止时，可从最后一条尚无结束事件的操作定位卡住阶段。每行包含 UTC 时间、运行 ID、账号代号和业务日期，并按情况记录阶段、操作、耗时、HTTP 状态、等待时长、进度、授权缓存是否到期、错误分类、固定原因及 Rewards 源码文件/行号。浏览器启动、上下文、页面导航、OAuth 跳转与交换、API、提交 intent、读回、阶段和最终结果均有埋点；阶段边界附进程 RSS、系统内存、交换空间和负载。

日志最多 512 KiB，以 `0600` 创建；生产访问权沿用既有私有运行目录的 FnOS ACL。达到上限记录一次 `log.truncated` 后停止增长。仅允许固定字段与值，不记录 Cookie、token、授权 code/state、完整 URL、搜索词、请求体、原始错误消息或完整堆栈；活动/查询标识只存摘要。写日志失败只输出固定诊断提示，不改变业务动作或结果。排查时先看本次回执，再按同一运行 ID 查看 `error` 和对应的 `start`/`finish`，从而区分授权超时、网络/TLS、导航上下文失效、限流或业务未确认。完整回执还保留失败阶段的诊断条目。

## 独立模式与边界

`--mode activities / snapshot / extra / desktop-search / mobile-search / punchcards` 可单独调用。snapshot 只读，结果按 mode 保存，避免覆盖 full 日报事实。

移动搜索需要自己的 `storage-state.mobile.json`，以及 `native-config.json` 中 `mobile.isMobile=true` 和稳定 userAgent；不拿桌面会话冒充移动设备。read_to_earn 有独立 APP 组件，但不是当前旧部署启用项。Edge 时长、视觉搜索、实验 API 搜索等未绑定的请求会明确保持未完成，不静默跳过。

登录失效、验证码、地区不一致、账号限制等会返回明确原因。新增兑换目标需真实目标 URL 和对应操作授权；没有默认目标、自动兑换或伪造年龄数据。

HTML 最多 2 MiB，flyout 最多 4 MiB，账号状态最多 1 MiB。有限活动、查询、轮询和总时限共同限制运行；结果不保存网页/截图/完整 API 响应。实际浏览器内存不是硬限额。

解析器仅加载 `vendor/rewards-parser/` 中固定的约 26 KiB JS，无运行时依赖；不安装完整上游应用。协议适配参考 TheNetsky/Microsoft-Rewards-Script v4.3.2，GPL-3.0-or-later；来源、编译证明和完整许可证保留。历史能力对照见 [REWARDS_PARITY](../../docs/REWARDS_PARITY.md)。
