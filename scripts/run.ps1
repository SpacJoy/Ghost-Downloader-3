<#
注意：本文件必须保存为「UTF-8 with BOM」。Windows PowerShell 5.1 读不带 BOM 的 UTF-8
会按 ANSI 解析，中文字符串截断后连花括号都会报语法错。用编辑器改完记得确认 BOM 还在。

.SYNOPSIS
    启动源码版 Ghost Downloader 做测试，带菜单选择启动方式。

.DESCRIPTION
    程序用 QSharedMemory 做单实例锁，抢不到锁的新实例会把参数转给老实例然后自己退出，
    表现就是"改了代码重启却没变化"。安装版 exe 占同一把锁，所以启动前一并清掉。

.PARAMETER Mode
    跳过菜单直接执行：bg（后台）、fg（前台）、log（启动并跟随日志）、list（只看实例）、kill（只杀）、
    package（Nuitka 打包）。

.PARAMETER Arch
    打包的目标架构：x86_64 或 arm64。Nuitka 不能交叉编译，必须和本机一致，默认本机。

.PARAMETER Version
    打包时写进二进制属性和安装包的版本号，默认取 app/config/constants.py 里的 VERSION。

.PARAMETER Installer
    打包同时出 Inno Setup 安装包，需要本机装了 Inno Setup 6。

.EXAMPLE
    .\scripts\run.ps1
    .\scripts\run.ps1 -Mode log
    .\scripts\run.ps1 -Mode package -Installer
    .\scripts\run.ps1 -Mode package -Version 4.6.1 -Installer
