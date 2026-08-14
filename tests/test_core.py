import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import uiautomation as auto

from win_use import actions, apps, cache, dispatch, reader, selectors, utils


class FakeRect:
    def __init__(self, x=10, y=20, width=300, height=200):
        self.left = x
        self.top = y
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeWindowPattern:
    def __init__(self, state=0):
        self.WindowVisualState = state
        self.states = []

    def SetWindowVisualState(self, state):
        self.WindowVisualState = state
        self.states.append(state)

    def SetFocus(self):
        return None


class FakeControl:
    _next_runtime_id = 1

    def __init__(
        self,
        name,
        control_type="PaneControl",
        class_name="",
        automation_id="",
        handle=0,
        bounds=None,
        children=None,
        pattern_ids=None,
        window_state=None,
    ):
        self.Name = name
        self.ControlTypeName = control_type
        self.ClassName = class_name
        self.AutomationId = automation_id
        self.NativeWindowHandle = handle
        self.BoundingRectangle = bounds or FakeRect()
        self.IsEnabled = True
        self.IsOffscreen = False
        self.children = children or []
        self.pattern_ids = set(pattern_ids or [])
        self.window_pattern = (
            FakeWindowPattern(window_state) if window_state is not None else None
        )
        self.runtime_id = (42, FakeControl._next_runtime_id)
        FakeControl._next_runtime_id += 1
        self.focused = False

    def GetChildren(self):
        return self.children

    def GetRuntimeId(self):
        return self.runtime_id

    def GetPattern(self, pattern_id):
        return object() if pattern_id in self.pattern_ids else None

    def GetWindowPattern(self):
        return self.window_pattern

    def SetFocus(self):
        self.focused = True


def make_tree(window_state=0):
    button = FakeControl(
        "保存",
        control_type="ButtonControl",
        automation_id="save",
        pattern_ids=[auto.PatternId.InvokePattern],
        bounds=FakeRect(100, 120, 80, 30),
    )
    pane = FakeControl("container", children=[button])
    window = FakeControl(
        "编辑器",
        control_type="WindowControl",
        class_name="EditorWindow",
        handle=123,
        children=[pane],
        window_state=window_state,
        bounds=FakeRect(0, 0, 800, 600),
    )
    return window, pane, button


class UtilsTests(unittest.TestCase):
    def test_minimized_window_is_meaningful_and_matches_class(self):
        window, _, _ = make_tree(window_state=2)
        self.assertTrue(utils.is_meaningful_window(window))
        self.assertEqual("Button", utils.safe_type(window.children[0].children[0]))
        self.assertEqual((True, "class_name"), utils.window_matches(window, "editorwindow"))

    def test_supported_patterns_use_get_pattern_api(self):
        _, _, button = make_tree()
        self.assertEqual(["Invoke"], utils.get_supported_patterns(button))


class ReaderTests(unittest.TestCase):
    def _read(self, window, mode, query=None):
        with (
            patch.object(reader, "get_top_level_windows", return_value=[window]),
            patch.object(reader, "get_active_window", return_value=window),
            patch.object(reader, "get_screen_size", return_value=(1920, 1080)),
        ):
            return reader.read_screen(
                windows=[query] if query else None,
                max_depth=4,
                mode=mode,
            )

    def test_full_and_compact_modes(self):
        window, _, _ = make_tree()
        full = self._read(window, "full")
        compact = self._read(window, "compact")

        self.assertEqual(3, full["element_count"])
        self.assertEqual(2, compact["element_count"])
        self.assertEqual([2], compact["elements"][0]["children"])
        self.assertEqual(["Invoke"], compact["elements"][1]["patterns"])

    def test_reader_uses_shared_class_name_matching(self):
        window, _, _ = make_tree()
        data = self._read(window, "full", query="editorwindow")
        self.assertEqual(3, data["element_count"])


