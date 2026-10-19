# 网易严选：积分只读查询

当前交付为官方积分中心的**只读查询**，自动签到尚未完成。没有签到 `run.py`，不要为它注册签到定时任务。

## 已核对的接口

2026-10-19 直接读取官方积分中心页面及其引用的前端资源，确认以下调用链：

1. `GET https://m.you.163.com/xhr/common/checklogin.json` 检查登录。
2. `POST https://m.you.163.com/xhr/points/index.json` 读取积分中心数据，表单正文为空。
3. `yx_csrf` Cookie 解码后的值作为 `csrf_token` 查询参数；Cookie 与 CSRF 必须来自同一会话。

余额字段来自 `data.userPointSimpleInfo.totalPoint`；待领取积分来自同对象的 `unReceivedPoint`；可用积分来自 `data.availablePoint`。后两者缺失时保持 null。只读查询不计算本次收益，所有 before/after/delta 均为 null，也不自动调用 `receiveAll`。

官方页面当前的签到按钮处理会引导进入 App；虽然前端仍声明 `sign` 接口，但本次未找到其当前实际写入调用及“今日已签”的读回契约。历史脚本引用的“打卡领鸡蛋”页面结束时间为 **2024-09-08 23:59:59（Asia/Shanghai）**；匿名访问旧 index 返回未登录，不能证明旧签到活动仍在运行。证据与版本见 [provider-source.json](provider-source.json)。

## 运行

仅依赖 Python 标准库及本仓库 common，无新增服务或第三方运行依赖。

凭据通过私有环境提供：

| 变量 | 用途 |
| --- | --- |
| `YANXUAN_COOKIE` | 官方 `m.you.163.com` 当前登录请求的 Cookie，须含非空 `yx_csrf` |
| `YANXUAN_USER_AGENT` | 可选，获取 Cookie 时的浏览器 UA；默认 `Mozilla/5.0` |
| `YANXUAN_PROXY` | 可选，明确的 HTTP/HTTPS 代理；未配置时直连，不继承其他进程代理 |

不要把 Cookie 放命令行、源码、Git 或调研记录。凭据准备在仓库外的私有环境文件中；本模块不扫描其他平台凭据、不自动登录或续期。

```sh
python3 platforms/yanxuan/status.py --runtime-root /absolute/private/benefits-data
python3 platforms/yanxuan/status.py --runtime-root /absolute/private/benefits-data --account account1 --execute
```

不加 `--execute` 不联网，按现有运行器返回 `execution_not_requested`。加上后只检查登录和查询积分，标准输出一条 schema v1 JSON，并使用公共运行器保存结果和持有账号锁。成功结果仅包含 `business.points_query=complete`，不包含签到完成状态。

每个请求限时 15 秒、响应最多 1 MiB；不自动重试或跟随重定向。HTTP 200 不等于业务成功；登录拒绝、CSRF 缺失、结构变化和余额缺失均输出失败，不从缺失字段补 0，也不把原始响应写入结果。

## 验证状态与剩余工作

- **实测**：官方页面与资源可读取；匿名登录检查返回 `data=false`；旧活动 index 返回 `401 / NO UID`；匿名积分 index 返回业务 `403`。
- **实测**：新客户端使用匿名探针返回 `authentication_invalid`，未继续请求积分。
- **离线验证**：请求方法、目标、CSRF 解码、积分解析、登录/业务拒绝、未知字段、网络失败、重定向、响应限额和独立入口。
- **未验证**：真实账号登录、成功读取账号积分；当前自动签到和签到到账。模拟成功响应仅按已核对的官方字段构造，不代表真实账号样本。

继续实现签到需要当前官方 App/小程序的一组经授权且脱敏的证据：

1. 正常登录后打开签到页的请求、响应字段和当前活动标识。
2. 一次手动签到的 method、host、path、所需头字段名、查询/正文字段名及业务响应结构。
3. 签到前后同一天状态查询的字段变化，以及积分/奖励读回字段。

真实 Cookie、CSRF、账号 ID、手机号及会话票据通过私有文件提供，不粘贴到公开文档。取得证据后再实现独立 `run.py`、单次 intent 和提交后只读恢复；不是给旧脚本补一个 Cookie 就启用。

```sh
python3 -m unittest discover -s tests -p 'test_yanxuan.py' -v
```

本目录为根据官方可观察请求独立编写的适配代码，没有复制或执行官方前端 bundle 或历史第三方脚本；不对这些外部资源主张开源许可。
