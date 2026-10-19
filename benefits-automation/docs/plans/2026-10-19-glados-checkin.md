# GLaDOS 签到接入

## 范围与决定

- 仅在 `codex/benefits-glados-20261019` 的独立 worktree 开发 GLaDOS，不修改公共运行器、全局来源清单或调度仓库。
- 复用 `common.runner/Task` 和 JSON schema v1；单账号独立调用，不加 `--execute` 不联网。
- 参考 dff652/GLaDOS-Qinglong 的实际 HTTP 协议；不复制未确认许可的完整脚本，不导入其 pandas、通知、自动镜像轮换或写重试。
- 显式配置单一 HTTPS origin、对应 Cookie 与浏览器 User-Agent；签到 token 缺省跟随 origin hostname，可按当前浏览器真实请求覆盖。
- 每次先读取认证状态及积分记录，保存签到 intent 后最多提交一次；不明确的写请求只读恢复，同一天不盲目重签。
- 积分、剩余天数和连续签到天数仅传递可核实值，未知为 null；业务签到成功不被可选统计失败抹去。

## 已核对协议

- `POST /api/user/checkin` 的 `code=0` 表示成功；`code=1` 只接受已验证的已签到文案，不把所有 code=1 都当成功。
- `GET /api/user/status` 可读账号状态与 `data.leftDays`；只保留业务值，不传递邮箱或原始响应。
- `GET /api/user/points` 返回顶层 points/history/streak。官网当前签到页使用 history 的 checkin 业务标记和毫秒时间，按本地时区构建签到日历；本实现用同一证据读回，不根据余额变化猜测签到已完成。

## 验收

- 配置缺失与格式错误在联网前报告；Cookie/UA 不进入标准输出、结果、状态和日志。
- 离线覆盖首次签到、今日已签、认证失效、自动签到拒绝、设备不匹配、非 JSON/非 200/异常结构及可选统计失败。
- 覆盖写请求超时后确认、未确认及跨次恢复；同一天不重复提交，旧日期不能当今日成功。
- 验证真实 HTTP 流的 TLS、响应大小、禁止重定向和请求时限；无 --execute 及缺失凭据时保持可独立运行。
- 使用可用凭据才能做真实业务验收；当前环境未发现 GLADOS_* 配置，开发与离线测试继续进行。

## 进度

- 已读取中央计划、适用仓库约定和现有 HTTP 平台的结果/恢复实现。
- 已核对上游 HEAD `5ad6cc082d6cf89b8eec3bfce3e7bfdab6fa2cd9` 及官网当前积分读取、日历、hostname token 和设备拒绝代码；哈希记录在平台 provider-source.json，未复制完整上游。
- 已实现独立入口、stdlib 有界 HTTPS 客户端、只读状态模式、可选既有 CookieCloud、持久 intent 和当日确认事实。没有新增基础依赖或修改公共接口。
- 离线验证覆盖 39 项平台/协议/真实入口及 CookieCloud 绑定用例，在默认 Python 3.11.2 和生产 HTTP venv 的 Python 3.12.13 中均通过；首次测试暴露毫秒时间戳超出普通业务数字上限的问题，改为独立时间转换后，时区及超时恢复测试通过。CookieCloud 用例验证仅请求所选主机、配置后不回退旧 Cookie、缺 UA 不先访问凭据服务。
- 公网只读实测：本地 Client 使用无效占位 Cookie 分别访问 status/points，两者都返回 authentication_invalid，验证现行端点和认证拒绝路径；没有访问真实账号或提交签到。
- 初次开发验收时没有 GLaDOS 专用 origin/UA/Cookie，真实认证、签到、奖励到账和 CookieCloud 此平台联调未验证；后续真实访问诊断见下节。按 README 的 status → 一次签到 → 重复执行顺序验收。
- 集成建议：按 Task 现有 allowlist 注入环境变量即可；日报补充 device_mismatch、automated_checkin_rejected、access_denied、transport_error、checkin_pending_confirmation 等原因文案及 balance/reward/remaining_days 展示，不需要改 schema 或 runner。

