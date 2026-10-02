# SMZDM 单账号适配器

公开入口为 `run.py`。没有 `--execute` 时不访问网络；实际签到/领奖需要预先授权及独立配置的 `SMZDM_COOKIE`、可选 `SMZDM_SK`、`SMZDM_USER_AGENT_APP`。不在源码、结果或动作记录中保存凭据。

## 签到与奖励恢复

- 保留固定来源的签名与接口：`/checkin` 是签到写操作；`/checkin/all_reward`、`/checkin/show_view_v2` 是奖励查询，虽然 HTTP 方法为 POST；`/checkin/extra_reward` 是额外奖励写操作
- “已经签到”与新签到成功都会继续查询奖励，不再提前返回。签到、普通奖励查询和额外奖励分别报告；奖励未知不会导致重新签到
- `BENEFITS_STATE_DIR/http-actions.json` 保存有界的账号/日期/动作状态。写操作前原子保存并同步 intent；重启后已确认的签到或额外奖励不重发，不明确的写操作也不重发
- 兼容导入运行器提供的旧 `last-confirmed.json`，但必须完整校验 schema、平台、账号和业务日期，分别合并已有明确回执的签到和额外奖励事实，绝不由签到推断额外奖励完成；奖励查询仍继续
- 原始接口实现没有提供可用的签到状态读回字段或额外领奖回执。查询成功不能证明不明确的签到成功，领奖入口消失也不能证明到账。因此未知签到/领奖保持 unknown，等待可信核验；不猜测新字段或通过重复写请求探测状态
- 换日可执行新的每日签到；未核实的连续签到额外奖励 intent 保留，避免把跨日仍未明确的同一奖励再次领取
- HTTP 响应流最多 1 MiB，每次请求 30 秒；整个任务还受运行器总超时及账号互斥锁约束。损坏动作记录拒绝写操作

离线测试：`node --test tests/adapters.test.cjs tests/smzdm-recovery.test.cjs`。新增测试通过真实 `main()` 绑定和不同本地子进程验证状态恢复，HTTP 全为 fake，不使用真实 Cookie 或站点。

这些检查不证明当前线上 API 兼容或积分实际到账。
