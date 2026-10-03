# benefits-automation

一个 Git 仓库，六个平台各一个目录；原生 Linux 一次性任务，无容器、常驻 worker、任务队列或浏览器池。

## NAS 验收（2026-10-03）

代码已同步到 NAS，Firefox 和 Chromium 的原生本地页面冒烟通过；V2EX 今日奖励已通过原生入口只读恢复确认。整套迁移仍未通过：Epic 公共领取入口未接通，Rewards 四项旧有能力缺 CLI 绑定且快照失败，CookieCloud 同步和日报/调度尚未迁移。青龙与旧仓库继续承担生产任务，暂不清理。具体结果及清理条件见 [NAS 验收记录](docs/NAS_ACCEPTANCE_2026-10-03.md)。

## 当前状态（2026-10-02）

- SMZDM：原有签名与签到/奖励查询已迁移；动作级日状态保留已确认签到，后续仍可恢复奖励查询；不明确写入不盲目重放
- V2EX：从 dailycheckin 25.12.9 提取 MIT 的最小 provider，去除全包导入；独立 venv、完整带 hash 的 HTTP 依赖锁、与原 provider 的假 Session 等价测试；强制 TLS 验证
- 阿里云：只签到/领取的原生适配器，逐社区保留结果并正确汇总；外部 daily.py 必须匹配精确 hash，不调用完整 main、发通知、清理或互动任务
- Laowang：原生 Firefox 流程、持久账号 profile、状态查询及人工登录入口；页面模拟测试通过；前一环境 Firefox smoke 在 profile 初始化时失败；当前环境的依赖/浏览器验证结果单独记录，尚未通过业务验收
- Epic：已有固定来源检查、状态机与原生浏览器对象驱动、零价/购物车/商品身份核验和不确定提交只读恢复；公共claim入口尚未开放，未通过真实端到端验收
- Rewards：已有独立每日活动、快照、extra、桌面/手机搜索、onboarding punchcard；full 按明确的 capabilities.json 顺序编排，缺少清单时不执行。未接入能力保持 pending，部分成功不会冒充所有能力完成；APP/目标恢复需可信调用方，尚无真实账号端到端验收

这是持续开发中的实现检查点，尚未六平台上线。没有使用账号、登录、签到、领取、解验证码或改 NAS 调度。离线测试不证明真实网站/API 仍兼容。

## 目录

```
common/                  Python 标准库 launcher、锁、监督、结果协议
platforms/<platform>/    run.py 是唯一公开调度入口
locks/                   依赖锁（不是运行锁）
tests/                   离线流程、进程、并发、解析测试
upstream/                用于归属和行为对照的原始业务代码，不是运行入口
source-lock.json         原始仓库来源
```

全部运行数据放仓库外。每个账户用不含邮箱的代号。所有入口必须使用同一主机、同一绝对 runtime-root，以共享浏览器互斥锁。

## 离线检查

```sh
python3 -m unittest discover -s tests -v
node --test tests/*.test.cjs
python3 platforms/smzdm/run.py --runtime-root /absolute/private/benefits-data
```

最后一条默认只检查入口/目录/锁，输出 execution_not_requested 并返回 1，不执行平台操作。只有显式 --execute 才进入适配器；已有凭据时这会执行真实操作，需先完成对应部署/账号授权。

已验证开发运行时：CPython 3.12.14、Node 24.19.0、Linux x86_64。未宣称其他 NAS CPU/libc 已验证。Python launcher 只依赖标准库。SMZDM 不依赖 npm 包。

V2EX/阿里云共用的小型独立 HTTP 环境（不安装 dailycheckin 全包、RSA、PyCryptodome）：

```sh
python3 -m venv .venv-http
.venv-http/bin/pip install --require-hashes -r locks/http-python312-linux-x86_64.txt
PYTHONPATH=. .venv-http/bin/python tests/provider_contract.py
```

锁针对本轮 Linux x86_64 wheel；其他架构需重新解析并审查锁。Aliyun 也使用这一 requests 环境；锁文件固定 requests 2.32.5 及完整传递依赖。V2EX 使用 V2EX_COOKIE、V2EX_PROXY、V2EX_USER_AGENT；每次仅一个账户，替代原来单进程 V2EX 多账号 JSON。调度器逐个账户调用，不并行。

Laowang npm 安装不自动下载/执行浏览器安装脚本：

```sh
cd platforms/laowang
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --ignore-scripts
```

Playwright Firefox 1.63.0 已锁完整 npm integrity。本轮已安装 Firefox 155.0/revision1543、FFmpeg1011；本地 smoke 报“Could not find profile folder”，未通过运行验收；用 --browser-cache /absolute/path 指定统一安装缓存。账号 profile 位于 runtime-root/state/laowang/<account>/browser，不复制、不覆盖既有 profile。人工登录入口为 run.py --execute --login（交互 TTY、可用 DISPLAY）；登录确认不等于签到成功。--status 仅 Laowang 支持，禁止用于其他平台。

