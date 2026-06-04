"""模拟操作：点击、输入、滚动、快捷键"""

import time
import uiautomation as auto
from .locator import resolve_element
from .utils import safe_bounds, safe_offscreen


# ─── 坐标计算 ───

def _center(bounds: dict) -> tuple:
    """返回矩形中心点坐标"""
    return (bounds["x"] + bounds["w"] // 2, bounds["y"] + bounds["h"] // 2)


def _resolve_click_point(element_id: int, elements_cache: list) -> tuple[int, int]:
    for cached in elements_cache:
        if cached.get("id") != element_id:
            continue
        bounds = cached["bounds"]
        locator = cached.get("locator")
        element = resolve_element(locator)
        if locator and element is None:
            raise RuntimeError(f"元素 ID {element_id} 已失效，请重新 read")
        if element is not None:
            if safe_offscreen(element):
                raise RuntimeError(f"元素 ID {element_id} 当前不在屏幕内，请滚动或恢复窗口")
            x, y, width, height = safe_bounds(element)
            bounds = {"x": x, "y": y, "w": width, "h": height}
        if bounds["w"] <= 0 or bounds["h"] <= 0:
            raise RuntimeError(f"元素 ID {element_id} 当前不可见，请重新 read 或先恢复窗口")
        x, y = _center(bounds)
        if abs(x) > 30000 or abs(y) > 30000:
            raise RuntimeError(f"元素 ID {element_id} 当前位于屏幕外，请重新 read 或先恢复窗口")
        return x, y
    raise ValueError(f"元素 ID {element_id} 未在缓存中找到，请重新 read")


# ─── 点击 ───

def click(coords: tuple[int, int] | None = None, element_id: int | None = None,
          button: str = "left", elements_cache: list | None = None, settle: float = 0.3):
    """
    点击指定坐标或元素。

    Args:
        coords: 屏幕坐标 (x, y)
        element_id: 从 reader 返回的元素 ID
        button: left / right / middle
        elements_cache: reader 返回的 elements 列表，用于按 ID 查找
    """
    if element_id is not None and elements_cache:
        x, y = _resolve_click_point(element_id, elements_cache)
    elif coords:
        x, y = coords
    else:
        raise ValueError("必须提供 coords 或 element_id")

    if button == "left":
        auto.Click(x, y)
    elif button == "right":
        auto.RightClick(x, y)
    elif button == "middle":
        auto.MiddleClick(x, y)
    else:
        raise ValueError(f"不支持的按钮类型: {button}")

    time.sleep(max(0, settle))
    return {"success": True, "action": "click", "button": button, "coords": (x, y)}


def double_click(coords: tuple[int, int] | None = None, element_id: int | None = None,
                 elements_cache: list | None = None, settle: float = 0.3):
    """双击"""
    if element_id is not None and elements_cache:
        x, y = _resolve_click_point(element_id, elements_cache)
    elif coords:
        x, y = coords
    else:
        raise ValueError("必须提供 coords 或 element_id")

    auto.DoubleClick(x, y)
    time.sleep(max(0, settle))
    return {"success": True, "action": "double_click", "coords": (x, y)}


# ─── 输入 ───

OUTER_QUOTE_PAIRS = {
    '"': '"',
    "'": "'",
    "“": "”",
    "‘": "’",
}


def normalize_text_input(text: str, preserve_outer_quotes: bool = False) -> tuple[str, int]:
    """
    移除 Agent/shell 误传入的整段外层引号。

    最多移除三层匹配引号。确实需要输入外层引号时使用 preserve_outer_quotes=True。
    """
    if preserve_outer_quotes:
        return text, 0

    normalized = text
    removed_layers = 0
    while removed_layers < 3 and len(normalized) >= 2:
        expected_end = OUTER_QUOTE_PAIRS.get(normalized[0])
        if expected_end is None or normalized[-1] != expected_end:
            break
        normalized = normalized[1:-1]
        removed_layers += 1
    return normalized, removed_layers


def type_text(
    text: str,
    delay: int = 0,
    settle: float = 0.2,
    preserve_outer_quotes: bool = False,
):
    """
    模拟键盘输入文字。

    Args:
        text: 要输入的文字
        delay: 每个字符间的延迟（毫秒），0 表示粘贴模式
        preserve_outer_quotes: 保留整段文本最外层引号
    """
    text, removed_quote_layers = normalize_text_input(
        text,
        preserve_outer_quotes=preserve_outer_quotes,
    )

    if delay == 0:
        # 粘贴模式按字面量输入，不会把引号、花括号等解释为按键语法。
        import pyperclip
        pyperclip.copy(text)
        auto.SendKeys("{Ctrl}v", waitTime=0.3)
        method = "paste"
    else:
        # 逐字输入
        auto.SendKeys(text, waitTime=delay / 1000.0)
        method = "send_keys"

    time.sleep(max(0, settle))
    return {
        "success": True,
        "action": "type",
        "text": text,
        "length": len(text),
        "delay": delay,
        "method": method,
        "removed_outer_quote_layers": removed_quote_layers,
    }


# ─── 按键 ───

def send_keys(keys: str, settle: float = 0.3):
    """
    发送键盘组合键。

    Examples:
        send_keys("{Ctrl}c")     → Ctrl+C
        send_keys("{Alt}{F4}")   → Alt+F4
        send_keys("{Win}r")      → Win+R
        send_keys("{Enter}")     → Enter
    """
    auto.SendKeys(keys, waitTime=0.2)
    time.sleep(max(0, settle))
    return {"success": True, "action": "keys", "keys": keys}


# ─── 滚动 ───

def scroll(direction: str = "down", amount: int = 300, coords: tuple[int, int] | None = None,
           settle: float = 0.2):
    """
    在指定位置滚动。

    Args:
        direction: up / down / left / right
        amount: 滚动量（像素）
        coords: 滚动发生的屏幕坐标，None 表示鼠标当前位置
    """
    if coords is None:
        # 获取鼠标当前位置
        import pyautogui
        x, y = pyautogui.position()
    else:
        x, y = coords

    # 移动到目标位置
    auto.SetCursorPos(x, y)
    time.sleep(0.05)

    wheel_amount = amount if direction in ("up", "right") else -amount

    if direction in ("up", "down"):
        auto.MouseWheel(wheel_amount, x, y)
    else:
        auto.MouseWheelHoriz(wheel_amount, x, y)

    time.sleep(max(0, settle))
    return {"success": True, "action": "scroll", "direction": direction, "amount": amount, "coords": (x, y)}


# ─── 拖拽 ───

def drag(from_coords: tuple[int, int], to_coords: tuple[int, int], settle: float = 0.3):
    """从起始坐标拖拽到目标坐标"""
    x1, y1 = from_coords
    x2, y2 = to_coords
    auto.DragDrop(x1, y1, x2, y2, moveSpeed=1, waitTime=0.3)
    time.sleep(max(0, settle))
    return {"success": True, "action": "drag", "from": from_coords, "to": to_coords}


# ─── 移动鼠标 ───

def move_mouse(coords: tuple[int, int], settle: float = 0.1):
    """移动鼠标到指定位置（不点击）"""
    auto.SetCursorPos(coords[0], coords[1])
    time.sleep(max(0, settle))
    return {"success": True, "action": "move", "coords": coords}


# ─── 等待 ───

def wait(seconds: float = 1.0):
    """等待指定秒数"""
    time.sleep(seconds)
    return {"success": True, "action": "wait", "seconds": seconds}
