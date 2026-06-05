"""读取 Windows UIA 无障碍树，输出 full、compact 或 windows 结构化 JSON。

模式说明：
- windows：只扫描顶层窗口（深度 0），等同于 tree -L 1，极快
- compact：深度递归但只保留可交互元素，适合常规操作
- full：完整递归输出所有元素，适合诊断未知界面
"""

from .locator import make_locator
from .utils import (
    safe_name, safe_type, safe_bounds, safe_enabled, safe_offscreen,
    safe_automation_id, safe_class_name, safe_children,
    is_meaningful_window,
    get_supported_patterns, get_window_state, get_screen_size,
    get_top_level_windows, get_active_window, window_matches,
    safe_native_handle,
)


def read_screen(
    windows: list[str] | None = None,
    active_only: bool = False,
    max_depth: int = 4,
    interactive_only: bool = False,
    include_all: bool = False,
    mode: str = "full",
):
    """
    读取当前屏幕的无障碍树。

    Args:
        windows: 只读取指定名称的窗口（模糊匹配），None = 所有
        active_only: 只读活动窗口
        max_depth: 递归深度上限（windows 模式下自动为 0）
        interactive_only: 向后兼容参数；True 等价于 mode="compact"
        include_all: 包含全部窗口（包括最小化、后台）
        mode: windows / full / compact

    Returns:
        dict: 包含 screen_size, active_window, elements 的字典
    """
    if mode not in {"full", "compact", "windows"}:
        raise ValueError("mode 必须是 windows、full 或 compact")
    compact = mode == "compact" or interactive_only

    if mode == "windows":
        return _read_windows(active_only, include_all, windows)

    max_depth = max(max_depth, 0)
    elements = []
    nodes_by_id = {}
    id_counter = [0]

    def matches_window(element) -> bool:
        if windows is None:
            return True
        return any(window_matches(element, query)[0] for query in windows)

    def process(element, depth: int, parent_id: int | None, top_window, path: list[int]):
        """递归处理元素。返回节点或 None（跳过自身保留子元素）。"""
        if depth > max_depth:
            return None

        elem_type = safe_type(element)
        bounds = safe_bounds(element)
        patterns = get_supported_patterns(element)
        interactive = bool(patterns)

        if depth > 0 and (bounds[2] <= 0 or bounds[3] <= 0):
            for child_index, child in enumerate(safe_children(element)):
                process(child, depth + 1, parent_id, top_window, path + [child_index])
            return None

        if compact and depth > 0 and not interactive:
            for child_index, child in enumerate(safe_children(element)):
                process(child, depth + 1, parent_id, top_window, path + [child_index])
            return None

        id_counter[0] += 1
        node_id = id_counter[0]

        node = {
            "id": node_id,
            "type": elem_type,
            "name": safe_name(element),
            "automation_id": safe_automation_id(element),
            "bounds": {"x": bounds[0], "y": bounds[1], "w": bounds[2], "h": bounds[3]},
            "enabled": safe_enabled(element),
            "offscreen": safe_offscreen(element),
            "children": [],
            "_locator": make_locator(element, top_window, path),
        }

        if interactive:
            node["patterns"] = patterns

        if depth == 0:
            node["window_state"] = get_window_state(element)
            node["class_name"] = safe_class_name(element)

        elements.append(node)
        nodes_by_id[node_id] = node
        if parent_id is not None and parent_id in nodes_by_id:
            nodes_by_id[parent_id]["children"].append(node_id)

        for child_index, child in enumerate(safe_children(element)):
            process(child, depth + 1, node_id, top_window, path + [child_index])

        return node

    if active_only:
        root = get_active_window()
        if root is not None:
            process(root, 0, None, root, [])
    else:
        for top_window in get_top_level_windows():
            if not is_meaningful_window(top_window):
                continue
            if not include_all and get_window_state(top_window) == "minimized" and windows is None:
                continue
            if not matches_window(top_window):
                continue
            process(top_window, 0, None, top_window, [])

    screen_w, screen_h = get_screen_size()
    active = get_active_window()
    active_window = safe_name(active) if active is not None else ""

    mode_label = "compact" if compact else "full"
    return {
        "success": True,
        "mode": mode_label,
        "screen_size": {"width": screen_w, "height": screen_h},
        "active_window": active_window,
        "element_count": len(elements),
        "elements": elements,
    }


def _read_windows(active_only: bool, include_all: bool, filter_windows: list[str] | None) -> dict:
    """windows 模式：只扫描顶层窗口元数据，不做深度遍历。"""
    screen_w, screen_h = get_screen_size()
    active = get_active_window()
    active_handle = safe_native_handle(active) if active is not None else 0
    active_name = safe_name(active) if active is not None else ""

    elements = []
    id_counter = [0]

    for top_window in get_top_level_windows():
        if not is_meaningful_window(top_window):
            continue
        if not include_all and get_window_state(top_window) == "minimized" and filter_windows is None:
            continue
        if filter_windows and not any(window_matches(top_window, q)[0] for q in filter_windows):
            continue

        id_counter[0] += 1
        bounds = safe_bounds(top_window)
        elements.append({
            "id": id_counter[0],
            "type": safe_type(top_window),
            "name": safe_name(top_window),
            "class_name": safe_class_name(top_window),
            "automation_id": safe_automation_id(top_window),
            "bounds": {"x": bounds[0], "y": bounds[1], "w": bounds[2], "h": bounds[3]},
            "window_state": get_window_state(top_window),
            "enabled": safe_enabled(top_window),
            "offscreen": safe_offscreen(top_window),
            "active": bool(active_handle and safe_native_handle(top_window) == active_handle),
            "children": [],
        })

    return {
        "success": True,
        "mode": "windows",
        "screen_size": {"width": screen_w, "height": screen_h},
        "active_window": active_name,
        "element_count": len(elements),
        "elements": elements,
    }


def read_screen_compact(max_depth: int = 3, interactive_only: bool = True,
                        windows: list[str] | None = None, active_only: bool = False):
    """精简版读取：只输出可交互元素，适合发给 LLM"""
    data = read_screen(
        windows=windows, active_only=active_only,
        max_depth=max_depth, mode="compact",
    )
    for el in data["elements"]:
        el.pop("offscreen", None)
    return data
