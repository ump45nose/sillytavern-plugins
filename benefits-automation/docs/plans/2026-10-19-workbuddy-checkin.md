# WorkBuddy 国内与国际版接入

## 范围与决定

- 在独立分支 `codex/benefits-workbuddy-20261019` 实现平台入口、HTTP 协议适配、官方授权登录与令牌续期、测试和说明；不修改公共运行器、调度仓库或生产调度。
- 复用 `common.runner` / `Task`，入口为 `run.py --edition cn|intl`；每次一个账号，两版使用不同账号代号和仓库外私有凭据。
- 国内版先读真实活动/当日签到状态，仅未签时提交一次，然后读回状态和余额；活动明确关闭为不适用，缺失字段为未知。
- 国际版每日一次 `hy3` + `only print:1`，按现有协议登记云端会话、携带客户端特征与 growthEvent；提交前持久化 intent，不因失败或积分未即时到账重复发起。
- 国际版对话响应和积分观察分别报告。余额差不是已证实的活跃奖励；没有可归因的到账证据时奖励维持未知。
- 用独立官方网页登录建立 NAS 登录态，避免依赖桌面端加密文件或与桌面客户端争用旋转 refresh token。可导入已解密的单账号凭据；不实现桌面解密助手。
- 接口协议参考 MIT 的 workbuddy-helper；只迁移必要协议，不引入看板、常驻调度、DNS fallback 或推送。国内状态字段与路由另与 ZaiZaiCat 公开源码对照，不复制其整包。

## 验收标准

- 无 `--execute` 时不联网，缺少凭据返回结构化原因；双版凭据/状态不能混用。
- 国内覆盖已签、活动关闭、活动字段未知、签到成功、提交超时后读回、重复运行不重签。
- 认证拒绝只在读取路径续期一次；旋转 access/refresh token 原子写回后才继续，持久化失败停止业务写操作。
- 国际请求的固定模型与提示词、会话 ID、growthEvent 与请求头一致；空流、流内错误、截断流不得误报成功，超时/重启不重复发送。
- 余额分页、套餐周期额度与旧格式覆盖真实已知响应；不完整或异常数据不按零汇总。
- 登录授权只接受对应官方域，轮询有总时间上限；CookieCloud 只取版本对应域，网页 SSO 仅跟随同域跳转，只自动选择唯一启用的个人账号，新 bearer 清空 Cookie 后核对身份。凭据与原始响应不进业务结果或日志。
- 凭据实际文件为运行身份所有、0600；运行目录存在宿主强制共享 ACL 时，使用私有目录中的实际文件及原路径链接。登录和任务使用同一实际路径加锁与续期。
- 离线测试通过，真实账号验收单独记录，完成必要本地提交但不自动合并。

## 进度

- 已读取中央计划和公共运行器/结果约束。
- 已取得 workbuddy-helper 固定提交 `11808853e53ae195a329182f5655baa1783de64c`，核对登录、续期、国际会话/对话和积分分页协议。
- 已与 ZaiZaiCat 国内状态与签到接口、88lin 客户端登录态字段进行对照。
- 已完成 `run.py --edition cn|intl` / `--status`、国内签到与读回、国际云端会话与单次活跃请求、余额分页、官方授权登录/明文导入、令牌旋转原子保存和按 UID/版本绑定的每日 intent。
- 日常任务只用 Python 标准库，Task 总时限 240 秒；可选 CookieCloud 首次登录复用已有 cryptography 环境。没有常驻进程、模型 SDK、生产调度或代理配置变更。
- 共 42 项离线测试，在生产同版 Python 3.12.13 通过；覆盖提交后断线/重启、认证续期保存失败、双版隔离、流内错误/截断、积分分页、网页登录身份核验、同域跳转上限及链接凭据锁。初次实现的 35 项另在 Python 3.11.2 通过，现有 `test_runner.py` 的 19 项回归通过。
- 来源已核对固定提交和文件 SHA256，MIT 许可保存在平台目录。ZaiZaiCat 固定提交的 `api.py` 通过 Git 对象读取校验与原下载字节一致。
- 实测离线入口不加 `--execute` 返回 `execution_not_requested`；两版缺少凭据均结构化返回 `missing_session`。
- 已按用户授权完成两版真实会话配置与业务验收，结果见下方；自然过期与国际活跃奖励发放仍未实测。

