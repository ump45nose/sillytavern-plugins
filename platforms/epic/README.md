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

挑战 SDK 返回的执行超时和响应超时统一报告 `challenge_timeout`，与实际未通过区分。浏览器在进入业务工作流之前超时报 `browser_timeout`。原生入口、工作流和 SDK 内部捕获的错误保留异常类型及源码位置，不记录原始错误消息、会话 token、图片或模型响应。商店脚本被 403 拒绝时停止领取，不把静态商品按钮当作可用页面。

```sh
EPIC_CONFIG=/absolute/private/epic.json \
.venv-epic/bin/python platforms/epic/run.py \
  --runtime-root /absolute/private/runtime --execute
```

每次一个账号，profile 位于 `state/epic/<account>/browser/`。当前促销为空时 claim 不适用；所有当前免费游戏均经所有权确认才返回 complete。登录成功或验证码通过不代表游戏领取成功。

统一结果包含本次新领、已在库、未确认、当前促销数量，以及游戏名称、商品 ID、商店链接和结论。清单读取失败时数量为 null，不输出虚假的“新领 0 款”。见 [结果契约](../../docs/RESULTS.md)。

## 恢复与验收边界

公开入口绑定已授权的普通登录、验证码和账号链接处理，不要求每次由 Hermes 建立额外批准回调。缺少真实 MFA 数据或新增协议/年龄/账号设置时返回具体未完成原因，不虚构信息。

已有付费或无法识别的购物车不清空。商品页的直接领取使用该商品的独立结算，不因另一购物车里有付费商品而中断；加入购物车的路径仍检查整车。两种路径的订单都必须匹配当前商品身份且明确零价；发送前持久化 `claim-journal.json`。提交不明确时只读查所有权，不再次下单。具体见 [验收记录](../../docs/IMPLEMENTATION_ACCEPTANCE_2026-10-03.md)。

结算身份兼容已观察到的 `/purchase?offers=1-namespace-offerId--` 格式。数量变化、额外参数和重复身份参数仍不予确认；结算窗口有独立的有限加载等待，期间持续检查登录、验证码和账号提示。

NAS 浏览器可能触发“Device not supported”提示。仅在已绑定当前商品、官方商店的结算阶段，且弹窗完整文字和按钮精确匹配时点击一次 Continue，随后仍重新核对商品身份和零价。新增协议、年龄、账号设置或其他 Continue 提示不复用此处理。

2026-10-09 原 Hermes 入口实跑成功，run ID 为 `78d5a00f-76ab-4b77-a834-67b095fc846d`。当期 Out of Sight 和 TerraScape 两款均确认在库；正式任务记录一款已在库、一款新领、零项未确认。已有付费购物车未被修改。

业务状态机、浏览器绑定和挑战模型桥彼此分开；通用生命周期/锁/结果使用 `common/`。参考 Ronchy2000/epic-freebies-helper 的窄范围实现，GPL-3.0-or-later，原始许可证及固定来源保留在 [upstream](../../upstream/epic-freebies-verifier/) 和 [上游版本契约](upstream-contract.json)。不导入完整上游应用、settings 单例或常驻 worker。
