# WeTalk 单账号签到

`run.py` 复用项目的 Task、账号锁、超时监督和 JSON 结果。Node.js 22/24 与 Python 标准库即可运行，不安装 npm 包或浏览器。调度、日报与通知由 Hermes 集成，适配器本身不推送。

## 凭据

环境变量 `WETALK_CONFIG` 指向**仓库外的绝对路径 JSON 文件**。文件仅运行身份可读（0600 或 0400），不能是符号链接，最多 16 KiB。

结构示例（仅示意格式，不是一组足以登录的凭据）：

```json
{
  "params": {
    "email": "your-account@example.invalid"
  },
  "headers": {
    "User-Agent": "从本人有效 WeTalk 请求复制的值"
  }
}
```

从本人已登录客户端的 `https://api.wetalkapp.com/app/queryBalanceAndBonus` 或 `checkIn` 请求提取：

- `params`：所有实际查询参数，值为**URL 解码一次后的原始字符串**。已有 Quantumult X 存储中的 `capture.params` 已完成解码，可直接提取该账号这一项；不要再次解码，尤其不能改写字面量 `+` 和 `%xx`。
- 旧 `sign`、`signDate` 可删去，程序每次按当前 UTC 时间重算；其他认证、设备、版本字段按实际请求保留。上游只明确要求 `email`，没有给出完整最小认证字段清单，因此不能假设只填邮箱即可登录。
- `headers`：保留原请求的 User-Agent，以及实际存在的 Authorization、Cookie 或其他业务认证头。Host、连接、内容长度、压缩和代理等传输头会丢弃，不保存原始 URL、整个账号存储或完整 HAR。

原始参数只保存在该私有配置。结果、日志和动作记录不输出邮箱、认证头、签名请求 URL或原始响应；账号代号使用 `account1` 等不含邮箱的名称。

固定来源的手写 MD5 未按 UTF-8 编码字符串。已用其原函数对照 ASCII 签名，中文参数的结果与标准 UTF-8 MD5 不同；本版遇到非 ASCII 查询参数明确返回 `signature_parameters_unsupported`，不会猜测另一种签名。请求头保留客户端的合法取值。

### CookieCloud 与一次性客户端捕获

2026-10-19 同步中的 `.wetalkapp.com` 只有 `_c_WBKFRo`、`_nb_ioWEgULi` 两个 Cookie，没有本适配器需要的查询参数。真实只读对照中，不带 Cookie 和仅带这两个 Cookie 均返回 `retcode=100004`、`Missing param or param error.`，未返回余额或签到资格。HTTP 200 和 Cookie 存在均不代表客户端登录可用。

当前 `mobile.wetalkapp.com` 网页使用 `/web/*` 和 `x-auth-token`；网页 token 不能未经验证就改填到 `/app/*` 的旧客户端参数中。

补齐凭据需要**已登录 WeTalk 客户端产生的一条成功只读请求**：

1. 在 App 内打开会展示当前余额或签到资格的页面，捕获 `GET https://api.wetalkapp.com/app/queryBalanceAndBonus?...`。不需要先点签到，也不需要捕获 `videoBonus`。
2. 将这条请求的全部查询参数（含实际 email、认证、设备、版本等现有字段）与请求头保存到私有文件；不要在聊天、命令行参数或 Git 中粘贴含凭据的 URL。若已有 Quantumult X 捕获，仅导出这一个账号的 `capture.params` 和必要的 `capture.headers`，不需要整个账号库或整份浏览记录。
3. 确认该请求响应的 `retcode=0`，结果包含真实 `balance` 和/或布尔 `isallowcheckin`；响应中的余额数字无需公开。按上面的结构生成 `wetalk.json`，旧 sign/signDate 会重算，不能补猜没有捕获到的邮箱或设备字段。
4. 用 `--execute --status` 验证，再进行一次受控签到、余额读回和重复运行。若只能提供网页 `/web/*` 请求，仍须先验证其能否作为客户端签到凭据，不能直接套用。

## 运行

先在私有环境中设置配置路径，再调用：

```sh
export WETALK_CONFIG=/absolute/private/wetalk.json

# 默认不访问平台，只检查运行器。
python3 platforms/wetalk/run.py --runtime-root /absolute/private/benefits-runtime --account account1

# 只读检查当前余额和签到资格；仍须显式允许网络执行。
python3 platforms/wetalk/run.py --runtime-root /absolute/private/benefits-runtime --account account1 --execute --status

# 查询资格，必要时签到一次，再读回。
python3 platforms/wetalk/run.py --runtime-root /absolute/private/benefits-runtime --account account1 --execute
```