## 交给集成的接口

- 两个作业均使用 `platform=workbuddy`，arguments 分别为 `--edition cn` 和 `--edition intl`，账号代号须不同。平台白名单环境仅 `WORKBUDDY_CONFIG` 与可选 `WORKBUDDY_PROXY`。
- 结果仍为 schema v1；新增平台业务项 `balance`（积分查询）以及国际版 `activity`（活跃请求）。日报可增加对应中文名称。
- 国际版收到完整模型响应后，`activity=complete`、`reward=unknown`、`reason=activity_sent_reward_unconfirmed`，公共运行器退出 3；现有积分接口不能提供与某次请求关联的奖励流水，不能把余额差直接标成活跃奖励。
- 登录失效沿用 `authentication_invalid`；不确定提交为 `checkin_submission_unconfirmed` / `activity_submission_unconfirmed`。这些原因应作为待处理事实保留，不应通过调度重复写请求来消除。
- 工作区与分支：`/home/yuwk/code/.worktree/benefits-workbuddy-20261019` / `codex/benefits-workbuddy-20261019`。本任务只提交平台目录、专属测试及本计划，公共运行器和调度接入留给集成。

## 2026-10-19 真实账号验收

- 通过现有 CookieCloud 仅读取版本对应网站的 Cookie，官方同域 SSO 恢复登录，唯一个人账号的新网页登录 grant 成功。清除 Cookie 后，官方 `/v2/plugin/login/account` 返回身份与网页账号一致，两版余额接口均成功。未复制桌面 refresh token，未输出 Cookie、令牌、UID 或原始账号响应。
- 两版均主动执行一次官方 refresh，确认 refresh token 已旋转、原子保存后重读成功，新 bearer 身份一致；自然过期后的自动触发尚未等待，认证拒绝后的单次自动续期另有离线测试。
- `hermes-yuwk-access.service` 对 `.hermes` 的 inotify ACL 修复会将凭据变成 0660。保留既有授权服务，将新凭据实际文件保存在 `/home/hermes/.config/benefits-automation/credentials/`（0700 目录），原约定 `benefits-runtime/credentials/workbuddy-{cn,intl}.session.json` 为链接。实际文件持续为 `hermes` 988:984、0600，登录与运行共用解析后的路径和锁。未调整任何既有文件或目录的权限。
- 验收以 Hermes 身份、生产 Python 3.12.13，通过正式平台入口使用原运行目录和两个真实代号；没有增加或启用生产调度。

| 操作 | run_id | 实测结果 |
| --- | --- | --- |
| 国内只读 | `2934f0b6-b763-47d3-bf3d-7bef15620999` | 活动有效、当日未签，余额 1000 |
| 国际只读 | `6ad6083c-6af1-4d64-ba2d-b3ebd1b87449` | 余额 350，未发送模型请求 |
| 国内受控签到 | `b32e1a63-399b-44fc-8d0d-46a4d24678c0` | 签到读回确认，奖励 100，余额 1000→1100，退出 0 |
| 国际单次活跃 | `e0e3ef5e-1d38-4cbb-93d9-d184a350dace` | `hy3` / `only print:1` 完整响应成功；余额 350→350，奖励未知，退出 3 |
| 国内再次运行 | `6d43f154-b59e-4246-87b3-5e253ae5d0ee` | 已签、奖励保留 100、余额 1100；原 intent 字节未变，退出 0 |
| 国际再次运行 | `251eeca9-6d9c-4487-8dfd-287b0a721737` | 活跃请求完成、余额 350、奖励未知；原 intent 字节未变，退出 3 |

再次运行实测证明状态恢复与结果保持；不会再次发送写请求的分支由离线调用计数测试覆盖。没有取得服务端请求流水，未把未变的余额当作请求次数证据。国际奖励未核实，应保留 unknown，不删除当天 intent 或补发。
