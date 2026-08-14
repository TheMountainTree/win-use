---
name: win-use
description: Windows 桌面自动化工具 — 通过 UIA、selector、条件等待和 loop agent 常驻进程操控 Windows
---

# win-use — Windows Computer Use for AI Agents

通过 `uiautomation` 库读取 Windows UIA 无障碍树，实现窗口管理和元素操控。

## 🔴 Agent 核心规则：使用 loop agent 常驻进程

**核心理念是 loop agent 常驻进程。** `python -m win_use` 启动后进入 stdin/stdout
JSON-lines REPL：agent 逐行发送 `{"cmd": "...", "args": {...}}`，进程逐行返回
`{"success": true/false, ...}`。单进程复用 COM 上下文，消除 ~500ms/次的进程启动惩罚。

> 一个 5 步操作 (`read → click → type → keys → screenshot`)：
> - 逐条独立 CLI（旧模式）：~3.0s（5 × 500ms 启动 + 各步骤耗时）
> - loop agent REPL：~0.15s（1 × 启动 + 各步骤耗时，无重复启动开销）

### 🟡 会话开始时先启动常驻进程

**每次会话开始时，先 `python -m win_use` 启动常驻进程**，通过 stdin/stdout 逐条交互。
不可用时让用户 `pip install -e .`。不要用 `conda run` / 手动拼 `sys.argv` 绕过入口。

```bash
# 启动常驻进程（阻塞式，通过 stdin/stdout 交互）
python -m win_use

# 每行发送一个 JSON 命令，每行收到一个 JSON 响应
{"cmd": "apps", "args": {"action": "list"}}
{"cmd": "read", "args": {"window": "记事本", "mode": "compact"}}
{"cmd": "click", "args": {"id": 5}}
```

或通过管道一次性发送多条命令：

```bash
echo '{"cmd":"apps","args":{"action":"list"}}' | python -m win_use
```

stdin 关闭（EOF）时进程优雅退出。

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

## 执行策略：默认走快速路径

先判断任务属于哪种模式，不要机械地在每一步之间执行 `read`：

| 场景 | 推荐方式 |
|---|---|
| 已知窗口、操作流程和目标元素名称 | 逐条发送命令，优先使用 selector + `wait_for` |
| 已知窗口，但不清楚元素名称或结构 | 一次目标窗口 `compact read`，然后逐条操作 |
| 未知窗口名称 | 一次 `apps list`，确认后进入快速路径 |
| 多步探索式交互 | 常驻进程内逐条命令（每次无启动开销） |
| selector 找不到元素、界面结构未知 | 对目标窗口执行 `full read` 诊断 |
| 需要确认业务结果 | 使用 `wait_for` 或 `screenshot` |

### 性能规则

1. **会话开始时启动常驻进程**，后续所有命令通过 stdin/stdout 逐条发送，无进程启动开销。
2. **已知目标元素名称时直接使用 selector**（通过 `wait_for`），不要为了获取 ID 先执行 `read`。
3. **只读取目标窗口**，不要默认读取全部桌面。
4. **常规探索使用 `mode: compact`**；仅在 compact 信息不足时使用 `full`。
5. **使用 `wait_for` 等待界面变化**（基于 UIA 事件通知，自动降级轮询），不要使用固定 `wait 1`、`wait 2`。
6. **输入文字优先使用 `delay: 0`**，通过剪贴板一次性粘贴。
7. **优先使用 Name、AutomationId、ClassName 和控件类型定位**；坐标点击仅作最后降级。
8. **不要在确定性操作之间重复 read**。只有界面结构未知或操作失败后才重新读取。
9. `apps focus` 会自动恢复最小化窗口；仅在布局依赖最大化尺寸时使用 `apps maximize`。
10. `timeout` 是最大等待时间，不是固定休眠；通常保持 `5` 秒即可。
11. 已知目标窗口时不要调用 `apps list`，避免返回无关窗口和浪费 token。
12. **普通文字只能使用 `type`，快捷键才使用 `keys`**。不要用 `keys` 输入搜索词或消息。
13. `type` 默认使用字面量粘贴，并移除 Agent/shell 意外传入的整段外层引号。
14. **首次探索先用 `read`（windows 模式）扫描窗口**，然后再 `read --window "X"` 深入目标窗口。

### 快速路径示例

逐条发送命令（常驻进程内，无启动开销）：

