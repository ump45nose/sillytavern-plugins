# Mac 统一应用验收

2026-10-07 在现有 Mac 完成 0.3.1 build 8 的打包、安装、采集迁移和登录项注册。NAS 服务镜像保持 `local/personal-data-hub:wechat-media-0a7fe87`，本轮未修改后端。

同日图标更新为 build 9：新增蓝色归档盒与资料卡图标，ICNS 含 16–1024 像素尺寸；重新构建、安装和 ZIP 解压后的严格签名验证通过。采集 archive 未变，安装返回 `unchanged=true`，两个后台任务无需重启；登录项仍为 `enabled`，固定助手的真实凭据读取通过。

## 交付

- 已安装：`~/Applications/Personal Data Hub.app`；前版保存在 `Personal Data Hub.previous.app`。
- 本机更新包：`apps/mac-client/dist/Personal Data Hub.zip`，约 53 MiB。解压后严格签名校验通过，组件 manifest 和安装脚本与已安装版本一致。
- `SMAppService.mainApp` 返回 `enabled`；两个原采集 label 均已加载。
- 包含微信 Python 3.12.14、所需 wheel 依赖、采集代码、固定原生读取器、Skysight 脚本及固定凭据助手代码副本。凭据、Signing 私钥、数据库、附件、水位和媒体队列留在仓库外。
- 运行组件解压到 `~/Library/Application Support/PersonalDataHub/Agents/versions/<SHA256>/`；采集命令不再引用 Mac 仓库检出路径。

## 后台权限与迁移

初版候选将 launchd 的微信解释器直接换成包内 Python，终端目录读取成功，但后台返回 `directory_unavailable`。同环境、同原生读取器的临时 launchd 对比确认：原获准解释器及其真实路径可读，复制后的解释器路径不可读。仅恢复原生读取器路径仍失败。

最终实现保留原获准 Python 的真实路径，用标准库启动脚本转交包内 Python；微信业务代码和依赖均从应用组件目录读取。该父子进程链的后台探针读取成功：1 个账号、2,062 个会话目录。电脑活动保留原系统 Python 和 ChatGPT Node 路径，不更换 TCC 责任入口，不增加读取范围。

安装器在停止原任务前验证应用签名、archive 哈希、imports、原生二进制、固定助手，并用临时 launchd 任务验证真实后台目录读取。失败时保持原任务运行；探针停止后删除临时配置和输出。迁移有独占锁，保留原 label、设备身份、私有环境文件、检查点和队列；同版已安装时不重启任务。安装失败恢复原 plist 与原加载状态，回退不完整时明确报错。

最终迁移备份：`~/Library/Application Support/PersonalDataHub/backups/collection-app-20261007-154040`。原始配置、媒体 cutoff 和水位未重置；正文和 Skysight 水位允许后续成功采集继续推进。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| 默认 `.build` 的 Swift 测试 | 8 项通过；release 构建和严格签名校验通过 |
| 合成迁移测试 | 4 项通过，覆盖路径逃逸、迁移/回退、相对状态路径、后台预检失败不停止原任务 |
| Python lint / Git diff | Ruff F 检查与 `git diff --check` 通过 |
| 签名与真实 Keychain | 与原应用指定要求相同；助手字节不变；归档和 Google 凭据禁止弹窗时均可读 |
| 跨版本 Keychain | 不同 CDHash 的同证书候选均可读取；未获准脚本被拒绝且无数据返回 |
| 查看端真实冒烟 | 16 来源、27 类型、71,971 条记录，两 Agent 已加载，附件 SHA-256 校验通过；数量为验收时快照 |
| 微信真实后台 | 新责任链完成同步，`sent=true`、`errors=[]`；本轮无新增文字，Fact 数为 0 |
| 微信正文水位 | 从迁移前 `2026-10-07T07:28:51.518642+00:00` 推进到 `2026-10-07T07:42:52.786797+00:00` |
| Skysight 真实后台 | 同步 1 个片段、1 个摘要，退出码 0；成功时间 `2026-10-07T07:40:52.915Z`；旧片段与摘要身份保留 |
| 媒体队列 | `enabled_since=2026-10-07T05:39:19.677772+00:00` 保持不变，验收时待处理为 0；原 spool 路径保留 |
| 同版重复安装 | 返回 `unchanged=true`，不重启已加载采集任务 |
| 退出查看端 | 两任务仍已加载，微信进程 PID 保持不变；随后重新打开应用 |
| 登录启动 | 状态 `enabled`；未进行实际注销或重启 |

## 边界

这是当前已配置 Mac 的统一安装包，仍保留原获准微信启动解释器、系统 Python、ChatGPT Node 和仓库外私有设备配置。不能删除这些执行器；新 Mac 需要先完成配置与首次数据权限。本机自签名包没有 Developer ID 公证，不作为公开分发安装包。

图片继续归档原始加密 `.dat`，语音保存原 SILK，不生成图片密钥、ASR 或其他处理产物。本轮没有发送新的微信测试消息或媒体，因此新增媒体端到端到达不属于此次打包验收；原媒体功能与样本验证见 [微信采集验收](wechat-faithful-validation.md)。
