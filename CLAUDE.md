# win-use — Windows Computer Use CLI

Python 包，通过 `uiautomation` 读取 Windows UIA 无障碍树，为 AI Agent 提供操控 Windows 桌面的能力。

## Agent 核心原则

**🔴 多步操作必须合并为 `batch` 工作流。** 逐条 CLI 命令会产生 ~500ms/次的进程启动惩罚。
batch 将所有步骤在单进程中执行，消除重复进程启动和 UIA 树枚举开销。

**探索式交互先启动 `win-use serve`**，后续逐条命令延迟降到 ~5ms（通过 socket 复用服务进程）。

## 项目结构

```
win_use/
├── __init__.py   # 版本号
├── cli.py        # Typer CLI 入口（自动路由到 serve 服务）
├── serve.py      # 长驻 socket 服务（复用 COM 上下文）
├── reader.py     # 读取 UIA 树，输出结构化 JSON
├── actions.py    # 模拟操作：点击、输入、滚动、拖拽
├── apps.py       # 窗口管理：列出/聚焦/启动/关闭/最小化/最大化
├── batch.py      # 批处理工作流引擎
├── selectors.py  # Selector 匹配 + 事件驱动 wait_for
├── screen.py     # 截图
├── cache.py      # 索引化元素定位缓存
├── locator.py    # 元素重定位
└── utils.py      # 安全读取 UIA 属性、窗口过滤、元素判断
```

## 窗口定位方式

多字段模糊匹配（优先级：Name > AutomationId > ClassName），支持 `--index` 选择多匹配中的第 N 个。

## 元素定位方式

`win-use read` 默认以 **windows 模式**扫描所有窗口（等同于 `tree -L 1`）。
使用 `--window "X"` 指定目标窗口后再 deep read（等价于 `tree` 递归子树）。
输出运行时自增 `id`，定位信息持久化到索引化临时缓存（O(1) 查找）。
后续独立 CLI 进程中的 `click --id N` 会重新解析当前 UIA 元素后执行点击。

已知流程优先使用 `win-use batch <workflow.json>`。批处理支持 selector 直接点击和
`wait_for` 条件等待（基于 UIA 事件通知，自动降级为轮询），每个步骤返回 `success`、`elapsed_ms` 和结构化结果。
使用 `--cleanup` 自动删除临时 batch 文件。

## serve 长驻模式

```bash
# 启动服务
win-use serve [--port PORT]

# 所有 CLI 命令自动检测 serve 并通过 socket 转发
win-use read --window "Notepad" --compact
win-use click --id 5
```

## 关键依赖

- `uiautomation` — Windows UIA 客户端
- `typer` — CLI 框架
- `pyautogui` / `pyperclip` — 辅助输入
