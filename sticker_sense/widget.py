"""桌面悬浮挂件：点一下弹面板，点表情自动粘进当前输入框。

流程：
  点悬浮球（或按 Ctrl+Shift+E）
    → 面板弹出
    → 点某张表情
    → 图片 + 标记写入剪贴板
    → 焦点还给原来的窗口，模拟 Ctrl+V
    → 表情直接落进输入框，回车即发

不依赖任何客户端，ChatGPT / Claude / 微信 / QQ 都能用。
"""

from __future__ import annotations

import ctypes
import json
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageTk

from . import clipboard
from .library import Library

BALL = 56
CELL = 72
COLS = 4
PAD = 12
GAP = 8

TRANSPARENT = "#FF00FF"
PANEL_BG = "#FFFFFF"
LINE = "#DDDAD2"
INK = "#1A1A1A"
MUTED = "#7A7A7A"

# 挂件住在哪个进程的窗口里。找不到就退化成普通悬浮球。
HOST_KEYWORDS = ("workbuddy", "codebuddy")


class Widget:
    def __init__(self, lib: Library, hotkey_text: str = "Ctrl+Shift+E"):
        self.lib = lib
        self.hotkey_text = hotkey_text
        self.target_hwnd = 0
        self.host = 0
        self._orphan_since = 0.0
        self.panel: tk.Toplevel | None = None
        self._photos: list[ImageTk.PhotoImage] = []
        self._notice = ""
        self._drag = (0, 0)
        self._moved = False
        self._dragging = False
        self._modal = False
        self._dock_ratio = 0.5
        self._hotkey_hit = threading.Event()
        self._hotkey_ok = False

        self.root = tk.Tk()
        self.root.title("表情挂件")
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.root.configure(bg=TRANSPARENT)
        self.root.attributes("-topmost", True)
        self.root.update_idletasks()

        self._attach_host()
        self._build_ball()
        self._start_hotkey()
        self.root.after(60, self._poll_hotkey)
        self.root.after(150, self._follow_host)

    # ---------- 宿主窗口 ----------

    def _attach_host(self) -> bool:
        """找到 agent 主窗口并停靠。

        实测 tk 的 overrideredirect 窗口拿不到真正的 owner 关系，
        所以不靠它，改用「前台跟随」：宿主在前台时置顶显示，切走就收起。
        这样既不会被宿主遮住，也不会飘在别的应用上面。
        """
        host = clipboard.find_host_window(HOST_KEYWORDS)
        if host and host != self.host:
            self.host = host
            clipboard.set_owner(clipboard.toplevel_hwnd(self.root), host)
            self._dock()
        return bool(host)

    def _dock(self) -> None:
        rect = clipboard.window_rect(self.host) if self.host else None
        if not rect:
            return
        left, top, right, bottom = rect
        margin = 14
        x = right - BALL - margin
        y = top + int((bottom - top) * self._dock_ratio) - BALL // 2
        y = max(top + margin, min(y, bottom - BALL - margin))
        self.root.geometry(f"{BALL}x{BALL}+{x}+{y}")

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        rect = clipboard.window_rect(self.host) if self.host else None
        if not rect:
            return x, y
        left, top, right, bottom = rect
        margin = 6
        return (
            max(left + margin, min(x, right - BALL - margin)),
            max(top + margin, min(y, bottom - BALL - margin)),
        )

    def _follow_host(self) -> None:
        """宿主移动/缩放跟着走；宿主不在前台就收起；宿主没了就重新找。

        注意别在宿主消失时立刻退出：agent 重启会换一个新的窗口句柄，
        如果这里自杀，新起的 hook 又会被单实例互斥量挡掉，最后两头落空。
        正确做法是把 host 清零重新找，找到就继续跟着新窗口走。
        """
        try:
            if self.host and clipboard.window_rect(self.host) is None:
                self.host = 0
                self._orphan_since = self._orphan_since or time.time()

            if not self.host:
                self._attach_host()
                if self.host:
                    self._orphan_since = 0.0
                elif self._orphan_since and time.time() - self._orphan_since > 300:
                    # 五分钟都没等到 agent，别留个隐形进程
                    self.quit()
                    return
                else:
                    self.root.withdraw()

            if self.host:
                on_stage = clipboard.is_active(self.host) and not clipboard.is_minimized(
                    self.host
                )
                # 面板开着、文件对话框开着、正在拖动时，不要抢着收起
                if not on_stage and self.panel is None and not self._modal and not self._dragging:
                    self.root.withdraw()
                elif on_stage:
                    if self.root.state() == "withdrawn":
                        self.root.deiconify()
                    if not self._dragging:
                        self._dock()
        finally:
            try:
                self.root.after(400, self._follow_host)
            except tk.TclError:
                pass

    def _build_ball(self) -> None:
        canvas = tk.Canvas(
            self.root, width=BALL, height=BALL, bg=TRANSPARENT,
            highlightthickness=0, cursor="hand2",
        )
        canvas.pack()
        canvas.create_oval(3, 3, BALL - 3, BALL - 3, fill="#FFD51A",
                           outline="#E8B800", width=2)
        canvas.create_oval(19, 24, 25, 30, fill="#342C14", outline="")
        canvas.create_oval(31, 24, 37, 30, fill="#342C14", outline="")
        canvas.create_line(23, 39, 33, 39, fill="#342C14", width=3, capstyle="round")

        canvas.bind("<Button-1>", self._ball_down)
        canvas.bind("<B1-Motion>", self._ball_move)
        canvas.bind("<ButtonRelease-1>", self._ball_up)
        canvas.bind("<Button-3>", self._ball_menu)
        self.canvas = canvas

    def _ball_down(self, event) -> None:
        self._drag = (event.x_root - self.root.winfo_x(),
                      event.y_root - self.root.winfo_y())
        self._moved = False
        self._dragging = True

    def _ball_move(self, event) -> None:
        self._moved = True
        x, y = self._clamp(event.x_root - self._drag[0],
                           event.y_root - self._drag[1])
        self.root.geometry(f"+{x}+{y}")

    def _ball_up(self, event) -> None:
        self._dragging = False
        if self._moved:
            rect = clipboard.window_rect(self.host) if self.host else None
            if rect:
                top, bottom = rect[1], rect[3]
                center = self.root.winfo_y() + BALL // 2
                span = max(1, bottom - top)
                self._dock_ratio = max(0.05, min(0.95, (center - top) / span))
            return
        self.toggle_panel()

    def _ball_menu(self, event) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"快捷键 {self.hotkey_text}", state="disabled")
        menu.add_separator()
        menu.add_command(label="退出挂件", command=self.quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---------- 面板 ----------

    def toggle_panel(self) -> None:
        if self.panel is not None:
            self.close_panel()
        else:
            self.open_panel()

    def open_panel(self, preserve_target: bool = False) -> None:
        if not preserve_target:
            if not self.host:
                self._attach_host()
            # 点球会把前台抢到挂件身上，直接取 foreground 会记成自己，
            # 粘回时就粘到挂件里了。pick_target 会排掉这种情况。
            self.target_hwnd = clipboard.pick_target(self.host)
        notice, self._notice = self._notice, ""
        items = self.lib.list_stickers()

        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        panel.attributes("-topmost", True)
        panel.configure(bg=LINE)

        body = tk.Frame(panel, bg=PANEL_BG, padx=PAD, pady=PAD)
        body.pack(padx=1, pady=1)

        head = tk.Frame(body, bg=PANEL_BG)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="表情", bg=PANEL_BG, fg=INK,
                 font=("Microsoft YaHei", 10, "bold")).pack(side="left")
        tk.Button(
            head, text="＋ 添加", command=self.add_stickers, bd=0, relief="flat",
            bg="#F2F0E9", fg=INK, activebackground="#E8E6DE", cursor="hand2",
            font=("Microsoft YaHei", 9), padx=8, pady=1,
        ).pack(side="right")

        grid = tk.Frame(body, bg=PANEL_BG)
        grid.pack()

        self._photos = []
        if not items:
            tk.Label(
                grid, text="还没有表情\n点右上角「＋ 添加」导入", bg=PANEL_BG,
                fg=MUTED, font=("Microsoft YaHei", 9), justify="center",
                padx=24, pady=20,
            ).pack()
        for idx, item in enumerate(items[:24]):
            row, col = divmod(idx, COLS)
            self._add_cell(grid, item, row, col)

        unlabeled = sum(1 for i in items if i["reading_count"] == 0)
        tip = tk.Frame(body, bg=PANEL_BG)
        tip.pack(fill="x", pady=(10, 0))
        note = notice or f"{len(items)} 张 · 点击即粘贴"
        if unlabeled and not notice:
            note += f" · {unlabeled} 张待说明"
        tk.Label(tip, text=note, bg=PANEL_BG,
                 fg="#854F0B" if notice else MUTED,
                 font=("Microsoft YaHei", 8)).pack(side="left")
        tk.Label(tip, text="Esc 关闭", bg=PANEL_BG, fg=MUTED,
                 font=("Microsoft YaHei", 8)).pack(side="right")

        panel.update_idletasks()
        pw, ph = panel.winfo_reqwidth(), panel.winfo_reqheight()
        bx, by = self.root.winfo_x(), self.root.winfo_y()

        rect = clipboard.window_rect(self.host) if self.host else None
        if rect:
            # 面板也不许跑出 agent 窗口
            left, top, right, bottom = rect
            x = min(max(left + 8, bx - pw - 12), right - pw - 8)
            y = min(max(top + 8, by + BALL // 2 - ph // 2), bottom - ph - 8)
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = min(max(8, bx - pw - 12), sw - pw - 8)
            y = min(max(8, by + BALL // 2 - ph // 2), sh - ph - 48)
        panel.geometry(f"+{x}+{y}")

        panel.bind("<Escape>", lambda _e: self.close_panel())
        panel.focus_force()
        self.panel = panel

    def _add_cell(self, parent: tk.Frame, item: dict, row: int, col: int) -> None:
        try:
            img = Image.open(item["file"]).convert("RGB")
            img.thumbnail((CELL - 8, CELL - 8), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
        except Exception:
            return
        self._photos.append(photo)

        # 还没写读法的图，用暖色描边标出来，提醒用户它还没被"教"过
        unlabeled = item["reading_count"] == 0
        btn = tk.Button(
            parent, image=photo, bd=0, relief="flat", bg=PANEL_BG,
            activebackground="#F2F0E9",
            highlightthickness=1 if unlabeled else 0,
            highlightbackground="#E8B800",
            cursor="hand2", padx=0, pady=0,
            command=lambda i=item: self.pick(i),
        )
        btn.grid(row=row, column=col, padx=GAP // 2, pady=GAP // 2,
                 ipadx=2, ipady=2)

    def close_panel(self) -> None:
        if self.panel is not None:
            self.panel.destroy()
            self.panel = None

    def refresh_panel(self) -> None:
        self.close_panel()
        self.open_panel(preserve_target=True)

    def add_stickers(self) -> None:
        """导入自己的表情包。

        这里刻意不要求用户填含义——加了图直接就能用，含义等你发一次、
        AI 问一句之后再记。让"加图"这件事的摩擦降到零。
        """
        self._modal = True
        try:
            paths = filedialog.askopenfilenames(
                parent=self.panel,
                title="选择表情包图片（可多选）",
                filetypes=[
                    ("图片", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                    ("所有文件", "*.*"),
                ],
            )
        finally:
            self._modal = False
        if not paths:
            return

        added = 0
        for path in paths:
            try:
                res = self.lib.import_file(path, source="user_added")
            except Exception:
                continue
            if res and res["status"] == "added":
                added += 1

        if added:
            self._notice = f"已加 {added} 张 · 发一次我就问它什么意思"
        else:
            self._notice = "这些图已经在库里了"
        self.refresh_panel()

    # ---------- 核心动作 ----------

    def pick(self, item: dict) -> None:
        sid = item["id"]
        token = f"[sticker:{sid}]"
        try:
            img = Image.open(item["file"])
            clipboard.set_image_and_text(img, token)
        except Exception as exc:  # 剪贴板被占用时会失败
            print(f"写剪贴板失败：{exc}")
            return

        self._write_last_pick(sid, item["file"])
        try:
            self.lib.record_use(sid)
        except Exception:
            pass

        self.close_panel()

        hwnd = self.target_hwnd
        if hwnd:
            threading.Thread(
                target=self._paste_back, args=(hwnd,), daemon=True
            ).start()

    def _paste_back(self, hwnd: int) -> None:
        clipboard.force_foreground(hwnd)
        clipboard.send_paste(0.18)

    def _write_last_pick(self, sid: str, path: str) -> None:
        payload = {"id": sid, "ts": time.time(), "path": path}
        try:
            (self.lib.data_dir / "last_pick.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    # ---------- 全局热键 ----------

    def _start_hotkey(self) -> None:
        def run() -> None:
            self._hotkey_ok = clipboard.register_hotkey()
            if not self._hotkey_ok:
                return
            msg = wintypes.MSG()
            while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == clipboard.WM_HOTKEY:
                    self._hotkey_hit.set()

        threading.Thread(target=run, daemon=True).start()

    def _poll_hotkey(self) -> None:
        if self._hotkey_hit.is_set():
            self._hotkey_hit.clear()
            self.toggle_panel()
        self.root.after(60, self._poll_hotkey)

    # ---------- 生命周期 ----------

    def quit(self) -> None:
        try:
            clipboard.unregister_hotkey()
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


_MUTEX = None


def _acquire_single_instance() -> bool:
    """同一个用户只允许跑一个挂件，重复启动直接静默退出。

    开机自启 + 手动双击很容易撞上，没有这个锁就会冒出两个悬浮球。
    """
    global _MUTEX
    kernel32 = ctypes.windll.kernel32
    _MUTEX = kernel32.CreateMutexW(None, False, "Local\\StickerSenseWidget")
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main(data_dir: str | Path) -> int:
    if not _acquire_single_instance():
        print("挂件已经在运行了")
        return 0
    lib = Library(data_dir)
    widget = Widget(lib)
    try:
        widget.run()
    finally:
        lib.close()
    return 0
