# win-use 设计文档

> **版本**: 0.2.0  
> **语言**: Python 3.10+  
> **平台**: Windows 专属  
> **定位**: 为 AI Agent 提供操控 Windows 桌面的命令行工具

---

## 1. 项目概述

### 1.1 背景与动机

AI Agent 需要一个标准化的接口来观察和操控图形用户界面。在 Windows 平台上，Microsoft UI Automation (UIA) 提供了完整的无障碍树访问能力，但原生 API 复杂、面向 COM，不适合 AI 直接消费。**win-use** 将 UIA 能力封装为简洁的 CLI 命令和结构化 JSON 输出，使任何 AI Agent 都能轻松执行 Windows 桌面自动化任务。

### 1.2 核心能力

| 能力 | 命令 | 说明 |
|------|------|------|
| 观察 | `read` | 读取 UIA 无障碍树，输出结构化 JSON |
| 操作 | `click / type / keys / scroll / drag` | 模拟鼠标键盘操作 |
| 窗口 | `apps list / focus / launch / close` | 窗口与应用生命周期管理 |
| 截图 | `screenshot` | 截取当前屏幕 |
| 条件等待 | `wait_for` | 基于 UIA 事件的条件等待，自动降级轮询 |
| 视觉定位 | `locate_vision` | 截图 + overlay → 视觉模型 → 精确坐标 |
| 系统 | `shell` | 执行 PowerShell 命令，获取标准输出 |

### 1.3 设计原则

- **AI-First**: 所有输出均为结构化 JSON，无人类可读格式
- **Loop Agent 常驻进程**: 单进程复用 COM 上下文，通过 stdin/stdout JSON-lines 逐条交互，消除进程启动开销
- **渐进增强**: 从坐标点击 → ID 点击 → 语义选择器，三种定位策略逐级提升鲁棒性
- **容错优先**: 所有 UIA 属性读取包裹 `try/except`，失败返回默认值而非崩溃

---

## 2. 系统架构

### 2.1 分层架构

```mermaid
graph TB
    subgraph "REPL 层"
        CLI[cli.py<br/>stdin/stdout JSON-lines REPL]
    end

    subgraph "分发层"
        DISPATCH[dispatch.py<br/>命令分发 + LoopContext]
    end

    subgraph "业务逻辑层"
        READER[reader.py<br/>UIA 树读取]
        ACTIONS[actions.py<br/>输入操作]
        APPS[apps.py<br/>窗口管理]
        SCREEN[screen.py<br/>截图]
        VISION[vision.py<br/>视觉定位]
    end

    subgraph "定位与缓存层"
        CACHE[cache.py<br/>内存缓存 + 文件兼容]
        LOCATOR[locator.py<br/>元素重定位]
        SELECTORS[selectors.py<br/>选择器匹配]
    end

    subgraph "基础设施层"
        UTILS[utils.py<br/>安全属性读取<br/>窗口过滤]
        UIA[uiautomation<br/>第三方 UIA 客户端]
        PYTHON[pyautogui / pyperclip<br/>辅助输入]
    end

    CLI --> DISPATCH
    DISPATCH --> READER
    DISPATCH --> ACTIONS
    DISPATCH --> APPS
    DISPATCH --> SCREEN
    DISPATCH --> VISION
    DISPATCH --> SELECTORS

    READER --> UTILS
    READER --> LOCATOR
    ACTIONS --> LOCATOR
    ACTIONS --> CACHE
    APPS --> UTILS
    SELECTORS --> UTILS
    LOCATOR --> UTILS

    UTILS --> UIA
    ACTIONS --> UIA
    ACTIONS --> PYTHON
    SCREEN --> PYTHON
```

### 2.2 模块职责