```json
{"cmd": "apps", "args": {"action": "focus", "name": "目标窗口"}}
{"cmd": "keys", "args": {"keys": "{Ctrl}f"}}
{"cmd": "type", "args": {"text": "搜索内容", "delay": 0}}
{"cmd": "wait_for", "args": {"window": "目标窗口", "selector": {"name": "目标项", "match": "contains"}, "timeout": 5}}
{"cmd": "click", "args": {"id": 5}}
{"cmd": "wait_for", "args": {"window": "目标窗口", "selector": {"name": "预期元素"}}}
{"cmd": "screenshot", "args": {"output": "result.png"}}
```

每条命令返回 `success` 和结构化结果。根据结果决定下一步操作。

## 探索工作流

仅当目标窗口或元素未知时，按下面顺序逐步探索。

### 第一步：列出所有窗口

```json
{"cmd": "apps", "args": {"action": "list"}}
```

输出当前所有可见窗口，包含 `id`、`name`、`class_name`、`automation_id`、`state`。
仅在不知道目标窗口名称、窗口不存在或存在多个歧义窗口时执行。

### 第二步：读取目标窗口的元素树

```json
// 先扫描所有窗口（windows 模式 = tree -L 1，极快）
{"cmd": "read", "args": {}}

// 对目标窗口做 compact 读取（只输出可交互元素）
{"cmd": "read", "args": {"window": "窗口名称", "mode": "compact"}}

// 深度诊断时用 full 模式
{"cmd": "read", "args": {"window": "窗口名称", "mode": "full", "depth": 8}}

// 只读活动窗口
{"cmd": "read", "args": {"active": true, "mode": "compact"}}
```

读取模式由 Agent 按需选择：

- `windows`（**无 window 时的默认**）：只列出顶层窗口元数据（名、类、状态、坐标），不做深度遍历。等同于 `tree -L 1`，极快。
- `compact`（**有 window 时的默认**）：只输出目标窗口和可交互元素，适合常规操作。
- `full`：完整 UIA JSON 树，适合诊断、探索未知界面。

输出中每个元素包含：
- `id` — 运行时分配的整数 ID（后续操作用此 ID 定位）
- `type` — 控件类型（Button、Edit、ListItem 等）
- `name` — 元素名称
- `automation_id` — UIA AutomationId（系统级标识，比 name 更稳定）
- `bounds` — 屏幕坐标 `{x, y, w, h}`
- `patterns` — 支持的交互模式

### 第三步：确认目标元素位置

分析上一步输出，确认：
- 目标按钮/输入框的 `id` 是多少
- 元素的 `bounds` 坐标是否合理（不要点击 0,0）
- 如果有多个相似元素，通过 `name`、`automation_id`、位置区分

### 第四步：逐步操作

```json
// 聚焦窗口（支持 Name、ClassName、AutomationId 多字段匹配）
{"cmd": "apps", "args": {"action": "focus", "name": "记事本"}}
{"cmd": "apps", "args": {"action": "focus", "name": "记事本", "index": 1}}

// 点击元素（id 来自 read 输出）
{"cmd": "click", "args": {"id": 5}}

// 或按坐标点击
{"cmd": "click", "args": {"x": 300, "y": 200}}

// 输入文字
{"cmd": "type", "args": {"text": "hello world"}}

// 按键
{"cmd": "keys", "args": {"keys": "{Ctrl}c"}}
{"cmd": "keys", "args": {"keys": "{Enter}"}}
{"cmd": "keys", "args": {"keys": "{Win}r"}}

// 滚动
{"cmd": "scroll", "args": {"direction": "down", "amount": 300}}

// 截图确认结果
{"cmd": "screenshot", "args": {"output": "result.png"}}
```

### 第五步：验证

操作后用 screenshot 确认界面变化是否符合预期。

### 截图辅助定位（opaque app 降级策略）

部分应用（Qt 自绘、Chrome Web App、Electron）不通过 UIA 暴露内部控件。
`read` 的 compact/full 输出中会包含 `opaque_app: true` 标记，Agent 应自动降级为截图定位：

```json
// 第一步：检测 opaque
{"cmd": "read", "args": {"window": "LobeHub", "mode": "compact"}}
// → {"opaque_app": true, "opaque_reason": "共 11 个元素...无实际交互控件"}

// 第二步：截图降级
{"cmd": "screenshot", "args": {"window": "LobeHub", "output": "lobehub.png"}}
// 或 base64 用于视觉模型分析
{"cmd": "screenshot", "args": {"window": "LobeHub", "base64": true}}

// 第三步：视觉模型分析截图获得元素坐标
// (Agent 内部处理)

// 第四步：坐标点击 + 输入
{"cmd": "click", "args": {"x": 800, "y": 1020}}
{"cmd": "type", "args": {"text": "提问内容", "delay": 0}}
{"cmd": "keys", "args": {"keys": "{Enter}"}}
```

