# Deskflow Windows 服务端一键恢复脚本
# 用法: powershell -ExecutionPolicy Bypass -File setup-windows.ps1
# 幂等，可重复执行。需与 Deskflow.conf 同目录运行。

$ErrorActionPreference = 'Stop'

$confSrc = Join-Path $PSScriptRoot 'Deskflow.conf'
$confDir = Join-Path $env:APPDATA 'Deskflow'
$gui = 'C:\Program Files\Deskflow\deskflow.exe'

if (-not (Test-Path $gui)) { throw "Deskflow not installed at $gui" }
if (-not (Test-Path $confSrc)) { throw "Deskflow.conf not found next to this script" }

# 1. 停止 GUI（核心由守护进程管理，随 GUI 一并重启）
Get-Process deskflow -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

# 2. 拷贝配置
New-Item -ItemType Directory -Force -Path $confDir | Out-Null
Copy-Item $confSrc (Join-Path $confDir 'Deskflow.conf') -Force
Write-Output "config -> $confDir\Deskflow.conf"

# 3. 登录自启（Run 键）
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
New-ItemProperty -Path $runKey -Name 'Deskflow' -Value "`"$gui`"" -PropertyType String -Force | Out-Null
Write-Output "autostart -> HKCU Run\Deskflow = $gui"

# 4. 重启 GUI（autoHide=true 会直接隐藏到托盘，由守护进程拉起提权核心）
Start-Process $gui
Start-Sleep -Seconds 3
Get-Process deskflow -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output ("running: {0} (pid {1}, window '{2}')" -f $_.ProcessName, $_.Id, $_.MainWindowTitle)
}
Write-Output 'done. Mac client may need a manual restart of Deskflow on the Mac to reconnect.'
