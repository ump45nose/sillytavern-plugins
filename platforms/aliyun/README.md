# 阿里云开发者社区

一个账号一次调用，只做现有范围内的签到和领奖。不调用上游 `main()`、完整任务、点赞/评论/分享、清理互动、外部通知或密码登录。默认入口不访问网络，只有显式 `--execute` 才执行。

## 外部依赖

- Python 3.12；`requests` 可复用根目录的已固定 Python 依赖环境
- 外部 `daily.py`：来源 `WillpowerJin/ql-scripts`，候选版本 `37f42204a8eea3a489e67e866a2b356bed4b9b22` 的 `aliyun_dev/daily.py`
- 文件 SHA256：`286563810a780f06edaa0eea2dd0633480b403d6634ab3357d0890df77b696c3`

该文件在当前上游仓库的许可证未确认，因此本项目不重新分发。将用户自行取得的文件位置设为 `ALIYUN_UPSTREAM_PATH`；内容哈希不匹配时拒绝导入。该来源是本次可核对的候选基线，不代表已经确认 NAS 旧运行文件的版本。

## 配置

只读取当前账号的 `ALIYUN_COOKIE`、`ALIYUN_UPSTREAM_PATH` 和可选 `ALIYUN_PROXY`。凭据放在源码目录之外，不放在命令行或提交到 Git。账号代号来自通用 `--account` 参数。没有密码登录回退，不读取上游账号 YAML 或会话缓存。

```sh
python platforms/aliyun/run.py --runtime-root /absolute/private/runtime --account default
```

以上仅生成未请求执行的结果；真实运行需显式增加 `--execute`，并事先准备凭据。请先完成自己的授权与账号检查，离线测试不需要任何真实 Cookie。

## 行为与已知限制

- 每个请求最多一次，发生不明确的签到/领奖结果时只读查询，不自动重放写操作
- 签到后最多 30 次、每次间隔 2 秒只读确认；整任务同时受通用运行器超时约束，建议沿用旧任务 480 秒作为初始待测值
- 连续奖励仅在资格接口明确返回成功且 `data` 为布尔 `true` 时尝试领取；明确 `false` 跳过；其他值保持未知。这比旧包装仅判断 code 的方式更保守
- 领取待收积分的 GET 接口具有副作用，同样禁止自动重试；缺失成功代码不算确认
- 平台响应格式、实际积分到账和当前 Cookie 有效性没有在线验证
- 该适配器使用已有 provider 的 HTTP 和认证实现，外部依赖变更需要重新审阅，不能只更新哈希绕过兼容检查

离线验证：`python -m unittest discover -s tests -p test_aliyun.py -v`。全部使用 fake client，不导入外部 daily.py，不访问平台。
