# 阿里云开发者社区签到

独立 HTTP 脚本，只做当前社区签到、连续奖励资格检查和待收积分领取。不导入上游完整 main，不做评论、点赞、分享或通知。

## 依赖与调用

Python 3.12、requests；可复用仓库根目录的 HTTP venv：

```sh
python3 -m venv .venv-http
.venv-http/bin/pip install --require-hashes -r locks/http-python312-linux-x86_64.txt
.venv-http/bin/pip install --require-hashes -r locks/cookiecloud-python312-linux-x86_64.txt
```

外部 provider 来自 WillpowerJin/ql-scripts 的 `aliyun_dev/daily.py`，固定提交 `37f42204a8eea3a489e67e866a2b356bed4b9b22`，SHA256 `286563810a780f06edaa0eea2dd0633480b403d6634ab3357d0890df77b696c3`。未确认该文件的分发许可证，因此不复制进本仓库；自行取得后用 `ALIYUN_UPSTREAM_PATH` 指定，内容不匹配就拒绝导入。

```sh
ALIYUN_UPSTREAM_PATH=/absolute/reviewed/aliyun_dev/daily.py \
COOKIECLOUD_CONFIG=/absolute/private/cookiecloud.json \
.venv-http/bin/python platforms/aliyun/run.py \
  --runtime-root /absolute/private/runtime --execute
```

也可用 `ALIYUN_COOKIE`，可选 `ALIYUN_PROXY`。配置了 CookieCloud 时，每次使用其最新 developer.aliyun.com Cookie，不回退到失效的旧值。格式见 [公共凭据说明](../../docs/CREDENTIALS.md)。凭据不进 Git，不在命令行提供。

## 确认与恢复

2026-10-03 NAS 使用新推送的 CookieCloud 数据：默认社区签到和待收积分读回确认；14 个旧社区返回明确无活动数据，标记不适用，不当作签到失败。

签到及连续奖励请求沿用 provider 的 JSON 请求格式。连续奖励仅明确符合资格才领取；精确“不满足领奖条件”回执可表示当前不适用，不推断先前不明确的领奖已到账。

`http-actions.json` 在写请求前记录账号/日期/社区 intent。不明确的签到和领奖只读恢复；签到确认后仍查询奖励。15 个社区分别保留结果，汇总允许明确不适用，但不会用第一个社区成功遮盖其他未知结果。未核实奖励 intent 不因换日自动删除。

单请求 30 秒、响应最多 1 MiB；默认总预算 480 秒。损坏状态拒绝进一步写请求。输出通用 JSON 与逐社区结果，不保留 Cookie 或完整响应。
