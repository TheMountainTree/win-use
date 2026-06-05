"""截图模块，支持叠加编号坐标网格辅助视觉模型定位。"""

import io
import base64
from PIL import Image, ImageDraw, ImageFont, ImageGrab

from .utils import (
    get_top_level_windows,
    is_meaningful_window,
    safe_bounds,
    safe_name,
    window_matches,
)

DEFAULT_GRID_SPACING = 150
DOT_RADIUS = 10
_GRID_FONT = None


def _get_font(size: int = 10) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    global _GRID_FONT
    if _GRID_FONT is not None:
        return _GRID_FONT.font_variant(size=size)
    try:
        _GRID_FONT = ImageFont.truetype("consola.ttf", size=12)
    except OSError:
        try:
            _GRID_FONT = ImageFont.truetype("segoeui.ttf", size=12)
        except OSError:
            _GRID_FONT = ImageFont.load_default()
    return _GRID_FONT.font_variant(size=size)


def _apply_overlay(image: Image.Image, window_offset_x: int, window_offset_y: int,
                   spacing: int) -> tuple[Image.Image, list[dict]]:
    img_w, img_h = image.size
    overlay = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _get_font(10)
    dot_id = 0
    dots = []

    for y in range(spacing, img_h - spacing // 2, spacing):
        for x in range(spacing, img_w - spacing // 2, spacing):
            dot_id += 1
            screen_x = window_offset_x + x
            screen_y = window_offset_y + y

            draw.ellipse(
                [x - DOT_RADIUS, y - DOT_RADIUS, x + DOT_RADIUS, y + DOT_RADIUS],
                fill=(220, 40, 40, 160),
                outline=(255, 255, 255, 200),
                width=1,
            )

            text = str(dot_id)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((x - tw // 2, y - th // 2), text, fill=(255, 255, 255, 220), font=font)

            dots.append({
                "id": dot_id,
                "screen_x": screen_x,
                "screen_y": screen_y,
                "img_x": x,
                "img_y": y,
            })

    result = Image.alpha_composite(image.convert("RGBA"), overlay)
    return result, dots


def screenshot(output_file: str | None = None, to_base64: bool = False, quality: int = 85,
               window_name: str | None = None, overlay_grid: int | bool = False):
    """
    截取屏幕或指定窗口。

    Args:
        output_file: 保存路径，None 则不保存
        to_base64: 是否返回 base64 编码
        quality: JPEG 质量 (1-100)
        window_name: 只截取指定窗口区域（模糊匹配名称）
        overlay_grid: True 使用默认 150px 间距，int 为自定义间距；叠加编号坐标点

    Returns:
        dict: 包含路径、base64 数据、overlay_dots（如有）
    """
    img = ImageGrab.grab()
    window_cropped = None
    offset_x, offset_y = 0, 0

    if window_name:
        windows = [w for w in get_top_level_windows() if is_meaningful_window(w)]
        matched = [w for w in windows if window_matches(w, window_name)[0]]
        if matched:
            target = matched[0]
            x, y, w, h = safe_bounds(target)
            if w > 0 and h > 0:
                offset_x, offset_y = x, y
                img = img.crop((x, y, x + w, y + h))
                window_cropped = safe_name(target)

    spacing = DEFAULT_GRID_SPACING
    if type(overlay_grid) is int and overlay_grid > 20:
        spacing = overlay_grid
    elif overlay_grid is True:
        spacing = DEFAULT_GRID_SPACING
    elif type(overlay_grid) is int:
        spacing = max(40, overlay_grid)

    dots = None
    if overlay_grid and img.width > spacing * 2 and img.height > spacing * 2:
        img, dots = _apply_overlay(img, offset_x, offset_y, spacing)

    result = {
        "success": True,
        "action": "screenshot",
        "size": img.size,
    }
    if window_cropped:
        result["window"] = window_cropped
    if dots:
        result["overlay_dots"] = dots
        result["overlay_spacing"] = spacing
        result["overlay_offset"] = {"x": offset_x, "y": offset_y}

    save_format = "PNG" if (output_file and output_file.lower().endswith(".png")) or dots else None

    if output_file:
        if save_format == "PNG":
            img.save(output_file, "PNG")
        else:
            img.save(output_file, "JPEG", quality=quality)
        result["file"] = output_file

    if to_base64:
        buf = io.BytesIO()
        if save_format == "PNG":
            img.save(buf, format="PNG")
        else:
            img.save(buf, format="JPEG", quality=quality)
        b64 = base64.b64encode(buf.getvalue()).decode()
        result["base64"] = b64

    return result
