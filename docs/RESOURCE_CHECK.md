# 2026-10-01 云端复测记录

## 测量范围

Linux x86_64、Python 3.12.14、Node 24.19.0。每个平台运行一次默认入口（不带 `--execute`），使用新临时 runtime-root，无凭据、网络业务或浏览器启动。独立 Python 观察进程以 `resource.getrusage(RUSAGE_CHILDREN).ru_maxrss` 读取已退出子进程峰值 RSS，`time.monotonic` 测墙钟时间。Linux 的该字段单位是 KiB。

| 入口 | 峰值 RSS KiB | 秒 | 结果 |
|---|---:|---:|---|
| SMZDM | 13440 | 0.048 | execution_not_requested，退出 1 |
| V2EX | 13184 | 0.041 | execution_not_requested，退出 1 |
| Aliyun | 13184 | 0.045 | execution_not_requested，退出 1 |
| Laowang | 13184 | 0.048 | execution_not_requested，退出 1 |
| Rewards | 13184 | 0.046 | execution_not_requested，退出 1 |
| Epic | 13184 | 0.040 | execution_not_requested，退出 1 |

这只说明启动器空跑开销约 13 MiB、数十毫秒。不是业务任务、浏览器进程树或 NAS 实测，不代表比青龙节省了多少内存。浏览器任务串行和按需启动的设计仍需真实任务峰值 PSS/RSS、退出残留及旧方案同条件对照验证。

## 新环境浏览器检查

重新通过各平台 lockfile 执行 npm ci，关闭安装脚本；随后由官方浏览器安装器安装固定版本。

- Rewards：Patchright 1.61.1 依赖安装成功；Chromium 1228 / Chrome for Testing 149.0.7827.55 下载器有限重试后仍得到不可解压内容，浏览器安装失败。因此 Chromium 本地 DOM smoke 未运行
- Laowang：Playwright Firefox 1.63.0 依赖安装成功；官方备用下载端点完成 Firefox 155.0/revision 1543 和 FFmpeg 1011 下载。tests/browser_smoke.cjs 运行后，在页面创建之前报 `Could not find profile folder`，退出 1。测试创建了临时 profile；尚未确定更深层原因
- 没有关闭浏览器 sandbox、改系统安全设置、变更代理或访问真实账号；以上不是线上自动签到验收

## 环境恢复与验证边界

云端环境重建后，使用已授权 GitHub 连接恢复全部 112 个文件 blob 与 Git 树，核验其与已发布检查点一致，并恢复精确提交对象。随后重建中断前尚未提交的 Epic/Rewards 改动。已重新运行的单元测试及检查记录在 STATUS；旧环境的外部上游构建目录和登录配置未随环境保留，不能声称它们已恢复或重新验收。
