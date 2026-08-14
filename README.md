# win-use — Windows Computer Use CLI for AI Agents

A Python package that exposes the Windows UI Automation (UIA) accessibility tree as structured JSON, enabling AI agents to observe and control the Windows desktop via a persistent loop-agent process.

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

`python -m win_use` starts a persistent REPL process. The agent sends one JSON request per line via stdin and receives one JSON response per line via stdout.

```bash
# Start the loop agent process
python -m win_use

# Each line is a JSON request:
{"cmd": "apps", "args": {"action": "list"}}
{"cmd": "read", "args": {"window": "Notepad", "mode": "compact"}}
{"cmd": "click", "args": {"id": 5}}
{"cmd": "type", "args": {"text": "Hello, world!"}}
{"cmd": "keys", "args": {"keys": "{Ctrl}s"}}
{"cmd": "screenshot", "args": {"output": "screenshot.png"}}
```

Or pipe commands directly:

```bash
echo '{"cmd":"apps","args":{"action":"list"}}' | python -m win_use
```

## REPL Protocol

**Request** (one JSON per line, UTF-8):

```json
{"cmd": "read", "args": {"window": "记事本", "mode": "compact"}}
```

**Response** (one JSON per line, UTF-8):

```json
{"success": true, "mode": "compact", "elements": [...]} 
```

**Error**:

```json
{"success": false, "error": "...", "error_type": "ValueError"}
```

EOF (stdin closed) exits the process gracefully.

## Commands

| cmd | args | description |
|-----|------|-------------|
| `read` | window, active, depth, mode, all | Read the UIA accessibility tree as JSON |
| `click` | id or x/y, button, double | Click an element (by ID or coordinates) |
| `type` | text, delay, preserve_outer_quotes | Type literal text (clipboard paste by default) |
| `keys` | keys | Send a key combination (e.g. `{Ctrl}c`) |
| `scroll` | direction, amount, x, y | Scroll at a position or the cursor |
| `move` | x, y | Move the mouse to coordinates |
| `drag` | from_x, from_y, to_x, to_y | Drag from one point to another |
| `wait` | seconds | Pause for N seconds |
| `wait_for` | selector, window, active, timeout, state | Wait until a selector matches |
| `apps` | action, name, index, timeout | Manage windows (list / focus / launch / close / minimize / maximize) |
| `screenshot` | output, base64, quality, window, overlay_grid | Capture the screen (PNG file or base64) |
| `locate_vision` | window, target, model, spacing | Visual element location via OpenAI vision API |
| `shell` | command, timeout | Execute a PowerShell command |

### `read`

```json
{"cmd": "read", "args": {"window": "Notepad", "mode": "compact", "depth": 4}}
```

- `window` — filter to a specific window (fuzzy name match)
- `active` — read only the currently active window
- `depth` — max recursion depth (default: 4)
- `mode` — `windows` (top-level only), `full` (complete tree), `compact` (interactive elements only), `auto` (default: `windows` without `window`/`active`, else `compact`)
- `all` — include background and minimized windows

Each element in the output has:

- `id` — runtime integer ID used for subsequent `click`, etc.
- `type` — control type (`Button`, `Edit`, `ListItem`, …)
- `name`, `automation_id`, `class_name` — identifying properties
- `bounds` — bounding rectangle (`x`, `y`, `w`, `h`)
- `enabled`, `offscreen` — state flags

### `click`

```json
{"cmd": "click", "args": {"id": 5}}
{"cmd": "click", "args": {"x": 500, "y": 300}}
{"cmd": "click", "args": {"id": 5, "double": true}}
{"cmd": "click", "args": {"id": 5, "button": "right"}}
```

### `type`

```json
{"cmd": "type", "args": {"text": "some text"}}
{"cmd": "type", "args": {"text": "slow text", "delay": 50}}
{"cmd": "type", "args": {"text": "\"quoted\"", "preserve_outer_quotes": true}}
```

### `keys`

```json
{"cmd": "keys", "args": {"keys": "{Ctrl}c"}}
{"cmd": "keys", "args": {"keys": "{Win}r"}}
{"cmd": "keys", "args": {"keys": "{Alt}{F4}"}}
```

### `scroll`

```json
{"cmd": "scroll", "args": {"direction": "down", "amount": 300}}
{"cmd": "scroll", "args": {"direction": "up", "x": 500, "y": 400}}
```

### `apps`

```json
{"cmd": "apps", "args": {"action": "list"}}
{"cmd": "apps", "args": {"action": "focus", "name": "Notepad"}}
{"cmd": "apps", "args": {"action": "launch", "name": "notepad.exe"}}
{"cmd": "apps", "args": {"action": "close", "name": "Calculator"}}
{"cmd": "apps", "args": {"action": "minimize", "name": "Chrome"}}
{"cmd": "apps", "args": {"action": "maximize", "name": "Chrome"}}
```

### `screenshot`

```json
{"cmd": "screenshot", "args": {"output": "result.png"}}
{"cmd": "screenshot", "args": {"base64": true}}
{"cmd": "screenshot", "args": {"window": "Notepad", "overlay_grid": 150}}
```

### `wait_for`

```json
{"cmd": "wait_for", "args": {"selector": {"name": "OK", "match": "contains"}, "window": "Notepad", "timeout": 5}}
```

### `shell`

```json
{"cmd": "shell", "args": {"command": "Get-Process | Select-Object -First 5"}}
```

## Element Selectors

Selectors are JSON objects matched against UIA properties. Fuzzy matching priority: **Name > AutomationId > ClassName**.

```json
{"name": "OK", "match": "contains"}
{"automation_id": "btnSave", "visible": true}
{"class_name": "Button", "name": "Submit"}
```

- `match` — `contains` (default), `exact`, `starts_with`, or `ends_with`
- `visible` — filter to visible elements only
- `enabled` — filter to enabled elements only
- `index` — pick the N-th match (0-based)

## Element Caching

`read` fills an in-memory cache (O(1) lookup) and writes a file copy (`%TEMP%/win-use/last-read.json`, overridable via `WIN_USE_CACHE_PATH`) for crash recovery and external inspection. Element IDs are only valid until the next `read`.

## Project Structure

```
win_use/
├── __init__.py      # package version
├── __main__.py      # python -m win_use entry
├── cli.py           # stdin/stdout JSON-lines REPL main loop
├── dispatch.py      # command dispatch core (dispatch + LoopContext)
├── reader.py        # UIA tree reader (full / compact / windows mode)
├── actions.py       # mouse, keyboard, scroll, drag
├── apps.py          # window enumeration, focus, launch, close
├── cache.py         # element cache (in-memory + file persistence)
├── locator.py       # element resolution from cached locators
├── selectors.py     # selector matching & wait_for
├── screen.py        # screenshot capture
├── vision.py        # visual element location (OpenAI vision API)
└── utils.py         # safe UIA property reads, window filtering
```

## Design Principles

- **AI-first** — all output is structured JSON; no human-readable formatting
- **Loop agent** — a persistent process reuses COM context across commands, eliminating ~500ms per-call startup overhead
- **Progressive enhancement** — coordinate clicks → ID-based clicks → semantic selectors, each layer increasing robustness
- **Fault-tolerant** — all UIA property reads are wrapped in try/except; failures return defaults rather than crashing

## License

MIT
