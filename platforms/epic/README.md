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

```sh
EPIC_CONFIG=/absolute/private/epic.json \
.venv-epic/bin/python platforms/epic/run.py \
  --runtime-root /absolute/private/runtime --execute
```

每次一个账号，profile 位于 `state/epic/<account>/browser/`。当前促销为空时 claim 不适用；所有当前免费游戏均经所有权确认才返回 complete。登录成功或验证码通过不代表游戏领取成功。

## 恢复与验收边界

公开入口绑定已授权的普通登录、验证码和账号链接处理，不要求每次由 Hermes 建立额外批准回调。缺少真实 MFA 数据或新增协议/年龄/账号设置时返回具体未完成原因，不虚构信息。

已有付费或无法识别的购物车不清空。订单必须匹配当前商品身份且明确零价；发送前持久化 `claim-journal.json`。提交不明确时只读查所有权，不再次下单。当前促销已在库的只读轮询通过；本次未遇到新订单或 hCaptcha，真实下单/挑战仍需后续促销验证。具体见 [验收记录](../../docs/IMPLEMENTATION_ACCEPTANCE_2026-10-03.md)。

业务状态机、浏览器绑定和挑战模型桥彼此分开；通用生命周期/锁/结果使用 `common/`。参考 Ronchy2000/epic-freebies-helper 的窄范围实现，GPL-3.0-or-later，原始许可证及固定来源保留在 [upstream](../../upstream/epic-freebies-verifier/) 和 [上游版本契约](upstream-contract.json)。不导入完整上游应用、settings 单例或常驻 worker。
