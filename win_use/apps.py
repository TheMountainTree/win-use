"""窗口管理：列出、切换、启动应用"""

import logging
import subprocess
import time
import uiautomation as auto
from .utils import (
    get_active_window,
    get_top_level_windows,
    safe_name,
    safe_class_name,
    safe_automation_id,
    safe_identifiers,
    safe_native_handle,
    get_window_state,
    is_meaningful_window,
    window_matches,
)

logger = logging.getLogger(__name__)


def _find_windows(name_substring: str, timeout: float = 2.0):
    """
    按多字段模糊匹配查找窗口。返回匹配窗口列表。

    匹配优先级：Name > AutomationId > ClassName
    """
    deadline = time.monotonic() + max(0, timeout)
    while True:
        matches = []
        for w in get_top_level_windows():
            if not is_meaningful_window(w):
                continue
            try:
                matched, matched_field = window_matches(w, name_substring)
                if matched:
                    ids = safe_identifiers(w)
                    matches.append({
                        "element": w,
                        "name": ids["name"],
                        "class_name": ids["class_name"],
                        "automation_id": ids["automation_id"],
                        "matched_field": matched_field,
                    })
            except Exception as exc:
                logger.warning("读取候选窗口属性失败: %s", exc)
        if matches or time.monotonic() >= deadline:
            return matches
        time.sleep(0.15)


def list_windows():
    """列出所有有意义的顶层窗口"""
    windows = []
    active = get_active_window()
    active_handle = safe_native_handle(active) if active is not None else 0

    for i, w in enumerate(get_top_level_windows()):
        if not is_meaningful_window(w):
            continue
        windows.append({
            "id": i,
            "name": safe_name(w),
            "class_name": safe_class_name(w),
            "automation_id": safe_automation_id(w),
            "native_window_handle": safe_native_handle(w),
            "state": get_window_state(w),
            "active": bool(active_handle and safe_native_handle(w) == active_handle),
        })

    return windows


def focus_window(name_substring: str, index: int = 0, timeout: float = 2.0):
    """
    按名称/ClassName/AutomationId 模糊匹配，将窗口置为前台。

    Args:
        name_substring: 匹配字符串（同时匹配 Name、ClassName、AutomationId）
        index: 当有多个匹配时，选择第几个（0-based）
    """
    matches = _find_windows(name_substring, timeout=timeout)

    if not matches:
        raise ValueError(f"未找到匹配 '{name_substring}' 的窗口（已尝试 Name、AutomationId、ClassName）")

    if index >= len(matches):
        raise ValueError(f"匹配到 {len(matches)} 个窗口，但 index={index} 超出范围，有效范围 0-{len(matches) - 1}")

    w = matches[index]["element"]
    wp = w.GetWindowPattern()
    handle = safe_native_handle(w)
    if wp:
        if get_window_state(w) == "minimized":
            wp.SetWindowVisualState(0)  # Normal
            time.sleep(0.2)
    if not wp and not handle:
        raise RuntimeError(f"窗口 '{safe_name(w)}' 不支持 WindowPattern 且没有原生窗口句柄")

    focus_error = None
    try:
        w.SetFocus()
    except Exception as exc:
        focus_error = exc
        if wp:
            try:
                wp.SetFocus()
                focus_error = None
            except Exception as pattern_exc:
                focus_error = pattern_exc
    if handle:
        try:
            auto.SetForegroundWindow(handle)
            focus_error = None
        except Exception as exc:
            logger.debug("SetForegroundWindow(%s) 失败: %s", handle, exc)
            if focus_error is None:
                focus_error = exc
    if focus_error is not None:
        raise RuntimeError(f"窗口 '{safe_name(w)}' 无法置于前台: {focus_error}") from focus_error
    time.sleep(0.4)
    return {
        "success": True,
        "action": "focus",
        "name": safe_name(w),
        "match_count": len(matches),
        "selected_index": index,
        "matched_field": matches[index]["matched_field"],
    }


def launch_app(app_name: str, timeout: float = 5.0):
    """
    启动应用。

    支持：
        - 系统应用名："notepad", "calc", "mspaint"
        - 可执行文件名："notepad.exe", "calc.exe"
        - 全路径
    """
    try:
        before = {safe_native_handle(w) for w in get_top_level_windows()}
        subprocess.Popen(app_name, shell=True)
        deadline = time.monotonic() + max(0, timeout)
        new_windows = []
        while time.monotonic() < deadline:
            time.sleep(0.2)
            new_windows = [
                w for w in get_top_level_windows()
                if is_meaningful_window(w) and safe_native_handle(w) not in before
            ]
            if new_windows:
                break
        return {
            "success": True,
            "action": "launch",
            "app": app_name,
            "status": "started",
            "new_windows": [safe_name(w) for w in new_windows],
        }
    except Exception as e:
        raise RuntimeError(f"启动 {app_name} 失败: {e}")


def close_window(name_substring: str, index: int = 0):
    """按名称/ClassName/AutomationId 模糊匹配关闭窗口"""
    matches = _find_windows(name_substring)

    if not matches:
        raise ValueError(f"未找到匹配 '{name_substring}' 的窗口")

    if index >= len(matches):
        raise ValueError(f"匹配到 {len(matches)} 个窗口，但 index={index} 超出范围")

    w = matches[index]["element"]
    wp = w.GetWindowPattern()
    if wp:
        wp.Close()
        time.sleep(0.5)
        return {
            "success": True,
            "action": "close",
            "name": safe_name(w),
            "match_count": len(matches),
            "selected_index": index,
        }

    raise RuntimeError(f"窗口 '{safe_name(w)}' 不支持 WindowPattern")


def minimize_window(name_substring: str, index: int = 0):
    """最小化窗口"""
    matches = _find_windows(name_substring)

    if not matches:
        raise ValueError(f"未找到匹配 '{name_substring}' 的窗口")

    if index >= len(matches):
        raise ValueError(f"匹配到 {len(matches)} 个窗口，但 index={index} 超出范围")

    w = matches[index]["element"]
    wp = w.GetWindowPattern()
    if wp:
        wp.SetWindowVisualState(2)  # Minimized
        return {
            "success": True,
            "action": "minimize",
            "name": safe_name(w),
            "match_count": len(matches),
            "selected_index": index,
        }

    raise RuntimeError(f"窗口 '{safe_name(w)}' 不支持 WindowPattern")


def maximize_window(name_substring: str, index: int = 0):
    """最大化窗口"""
    matches = _find_windows(name_substring)

    if not matches:
        raise ValueError(f"未找到匹配 '{name_substring}' 的窗口")

    if index >= len(matches):
        raise ValueError(f"匹配到 {len(matches)} 个窗口，但 index={index} 超出范围")

    w = matches[index]["element"]
    wp = w.GetWindowPattern()
    if wp:
        wp.SetWindowVisualState(1)  # Maximized
        return {
            "success": True,
            "action": "maximize",
            "name": safe_name(w),
            "match_count": len(matches),
            "selected_index": index,
        }

    raise RuntimeError(f"窗口 '{safe_name(w)}' 不支持 WindowPattern")
