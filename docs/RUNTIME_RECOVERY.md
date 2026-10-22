# 一次性运行、业务恢复与浏览器回收

## 业务结果

launcher 仍以同账号锁串行启动适配器，但不再因为 `checkin=complete` 跳过整个平台。`last-confirmed.json` 是已确认事实的记录，通过 `BENEFITS_LAST_CONFIRMED_PATH` 提供给适配器；适配器只在核验账号、日期与具体动作后采用，不把历史记录当整个平台完成。

具体签到/领奖的去重、只读确认和不确定提交恢复属于平台适配器。`--allow-repeat` 仅保留命令行兼容性，不绕过动作日志或允许盲目重发。超时、取消、退出非零不会擦除已经通过协议验证的 `business` 项；执行状态仍明确为 timeout/failed。缺失或无效的结果不能证明完成。

即使运行目录无法创建或结果文件无法写入，也尽力在 stdout 输出一个失败 JSON。文件保存失败不能承诺磁盘记录存在。

## 浏览器进程

Playwright/Patchright 在 Linux 中会把浏览器放到独立进程组。仅 `killpg(adapter)` 无法回收这类进程。

浏览器任务在全局锁内使用当前 launcher 进程的 Linux child-subreaper 标志。它只改变该进程的后代回收行为，不创建系统服务，不改变系统/网络/安全配置。进入前要求当前进程没有其他子进程或 Python 工作线程，且 `/proc`、`prctl`、pidfd 能力可用；不满足就不启动浏览器任务。

adapter 结束或被 deadline 终止后，脱离组的后代由 launcher 收养。回收以 `waitpid` 确认父子关系，以 pidfd 定向发信号并回收；不按进程名或全机搜索结果杀进程。清理等待有界，无法验证全部回收时保留阻塞记录。运行阶段的 TERM→KILL 时限后最多另加两秒回收检查；不能把操作系统不可中断状态描述为一定可杀死。

已退出的子进程先通过 `waitpid` 回收，不要求先取得 pidfd；仍存活的已确认子进程才打开 pidfd 并终止。清理失败记录明确区分父子归属、系统调用错误和清理超时，保留必要 PID/errno，不再只剩一个无法诊断的失败码。

## launcher 被 SIGKILL 后怎么办

浏览器任务启动前，在 `runtime-root/locks/browser-cleanup.json` 写入当前启动周期和 run ID。只有清理确认后才移除。launcher 自身 SIGKILL 无法执行 finally；marker 因此保留。即使浏览器 flock 随其他进程退出而释放，下次浏览器任务仍拒绝运行，返回 `browser_cleanup_unverified`，避免新旧浏览器重叠。HTTP 任务不受该全局浏览器标记影响。

只读检查命令（不清理任何进程/文件）：

```sh
python3 -m common.containment --runtime-root /absolute/private/benefits-data
```

- `no_pending_cleanup`：没有待确认记录
- `same_boot_cleanup_requires_operator_verification_or_host_restart`：仍是原主机启动周期；不能仅因 PID 不存在或记录过期就删标记。先检查原 run 的记录并由运维确认残留进程。没有可靠归属证据时，主机重启是可验证恢复边界，不自动重启机器
- `previous_boot_next_run_can_recover`：主机确实经历了另一次启动，旧进程已不存在；下一次正常任务可自动替换旧标记继续运行
- 无效/无法读取的标记也返回 `browser_cleanup_unverified`，不得凭猜测删除

本实现不提供“忽略清理”的开关。若部署需要 launcher SIGKILL 后仍自动立即收敛，需另行授权并验证原生 systemd/cgroup 的每任务控制组；这里未部署或修改这些设施。

## 已验证范围

离线测试使用已锁定的 Firefox/Patchright 启动器，启动本地 fake-browser 可执行文件，再让 Node adapter 的事件循环停止响应。deadline 强杀 adapter 后验证 fake-browser 被回收、标记清除、锁可重新获得。另测 launcher SIGKILL 保留标记并拒绝下一次任务、现存无关子进程不被杀、旧启动周期恢复、能力不足拒绝启动。

这不等于真实 Firefox/Chromium 页面、账号、NAS 峰值内存或线上操作验收。
