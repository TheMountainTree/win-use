"""长驻 socket 服务：复用 COM 上下文和缓存，避免重复进程启动开销。"""

import json
import logging
import os
import socketserver
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

SERVER_PORT_FILE = Path(tempfile.gettempdir()) / "win-use" / "server-port.txt"
BUFFER_SIZE = 65536


def _write_port(port: int):
    SERVER_PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = SERVER_PORT_FILE.with_suffix(f".{os.getpid()}.tmp")
    temp_path.write_text(str(port), encoding="utf-8")
    temp_path.replace(SERVER_PORT_FILE)


def _clear_port():
    try:
        SERVER_PORT_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def get_server_port() -> int | None:
    override = os.environ.get("WIN_USE_PORT")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    try:
        if SERVER_PORT_FILE.exists():
            return int(SERVER_PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    return None


def _dispatch(cmd: str, args: dict) -> dict:
    from . import apps as apps_mod
    from .actions import click, double_click, drag, move_mouse, scroll, send_keys, type_text, wait
    from .batch import execute_batch, load_workflow
    from .cache import load_elements_cache, save_elements_cache, strip_internal_fields
    from .reader import read_screen
    from .screen import screenshot

    if cmd == "read":
        data = read_screen(
            windows=[args.get("window")] if args.get("window") else None,
            active_only=bool(args.get("active", False)),
            max_depth=int(args.get("depth", 4)),
            include_all=bool(args.get("all", False)),
            mode=args.get("mode", "full"),
        )
        save_elements_cache(data["elements"])
        return strip_internal_fields(data)

    if cmd == "click":
        element_id = args.get("element_id")
        if element_id:
            elements_cache = load_elements_cache()
            if not elements_cache:
                return {"success": False, "error": "没有缓存元素，请先 read"}
            if args.get("double"):
                return double_click(
                    element_id=element_id, elements_cache=elements_cache,
                )
            return click(
                element_id=element_id, elements_cache=elements_cache,
                button=args.get("button", "left"),
            )
        coords = (int(args["x"]), int(args["y"]))
        if args.get("double"):
            return double_click(coords=coords)
        return click(coords=coords, button=args.get("button", "left"))

    if cmd == "type":
        return type_text(
            args["text"],
            delay=int(args.get("delay", 0)),
            preserve_outer_quotes=bool(args.get("preserve_outer_quotes", False)),
        )

    if cmd == "keys":
        return send_keys(args["keys"])

    if cmd == "scroll":
        coords = None
        if "x" in args and "y" in args:
            coords = (int(args["x"]), int(args["y"]))
        return scroll(
            direction=args.get("direction", "down"),
            amount=int(args.get("amount", 300)),
            coords=coords,
        )

    if cmd == "move":
        return move_mouse((int(args["x"]), int(args["y"])))

    if cmd == "drag":
        return drag(
            (int(args["from_x"]), int(args["from_y"])),
            (int(args["to_x"]), int(args["to_y"])),
        )

    if cmd == "wait":
        return wait(float(args.get("seconds", 1.0)))

    if cmd == "batch":
        source = args["workflow"]
        spec = load_workflow(source) if source != "-" else json.loads(args.get("stdin_json", "{}"))
        return execute_batch(spec)

    if cmd == "apps":
        action = args.get("action", "list")
        if action == "list":
            return apps_mod.list_windows()
        if action == "focus":
            return apps_mod.focus_window(
                args["name"], index=int(args.get("index", 0)),
                timeout=float(args.get("timeout", 2.0)),
            )
        if action == "launch":
            return apps_mod.launch_app(
                args["name"], timeout=max(float(args.get("timeout", 2.0)), 0),
            )
        if action == "close":
            return apps_mod.close_window(args["name"], index=int(args.get("index", 0)))
        if action == "minimize":
            return apps_mod.minimize_window(args["name"], index=int(args.get("index", 0)))
        if action == "maximize":
            return apps_mod.maximize_window(args["name"], index=int(args.get("index", 0)))
        return {"success": False, "error": f"未知操作: {action}"}

    if cmd == "screenshot":
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

    if cmd == "locate_vision":
        from .vision import locate_element
        return locate_element(
            window_name=args["window"],
            target_description=args["target"],
            model=args.get("model", "gpt-4o"),
            api_key=args.get("api_key"),
            base_url=args.get("base_url"),
            overlay_spacing=int(args.get("spacing", 150)),
        )

    return {"success": False, "error": f"未知命令: {cmd}"}


class _ServeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            raw = self.rfile.readline()
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            cmd = request.get("cmd", "")
            args = request.get("args", {})
            result = _dispatch(cmd, args)
        except Exception as exc:
            result = {"success": False, "error": str(exc), "error_type": type(exc).__name__}

        try:
            response = json.dumps(result, ensure_ascii=False) + "\n"
            self.wfile.write(response.encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass


def run_server(port: int = 0):
    import uiautomation as auto

    _ = auto.GetRootControl()

    with socketserver.ThreadingTCPServer(("127.0.0.1", port), _ServeHandler) as server:
        actual_port = server.server_address[1]
        _write_port(actual_port)
        logger.info("win-use serve 已启动: 127.0.0.1:%s", actual_port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            _clear_port()


def try_serve_call(cmd: str, args: dict, timeout: float = 15.0) -> dict | None:
    import socket

    port = get_server_port()
    if port is None:
        return None

    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        with sock:
            request = json.dumps({"cmd": cmd, "args": args}, ensure_ascii=False) + "\n"
            sock.sendall(request.encode("utf-8"))
            response = b""
            while True:
                chunk = sock.recv(BUFFER_SIZE)
                if not chunk:
                    break
                response += chunk
                if b"\n" in response:
                    break
            if not response:
                return None
            return json.loads(response.decode("utf-8"))
    except (OSError, json.JSONDecodeError, ConnectionRefusedError):
        return None
    except Exception as exc:
        logger.debug("serve 调用失败: %s", exc)
        return None