**Agent 截图降级决策树**：

| `opaque_app` | `opaque_warning` | 策略 |
|---|---|---|
| `true` | — | **必须**截图 → **必须送给视觉模型**分析坐标 → 坐标点击 |
| `false` | 有 `opaque_warning` | 可先用 UIA selector 点击；失败时截图检查 |
| `false` | 无 | 直接用 UIA selector/id 定位 |

**🔴 截图降级不可"估算"坐标。Agent 必须执行以下完整流程**：

```
1. 截图 → 2. 读取截图文件 → 3. 视觉模型分析 → 4. 提取精确坐标 → 5. 坐标点击
```

**禁止行为**：
- ❌ 截图后不看图，用"窗口左上角 + 估算偏移"盲猜坐标
- ❌ 用窗口 bounds 推算"大概中间是输入框"
- ❌ 截了 base64 但不传给视觉模型分析

**截图技巧**：
- `window: "X"` 只截取目标窗口区域，减少无关信息和 token 消耗
- `base64: true` 返回 base64 编码，直接供视觉模型使用
- `overlay_grid` 在截图上叠加编号坐标点网格，返回每个点的屏幕绝对坐标映射

### 编号坐标点叠加（`overlay_grid`）

Opaque app 截图时可启用 `overlay_grid`，在窗口截图上叠加等间距编号红点：

```json
{"cmd": "screenshot", "args": {"window": "LobeHub", "overlay_grid": 150, "output": "lobehub.png"}}
```

**但 Agent 不应直接使用 `overlay_grid` + 手动分析**。应使用 `locate_vision` 命令，该命令内部完成截图→overlay→视觉模型→坐标的完整闭环：

```json
// 一步到位：截图+overlay+视觉模型 → 直接返回屏幕坐标
{"cmd": "locate_vision", "args": {"window": "LobeHub", "target": "页面底部的聊天输入框"}}

// 返回：
// {"success": true, "screen_x": 1580, "screen_y": 1098, "nearest_dot": 645, "offset": {"x": 35, "y": -12}}
```

**Agent 完整开源路径**：
```json
{"cmd": "apps", "args": {"action": "focus", "name": "微信"}}
{"cmd": "read", "args": {"window": "微信", "mode": "compact"}}
// → {"opaque_app": true}  ← 检测到 opaque

{"cmd": "locate_vision", "args": {"window": "微信", "target": "底部消息输入框"}}
// → {"screen_x": 1200, "screen_y": 980}  ← 直接可用的屏幕坐标

{"cmd": "click", "args": {"x": 1200, "y": 980}}
{"cmd": "type", "args": {"text": "消息", "delay": 0}}
{"cmd": "keys", "args": {"keys": "{Enter}"}}
```

**`locate_vision` 参数**：
- `window`：目标窗口名称
- `target`：要定位的元素自然语言描述
- `model`：视觉模型，默认 `gpt-4o`
- `api_key`：API Key（默认用 `OPENAI_API_KEY` 环境变量）
- `base_url`：自定义 API 端点
- `spacing`：overlay 网格间距，默认 150px

**返回字段**：`screen_x`, `screen_y`（可直接用于 `click`）、`nearest_dot`, `offset`

### Selector 支持字段

```json
{
  "name": "文本名称",
  "automation_id": "系统标识",
  "class_name": "窗口或控件类名",
  "type": "Button",
  "match": "contains",
  "enabled": true,
  "visible": true
}
```

- `match` 支持 `contains`、`exact`、`starts_with`、`ends_with`
- selector 默认大小写不敏感
- 使用 `window` 限定目标窗口，避免扫描全部应用
- 使用 `index` 选择多个匹配中的第 N 个
- 使用 `timeout` 等待目标出现；条件一满足就立即继续，不会等待完整超时时间

`wait_for` 可以直接使用 selector，无需先 `read` 获取 ID，并会自动等待元素出现：

```json
{"cmd": "wait_for", "args": {"window": "Weixin", "selector": {"name": "长夜无荒", "match": "contains", "type": "ListItem"}, "timeout": 5}}
```