class AppsTests(unittest.TestCase):
    def test_find_and_focus_minimized_window(self):
        window, _, _ = make_tree(window_state=2)
        with (
            patch.object(apps, "get_top_level_windows", return_value=[window]),
            patch.object(apps.auto, "SetForegroundWindow"),
            patch.object(apps.time, "sleep"),
        ):
            result = apps.focus_window("EditorWindow", timeout=0)

        self.assertEqual("class_name", result["matched_field"])
        self.assertEqual([0], window.window_pattern.states)
        self.assertTrue(window.focused)


class CacheAndActionTests(unittest.TestCase):
    def test_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "cache.json")
            with patch.dict(os.environ, {"WIN_USE_CACHE_PATH": path}):
                cache.save_elements_cache([
                    {
                        "id": 7,
                        "bounds": {"x": 1, "y": 2, "w": 3, "h": 4},
                        "name": "保存",
                        "type": "Button",
                        "_locator": {"path": [0, 0]},
                    }
                ])
                loaded = cache.load_elements_cache()

        self.assertEqual(7, loaded[7]["id"])
        self.assertEqual({"path": [0, 0]}, loaded[7]["locator"])

    def test_build_memory_cache(self):
        mem = cache.build_memory_cache([
            {"id": 1, "bounds": {"x": 0, "y": 0, "w": 10, "h": 10}, "name": "A", "type": "Button", "_locator": {"path": [0]}},
            {"id": 2, "bounds": {"x": 5, "y": 5, "w": 20, "h": 20}, "name": "B", "type": "Pane", "_locator": None},
        ])
        self.assertEqual({1, 2}, set(mem))
        self.assertEqual("A", mem[1]["name"])
        self.assertEqual({"path": [0]}, mem[1]["locator"])

    def test_click_uses_resolved_current_bounds(self):
        _, _, button = make_tree()
        cached = {7: {
            "id": 7,
            "bounds": {"x": 1, "y": 2, "w": 3, "h": 4},
            "locator": {"path": [0, 0]},
        }}
        with (
            patch.object(actions, "resolve_element", return_value=button),
            patch.object(actions.auto, "Click") as click,
            patch.object(actions.time, "sleep"),
        ):
            result = actions.click(element_id=7, elements_cache=cached)

        click.assert_called_once_with(140, 135)
        self.assertEqual((140, 135), result["coords"])

    def test_type_text_removes_accidental_outer_quotes_and_pastes_literal_text(self):
        with (
            patch("pyperclip.copy") as copy,
            patch.object(actions.auto, "SendKeys") as send_keys,
            patch.object(actions.time, "sleep"),
        ):
            result = actions.type_text('""长夜无荒""')

        copy.assert_called_once_with("长夜无荒")
        send_keys.assert_called_once_with("{Ctrl}v", waitTime=0.3)
        self.assertEqual(2, result["removed_outer_quote_layers"])
        self.assertEqual("paste", result["method"])

    def test_type_text_can_preserve_outer_quotes(self):
        with (
            patch("pyperclip.copy") as copy,
            patch.object(actions.auto, "SendKeys"),
            patch.object(actions.time, "sleep"),
        ):
            result = actions.type_text('"quoted"', preserve_outer_quotes=True)

        copy.assert_called_once_with('"quoted"')
        self.assertEqual(0, result["removed_outer_quote_layers"])

    def test_normalize_text_supports_curly_quotes(self):
        self.assertEqual(("内容", 1), actions.normalize_text_input("“内容”"))


class SelectorTests(unittest.TestCase):
    def test_find_elements_by_name_and_type(self):
        window, _, button = make_tree()
        with patch.object(selectors, "_roots", return_value=[window]):
            matches = selectors.find_elements({
                "name": "保",
                "type": "Button",
                "match": "contains",
            })
        self.assertEqual([button], matches)

    def test_wait_for_element_polls_until_present(self):
        _, _, button = make_tree()
        with (
            patch.object(selectors, "find_elements", side_effect=[[], [button]]),
            patch.object(selectors.time, "sleep"),
        ):
            result = selectors.wait_for_element({"name": "保存"}, timeout=1)
        self.assertIs(button, result)


