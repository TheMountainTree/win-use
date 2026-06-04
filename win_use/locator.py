"""根据持久化 locator 在最新 UIA 树中重新定位元素。"""

from collections import deque

import uiautomation as auto

from .utils import (
    get_top_level_windows,
    is_meaningful_window,
    safe_automation_id,
    safe_class_name,
    safe_name,
    safe_native_handle,
    safe_runtime_id,
    safe_type,
)


def make_locator(element, window, path: list[int]) -> dict:
    return {
        "window": {
            "native_window_handle": safe_native_handle(window),
            "name": safe_name(window),
            "class_name": safe_class_name(window),
            "automation_id": safe_automation_id(window),
        },
        "path": path,
        "runtime_id": safe_runtime_id(element),
        "name": safe_name(element),
        "class_name": safe_class_name(element),
        "automation_id": safe_automation_id(element),
        "type": safe_type(element),
    }


def _same_element(element, locator: dict) -> bool:
    runtime_id = locator.get("runtime_id") or []
    if runtime_id and safe_runtime_id(element) == runtime_id:
        return True

    expected_type = locator.get("type", "Unknown")
    if safe_type(element) != expected_type:
        return False
    automation_id = locator.get("automation_id", "")
    if automation_id:
        return safe_automation_id(element) == automation_id
    name = locator.get("name", "")
    class_name = locator.get("class_name", "")
    if name:
        return safe_name(element) == name and (
            not class_name or safe_class_name(element) == class_name
        )
    return bool(class_name and safe_class_name(element) == class_name)


def _resolve_window(window_locator: dict):
    handle = int(window_locator.get("native_window_handle") or 0)
    if handle:
        try:
            window = auto.ControlFromHandle(handle)
            if window is not None:
                return window
        except Exception:
            pass

    candidates = [w for w in get_top_level_windows() if is_meaningful_window(w)]
    for field, getter in (
        ("automation_id", safe_automation_id),
        ("name", safe_name),
        ("class_name", safe_class_name),
    ):
        expected = window_locator.get(field, "")
        if expected:
            for candidate in candidates:
                if getter(candidate) == expected:
                    return candidate
    return None


def resolve_element(locator: dict, max_nodes: int = 5000):
    """先按原树路径定位，结构变化时再在目标窗口内广度搜索。"""
    if not locator:
        return None
    window = _resolve_window(locator.get("window", {}))
    if window is None:
        return None

    candidate = window
    try:
        for child_index in locator.get("path", []):
            candidate = candidate.GetChildren()[child_index]
        if _same_element(candidate, locator):
            return candidate
    except (IndexError, TypeError, AttributeError):
        pass
    except Exception:
        pass

    queue = deque([window])
    visited = 0
    while queue and visited < max_nodes:
        candidate = queue.popleft()
        visited += 1
        if _same_element(candidate, locator):
            return candidate
        try:
            queue.extend(candidate.GetChildren())
        except Exception:
            continue
    return None
