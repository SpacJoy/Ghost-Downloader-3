<#
注意：本文件必须保存为「UTF-8 with BOM」。Windows PowerShell 5.1 读不带 BOM 的 UTF-8
会按 ANSI 解析，中文字符串截断后连花括号都会报语法错。用编辑器改完记得确认 BOM 还在。

.SYNOPSIS
    启动源码版 Ghost Downloader 做测试，带菜单选择启动方式。

.DESCRIPTION
    程序用 QSharedMemory 做单实例锁，抢不到锁的新实例会把参数转给老实例然后自己退出，
    表现就是"改了代码重启却没变化"。安装版 exe 占同一把锁，所以启动前一并清掉。

.PARAMETER Mode
    跳过菜单直接执行：bg（后台）、fg（前台）、log（启动并跟随日志）、list（只看实例）、kill（只杀）。

.EXAMPLE
    .\scripts\run.ps1
    .\scripts\run.ps1 -Mode log
#>
param(
    [ValidateSet("bg", "fg", "log", "list", "kill")]
    [string]$Mode
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Entry = Join-Path $Root "Ghost-Downloader-3.py"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$LogFile = Join-Path $env:LOCALAPPDATA "GhostDownloader\GhostDownloader.log"
$EntryName = (Split-Path -Leaf $Entry).ToLower()

function Get-Instances {
    # 源码版跑在 python/pythonw 上，安装版是 Ghost-Downloader-3.exe，三类都算
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='Ghost-Downloader-3.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($EntryName) } |
        Select-Object ProcessId, CommandLine
}

function Show-Instances {
    $items = @(Get-Instances)
    if ($items.Count -eq 0) {
        Write-Host "没有正在运行的实例。" -ForegroundColor DarkGray
        return
    }
    foreach ($item in $items) {
        $command = $item.CommandLine
        if ($command.Length -gt 110) { $command = $command.Substring(0, 107) + "..." }
        Write-Host ("{0,8}  {1}" -f $item.ProcessId, $command)
    }
}

function Stop-Instances {
    $items = @(Get-Instances)
    if ($items.Count -eq 0) {
        Write-Host "没有正在运行的实例。" -ForegroundColor DarkGray
        return $true
    }
    foreach ($item in $items) {
        $command = $item.CommandLine
        if ($command.Length -gt 90) { $command = $command.Substring(0, 87) + "..." }
        Write-Host "结束进程 $($item.ProcessId): $command" -ForegroundColor DarkYellow
        # /T 连子进程一起杀：pythonw 只是启动器，真正跑界面的是它拉起的 python 子进程。
        # 父进程被杀后子进程也一起没了，后面的 taskkill 会报 "not found"，
        # 而 $ErrorActionPreference = Stop 会把它当致命错误，所以这段单独放宽。
        $previous = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & taskkill /PID $item.ProcessId /T /F 2>&1 | Out-Null
        $ErrorActionPreference = $previous
    }
    Start-Sleep -Milliseconds 1500
    $left = @(Get-Instances)
    if ($left.Count -gt 0) {
        Write-Host "还有 $($left.Count) 个进程没退掉，可能要手动处理。" -ForegroundColor Red
        return $false
    }
    Write-Host "旧实例已全部退出。" -ForegroundColor Green
    return $true
}

function Start-Background {
    if (-not (Test-Path $Pythonw)) {
        Write-Host "找不到 $Pythonw，先确认虚拟环境在不在。" -ForegroundColor Red
        return
    }
    $quotedEntry = '"' + $Entry + '"'
    $process = Start-Process -FilePath $Pythonw -ArgumentList $quotedEntry -WorkingDirectory $Root -PassThru
    Start-Sleep -Milliseconds 1200
    if ($process.HasExited) {
        Write-Host "启动后立刻退出了（退出码 $($process.ExitCode)），大概率是单实例锁没抢到，或者启动就报错。" -ForegroundColor Red
        Write-Host "看日志：$LogFile" -ForegroundColor DarkGray
        return
    }
    Write-Host "已启动，PID $($process.Id)" -ForegroundColor Green
    Write-Host "日志：$LogFile" -ForegroundColor DarkGray
}

function Start-Foreground {
    if (-not (Test-Path $Python)) {
        Write-Host "找不到 $Python，先确认虚拟环境在不在。" -ForegroundColor Red
        return
    }
    Write-Host "前台运行，Ctrl+C 结束。" -ForegroundColor DarkGray
    & $Python $Entry
}

function Watch-Log {
    if (-not (Test-Path $LogFile)) {
        Write-Host "日志还不存在：$LogFile" -ForegroundColor Red
        return
    }
    Write-Host "跟随日志 $LogFile（Ctrl+C 退出）" -ForegroundColor DarkGray
    Get-Content $LogFile -Wait -Tail 20
}

function Invoke-Mode {
    param([string]$Name)
    switch ($Name) {
        "list" { Show-Instances }
        "kill" { [void](Stop-Instances) }
        "bg" {
            if (-not (Stop-Instances)) { return }
            Start-Background
        }
        "fg" {
            if (-not (Stop-Instances)) { return }
            Start-Foreground
        }
        "log" {
            if (-not (Stop-Instances)) { return }
            Start-Background
            Watch-Log
        }
    }
}

if ($Mode) {
    Invoke-Mode -Name $Mode
    exit
}

while ($true) {
    Write-Host ""
    Write-Host "===== Ghost Downloader 启动器 =====" -ForegroundColor Cyan
    Write-Host "  1. 后台启动（自动杀旧实例，终端干净）"
    Write-Host "  2. 前台启动（输出直接打在这里）"
    Write-Host "  3. 启动并跟随日志（测试最顺手）"
    Write-Host "  4. 只看正在运行的实例"
    Write-Host "  5. 只杀旧实例"
    Write-Host "  0. 退出"
    Write-Host ""
    $choice = Read-Host "选一个"

    switch ($choice.Trim()) {
        "1" { Invoke-Mode -Name "bg" }
        "2" { Invoke-Mode -Name "fg" }
        "3" { Invoke-Mode -Name "log" }
        "4" { Invoke-Mode -Name "list" }
        "5" { Invoke-Mode -Name "kill" }
        "0" { return }
        default { Write-Host "没有这一项，重新选。" -ForegroundColor DarkYellow }
    }

    # 前台模式回来后就回到菜单，方便改代码再起
    if ($choice.Trim() -in @("1", "2", "3", "4", "5")) {
        Write-Host ""
        [void](Read-Host "按回车回到菜单")
        # 输出被重定向时没有控制台句柄，Clear-Host 会抛错，出错就只空一行
        try { Clear-Host } catch { Write-Host "" }
    }
}
