# GLaDOS 单账号签到

独立 HTTP 执行器，复用公共 `Task`、账号锁、总时限及 JSON schema v1。不启动浏览器、通知或调度服务。基础执行仅依赖 Python 3.12 标准库；可选 CookieCloud 使用既有解密依赖。

## 配置与运行

将下面的配置放入仓库外权限 0600 的私有环境文件，由调用方加载。不要把实际 Cookie 放入命令行、源码、终端输出或 Git。

| 变量 | 要求 |
| --- | --- |
| `GLADOS_ORIGIN` | 必填，获取 Cookie 时的单一 HTTPS origin，例如 `https://glados.cloud`；不能包含路径、参数、账号密码或候选域名列表。 |
| `GLADOS_USER_AGENT` | 必填，获取 Cookie 的浏览器请求使用的完整 User-Agent；不自动猜测或轮换设备。 |
| `GLADOS_COOKIE` | 单账号完整 Cookie 请求头，必须包含完整 `gld:sess`/`gld:sess.sig` 或旧版 `koa:sess`/`koa:sess.sig` 配对。 |
| `COOKIECLOUD_CONFIG` | 可选，既有私有 CookieCloud 配置文件路径。配置后从对应 origin 主机读取 Cookie，缺失/失效时不回退到旧环境 Cookie。 |
| `GLADOS_TOKEN` | 可选，默认取 origin 的 hostname。仅在浏览器真实签到请求使用不同 token 时显式覆盖。 |
| `GLADOS_PROXY` | 可选，显式 HTTP/HTTPS 代理 URL。未配置时直连，不读取进程的全局代理环境。 |

CookieCloud 只替代 Cookie 来源，不能替代匹配的 User-Agent 与域名配置。其私有配置格式及依赖见公共凭据说明；本平台不创建同步服务或保存全站 Cookie 缓存。

在项目根目录运行：

```sh
python3 platforms/glados/run.py --runtime-root /absolute/private/benefits-data --account glados_main

# 调用方已加载仓库外的环境文件后，先进行只读认证、签到记录与积分检查：
python3 platforms/glados/run.py --runtime-root /absolute/private/benefits-data --account glados_main --execute --status

# 执行签到：
python3 platforms/glados/run.py --runtime-root /absolute/private/benefits-data --account glados_main --execute
```

不加 `--execute` 不联网，返回 `execution_not_requested`。`--status` 的平台请求全部只读；同样必须加 `--execute` 才会访问网络。所有入口沿用公共 `--timezone`，默认 Asia/Shanghai；历史记录的毫秒时间按该时区换算业务日，与官网日历使用访问者本地日期的方式一致。

## 确认与恢复

先请求 `/api/user/status` 和 `/api/user/points`。只有结构有效的积分历史允许判断当前日期是否已有签到；缺失/异常 history 不能授权新的写请求。当天有 `checkin` 业务账目时直接确认，邀请等其他入账不会当作签到，余额上涨也不会代替签到证据。

写请求前，`state/glados/<account>/checkin.json` 原子保存并同步账号/日期的 pending intent。每次最多提交一次 `POST /api/user/checkin`；网络异常、重定向或未识别响应后只读查询积分历史，本日后续调用继续只读恢复，不重新提交。明确的登录失效、设备不匹配或自动签到拒绝表示本次未执行签到，允许在修正配置后再次调用。日常签到按业务日独立，昨日 intent 不阻止下一天的动作。

`code=0` 是直接成功回执。`code=1` 只接受固定的已签到文案，其余值保留未确认；HTTP 200 本身不算成功。已确认签到与直接返回的奖励在本地保存，即使结束读回失败也不撤销；当前余额、签到奖励、剩余天数及连续天数独立交付，缺失值为 null。

`details.metrics.balance.delta` 只表示本次两次观测的余额差，不能当全天签到所得。`reward` 是本日签到已确认的奖励数值；已经签到后再次查询可得到 reward>0 且 delta=0。结束读回失败保留之前的 current，但 after/delta 为 null；不会从剩余天数或奖励文案推算积分。连续天数仅取接口 `streak`，不自行推断。

单次请求限时 20 秒，响应最多 1 MiB；总预算默认 180 秒。强制 TLS 验证、禁止重定向，Cookie 不跨域发送；无自动镜像切换、POST 重试或自动兑换。损坏状态会在联网前阻止执行。结果、状态和日志不保存邮箱、Cookie、User-Agent 或完整响应。

HTTP 403 本身不表示 Cookie 失效。明确的 Cloudflare 1010 JSON（cloudflare_error=true、error_code=1010）报告 `cloudflare_browser_signature_banned`；带 `cf-mitigated: challenge` 的响应报告 `cloudflare_challenge`，其余 403 保留 `access_denied`。这两类站点拦截不能冒充 GLaDOS 的认证拒绝或业务成功。

## 来源、测试与真实验收

本地实现参考 dff652/GLaDOS-Qinglong 的协议，并核对了 2026-10-19 官网前端的积分读取、日历和设备拒绝流程。固定提交、文件哈希与归属记录在 `provider-source.json`；没有复制或运行未确认许可的完整上游脚本，也没有引入其 pandas 或推送依赖。

```sh
python3 -m unittest discover -s tests -p test_glados.py -v
```

43 项离线测试覆盖真实入口与结果落盘、HTTP 请求格式及大小上限、重定向阻断、认证/设备/自动化拒绝、当天记录去重、毫秒时间及时区、单次 intent、跨次只读恢复、CookieCloud 绑定及 Cloudflare 拦截分类。初次开发曾以无效占位 Cookie 对公网 status/points 验证认证拒绝；真实 Cookie 的 Python 默认 UA 诊断曾返回 Cloudflare 1010。模拟测试及不同访问条件下的历史成功不能替代下面的真实账号验收。

2026-10-19 已从 Mac Chrome 的 `chrome://version/` 页面通过原生保存 HTML 读取真实 UA，写入 Hermes 私有 glados.json；Cookie 继续来自既有 CookieCloud。同一 Cookie 和访问路径下，Python 默认 UA 返回 1010，实际 Chrome UA 可正常读取认证后的 status，期间没有改变共享代理或浏览器设置。

Hermes 身份的只读入口和正式 `--execute` 入口均退出 0，checkin/reward/balance 全部确认。正式 run `9b99c8fd-7649-4c82-8d7a-8eca20715cb9` 读到今日已签到、积分 10、本日奖励 10、连续 1 天、剩余 14 天，本次余额差为 0。重复真实业务调用只产生两个 GET，未发签到 POST；请求计数证据保存在私有诊断目录。

本次验证覆盖真实认证、当前账目及已签去重场景。由于当天已经签到，没有为验收强行重发 POST；首次未签到日的新签到正向样本仍待实际运行覆盖。后续按先 `--execute --status`、再常规执行、再重复运行的顺序验收新账号。保留真实拒绝原因，不以镜像切换、猜测设备或关闭证书校验来冒充修复。调度及异常日报由集成任务完成。
