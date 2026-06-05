"""视觉模型定位：截图 + overlay → 视觉 API → 屏幕坐标。"""

import base64
import io
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

VISION_PROMPT = """Find the element described below in this screenshot. The image has a grid of numbered red dots overlaid. Each dot has a visible number.

Return ONLY this JSON object (no markdown, no explanation):
{"nearest_dot": <integer>, "offset_x": <integer>, "offset_y": <integer>}

nearest_dot: the number of the red dot closest to the center of the target element.
offset_x: horizontal pixels from that dot's center to the target center (positive=right, negative=left).
offset_y: vertical pixels from that dot's center to the target center (positive=down, negative=up).

TARGET: {target}"""


def _image_to_base64(image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _call_vision_api(
    image_b64: str,
    target_description: str,
    model: str,
    api_key: str,
    base_url: str,
) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "视觉定位需要 openai 库。请安装: pip install openai"
        )

    client = OpenAI(api_key=api_key, base_url=base_url)
    prompt = VISION_PROMPT.format(target=target_description)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        max_tokens=200,
        temperature=0,
    )

    raw = response.choices[0].message.content or ""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{[^}]+\}', raw)
        if match:
            return json.loads(match.group())
        raise RuntimeError(f"视觉模型返回无法解析: {raw}")


def locate_element(
    window_name: str,
    target_description: str,
    model: str = "gpt-4o",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    overlay_spacing: int = 150,
    quality: int = 85,
) -> dict:
    from .screen import screenshot

    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("需要 OPENAI_API_KEY 环境变量或 --api-key 参数")
    base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    shot = screenshot(
        window_name=window_name,
        to_base64=False,
        quality=quality,
        overlay_grid=overlay_spacing,
    )

    dots = shot.get("overlay_dots")
    if not dots:
        raise RuntimeError("overlay 生成失败，窗口可能不存在或太小")

    from PIL import ImageGrab

    from .utils import (
        get_top_level_windows,
        is_meaningful_window,
        safe_bounds,
        window_matches,
    )

    img = ImageGrab.grab()
    offset_x, offset_y = 0, 0
    windows = [w for w in get_top_level_windows() if is_meaningful_window(w)]
    matched = [w for w in windows if window_matches(w, window_name)[0]]
    if matched:
        x, y, w, h = safe_bounds(matched[0])
        if w > 0 and h > 0:
            offset_x, offset_y = x, y
            img = img.crop((x, y, x + w, y + h))

    from .screen import _apply_overlay
    overlay_img, _dots_check = _apply_overlay(img, offset_x, offset_y, overlay_spacing)

    image_b64 = _image_to_base64(overlay_img)
    vision_result = _call_vision_api(
        image_b64, target_description, model, api_key, base_url
    )

    dot_id = vision_result.get("nearest_dot")
    if dot_id is None:
        raise RuntimeError(f"视觉模型未返回 nearest_dot: {vision_result}")

    dot = next((d for d in dots if d["id"] == dot_id), None)
    if dot is None:
        raise RuntimeError(f"dot_id={dot_id} 不在 overlay_dots 中，共 {len(dots)} 个点")

    off_x = vision_result.get("offset_x", 0)
    off_y = vision_result.get("offset_y", 0)

    screen_x = dot["screen_x"] + off_x
    screen_y = dot["screen_y"] + off_y

    return {
        "success": True,
        "action": "locate_vision",
        "window": window_name,
        "target": target_description,
        "nearest_dot": dot_id,
        "offset": {"x": off_x, "y": off_y},
        "dot_screen_x": dot["screen_x"],
        "dot_screen_y": dot["screen_y"],
        "screen_x": screen_x,
        "screen_y": screen_y,
        "overlay_spacing": overlay_spacing,
        "total_dots": len(dots),
    }
