"""win-use CLI：loop agent 常驻进程入口。

启动后进入 stdin/stdout JSON-lines REPL：
  - agent 逐行发送 {"cmd": "...", "args": {...}}
  - 进程逐行返回 {"success": true/false, ...}
  - stdin 关闭（EOF）时进程优雅退出

用法：
    python -m win_use
    echo '{"cmd":"apps","args":{"action":"list"}}' | python -m win_use
"""

import json
import logging
import sys

from .dispatch import LoopContext, dispatch

logger = logging.getLogger(__name__)


def main():
    """启动 loop agent REPL，从 stdin 逐行读取 JSON 命令并分发。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # 预热 COM 上下文（复用 UIA 连接，消除后续命令的初始化开销）
    try:
        import uiautomation as auto
        _ = auto.GetRootControl()
    except Exception:
        pass

    ctx = LoopContext()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        result = _handle_line(line, ctx)
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _handle_line(line: str, ctx: LoopContext) -> dict:
    """解析单行 JSON 请求并分发，返回结构化结果。"""
    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"JSON 解析失败: {exc}", "error_type": "JSONDecodeError"}

    if not isinstance(request, dict):
        return {"success": False, "error": "请求必须是 JSON 对象", "error_type": "InvalidRequest"}

    cmd = request.get("cmd", "")
    args = request.get("args", {})
    if not isinstance(args, dict):
        return {"success": False, "error": "args 必须是 JSON 对象", "error_type": "InvalidRequest"}

    return dispatch(cmd, args, ctx)


if __name__ == "__main__":
    main()
