# 雨云一次性签到接入

## 范围与关键决定

- 分支 `codex/benefits-rainyun-20261019` 仅拥有雨云平台、专用测试/依赖锁和本计划；公共运行器、Hermes 调度和生产源码集成由原任务负责。
- 独立 `run.py` 复用 `common.runner` / `Task(browser=True)`、单账号锁、全局浏览器互斥、总超时、进程包含及回收。默认不联网；只做签到与积分查询。
- 复用 LeapYa/Rainyun-Qiandao 固定提交 `fdefba4dbec2d7e99568e08e182eda9c3026c75f` 的 Selenium 交互和验证码流程。上游未发现 LICENSE，完整来源保持仓库外；按 hash 校验后仅加载 ICR 和 stealth 字节，不导入上游主程序。
- 浏览器与驱动显式路径，固定 Chrome for Testing / ChromeDriver `153.0.8010.12`；不在运行时安装、下载或切版本，保留 Chromium sandbox。
- 只认每日签到行精确“已完成”；未知文本不能当成功。领取前写入每日 pending intent，提交结果不明时只读恢复，不再次领取；验证码最多两次，仅未提交或明确失败可换题。
- 认证复用已有 CookieCloud，每次只读取目标域。profile/journal 绑定雨云内部账号 ID 的摘要，令牌轮换不切换身份。先通过官方用户接口核对当前会话身份，再接受业务状态或提交签到；密码模式保留。
- CookieCloud 冷 profile 由官方首页先填充完整用户缓存，再进入积分页，避免有效会话被前端异步初始化的路由守卫误判。余额读取当前官方 `/user/?no_cache=true` 的 `data.Points`，不解析失效的余额 XPath，也不保留完整用户响应。

## 验收标准

- 无 `--execute` 不加载 Selenium、不访问平台；配置、来源、浏览器版本或认证失败均输出标准 JSON v1。
- 未签/已完成/未知分开报告；已签到重复运行、提交丢响应、跨进程 pending 均不重复领取。
- 身份未核实时不提交；同次运行身份已核实后的余额暂时故障不撤销已确认签到。
- 真实启动保留 Namespace、PID/Network namespaces、Seccomp-BPF sandbox；所有浏览器操作遵守共享租约。
- 真实账号验收包括只读状态、一次签到、独立读回、积分变化及重复运行；算法合成测试不等于真实验证码通过率。

## 交付进度

- 初始提交 `0367ecb` 完成单次入口、平台适配、私有配置、profile、每日 intent、来源契约、依赖锁、README 和防重/验证码测试。
- 追加工作按原聊天授权配置 `rainyun-main`、接入既有 CookieCloud，并完成真实账号验收；没有修改公共 runner、代理、容器或调度。
- 冷启动实测首先发现前端初始化竞争，官方接口确认会话有效后修复首页初始化顺序；随后真实只读 run `15ad52d0-8d8c-4a7f-9a0c-429bd1cfcb96` 确认未签到。
- 余额实测发现上游 XPath 已过时，改用当前官方用户接口，并核对返回 ID 与同步身份。当前前端 URL、hash 和字段证据见 `platforms/rainyun/provider-source.json`。
- 真实签到 run `5d7c519c-b136-46e4-8c4c-3ed1919c9360`：`checkin_confirmed`，签到与余额均 complete；积分从 **200 → 700**，本次读回差值 **+500**。
- 重复完整执行 run `d0097fd6-333e-4bf7-9b5a-048c42958c54`：已完成分支直接返回，积分 **700 → 700**、差值 **0**。独立官方 GET 用户/任务接口均 code 200，ID 一致，`每日签到.Status` 从 1 变为 2、奖励 Points 500。
- 最终代码只读复核 run `0b6d70f4-4504-488a-9a00-bca5633fc351`：服务端身份核对通过，签到与余额均 complete，余额 700、差值 0。
- 浏览器真实冒烟 run `ee6dbfc5-834d-4651-9343-632f3751f58b`：`browser_sandbox_confirmed`，Namespace、PID/Network namespaces、Seccomp-BPF 确认且无 `--no-sandbox`。曾出现的 sandbox_not_confirmed 是旧页面字段名匹配失效，已按固定 Chrome 153 实际页面修正。
- 首次启动遇到 Chromium Unix socket 路径超长；仅浏览器子进程使用短私有 `/tmp/rainyun-*`，profile 仍在账号 state。实际 AF_UNIX 回归及真实 Chromium 启动均通过。
- 40 项雨云测试在固定依赖及固定外部 ICR 环境全部通过，含真实算法识别合成图案、身份核对、冷启动、防重恢复和有界验证码。初始现有入口 19 项、公共能力 13 项通过，进程包含 10 项中 2 项按环境条件跳过、其余通过；未修改公共能力。

## 运行配置

既有共享 runtime：`/home/hermes/.hermes/profiles/lingjun/benefits-runtime`。

- 私有入口配置：`credentials/rainyun.json`，只存浏览器、驱动、provider 与 `credentials/cookiecloud.json` 的路径引用，不复制 CookieCloud 密钥或会话。
- 独立依赖：`dependencies/rainyun/venv`（Python 3.12.13）、`driver/chromedriver`、`provider/`。按现有雨云锁和 CookieCloud 解密锁联合安装，保留驱动许可证及 notices。
- 复用已有 Chrome `/home/yuwk/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`，实际版本符合契约。
- 新增运行对象由 Hermes `988:984` 持有；执行也使用此身份。FnOS 命名 ACL 将新配置显示为 0660：该文件只有路径引用，代码允许受控组权限且拒绝 world；含密码的配置仍要求 0600。没有声称此文件具备无法在该 ACL 下保持的 0600。
- 公共环境变量白名单只需 `RAINYUN_CONFIG`；调用 README 的单次命令、同一 runtime-root 和账号 `rainyun-main`。调度启用由集成任务完成。

## 验证边界与待集成

- 真实登录会话、领取、页面读回、官方独立读回、积分查询及重复执行已验证。本轮未单独记录是否出现验证码挑战，因此不将签到成功当成真实验证码识别通过率证据；已验证固定算法及验证码交互单元行为。
- `container-boot.py --check` 返回既有差异：missing `tailscale`，active_unplanned `ai-resource-center`、`personal-crm`，无 stopped_planned。本任务未修改这些容器，也未执行 reconcile。
- 无需修改公共 Task/runner。Hermes 任务和日报标签由原集成任务统一修改；外部来源、私有配置与长期依赖已就位。
