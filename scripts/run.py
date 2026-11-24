r"""启动源码版 Ghost Downloader，改完代码后快速重启测试。

用法：
    .venv\Scripts\python.exe scripts\run.py            # 杀掉旧实例后后台启动，打印 PID
    .venv\Scripts\python.exe scripts\run.py --fg       # 前台启动，日志直接打在终端，Ctrl+C 退出
    .venv\Scripts\python.exe scripts\run.py --kill     # 只杀掉正在跑的实例
    .venv\Scripts\python.exe scripts\run.py --list     # 只列出正在跑的实例
    .venv\Scripts\python.exe scripts\run.py --log      # 启动后跟随日志输出

为什么启动前要先杀：程序用 QSharedMemory 做单实例锁，抢不到锁的新实例会把参数转给老实例然后自己退出，
表现就是"点了没反应"。安装版 exe 也占同一把锁，所以一并处理。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "Ghost-Downloader-3.py"
LOGFILE = Path(os.environ.get("LOCALAPPDATA", "")) / "GhostDownloader" / "GhostDownloader.log"
ENTRY_NAME = ENTRY.name.lower()

ENUM_PROCESSES = (
    "Get-CimInstance Win32_Process -Filter "
    "\"Name='python.exe' OR Name='pythonw.exe' OR Name='Ghost-Downloader-3.exe'\" | "
    "Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains('%s') } | "
    "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
) % ENTRY_NAME


def listInstances() -> list[dict]:
    """列出正在跑本项目的进程：源码版（python/pythonw）和安装版 exe 都算。"""
    shell = "pwsh" if subprocess.run(["where", "pwsh"], capture_output=True).returncode == 0 else "powershell"
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", ENUM_PROCESSES],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [{"pid": item["ProcessId"], "command": (item.get("CommandLine") or "").strip()} for item in data]


def killInstances() -> int:
    instances = listInstances()
    if not instances:
        print("没有正在运行的实例。")
        return 0
    for item in instances:
        print(f"结束进程 {item['pid']}: {shorten(item['command'])}")
        subprocess.run(["taskkill", "/PID", str(item["pid"]), "/T", "/F"], capture_output=True)
    time.sleep(1.5)
    left = listInstances()
    if left:
        print(f"还有 {len(left)} 个进程没退掉，可能要手动处理。")
        return 1
    print("旧实例已全部退出。")
    return 0


def shorten(text: str, limit: int = 110) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def startBackground() -> int:
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        print(f"找不到 {pythonw}，先确认虚拟环境在不在。")
        return 1
    process = subprocess.Popen(
        [str(pythonw), str(ENTRY)],
        cwd=str(ROOT),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.2)
    if process.poll() is not None:
        print(f"启动后立刻退出了（退出码 {process.returncode}），大概率是单实例锁没抢到，或者启动就报错。")
        print(f"看日志：{LOGFILE}")
        return 1
    print(f"已启动，PID {process.pid}")
    print(f"日志：{LOGFILE}")
    return 0


def startForeground() -> int:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        print(f"找不到 {python}，先确认虚拟环境在不在。")
        return 1
    print(f"前台运行 {ENTRY.name}，Ctrl+C 结束。")
    try:
        return subprocess.call([str(python), str(ENTRY)], cwd=str(ROOT))
    except KeyboardInterrupt:
        return 0


def followLog() -> None:
    if not LOGFILE.exists():
        print(f"日志还不存在：{LOGFILE}")
        return
    print(f"跟随日志 {LOGFILE}（Ctrl+C 退出）")
    with LOGFILE.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        try:
            while True:
                line = handle.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.3)
        except KeyboardInterrupt:
            print()


def main() -> int:
    parser = argparse.ArgumentParser(description="启动源码版 Ghost Downloader 做测试")
    parser.add_argument("--fg", action="store_true", help="前台启动，日志打在终端")
    parser.add_argument("--kill", action="store_true", help="只杀掉正在跑的实例")
    parser.add_argument("--list", action="store_true", help="只列出正在跑的实例")
    parser.add_argument("--log", action="store_true", help="启动后跟随日志")
    parser.add_argument("--no-kill", action="store_true", help="启动前不杀旧实例")
    args = parser.parse_args()

    if args.list:
        instances = listInstances()
        if not instances:
            print("没有正在运行的实例。")
        for item in instances:
            print(f"{item['pid']:>8}  {shorten(item['command'])}")
        return 0

    if args.kill:
        return killInstances()

    if not args.no_kill:
        killInstances()
    code = startForeground() if args.fg else startBackground()
    if code == 0 and args.log and not args.fg:
        followLog()
    return code


if __name__ == "__main__":
    sys.exit(main())