## 结果与调度

每次输出一个 JSON 结果；同时原子写 runs/<run-id>/result.json。执行状态与业务状态独立，unknown 不等于完成。退出码：

- 0：执行正常且所有业务项 complete/not_applicable
- 1：失败/未请求执行
- 3：执行正常，但部分业务未知、未完成或受限
- 75：锁忙，未执行业务
- 124：总时限耗尽，结果可能未知，禁止盲目重放写请求

通用运行器每次在锁内调用适配器，不再以 checkin=complete 跳过整个平台。last-confirmed.json 仅保留证据；各平台按具体动作及业务日期恢复，已确认签到不会因为奖励未知而重做，待确认奖励仍可读回。异常退出、超时和中断保留经过身份校验的同 run 业务事实，只改变执行状态。--allow-repeat 仅为旧命令兼容保留，已弃用且不绕过动作防重放。--status 当前仅 Laowang 支持。dry-run 不覆盖最新业务结果。尚未实现每日汇总或自动凭据同步。

运行一次示意（仅在完成真实操作授权后）：

```sh
python3 platforms/smzdm/run.py --runtime-root /absolute/private/benefits-data --account account1 --execute
python3 platforms/v2ex/run.py --runtime-root /absolute/private/benefits-data --account account1 --python /absolute/project/.venv-http/bin/python --execute
```

默认日期 Asia/Shanghai，可用 --timezone 更改；未擅自安装 cron/systemd 或停旧任务。迁移 NAS 时先停该项旧调度，再开启新入口，避免双跑。

## 安全与生命周期边界

任务锁→全局浏览器锁，flock 文件不删除；浏览器任务串行。监督者按 chunk 排空输出，单 run 日志最多 1 MiB，结果最多 64 KiB。精确已知环境值跨 chunk 脱敏；不能保证未知编码机密被识别。凭据仅从当前平台白名单传入，不写 argv/result。文件默认 0600、新目录 0700；已有目录权限不擅自修改。

总时限内 TERM→KILL 适配器进程组。浏览器任务另使用一次性启动器进程自身的 Linux subreaper 与 pidfd，回收适配器退出后被收养的分离子进程；仅操作经确认属于该启动器的后代，不按名称杀进程。执行前实际探测内核能力，不支持时不会启动浏览器任务。该实现没有安装系统服务或修改系统安全设置。

cleanup 标记在确认回收后才清除。如果启动器自身被 SIGKILL，或无法证明回收完成，同一主机本次启动期间的后续浏览器任务会拒绝重叠执行；这不代表已立即杀掉所有孤儿。只读检查和恢复边界见 [运行与回收说明](docs/RUNTIME_RECOVERY.md)。只有已验证的新 boot ID 才自动恢复旧启动记录；正常运行中不提供盲目清除标记的开关。NAS 内核能力及真实峰值内存仍须部署前确认。

通用 run 历史目前无自动删除；日志单次有界不等于磁盘总量有界。平台的每日动作 journal 有自己的有界周期管理，但不会替用户清除未知提交或既有会话。成功不保留网页截图/HTML。Laowang 已有按需 tncode 处理器和同次调用的有界授权恢复，普通 CLI 尚未接入可信 Hermes 宿主，因此遇到挑战仍暂停。Epic 的公开领取入口也仍有明确闸门。

详见 [本轮修复与验收](docs/FIX_STATUS_2026-10-02.md)、[实现状态与阻塞](docs/STATUS.md) 和 [来源与许可证](THIRD_PARTY_NOTICES.md)。

## Rewards 每日活动限定模式

platforms/rewards/package-lock.json 固定 patchright 1.61.1。先在该目录 npm ci --ignore-scripts（PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1），再配置 REWARDS_ROOT 为该目录绝对路径。仅从 runtime-root/state/rewards/<account>/storage-state.json 读取已授权人工准备的单账号会话，不自动迁移数据库/凭据。会话文件最多1MiB。

显式 --execute --mode activities 只点每日活动卡片、读回进度，不执行搜索、extra、完整上游或通知。仍受全局浏览器锁；要求原生 Chromium sandbox，不用 --no-sandbox。尚未进行真实浏览器/账号验证；遇到挑战/页面变化可能返回 unknown。该模式完成不表示全部 Rewards 项目完成。

Rewards 的新增 snapshot/extra 模式及可重复 parser 构建、编译参数和范围边界详见 [平台说明](platforms/rewards/README.md)。不自动设置兑换目标，不运行完整上游 Main。
