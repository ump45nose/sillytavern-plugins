# Grok Bot macOS 副号启动器

使用同一份 `/Applications/Grok Bot.app`，为副号指定独立的数据目录，再通过 Automator 制作可放进 Dock 的启动入口。

本目录包含 [launch-account2.zsh](launch-account2.zsh) 和使用说明，不包含已打包的 `.app`、账号凭据、登录状态或用户数据。

## 原理与前提

- Grok Bot 已安装到 `/Applications/Grok Bot.app`，能够正常启动。
- `--user-data-dir` 指向 `$HOME/Library/Application Support/Grok Bot-Account2`。
- `SAND_DATA_ROOT` 指向上述目录下的 `sand-data`。
- 两个参数应同时保留，每次副号启动都使用相同的目录。`$HOME` 会按当前 Mac 登录用户展开，不需要写死用户名。
- 原版应用仍可用于主号。把原版 Grok Bot 图标直接留在 Dock，不会保存这次启动时的环境变量和命令行参数。

已验证双登录的原始命令：

```zsh
PROFILE="$HOME/Library/Application Support/Grok Bot-Account2"
SAND_DATA_ROOT="$PROFILE/sand-data" "/Applications/Grok Bot.app/Contents/MacOS/Grok Bot" --user-data-dir="$PROFILE"
```

启动脚本在此基础上检查可执行文件、创建目录，并使用 `nohup` 后台运行。它不修改应用包、签名、隔离属性或自动更新设置。

## 方式一：把脚本粘贴到 Automator

1. 打开 macOS 的“自动操作”（Automator），新建文稿，选择“应用程序”。
2. 搜索并添加“运行 Shell 脚本”操作。
3. 将 Shell 设为 `/bin/zsh`。
4. 删除默认内容，将 [launch-account2.zsh](launch-account2.zsh) 的完整内容粘贴进去。
5. 保存为 `Grok副号.app`，放到容易找到且不会随手移动的位置，例如个人“应用程序”文件夹。
6. 在 Finder 中把 `Grok副号.app` 拖到 Dock 的应用区域。
7. 副号尚未运行时，点击这个启动器，按应用界面完成副号登录。

这种方式把脚本保存在 Automator 应用里，移动或删除本地仓库不会影响它。以后更新仓库脚本时，需要手动同步 Automator 中的内容。

## 方式二：让 Automator 引用本地脚本

如果希望更新仓库后直接使用新脚本，在“运行 Shell 脚本”中填入：

```zsh
/bin/zsh "$HOME/Projects/app-configs/grokbot/macos-account2/launch-account2.zsh"
```

将示例中的 `$HOME/Projects/app-configs` 改为实际的本地仓库路径，保留引号。仍按方式一保存应用并拖入 Dock。仓库和脚本必须一直保留在该路径；显式使用 `/bin/zsh` 调用，无需另外执行 `chmod`。

也可以在终端用同一条命令启动，无需 Automator。

## 日常使用与排查

- 主号用原版 Grok Bot 入口，副号用 `Grok副号.app`。
- 副号已经打开时，切换到已有的运行窗口。不要反复点击启动器；脚本没有重复启动检测，也不负责把已有副号窗口带到前台。
- `Grok副号.app` 是启动入口，启动后会退出；正在运行的 Grok Bot 仍可能显示原应用的名称和图标。
- 若提示找不到可执行文件，先确认安装位置；应用名称或路径变化后，更新脚本的 `BINARY`。
- 后台启动会丢弃标准输出和错误输出。若没有出现窗口，先确认副号未在运行，再在终端运行上面的原始命令查看错误。不要把可能含凭据的完整日志公开上传。
- 脚本返回不代表应用已经启动或登录成功，以实际窗口为准。
- 不要把 `$HOME/Library/Application Support/Grok Bot-Account2`、`sand-data` 或其中的登录数据提交到 Git。

## 验证状态（2026-10-12）

- 用户已确认原始命令可以实现两个账号同时登录。
- `launch-account2.zsh` 已通过 `zsh -n` 语法检查。
- Automator 应用、Dock 点击启动及后台启动行为尚未在 Mac 上实测。
- 仓库保存的是启动脚本和制作步骤；`Grok副号.app` 需要在 Mac 上按步骤创建。
