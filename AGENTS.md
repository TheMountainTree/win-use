# AGENTS.md — developing win-use

How to **develop** this package. For using win-use as a tool, see `CLAUDE.md`
(operational rules) and `win-use.md` (usage patterns); for architecture, `DESIGN.md`.

## Setup & verification

- Windows-only, Python 3.10+. Install for development with `pip install -e .`.
- Invoke the CLI as `python -m win_use` (works without PATH; `__main__.py` exists).
  This starts the loop agent REPL — no subcommands.
- Tests use **`unittest`**, not pytest (no pytest config exists):
  - all: `python -m unittest tests.test_core`
  - single: `python -m unittest tests.test_core.ReaderTests.test_full_and_compact_modes`
- No lint, typecheck, formatter, or CI config is present. Don't invent commands or
  assume one runs before committing.

## Test approach

`tests/test_core.py` never touches the real UIA tree — it fakes `uiautomation` with
`FakeControl` / `FakeRect` / `FakeWindowPattern` and runs headless on any machine. REPL
protocol tests use `io.StringIO` to simulate stdin/stdout. Patch at module level, e.g.
`patch.object(reader, "get_top_level_windows", return_value=[window])`. When adding
behavior to a module, add a fake-backed test there rather than relying on a live desktop.

## Architecture wiring (not obvious from filenames)

- `cli.py` is the stdin/stdout JSON-lines REPL entry. `main()` reads lines from stdin,
  calls `dispatch(cmd, args, ctx)`, and writes one JSON response per line to stdout.
  EOF (stdin closed) exits gracefully. COM context is pre-warmed at startup.
- `dispatch.py` is the single command dispatch core. `dispatch(cmd, args, ctx)` routes
  to a handler in the `_COMMANDS` registry. **Adding a command means**: a handler
  function + an entry in `_COMMANDS`. `LoopContext` holds the in-memory element cache
  that persists across commands within the process.
- `cache.py` provides `build_memory_cache(elements)` for the in-memory cache (O(1)
  lookup) and `save_elements_cache` / `load_elements_cache` for file-based persistence
  (crash recovery, external inspection). `read` fills both; `click --id` uses memory.
- `locator.py` re-resolves cached element IDs against the live UIA tree on each
  `click --id N` — an ID is only valid until the next `read`.
- `vision.py` (the `locate_vision` command) requires the `[vision]` extra (`openai`)
  and `OPENAI_API_KEY`.

## Gotchas

- **The file trees in `README.md` and `DESIGN.md` are stale** — they reference the old
  `serve.py` / `batch.py` / typer CLI. Trust the actual `win_use/` directory (the tree in
  `CLAUDE.md` is current).
- `type` with `delay=0` pastes via clipboard and strips up to 3 layers of matching outer
  quotes (incl. curly `“”`); `preserve_outer_quotes` keeps them. These are covered by
  tests — preserve the behavior when editing `actions.py`.
- `shell` decodes stdout as `gbk` (dispatch.py `_cmd_shell`) — a Windows zh-CN locale
  assumption; account for it when changing output handling.
- Element cache lives at `%TEMP%/win-use/last-read.json`, overridable via
  `WIN_USE_CACHE_PATH`. The in-memory cache in `LoopContext` is the primary lookup;
  the file is for compatibility and crash recovery.
- Selector `match` values in code are `contains` / `exact` / `starts_with` / `ends_with`
  (README documents `startswith` — use the code forms).

## Conventions

- All REPL output is JSON (one line per response, `json.dumps(..., ensure_ascii=False)`);
  errors are returned as `{"success": false, "error": ..., "error_type": ...}` in the
  same JSON stream (not stderr). Keep this contract for new commands.
- UIA property reads go through `utils.safe_*` helpers and must never raise on missing
  properties — return defaults instead.
- Strings and comments mix Chinese and English; match the surrounding file's style.
