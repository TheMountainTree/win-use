---
name: win-use
description: Windows 桌面自动化工具 — 通过 UIA、selector、条件等待和 batch 快速操控 Windows
---

# win-use — Windows Computer Use for AI Agents

通过 `uiautomation` 库读取 Windows UIA 无障碍树，实现窗口管理和元素操控。

## 执行策略：默认走快速路径

先判断任务属于哪种模式，不要机械地在每一步之间执行 `read`：

| 场景 | 推荐方式 |
|---|---|
| 已知窗口、操作流程和目标元素名称 | 一次 `batch` 完成，优先使用 selector |
| 已知窗口，但不清楚元素名称或结构 | 只执行一次目标窗口 `compact read`，然后用 `batch` |
| 未知窗口名称 | 执行一次 `apps list`，确认后进入快速路径 |
| selector 找不到元素、界面结构未知 | 对目标窗口执行 `full read` 诊断 |
| 需要确认业务结果 | 在 batch 末尾使用 `wait_for` 或 `screenshot` |

### 性能规则

1. **已知流程必须优先使用 `batch`**，避免 Agent 与 CLI 多次往返。
2. **已知目标元素名称时直接使用 selector**，不要为了获取 ID 先执行 `read`。
3. **只读取目标窗口**，不要默认读取全部桌面。
4. **常规探索使用 `--mode compact`**；仅在 compact 信息不足时使用 `full`。
5. **使用 `wait_for` 等待界面变化**，不要使用固定 `wait 1`、`wait 2`。
6. **输入文字优先使用 `"delay": 0`**，通过剪贴板一次性粘贴。
7. **优先使用 Name、AutomationId、ClassName 和控件类型定位**；坐标点击仅作最后降级。
8. **不要在确定性操作之间重复 read**。只有界面结构未知或操作失败后才重新读取。
9. `apps.focus` 会自动恢复最小化窗口；仅在布局依赖最大化尺寸时使用 `apps.maximize`。
10. `default_timeout` 是最大等待时间，不是固定休眠；通常保持 `5` 秒即可。
11. `default_settle` 推荐 `0.03-0.1` 秒。界面加载慢时增加 `wait_for`，不要全局增大 settle。
12. 已知目标窗口时不要在 batch 中调用 `apps.list`，避免返回无关窗口和浪费 token。
13. **普通文字只能使用 `type`，快捷键才使用 `keys`**。不要用 `keys` 输入搜索词或消息。
14. `type` 默认使用字面量粘贴，并移除 Agent/shell 意外传入的整段外层引号。
15. 复杂文本优先放入 batch JSON 文件或通过 `win-use type --stdin` 输入，避免 shell 多层转义。

### 快速路径模板

```json
{
  "default_timeout": 5,
  "default_settle": 0.05,
  "steps": [
    {"action": "apps.focus", "name": "目标窗口"},
    {"action": "keys", "keys": "{Ctrl}f"},
    {"action": "type", "text": "搜索内容", "delay": 0},
    {
      "action": "click",
      "window": "目标窗口",
      "selector": {"name": "目标项", "match": "contains"},
      "timeout": 5
    },
    {"action": "wait_for", "window": "目标窗口", "selector": {"name": "预期元素"}},
    {"action": "screenshot", "output": "result.png"}
  ]
}
```

保存为 JSON 后一次执行：

```bash
win-use batch workflow.json
```

默认遇到失败立即停止。检查最终输出中的顶层 `success`、每一步 `success`、
`elapsed_ms`、`result` 或 `error`。

## 探索工作流

仅当目标窗口或元素未知时，按下面顺序逐步探索。

### 第一步：列出所有窗口

```bash
win-use apps list
```

输出当前所有可见窗口，包含 `id`、`name`、`class_name`、`automation_id`、`state`。
仅在不知道目标窗口名称、窗口不存在或存在多个歧义窗口时执行。

### 第二步：读取目标窗口的元素树

```bash
win-use read --window "窗口名称" --mode compact
# 或只读活动窗口
win-use read --active --mode compact
```

读取模式由 Agent 按任务选择：

- `--mode full`：完整 UIA JSON 树，适合诊断、探索未知界面，默认模式
- `--mode compact`：只输出目标窗口和可交互元素，适合常规操作
- `--compact`：兼容旧调用，等价于 `--mode compact`

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

```bash
# 聚焦窗口（支持 Name、ClassName、AutomationId 多字段匹配）
win-use apps focus "记事本"              # 第一个匹配
win-use apps focus "记事本" --index 1    # 第二个匹配

# 点击元素（id 来自 read 输出）
win-use click --id 5

# 或按坐标点击
win-use click --x 300 --y 200

# 输入文字
win-use type "hello world"

# 按键
win-use keys "{Ctrl}c"
win-use keys "{Enter}"
win-use keys "{Win}r"

# 滚动
win-use scroll down --amount 300

# 截图确认结果
win-use screenshot -o result.png
```

