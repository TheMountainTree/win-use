"""直接查询 UIA 窗口和元素，供批处理与条件等待使用。"""

import time
from collections import deque

from .utils import (
    get_active_window,
    get_top_level_windows,
    is_meaningful_window,
    safe_automation_id,
    safe_bounds,
    safe_children,
    safe_class_name,
    safe_enabled,
    safe_name,
    safe_offscreen,
    safe_type,
    window_matches,
)


def element_summary(element) -> dict:
    bounds = safe_bounds(element)
    return {
        "type": safe_type(element),
        "name": safe_name(element),
        "automation_id": safe_automation_id(element),
        "class_name": safe_class_name(element),
        "bounds": {"x": bounds[0], "y": bounds[1], "w": bounds[2], "h": bounds[3]},
        "enabled": safe_enabled(element),
        "offscreen": safe_offscreen(element),
    }


def find_windows(query: str | None = None) -> list:
    windows = [window for window in get_top_level_windows() if is_meaningful_window(window)]
    if query is None:
        return windows
    return [window for window in windows if window_matches(window, query)[0]]


def iter_elements(root, max_depth: int = 8):
    queue = deque([(root, 0)])
    while queue:
        element, depth = queue.popleft()
        yield element
        if depth < max_depth:
            queue.extend((child, depth + 1) for child in safe_children(element))


def _text_matches(actual: str, expected: str, match: str) -> bool:
    actual_folded = actual.casefold()
    expected_folded = expected.casefold()
    if match == "exact":
        return actual_folded == expected_folded
    if match == "starts_with":
        return actual_folded.startswith(expected_folded)
    if match == "ends_with":
        return actual_folded.endswith(expected_folded)
    return expected_folded in actual_folded


def element_matches(element, selector: dict) -> bool:
    """匹配 name/automation_id/class_name/type/enabled/visible。"""
    match = selector.get("match", "contains")
    for key, getter in (
        ("name", safe_name),
        ("automation_id", safe_automation_id),
        ("class_name", safe_class_name),
    ):
        expected = selector.get(key)
        if expected is not None and not _text_matches(getter(element), str(expected), match):
            return False

    expected_type = selector.get("type")
    if expected_type is not None and safe_type(element).casefold() != str(expected_type).casefold():
        return False
    if "enabled" in selector and safe_enabled(element) != bool(selector["enabled"]):
        return False
    if selector.get("visible", True) and safe_offscreen(element):
        return False
    return True


def _roots(window: str | None, active: bool) -> list:
    if window:
        return find_windows(window)
    if active:
        active_window = get_active_window()
        return [active_window] if active_window is not None else []
    return find_windows()


def find_elements(
    selector: dict,
    window: str | None = None,
    active: bool = True,
    max_depth: int = 8,
) -> list:
    matches = []
    for root in _roots(window, active):
        matches.extend(
            element for element in iter_elements(root, max_depth)
            if element_matches(element, selector)
        )
    return matches


def wait_for_element(
    selector: dict,
    window: str | None = None,
    active: bool = True,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
    index: int = 0,
    state: str = "present",
    max_depth: int = 8,
):
    """等待元素出现或消失。出现时返回目标元素，消失时返回 None。"""
    if state not in {"present", "absent"}:
        raise ValueError("state 必须是 present 或 absent")
    deadline = time.monotonic() + max(0, timeout)

    while True:
        matches = find_elements(
            selector=selector,
            window=window,
            active=active,
            max_depth=max_depth,
        )
        if state == "absent" and not matches:
            return None
        if state == "present" and len(matches) > index:
            return matches[index]
        if time.monotonic() >= deadline:
            if state == "absent":
                raise TimeoutError(f"等待元素消失超时: {selector}")
            raise TimeoutError(f"等待元素出现超时: {selector}，仅匹配到 {len(matches)} 个")
        time.sleep(max(0.01, poll_interval))
