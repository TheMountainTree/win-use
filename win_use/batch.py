"""在单个 CLI 进程中执行多步 Windows 自动化工作流。"""

import json
import time
from pathlib import Path

from . import apps
from .actions import click, double_click, drag, move_mouse, scroll, send_keys, type_text, wait
from .cache import load_elements_cache, save_elements_cache, strip_internal_fields
from .reader import read_screen
from .screen import screenshot
from .selectors import element_summary, wait_for_element
from .utils import safe_bounds, safe_offscreen


SUPPORTED_ACTIONS = {
    "apps.list", "apps.focus", "apps.launch", "apps.close", "apps.minimize", "apps.maximize",
    "read", "click", "double_click", "type", "keys", "scroll", "move", "drag", "wait",
    "wait_for", "screenshot", "locate_vision",
}

VALID_FIELDS = {
    "apps.launch":    {"name", "timeout", "action"},
    "apps.focus":     {"name", "index", "timeout", "action"},
    "apps.close":     {"name", "index", "action"},
    "apps.minimize":  {"name", "index", "action"},
    "apps.maximize":  {"name", "index", "action"},
    "apps.list":      {"action"},
    "read":           {"window", "active", "depth", "mode", "all", "action"},
    "click":          {"selector", "id", "x", "y", "button", "double", "window", "active", "timeout", "poll_interval", "index", "depth", "settle", "action"},
    "double_click":   {"selector", "id", "x", "y", "button", "window", "active", "timeout", "poll_interval", "index", "depth", "settle", "action"},
    "type":           {"text", "delay", "settle", "preserve_outer_quotes", "action"},
    "keys":           {"keys", "settle", "action"},
    "scroll":         {"direction", "amount", "x", "y", "settle", "action"},
    "move":           {"x", "y", "settle", "action"},
    "drag":           {"from_x", "from_y", "to_x", "to_y", "settle", "action"},
    "wait":           {"seconds", "action"},
    "wait_for":       {"selector", "window", "active", "timeout", "poll_interval", "index", "state", "depth", "action"},
    "screenshot":     {"output", "base64", "quality", "window", "overlay_grid", "action"},
    "locate_vision":  {"window", "target", "model", "api_key", "base_url", "spacing", "action"},
}

TYPO_FIXES = {
    "url": "name",
    "duration": "seconds",
    "sleep": "seconds",
    "textToType": "text",
    "message": "text",
    "content": "text",
    "input": "text",
    "command": "keys",
    "key": "keys",
    "key_combination": "keys",
    "shortcut": "keys",
    "chrome": "window",
    "browser": "window",
    "app": "name",
    "application": "name",
    "title": "name",
    "window_name": "name",
    "windowName": "name",
    "automationId": "selector",
    "className": "selector",
    "target_name": "name",
}


def _validate_step(step: dict, index: int):
    action = step.get("action")
    if not action:
        raise ValueError(f"步骤 {index}: 缺少 action 字段")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(
            f"步骤 {index}: 不支持的 action '{action}'，"
            f"支持: {', '.join(sorted(SUPPORTED_ACTIONS))}"
        )

    if action in VALID_FIELDS:
        for key in list(step.keys()):
            if key in ("index",):
                continue
            if key not in VALID_FIELDS[action]:
                fix = TYPO_FIXES.get(key)
                if fix:
                    raise ValueError(
                        f"步骤 {index} ({action}): 无效字段 '{key}'，"
                        f"你可能想用 '{fix}'"
                    )
                raise ValueError(
                    f"步骤 {index} ({action}): 无效字段 '{key}'，"
                    f"有效字段: {', '.join(sorted(VALID_FIELDS[action]))}"
                )

    if action == "type" and "text" not in step:
        raise ValueError(f"步骤 {index} (type): 缺少 text 字段")
    if action == "keys" and "keys" not in step:
        raise ValueError(f"步骤 {index} (keys): 缺少 keys 字段")
    if action in {"apps.launch", "apps.focus", "apps.close", "apps.minimize", "apps.maximize"} and "name" not in step:
        raise ValueError(f"步骤 {index} ({action}): 缺少 name 字段")
    if action == "wait" and "seconds" not in step:
        raise ValueError(f"步骤 {index} (wait): 缺少 seconds 字段")


def load_workflow(source: str) -> dict | list:
    if source == "-":
        raise ValueError("stdin 工作流应由 CLI 读取后直接传给 execute_batch")
    path = Path(source)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        pass
    return json.loads(source)


