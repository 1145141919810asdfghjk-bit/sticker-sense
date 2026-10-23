"""用 WMI 创建进程，跳出调用方的 Job Object。

为什么需要：agent 把 hook 放在 kill-on-close 的作业对象里跑，
子进程会随 hook 命令结束被连带杀掉（实测 CREATE_BREAKAWAY_FROM_JOB
被拒绝，WinError 5）。而 Win32_Process.Create 是由 WmiPrvSE 这个服务
创建的，父进程不是 hook，天然不在那个作业里，进程能活下来。

实现上走 PowerShell 的 Invoke-CimMethod，脚本用 base64 传，
避免引号和中文路径在命令行里被转义搞坏。
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000


def _encode(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def launch(exe: Path, script: Path, timeout: float = 8.0) -> bool:
    """用 WMI 拉起进程。成功返回 True。"""
    # PowerShell 单引号字符串里，单引号要写两遍
    cmdline = f'"{exe}" "{script}"'
    ps = (
        "$ErrorActionPreference='Stop';"
        "$r=Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine='" + cmdline.replace("'", "''") + "'};"
        "if($r.ReturnValue -eq 0){exit 0}else{exit $r.ReturnValue}"
    )
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle", "Hidden",
                "-EncodedCommand", _encode(ps),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
