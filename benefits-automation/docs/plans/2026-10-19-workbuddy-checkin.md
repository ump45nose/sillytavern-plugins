# WorkBuddy 国内与国际版接入

## 范围与决定

- 在独立分支 `codex/benefits-workbuddy-20261019` 实现平台入口、HTTP 协议适配、官方授权登录与令牌续期、测试和说明；不修改公共运行器、调度仓库或生产配置。
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
- 登录授权只接受对应官方域，轮询有总时间上限；凭据与原始响应不进业务结果或日志。
- 离线测试通过，真实账号验收单独记录，完成必要本地提交但不自动合并。

## 进度

- 已读取中央计划和公共运行器/结果约束。
- 已取得 workbuddy-helper 固定提交 `11808853e53ae195a329182f5655baa1783de64c`，核对登录、续期、国际会话/对话和积分分页协议。
- 已与 ZaiZaiCat 国内状态与签到接口、88lin 客户端登录态字段进行对照。
- 已完成 `run.py --edition cn|intl` / `--status`、国内签到与读回、国际云端会话与单次活跃请求、余额分页、官方授权登录/明文导入、令牌旋转原子保存和按 UID/版本绑定的每日 intent。
- 只用 Python 标准库，Task 总时限 240 秒；没有常驻进程、模型 SDK、生产调度或代理配置变更。
- 新增 35 项离线测试，Python 3.11.2 与生产同版 Python 3.12.13 均通过。现有 `test_runner.py` 的 19 项回归通过。检查涵盖提交后断线/重启、认证续期保存失败、双版隔离、流内错误/截断、积分分页和登录授权边界。
- 来源已核对固定提交和文件 SHA256，MIT 许可保存在平台目录。ZaiZaiCat 固定提交的 `api.py` 通过 Git 对象读取校验与原下载字节一致。
- 实测离线入口不加 `--execute` 返回 `execution_not_requested`；两版缺少凭据均结构化返回 `missing_session`。
- 尚未接触真实账号凭据；官方授权、真实签到/活跃、自然过期后的续期和实际积分发放均未实测，不能声称真实签到成功。

## 交给集成的接口

- 两个作业均使用 `platform=workbuddy`，arguments 分别为 `--edition cn` 和 `--edition intl`，账号代号须不同。平台白名单环境仅 `WORKBUDDY_CONFIG` 与可选 `WORKBUDDY_PROXY`。
- 结果仍为 schema v1；新增平台业务项 `balance`（积分查询）以及国际版 `activity`（活跃请求）。日报可增加对应中文名称。
- 国际版收到完整模型响应后，`activity=complete`、`reward=unknown`、`reason=activity_sent_reward_unconfirmed`，公共运行器退出 3；现有积分接口不能提供与某次请求关联的奖励流水，不能把余额差直接标成活跃奖励。
- 登录失效沿用 `authentication_invalid`；不确定提交为 `checkin_submission_unconfirmed` / `activity_submission_unconfirmed`。这些原因应作为待处理事实保留，不应通过调度重复写请求来消除。
- 工作区与分支：`/home/yuwk/code/.worktree/benefits-workbuddy-20261019` / `codex/benefits-workbuddy-20261019`。本任务只提交平台目录、专属测试及本计划，公共运行器和调度接入留给集成。