| 模块 | 职责 | 依赖 |
|------|------|------|
| `cli.py` | stdin/stdout JSON-lines REPL 主循环，预热 COM 上下文 | `dispatch` |
| `dispatch.py` | 命令分发核心，`dispatch(cmd, args, ctx)` 路由到各 handler，`LoopContext` 持有内存缓存 | 所有业务模块 |
| `reader.py` | 递归遍历 UIA 树，输出 full/compact/windows 三种 JSON | `utils`, `locator` |
| `actions.py` | 点击、输入、按键、滚动、拖拽、等待 | `locator`, `cache`, `uiautomation`, `pyautogui` |
| `apps.py` | 窗口列举、聚焦、启动、关闭、最小化/最大化 | `utils`, `uiautomation` |
| `screen.py` | 全屏截图，支持文件保存和 base64 输出 | `PIL.ImageGrab` |
| `vision.py` | 截图 + overlay → 视觉模型 → 精确坐标 | `screen`, `openai` |
| `cache.py` | 内存缓存构建 + 文件持久化（崩溃恢复/外部检查） | 文件系统 |
| `locator.py` | 根据缓存 locator 在最新 UIA 树中重新定位元素 | `utils` |
| `selectors.py` | 按 name/type/automation_id 等多字段查询元素，支持等待 | `utils` |
| `utils.py` | 安全属性读取、窗口过滤、元素判断、屏幕信息 | `uiautomation` |

---

## 3. 核心模块设计

### 3.1 无障碍树读取 (`reader.py`)

#### 3.1.1 两种输出模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `full` | 完整递归树，保留所有节点及其父子关系 | 调试、诊断、完整上下文理解 |
| `compact` | 仅保留窗口根节点 + 可交互元素（含 patterns 列表） | AI Agent 行动决策，减少 token 消耗 |

**compact 模式的过滤逻辑**:
- 窗口根节点始终保留
- 非交互元素被跳过，但其子元素仍被递归搜索（不丢失深层可交互元素）
- 零尺寸元素（bounds w/h ≤ 0）在 depth > 0 时被跳过

#### 3.1.2 元素数据结构

```json
{
  "id": 42,
  "type": "Button",
  "name": "确定",
  "automation_id": "confirmBtn",
  "bounds": {"x": 100, "y": 200, "w": 80, "h": 30},
  "enabled": true,
  "offscreen": false,
  "children": [43, 44],
  "patterns": ["Invoke"],
  "window_state": "normal"
}
```

#### 3.1.3 自增 ID 机制

- 遍历过程中使用 `id_counter`（列表包装实现闭包可变）为每个保留元素分配递增整数 ID
- ID 在单次 `read` 调用内唯一，跨调用不保证稳定性
- 配合 `cache.py` 实现跨 CLI 进程的"先 read 后 click"模式

### 3.2 元素定位 (`locator.py`)

#### 3.2.1 Locator 结构

```json
{
  "window": {
    "native_window_handle": 123456,
    "name": "记事本",
    "class_name": "Notepad",
    "automation_id": ""
  },
  "path": [0, 2, 1],
  "runtime_id": [42, 123456],
  "name": "确定",
  "class_name": "Button",
  "automation_id": "confirmBtn",
  "type": "Button"
}
```

#### 3.2.2 两阶段重定位策略

```
定位流程:
1. 窗口定位（优先级递减）:
   a. NativeWindowHandle 直接句柄获取
   b. AutomationId 精确匹配
   c. Name 精确匹配
   d. ClassName 精确匹配

2. 元素定位:
   a. 路径定位: 按 locator.path 沿树路径定位，再用 _same_element 校验
   b. 广度搜索: 路径失效时在目标窗口内 BFS 搜索（上限 5000 节点）
      - 优先 RuntimeId 匹配（完全等于）
      - 其次 type + automation_id 匹配
      - 再次 name + class_name 匹配
```

#### 3.2.3 元素一致性校验 (`_same_element`)

校验优先级:
1. `runtime_id` 完全相等 → 精确匹配
2. `type` 相同 + `automation_id` 非空且相等
3. `name` 相同 + 可选 `class_name` 相同
4. 仅 `class_name` 相同

