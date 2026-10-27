import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class FakeText:
    def __init__(self, value=""):
        self.value = value

    def get(self, *_args):
        return self.value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _where, value):
        self.value += value


def bare_app():
    instance = object.__new__(app.InputHelperApp)
    tcl = app.tk.Tcl()
    instance.delay_var = app.tk.DoubleVar(tcl, value=0.8)
    instance.interval_var = app.tk.DoubleVar(tcl, value=0.05)
    instance.tab_size_var = app.tk.IntVar(tcl, value=4)
    instance.expand_tabs_var = app.tk.BooleanVar(tcl, value=True)
    instance.code_mode_var = app.tk.BooleanVar(tcl, value=True)
    instance.textbox = FakeText()
    instance.stop_typing_event = threading.Event()
    instance.typing_thread = None
    instance.hotkey_listener = None
    instance.root = type("Root", (), {"after": lambda self, *_args: None})()
    instance.status_var = app.tk.StringVar(tcl, value="ready")
    instance.set_status = lambda value: instance.status_var.set(value)
    return instance


class HotkeyRegistry:
    def __init__(self):
        self.handlers = {}
        self.next_handle = 0

    def add(self, chord, callback, **_kwargs):
        self.next_handle += 1
        self.handlers[self.next_handle] = (chord, callback)
        return self.next_handle

    def remove(self, handle):
        del self.handlers[handle]

    def trigger(self, chord):
        for registered_chord, callback in list(self.handlers.values()):
            if registered_chord == chord:
                callback()
                return True
        return False


