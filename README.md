# win-use — Windows Computer Use CLI for AI Agents

A Python CLI that exposes the Windows UI Automation (UIA) accessibility tree as structured JSON, enabling AI agents to observe and control the Windows desktop.

- **Python**: 3.10+
- **Platform**: Windows only
- **Core dependency**: [`uiautomation`](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows)

## Installation

```bash
pip install -e .
```

Or install from source:

```bash
git clone <repo-url> && cd win-use
pip install .
```

## Quick Start

```bash
# List all visible windows
win-use apps list

# Read the accessibility tree of a specific window (compact mode — interactive elements only)
win-use read --window "Notepad" --mode compact

# Click element ID 5 (ID comes from the `read` output above)
win-use click --id 5

# Type text
win-use type "Hello, world!"

# Send a key combination
win-use keys "{Ctrl}s"

# Take a screenshot
win-use screenshot -o screenshot.png
```

## Commands

| Command | Description |
|---|---|
| `win-use read` | Read the UIA accessibility tree as JSON |
| `win-use click` | Click an element (by ID or coordinates) |
| `win-use type` | Type literal text (clipboard paste by default) |
| `win-use keys` | Send a key combination (e.g. `{Ctrl}c`) |
| `win-use scroll` | Scroll at a position or the cursor |
| `win-use move` | Move the mouse to coordinates |
| `win-use drag` | Drag from one point to another |
| `win-use wait` | Pause for N seconds |
| `win-use apps` | Manage windows (list / focus / launch / close / minimize / maximize) |
| `win-use screenshot` | Capture the screen (PNG file or base64) |
| `win-use shell` | Execute a PowerShell command |
| `win-use batch` | Run a multi-step workflow from a JSON file |

### `win-use read`

```
win-use read [--window NAME] [--active] [--depth N] [--mode full|compact] [--output file.json]
```

- `--window, -w` — filter to a specific window (fuzzy name match)
- `--active, -a` — read only the currently active window
- `--depth, -d` — max recursion depth (default: 4)
- `--mode full|compact` — `full` outputs the complete tree; `compact` returns only interactive elements
- `--all` — include background and minimized windows
- `--output, -o` — save JSON to file

Each element in the output has:

- `id` — runtime integer ID used for subsequent `click`, etc.
- `type` — control type (`Button`, `Edit`, `ListItem`, …)
- `name`, `automation_id`, `class_name` — identifying properties
- `bounds` — bounding rectangle (`x`, `y`, `w`, `h`)
- `enabled`, `offscreen` — state flags

### `win-use click`

```
win-use click --id N              # click an element by its read-time ID
win-use click --x 500 --y 300     # click at screen coordinates
win-use click --id N --double     # double-click
win-use click --id N --button right
```

### `win-use type`

```
win-use type "some text"          # paste via clipboard (instant)
win-use type "slow text" --delay 50  # simulate keystrokes with 50ms delay
echo "text from pipe" | win-use type --stdin  # read from stdin
```

### `win-use keys`

```
win-use keys "{Ctrl}c"
win-use keys "{Win}r"
win-use keys "{Alt}{F4}"
```

### `win-use scroll`

```
win-use scroll down --amount 300
win-use scroll up --x 500 --y 400
```

### `win-use apps`

```
win-use apps list                        # list all visible windows
win-use apps focus "Notepad"             # bring a window to the foreground
win-use apps launch "notepad.exe"        # start an application
win-use apps close "Calculator"          # close a window
win-use apps minimize "Chrome"           # minimize
win-use apps maximize "Chrome"           # maximize
```

### `win-use screenshot`

```
win-use screenshot -o result.png         # save to file
win-use screenshot --base64              # output base64-encoded image
```

### `win-use shell`

```
win-use shell "Get-Process | Select-Object -First 5"
```

## Batch Workflows

The recommended way for AI agents to drive Windows is through **batch workflows** — a single JSON file that defines a sequence of steps executed in one process. This avoids round-trip latency between the agent and the CLI.

```bash
win-use batch workflow.json
```

### Workflow JSON Structure

```json
{
  "default_timeout": 5,
  "default_settle": 0.05,
  "steps": [
    {"action": "apps.focus", "name": "WeChat"},
    {"action": "keys", "keys": "{Ctrl}f"},
    {"action": "type", "text": "search query", "delay": 0},
    {
      "action": "click",
      "window": "WeChat",
      "selector": {"name": "target item", "match": "contains"},
      "timeout": 5
    },
    {"action": "type", "text": "Hello!", "delay": 0},
    {"action": "keys", "keys": "{Enter}"},
    {"action": "wait_for", "window": "WeChat", "selector": {"name": "confirmation"}},
    {"action": "screenshot", "output": "result.png"}
  ]
}
```

### Supported Batch Actions

| Action | Description |
|---|---|
| `apps.list` | List all visible windows |
| `apps.focus` | Focus a window by name |
| `apps.launch` | Launch an application |
| `apps.close` | Close a window |
| `apps.minimize` | Minimize a window |
| `apps.maximize` | Maximize a window |
| `read` | Read the UIA tree |
| `click` | Click an element (by selector or ID) |
| `double_click` | Double-click an element |
| `type` | Type text |
| `keys` | Send a key combination |
| `scroll` | Scroll at coordinates |
| `move` | Move the mouse |
| `drag` | Drag from one point to another |
| `wait` | Sleep for N seconds |
| `wait_for` | Wait until a selector matches an element |
| `screenshot` | Take a screenshot |

### Element Selectors

Selectors are JSON objects matched against UIA properties. Fuzzy matching priority: **Name > AutomationId > ClassName**.

```json
{"name": "OK", "match": "contains"}
{"automation_id": "btnSave", "visible": true}
{"class_name": "Button", "name": "Submit"}
```

- `match` — `contains` (default), `exact`, `startswith`, or `regex`
- `visible` — filter to visible elements only
- `enabled` — filter to enabled elements only
- `index` — pick the N-th match (0-based)

### Output

Each step returns `success`, `elapsed_ms`, and its `result` (or `error` on failure). The top-level response also has `success` and `total_elapsed_ms`. Execution stops on the first failure.

## Project Structure

```
win_use/
├── __init__.py      # package version
├── cli.py           # Typer CLI entry point
├── reader.py        # UIA tree reader (full / compact mode)
├── actions.py       # mouse, keyboard, scroll, drag
├── apps.py          # window enumeration, focus, launch, close
├── batch.py         # workflow engine
├── cache.py         # temporary element cache (cross-process)
├── locator.py       # element resolution from cached locators
├── selectors.py     # selector matching & wait_for
├── screen.py        # screenshot capture
└── utils.py         # safe UIA property reads, window filtering
```

## Design Principles

- **AI-first** — all output is structured JSON; no human-readable formatting
- **Stateless CLI** — each command runs in its own process; element references persist via a temporary cache file
- **Progressive enhancement** — coordinate clicks → ID-based clicks → semantic selectors, each layer increasing robustness
- **Fault-tolerant** — all UIA property reads are wrapped in try/except; failures return defaults rather than crashing

## License

MIT
