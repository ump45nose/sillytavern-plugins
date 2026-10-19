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
- 当前没有 GLaDOS 专用 origin/UA/Cookie，真实认证、签到、奖励到账和 CookieCloud 此平台联调未验证。按 README 的 status → 一次签到 → 重复执行顺序验收。
- 集成建议：按 Task 现有 allowlist 注入环境变量即可；日报补充 device_mismatch、automated_checkin_rejected、access_denied、transport_error、checkin_pending_confirmation 等原因文案及 balance/reward/remaining_days 展示，不需要改 schema 或 runner。
