import threading
import unittest
from unittest.mock import patch

import app


class FakeSmartIndentEditor:
    """Small Educoder-like editor model for the operating-system input boundary."""

    def __init__(self, tab_size=4):
        self.tab_size = tab_size
        self.lines = [""]
        self.line_index = 0
        self.column = 0
        self.selection = None

    @property
    def text(self):
        return "\n".join(self.lines)

    def _replace_selection(self, text):
        if self.selection is None:
            return False
        start, end = sorted(self.selection)
        line = self.lines[self.line_index]
        self.lines[self.line_index] = line[:start] + text + line[end:]
        self.column = start + len(text)
        self.selection = None
        return True

    def write(self, text):
        if self._replace_selection(text):
            return
        line = self.lines[self.line_index]
        self.lines[self.line_index] = line[:self.column] + text + line[self.column:]
        self.column += len(text)

    def select_to_line_start(self):
        self.selection = (0, self.column)

    def send_inputs(self, inputs):
        key_events = [(item.ki.wVk, item.ki.dwFlags) for item in inputs]
        expected = [
            (app._VK_SHIFT, 0),
            (app._VK_HOME, app._KEYEVENTF_EXTENDEDKEY),
            (app._VK_HOME, app._KEYEVENTF_EXTENDEDKEY | app._KEYEVENTF_KEYUP),
            (app._VK_SHIFT, app._KEYEVENTF_KEYUP),
        ]
        if key_events != expected:
            raise AssertionError(f"Unexpected input sequence: {key_events!r}")
        self.select_to_line_start()

    def tap(self, vk, extended=False):
        del extended
        if vk == app._VK_RETURN:
            self._press_enter()
        elif vk == app._VK_BACK:
            self._press_backspace()

    def _press_enter(self):
        if self.selection is not None:
            self._replace_selection("")

        current = self.lines[self.line_index]
        before = current[:self.column]
        after = current[self.column:]
        leading = len(before) - len(before.lstrip(" "))
        if before.rstrip().endswith(":"):
            leading += self.tab_size

        self.lines[self.line_index] = before
        self.line_index += 1
        self.lines.insert(self.line_index, " " * leading + after)
        self.column = leading

    def _press_backspace(self):
        if self.selection is not None:
            self._replace_selection("")
            return

        line = self.lines[self.line_index]
        if self.column > 0:
            if not line[:self.column].strip():
                width = self.column % self.tab_size or self.tab_size
                start = max(0, self.column - width)
            else:
                start = self.column - 1
            self.lines[self.line_index] = line[:start] + line[self.column:]
            self.column = start
            return

        if self.line_index > 0:
            previous = self.lines[self.line_index - 1]
            current = self.lines.pop(self.line_index)
            self.line_index -= 1
            self.column = len(previous)
            self.lines[self.line_index] = previous + current


class FakeAutocompleteEditor(FakeSmartIndentEditor):
    def __init__(self, suggestion="auto", tab_size=4):
        super().__init__(tab_size=tab_size)
        self.suggestion = suggestion

    def tap(self, vk, extended=False):
        if vk == 0x1B:
            self.suggestion = None
            return
        if vk == app._VK_RETURN and self.suggestion:
            suggestion = self.suggestion
            self.suggestion = None
            self.write(suggestion)
            return
        super().tap(vk, extended)


class CodeTypingTests(unittest.TestCase):
    def make_app(self):
        instance = object.__new__(app.InputHelperApp)
        instance.stop_typing_event = threading.Event()
        return instance

    def type_into_fake_editor(self, source, editor=None):
        editor = editor or FakeSmartIndentEditor()
        instance = self.make_app()
        with (
            patch.object(app, "send_unicode_text", editor.write),
            patch.object(app, "send_vk_tap", editor.tap),
            patch.object(app, "_send_inputs", editor.send_inputs),
            patch.object(app.time, "sleep", return_value=None),
        ):
            instance.type_code_text(source, interval=0, tab_size=4)
        return editor

    def test_dedent_never_deletes_or_joins_existing_code(self):
        source = (
            "if ready:\n"
            "    try:\n"
            "        work()\n"
            "    except ValueError:\n"
            "        recover()\n"
            "else:\n"
            "    fallback()"
        )

        editor = self.type_into_fake_editor(source)

        self.assertEqual(source, editor.text)

    def test_blank_line_clears_auto_indent_without_touching_previous_line(self):
        source = "if ready:\n    work()\n\ndone()"

        editor = self.type_into_fake_editor(source)

        self.assertEqual(source, editor.text)
        self.assertIsNone(editor.selection)

    def test_trailing_newline_dismisses_autocomplete_before_pressing_enter(self):
        source = " * @param position 插入位置（从1开始，1表示插入到第一个元素前）\n"

        editor = self.type_into_fake_editor(source, FakeAutocompleteEditor())

        self.assertEqual(source, editor.text)


if __name__ == "__main__":
    unittest.main()
