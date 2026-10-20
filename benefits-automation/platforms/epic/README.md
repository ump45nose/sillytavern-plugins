# Epic 免费游戏

一次性原生 Camoufox 任务：恢复账号 profile、必要时登录、查询当前免费游戏、检查购物车和零价、提交一次、重新查询所有权。使用持久账号状态和订单 journal，没有容器、VNC、调度器、录屏或浏览器池。

## 依赖

浏览器与挑战处理分开安装；未遇到挑战不会加载模型 SDK、numpy 或图像库。

```sh
python3 -m venv .venv-epic
.venv-epic/bin/pip install --require-hashes -r locks/epic-browser-python312-linux-x86_64.txt
.venv-epic/bin/pip install --require-hashes -r locks/epic-challenge-python312-linux-x86_64.txt
.venv-epic/bin/python -m camoufox fetch
```

锁针对 Python 3.12 / Linux x86_64。运行前安装浏览器，配置其绝对缓存目录；任务不会自动下载浏览器。已验证 Camoufox 0.4.11 / Playwright 1.53.0 的 NAS 启动。

## 配置与调用

`EPIC_CONFIG` 指向源码目录外的私有 JSON，权限 0600：

```json
{
  "email":"your-account@example.com",
  "password":"your-private-password",
  "proxy":"http://your-existing-proxy:7890",
  "browser_cache":"/absolute/camoufox-cache",
  "model":{
    "name":"your-CPA-model",
    "base_url":"http://your-existing-provider/v1",
    "api_key":"your-private-key"
  }
}
```

model 是可选挑战路径使用的 OpenAI compatible 视觉模型。当前 NAS 延用已有 CPA 的 `gemini-3.8-flash-high` 配置。图片只在挑战期间临时使用，不保留截图/录屏；调用不自动重试。不要将邮箱、密码或 key 放命令行或 Git。

验证码模型同时接收当前原题和 SDK 技能提示。单次模型请求最多 120 秒，整轮挑战最多 300 秒，并受本次任务剩余时间约束；验证码通过后继续独立确认游戏所有权。

挑战 SDK 返回的执行超时和响应超时统一报告 `challenge_timeout`，与实际未通过区分。浏览器在进入业务工作流之前超时报 `browser_timeout`。原生入口、工作流和 SDK 内部捕获的错误保留异常类型及源码位置，不记录原始错误消息、会话 token、图片或模型响应。商店部分脚本的 403 不覆盖实际可用的业务控件或当前登录、验证码状态；有界观察后仍无法确认页面状态时，才报告资源拒绝。进入结算后仍须通过商品身份、零价和独立所有权回查，不能据此确认领取。

