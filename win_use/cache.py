"""跨 CLI 进程持久化最近一次 read 的元素定位信息。"""

import json
import os
import tempfile
from pathlib import Path


def get_cache_path() -> Path:
    override = os.environ.get("WIN_USE_CACHE_PATH")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "win-use" / "last-read.json"


def save_elements_cache(elements: list[dict]) -> Path:
    path = get_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "id": element["id"],
            "bounds": element["bounds"],
            "name": element.get("name", ""),
            "type": element.get("type", "Unknown"),
            "locator": element.get("_locator"),
        }
        for element in elements
    ]
    temp_path = path.with_suffix(f".{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
    return path


def load_elements_cache() -> list[dict]:
    path = get_cache_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def strip_internal_fields(data: dict) -> dict:
    for element in data.get("elements", []):
        element.pop("_locator", None)
    return data