#>
param(
    [ValidateSet("bg", "fg", "log", "list", "kill", "package")]
    [string]$Mode,
    [ValidateSet("x86_64", "arm64")]
    [string]$Arch,
    [string]$Version,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Entry = Join-Path $Root "Ghost-Downloader-3.py"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$LogFile = Join-Path $env:LOCALAPPDATA "GhostDownloader\GhostDownloader.log"
$EntryName = (Split-Path -Leaf $Entry).ToLower()
$Constants = Join-Path $Root "app\config\constants.py"
$Deploy = Join-Path $PSScriptRoot "deploy.py"
$Iss = Join-Path $PSScriptRoot "Ghost-Downloader-3.iss"
$DistDir = Join-Path $Root "dist\Ghost-Downloader-3.dist"

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

function Read-BuildVersion {
    if (-not (Test-Path $Constants)) { return "" }
    $text = Get-Content $Constants -Raw -Encoding UTF8
    $match = [regex]::Match($text, '(?m)^VERSION\s*=\s*"([^"]+)"')
    if (-not $match.Success) { return "" }
    return $match.Groups[1].Value.Split("-")[0]
}

function Get-MachineArch {
    # 32 位 PowerShell 跑在 ARM64 上时 ARCHITECTURE 是 x86，真架构在 ARCHITEW6432
    if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64" -or $env:PROCESSOR_ARCHITEW6432 -eq "ARM64") { return "arm64" }
    return "x86_64"
}

function Find-Iscc {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return ""
}

function Run-Package {
    param([string]$TargetArch, [string]$TargetVersion, [switch]$WithInstaller)
    if (-not (Test-Path $Python)) {
        Write-Host "找不到 $Python，先确认虚拟环境在不在。" -ForegroundColor Red
        return
    }

    if (-not $TargetVersion) { $TargetVersion = Read-BuildVersion }
    $targetVersion = $TargetVersion
    if ($targetVersion -notmatch '^\d+(\.\d+){0,3}$') {
        Write-Host "版本号只能是数字点号，比如 4.6 或 4.6.1：$targetVersion" -ForegroundColor Red
        return
    }

    if ($TargetArch -and $TargetArch -notin @("x86_64", "arm64")) {
        Write-Host "架构只能是 x86_64 或 arm64：$TargetArch" -ForegroundColor Red
        return
    }

    $machineArch = Get-MachineArch
    if (-not $TargetArch) { $TargetArch = $machineArch }
    $targetArch = $TargetArch
    if ($targetArch -ne $machineArch) {
        Write-Host "本机是 $machineArch，Nuitka 不能交叉编译，$targetArch 的包得在 $targetArch 机器上打。" -ForegroundColor Red
        return
    }

    if (-not (Stop-Instances)) { return }

    Write-Host "开始构建：版本 $targetVersion，架构 $targetArch" -ForegroundColor Cyan
    & $Python $Deploy --version $targetVersion
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Nuitka 构建失败，退出码 $LASTEXITCODE。" -ForegroundColor Red
        return
    }

    if (-not $WithInstaller) {
        Write-Host "构建完成，产物在 $Root\dist。" -ForegroundColor Green
        return
    }

    $iscc = Find-Iscc
    if (-not $iscc) {
        Write-Host "找不到 ISCC.exe，装了 Inno Setup 6 再来。" -ForegroundColor Red
        return
    }
    if (-not (Test-Path $DistDir)) {
        Write-Host "找不到 $DistDir，构建产物不完整。" -ForegroundColor Red
        return
    }

    $languagesIss = Join-Path $Root "build\installer\languages.iss"
    if (-not (Test-Path $languagesIss)) {
        Write-Host "安装包语言文件还不存在，先联网生成一次。" -ForegroundColor DarkGray
        & $Python (Join-Path $PSScriptRoot "fetch_installer_languages.py")
        if ($LASTEXITCODE -ne 0) {
            Write-Host "生成语言文件失败，检查网络后重试。" -ForegroundColor Red
            return
        }
    }

    # 不动仓库里的 .iss：复制一份到同目录，SourceDir=.. 之类的相对路径才不会错位，
    # 在副本里换掉版本号和架构字面量，编完删掉。
    if ($targetArch -eq "arm64") { $innoArch = "arm64" } else { $innoArch = "x64compatible and not arm64" }
    $tempIss = Join-Path $PSScriptRoot "Ghost-Downloader-3.local.iss"
    $text = Get-Content $Iss -Raw -Encoding UTF8
    $text = $text.Replace('"APPLICATION_VERSION"', '"' + $targetVersion + '"')
    $text = $text.Replace('"APPLICATION_ARCHITECTURES"', '"' + $innoArch + '"')
    # 带 BOM 写，ISCC 靠 BOM 判断 UTF-8；.iss 里有中文注释，无 BOM 会按 ANSI 解析成乱码
    [System.IO.File]::WriteAllText($tempIss, $text, (New-Object System.Text.UTF8Encoding($true)))
    try {
        & $iscc /Qp $tempIss
        # ISCC 在 /Qp 下会往 stdout 打一个不带换行的 "Preprocessing"，之后不补换行，
        # 后面的提示就会粘在同一行末尾，看起来像卡住没输出。这里先断行。
        Write-Host ""
        if ($LASTEXITCODE -ne 0) {
            Write-Host "安装包编译失败，退出码 $LASTEXITCODE。" -ForegroundColor Red
            return
        }
    }
    finally {
        Remove-Item $tempIss -Force -ErrorAction SilentlyContinue
    }

    Write-Host "安装包好了：$Root\dist\Ghost-Downloader-v$targetVersion-Windows-Setup.exe" -ForegroundColor Green
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
        "package" { Run-Package -TargetArch $Arch -TargetVersion $Version -WithInstaller:$Installer }
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
    Write-Host "  6. 打包（Nuitka 构建，可选出安装包）"
    Write-Host "  0. 退出"
    Write-Host ""
    $choice = Read-Host "选一个"

    switch ($choice.Trim()) {
        "1" { Invoke-Mode -Name "bg" }
        "2" { Invoke-Mode -Name "fg" }
        "3" { Invoke-Mode -Name "log" }
        "4" { Invoke-Mode -Name "list" }
        "5" { Invoke-Mode -Name "kill" }
        "6" {
            # 变量名不能叫 $arch/$version/$installer：PowerShell 变量名大小写不敏感，
            # 那就是参数 $Arch（带 ValidateSet）本人，回车给空串会当场抛 MetadataError
            $archInput = Read-Host ("目标架构，回车用本机 " + (Get-MachineArch) + "（x86_64/arm64）")
            $versionInput = Read-Host ("版本号，回车用 constants.py 里的 " + (Read-BuildVersion))
            $installerInput = Read-Host "要安装包吗？出的话输入 y"
            Run-Package -TargetArch $archInput -TargetVersion $versionInput -WithInstaller:($installerInput -match "^y")
        }
        "0" { return }
        default { Write-Host "没有这一项，重新选。" -ForegroundColor DarkYellow }
    }

    # 前台模式回来后就回到菜单，方便改代码再起
    if ($choice.Trim() -in @("1", "2", "3", "4", "5", "6")) {
        Write-Host ""
        [void](Read-Host "按回车回到菜单")
        # 输出被重定向时没有控制台句柄，Clear-Host 会抛错，出错就只空一行
        try { Clear-Host } catch { Write-Host "" }
    }
}