class DispatchTests(unittest.TestCase):
    """直接调用 dispatch(cmd, args, ctx) 验证各命令分发。"""

    def test_unknown_command(self):
        ctx = dispatch.LoopContext()
        result = dispatch.dispatch("nope", {}, ctx)
        self.assertFalse(result["success"])
        self.assertEqual("UnknownCommand", result["error_type"])

    def test_read_fills_memory_cache(self):
        window, _, _ = make_tree()
        ctx = dispatch.LoopContext()
        with (
            patch.object(reader, "get_top_level_windows", return_value=[window]),
            patch.object(reader, "get_active_window", return_value=window),
            patch.object(reader, "get_screen_size", return_value=(1920, 1080)),
            patch.object(cache, "save_elements_cache"),
        ):
            result = dispatch.dispatch("read", {"mode": "full"}, ctx)
        self.assertTrue(result["success"])
        self.assertEqual(3, result["element_count"])
        # 内存缓存已填充
        self.assertEqual(3, len(ctx.element_cache))
        self.assertIn(1, ctx.element_cache)

    def test_click_by_id_uses_memory_cache(self):
        _, _, button = make_tree()
        ctx = dispatch.LoopContext()
        ctx.element_cache = {5: {
            "id": 5,
            "bounds": {"x": 100, "y": 120, "w": 80, "h": 30},
            "locator": {"path": [0, 0]},
        }}
        with (
            patch.object(actions, "resolve_element", return_value=button),
            patch.object(actions.auto, "Click") as click,
            patch.object(actions.time, "sleep"),
        ):
            result = dispatch.dispatch("click", {"id": 5}, ctx)
        self.assertTrue(result["success"])
        click.assert_called_once()

    def test_click_by_coords(self):
        ctx = dispatch.LoopContext()
        with (
            patch.object(actions.auto, "Click") as click,
            patch.object(actions.time, "sleep"),
        ):
            result = dispatch.dispatch("click", {"x": 100, "y": 200}, ctx)
        self.assertTrue(result["success"])
        click.assert_called_once_with(100, 200)

    def test_click_without_target(self):
        ctx = dispatch.LoopContext()
        result = dispatch.dispatch("click", {}, ctx)
        self.assertFalse(result["success"])
        self.assertEqual("MissingArgument", result["error_type"])

    def test_click_id_without_cache(self):
        ctx = dispatch.LoopContext()
        result = dispatch.dispatch("click", {"id": 1}, ctx)
        self.assertFalse(result["success"])
        self.assertEqual("CacheEmpty", result["error_type"])

    def test_type_dispatch(self):
        ctx = dispatch.LoopContext()
        with (
            patch("pyperclip.copy"),
            patch.object(actions.auto, "SendKeys"),
            patch.object(actions.time, "sleep"),
        ):
            result = dispatch.dispatch("type", {"text": "hello"}, ctx)
        self.assertTrue(result["success"])
        self.assertEqual("hello", result["text"])

    def test_type_missing_text(self):
        ctx = dispatch.LoopContext()
        result = dispatch.dispatch("type", {}, ctx)
        self.assertFalse(result["success"])

    def test_keys_dispatch(self):
        ctx = dispatch.LoopContext()
        with (
            patch.object(actions.auto, "SendKeys"),
            patch.object(actions.time, "sleep"),
        ):
            result = dispatch.dispatch("keys", {"keys": "{Enter}"}, ctx)
        self.assertTrue(result["success"])
        self.assertEqual("{Enter}", result["keys"])

    def test_wait_dispatch(self):
        ctx = dispatch.LoopContext()
        with patch.object(actions.time, "sleep"):
            result = dispatch.dispatch("wait", {"seconds": 0}, ctx)
        self.assertTrue(result["success"])

    def test_apps_list_dispatch(self):
        window, _, _ = make_tree()
        ctx = dispatch.LoopContext()
        with patch.object(apps, "get_top_level_windows", return_value=[window]):
            result = dispatch.dispatch("apps", {"action": "list"}, ctx)
        self.assertTrue(result["success"])

    def test_apps_unknown_action(self):
        ctx = dispatch.LoopContext()
        result = dispatch.dispatch("apps", {"action": "fly"}, ctx)
        self.assertFalse(result["success"])
        self.assertEqual("UnknownAction", result["error_type"])

    def test_shell_dispatch(self):
        ctx = dispatch.LoopContext()
        result = dispatch.dispatch("shell", {"command": "echo hi"}, ctx)
        self.assertTrue(result["success"])
        self.assertIn("hi", result["stdout"])

    def test_shell_missing_command(self):
        ctx = dispatch.LoopContext()
        result = dispatch.dispatch("shell", {}, ctx)
        self.assertFalse(result["success"])

    def test_dispatch_catches_exceptions(self):
        ctx = dispatch.LoopContext()
        with patch.object(actions, "wait", side_effect=RuntimeError("boom")):
            result = dispatch.dispatch("wait", {"seconds": 1}, ctx)
        self.assertFalse(result["success"])
        self.assertEqual("RuntimeError", result["error_type"])
        self.assertEqual("boom", result["error"])