等待界面变化时使用条件等待，避免固定等待：

```json
{"cmd": "wait_for", "args": {"window": "Weixin", "selector": {"name": "长夜无荒"}, "state": "present", "timeout": 5}}
```

### 快速失败恢复

某一步失败时，不要从头重复整个慢流程：

1. 查看失败响应的 `error` 和 `error_type`。
2. selector 过宽时增加 `type`、`automation_id` 或改用 `match: exact`。
3. selector 找不到时，仅对目标窗口执行一次：

```json
{"cmd": "read", "args": {"window": "目标窗口", "mode": "compact", "depth": 6}}
```

4. compact 仍不足时，再使用 `mode: full`。
5. 修正 selector 后重新发送 `wait_for` 或 `click`。

### 成功语义

- 操作步骤的 `success: true`：输入、按键或点击已成功派发。
- `wait_for` 的 `success: true`：预期 UIA 条件已经满足。
- 截图成功：截图文件已生成。
- 操作派发成功不等于业务目标完成。发送消息、提交表单等关键操作必须追加
  `wait_for` 或截图验证。

### 文本输入与引号

普通文本输入：

```json
{"cmd": "type", "args": {"text": "长夜无荒"}}
```

即使 Agent 误把整段外层引号作为文本传入，`type` 默认也会移除最多三层匹配的单引号、
双引号或中文弯引号。

确实需要在输入内容最外层保留引号：

```json
{"cmd": "type", "args": {"text": "\"需要保留引号\"", "preserve_outer_quotes": true}}
```

- JSON 字段语法中的 `"text": "长夜无荒"` 外层引号只是 JSON 语法，不会被输入。
- 不要写 `"text": "\"长夜无荒\""`，除非确实需要输入引号。
- `delay: 0` 使用剪贴板按字面量粘贴，推荐用于中文、引号、花括号和长文本。
- `keys` 会解释 `{Ctrl}`、`{Enter}` 等按键语法，只用于快捷键。

## 窗口匹配规则

窗口操作（focus/close/minimize/maximize）按以下优先级模糊匹配：

1. **Name**（窗口标题）
2. **AutomationId**（UIA 系统标识，最稳定）
3. **ClassName**（窗口类名）

当匹配到多个窗口时，默认操作第一个。使用 `index` 选择其他匹配项。

```json
// 示例：有两个"记事本"窗口
{"cmd": "apps", "args": {"action": "focus", "name": "记事本"}}           // 聚焦第一个
{"cmd": "apps", "args": {"action": "focus", "name": "记事本", "index": 1}} // 聚焦第二个
```

## 常见操作模式（探索或降级）

以下逐条命令用于探索未知界面或修复失败步骤。

### 打开应用并操作

```json
{"cmd": "apps", "args": {"action": "launch", "name": "notepad"}}
{"cmd": "apps", "args": {"action": "focus", "name": "记事本"}}
{"cmd": "read", "args": {"window": "记事本", "mode": "compact"}}
{"cmd": "click", "args": {"id": 1}}
{"cmd": "type", "args": {"text": "输入内容"}}
```

### 在浏览器中操作

```json
{"cmd": "apps", "args": {"action": "list"}}
{"cmd": "read", "args": {"window": "Chrome", "mode": "compact"}}
{"cmd": "click", "args": {"id": 1}}
{"cmd": "type", "args": {"text": "https://example.com"}}
{"cmd": "keys", "args": {"keys": "{Enter}"}}
```

### 处理多窗口场景

```json
{"cmd": "apps", "args": {"action": "list"}}
// 如果输出显示两个 VS Code 窗口：
//   { "id": 3, "name": "app.ts - VS Code", ... }
//   { "id": 5, "name": "README.md - VS Code", ... }

// 用具体的名称子串区分
{"cmd": "apps", "args": {"action": "focus", "name": "app.ts"}}
// 或匹配 class_name
{"cmd": "apps", "args": {"action": "focus", "name": "MozillaWindowClass", "index": 0}}
```

## 注意事项

- 每次 `read` 会刷新元素 ID；内存缓存跨命令复用，下一次 read 后旧 ID 失效
- `safe_name()` 返回空字符串时，优先用 `automation_id` 或 `class_name` 定位窗口
- 动态标题的窗口（浏览器、IDE）建议用 `class_name` 匹配
- 先 focus 窗口再 read，确保读到的是目标窗口的前台状态
