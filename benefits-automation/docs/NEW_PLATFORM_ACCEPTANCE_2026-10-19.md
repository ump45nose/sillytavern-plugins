# 新增平台配置与真实验收

## 当前范围

用户已要求从完成的 fork 继续配置和真实验收。源码统一在独立集成分支 `codex/benefits-checkins-integration-20261019`，不覆盖主工作树仍在更新的 Epic 修复计划；现有生产账号、旧任务、暂停状态和代理保持原有归属。

集成检查已通过：Python 新平台 133 项（2 项需要雨云依赖环境），Node 80 项；新增作业隔离、账号核验和共用服务故障合并 3 项，既有通知回归 32 项。为受控验收补充 Olé 的 `--execute --status`，只读模式不查询门店、不创建签到 intent、不提交签到。实际新增计数以本轮最终记录为准。

## 实测与待完成

| 平台/依赖 | 当前实测 | 尚未完成 |
| --- | --- | --- |
| YYB | 固定 0.2.33 镜像正式部署；健康、管理登录和协议鉴权通过，公开注册关闭 | 用户微信扫码、两个目标 AppID 取码、商家登录与续期 |
| GLaDOS | CookieCloud 有完整会话 Cookie；诚实 urllib 客户端只读 status 请求收到 HTTP 403 | 确认 403 来源、匹配的浏览器 UA、真实签到与积分读回 |
| 影视飓风 | 执行器与共用取码客户端已集成，离线验证通过 | 依赖 YYB 扫码，登录/签到/读回实测 |
| Olé | 执行器与共用取码客户端已集成，补充只读入口 | 依赖 YYB 扫码、真实会员/门店、签到/积分读回 |
| 雨云 | CookieCloud 有现有网页会话，平台任务正配置会话复用和固定浏览器依赖 | 登录、真实签到/验证码、读回及重复运行 |
| WorkBuddy 双版 | CookieCloud 有网页会话，两个官方授权入口可达 | NAS 独立授权、余额/活动查询、国内签到及国际一次活跃请求 |
| 网易严选 | 使用 CookieCloud 的当前会话实跑只读入口，返回 authentication_invalid，run `2d03edf1-e0a2-4293-b975-abf52561e2cb` | 当前可用登录态，以及当前 App 签到/独立读回接口证据；没有启用签到任务 |
| WeTalk | 执行器和签名测试已集成 | 有效客户端请求参数/认证头，真实签到与余额读回 |

HTTP 403 不能单独证明 GLaDOS Cookie 失效。WorkBuddy 国际模型响应也不能证明活跃奖励到账。待身份授权或缺少接口证据的项目不被标记为验收通过。

## 运行位置与配置

- 共享运行目录：`/home/hermes/.hermes/profiles/lingjun/benefits-runtime`，真实浏览器继续使用其中的全局锁。
- 私有账号配置：该目录的 `credentials/`；新文件以实际运行身份 Hermes（988:984）读取，0600。CookieCloud 复用既有 `cookiecloud.json`，不复制全站凭据。
- YYB 正式入口：`automation/compose.yaml` 的 `yyb`，容器 `benefits-yyb`。仅绑定 `127.0.0.1:33082`，复用 `favsync_default`，SQLite/账号数据在 `/vol2/1000/Docker/benefits-yyb/data`；密码和协议令牌位于 automation 的私有 env 文件，不在此文档保存。
- 本次 Compose 与启动登记的备份：`/vol2/1000/Docker/backups/benefits-yyb/20261019-165650`。开机检查已识别新服务，没有计划内停机；仍有既存 `tailscale` 缺失及 `ai-resource-center`、`personal-crm` 未列入原启动计划的差异，本次不修改它们。
- 新增平台的 Hermes 包装与 manifest 在源码完成，未验收的平台不启用无人值守生产调度。原生产配置仍使用主线源码，新平台验收显式调用独立集成工作区。独立验收配置位于共享 runtime 的 `acceptance/benefits-deployment.json`，只含新增作业，以 `HERMES_HOME=<runtime>/acceptance` 调用集成分支的 native runner；运行目录继续共用原锁与各自账号分区，没有创建新的 Hermes profile 或常驻进程。
