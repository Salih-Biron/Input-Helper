import json
import os
import sys
import tempfile
import threading
from pathlib import Path

import ctypes
from ctypes import wintypes

import keyboard

def get_config_path():
    if getattr(sys, "frozen", False):
        local_appdata = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(local_appdata) / "InputHelper" / "config.json"
    return Path(__file__).with_name("config.json")


CONFIG_PATH = get_config_path()


PUL = ctypes.POINTER(ctypes.c_ulong)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_EXTENDEDKEY = 0x0001

_VK_RETURN = 0x0D
_VK_BACK = 0x08
_VK_ESCAPE = 0x1B
_VK_HOME = 0x24
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_SHIFT = 0x10
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C
_VK_LCONTROL = 0xA2
_VK_RCONTROL = 0xA3
_VK_LSHIFT = 0xA0
_VK_RSHIFT = 0xA1
_VK_LMENU = 0xA4
_VK_RMENU = 0xA5

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    _user32.SendInput.restype = wintypes.UINT
    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = wintypes.SHORT
except (OSError, AttributeError):
    _user32 = None


def _send_inputs(inputs):
    if not inputs or _user32 is None:
        return
    arr_type = _INPUT * len(inputs)
    arr = arr_type(*inputs)
    _user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))


def _make_unicode_input(code_unit, key_up=False):
    flags = _KEYEVENTF_UNICODE | (_KEYEVENTF_KEYUP if key_up else 0)
    ki = _KEYBDINPUT(0, code_unit, flags, 0, None)
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp.ki = ki
    return inp


def _make_vk_input(vk, key_up=False, extended=False):
    flags = (_KEYEVENTF_KEYUP if key_up else 0) | (_KEYEVENTF_EXTENDEDKEY if extended else 0)
    ki = _KEYBDINPUT(vk, 0, flags, 0, None)
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp.ki = ki
    return inp


def send_unicode_text(text):
    if not text or _user32 is None:
        return
    inputs = []
    for ch in text:
        cp = ord(ch)
        if cp > 0xFFFF:
            cp -= 0x10000
            high = 0xD800 + (cp >> 10)
            low = 0xDC00 + (cp & 0x3FF)
            inputs.append(_make_unicode_input(high))
            inputs.append(_make_unicode_input(high, key_up=True))
            inputs.append(_make_unicode_input(low))
            inputs.append(_make_unicode_input(low, key_up=True))
        else:
            inputs.append(_make_unicode_input(cp))
            inputs.append(_make_unicode_input(cp, key_up=True))
    _send_inputs(inputs)


def send_vk_tap(vk, extended=False):
    _send_inputs([_make_vk_input(vk, extended=extended), _make_vk_input(vk, key_up=True, extended=extended)])


def select_to_line_start():
    _send_inputs([
        _make_vk_input(_VK_SHIFT),
        _make_vk_input(_VK_HOME, extended=True),
        _make_vk_input(_VK_HOME, key_up=True, extended=True),
        _make_vk_input(_VK_SHIFT, key_up=True),
    ])


def release_modifier_keys():
    if _user32 is None:
        return
    inputs = []
    for vk in (_VK_LCONTROL, _VK_RCONTROL, _VK_LSHIFT, _VK_RSHIFT, _VK_LMENU, _VK_RMENU,
               _VK_CONTROL, _VK_SHIFT, _VK_MENU, _VK_LWIN, _VK_RWIN):
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            inputs.append(_make_vk_input(vk, key_up=True))
    if inputs:
        _send_inputs(inputs)


