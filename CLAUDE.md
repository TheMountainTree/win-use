# win-use — Windows Computer Use CLI

Python 包，通过 `uiautomation` 读取 Windows UIA 无障碍树，为 AI Agent 提供操控 Windows 桌面的能力。

## 项目结构

```
win_use/
├── __init__.py   # 版本号
├── cli.py        # Typer CLI 入口（read/click/type/keys/scroll/drag/screenshot/apps/shell）
├── reader.py     # 读取 UIA 树，输出结构化 JSON
├── actions.py    # 模拟操作：点击、输入、滚动、拖拽
├── apps.py       # 窗口管理：列出/聚焦/启动/关闭/最小化/最大化
├── screen.py     # 截图
└── utils.py      # 安全读取 UIA 属性、窗口过滤、元素判断
```

## 窗口定位方式

多字段模糊匹配（优先级：Name > AutomationId > ClassName），支持 `--index` 选择多匹配中的第 N 个。

## 元素定位方式

`win-use read --mode full|compact` 输出运行时自增 `id`。定位信息会持久化到临时缓存，
后续独立 CLI 进程中的 `click --id N` 会重新解析当前 UIA 元素后执行点击。

已知流程优先使用 `win-use batch <workflow.json>`。批处理支持 selector 直接点击和
`wait_for` 条件等待，每个步骤返回 `success`、`elapsed_ms` 和结构化结果。

## 关键依赖

- `uiautomation` — Windows UIA 客户端
- `typer` — CLI 框架
- `pyautogui` / `pyperclip` — 辅助输入
