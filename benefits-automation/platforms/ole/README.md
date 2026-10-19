# Olé 精品超市

单账号一次性签到，使用 Olé 微信小程序会员的实际商家会话。调度和通知由 Hermes 负责。

## 依赖与配置

Python 3.12 标准库、Node.js 24；不额外安装 npm 包或浏览器。首次登录和会话失效续登需要共用的 `common/wechat_code.cjs`（由 YYB 登录能力任务提供）。该文件尚未集成时，已有商家会话仍可查询，取码会明确返回 `wechat_code_unavailable`。

先在官方 Olé 小程序完成会员注册和必要授权，再将微信账号扫码加入自己的 YYB 服务。`OLE_CONFIG` 指向仓库外的绝对 JSON 路径，文件权限为 0600：

```json
{
  "wechat": {
    "url": "http://127.0.0.1:8000",
    "token": "replace-with-private-yyb-token",
    "account": "your-yyb-account-ref"
  },
  "shop_code": "your-real-ole-shop-code"
}
```

`wechat.account` 是 YYB 的账号引用；Olé 使用的 `open_id` 必须从 Olé 登录响应取得，二者不能互换。取码使用 AppID `wx6c61aaeba1551439`，code 当次消费，不写日志或缓存。商家 session/openid 原子保存至运行目录 `state/ole/<account>/ole-state.json`。

门店选择依次为显式 `shop_code`、商家状态/登录响应的 `shop_code`。两者都没有时，可在私有配置中提供 `location`，格式为自己的 `经度,纬度`；适配器通过商家门店接口解析门店。未提供必要门店信息时返回 `missing_shop_configuration`，不提交签到。没有默认坐标或作者门店。可选 `user_agent` 覆盖公开参考使用的微信小程序 UA。

```sh
export OLE_CONFIG=/absolute/private/ole.json
python3 platforms/ole/run.py --runtime-root /absolute/private/benefits-data --account ole-main
python3 platforms/ole/run.py --runtime-root /absolute/private/benefits-data --account ole-main --execute
```

不加 `--execute` 不读凭据、不联网。每个微信会员使用不同账号代号和配置；同一账号代号已绑定的 YYB 地址/账号引用变化时返回 `account_configuration_mismatch`，避免重用另一个账号的商家会话。YYB token 轮换不改变该绑定。

## 执行与结果

1. 复用已缓存商家会话；只有明确认证拒绝才重新取码登录一次。网络或商家接口故障不会使缓存失效。
2. 查询 `member_sign`，`sign_of_day=Y` 才确认当日已签到，`N` 才允许准备签到。未知结构停止写操作。
3. 获取真实门店，先保存当日提交 intent，再发送一次签到 POST；随后 GET 读回，只有 `sign_of_day=Y` 才确认签到。
4. 连接中断、POST 被拒绝或读回未确认时保留 pending，当日后续执行只读查询，不自动重发。即使修改门店配置，也不会自动重放当天已有 intent；下一业务日重新按当日状态判断。

结果沿用 schema v1。`business.checkin` 与 `business.balance` 分别表示签到、积分余额查询；签到确认而余额缺失时仍保留签到完成，入口返回 3。`details.metrics.balance` 的 `before/after/delta` 是本次调用前后观测；未做写操作时只提供当前 `after`，不编造签到奖励数。读回失败保留先前 `current/before`，`after/delta` 为 null。

常见原因：

| 原因 | 处理 |
| --- | --- |
| `membership_registration_required` | 微信号尚未完成 Olé 会员注册，先在官方小程序处理 |
| `wechat_code_authentication_invalid` / `wechat_code_account_unavailable` | 核对 YYB 访问令牌或重新扫码登录 |
| `wechat_code_connection_failed` / `wechat_code_timeout` | 检查执行侧至 YYB 服务的连接 |
| `authentication_invalid` | 商家会话认证拒绝；一次续登后仍拒绝时停止 |
| `merchant_login_response_invalid` | 登录返回不符合已核对字段，不能当作未注册或登录成功 |
| `missing_shop_configuration` | 补充真实门店编码或自己的位置 |
| `write_pending_confirmation` | 本日提交结果仍待读回，不重签 |
| `checkin_state_conflict` | 本日已有确认记录，但当前接口却返回未签，需要核对业务日期/平台状态 |

## 验证与来源

```sh
node --test tests/ole-checkin.test.cjs
python3 -m unittest discover -s tests -p 'test_ole_entrypoint.py' -v
```

参考 [smallfawn Olé 脚本的固定提交](https://github.com/smallfawn/QLScriptPublic/blob/6f471a97fa0a9f418f41978c3d79638961183478/wxapp/olecs.js)，精确 SHA-256 和使用边界见 `provider-source.json`。仅依据公开协议独立实现适配器，没有导入其框架、推送、作者坐标或签到失败自动重试。

目前完成离线验证；尚未使用真实微信/Olé 账号联调。需要验收 YYB 对该 AppID 的扫码取码、商家会员登录、实际门店、真实签到及积分读回、过期会话续登。模拟测试不代表这些步骤已经通过，也没有启用生产调度。
