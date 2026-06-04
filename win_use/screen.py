"""截图模块"""

import io
import base64
import uiautomation as auto
from PIL import ImageGrab


def screenshot(output_file: str | None = None, to_base64: bool = False, quality: int = 85):
    """
    截取当前屏幕。

    Args:
        output_file: 保存路径，None 则不保存
        to_base64: 是否返回 base64 编码
        quality: JPEG 质量 (1-100)

    Returns:
        dict: 包含路径或 base64 数据
    """
    img = ImageGrab.grab()

    result = {"success": True, "action": "screenshot", "size": img.size}

    if output_file:
        if output_file.lower().endswith(".png"):
            img.save(output_file, "PNG")
        else:
            img.save(output_file, "JPEG", quality=quality)
        result["file"] = output_file

    if to_base64:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode()
        result["base64"] = b64

    return result
