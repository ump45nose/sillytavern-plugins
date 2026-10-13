# Deskflow Windows 服务端配置

主机 `yuwk_home`（192.168.31.101）作为服务端，Mac（192.168.31.148，屏幕名 `Mac`）作为客户端从左屏跨入。

## 文件说明

| 文件 | 位置 | 说明 |
|---|---|---|
| `Deskflow.conf` | `%APPDATA%\Deskflow\Deskflow.conf` | GUI 配置 + 服务端布局（真正的配置源，手动恢复用这个） |
| `deskflow-server.conf` | `C:\ProgramData\Deskflow\deskflow-server.conf` | GUI 每次保存时自动生成，核心实际读取；仓库里留作 diff 参考，**不要手动恢复** |
| `setup-windows.ps1` | 任意处 | 一键恢复脚本：停 GUI → 拷贝配置 → 注册自启 → 重启 GUI |

## 本次配置的修改点（1.26.0）

1. **跨屏解锁**：`defaultLockToScreenState=false`。此前的"默认锁定到屏幕"会让鼠标被锁死在 Windows 屏，是跨屏失败的根因。
2. **开机无感自启**（三件套）：
   - `Deskflow` 守护进程服务（自动启动 / LocalSystem，安装时自带）开机拉起提权核心，无 UAC；
   - 注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` → `Deskflow = "C:\Program Files\Deskflow\deskflow.exe"` 实现登录自启 GUI；
   - `autoHide=true` 让 GUI 启动后直接隐藏到托盘，无窗口。
3. **Mac 屏修饰键映射**（仅对 Mac 屏生效，Mac 本机键盘不受影响）：

   | Windows 物理键 | Mac 收到 | 生成行 |
   |---|---|---|
   | Ctrl | ⌘ Command | `ctrl = meta` |
   | Win | ⌃ Control | `meta = ctrl`、`super = ctrl` |
   | Alt | ⌥ Option | 未改 |

   效果：Ctrl+C/V/X/Z/A/S = 复制粘贴那一套；Ctrl+Tab = ⌘Tab 切应用；Ctrl+Q/W = ⌘Q/⌘W；Win+C = ⌃C（终端中断）；Ctrl+Win+Space = ⌃⌘Space（表情面板）。
4. **布局**：`Mac`（左）— `yuwk_home`（中）— `192.168.31.48`（右）。右侧为无设备的幽灵屏（Mac 实际按名字 `Mac` 连接），可在 GUI 网格中删除。

## Mac 侧要求

- Mac 端 Deskflow 设为登录自启，服务器地址 `192.168.31.101:24802`。
- 注意：Windows 服务端重启（改配置/重启 GUI）后，Mac 客户端偶尔不自动重连，需手动重启 Mac 端 Deskflow（已知怪癖，版本 1.26.0）。

## Alt+Tab 热键为什么没做（实测结论）

需求：Windows 键盘按 Alt+Tab 时 Mac 收到 ⌘Tab。**Deskflow 1.26 无法实现**，两条独立证据：

1. 服务端热键通过 Win32 `RegisterHotKey` 注册；在本机实测 `RegisterHotKey(MOD_ALT, VK_TAB)` 返回 **error 1409（ERROR_HOTKEY_REGISTERED）** —— Alt+Tab 被系统保留，任何程序都注册不了，Deskflow 日志会报 `failed to register hotkey` 且热键完全不生效。
2. 源码核实（`src/lib/gui/Hotkey.cpp`、`src/lib/server/Config.cpp`）：热键触发条件只有 `keystroke` / `mousebutton` / `connect` 三种，**没有"仅在某屏激活时生效"的作用域**，因此即便能注册也会全局吞键。

替代：上面第 3 条的修饰键映射已让 **Ctrl+Tab 在 Mac 屏等于 ⌘Tab**（客户端把 Ctrl 掩码翻译为 Meta），Windows 本机的 Ctrl+Tab 行为不变。

注意：网上流传的写法 `keystroke(Alt+Tab) = keystroke(Meta+Tab,Mac)` 有两处错误——动作键写 `Meta` 经 `meta = ctrl` 映射后 Mac 实际收到的是 ⌃Tab（要发 ⌘Tab 应写 `keystroke(Ctrl+Tab,Mac)`）；且触发端如上所述不可行。

## 恢复步骤（新机器）

```powershell
# 以管理员或普通用户运行
powershell -ExecutionPolicy Bypass -File setup-windows.ps1
```

脚本等价于：停止 deskflow GUI → 将 `Deskflow.conf` 拷贝到 `%APPDATA%\Deskflow\` → 写入 HKCU Run 自启键 → 重新启动 GUI。TLS 证书（`C:\ProgramData\Deskflow\tls\`）首次启动会自动生成，Mac 端首次连接需重新信任指纹。
