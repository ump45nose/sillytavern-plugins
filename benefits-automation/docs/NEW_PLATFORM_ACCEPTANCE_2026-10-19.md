# 新增平台配置与真实验收

## 当前范围

用户已要求从完成的 fork 继续配置和真实验收。源码统一在独立集成分支 `codex/benefits-checkins-integration-20261019`，不覆盖主工作树仍在更新的 Epic 修复计划；现有生产账号、旧任务、暂停状态和代理保持原有归属。

初始集成检查：Python 新平台 133 项（2 项需要雨云依赖环境），Node 80 项，既有通知回归 32 项。真实联调修复后，受影响检查重新通过：GLaDOS 43 项、WorkBuddy 42 项、雨云 40 项（固定依赖及外部 provider 环境）；Node 的 ACL/影视飓风/Olé/WeTalk 合计 72 项，新作业与日报集成 4 项。Olé `--execute --status` 不查询门店、不创建签到 intent、不提交签到。测试与下面的真实账号结果分别记录。

## 实测与待完成

| 平台/依赖 | 当前实测 | 尚未完成 |
| --- | --- | --- |
| YYB | 固定 0.2.33 镜像正式部署；健康、管理登录和协议鉴权通过，公开注册关闭；微信扫码持久保存；重启后两个目标 AppID 均重新取码成功，两商家已登录 | 自然过期后的长期会话续期 |
| GLaDOS | 从实际 Mac Chrome 版本页取得 UA 后认证通过；官方确认今日已签到，余额 10、本日奖励 10、剩余 14 天；本次余额变动 0；Hermes 包装复核通过 | 本轮走已签到路径，没有新增签到 POST；未来未签到路径与自然过期续期仍需持续观察 |
| 影视飓风 | 真实登录、签到回执与积分读回通过，0→10；重复执行保持 10，未重复提交 | 自然过期续登；仍无独立的当日签到状态接口，模糊提交继续保留 pending |
| Olé | 真实会员登录；空门店签到成功，官方 GET 状态 N→Y；积分保持 0，重复入口确认已签到 | 自然过期续登；没有已到账积分增量 |
| 雨云 | 真实签到 200→700、+500；官方身份和任务状态独立读回一致；重复执行 700→700；sandbox 实测通过 | 本轮没有单独记录真实验证码挑战，不能声明真实识别通过率 |
| WorkBuddy 国内版 | 独立 NAS 会话、令牌刷新与身份核对成功；签到奖励 100，余额 1000→1100，重复运行不重发 | 自然过期后的续期 |
| WorkBuddy 国际版 | 独立 NAS 会话、令牌刷新成功；当天唯一一次 hy3 / `only print:1` 成功，重复运行不再发送；余额 350 | 活跃奖励到账未知，仍报告 reward=unknown |
| 网易严选 | 使用 CookieCloud 的当前会话实跑只读入口，返回 authentication_invalid，run `2d03edf1-e0a2-4293-b975-abf52561e2cb` | 当前可用登录态，以及当前 App 签到/独立读回接口证据；没有启用签到任务 |
| WeTalk | 最新 CookieCloud 仅有两个 Cookie、没有 localStorage；带/不带 Cookie 的余额请求均返回 100004，缺少客户端参数；没有提交签到 | 从已登录 App 捕获一条成功的 GET `/app/queryBalanceAndBonus` 的全部参数及必要头；详见平台 README，之后再验收 |

HTTP 403 不能单独证明 GLaDOS Cookie 失效。WorkBuddy 国际模型响应也不能证明活跃奖励到账。待身份授权或缺少接口证据的项目不被标记为验收通过。Olé 初始适配器把门店设为必填，联调核对固定参考发现其允许空值；已删除这一限制并真实验收，不需要用户门店或位置，也没有伪造作者坐标。

真实凭据处理不打印 Cookie、token、UID、邮箱或原始响应。最新 Mac 同步时间为 `2026-10-19T09:10:58.009Z`；CookieCloud 不包含浏览器 UA，不能将同步成功等同于所有平台凭据齐全。

