# Personal Info 源码归组迁移

## 范围与决定

- 用户要求将 personal-records 和独立 Plaud 项目统一到 Code/personal-info/ 下；本机 Code 根目录为 /vol1/1000/Code（/home/yuwk/code 指向此处）。
- 聚合路径统一为 personal-info/personal-records 与 personal-info/plaud-archive；两个独立 GitHub 仓库及业务运行保持独立，通过现有 subtree 同步。
- 主工作树有其他任务修改，不做主线合并。继续在当前干净聚合 worktree 修改，在 Code/personal-info 提供两个源码入口，指向此工作区内的新归组路径；将来主线干净时以真实目录替换入口并集成。
- personal-records 以已发布独立仓库 main 为迁移基线，Plaud 以其已发布 main 和干净任务分支 3377d25 为基线；保留独立仓库历史，不混入主树或其他任务的修改。
- 同步项目登记、Hub 本地依赖/构建路径、Plaud systemd 与私有 CLI/MCP source_roots、部署登记。Plaud NAS 源码包装同步新路径，但保持既有作业暂停且不切换旧运行包装。
- 仅移动源码与重建可再生虚拟环境；数据库、音频、MD、RAW、OAuth、凭据、域名、:28443 路由和个人记录镜像/卷保持绑定。

## 验收

- 两个新源码入口可访问且项目登记/导出路径正确；独立仓库提交历史保留。
- 锁定依赖安装和原应用行为测试通过；Hermes 身份能从新目录导入、运行 Plaud CLI。
- Plaud 服务只重启目标进程，健康与真实只读 HTTP 内容一致；personal-records HTTP 和健康检查正常。
- 暂停作业、服务 enabled 状态、数据库业务计数与授权状态不变；执行宿主启动检查并区分既有问题。

## 进度

- [x] 确认源码、仓库、运行身份和实际依赖。
- [x] 迁移聚合路径、同步源码引用；独立仓库待推送本次文档。
- [x] 备份受影响私有配置，切换新启动路径并验证。
- [ ] 记录最终路径、检查点与剩余集成边界。

## 实测结果

- 两个应用均以原锁文件重建 Python 3.12 环境，基础安装、wheel 构建通过，测试为 Records 19 + Plaud 22 项。Hub 新本地路径的 lock 检查和同步通过。
- 已更新两个 GitHub 来源登记、MCP 应用目录及 NAS targets 的两个 source_roots。Code/personal-info/ 的两个入口指向本工作区内同名目录，Hermes 身份访问正常。
- Plaud 只重启本进程，新 WorkingDirectory 生效；两个 /healthz 正常，6 组真实读取结果逐字节一致，两条公网 :28443 TLS 鉴权读取通过。15 份 MD 和 33 条音频未变化，凭据未变化，Records 原镜像未重启。
- 私有备份与候选比较记录：/vol1/1000/personal-data-hub/source-backups/20261019-personal-info-layout/{before.json,journal.json,after.json}。
- 主树原有 tracked diff 摘要及 Plaud 原工作区状态均未变化。主线合并仍以主树干净和归属检查为前提；原 Plaud 定时作业不恢复。