def configure_tk_library_paths():
    if not getattr(sys, "frozen", False):
        return

    bundle_root = Path(getattr(sys, "_MEIPASS", ""))
    if not bundle_root.exists():
        return

    os.environ.pop("TCL_LIBRARY", None)
    os.environ.pop("TK_LIBRARY", None)
    os.environ.pop("TCLLIBPATH", None)

    candidates = [
        (bundle_root / "_tcl_data", bundle_root / "_tk_data"),
        (bundle_root / "tcl" / "tcl8.6", bundle_root / "tcl" / "tk8.6"),
        (bundle_root / "lib" / "tcl8.6", bundle_root / "lib" / "tk8.6"),
    ]

    for tcl_dir, tk_dir in candidates:
        if (tcl_dir / "init.tcl").exists() and (tk_dir / "tk.tcl").exists():
            os.environ["TCL_LIBRARY"] = str(tcl_dir)
            os.environ["TK_LIBRARY"] = str(tk_dir)
            return

    for init_path in bundle_root.rglob("init.tcl"):
        os.environ["TCL_LIBRARY"] = str(init_path.parent)
        break

    for tk_path in bundle_root.rglob("tk.tcl"):
        os.environ["TK_LIBRARY"] = str(tk_path.parent)
        break


configure_tk_library_paths()

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText


class HotkeyListener(threading.Thread):
    def __init__(self, on_type_hotkey, on_stop_hotkey, on_status):
        super().__init__(daemon=True)
        self.on_type_hotkey = on_type_hotkey
        self.on_stop_hotkey = on_stop_hotkey
        self.on_status = on_status
        self.stop_event = threading.Event()
        self.type_hotkey_handle = None
        self.stop_hotkey_handle = None
        self._lock = threading.Lock()

    def _register(self):
        if self.stop_hotkey_handle is None:
            self.stop_hotkey_handle = keyboard.add_hotkey(
                "ctrl+shift+x",
                self.on_stop_hotkey,
                suppress=True,
                trigger_on_release=False,
            )
        if self.type_hotkey_handle is None:
            self.type_hotkey_handle = keyboard.add_hotkey(
                "ctrl+shift+q",
                self.on_type_hotkey,
                suppress=True,
                trigger_on_release=True,
            )

    def _unregister_type_hotkey(self):
        if self.type_hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.type_hotkey_handle)
            except (KeyError, ValueError):
                pass
            self.type_hotkey_handle = None

    def _unregister(self):
        self._unregister_type_hotkey()
        if self.stop_hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.stop_hotkey_handle)
            except (KeyError, ValueError):
                pass
            self.stop_hotkey_handle = None

    def run(self):
        try:
            with self._lock:
                self._register()
        except Exception as exc:
            with self._lock:
                self._unregister()
            self.on_status(f"热键注册失败：{exc}")
            return

        self.on_status("热键已就绪：Ctrl+Shift+Q 输入，Ctrl+Shift+X 停止。")

        self.stop_event.wait()

        with self._lock:
            self._unregister()

    def pause_hotkeys(self):
        with self._lock:
            self._unregister_type_hotkey()

    def resume_hotkeys(self):
        with self._lock:
            if self.stop_event.is_set():
                return
            try:
                self._register()
            except Exception as exc:
                self.on_status(f"热键恢复失败：{exc}")

    def stop(self):
        self.stop_event.set()


class InputHelperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("自动输入助手")
        self.root.geometry("860x660")
        self.root.minsize(760, 600)

        self.typing_thread = None
        self.stop_typing_event = threading.Event()
        self.hotkey_listener = None

        self.delay_var = tk.DoubleVar(value=0.8)
        self.interval_var = tk.DoubleVar(value=0.05)
        self.tab_size_var = tk.IntVar(value=4)
        self.expand_tabs_var = tk.BooleanVar(value=True)
        self.code_mode_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="正在启动热键监听...")

        self.build_ui()
        self.load_config()
        self.start_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        title = ttk.Label(main, text="自动输入助手", font=("Microsoft YaHei UI", 16, "bold"))
        title.pack(anchor="w")

        hint = ttk.Label(
            main,
            text="针对 Educoder 代码编辑器：默认启用“代码模式”，程序会逐行覆盖编辑器的自动缩进。",
            foreground="#444444",
        )
        hint.pack(anchor="w", pady=(6, 12))

        self.textbox = ScrolledText(main, wrap="none", font=("Consolas", 11), height=20)
        self.textbox.pack(fill="both", expand=True)

        controls = ttk.Frame(main)
        controls.pack(fill="x", pady=12)

        ttk.Label(controls, text="开始前延迟(秒)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(controls, from_=0, to=10, increment=0.1, textvariable=self.delay_var, width=8).grid(row=0, column=1, padx=(8, 20))

        ttk.Label(controls, text="每字间隔(秒)").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(controls, from_=0, to=1, increment=0.005, textvariable=self.interval_var, width=8).grid(row=0, column=3, padx=(8, 20))

        ttk.Checkbutton(controls, text="Tab 转空格", variable=self.expand_tabs_var).grid(row=0, column=4, sticky="w")
        ttk.Label(controls, text="Tab 宽度").grid(row=0, column=5, sticky="w", padx=(20, 0))
        ttk.Spinbox(controls, from_=1, to=8, increment=1, textvariable=self.tab_size_var, width=5).grid(row=0, column=6, padx=(8, 0))

        ttk.Checkbutton(controls, text="代码模式(自动缩进补偿)", variable=self.code_mode_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(controls, text="输入热键：Ctrl+Shift+Q").grid(row=1, column=3, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(controls, text="停止热键：Ctrl+Shift+X").grid(row=1, column=5, columnspan=2, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(main)
        buttons.pack(fill="x")

        ttk.Button(buttons, text="导入 TXT", command=self.load_text_file).pack(side="left")
        ttk.Button(buttons, text="保存内容", command=self.save_text_file).pack(side="left", padx=8)
        ttk.Button(buttons, text="预处理缩进", command=self.normalize_text_in_editor).pack(side="left")
        ttk.Button(buttons, text="清空", command=self.clear_text).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="3秒后开始", command=self.start_with_countdown).pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="停止当前输入", command=self.stop_typing).pack(side="right")

        status_box = ttk.LabelFrame(main, text="状态")
        status_box.pack(fill="x", pady=(14, 0))
        ttk.Label(status_box, textvariable=self.status_var, padding=10).pack(anchor="w")

        tips_box = ttk.LabelFrame(main, text="这次针对你截图做的修复")
        tips_box.pack(fill="x", pady=(14, 0))
        tips = (
            "1. 你截图里那种‘每一行越来越往右’是代码编辑器自动缩进和原始缩进叠加造成的。\n"
            "2. 现在代码模式会按行输入：先选中编辑器生成的行首空白，再用原文整行安全覆盖。\n"
            "3. 减少缩进时不再连续退格，因此不会误删上一行或把 except/else 粘到前一行。\n"
            "4. 每次换行前会先关闭自动补全，避免 Enter 接受 auto 等候选词。\n"
            "5. 建议继续保留 Tab 转空格，Tab 宽度用 4，每字间隔用 0.03 到 0.05。"
        )
        ttk.Label(tips_box, text=tips, padding=10, justify="left").pack(anchor="w")

    def start_hotkeys(self):
        self.hotkey_listener = HotkeyListener(
            on_type_hotkey=lambda: self.root.after(0, self.handle_type_hotkey),
            on_stop_hotkey=self.stop_typing,
            on_status=lambda text: self.root.after(0, self.set_status, text),
        )
        self.hotkey_listener.start()

    def set_status(self, text: str):
        self.status_var.set(text)

    def get_numeric_value(self, variable: tk.Variable, default):
        try:
            value = variable.get()
            if isinstance(default, int):
                return max(0, int(value))
            return max(0.0, float(value))
        except (tk.TclError, ValueError):
            return default

    def try_get_numeric_value(self, variable: tk.Variable, default):
        try:
            value = variable.get()
            if isinstance(default, int):
                return max(0, int(value)), True
            return max(0.0, float(value)), True
        except (tk.TclError, ValueError):
            return default, False

    def get_text(self):
        return self.textbox.get("1.0", "end-1c")

    def set_text(self, text: str):
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)

    def normalize_text(self, text: str, expand_tabs: bool, tab_size: int):
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = normalized.replace("\u00a0", " ")
        normalized = normalized.replace("\ufeff", "")
        if expand_tabs:
            normalized = normalized.expandtabs(max(1, tab_size))
        return normalized

    def handle_type_hotkey(self):
        self.start_typing_request(source_label="热键")

    def start_with_countdown(self):
        self.start_typing_request(start_delay_override=3.0, source_label="倒计时")

    def normalize_text_in_editor(self):
        tab_size, tab_size_valid = self.try_get_numeric_value(self.tab_size_var, 4)
        if not tab_size_valid or tab_size < 1:
            tab_size = 4
            self.tab_size_var.set(tab_size)
        normalized = self.normalize_text(self.get_text(), bool(self.expand_tabs_var.get()), tab_size)
        self.set_text(normalized)
        self.save_config()
        self.set_status("已在程序内预处理文本：换行统一，Tab 已按设置转换。")

    def start_typing_request(self, start_delay_override=None, source_label="热键"):
        text = self.get_text()
        if not text.strip():
            self.set_status("文本框是空的，请先输入或导入内容。")
            return

        if self.typing_thread and self.typing_thread.is_alive():
            self.set_status("正在输入中；如需中止，请按 Ctrl+Shift+X。")
            return

        start_delay, delay_valid = self.try_get_numeric_value(self.delay_var, 0.8)
        interval, interval_valid = self.try_get_numeric_value(self.interval_var, 0.03)
        tab_size, tab_size_valid = self.try_get_numeric_value(self.tab_size_var, 4)

        if not delay_valid:
            start_delay = 0.8
            self.delay_var.set(start_delay)
        if not interval_valid:
            interval = 0.03
            self.interval_var.set(interval)
        if not tab_size_valid or tab_size < 1:
            tab_size = 4
            self.tab_size_var.set(tab_size)
        if not delay_valid or not interval_valid or not tab_size_valid:
            messagebox.showwarning("参数已修正", "检测到无效数字，已恢复为可用设置。")

        if start_delay_override is not None:
            start_delay = max(float(start_delay_override), start_delay)

        prepared_text = self.normalize_text(text, bool(self.expand_tabs_var.get()), tab_size)
        code_mode = bool(self.code_mode_var.get())

        self.stop_typing_event.clear()
        self.typing_thread = threading.Thread(
            target=self.type_text_worker,
            args=(prepared_text, start_delay, interval, tab_size, code_mode),
            daemon=True,
        )
        self.typing_thread.start()

        if start_delay > 0:
            self.set_status(f"{source_label}已触发，将在 {start_delay:.1f} 秒后开始输入。")
        else:
            self.set_status(f"{source_label}已触发，正在发送文字...")

    def type_text_chunk(self, text: str, interval: float):
        if not text:
            return True

        for ch in text:
            if self.stop_typing_event.is_set():
                return False
            send_unicode_text(ch)
            if interval and self.stop_typing_event.wait(interval):
                return False
        return not self.stop_typing_event.is_set()

    def type_exact_line(self, line: str, interval: float):
        if not line:
            return True
        return self.type_text_chunk(line, interval)

    def type_code_text(self, text: str, interval: float, tab_size: int):
        del tab_size
        lines = text.split("\n")
        if not lines:
            return

        enter_settle = max(interval * 3, 0.08)

        if not self.type_exact_line(lines[0], interval):
            return

        for line in lines[1:]:
            if self.stop_typing_event.is_set():
                return

            send_vk_tap(_VK_ESCAPE)
            if self.stop_typing_event.wait(min(max(interval, 0.01), 0.03)):
                return
            send_vk_tap(_VK_RETURN)
            if self.stop_typing_event.wait(enter_settle):
                return

            select_to_line_start()
            replacement = line if line else " "
            if not self.type_exact_line(replacement, interval):
                return
            if not line:
                send_vk_tap(_VK_BACK)

    def type_plain_text(self, text: str, interval: float):
        run_start = 0

        def flush_text(end: int):
            segment = text[run_start:end]
            if not segment:
                return True
            return self.type_text_chunk(segment, interval)

        idx = 0
        while idx < len(text):
            if self.stop_typing_event.is_set():
                return
            ch = text[idx]
            if ch in ("\n", "\b"):
                if not flush_text(idx):
                    return
                if self.stop_typing_event.is_set():
                    return
                if ch == "\n":
                    send_vk_tap(_VK_RETURN)
                else:
                    send_vk_tap(_VK_BACK)
                if interval and self.stop_typing_event.wait(interval):
                    return
                run_start = idx + 1
            idx += 1

        flush_text(len(text))

    def type_text_worker(self, text: str, start_delay: float, interval: float, tab_size: int, code_mode: bool):
        hotkeys_paused = False
        try:
            if self.stop_typing_event.wait(start_delay):
                return

            if self.hotkey_listener:
                self.hotkey_listener.pause_hotkeys()
                hotkeys_paused = True

            if self.stop_typing_event.wait(0.05):
                return
            release_modifier_keys()
            if self.stop_typing_event.wait(0.02):
                return

            if code_mode:
                self.type_code_text(text, interval, tab_size)
            else:
                self.type_plain_text(text, interval)

            if not self.stop_typing_event.is_set():
                self.root.after(0, self.set_status, "输入完成，可以继续修改内容后再次触发。")
        except Exception as exc:
            self.root.after(0, self.set_status, f"输入失败：{exc}")
        finally:
            if hotkeys_paused and self.hotkey_listener:
                self.hotkey_listener.resume_hotkeys()
            if self.stop_typing_event.is_set():
                self.root.after(0, self.set_status, "输入已停止。")

    def stop_typing(self):
        self.stop_typing_event.set()
        self.root.after(0, self.set_status, "已请求停止；若正在输入，会在下一字符处停下。")

    def load_text_file(self):
        file_path = filedialog.askopenfilename(
            title="选择 TXT 文件",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = Path(file_path).read_text(encoding="gbk")

        self.set_text(content)
        self.set_status(f"已导入：{file_path}")
        self.save_config()

    def save_text_file(self):
        file_path = filedialog.asksaveasfilename(
            title="保存内容",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        Path(file_path).write_text(self.get_text(), encoding="utf-8")
        self.set_status(f"内容已保存到：{file_path}")
        self.save_config()

    def clear_text(self):
        self.textbox.delete("1.0", "end")
        self.set_status("文本已清空。")
        self.save_config()

    def load_config(self):
        if not CONFIG_PATH.exists():
            return

        try:
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return
        if not isinstance(config, dict):
            return

        self.delay_var.set(config.get("start_delay", 0.8))
        self.interval_var.set(config.get("char_interval", 0.03))
        self.tab_size_var.set(config.get("tab_size", 4))
        self.expand_tabs_var.set(config.get("expand_tabs", True))
        self.code_mode_var.set(config.get("code_mode", True))
        cached_text = config.get("cached_text", "")
        if cached_text:
            self.set_text(cached_text)

    def save_config(self):
        config = {
            "start_delay": self.get_numeric_value(self.delay_var, 0.8),
            "char_interval": self.get_numeric_value(self.interval_var, 0.03),
            "tab_size": self.get_numeric_value(self.tab_size_var, 4),
            "expand_tabs": bool(self.expand_tabs_var.get()),
            "code_mode": bool(self.code_mode_var.get()),
            "cached_text": self.get_text(),
        }
        temp_path = None
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=CONFIG_PATH.parent,
                prefix=".config-", suffix=".tmp", delete=False,
            ) as config_file:
                temp_path = Path(config_file.name)
                json.dump(config, config_file, ensure_ascii=False, indent=2)
            temp_path.replace(CONFIG_PATH)
        except OSError as exc:
            self.set_status(f"配置保存失败：{exc}")
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def on_close(self):
        self.stop_typing_event.set()
        self.save_config()
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener.join(timeout=1.0)
        keyboard.unhook_all_hotkeys()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    InputHelperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