class ReplProtocolTests(unittest.TestCase):
    """用 StringIO 模拟 stdin/stdout 验证 JSON-lines REPL 往返。"""

    def test_single_command_roundtrip(self):
        import win_use.cli as cli_mod
        stdin = io.StringIO(json.dumps({"cmd": "wait", "args": {"seconds": 0}}) + "\n")
        stdout = io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", stdout),
            patch.object(actions.time, "sleep"),
        ):
            cli_mod.main()
        lines = [l for l in stdout.getvalue().split("\n") if l]
        self.assertEqual(1, len(lines))
        result = json.loads(lines[0])
        self.assertTrue(result["success"])
        self.assertEqual("wait", result["action"])

    def test_multiple_commands(self):
        import win_use.cli as cli_mod
        stdin = io.StringIO(
            json.dumps({"cmd": "wait", "args": {"seconds": 0}}) + "\n"
            + json.dumps({"cmd": "wait", "args": {"seconds": 0}}) + "\n"
        )
        stdout = io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", stdout),
            patch.object(actions.time, "sleep"),
        ):
            cli_mod.main()
        lines = [l for l in stdout.getvalue().split("\n") if l]
        self.assertEqual(2, len(lines))
        for line in lines:
            self.assertTrue(json.loads(line)["success"])

    def test_invalid_json_returns_error(self):
        import win_use.cli as cli_mod
        stdin = io.StringIO("not json\n")
        stdout = io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", stdout),
        ):
            cli_mod.main()
        lines = [l for l in stdout.getvalue().split("\n") if l]
        self.assertEqual(1, len(lines))
        result = json.loads(lines[0])
        self.assertFalse(result["success"])
        self.assertEqual("JSONDecodeError", result["error_type"])

    def test_unknown_command_returns_error(self):
        import win_use.cli as cli_mod
        stdin = io.StringIO(json.dumps({"cmd": "fly", "args": {}}) + "\n")
        stdout = io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", stdout),
        ):
            cli_mod.main()
        lines = [l for l in stdout.getvalue().split("\n") if l]
        result = json.loads(lines[0])
        self.assertFalse(result["success"])
        self.assertEqual("UnknownCommand", result["error_type"])

    def test_empty_lines_skipped(self):
        import win_use.cli as cli_mod
        stdin = io.StringIO("\n\n" + json.dumps({"cmd": "wait", "args": {"seconds": 0}}) + "\n\n")
        stdout = io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", stdout),
            patch.object(actions.time, "sleep"),
        ):
            cli_mod.main()
        lines = [l for l in stdout.getvalue().split("\n") if l]
        self.assertEqual(1, len(lines))

    def test_eof_exits_cleanly(self):
        import win_use.cli as cli_mod
        stdin = io.StringIO("")
        stdout = io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.object(sys, "stdout", stdout),
        ):
            cli_mod.main()
        self.assertEqual("", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