主文档返回 `cf-mitigated: challenge` 时，以响应协议识别 Cloudflare 验证，不依赖页面语言或可见 iframe。浏览器使用 Camoufox 的 [`disable_coop=True`](https://camoufox.com/python/usage/)，使 Turnstile 跨域 iframe 可读取和正常点击；自动 Managed Challenge 保持当前页面并有界等待，再由工作流读取真实状态，不调用 hCaptcha 模型。初始化阶段也先完成当前验证，随后才处理明确的未登录状态。单个子资源的挑战响应不能替代主文档状态。

hCaptcha 组件可能在显示前已取得题目。浏览器仅在内存保留当前页面最新的脚本与题目响应，处理器按需创建后读取一次，避免错过响应而空等 30 秒或丢失题型、题数。CORS OPTIONS 不交给题目/答案解析器；HTTP 400 的真实 POST 答案响应仍保留失败语义。没有重发验证码 API 请求，也不落盘响应或 token。

```sh
EPIC_CONFIG=/absolute/private/epic.json \
.venv-epic/bin/python platforms/epic/run.py \
  --runtime-root /absolute/private/runtime --execute
```

每次一个账号，profile 位于 `state/epic/<account>/browser/`。同级 `browser-identity.json` 保存该账号的 Camoufox 身份，跨次启动复用，并与 profile 一起备份、恢复，保持指纹与 Cookie 对应；已有身份损坏时直接报错。当前促销为空时 claim 不适用；所有当前免费游戏均经所有权确认才返回 complete。初次读回即已在库时，将该游戏已有的未确认 intent 确认为 confirmed，不创建新的领取记录。登录成功或验证码通过不代表游戏领取成功。

`proxy` 可省略以使用直连。目录读取复用已完成会话检查的商店页，避免重复加载首页；线路和验证码处理均须通过当前浏览器与所有权回查验证。

统一结果包含本次新领、已在库、未确认、当前促销数量，以及游戏名称、商品 ID、商店链接和结论。清单读取失败时数量为 null，不输出虚假的“新领 0 款”。见 [结果契约](../../docs/RESULTS.md)。

## 恢复与验收边界

公开入口绑定已授权的普通登录、验证码和账号链接处理，不要求每次由 Hermes 建立额外批准回调。缺少真实 MFA 数据或新增协议/年龄/账号设置时返回具体未完成原因，不虚构信息。

商品页明确显示未登录时，先点击商店自己的登录控件，由商店生成认证跳转。已准备的领取跳转进入商店 `/login` 时，保留该 URL 完成一次 SSO 恢复。每个商品只允许一次该恢复；不会重复点击领取按钮，也不在订单提交后的不确定阶段重新登录或提交。

已有付费或无法识别的购物车不清空。商品页的直接领取使用该商品的官方独立结算 `/purchase?offers=1-namespace-offerId--`，不点击可能自动下单的 Get / 快速领取入口，也不因另一购物车里有付费商品而中断；加入购物车的路径仍检查整车。两种路径的订单都必须匹配当前商品身份且明确零价；发送前持久化 `claim-journal.json`。提交不明确时只读查所有权，不再次下单。具体见 [验收记录](../../docs/IMPLEMENTATION_ACCEPTANCE_2026-10-03.md)。

结算身份兼容已观察到的 `/purchase?offers=1-namespace-offerId--` 格式。数量变化、额外参数和重复身份参数仍不予确认；结算窗口有独立的有限加载等待，期间持续检查登录、验证码和账号提示。

2026-10-20 用户在 MacAir Chrome 的首次领取成功，但观察到商品领取至购买页跳转约两分钟。独立结算导航及结算/提交后的控件观察现各最多等待 150 秒，并受本次任务剩余时限约束；其间不重新导航或重复点击，登录、验证码、条款等明确状态立即返回处理。该修复只覆盖过早超时，不代表商店资源 403 或支付拒绝已经解决。

NAS 浏览器可能触发“Device not supported”提示。仅在已绑定当前商品、官方商店的结算阶段，且弹窗完整文字和按钮精确匹配时点击一次 Continue，随后仍重新核对商品身份和零价。新增协议、年龄、账号设置或其他 Continue 提示不复用此处理。

2026-10-09 原 Hermes 入口实跑成功，run ID 为 `78d5a00f-76ab-4b77-a834-67b095fc846d`。当期 Out of Sight 和 TerraScape 两款均确认在库；正式任务记录一款已在库、一款新领、零项未确认。已有付费购物车未被修改。

2026-10-20 正式回执已确认用户手动领取的 Bad Cheese 在库，Agent A 仍未在库；商品与独立零元结算均可加载，但间歇性资源 403 尚未根治。本日经额外授权只对 Agent A 点击一次提交，失败于 hCaptcha SDK 的 `RetryError` 及后续刷新异常，没有发送 confirm-order 或 challenge-order；旧 intent 和本次独立 intent 均保留。2026-10-19 的 `epic.error.captcha.challenge.failed` 支付拒绝尚无成功领取对照，不能称已解决。详细证据与未完成项见 [持续排查计划](../../docs/plans/2026-10-20-benefits-followup.md)。

业务状态机、浏览器绑定和挑战模型桥彼此分开；通用生命周期/锁/结果使用 `common/`。参考 Ronchy2000/epic-freebies-helper 的窄范围实现，GPL-3.0-or-later，原始许可证及固定来源保留在 [upstream](../../upstream/epic-freebies-verifier/) 和 [上游版本契约](upstream-contract.json)。不导入完整上游应用、settings 单例或常驻 worker。
