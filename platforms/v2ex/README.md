# V2EX 单账号 HTTP 适配器

公开入口为 `run.py`，默认不执行；实际调用须显式 `--execute` 并事先授权。使用独立的 requests 依赖锁与 `V2EX_COOKIE`，可选 `V2EX_PROXY`、`V2EX_USER_AGENT`，不安装 dailycheckin 全包。

## 来源与本地改动

`provider.py` 从 dailycheckin 25.12.9 的 MIT 模块提取；原 wheel/module 哈希与本地改动记录在 `provider-source.json`，许可证为 `LICENSE.provider`。它是保留来源归属的本地适配版本，不是字节不变的上游副本；归档来源未修改。

默认 provider 的输出和请求顺序仍通过原始 fake Session 对照。适配器额外传入只读恢复、写前 intent 和余额确认回调；余额已经确认后，即使可选的连续天数查询失败，也保留业务事实。

## 有界 HTTP 与重复执行

- 请求强制 TLS 证书验证，关闭环境代理/凭据发现；显式代理仍可配置
- 私有 Cookie 仅用于初始化官方域名的会话 Cookie jar，接受后续 Set-Cookie 更新；不固定 Cookie 请求头，以免 PB3_SESSION 更新后仍携带旧会话导致领取令牌失效。
- 强制 streaming，按解码后的响应流累计最多 1 MiB，超限立即关闭响应；每次请求 30 秒，整任务仍受运行器总超时约束
- 禁止自动重定向，同时禁用 requests 为 `Response.next` 预读重定向响应的路径，避免在字节上限生效前缓冲大响应。遇到重定向返回未知/失败，不绕过证书或站点限制
- `BENEFITS_STATE_DIR/http-actions.json` 保存一个账号/业务日的有界 redeem intent。发出领取 GET 前先原子同步记录；该 GET 虽不是 POST，仍视为写操作
- 写请求不明确时，下一次只查询页面和余额，禁止重发 redeem。账目含当日每日登录奖励才确认 complete；已确认当日结果直接保留，不再签到
- 可导入严格校验且账号/平台/业务日相符的旧确认结果；损坏动作记录不授权写操作。动作记录不保存 Cookie 或网页内容

离线测试：`python -m unittest discover -s tests -p test_v2ex.py -v`，以及独立 HTTP 环境中的 `PYTHONPATH=. python tests/provider_contract.py`。测试覆盖默认来源等价、真实 requests Session 的 fake transport 绑定、超限流、重定向预读、异常恢复和已确认动作去重；不访问真实 V2EX。

## 独立运行

```sh
python3 -m venv .venv-http
.venv-http/bin/pip install --require-hashes -r locks/http-python312-linux-x86_64.txt
.venv-http/bin/python platforms/v2ex/run.py --runtime-root /absolute/private/runtime --execute
```

使用仓库外的 V2EX_COOKIE 环境变量；不安装浏览器或其他平台模块。2026-10-03 NAS 通过今日奖励账目只读恢复确认。输出标准 JSON 和结果文件，调度、日报与通知由调用方负责。

2026-10-20 现场确认：当日 08:12（北京时间）运行在领取前的只读查询阶段遇到瞬时网络错误，直接报 `provider_error` 失败；13:58 的后续运行网络恢复后自动签到成功。现在领取前（未发生写操作）遇到网络类异常会原地重试一次，仍失败才上报，并单独归类为 `network_error`，不再与其他 provider 异常混淆。

## 统一结果

通用 JSON 补充运行起止时间、耗时及 `details.metrics/items`。数值未知时为 null；已签到与奖励已到账分别判断。字段与各平台事实边界见 [结果契约](../../docs/RESULTS.md)。
