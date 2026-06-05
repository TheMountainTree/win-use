"""
win-use CLI：AI Agent 操控 Windows 桌面的通用命令行工具。

用法：
    win-use serve                     # 启动长驻服务（复用 COM 上下文，加速连续调用）
    win-use read                      # 读取当前无障碍树
    win-use click --id 5              # 点击元素 5
    win-use type "你好"               # 输入文字
    win-use apps list                 # 列出所有窗口
    win-use batch flow.json           # 单进程执行多步工作流
    win-use screenshot -o a.png       # 截图

所有命令在有 serve 运行时自动通过 socket 发送，避免重复进程启动开销。
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional
import typer

app = typer.Typer(
    name="win-use",
    help="Windows Computer Use CLI — 让 AI Agent 操控 Windows 桌面",
    add_completion=False,
)

_USE_SERVE = True


def _try_serve(cmd: str, args: dict) -> bool:
    if not _USE_SERVE:
        return False
    try:
        from .serve import try_serve_call
        result = try_serve_call(cmd, args)
        if result is not None:
            typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
            return True
    except Exception:
        pass
    return False


# ─── serve ───

@app.command("serve")
def cmd_serve(
    port: int = typer.Option(0, "--port", "-p", help="监听端口，0=自动分配"),
):
    """启动长驻服务，复用 COM 上下文和 UIA 缓存，加速连续调用"""
    from .serve import run_server

    run_server(port)


# ─── read ───

@app.command("read")
def cmd_read(
    window: Optional[str] = typer.Option(None, "--window", "-w", help="只读指定窗口（模糊匹配名称）"),
    active: bool = typer.Option(False, "--active", "-a", help="只读当前活动窗口"),
    depth: int = typer.Option(4, "--depth", "-d", help="递归深度上限"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="只输出可交互元素"),
    compact: bool = typer.Option(False, "--compact", "-c", help="精简输出"),
    mode: str = typer.Option("auto", "--mode", help="windows / full / compact / auto（默认auto=无--window时windows，有时compact）"),
    all_windows: bool = typer.Option(False, "--all", help="包括后台和最小化窗口"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="保存到 JSON 文件"),
):
    """读取 Windows 无障碍树：无--window时只扫窗口层(L1)，--window后递归子树"""
    _mode = mode
    if _mode not in {"auto", "windows", "full", "compact"}:
        typer.echo("错误：--mode 仅支持 auto / windows / full / compact", err=True)
        raise typer.Exit(1)
    if compact or interactive:
        _mode = "compact"
    if _mode == "auto":
        _mode = "windows" if not window and not active else "compact"

    args = {
        "window": window,
        "active": active,
        "depth": depth,
        "all": all_windows,
        "mode": _mode,
    }
    if _try_serve("read", args):
        return

    from .reader import read_screen
    from .cache import save_elements_cache, strip_internal_fields

    windows_list = [window] if window else None

    data = read_screen(
        windows=windows_list,
        active_only=active,
        max_depth=depth,
        include_all=all_windows,
        mode=_mode,
    )
    save_elements_cache(data["elements"])
    strip_internal_fields(data)

    json_str = json.dumps(data, indent=2, ensure_ascii=False)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(json_str)
        typer.echo(f"已保存到 {output}")

    typer.echo(json_str)


# ─── click ───

@app.command("click")
def cmd_click(
    element_id: Optional[int] = typer.Option(None, "--id", help="元素 ID（需先 read）"),
    x: Optional[int] = typer.Option(None, "--x", help="屏幕 X 坐标"),
    y: Optional[int] = typer.Option(None, "--y", help="屏幕 Y 坐标"),
    button: str = typer.Option("left", "--button", "-b", help="left / right / middle"),
    double: bool = typer.Option(False, "--double", help="双击"),
):
    """点击指定元素或坐标"""
    args: dict = {}
    if element_id:
        args = {"element_id": int(element_id), "button": button, "double": double}
    elif x is not None and y is not None:
        args = {"x": int(x), "y": int(y), "button": button, "double": double}
    else:
        typer.echo("错误：请提供 --id 或 --x/--y", err=True)
        raise typer.Exit(1)

    if _try_serve("click", args):
        return

    from .actions import click, double_click
    from .cache import load_elements_cache

    if element_id:
        elements_cache = load_elements_cache()
        if not elements_cache:
            typer.echo("错误：没有缓存的元素数据，请先运行 win-use read", err=True)
            raise typer.Exit(1)
        if double:
            result = double_click(element_id=element_id, elements_cache=elements_cache)
        else:
            result = click(element_id=element_id, button=button, elements_cache=elements_cache)
    elif x is not None and y is not None:
        if double:
            result = double_click(coords=(x, y))
        else:
            result = click(coords=(x, y), button=button)
    else:
        typer.echo("错误：请提供 --id 或 --x/--y", err=True)
        raise typer.Exit(1)

    typer.echo(json.dumps(result, ensure_ascii=False))


# ─── type ───

@app.command("type")
def cmd_type(
    text: Optional[str] = typer.Argument(None, help="要输入的文字"),
    delay: int = typer.Option(0, "--delay", "-d", help="每字延迟(ms)，0=字面量粘贴"),
    stdin: bool = typer.Option(False, "--stdin", help="从 stdin 读取文字，避免 shell 引号转义"),
    preserve_stdin_newline: bool = typer.Option(
        False, "--preserve-stdin-newline", help="保留 stdin 末尾的一个换行"
    ),
    preserve_outer_quotes: bool = typer.Option(
        False, "--preserve-outer-quotes", help="保留整段文本最外层引号"
    ),
):
    """输入字面量文字；默认移除 Agent/shell 意外传入的整段外层引号"""
    if stdin:
        if text is not None:
            typer.echo("错误：使用 --stdin 时不要同时提供文字参数", err=True)
            raise typer.Exit(1)
        text = sys.stdin.read()
        if not preserve_stdin_newline:
            if text.endswith("\r\n"):
                text = text[:-2]
            elif text.endswith("\n") or text.endswith("\r"):
                text = text[:-1]
    if text is None:
        typer.echo("错误：请提供文字参数或使用 --stdin", err=True)
        raise typer.Exit(1)

    args = {
        "text": text,
        "delay": delay,
        "preserve_outer_quotes": preserve_outer_quotes,
    }
    if _try_serve("type", args):
        return

    from .actions import type_text

    result = type_text(
        text,
        delay=delay,
        preserve_outer_quotes=preserve_outer_quotes,
    )
    typer.echo(json.dumps(result, ensure_ascii=False))


# ─── keys ───

@app.command("keys")
def cmd_keys(
    keys: str = typer.Argument(..., help="组合键，如 {Ctrl}c, {Win}r, {Alt}{F4}"),
):
    """发送键盘组合键"""
    args = {"keys": keys}
    if _try_serve("keys", args):
        return

    from .actions import send_keys

    result = send_keys(keys)
    typer.echo(json.dumps(result, ensure_ascii=False))


# ─── scroll ───

@app.command("scroll")
def cmd_scroll(
    direction: str = typer.Argument("down", help="up / down / left / right"),
    amount: int = typer.Option(300, "--amount", "-a", help="滚动量（像素）"),
    x: Optional[int] = typer.Option(None, "--x", help="滚动位置 X"),
    y: Optional[int] = typer.Option(None, "--y", help="滚动位置 Y"),
):
    """在指定位置滚动"""
    args: dict = {"direction": direction, "amount": amount}
    if x is not None and y is not None:
        args["x"] = x
        args["y"] = y
    if _try_serve("scroll", args):
        return

    from .actions import scroll

    coords = (x, y) if x is not None and y is not None else None
    result = scroll(direction=direction, amount=amount, coords=coords)
    typer.echo(json.dumps(result, ensure_ascii=False))


# ─── move ───

@app.command("move")
def cmd_move(
    x: int = typer.Argument(...),
    y: int = typer.Argument(...),
):
    """移动鼠标到指定坐标（不点击）"""
    args = {"x": x, "y": y}
    if _try_serve("move", args):
        return

    from .actions import move_mouse

    result = move_mouse((x, y))
    typer.echo(json.dumps(result, ensure_ascii=False))


# ─── drag ───

@app.command("drag")
def cmd_drag(
    from_x: int = typer.Argument(...),
    from_y: int = typer.Argument(...),
    to_x: int = typer.Argument(...),
    to_y: int = typer.Argument(...),
):
    """从 (from_x, from_y) 拖拽到 (to_x, to_y)"""
    args = {"from_x": from_x, "from_y": from_y, "to_x": to_x, "to_y": to_y}
    if _try_serve("drag", args):
        return

    from .actions import drag

    result = drag((from_x, from_y), (to_x, to_y))
    typer.echo(json.dumps(result, ensure_ascii=False))


# ─── wait ───

@app.command("wait")
def cmd_wait(
    seconds: float = typer.Argument(1.0, help="等待秒数"),
):
    """等待指定秒数"""
    args = {"seconds": seconds}
    if _try_serve("wait", args):
        return

    from .actions import wait

    result = wait(seconds)
    typer.echo(json.dumps(result, ensure_ascii=False))


# ─── batch ───

@app.command("batch")
def cmd_batch(
    workflow: Optional[str] = typer.Argument(
        None, help="工作流 JSON 文件路径、JSON 字符串，或 - 表示从 stdin 读取"
    ),
    json_data: Optional[str] = typer.Option(None, "--json", help="内联工作流 JSON"),
    pretty: bool = typer.Option(True, "--pretty/--no-pretty", help="格式化 JSON 输出"),
    cleanup: bool = typer.Option(False, "--cleanup", help="执行后自动删除工作流 JSON 文件"),
):
    """单进程执行多步操作，每步返回 success、耗时和结果"""
    workflow_file = None
    try:
        if json_data is not None or (workflow and workflow != "-"):
            source = json_data or workflow
            args = {"workflow": source}
            if _try_serve("batch", args):
                return

        from .batch import execute_batch, load_workflow

        if json_data is not None:
            spec = load_workflow(json_data)
        elif workflow == "-":
            spec = json.loads(sys.stdin.read())
        elif workflow:
            spec = load_workflow(workflow)
            if Path(workflow).exists():
                workflow_file = Path(workflow)
        else:
            typer.echo("错误：请提供工作流 JSON 文件、JSON 字符串或 stdin", err=True)
            raise typer.Exit(1)

        result = execute_batch(spec)
        typer.echo(json.dumps(result, indent=2 if pretty else None, ensure_ascii=False))
        if not result["success"]:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(json.dumps({
            "success": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }, ensure_ascii=False), err=True)
        raise typer.Exit(1)
    finally:
        if cleanup and workflow_file:
            try:
                workflow_file.unlink(missing_ok=True)
            except OSError:
                pass


# ─── apps ───

@app.command("apps")
def cmd_apps(
    action: str = typer.Argument("list", help="list / focus / launch / close / minimize / maximize"),
    name: Optional[str] = typer.Argument(None, help="应用或窗口名"),
    index: int = typer.Option(0, "--index", "-n", help="多匹配时选择第几个（0-based）"),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="等待窗口出现的秒数"),
):
    """管理应用窗口"""
    args: dict = {"action": action, "name": name, "index": index, "timeout": timeout}
    if _try_serve("apps", args):
        return

    from . import apps as apps_mod

    try:
        if action == "list":
            result = apps_mod.list_windows()
        elif action == "focus":
            result = apps_mod.focus_window(name, index=index, timeout=timeout)
        elif action == "launch":
            result = apps_mod.launch_app(name, timeout=max(timeout, 0))
        elif action == "close":
            result = apps_mod.close_window(name, index=index)
        elif action == "minimize":
            result = apps_mod.minimize_window(name, index=index)
        elif action == "maximize":
            result = apps_mod.maximize_window(name, index=index)
        else:
            typer.echo(f"未知操作: {action}，支持: list/focus/launch/close/minimize/maximize", err=True)
            raise typer.Exit(1)

        typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        typer.echo(f"错误: {e}", err=True)
        raise typer.Exit(1)


# ─── screenshot ───

@app.command("screenshot")
def cmd_screenshot(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="保存路径"),
    base64: bool = typer.Option(False, "--base64", "-b", help="输出 base64"),
    quality: int = typer.Option(85, "--quality", "-q", help="JPEG 质量 (1-100)"),
):
    """截取当前屏幕"""
    args: dict = {"output": output, "base64": base64, "quality": quality}
    if _try_serve("screenshot", args):
        return

    from .screen import screenshot

    result = screenshot(output_file=output, to_base64=base64, quality=quality)
    if base64:
        b64_data = result.pop("base64")
        result["base64_length"] = len(b64_data)
        result["base64_preview"] = b64_data[:100] + "..."

    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


# ─── shell ───

@app.command("shell")
def cmd_shell(
    command: str = typer.Argument(..., help="PowerShell 命令"),
):
    """执行 Shell 命令"""
    import subprocess as sp

    try:
        output = sp.check_output(command, shell=True, stderr=sp.STDOUT, timeout=30)
        typer.echo(output.decode("gbk", errors="replace"))
    except sp.TimeoutExpired:
        typer.echo("错误：命令超时 (30s)", err=True)
    except sp.CalledProcessError as e:
        typer.echo(f"错误 (exit={e.returncode}):\n{e.output.decode('gbk', errors='replace')}", err=True)


# ─── 入口 ───

def main():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    app()


if __name__ == "__main__":
    main()