## 2026-10-19 真实访问诊断与私有配置

- 根聊天授权配置和真实验收后，使用已存在的 CookieCloud 私有配置取得 glados.cloud 的完整 gld:sess/gld:sess.sig 配对。未输出或另存 Cookie 值。
- 同一宿主侧的直接读取中，真实 Cookie 和无 Cookie 的 `/api/user/status` 都返回 HTTP 403、`server=cloudflare`、JSON `cloudflare_error=true`、`error_code=1010`、`error_name=browser_signature_banned`、`retryable=false`。直连与既有代理的无 Cookie 对照也一致；没有修改共享代理或路由。
- 响应没有 GLaDOS 业务码，也没有 `cf-mitigated: challenge`。当前确定的是 Cloudflare 浏览器签名拒绝，不能据此判断 Cookie 失效，也不能认定为可等待完成的挑战页。含义依据 [Cloudflare 1010](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/)、[结构化错误说明](https://developers.cloudflare.com/fundamentals/reference/error-responses/) 与 [挑战响应标记](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)。
- CookieCloud 解密数据只有 cookie_data/local_storage_data/update_time，没有浏览器 UA 字段；目标 session Cookie 是不含可读 UA 的不透明值，现有服务日志只有启动记录。没有找到可信的准确浏览器 UA，没有猜测 UA 或提交签到。
- 已创建仓库外 `benefits-runtime/credentials/glados.json`，只包含 GLADOS_ORIGIN 与 COOKIECLOUD_CONFIG，未填写未知的 GLADOS_USER_AGENT；身份 988:984、权限 0600。以 Hermes 的实际 UID/GID 读取配置、解密 Cookie 并做只读请求，确认权限和 Cookie 来源可用。
- 本地适配器新增 `cloudflare_browser_signature_banned` 与 `cloudflare_challenge` 原因；只凭 403 或缺少明确 Cloudflare 标志仍保留通用 access_denied。生产 Python 3.12.13 的 43 项测试通过，覆盖实际 1010 响应结构、挑战头和读取受阻时零签到提交。
- 同一 Hermes 身份下，更新后的 Client 使用诚实 Python-urllib/3.12 UA 进行诊断读取，真实返回 `cloudflare_browser_signature_banned`；该 UA 仅用于读诊断，未配置为 Cookie 对应浏览器身份。脱敏证据保存在 `benefits-runtime/diagnostics/glados-20261019/diagnosis.json`，不覆盖正式 delivery。
- 用户在 Mac 再次同步后，重新解密的 CookieCloud update_time 为 `2026-10-19T09:10:58.009Z`，完整 Cookie 配对仍在；Hermes 身份使用这份最新数据的只读请求仍返回同一 1010 原因，没有提交签到。
- 已按根聊天提供的新设备 ID 在 192.168.31.103 验证 `uname -s=Darwin`，执行 UID 与控制台 UID 均为 501。该设备 Chrome 实际 JavaScript 读取返回错误 12，未取得 navigator.userAgent；读取时临时创建的 about:blank 窗口已关闭，没有修改远程设置。旧远程工作台连接也无可读 Chrome 窗口，另一连接要求重新认证，不据这些失败推造 UA。
- 待根聊天取得获取 Cookie 时的准确 UA 私有路径后，保持既有权限补入 GLADOS_USER_AGENT，先复测 status/points。UA 匹配不保证 Cloudflare 接受 HTTP 客户端；只有真实认证与状态完整确认后，再执行一次签到、账目读回和重复运行验证。真实认证、签到与积分到账尚未确认。
- 集成追加事项：日报为 cloudflare_browser_signature_banned 显示“Cloudflare 拒绝客户端浏览器签名”，为 cloudflare_challenge 显示“Cloudflare 挑战未通过”，不能映射为 Cookie 失效。
