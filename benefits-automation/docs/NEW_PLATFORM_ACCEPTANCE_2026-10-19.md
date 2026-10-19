# 新增平台配置与真实验收

## 当前范围

用户已要求从完成的 fork 继续配置和真实验收，并要求操作全部记录、仅上报异常。平台源码与记录修复已合入聚合 main，正式运行继续使用 `/home/yuwk/code/benefits-automation`；既有生产账号、旧任务、暂停状态和代理保持原有归属，未提交另一聊天的 Epic 计划修改。

初始集成检查：Python 新平台 133 项（2 项需要雨云依赖环境），Node 80 项，既有通知回归 32 项。真实联调修复后，受影响检查重新通过：GLaDOS 43 项、WorkBuddy 42 项、雨云 40 项（固定依赖及外部 provider 环境）；Node 的 ACL/影视飓风/Olé/WeTalk 合计 72 项。执行记录补齐后，作业/日报集成 6 项、既有通知回归 32 项通过。Olé `--execute --status` 不查询门店、不创建签到 intent、不提交签到。测试与下面的真实账号结果分别记录。

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
| GLaDOS | 实际 UA 认证并从官方记录确认今日已签到，未额外提交 | `d6473a17-bc49-48ae-a2ab-75754f902ffd`，余额 10、delta 0 |
| 影视飓风 | `4019fa56-316c-4d15-a223-2d3e0ab30610`，0→10 | `4de249a0-80c2-4656-a2d6-6ab80cb72456` |
| Olé | `995b5518-cbaf-413d-9422-07ac54b4c603`，GET 确认已签到 | `31d6bc7c-ae43-4d03-8efb-15f1f4c3d458`，already_complete |
| 雨云 | `5d7c519c-b136-46e4-8c4c-3ed1919c9360`，200→700 | `1ccab35c-6003-46cb-b2f2-0066d97b7e0f` |
| WorkBuddy 国内版 | `b32e1a63-399b-44fc-8d0d-46a4d24678c0`，1000→1100 | `96041b01-ad2b-437e-bc5e-1bc52d75634d`，1100 |
| WorkBuddy 国际版 | `e0e3ef5e-1d38-4cbb-93d9-d184a350dace`，单次模型请求成功 | `375be131-4322-4a2b-8ce0-c58e332572f6`，activity complete、reward unknown |

最后一列是 17:52 的正式 Hermes 调度复核：六个作业均经过 execute/save/mark 链路，持久 execution ledger 为 completed，本地输出各 1 份，调度状态 ok；对应历史 JSON 与当前 delivery 逐项相同。执行身份 UID 988:GID 984，使用原共享 runtime 和公共浏览器锁。两个 WorkBuddy 作业输出到独立 delivery 文件，实际业务 platform 均为 workbuddy，没有覆盖旧任务。调度成功不代表国际奖励已到账。

## 运行位置与配置

- 共享运行目录：`/home/hermes/.hermes/profiles/lingjun/benefits-runtime`，真实浏览器继续使用其中的全局锁。
- 私有账号配置：该目录的 `credentials/`；新文件以实际运行身份 Hermes（988:984）读取。既有 ACL 服务持续保留 Hermes/本机管理身份读写，部分文件显示 0660；Node 平台核对当前 owner/group、拒绝 other/执行权限，兼容该运行组。WorkBuddy 的实际 0600 会话位于 `/home/hermes/.config/benefits-automation/credentials/`，原约定路径通过链接引用。CookieCloud 复用既有配置，不复制全站凭据，不停止或修改 ACL 服务。
- YYB 正式入口：`automation/compose.yaml` 的 `yyb`，容器 `benefits-yyb`。仅绑定 `127.0.0.1:33082`，复用 `favsync_default`，SQLite/账号数据在 `/vol2/1000/Docker/benefits-yyb/data`；密码和协议令牌位于 automation 的私有 env 文件，不在此文档保存。
- 本次 Compose 与启动登记的备份：`/vol2/1000/Docker/backups/benefits-yyb/20261019-165650`。开机检查已识别新服务，没有计划内停机；仍有既存 `tailscale` 缺失及 `ai-resource-center`、`personal-crm` 未列入原启动计划的差异，本次不修改它们。
- 六个已验收作业已接入原生产配置：每日 08:27 GLaDOS、08:29 影视飓风、08:31 Olé、08:33 雨云、08:35 WorkBuddy 国内、08:37 国际，首个日常触发为 2026-10-20（Asia/Shanghai）。均为 no_agent/local，只留本地执行记录；沿用原 12:00 异常日报、任务身份和通知路由，没有成功通知。WeTalk/严选未启用。
- 每次尝试复用既有 `runs/<run_id>/result.json` 并更新 `delivery/<task_id>.json`；启动失败、无效子结果和锁忙同样留逐次历史。实测新平台仅国际奖励未知进入异常预览，其他五个成功作业无通知内容；预览不发送额外通知。
- 本轮配置/jobs 备份与六作业执行关联证据位于 `cron/migration-backups/20261019-175059-benefits-platforms/`；选择性部署入口备份为 `cron/migration-backups/20261019-175059/`。84 个既有作业的身份、日程、投递和暂停字段逐项保持一致，7 个既有 benefits 配置不变（含阿里云停用）。
- 原独立验收配置仅保留作初始联调对照，不是生产入口；正式脚本从 `/home/yuwk/cron` 调用主线业务源码，不创建新的 Hermes profile 或常驻进程。