### 第五步：验证

操作后用 screenshot 确认界面变化是否符合预期。

## 快速批处理

已知操作流程时，优先使用 `batch` 在单个进程中完成多步操作，减少 Agent 与 CLI
往返以及重复读取完整 UIA 树：

```bash
win-use batch examples/wechat-fast.json
```

工作流支持 `apps.*`、`read`、`click`、`double_click`、`type`、`keys`、`scroll`、
`move`、`drag`、`wait`、`wait_for`、`screenshot`。每一步返回：

- `success`：该步骤是否执行成功
- `elapsed_ms`：步骤耗时
- `result` 或 `error`：结构化结果或错误

`success: true` 表示操作已成功派发或条件已满足，不代表业务目标一定完成。关键步骤应
追加 `wait_for` 或截图验证。

`click` 可以直接使用 selector，无需先 `read` 获取 ID，并会自动等待元素出现。
等待界面变化时使用 `wait_for` 条件等待，避免固定 `wait`。

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

### 快速失败恢复

batch 某一步失败时，不要从头重复整个慢流程：

1. 查看失败步骤的 `error` 和 `elapsed_ms`。
2. selector 过宽时增加 `type`、`automation_id` 或改用 `match: exact`。
3. selector 找不到时，仅对目标窗口执行一次：

```bash
win-use read --window "目标窗口" --mode compact --depth 6
```

4. compact 仍不足时，再使用 `--mode full`。
5. 修正 selector 后重新执行剩余 batch。

### 成功语义

- 操作步骤的 `success: true`：输入、按键或点击已成功派发。
- `wait_for` 的 `success: true`：预期 UIA 条件已经满足。
- 截图成功：截图文件已生成。
- 操作派发成功不等于业务目标完成。发送消息、提交表单等关键操作必须追加
  `wait_for` 或截图验证。

### 文本输入与引号

普通文本输入：

```bash
win-use type "长夜无荒"
```

shell 用来包裹参数的引号不会被输入。即使 Agent 误把整段外层引号作为文本传入，
`type` 默认也会移除最多三层匹配的单引号、双引号或中文弯引号。

需要输入包含 shell 特殊字符的复杂文本时，优先使用 stdin：

```bash
echo '包含 "引号"、{花括号} 的内容' | win-use type --stdin
```

`--stdin` 默认移除管道附带的一个末尾换行，避免意外触发搜索或发送。确实需要保留该
换行时添加 `--preserve-stdin-newline`。

确实需要在输入内容最外层保留引号：

```bash
win-use type '"需要保留引号"' --preserve-outer-quotes
```

batch 中对应写法：

```json
{
  "action": "type",
  "text": "\"需要保留引号\"",
  "preserve_outer_quotes": true,
  "delay": 0
}
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

当匹配到多个窗口时，默认操作第一个。使用 `--index N` 选择其他匹配项。

```bash
# 示例：有两个"记事本"窗口
win-use apps focus "记事本"           # 聚焦第一个
win-use apps focus "记事本" --index 1 # 聚焦第二个
```

## 常见操作模式（探索或降级）

以下逐条命令仅用于探索未知界面或修复失败步骤。已知流程不要逐条调用，应合并为 batch。

### 打开应用并操作

```bash
win-use apps launch notepad
# 等待启动后
win-use apps focus "记事本"
win-use read --window "记事本" --compact
# 找到编辑区的 id，然后
win-use click --id <编辑区ID>
win-use type "输入内容"
```

### 在浏览器中操作

```bash
win-use apps list                    # 找到浏览器窗口
win-use read --window "Chrome" --compact
win-use click --id <地址栏ID>
win-use type "https://example.com"
win-use keys "{Enter}"
```

### 处理多窗口场景

```bash
win-use apps list
# 如果输出显示两个 VS Code 窗口：
#   { "id": 3, "name": "app.ts - VS Code", ... }
#   { "id": 5, "name": "README.md - VS Code", ... }

# 用具体的名称子串区分
win-use apps focus "app.ts"
# 或匹配 class_name
win-use apps focus "MozillaWindowClass" --index 0
```

## 注意事项

- 每次 `win-use read` 会刷新元素 ID；ID 会跨 CLI 进程缓存，下一次 read 后旧 ID 失效
- `safe_name()` 返回空字符串时，优先用 `automation_id` 或 `class_name` 定位窗口
- 动态标题的窗口（浏览器、IDE）建议用 `class_name` 匹配
- 先 focus 窗口再 read，确保读到的是目标窗口的前台状态