### 3.3 元素缓存 (`cache.py`)

#### 3.3.1 设计目标

常驻进程模式下，`read` 和 `click --id N` 在同一进程内执行，可直接共享内存缓存。
同时保留文件持久化以支持崩溃恢复和外部检查。

#### 3.3.2 实现方案

- **内存缓存**: `LoopContext.element_cache` 字典，`read` 填充，`click --id` 直接 O(1) 查找
- **文件兼容**: `save_elements_cache` 同步写入 `%TEMP%/win-use/last-read.json`（`WIN_USE_CACHE_PATH` 可覆盖）
- **原子写入**: 先写临时文件，再 `replace`，避免并发读写脏数据
- **构建内存缓存**: `build_memory_cache(elements)` 从 read_screen 输出构建 `{id: record}` 字典

#### 3.3.3 缓存记录结构

```json
{
  "42": {
    "id": 42,
    "bounds": {"x": 100, "y": 200, "w": 80, "h": 30},
    "name": "确定",
    "type": "Button",
    "locator": { /* 完整 locator */ }
  }
}
```

### 3.4 动作模块 (`actions.py`)

#### 3.4.1 点击（Click）

两种调用模式:
- **坐标点击**: `click(coords=(x, y))` — 直接屏幕坐标
- **元素点击**: `click(element_id=42, elements_cache=cache)` — 先通过缓存 + locator 解析坐标

元素点击的安全检查:
1. locator 解析 → 元素是否存在
2. `IsOffscreen` 检查 → 是否在可视区域
3. bounds 有效性 → 是否有可点击区域
4. 坐标范围 → 是否在屏幕内（|x|, |y| ≤ 30000）

#### 3.4.2 文字输入（Type）

两种输入模式:

| 模式 | 触发条件 | 实现 | 适用场景 |
|------|---------|------|---------|
| 粘贴模式 | `delay == 0` | `pyperclip` 复制 + `Ctrl+V` | 快速输入，保留特殊字符 |
| 逐字模式 | `delay > 0` | `uiautomation.SendKeys` | 需要模拟真实输入速度 |

**引号智能剥离**: AI Agent 经常将文本包裹在引号中传入 CLI。`normalize_text_input` 最多去除三层匹配的成对引号（`""`, `''`, `""`, `''`）。

#### 3.4.3 组合键（Keys）

使用 `uiautomation.SendKeys` 的格式化字符串语法:

| 示例 | 效果 |
|------|------|
| `{Ctrl}c` | Ctrl+C |
| `{Alt}{F4}` | Alt+F4 |
| `{Win}r` | Win+R |
| `{Enter}` | Enter |

### 3.5 窗口管理 (`apps.py`)

#### 3.5.1 窗口定位

多字段模糊匹配，优先级递减:

```
Name > AutomationId > ClassName
```

每个字段使用**大小写不敏感的包含匹配**。多个候选时通过 `--index` 参数选择。

#### 3.5.2 聚焦窗口

```
1. 按名称查找目标窗口（轮询等待出现，默认超时 2s）
2. 若最小化，先调用 SetWindowVisualState(0) 恢复
3. 调用 WindowPattern.SetWindowVisualState(0) 或 SendKey {Alt} 切换焦点
```

#### 3.5.3 启动应用

```
1. 尝试直接以名称运行（如 "notepad"）
2. 若失败，尝试 shell:AppsFolder 查找并启动 UWP 应用
3. 轮询等待窗口出现（默认超时 2s）
```

### 3.6 命令分发 (`dispatch.py`)

#### 3.6.1 设计动机

loop agent 常驻进程模式下，agent 逐条发送命令、逐条获取结果、根据结果决定下一步。
`dispatch(cmd, args, ctx)` 是单一分发入口，路由到各 handler 函数，`LoopContext` 持有跨命令的内存状态。

