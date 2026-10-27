r"""Opt-in Windows checks: real global hotkey and two packaged-app restarts.

Run after building: .venv\Scripts\python.exe tests\windows_smoke.py
The hotkey check intercepts its own stop chord; no text is sent to other apps.
The EXE check uses an isolated LOCALAPPDATA and closes only windows it creates.
"""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def check_real_stop_hotkey():
    stopped = threading.Event()
    ready = threading.Event()
    listener = app.HotkeyListener(lambda: None, stopped.set, lambda _message: ready.set())
    with patch.object(app, "send_unicode_text"):
        listener.start()
        try:
            if not ready.wait(5) or listener.stop_hotkey_handle is None:
                raise AssertionError("Global hotkeys could not be registered")
            listener.pause_hotkeys()
            keys = (app._VK_LCONTROL, app._VK_LSHIFT, ord("X"))
            inputs = (
                [app._make_vk_input(vk) for vk in keys]
                + [app._make_vk_input(vk, key_up=True) for vk in reversed(keys)]
            )
            for item in inputs:
                item.ki.wScan = app._user32.MapVirtualKeyW(item.ki.wVk, 0)
            app._send_inputs(inputs)
            if not stopped.wait(2):
                raise AssertionError("Real stop chord was not received during typing pause")
            listener.resume_hotkeys()
        finally:
            app.keyboard.release("x")
            app.keyboard.release("shift")
            app.keyboard.release("ctrl")
            listener.stop()
            listener.join(5)
        if listener.is_alive():
            raise AssertionError("Hotkey listener did not exit")
    print("PASS: real Ctrl+Shift+X remains active while start hotkey is paused")


def app_windows():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    windows = set()

    @callback_type
    def visit(hwnd, _param):
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == "自动输入助手":
            windows.add(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return windows


def check_exe_config_restarts():
    exe = Path(__file__).resolve().parents[1] / "dist" / "AutoInputHelper.exe"
    if not exe.is_file():
        raise AssertionError("Build dist/AutoInputHelper.exe before running this check")
    expected = {
        "start_delay": 1.7,
        "char_interval": 0.013,
        "tab_size": 2,
        "expand_tabs": False,
        "code_mode": False,
        "cached_text": "持久化检查\n    value = 42",
    }
    with tempfile.TemporaryDirectory(prefix="input-helper-smoke-") as temporary:
        root = Path(temporary)
        profile = root / "profile"
        config = profile / "InputHelper" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
        for run in (1, 2):
            extraction = root / f"extraction-{run}"
            extraction.mkdir()
            env = dict(os.environ, LOCALAPPDATA=str(profile), TEMP=str(extraction), TMP=str(extraction))
            previous_windows = app_windows()
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.Popen([str(exe)], cwd=extraction, env=env, startupinfo=startup)
            try:
                deadline = time.monotonic() + 20
                new_windows = set()
                while time.monotonic() < deadline:
                    new_windows = app_windows() - previous_windows
                    if new_windows:
                        break
                    if process.poll() is not None:
                        raise AssertionError(f"EXE exited before opening a window: {process.returncode}")
                    time.sleep(0.05)
                if len(new_windows) != 1:
                    raise AssertionError(f"Expected one new app window, got {len(new_windows)}")
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                if not user32.PostMessageW(new_windows.pop(), 0x0010, 0, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
                if process.wait(timeout=10) != 0:
                    raise AssertionError(f"EXE exited with {process.returncode}")
            finally:
                if process.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True)
                    process.wait(timeout=10)
            actual = json.loads(config.read_text(encoding="utf-8"))
            if actual != expected:
                raise AssertionError(f"Saved config was not restored on run {run}: {actual!r}")
            print(f"PASS: EXE run {run} restores and saves Chinese text and settings outside its extraction directory")


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("This smoke check requires Windows")
    check_real_stop_hotkey()
    check_exe_config_restarts()
