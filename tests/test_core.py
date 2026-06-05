import os
import tempfile
import unittest
from unittest.mock import patch

import uiautomation as auto
from typer.testing import CliRunner

from win_use import actions, apps, batch, cache, cli, reader, selectors, utils


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


class BatchTests(unittest.TestCase):
    def test_execute_batch_returns_structured_step_results(self):
        workflow = {"steps": [{"action": "keys", "keys": "{Enter}"}, {"action": "wait", "seconds": 0}]}
        with patch.object(batch, "run_step", side_effect=[{"action": "keys"}, {"action": "wait"}]):
            result = batch.execute_batch(workflow)
        self.assertTrue(result["success"])
        self.assertEqual(2, result["completed_steps"])
        self.assertTrue(result["steps"][0]["success"])
        self.assertIn("elapsed_ms", result["steps"][0])

    def test_execute_batch_stops_on_error(self):
        workflow = {"steps": [{"action": "keys", "keys": "{Enter}"}, {"action": "wait", "seconds": 0}]}
        with patch.object(batch, "run_step", side_effect=RuntimeError("failed")):
            result = batch.execute_batch(workflow)
        self.assertFalse(result["success"])
        self.assertEqual(1, result["completed_steps"])
        self.assertEqual("RuntimeError", result["steps"][0]["error_type"])

    def test_selector_click_waits_and_returns_element(self):
        _, _, button = make_tree()
        with (
            patch.object(batch, "wait_for_element", return_value=button),
            patch.object(batch, "_click_element", return_value={"success": True, "action": "click"}),
        ):
            result = batch.run_step({
                "action": "click",
                "selector": {"name": "保存"},
            })
        self.assertTrue(result["success"])
        self.assertEqual("保存", result["element"]["name"])


class CliTests(unittest.TestCase):
    def test_type_stdin_removes_pipe_newline(self):
        runner = CliRunner()
        with patch.object(actions, "type_text", return_value={"success": True}) as type_text:
            result = runner.invoke(cli.app, ["type", "--stdin"], input='"搜索词"\n')

        self.assertEqual(0, result.exit_code)
        type_text.assert_called_once_with(
            '"搜索词"',
            delay=0,
            preserve_outer_quotes=False,
        )

    def test_type_stdin_can_preserve_newline(self):
        runner = CliRunner()
        with patch.object(actions, "type_text", return_value={"success": True}) as type_text:
            result = runner.invoke(
                cli.app,
                ["type", "--stdin", "--preserve-stdin-newline"],
                input="两行\n",
            )

        self.assertEqual(0, result.exit_code)
        type_text.assert_called_once_with(
            "两行\n",
            delay=0,
            preserve_outer_quotes=False,
        )


if __name__ == "__main__":
    unittest.main()
