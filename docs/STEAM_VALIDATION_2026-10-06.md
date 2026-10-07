# Steam 适配器开发验证（2026-10-06）

## 源码与变更边界

- 上游 main：`467ab85aef4f99e0e567e1f7c7c80fc01bcf66f0`
- HTTPS clone 缺少认证，未绕过；通过已授权 GitHub connector 按固定 SHA 读取并校验 Git blob hash
- 本地 snapshot 基线：`313ae4f4ed8bb0c8f0ca9d55e8f2969cb7f845d3`；分支 `steam-asf-adapter`。这不是上游完整 Git 历史；历史归档目录 docs/archive 未物化，151 个运行/测试/依赖/说明基线文件精确匹配
- 仅新增 platforms/steam、Steam tests、本说明，并在根 README 加入口。未改 common 或其他六个平台代码
- 没有 push、PR、部署、cron、真实账号登录或实际领取

## 已通过

`python3 -m unittest discover -s tests -p 'test_steam*.py' -v`：43 项全部通过。

其中本地 HTTP E2E 包括：

- 真实 run.py 启动器、子进程监督、账号锁、自动 PICS 发现、app/package 筛选、官方购买块校验
- 精确 subID 的 POST，Steam 业务结果判定，owned 读回，原子 run/result 与 latest 一致
- 默认离线、执行时 dry-run 不发 POST、无候选正常 no-op
- 提交响应丢失、跨进程状态重读不重复提交、活动消失/过期后恢复历史 pending
- 精确 bot 和 SteamID 验证、401 即停、限流持久冷却、无密码写入结果
- 真实 appinfo 根结构、地区允许/禁止规则、beta/demo/playtest/F2P 冲突、包内容变化
- PICS 队列跨批次推进、full-update/截断覆盖缺口明确报告
- 部分批次不误报 complete、已确认事实不被后续失败抹掉、结果超过100项时有界截断与 omitted_items

另通过 Python compileall 与 git diff --check。

这些测试使用本地 HTTP fixture 和重建的历史官方页面结构，不代表在真实 ASF 或 Steam 账号成功运行。生产源码没有 HTTP fixture 地址切换开关。

## 既有全量回归

- Python 全量：225 个测试方法；1 个 failure、3 个 error，另有 2 个 skipped 子测试
- 独立无新代码基线：182 个测试方法；同名 1 个 failure、3 个 error 和 2 个 skipped 子测试逐项复现
- 差值 43 项是新增 Steam 测试，全部通过
- Node：163 项，154 通过、9 失败、0 跳过；独立基线的9个失败完全一致

Python 原有失败：Epic 三个 fixture/API 不匹配错误（locator.count / wait_for），V2EX 一个旧恢复期望与现实现不一致。跳过的是 containment 中没有安装的 Firefox / Patchright 依赖分支。

Node 原有失败：Laowang 响应体大小测试1项；Rewards activities fixture/API不匹配4项、storage state 旧预期1项、APP/claim能力旧预期2项、snapshot warning 前置fixture不匹配1项。未为此任务改动原平台。

因此不能称“仓库全测通过”；只能称 Steam 测试通过且未引入已观察到的新回归。

## 独立代码复核

复核中发现并修正：app PICS 根名称契约、显式地区/beta冲突、发现队列饥饿、超过50条恢复饥饿、PICS截止时间最终复核、发现失败不应阻断历史恢复、HTTPException脱敏、部分结果完整性、目录fsync以及超过100项结果合并。对应场景已补回归测试。

## 尚需真实环境验收

用户已配置且授权使用的 ASF+FreePackages 会话、正确账户国家、IPC权限。先执行只读发现并检查证据，再另行授权真实领取；不得把模拟领取当成实际入库。

PICS 历史窗口不完整，初次 full-update/断档会保留覆盖不足标记；每次批次有限、队列容量有限。官方页面文案、年龄门槛或结构变化都会 hold。没有声称自动发现覆盖全站所有限免。

具体配置、运行与恢复见 [Steam README](../platforms/steam/README.md)。