def _click_element(element, double: bool = False, button: str = "left", settle: float = 0.05):
    if safe_offscreen(element):
        raise RuntimeError("目标元素当前不在屏幕内")
    x, y, width, height = safe_bounds(element)
    if width <= 0 or height <= 0:
        raise RuntimeError("目标元素当前没有可点击区域")
    coords = (x + width // 2, y + height // 2)
    if double:
        return double_click(coords=coords, settle=settle)
    return click(coords=coords, button=button, settle=settle)


def _selector_target(step: dict, default_timeout: float):
    selector = step.get("selector")
    if not isinstance(selector, dict) or not selector:
        raise ValueError("该步骤需要非空 selector")
    return wait_for_element(
        selector=selector,
        window=step.get("window"),
        active=step.get("active", step.get("window") is None),
        timeout=float(step.get("timeout", default_timeout)),
        poll_interval=float(step.get("poll_interval", 0.1)),
        index=int(step.get("index", 0)),
        max_depth=int(step.get("depth", 8)),
    )


def run_step(step: dict, default_timeout: float = 5.0, default_settle: float = 0.05):
    action = step.get("action")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"不支持的 batch action: {action}")
    settle = float(step.get("settle", default_settle))

    if action == "apps.list":
        return {"windows": apps.list_windows()}
    if action == "apps.focus":
        return apps.focus_window(
            step["name"], index=int(step.get("index", 0)),
            timeout=float(step.get("timeout", default_timeout)),
        )
    if action == "apps.launch":
        return apps.launch_app(step["name"], timeout=float(step.get("timeout", default_timeout)))
    if action == "apps.close":
        return apps.close_window(step["name"], index=int(step.get("index", 0)))
    if action == "apps.minimize":
        return apps.minimize_window(step["name"], index=int(step.get("index", 0)))
    if action == "apps.maximize":
        return apps.maximize_window(step["name"], index=int(step.get("index", 0)))

    if action == "read":
        data = read_screen(
            windows=[step["window"]] if step.get("window") else None,
            active_only=bool(step.get("active", False)),
            max_depth=int(step.get("depth", 4)),
            include_all=bool(step.get("all", False)),
            mode=step.get("mode", "compact"),
        )
        save_elements_cache(data["elements"])
        return strip_internal_fields(data)

    if action in {"click", "double_click"}:
        if step.get("selector"):
            target = _selector_target(step, default_timeout)
            result = _click_element(
                target,
                double=action == "double_click",
                button=step.get("button", "left"),
                settle=settle,
            )
            result["element"] = element_summary(target)
            return result
        if "id" in step:
            cache = load_elements_cache()
            if action == "double_click":
                return double_click(element_id=int(step["id"]), elements_cache=cache, settle=settle)
            return click(
                element_id=int(step["id"]), elements_cache=cache,
                button=step.get("button", "left"), settle=settle,
            )
        coords = (int(step["x"]), int(step["y"]))
        if action == "double_click":
            return double_click(coords=coords, settle=settle)
        return click(coords=coords, button=step.get("button", "left"), settle=settle)

    if action == "type":
        return type_text(
            step["text"],
            delay=int(step.get("delay", 0)),
            settle=settle,
            preserve_outer_quotes=bool(step.get("preserve_outer_quotes", False)),
        )
    if action == "keys":
        return send_keys(step["keys"], settle=settle)
    if action == "scroll":
        coords = None
        if "x" in step and "y" in step:
            coords = (int(step["x"]), int(step["y"]))
        return scroll(
            direction=step.get("direction", "down"),
            amount=int(step.get("amount", 300)),
            coords=coords,
            settle=settle,
        )
    if action == "move":
        return move_mouse((int(step["x"]), int(step["y"])), settle=settle)
    if action == "drag":
        return drag(
            (int(step["from_x"]), int(step["from_y"])),
            (int(step["to_x"]), int(step["to_y"])),
            settle=settle,
        )
    if action == "wait":
        return wait(float(step.get("seconds", 1.0)))
    if action == "wait_for":
        state = step.get("state", "present")
        selector = step.get("selector")
        if not isinstance(selector, dict) or not selector:
            raise ValueError("wait_for 需要非空 selector")
        target = wait_for_element(
            selector=selector,
            window=step.get("window"),
            active=step.get("active", step.get("window") is None),
            timeout=float(step.get("timeout", default_timeout)),
            poll_interval=float(step.get("poll_interval", 0.1)),
            index=int(step.get("index", 0)),
            state=state,
            max_depth=int(step.get("depth", 8)),
        )
        return {
            "action": "wait_for",
            "state": state,
            "element": element_summary(target) if target is not None else None,
        }
    if action == "screenshot":
        overlay = step.get("overlay_grid")
        if isinstance(overlay, bool) and not overlay:
            overlay = False
        return screenshot(
            output_file=step.get("output"),
            to_base64=bool(step.get("base64", False)),
            quality=int(step.get("quality", 85)),
            window_name=step.get("window"),
            overlay_grid=overlay if overlay else False,
        )
    if action == "locate_vision":
        from .vision import locate_element
        return locate_element(
            window_name=step["window"],
            target_description=step["target"],
            model=step.get("model", "gpt-4o"),
            api_key=step.get("api_key"),
            base_url=step.get("base_url"),
            overlay_spacing=int(step.get("spacing", 150)),
        )
    raise AssertionError(f"未实现的 batch action: {action}")


def execute_batch(workflow: dict | list) -> dict:
    if isinstance(workflow, list):
        workflow = {"steps": workflow}
    if not isinstance(workflow, dict) or not isinstance(workflow.get("steps"), list):
        raise ValueError("batch 工作流必须是步骤列表，或包含 steps 列表的对象")

    default_timeout = float(workflow.get("default_timeout", 5.0))
    default_settle = float(workflow.get("default_settle", 0.05))
    continue_on_error = bool(workflow.get("continue_on_error", False))

    for index, step in enumerate(workflow["steps"]):
        if isinstance(step, dict):
            _validate_step(step, index)

    started = time.perf_counter()
    step_results = []
    success = True

    for index, step in enumerate(workflow["steps"]):
        step_started = time.perf_counter()
        action = step.get("action") if isinstance(step, dict) else None
        try:
            if not isinstance(step, dict):
                raise ValueError("步骤必须是 JSON 对象")
            result = run_step(step, default_timeout=default_timeout, default_settle=default_settle)
            step_results.append({
                "index": index,
                "action": action,
                "success": True,
                "elapsed_ms": round((time.perf_counter() - step_started) * 1000, 1),
                "result": result,
            })
        except Exception as exc:
            success = False
            step_results.append({
                "index": index,
                "action": action,
                "success": False,
                "elapsed_ms": round((time.perf_counter() - step_started) * 1000, 1),
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            if not continue_on_error:
                break

    return {
        "success": success,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "completed_steps": len(step_results),
        "total_steps": len(workflow["steps"]),
        "steps": step_results,
    }