#### 3.6.2 支持的命令

```
read / click / type / keys / scroll / move / drag / wait / wait_for
apps / screenshot / locate_vision / shell
```

#### 3.6.3 REPL 协议

请求（每行一个 JSON）：
```json
{"cmd": "read", "args": {"window": "记事本", "mode": "compact"}}
```

响应（每行一个 JSON）：
```json
{"success": true, "mode": "compact", "elements": [...]}
```

错误：
```json
{"success": false, "error": "...", "error_type": "ValueError"}
```

#### 3.6.4 `wait_for` 条件等待

```json
{
  "cmd": "wait_for",
  "args": {
    "selector": {"name": "就绪", "visible": true},
    "state": "present",
    "timeout": 10,
    "poll_interval": 0.1,
    "index": 0,
    "depth": 8
  }
}
```

| 参数 | 说明 |
|------|------|
| `selector` | 多字段匹配条件（name/automation_id/class_name/type/enabled/visible） |
| `state` | `"present"` 等待出现 / `"absent"` 等待消失 |
| `timeout` | 超时秒数，超时抛 `TimeoutError` |
| `poll_interval` | 轮询间隔秒数 |
| `index` | 多匹配时选择第几个 |
| `depth` | UIA 树搜索深度 |
| `match` | `"contains"` / `"exact"` / `"starts_with"` / `"ends_with"` |

#### 3.6.5 错误处理

所有异常在 `dispatch` 层统一捕获，返回 `{"success": false, "error": ..., "error_type": ...}`，
不会导致进程崩溃。agent 可根据 `error_type` 决定重试或调整策略。

### 3.7 选择器系统 (`selectors.py`)

#### 3.7.1 选择器字段

```json
{
  "name": "确定",
  "automation_id": "confirmBtn",
  "class_name": "Button",
  "type": "Button",
  "enabled": true,
  "visible": true,
  "match": "contains"
}
```

所有文本字段支持四种匹配模式:
- `contains`（默认）: 大小写不敏感子串匹配
- `exact`: 大小写不敏感精确匹配
- `starts_with`: 大小写不敏感前缀匹配
- `ends_with`: 大小写不敏感后缀匹配

#### 3.7.2 搜索策略

1. 确定搜索根：指定 window 名称 → 模糊匹配窗口；`active: true` → 活动窗口；否则 → 所有顶层窗口
2. BFS 遍历，最大深度 `max_depth`
3. 每个元素过 `element_matches` 判定

### 3.8 截图模块 (`screen.py`)

- 使用 `PIL.ImageGrab.grab()` 全屏截图
- 支持保存为 PNG/JPEG 文件
- 支持 base64 编码返回，适合 AI 视觉模型消费
- JPEG 质量可配置（默认 85）

---

## 4. 数据流

### 4.1 Loop Agent REPL 模式

```mermaid
sequenceDiagram
    participant AI as AI Agent
    participant REPL as cli.py REPL
    participant D as dispatch.py
    participant R as reader.py
    participant C as cache.py
    participant A as actions.py
    participant L as locator.py
    participant UIA as UIA 树

    Note over AI,UIA: 进程启动：预热 COM 上下文
    AI->>REPL: stdin: {"cmd":"read","args":{"mode":"compact"}}
    REPL->>D: dispatch("read", args, ctx)
    D->>R: read_screen()
    R->>UIA: 递归遍历
    UIA-->>R: 元素属性
    R->>C: build_memory_cache() + save_elements_cache()
    C-->>D: ctx.element_cache 填充
    D-->>REPL: {"success":true, "elements":[...]}
    REPL-->>AI: stdout: JSON 一行

    AI->>REPL: stdin: {"cmd":"click","args":{"id":42}}
    REPL->>D: dispatch("click", args, ctx)
    D->>A: click(element_id=42, elements_cache=ctx.element_cache)
    A->>L: resolve_element(locator)
    L->>UIA: 搜索当前 UIA 树
    UIA-->>L: 匹配元素
    L-->>A: 元素引用
    A->>UIA: Click(x, y)
    A-->>D: {"success": true, ...}
    D-->>REPL: 结果
    REPL-->>AI: stdout: JSON 一行

    Note over AI,UIA: stdin 关闭 → 进程优雅退出
```