两个接口均为 GET，但 `checkIn` 被作为写操作处理。每个请求最多 30 秒，解码后的响应最多 1 MiB；任务总时限默认 120 秒，固定 HTTPS 主机、正常证书验证、不跟随重定向。入口不会发现其他账号或安装依赖。

## 确认与恢复

- 首先查询 `queryBalanceAndBonus`。只有严格布尔值 `isallowcheckin=true` 才允许提交。`false` 加明确“已签到”原因可确认完成；其他不可签到原因报告 blocked，缺失/异常资格字段为 unknown，均不提交。
- `state/wetalk/<account>/checkin.json` 在提交前原子保存并 fsync intent。签到业务回执 `retcode=0` 或明确的已签到回执保留完成事实；余额查询单独判断。
- 丢失写响应时立即只读查询。明确的已签到状态可以恢复确认；仍不能确认时保留 pending，同一业务日后续调用只读，不因网络错误重发签到。需要排查 pending 时先核对官方客户端和真实状态；不要直接删除 intent 触发重签。
- 明确的参数缺失、登录、签名、限流或 HTTP 403 拒绝没有接受写操作，可在修正问题后的下一次调用重新查资格；未知错误继续保留 intent。
- 当日回执与平台仍允许签到发生冲突时报告 `checkin_readback_conflict`，保留已收到的回执且不重发。此情况需核对平台重置时区；UTC 签名时间不证明签到以 UTC 零点重置。
- 动作记录只保存一个账号/业务日的事实和可核实奖励，账号邮箱的 SHA-256 摘要用于防止同一代号换号后复用旧回执。换账号须使用不同账号代号。

## 结果

使用现有 schema v1，`business.checkin` 表示签到，`business.balance` 表示余额查询。集成层需为 `balance` 添加“余额查询”显示名。

- `details.metrics.balance`：Coins 当前余额、本次调用的 before/after/delta。没有结束读回时 after、delta 为 null，保留已读到的 current/before；只有一次查询也不编造第二次余额或零增量。
- `details.metrics.reward`：签到回执中明确返回的 bonus；缺失为 null。可从本业务日私有回执保留，但不能把奖励文案解析为已到账金额，也不能将本次余额差当成全天签到收益。
- 已确认签到后余额请求失败，仍保留 checkin complete，同时报告读取错误。未知余额不记 0。
- 已实测的 `100004` 加 `Missing param or param error.` 返回 `request_parameters_invalid`，表示缺少或无效的客户端请求参数，不误报成已尝试签到被拒绝。登录、签名、限流、网络、非 JSON/超限响应分别输出稳定原因；其他未知业务错误不猜测私有码，当前没有经过真实账号校验的完整 retcode 对照表。

0 表示请求的业务均完成；3 表示正常执行但签到未完成、不可签到或余额未知；1 表示执行、配置或 I/O 失败。只读模式查询到尚未签到时为 incomplete，退出 3，并不表示已执行签到。其他锁忙、总时限退出码沿用公共运行器。

## 来源与验证

协议参考 [ZenmoFeiShi/Qx 的固定 WeTalk.js 提交](https://github.com/ZenmoFeiShi/Qx/blob/b057f396ffb93c65342f87b98c3bad97d54b5fad/WeTalk.js)，提交、文件 hash、编码边界和许可缺口记录在 `provider-source.json`。本地以 Node 内置 crypto/fetch 独立实现所需协议，没有复制上游手写 MD5、账号捕获/迁移框架、视频循环或通知，也未将未知许可代码标为 MIT。

离线验证：

```sh
node --test tests/wetalk.test.cjs
python3 -m unittest discover -s tests -p test_wetalk.py -v
```

测试包含固定上游签名向量、UTC/百分号/加号编码、资格判断、intent 和跨次恢复、响应限制、凭据不泄漏；Python 测试用真实 Node 适配器和启动器连接受控 HTTP transport，不访问 WeTalk。

已经完成仅 Cookie 的真实只读错误对照，尚无可用客户端参数；**未验证真实签到、实际登录/签名错误码、平台重置时间或 Coins 发放**。真实验收先运行只读模式，再受控签到、再次查询及重复运行，核对客户端当前状态与余额；不能以离线测试或程序退出 0 替代这一步。