## 真实执行回执

| 作业 | 首次有效操作 | 重复运行或集成包装复核 |
| --- | --- | --- |
| GLaDOS | 实际 UA 认证并从官方记录确认今日已签到，未额外提交 | `ab61c0c4-4a38-4a80-a92c-42eeadf41647`，余额 10、delta 0 |
| 影视飓风 | `4019fa56-316c-4d15-a223-2d3e0ab30610`，0→10 | `1b5dd8cf-ad0f-4901-81ea-ae7e8992a5bd` |
| Olé | `995b5518-cbaf-413d-9422-07ac54b4c603`，GET 确认已签到 | `da1a9246-0aed-4f13-b33d-bd29bba4635c`，already_complete |
| 雨云 | `5d7c519c-b136-46e4-8c4c-3ed1919c9360`，200→700 | `cf6eac21-050e-49b4-b059-7f3e523b46a7` |
| WorkBuddy 国内版 | `b32e1a63-399b-44fc-8d0d-46a4d24678c0`，1000→1100 | `735bbeb1-6399-4186-ae4e-8e3721b20075`，1100 |
| WorkBuddy 国际版 | `e0e3ef5e-1d38-4cbb-93d9-d184a350dace`，单次模型请求成功 | `6a97d6fe-1f67-4592-ae50-9b7542d0a98d`，activity complete、reward unknown |

上述包装复核通过集成分支的实际 `benefits_native_runner.py`，使用与 Hermes 一致的 UID 988:GID 984、原共享 runtime 和公共浏览器锁。两个 WorkBuddy 作业输出到独立 delivery 文件，实际业务 platform 均为 workbuddy，没有覆盖旧任务。

## 运行位置与配置

- 共享运行目录：`/home/hermes/.hermes/profiles/lingjun/benefits-runtime`，真实浏览器继续使用其中的全局锁。
- 私有账号配置：该目录的 `credentials/`；新文件以实际运行身份 Hermes（988:984）读取。既有 ACL 服务持续保留 Hermes/本机管理身份读写，部分文件显示 0660；Node 平台核对当前 owner/group、拒绝 other/执行权限，兼容该运行组。WorkBuddy 的实际 0600 会话位于 `/home/hermes/.config/benefits-automation/credentials/`，原约定路径通过链接引用。CookieCloud 复用既有配置，不复制全站凭据，不停止或修改 ACL 服务。
- YYB 正式入口：`automation/compose.yaml` 的 `yyb`，容器 `benefits-yyb`。仅绑定 `127.0.0.1:33082`，复用 `favsync_default`，SQLite/账号数据在 `/vol2/1000/Docker/benefits-yyb/data`；密码和协议令牌位于 automation 的私有 env 文件，不在此文档保存。
- 本次 Compose 与启动登记的备份：`/vol2/1000/Docker/backups/benefits-yyb/20261019-165650`。开机检查已识别新服务，没有计划内停机；仍有既存 `tailscale` 缺失及 `ai-resource-center`、`personal-crm` 未列入原启动计划的差异，本次不修改它们。
- 新增平台的 Hermes 包装与 manifest 在源码完成，未验收的平台不启用无人值守生产调度。原生产配置仍使用主线源码，新平台验收显式调用独立集成工作区。独立验收配置位于共享 runtime 的 `acceptance/benefits-deployment.json`，只含新增作业，以 `HERMES_HOME=<runtime>/acceptance` 调用集成分支的 native runner；运行目录继续共用原锁与各自账号分区，没有创建新的 Hermes profile 或常驻进程。
- 生产主工作树当前仍有另一聊天正在修改的 Epic 文件和计划。按照项目约定不覆盖、不提交这些变更、不在主树未干净时合并；新定时尚未启用。集成分支保存可复核提交与私有配置，后续主线干净后合并并仅启用验收过的作业。
