"""命令分发核心：loop agent 常驻进程的单一入口。

dispatch(cmd, args, ctx) 接收结构化命令，调用对应核心模块执行，
返回结构化结果字典。所有异常统一捕获为 {"success": false, ...}。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class LoopContext:
    """常驻进程的会话状态，跨命令复用。

    Attributes:
        element_cache: 内存元素缓存 {int(id): record}，由 read 命令填充。
                       click --id 直接查内存，无需文件 IO。
    """

    def __init__(self) -> None:
        self.element_cache: dict[int, dict] = {}


def dispatch(cmd: str, args: dict, ctx: LoopContext) -> dict:
    """分发单条命令并返回结构化结果。

    Args:
        cmd: 命令名（read / click / type / keys / scroll / move / drag /
             wait / wait_for / apps / screenshot / locate_vision / shell）
        args: 命令参数字典
        ctx: 常驻进程会话状态（内存元素缓存等）

    Returns:
        结果字典，成功时含业务字段，失败时 {"success": false, "error": ..., "error_type": ...}
    """
    try:
        handler = _COMMANDS.get(cmd)
        if handler is None:
            return {"success": False, "error": f"未知命令: {cmd}", "error_type": "UnknownCommand"}
        return handler(args, ctx)
    except Exception as exc:
        logger.debug("dispatch %s 异常: %s", cmd, exc, exc_info=True)
        return {"success": False, "error": str(exc), "error_type": type(exc).__name__}


# ─── 命令实现 ───

def _cmd_read(args: dict, ctx: LoopContext) -> dict:
    from .reader import read_screen
    from .cache import build_memory_cache, save_elements_cache, strip_internal_fields

    window = args.get("window")
    mode = args.get("mode", "auto")
    if mode == "auto":
        mode = "windows" if not window and not args.get("active") else "compact"

    data = read_screen(
        windows=[window] if window else None,
        active_only=bool(args.get("active", False)),
        max_depth=int(args.get("depth", 4)),
        include_all=bool(args.get("all", False)),
        mode=mode,
    )
    # 内存缓存：O(1) 查找，供后续 click --id 使用
    ctx.element_cache = build_memory_cache(data["elements"])
    # 文件兼容：供外部检查与崩溃恢复
    save_elements_cache(data["elements"])
    return strip_internal_fields(data)


def _cmd_click(args: dict, ctx: LoopContext) -> dict:
    from .actions import click, double_click

    element_id = args.get("element_id") or args.get("id")
    button = args.get("button", "left")
    is_double = bool(args.get("double", False))

    if element_id:
        if not ctx.element_cache:
            return {"success": False, "error": "没有缓存元素，请先 read", "error_type": "CacheEmpty"}
        if is_double:
            return double_click(element_id=int(element_id), elements_cache=ctx.element_cache)
        return click(element_id=int(element_id), button=button, elements_cache=ctx.element_cache)

    if "x" in args and "y" in args:
        coords = (int(args["x"]), int(args["y"]))
        if is_double:
            return double_click(coords=coords)
        return click(coords=coords, button=button)

    return {"success": False, "error": "请提供 id 或 x/y", "error_type": "MissingArgument"}


def _cmd_type(args: dict, ctx: LoopContext) -> dict:
    from .actions import type_text

    text = args.get("text")
    if text is None:
        return {"success": False, "error": "缺少 text 参数", "error_type": "MissingArgument"}
    return type_text(
        text,
        delay=int(args.get("delay", 0)),
        preserve_outer_quotes=bool(args.get("preserve_outer_quotes", False)),
    )


def _cmd_keys(args: dict, ctx: LoopContext) -> dict:
    from .actions import send_keys

    keys = args.get("keys")
    if keys is None:
        return {"success": False, "error": "缺少 keys 参数", "error_type": "MissingArgument"}
    return send_keys(keys)


def _cmd_scroll(args: dict, ctx: LoopContext) -> dict:
    from .actions import scroll

    coords = None
    if "x" in args and "y" in args:
        coords = (int(args["x"]), int(args["y"]))
    return scroll(
        direction=args.get("direction", "down"),
        amount=int(args.get("amount", 300)),
        coords=coords,
    )


def _cmd_move(args: dict, ctx: LoopContext) -> dict:
    from .actions import move_mouse

    return move_mouse((int(args["x"]), int(args["y"])))


def _cmd_drag(args: dict, ctx: LoopContext) -> dict:
    from .actions import drag

    return drag(
        (int(args["from_x"]), int(args["from_y"])),
        (int(args["to_x"]), int(args["to_y"])),
    )


def _cmd_wait(args: dict, ctx: LoopContext) -> dict:
    from .actions import wait

    return wait(float(args.get("seconds", 1.0)))


def _cmd_wait_for(args: dict, ctx: LoopContext) -> dict:
    from .selectors import wait_for_element, element_summary

    selector = args.get("selector")
    if not selector:
        return {"success": False, "error": "缺少 selector 参数", "error_type": "MissingArgument"}

    target = wait_for_element(
        selector,
        window=args.get("window"),
        active=bool(args.get("active", True)),
        timeout=float(args.get("timeout", 5.0)),
        poll_interval=float(args.get("poll_interval", 0.1)),
        index=int(args.get("index", 0)),
        state=args.get("state", "present"),
        max_depth=int(args.get("depth", 8)),
    )
    return {
        "success": True,
        "action": "wait_for",
        "state": args.get("state", "present"),
        "element": element_summary(target) if target is not None else None,
    }


def _cmd_apps(args: dict, ctx: LoopContext) -> dict:
    from . import apps as apps_mod

    action = args.get("action", "list")
    name = args.get("name")
    index = int(args.get("index", 0))
    timeout = float(args.get("timeout", 2.0))

    if action == "list":
        return {"success": True, "action": "apps", "windows": apps_mod.list_windows()}
    if action == "focus":
        return apps_mod.focus_window(name, index=index, timeout=timeout)
    if action == "launch":
        return apps_mod.launch_app(name, timeout=max(timeout, 0))
    if action == "close":
        return apps_mod.close_window(name, index=index)
    if action == "minimize":
        return apps_mod.minimize_window(name, index=index)
    if action == "maximize":
        return apps_mod.maximize_window(name, index=index)
    return {"success": False, "error": f"未知操作: {action}", "error_type": "UnknownAction"}


def _cmd_screenshot(args: dict, ctx: LoopContext) -> dict:
    from .screen import screenshot

    overlay = args.get("overlay_grid")
    if isinstance(overlay, bool) and not overlay:
        overlay = False
    return screenshot(
        output_file=args.get("output"),
        to_base64=bool(args.get("base64", False)),
        quality=int(args.get("quality", 85)),
        window_name=args.get("window"),
        overlay_grid=overlay if overlay else False,
    )


def _cmd_locate_vision(args: dict, ctx: LoopContext) -> dict:
    from .vision import locate_element

    return locate_element(
        window_name=args["window"],
        target_description=args["target"],
        model=args.get("model", "gpt-4o"),
        api_key=args.get("api_key"),
        base_url=args.get("base_url"),
        overlay_spacing=int(args.get("spacing", 150)),
    )


def _cmd_shell(args: dict, ctx: LoopContext) -> dict:
    import subprocess as sp

    command = args.get("command")
    if not command:
        return {"success": False, "error": "缺少 command 参数", "error_type": "MissingArgument"}

    try:
        proc = sp.run(
            command,
            shell=True,
            capture_output=True,
            timeout=float(args.get("timeout", 30)),
        )
        stdout = proc.stdout.decode("gbk", errors="replace")
        stderr = proc.stderr.decode("gbk", errors="replace")
        return {
            "success": proc.returncode == 0,
            "action": "shell",
            "stdout": stdout,
            "stderr": stderr,
            "returncode": proc.returncode,
        }
    except sp.TimeoutExpired:
        return {"success": False, "error": "命令超时", "error_type": "TimeoutExpired"}
    except Exception as exc:
        return {"success": False, "error": str(exc), "error_type": type(exc).__name__}


# ─── 命令注册表 ───

_COMMANDS: dict[str, callable] = {
    "read": _cmd_read,
    "click": _cmd_click,
    "type": _cmd_type,
    "keys": _cmd_keys,
    "scroll": _cmd_scroll,
    "move": _cmd_move,
    "drag": _cmd_drag,
    "wait": _cmd_wait,
    "wait_for": _cmd_wait_for,
    "apps": _cmd_apps,
    "screenshot": _cmd_screenshot,
    "locate_vision": _cmd_locate_vision,
    "shell": _cmd_shell,
}