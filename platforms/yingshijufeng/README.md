# 影视飓风小程序签到

单账号、一次性有赞签到执行器，复用公共 `Task`、账号锁、总超时与 JSON 结果。Python 入口只依赖标准库，业务适配使用 Node.js 22+ 内置 `fetch`，没有独立常驻进程或额外 npm 依赖。

## 配置与调用

在仓库外准备权限为 `0600` 的私有 JSON，将其绝对路径传给 `YINGSHIJUFENG_CONFIG`：

```json
{
  "wechat": {
    "url": "http://your-private-yyb:8000",
    "token": "your-private-protocol-token",
    "account": "your-private-yyb-account-reference"
  }
}
```

可选 `user_agent` 为用于该小程序的实际 UA；默认沿用固定参考版本中的 Windows 微信 UA。`wechat.account` 是 YYB 的账号引用，并非影视飓风商家自己的 openid。

```sh
# 不请求执行：不读取配置、不启动 Node、不联网。
python3 platforms/yingshijufeng/run.py --runtime-root /absolute/private/benefits-data --account account1

# 登录并查询积分、当前活动、本地已确认的当日回执；不发送签到请求。
YINGSHIJUFENG_CONFIG=/absolute/private/yingshijufeng.json \
  python3 platforms/yingshijufeng/run.py --runtime-root /absolute/private/benefits-data \
  --account account1 --execute --status

# 查询、按需签到，并再次读取活动和积分。
YINGSHIJUFENG_CONFIG=/absolute/private/yingshijufeng.json \
  python3 platforms/yingshijufeng/run.py --runtime-root /absolute/private/benefits-data \
  --account account1 --execute
```

首次需要先在微信内打开影视飓风小程序，完成商家要求的注册或授权，并在自建 YYB 中完成扫码。YYB 共用客户端 `common/wechat_code.cjs` 由本批集成提供，调用合同为 `getCode(config, appid) -> Promise<string>`；只在没有缓存会话或商家明确拒绝认证时读取一次 code。客户端尚未合入时返回 `wechat_code_client_unavailable`，不退回其他取码服务。

只读模式在没有当日已确认回执时保留 `checkin=unknown` 并退出 3；即使积分可读取，也不将其显示为今日签到已完成。

## 业务与恢复

- 商家 token、sid 和必要 Cookie 原子保存至运行目录的 `state/yingshijufeng/<account>/youzan-session.json`。缓存绑定本地账号与 YYB 来源，账号引用变更不会复用旧身份。code、昵称和手机号不进入缓存或结果。
- 缓存可用时先读取实际积分数值，再获取当前活动。网络或响应结构错误不会被当成 token 过期，也不会清除缓存或重新取码。
- 签到接口使用 GET，但按写操作处理。请求前保存当日 `pending` intent；收到带奖励列表的结构化成功回执或明确“今日已签到”的业务响应后记录 `complete`。泛化的“最大参与次数”不作为今日已签证据。
- 成功回执会在再次查询前交付，后续网络故障不丢失已确认的签到。中断后再次运行只查询，不重复发送当日不确定的签到请求。
- `business.checkin` 表示已确认操作，`business.points` 表示结束时的积分查询；`details.metrics.balance` 提供本次余额前后值与差。余额变化不单独证明签到，也不能解释为全天获得积分。

## 当前证据与待实测

已实测的公开只读响应表明，活动接口没有凭据也可返回 `code=0`、`checkinId`、`showPage=false`、`isShow=false`；积分接口同样可返回 `code=0`、`do_ext=false` 而没有积分。执行器不会据此确认身份、今日签到或活动关闭。

固定参考脚本没有独立的当日签到状态读回字段。当前只能保留结构化提交回执并重新查询活动及积分；发生不确定提交时，余额变动和活动可见性均不能恢复为成功，结果会保持 `checkin_pending_confirmation`。后续应通过真实小程序状态和脱敏接口响应补齐独立读回证据。

尚未取得本人的 YYB/商家凭据，以下验收仍待完成：

1. 两端真实扫码/授权，以及 `clientBiz=weapp_wsc` 登录返回的有效 session。
2. 首次签到、今日重复签到的真实业务响应与积分读回。
3. 商家会话失效后的取码与重新登录，以及独立当日签到状态接口或字段。

遇到 `merchant_points_unconfirmed` 时，说明响应没有可核实积分；它既不等于 0 分，也不自动证明会话过期。遇到当日 `pending` 时，先在真实小程序核实签到及对应响应，保留 journal 作为恢复证据。

## 来源与验证

协议参考 [smallfawn/QLScriptPublic 的影视飓风脚本](https://github.com/smallfawn/QLScriptPublic/blob/640dbac72a991fbc3c8cdedb17ad204eee3c15d9/wxapp/yingshujufeng.js)，固定提交和文件 hash 见 `provider-source.json`。该仓库没有声明许可证，本目录不复制其完整脚本，不在运行时加载上游文件；只独立实现所需协议。

```sh
node --test tests/yingshijufeng.test.cjs
python3 -m unittest discover -s tests -p 'test_yingshijufeng.py' -v
```

这些测试使用模拟商家/取码响应和真实私有文件、公共入口；不调用真实签到，不证明账号已经签到或取得奖励。
