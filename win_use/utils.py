"""工具函数：UIA 属性、安全枚举、窗口匹配和元素判断。"""

import logging
import time
import uiautomation as auto

logger = logging.getLogger(__name__)


PATTERNS = (
    ("Invoke", auto.PatternId.InvokePattern),
    ("Toggle", auto.PatternId.TogglePattern),
    ("SelectionItem", auto.PatternId.SelectionItemPattern),
    ("ExpandCollapse", auto.PatternId.ExpandCollapsePattern),
    ("Value", auto.PatternId.ValuePattern),
    ("RangeValue", auto.PatternId.RangeValuePattern),
    ("ScrollItem", auto.PatternId.ScrollItemPattern),
    ("Text", auto.PatternId.TextPattern),
)


def get_screen_size():
    """获取主屏幕尺寸"""
    w, h = auto.GetScreenSize()
    return w, h


def safe_attr(element, attr: str, default=None):
    """安全读取元素属性，避免 COM 异常"""
    try:
        return getattr(element, attr, default)
    except Exception:
        return default


def safe_name(element) -> str:
    return safe_attr(element, "Name") or ""


def safe_automation_id(element) -> str:
    return safe_attr(element, "AutomationId") or ""


def safe_identifiers(element) -> dict:
    """返回元素的所有标识字段，用于多字段匹配"""
    return {
        "name": safe_name(element),
        "class_name": safe_attr(element, "ClassName") or "",
        "automation_id": safe_automation_id(element),
    }


def safe_type(element) -> str:
    """返回规范化控件类型，例如 ButtonControl -> Button。"""
    control_type = safe_attr(element, "ControlTypeName") or "Unknown"
    if control_type.endswith("Control"):
        return control_type[:-7]
    return control_type


def safe_class_name(element) -> str:
    return safe_attr(element, "ClassName") or ""


def safe_native_handle(element) -> int:
    return int(safe_attr(element, "NativeWindowHandle", 0) or 0)


def safe_runtime_id(element) -> list[int]:
    try:
        return list(element.GetRuntimeId())
    except Exception:
        return []


def safe_bounds(element) -> tuple:
    """返回 (x, y, w, h)，失败返回 (0,0,0,0)"""
    try:
        r = element.BoundingRectangle
        return (r.left, r.top, r.width(), r.height())
    except Exception:
        return (0, 0, 0, 0)


def safe_enabled(element) -> bool:
    return bool(safe_attr(element, "IsEnabled", False))


def safe_offscreen(element) -> bool:
    return bool(safe_attr(element, "IsOffscreen", False))


def get_window_state(element) -> str:
    """返回窗口状态：normal / minimized / maximized / unknown"""
    try:
        wp = element.GetWindowPattern()
        if wp is None:
            return "unknown"
        vs = wp.WindowVisualState
        return {0: "normal", 1: "maximized", 2: "minimized"}.get(vs, "unknown")
    except Exception:
        return "unknown"


def is_interactive(element) -> bool:
    """判断元素是否可交互（有操作的 pattern）"""
    return bool(get_supported_patterns(element))


def get_supported_patterns(element) -> list[str]:
    """通过 uiautomation 2.x 的 GetPattern API 获取常用 Pattern。"""
    supported = []
    for name, pattern_id in PATTERNS:
        try:
            if element.GetPattern(pattern_id) is not None:
                supported.append(name)
        except Exception:
            continue
    return supported


def get_top_level_windows(retries: int = 3, retry_delay: float = 0.15) -> list:
    """枚举顶层 UIA 控件；瞬时 COM 异常时重试。"""
    last_error = None
    for attempt in range(retries):
        try:
            return list(auto.GetRootControl().GetChildren())
        except Exception as exc:
            last_error = exc
            logger.warning("枚举顶层窗口失败（第 %s/%s 次）: %s", attempt + 1, retries, exc)
            if attempt + 1 < retries:
                time.sleep(retry_delay)
    if last_error is not None:
        raise RuntimeError(f"无法枚举 Windows UIA 顶层窗口: {last_error}") from last_error
    return []


def safe_children(element, retries: int = 2, retry_delay: float = 0.05) -> list:
    """安全读取子控件；UIA 树瞬时变化时短暂重试。"""
    for attempt in range(retries):
        try:
            return list(element.GetChildren())
        except Exception as exc:
            if attempt + 1 >= retries:
                logger.debug("读取子控件失败: %s", exc)
                return []
            time.sleep(retry_delay)
    return []


def get_active_window():
    """通过 Win32 前台 HWND 获取真正的顶层活动窗口。"""
    try:
        handle = auto.GetForegroundWindow()
        if handle:
            return auto.ControlFromHandle(handle)
    except Exception as exc:
        logger.debug("通过前台 HWND 获取活动窗口失败: %s", exc)

    try:
        current = auto.GetForegroundControl()
        last_with_handle = current if safe_native_handle(current) else None
        for _ in range(20):
            parent = current.GetParentControl()
            if parent is None:
                break
            current = parent
            if safe_native_handle(current):
                last_with_handle = current
        return last_with_handle
    except Exception as exc:
        logger.warning("获取活动窗口失败: %s", exc)
        return None


def is_meaningful_window(element) -> bool:
    """判断是否是应用顶层窗口；保留最小化和暂时无尺寸的窗口。"""
    name = safe_name(element)
    class_name = safe_class_name(element)
    control_type = safe_type(element)
    handle = safe_native_handle(element)

    if class_name in {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}:
        return False
    if name == "Program Manager":
        return False
    if not name and not class_name:
        return False
    if control_type == "Window" or get_window_state(element) != "unknown":
        return True
    if not handle or not name:
        return False

    # 过滤常见的 1x1/22x22 后台消息窗口，但保留零尺寸的隐藏应用窗口。
    _, _, width, height = safe_bounds(element)
    if 0 < width < 80 and 0 < height < 80:
        return False
    return True


def window_matches(element, query: str) -> tuple[bool, str | None]:
    """统一窗口匹配规则：Name > AutomationId > ClassName，大小写不敏感。"""
    query_lower = (query or "").strip().casefold()
    if not query_lower:
        return False, None

    identifiers = safe_identifiers(element)
    for field in ("name", "automation_id", "class_name"):
        if query_lower in identifiers[field].casefold():
            return True, field
    return False, None


CLICKABLE_TYPES = {
    "Button", "Hyperlink", "ListItem", "TreeItem", "MenuItem",
    "TabItem", "RadioButton", "CheckBox", "ComboBox", "SplitButton",
}


INPUT_TYPES = {"Edit", "Document"}


def is_clickable(element) -> bool:
    """判断是否可点击"""
    return safe_type(element) in CLICKABLE_TYPES and safe_enabled(element)


def is_input(element) -> bool:
    """判断是否是输入框"""
    return safe_type(element) in INPUT_TYPES and safe_enabled(element)
