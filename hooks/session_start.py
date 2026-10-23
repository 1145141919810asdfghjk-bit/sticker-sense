"""SessionStart hook：确保表情挂件跟着 agent 一起起来。

五条原则：
1. fail-open —— 任何异常都静默退出 0，绝不阻塞 agent 启动
2. 立刻返回 —— hook 默认 60 秒超时，这里必须 fire-and-forget
3. 单实例 —— 真正的去重靠 widget 里的互斥量，这里重复调用无害
4. 跳出作业对象 —— agent 把 hook 放在 kill-on-close 的 Job Object 里跑，
   hook 命令一结束子进程就被连带杀掉。实测 CREATE_BREAKAWAY_FROM_JOB
   会被拒绝（WinError 5），所以优先走 WMI 的 Win32_Process.Create：
   进程由 WmiPrvSE 服务创建，天然不在那个作业里。
5. 留日志 —— 挂件是后台起的，崩了用户看不到任何提示，写 data/widget.log。

Windows 上 hook 走 Git Bash，所以用 python 显式调用，不依赖文件关联。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
BASE_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _pick_exe() -> Path:
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return pyw if pyw.exists() else exe


def _open_log():
    try:
        log_dir = ROOT / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "widget.log"
        if log_path.exists() and log_path.stat().st_size > 512 * 1024:
            log_path.unlink(missing_ok=True)
        return open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return subprocess.DEVNULL


def _fallback(exe: Path, log) -> None:
    """WMI 不可用时退回普通 detached。至少在本进程存活期间能显示。"""
    subprocess.Popen(
        [str(exe), str(ROOT / "run_widget.py")],
        cwd=str(ROOT),
        creationflags=BASE_FLAGS,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        close_fds=True,
    )


def main() -> int:
    try:
        exe = _pick_exe()
        log = _open_log()

        launched = False
        try:
            from _wmi_launch import launch

            launched = launch(exe, ROOT / "run_widget.py")
        except Exception:
            launched = False

        if not launched:
            _fallback(exe, log)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
