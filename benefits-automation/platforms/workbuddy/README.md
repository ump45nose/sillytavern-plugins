# WorkBuddy 国内 / 国际版

一次调用处理一个账号，复用公共运行器、账号锁、结果与超时；只需 Python 3.12 标准库，没有常驻服务。国内签到和国际活跃分别使用独立账号代号及凭据文件。

## 首次登录

在仓库外的私有目录建立 NAS 专用登录态，浏览器完成官方授权即可；无需复制或解密桌面客户端文件：

```sh
python3 platforms/workbuddy/login.py --edition cn \
  --session-file /absolute/private/workbuddy-cn.json
python3 platforms/workbuddy/login.py --edition intl \
  --session-file /absolute/private/workbuddy-intl.json
```

打开终端显示的官方授权链接完成登录，程序在有界时间内查询授权结果，保存 0600 凭据。`--timeout` 默认 300 秒，范围 30–600 秒。登录命令会显示一次性授权地址，日常任务和日报均不输出令牌、原始响应或模型回答。

已有 CookieCloud 网页登录态时，可以直接创建独立 NAS 会话：

```sh
python3 platforms/workbuddy/login.py --edition cn \
  --session-file /absolute/private/workbuddy-cn.json \
  --cookiecloud-config /absolute/private/cookiecloud.json
```

国际版改用 `--edition intl` 和独立凭据路径。此方式复用 `common.cookiecloud`，首次登录需要其可选 `cryptography` 依赖；日常运行不依赖 CookieCloud。只提取该版本的 `www.workbuddy.cn` 或 `www.workbuddy.ai` Cookie，按官方网页流程建立同域 SSO、申请新的 access/refresh token，再清空 Cookie，通过官方账号接口核对新 bearer 身份后保存。当前只支持唯一、启用客户端的个人账号；多账号或企业账号直接报告需要人工选择，Cookie 失效时重新登录官网并同步后再执行。不会修改浏览器中的原会话文件。

已有**明文**官方客户端会话可一次性导入：

```sh
python3 platforms/workbuddy/login.py --edition cn \
  --session-file /absolute/private/workbuddy-cn.json \
  --import-client /absolute/private/workbuddy-desktop.info
```

导入文件须为 0600，支持客户端的 `auth` / `account` 结构以及本适配器的单账号格式。新版 `$wbEncrypted` 字段不能直接导入；使用上面的独立官方授权登录。导入会复制 refresh token，后续不应让原客户端与 NAS 同时续期这一份会话；独立授权更适合常驻调度。

保存格式只有日常认证所需字段，均为字符串，`refresh_token`、`enterprise_id`、`domain` 可省略：

```json
{
  "edition": "cn",
  "access_token": "private-access-token",
  "refresh_token": "private-refresh-token",
  "uid": "private-uid",
  "enterprise_id": "",
  "domain": ""
}
```

国际版 `edition` 为 `intl`，官方授权会保存其真实 domain。文件不存入源码或 Git，不通过命令行传递令牌。读取请求被明确拒绝认证时，仅续期一次；旋转的令牌原子保存成功后才继续。登录工具和日常运行共用凭据文件旁的锁，避免并发刷新覆盖新令牌。

凭据文件要求 0600。如果宿主主动给运行目录修复共享 ACL，应把实际凭据放在 ACL 管理范围之外的 0700 私有目录，在约定的运行路径放链接。登录和运行会先解析实际路径，续期和锁都使用该路径，不会用新文件覆盖链接。不要反复 chmod 或停止宿主的权限服务。

## 运行

```sh
WORKBUDDY_CONFIG=/absolute/private/workbuddy-cn.json \
python3 platforms/workbuddy/run.py --runtime-root /absolute/private/benefits-runtime \
  --account workbuddy-cn --edition cn --execute

WORKBUDDY_CONFIG=/absolute/private/workbuddy-intl.json \
python3 platforms/workbuddy/run.py --runtime-root /absolute/private/benefits-runtime \
  --account workbuddy-intl --edition intl --execute
```

不加 `--execute` 不联网，报告 `execution_not_requested`。`--status --execute` 只查询状态/余额，不签到、不登记会话、不发模型请求；必要的认证续期仍保存新凭据。可选 `WORKBUDDY_PROXY` 显式指定 HTTP/HTTPS 代理；缺省直连，不继承环境代理、不更改 DNS 或路线。

国内版查询 `checkin-activity-status`，仅该路由 404 时使用旧版 `checkin-status`。明确活动关闭报告 `not_applicable`；状态缺失不猜测可签到。未签时先持久化 intent，再提交一次并读回；提交超时、异常或进程重启后只读恢复。原始 `daily_credit` 是奖励规则，不代表到账；只有已确认签到后的 `today_credit` 或本次明确成功的签到奖励才交付 reward 数值。

国际版先核验登录和余额，登记当前云端会话，再发送固定的 `hy3` / `only print:1`。请求携带 WorkBuddy 客户端特征、当前服务端会话 ID 和匹配的 growthEvent；每天最多发起一次，失败、超时、进程重启或未到账均不重发。使用参考协议的固定请求参数，没有额度预算或提示词配置。

两版的“每天”指本次运行 `business_date`，默认 Asia/Shanghai。凭据和 intent 绑定版本及 UID；同一个账号代号不能切换到另一版本或另一用户复用旧状态。

## 结果与验收边界

- 国内业务状态为 `checkin`、`reward`、`balance`；国际版另有 `activity`，其 `checkin` 为不适用。余额查询失败不撤销已确认的签到。
- 指标为 `balance` 的前后值及差、已核实的 `reward`、可读的连续签到 `streak`；未知值为 null。
- 国际版完整模型响应只确认请求成功。现有积分接口不提供与该请求关联的奖励流水，余额增长可能来自其他活动，因此 `reward` 保持 unknown，`reason=activity_sent_reward_unconfirmed`，公共运行器退出 3。余额差仍按观察事实交付，不宣称必然为活跃奖励。
- 套餐积分按服务端有效期筛选并分页读取；使用明确存在的周期余额，否则使用普通余额。不完整分页或缺失余额字段不能汇总成零。
- 日常结果保存在公共 `results/workbuddy/<account>/latest.json`，intent 在 `state/workbuddy/<account>/daily-intent.json`。人工重新授权同一账号仍保留当天 intent；不要删除它来重发不确定请求。

离线检查：

```sh
python3 -m unittest discover -s tests -p 'test_workbuddy.py' -v
```

2026-10-19 真实账号验收：两版通过 CookieCloud 的官方网页登录流程建立独立会话，清空 Cookie 后核对身份，并完成 refresh token 旋转、保存和重新读取。国内签到成功，确认奖励 100、余额 1000→1100；国际版 `hy3` 请求成功，余额当时仍为 350，活跃奖励维持 unknown。当天再次调用两版均保留原 intent，国内余额未再次变化；重复运行路径的写请求计数由离线测试核验。尚未等待令牌自然过期，也未核实国际活跃奖励的发放。

来源与许可见 `provider-source.json` 和 `LICENSE.provider`。协议窄范围移植自 MIT 的 workbuddy-helper；国内状态字段另对照 ZaiZaiCat 公开源码，不引入完整上游程序。