class RuntimeTests(unittest.TestCase):
    def test_frozen_config_path_uses_local_appdata_and_never_bundle_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "roaming-root"
            bundle = Path(temp) / "bundle"
            with patch.object(app.sys, "frozen", True, create=True), \
                    patch.object(app.sys, "_MEIPASS", str(bundle), create=True), \
                    patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
                path = app.get_config_path()
            self.assertEqual(local / "InputHelper" / "config.json", path)
            self.assertNotIn("_MEIPASS", str(path))

    def test_frozen_config_path_falls_back_for_missing_or_empty_localappdata(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with patch.object(app.sys, "frozen", True, create=True), \
                    patch.object(Path, "home", return_value=home), \
                    patch.dict(os.environ, {}, clear=True):
                missing = app.get_config_path()
            with patch.object(app.sys, "frozen", True, create=True), \
                    patch.object(Path, "home", return_value=home), \
                    patch.dict(os.environ, {"LOCALAPPDATA": ""}, clear=True):
                empty = app.get_config_path()
            expected = home / "AppData" / "Local" / "InputHelper" / "config.json"
            self.assertEqual(expected, missing)
            self.assertEqual(expected, empty)

    def test_source_config_path_is_next_to_app_module(self):
        with patch.object(app.sys, "frozen", False, create=True):
            self.assertEqual(Path(app.__file__).with_name("config.json"), app.get_config_path())

    def test_config_round_trip_creates_nested_path_and_preserves_values(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app, "CONFIG_PATH", Path(temp) / "nested" / "deep" / "config.json"):
            first = bare_app()
            first.delay_var.set(1.7)
            first.interval_var.set(0.013)
            first.tab_size_var.set(2)
            first.expand_tabs_var.set(False)
            first.code_mode_var.set(False)
            first.textbox.value = "中文内容\n    参数 = 42"
            first.save_config()

            second = bare_app()
            second.load_config()
            self.assertEqual(1.7, second.delay_var.get())
            self.assertAlmostEqual(0.013, second.interval_var.get())
            self.assertEqual(2, second.tab_size_var.get())
            self.assertFalse(second.expand_tabs_var.get())
            self.assertFalse(second.code_mode_var.get())
            self.assertEqual(first.textbox.value, second.textbox.value)

    def test_failed_save_does_not_replace_existing_config_and_reports_status(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app, "CONFIG_PATH", Path(temp) / "config.json"):
            target = app.CONFIG_PATH
            target.write_text("old config", encoding="utf-8")
            instance = bare_app()
            with patch.object(Path, "replace", side_effect=OSError("disk error")):
                instance.save_config()
            self.assertEqual("old config", target.read_text(encoding="utf-8"))
            self.assertNotEqual("ready", instance.status_var.get())

    def test_pause_keeps_stop_hotkey_live_and_resume_has_one_of_each(self):
        registry = HotkeyRegistry()
        stopped = []
        listener = app.HotkeyListener(lambda: None, lambda: stopped.append(True), lambda _status: None)
        with patch.object(app.keyboard, "add_hotkey", registry.add), patch.object(app.keyboard, "remove_hotkey", registry.remove):
            listener._register()
            listener.pause_hotkeys()
            self.assertFalse(registry.trigger("ctrl+shift+q"))
            self.assertTrue(registry.trigger("ctrl+shift+x"))
            self.assertEqual([True], stopped)
            listener.resume_hotkeys()
            chords = [chord for chord, _callback in registry.handlers.values()]
            self.assertEqual(1, chords.count("ctrl+shift+q"))
            self.assertEqual(1, chords.count("ctrl+shift+x"))
            listener._unregister()
            exiting_listener = app.HotkeyListener(lambda: None, lambda: None, lambda _status: None)
            exiting_listener.start()
            deadline = time.monotonic() + 1
            while len(registry.handlers) != 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            exiting_listener.stop()
            exiting_listener.join(timeout=1)
            self.assertFalse(exiting_listener.is_alive())
            self.assertEqual({}, registry.handlers)

    def test_worker_stop_interrupts_start_countdown(self):
        instance = bare_app()
        instance.stop_typing_event.clear()
        entered = threading.Event()
        sent = []

        def run_worker():
            entered.set()
            instance.type_text_worker("abc", 1, 0, 4, False)

        with patch.object(app, "send_unicode_text", sent.append):
            worker = threading.Thread(target=run_worker)
            worker.start()
            try:
                self.assertTrue(entered.wait(0.5))
                instance.stop_typing_event.set()
                worker.join(0.2)
                self.assertFalse(worker.is_alive(), "worker should wake promptly when stopped during countdown")
                self.assertEqual([], sent)
            finally:
                instance.stop_typing_event.set()
                worker.join(2)

    def test_worker_stop_interrupts_per_character_wait(self):
        instance = bare_app()
        sent = []
        entered = threading.Event()

        def send_character(character):
            sent.append(character)
            if character == "a":
                entered.set()

        with patch.object(app, "send_unicode_text", send_character):
            worker = threading.Thread(target=lambda: instance.type_text_worker("ab", 0, 1, 4, False))
            worker.start()
            try:
                self.assertTrue(entered.wait(0.5))
                instance.stop_typing_event.set()
                worker.join(0.2)
                self.assertFalse(worker.is_alive(), "worker should wake promptly during character interval")
                self.assertEqual(["a"], sent)
            finally:
                instance.stop_typing_event.set()
                worker.join(2)

    def test_stop_hotkey_sets_event_before_ui_callback_is_processed(self):
        instance = bare_app()
        callbacks = []
        instance.root.after = lambda *args: callbacks.append(args)
        with patch.object(app.HotkeyListener, "start"):
            instance.start_hotkeys()
        instance.hotkey_listener.on_stop_hotkey()
        self.assertTrue(instance.stop_typing_event.is_set())
        self.assertEqual(1, len(callbacks))

    def test_zero_interval_input_still_checks_stop_between_characters(self):
        instance = bare_app()
        sent = []

        def send_and_stop(text):
            sent.append(text)
            instance.stop_typing_event.set()

        with patch.object(app, "send_unicode_text", send_and_stop):
            instance.type_text_chunk("abc", interval=0)
        self.assertEqual(["a"], sent)

    def test_stop_during_newline_does_not_select_or_replace_next_line(self):
        for stop_key in (app._VK_ESCAPE, app._VK_RETURN):
            with self.subTest(stop_key=stop_key):
                instance = bare_app()
                sent = []

                def tap_and_stop(vk):
                    if vk == stop_key:
                        instance.stop_typing_event.set()

                with patch.object(app, "send_unicode_text", sent.append), \
                        patch.object(app, "send_vk_tap", tap_and_stop), \
                        patch.object(app, "select_to_line_start") as select:
                    instance.type_code_text("first\nsecond", interval=0, tab_size=4)
                self.assertEqual(list("first"), sent)
                select.assert_not_called()

    def test_stop_on_empty_line_placeholder_does_not_send_backspace(self):
        instance = bare_app()
        keys = []

        def stop_on_placeholder(text):
            if text == " ":
                instance.stop_typing_event.set()

        with patch.object(app, "send_unicode_text", stop_on_placeholder), \
                patch.object(app, "send_vk_tap", keys.append), \
                patch.object(app, "select_to_line_start"):
            instance.type_code_text("first\n", interval=0, tab_size=4)
        self.assertNotIn(app._VK_BACK, keys)


if __name__ == "__main__":
    unittest.main()