---

## 5. REPL 接口设计

### 5.1 命令总览

```
python -m win_use    # 启动 loop agent REPL

请求格式（每行一个 JSON）:
{"cmd": "...", "args": {...}}

命令集:
├── read        # 读取 UIA 无障碍树
│     window, active, depth, mode, all
│
├── click       # 点击元素或坐标
│     id 或 x/y, button, double
│
├── type        # 输入文字
│     text, delay, preserve_outer_quotes
│
├── keys        # 发送组合键
│     keys
│
├── scroll      # 滚动
│     direction, amount, x, y
│
├── move        # 移动鼠标
│     x, y
│
├── drag        # 拖拽
│     from_x, from_y, to_x, to_y
│
├── wait        # 等待秒数
│     seconds
│
├── wait_for    # 条件等待
│     selector, window, active, timeout, state
│
├── apps        # 窗口管理
│     action(list/focus/launch/close/minimize/maximize), name, index, timeout
│
├── screenshot  # 截图
│     output, base64, quality, window, overlay_grid
│
├── locate_vision  # 视觉定位
│     window, target, model, spacing
│
└── shell       # 执行 PowerShell
      command, timeout
```

### 5.2 输出规范

所有响应均为 JSON，每行一个，统一格式:

```json
{
  "success": true,
  "action": "click",
  "...": "..."
}
```

错误也通过同一 JSON 流返回（非 stderr）:

```json
{
  "success": false,
  "error": "...",
  "error_type": "ValueError"
}
```

---

## 6. 关键技术决策

### 6.1 为什么选择 uiautomation

| 候选库 | 优势 | 劣势 | 
|--------|------|------|
| **uiautomation** ✅ | 纯 Python，API 简洁，支持所有 UIA 模式 | 文档较少 |
| comtypes 直接调用 | 完全控制 | 代码量巨大，COM 生命周期管理复杂 |
| pywinauto | 成熟稳定 | 对某些现代控件支持不足 |
| Windows UI Automation API (C++) | 官方支持，最高性能 | 非 Python 生态，集成复杂 |

**选型理由**: `uiautomation` 提供了最简洁的 Python 封装，社区活跃，能满足读取 + 操作的核心需求。

### 6.2 常驻进程 vs 无状态 CLI

| 方案 | 优势 | 劣势 |
|------|------|------|
| **Loop Agent 常驻进程** ✅ | 复用 COM 上下文，消除 ~500ms/次启动开销；内存缓存 O(1) 查找 | 需管理进程生命周期 |
| 无状态 CLI（每次新进程） | 实现简单，无状态 | 每次启动重复初始化 UIA，延迟高 |
| 本地 Socket IPC | 支持多客户端 | 协议复杂，需端口发现 |

**选型理由**: loop agent 常驻进程通过 stdin/stdout JSON-lines 逐条交互，单进程复用 COM 上下文，
消除进程启动惩罚。内存缓存为主、文件为辅（崩溃恢复/外部检查），兼顾性能与可靠性。

### 6.3 三级定位策略

| 级别 | 定位方式 | 优势 | 劣势 |
|------|---------|------|------|
| 1 | 屏幕坐标 `--x --y` | 无依赖，100% 可靠 | 分辨率/DPI 敏感，不支持窗口移动 |
| 2 | 缓存 ID `--id N` | 相对鲁棒 | 需先 read，跨进程缓存 |  
| 3 | 语义选择器 `selector` | 最鲁棒，语义化 | 通过 `wait_for` 命令支持，可能有歧义 |

