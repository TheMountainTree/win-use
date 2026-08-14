# win-use — Windows Computer Use CLI

Python 包，通过 `uiautomation` 读取 Windows UIA 无障碍树，为 AI Agent 提供操控 Windows 桌面的能力。

## Agent 核心原则

**🔴 核心理念是 loop agent 常驻进程。** `python -m win_use` 启动后进入 stdin/stdout
JSON-lines REPL：agent 逐行发送 `{"cmd": "...", "args": {...}}`，进程逐行返回
`{"success": true/false, ...}`。单进程复用 COM 上下文，消除 ~500ms/次的进程启动惩罚。

**🟡 会话开始时先 `python -m win_use` 启动常驻进程**，通过 stdin/stdout 逐条交互。
不可用时让用户 `pip install -e .`。不要用 `conda run` / 手动拼 `sys.argv` 绕过入口。

**🔴 截图降级时不可"估算"坐标。** opaque app 截完图必须把 base64 送给视觉模型提取精确坐标，
禁止用窗口 bounds 推测。优先使用 `overlay_grid` 叠加编号坐标点，视觉模型返回最近点编号 + 偏移量，Agent 查表计算精确屏幕坐标。

## 项目结构

```
win_use/
├── __init__.py   # 版本号
├── __main__.py   # python -m win_use 入口
├── cli.py        # stdin/stdout JSON-lines REPL 主循环
├── dispatch.py   # 命令分发核心（dispatch + LoopContext）
├── reader.py     # 读取 UIA 树，输出结构化 JSON
├── actions.py    # 模拟操作：点击、输入、滚动、拖拽
├── apps.py       # 窗口管理：列出/聚焦/启动/关闭/最小化/最大化
├── selectors.py  # Selector 匹配 + 事件驱动 wait_for
├── screen.py     # 截图
├── cache.py      # 索引化元素定位缓存（内存 + 文件兼容）
├── locator.py    # 元素重定位
├── vision.py     # 视觉定位（locate_vision 命令）
└── utils.py      # 安全读取 UIA 属性、窗口过滤、元素判断
```

## REPL 协议

请求（每行一个 JSON，UTF-8）：
```json
{"cmd": "read", "args": {"window": "记事本", "mode": "compact"}}
```

响应（每行一个 JSON，UTF-8）：
```json
{"success": true, "mode": "compact", "elements": [...]}
```

错误：
```json
{"success": false, "error": "...", "error_type": "ValueError"}
```

EOF（stdin 关闭）时进程优雅退出。

## 命令集

| cmd | args 关键字段 | 说明 |
|-----|-------------|------|
| `read` | window, active, depth, mode, all | 读 UIA 树，填充内存缓存 |
| `click` | id 或 x/y, button, double | 点击；double=true 为双击 |
| `type` | text, delay, preserve_outer_quotes | 输入文本 |
| `keys` | keys | 组合键 |
| `scroll` | direction, amount, x, y | 滚动 |
| `move` | x, y | 移动鼠标 |
| `drag` | from_x, from_y, to_x, to_y | 拖拽 |
| `wait` | seconds | 等待 |
| `wait_for` | selector, window, active, timeout, state | 条件等待 |
| `apps` | action(list/focus/launch/close/minimize/maximize), name, index, timeout | 窗口管理 |
| `screenshot` | output, base64, quality, window, overlay_grid | 截图 |
| `locate_vision` | window, target, model, spacing | 视觉定位 |
| `shell` | command, timeout | 本地 PowerShell 执行 |

## 窗口定位方式

多字段模糊匹配（优先级：Name > AutomationId > ClassName），支持 `index` 选择多匹配中的第 N 个。

## 元素定位方式

`read` 默认以 **windows 模式**扫描所有窗口（等同于 `tree -L 1`）。
使用 `"window": "X"` 指定目标窗口后再 deep read（等价于 `tree` 递归子树）。
输出运行时自增 `id`，定位信息存入进程内存缓存（O(1) 查找）并同步写入文件（兼容外部检查与崩溃恢复）。
后续 `click --id N` 会从内存缓存读取，重新解析当前 UIA 元素后执行点击。

`wait_for` 支持 selector 条件等待（基于 UIA 事件通知，自动降级为轮询），
返回 `success`、`state` 和匹配元素摘要。

## 关键依赖

- `uiautomation` — Windows UIA 客户端
- `pyautogui` / `pyperclip` — 辅助输入
- `openai`（`[vision]` extra）— 视觉定位
