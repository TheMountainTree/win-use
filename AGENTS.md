# AGENTS.md — developing win-use

How to **develop** this package. For using win-use as a tool, see `CLAUDE.md`
(operational rules) and `win-use.md` (usage patterns); for architecture, `DESIGN.md`.

## Setup & verification

- Windows-only, Python 3.10+. Install for development with `pip install -e .`.
- Invoke the CLI as `python -m win_use ...` (works without PATH; `__main__.py` exists).
  The `win-use` console script is also wired in `setup.py`.
- Tests use **`unittest`**, not pytest (no pytest config exists):
  - all: `python -m unittest tests.test_core`
  - single: `python -m unittest tests.test_core.ReaderTests.test_full_and_compact_modes`
- No lint, typecheck, formatter, or CI config is present. Don't invent commands or
  assume one runs before committing.

## Test approach

`tests/test_core.py` never touches the real UIA tree — it fakes `uiautomation` with
`FakeControl` / `FakeRect` / `FakeWindowPattern` and runs headless on any machine. CLI
tests use `typer.testing.CliRunner`. Patch at module level, e.g.
`patch.object(reader, "get_top_level_windows", return_value=[window])`. When adding
behavior to a module, add a fake-backed test there rather than relying on a live desktop.

## Architecture wiring (not obvious from filenames)

- `cli.py` is the Typer entry. **Every command handler first calls `_try_serve(cmd, args)`**
  (cli.py:32) to forward to a running `serve` process, then falls back to local execution.
  Adding a command means: a handler + a `_try_serve` call + a matching branch in
  `serve.py` (serve.py:153).
- `serve.py` is a long-running socket server; its port is recorded in
  `%TEMP%/win-use/server-port.txt` (override via `WIN_USE_PORT`). It must handle every
  command name you add.
- `batch.py` gates actions in three places: `SUPPORTED_ACTIONS` (batch.py:16), the
  `ALLOWED_KEYS` map (~batch.py:30), and the `run_step` dispatch (batch.py:145, incl. the
  `locate_vision` branch at batch.py:260). Adding a batch action requires all three.
- `locator.py` re-resolves cached element IDs against the live UIA tree on each
  `click --id N` — an ID is only valid until the next `read`.
- `vision.py` (the `locate-vision` command and `locate_vision` batch action) requires the
  `[vision]` extra (`openai`) and `OPENAI_API_KEY`.

## Gotchas

- **The file trees in `README.md` and `DESIGN.md` are stale** — they omit `serve.py`,
  `vision.py`, and `__main__.py`. Trust the actual `win_use/` directory (the tree in
  `CLAUDE.md` is current).
- `type` with `delay=0` pastes via clipboard and strips up to 3 layers of matching outer
  quotes (incl. curly `“”`); `--preserve-outer-quotes` keeps them. `--stdin` strips one
  trailing newline unless `--preserve-stdin-newline`. These are covered by tests —
  preserve the behavior when editing `actions.py`.
- `shell` decodes stdout as `gbk` (cli.py:477) — a Windows zh-CN locale assumption;
  account for it when changing output handling.
- Element cache lives at `%TEMP%/win-use/last-read.json`, overridable via
  `WIN_USE_CACHE_PATH`.
- Selector `match` values in code are `contains` / `exact` / `starts_with` / `ends_with`
  (README documents `startswith` — use the code forms).

## Conventions

- All CLI and batch output is JSON (`typer.echo(json.dumps(...))`); errors go to stderr
  with non-zero exit. Keep this contract for new commands.
- UIA property reads go through `utils.safe_*` helpers and must never raise on missing
  properties — return defaults instead.
- Strings and comments mix Chinese and English; match the surrounding file's style.
