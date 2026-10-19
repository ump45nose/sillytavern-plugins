# WeTalk 单账号签到与余额查询

## 范围与事实

- 工作区 `benefits-wetalk-20261019`，分支 `codex/benefits-wetalk-20261019`；中央计划为同目录 `2026-10-19-platform-checkins.md`。
- 仅修改 `platforms/wetalk/`、WeTalk 独立测试与本计划。公共运行器、调度/日报、根说明和全局来源记录由集成任务负责。
- 实现单账号签到及 Coins 余额查询，不实现视频、任务循环、登录服务或通知。
- 2026-10-19 读取上游 `ZenmoFeiShi/Qx` 的 `WeTalk.js`：提交 `b057f396ffb93c65342f87b98c3bad97d54b5fad`（2026-09-15），SHA-256 `68361ab1428311f1b88ad5b37b8e0fa76dfd61a77328c837da4450b4f5042d16`。
- 上游协议：固定主机 `api.wetalkapp.com`，GET `/app/queryBalanceAndBonus`、GET `/app/checkIn`。后者虽为 GET，仍是写操作。
- 参数按键排序拼接未编码值，附加上游协议常量做 MD5；更新 `signDate` 为 UTC `YYYY-MM-DD HH:mm:ss`，去掉旧签名，最后以 `encodeURIComponent` 编码。
- 上游捕获流程要求 `email`；其他认证/设备参数及认证头没有公开的完整最小清单，必须从用户自己的有效请求保留，不能声称 email 足以登录。
- `retcode=0` 是业务响应；余额在 `result.balance`。`result.isallowcheckin=false` 只证明当前不可签到，必须结合明确的“今日已签到”原因才能确认已签。
- 仓库 LICENSE API 返回 404，来源文件头未声明开放许可；不复制整份脚本或其 MD5/存储框架，仅独立实现必要协议并记录来源。

## 接口与行为

- `run.py` 复用 `common.runner`/`Task`，HTTP 任务，Node.js 内置模块，不新增 npm 依赖。默认不联网；`--execute --status` 仅查询，`--execute` 可签到。
- 环境变量仅 `WETALK_CONFIG`，指向仓库外的绝对路径私有 JSON（0600），包含解码一次后的 `params` 和必要 `headers`；不接收原始 URL。
- 保留原参数字符串，不再次 URL 解码；每次请求重算签名及 UTC 时间。删除捕获的传输层头，固定主机并禁止重定向，保留必要认证头及 UA。
- 固定请求时限及响应体上限；失败仅输出稳定原因，不输出含邮箱/凭据的请求 URL、参数、原始响应或异常堆栈。
- 写前原子持久化 intent；提交中断时只读恢复，同一业务日仍无法确认时不再次提交。已确认签到保留事实，余额读回失败时保留此前 current/before，after/delta 为 null。
- 状态文件仅保存账号代号、业务日、邮件身份摘要、签到 intent/确认和可信的签到奖励，不保存捕获请求。配置换成另一账号时不能复用旧确认。
- 输出业务项 `checkin` 与 `balance`；metrics 包括 `balance` 和可核实的 `reward`，单位 coins。余额差仅代表本次调用前后变化。
- 已签到和不适用必须有明确平台证据；不可签到但原因不明为 blocked，字段缺失为 unknown。登录失效、签名错误、网络/响应异常与签到未确认分别报告。

## 验收

- 签名固定向量、UTC 日期、键顺序、空值、百分号/加号/空格只解码一次；检查上游签名的字符编码约束。
- 已签到不提交；资格字段未知不提交；不可签到不误报成功；成功签到后读回余额。
- 写前 intent、提交中断后只读恢复、跨次仍未知不重发；明确拒绝及损坏状态不可误报成功。
- 已确认签到后读回失败保持签到事实，余额未知不按 0；账号身份错配不复用旧状态。
- 响应限流、重定向、大小上限、超时和配置错误；结果、stdout/stderr、状态均无凭据泄漏。
- 入口不执行不联网，缺少凭据输出契约内失败；使用固定模拟 HTTP 验证完整 Node 适配器与 Python 启动器联通。
- 真实账号验收待提供 `WETALK_CONFIG`：先 `--execute --status` 确认余额/资格，随后受控签到并再次查询，重复运行不重签。当前环境仅确认变量未配置，没有读取其他服务凭据。

## 进度

- 已读取中央计划、Task/结果/运行器及现有 HTTP 适配器；已取得上游提交与文件 hash，核对来源协议和许可缺口。
- 已完成 run.py、Node 协议/业务适配器、单日 intent/回执状态、来源记录及平台说明；公共运行器和生产配置未改。
- 固定提交的完整文件重新取得，hash 与记录一致。在临时外部目录执行其原 MD5 函数：ASCII 固定向量与 Node/hashlib 均为 `b31c98c1a686d8e0ae7707a1a97c16c7`；中文参数对照证实原算法与标准 UTF-8 MD5 不等价。完整上游未保留在仓库。
- Node 协议/恢复测试 **23 项通过**，真实 Python 启动器 + Node 适配器受控 HTTP 集成 **6 项通过**，既有公共运行器回归 **19 项通过**。
- 受控集成覆盖提交响应丢失后的只读恢复、重复执行、JSON 落盘及整个运行目录不含测试邮箱/token/认证头；这是离线 transport 测试，不是真实 WeTalk 联调。
- 本轮实际测试环境为 Python 3.11.2、Node 22.23.2；没有安装额外依赖或启动浏览器。目标 NAS 的生产环境仍待集成验收。
- 当前没有 WETALK_CONFIG，真实签到、账号失效响应码、平台业务日重置边界与 Coins 发放均未实测；未改生产调度、代理、部署或主线。

## 集成交接

- 平台标识 `wetalk`，入口 `platforms/wetalk/run.py`；Task 仅放行 `WETALK_CONFIG`，超时默认 120 秒，不使用浏览器。
- 支持 `--status`；与 `--execute` 一起使用才联网，只读且可能按现有协议退出 3（当前尚未签到）。
- `business` 包含 `checkin` 和 `balance`，metrics 为 `balance`/`reward`、单位 coins。日报为 `balance` 增加“余额查询”标签，注册平台及必要稳定错误映射即可，无需修改结果 schema。
- 全局 source-lock/许可汇总由集成任务依据本平台 `provider-source.json` 更新；本平台没有需要重新分发的上游文件或可冒用的 MIT 许可。
- 接入真实账号前先完成平台 README 中的只读检查，再验证签到、读回和重复运行。尚未确认的业务项不能视为本次开发已验收。