**选型理由**: 渐进增强设计。坐标点击作为保底方案；ID 定位满足大部分场景；语义选择器为复杂工作流提供最佳鲁棒性。

### 6.4 compact 模式的剪枝策略

compact 模式不简单丢弃非交互元素，而是**跳过显示但递归搜索子元素**。这确保：
- 可交互元素不被中间容器隐藏
- token 消耗大幅降低（通常减少 70-90% 节点）
- 窗口层级结构仍然保真（通过 `children` 数组的 ID 引用）

---

## 7. 依赖关系

### 7.1 运行时依赖

| 包 | 版本 | 用途 |
|----|------|------|
| `uiautomation` | ≥2.0 | Windows UIA 客户端核心 |
| `Pillow` | ≥9.0 | 截图处理 |
| `pyautogui` | * | 辅助鼠标操作 |
| `pyperclip` | * | 剪贴板粘贴 |

### 7.2 可选依赖

| 包 | 用途 |
|----|------|
| `openai` ≥1.0 | `[vision]` extra: 结合截图的视觉分析 |

---

## 8. 扩展点与未来方向

### 8.1 已预留的扩展点

- **Vision 支持**: `setup.py` 中 `[vision]` extra 已预留，可接入 GPT-4V 等多模态模型分析截图
- **自定义选择器匹配**: `selectors.py` 的 `element_matches` 可扩展新的匹配字段和模式
- **新增命令**: 在 `dispatch.py` 的 `_COMMANDS` 注册表中添加 handler 函数即可
- **缓存策略可替换**: `WIN_USE_CACHE_PATH` 环境变量允许自定义缓存位置

### 8.2 已知限制

- **仅支持 Windows**: 依赖 UIA，无法跨平台
- **UWP 应用限制**: 部分 UWP 应用 UIA 暴露不完整
- **高 DPI 场景**: 需要额外的 DPI 缩放处理
- **并发安全**: 缓存文件无锁保护，多 Agent 并发需自行协调

### 8.3 未来方向

- MCP (Model Context Protocol) Server 封装，提供标准化的 Agent-桌面交互协议
- 基于视觉 + UIA 的混合定位，提高不可访问元素的定位成功率
- Windows 远程桌面场景下的自动化支持
- 录制回放功能

---

## 附录 A: 示例工作流（微信快速消息）

```json
{
  "default_timeout": 5,
  "default_settle": 0.05,
  "steps": [
    {"action": "apps.maximize", "name": "Weixin"},
    {"action": "apps.focus", "name": "Weixin"},
    {"action": "keys", "keys": "{Ctrl}f"},
    {"action": "type", "text": "长夜无荒", "delay": 0},
    {"action": "click", "window": "Weixin",
      "selector": {"name": "长夜无荒", "match": "contains", "visible": true}
    },
    {"action": "type", "text": "你好", "delay": 0},
    {"action": "keys", "keys": "{Enter}"},
    {"action": "screenshot", "output": "wechat_result.png"}
  ]
}
```

此工作流演示了完整的"打开微信 → 搜索联系人 → 发送消息 → 截图确认"自动化流程。

## 附录 B: 项目文件结构

```
win-use/
├── CLAUDE.md              # AI 上下文说明
├── setup.py               # 包安装配置
├── win-use.md             # 用户文档
├── examples/
│   └── wechat-fast.json   # 示例工作流
├── tests/
│   ├── __init__.py
│   └── test_core.py
└── win_use/
    ├── __init__.py         # 版本号
    ├── cli.py              # CLI 入口
    ├── reader.py           # UIA 树读取
    ├── actions.py          # 模拟操作
    ├── apps.py             # 窗口管理
    ├── batch.py            # 批处理引擎
    ├── screen.py           # 截图
    ├── cache.py            # 跨进程缓存
    ├── locator.py          # 元素重定位
    ├── selectors.py        # 选择器系统
    └── utils.py            # 工具函数
```
