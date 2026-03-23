# CLAUDE.md — Guide for using the codex-cli project

## What is this?

`codex-cli` is a Python CLI that automates the [ChatGPT Codex](https://chatgpt.com/codex) web UI using Playwright browser automation. It provides 17 commands for managing Codex tasks, plus an autonomous ticket worker that processes implementation tickets sequentially.

## Project structure

```
cli.py                          — Main CLI (entry point: python cli.py <command>)
codex_page_client.py            — CodexPageClient class (Playwright browser abstraction)
auth.py                         — Login flow: email → password → TOTP, session persistence
config.py                       — Config from env vars / .env file
ticket_implementation_runner.py — Ticket worker (reads markdown tickets, submits sequentially)
record_demo.py                  — Video recording utility
tests/                          — Unit tests (run with: python -m pytest tests/ -v)
```

## How to run commands

All CLI commands go through `cli.py`:

```bash
python cli.py [global-flags] <command> [command-flags]
```

Global flags come BEFORE the command: `python cli.py --show-browser list-tasks`

### Common workflows

```bash
# First time setup
python cli.py --show-browser login

# Browse tasks (instant from cache)
python cli.py list-tasks --cached

# Set working task context
python cli.py use-task "My task name"

# All subsequent commands use the current task automatically
python cli.py --show-browser history
python cli.py --show-browser list-files
python cli.py --show-browser logs
python cli.py --show-browser send "please add tests"

# Submit a new task
python cli.py --show-browser submit-task --text "implement feature X" --env "org/repo"
```

### Ticket worker

```bash
python ticket_implementation_runner.py --dry-run                    # Preview next ticket
python ticket_implementation_runner.py --show-browser --count 1     # Run 1 ticket
python ticket_implementation_runner.py --count 5 --env "org/repo"   # Run 5 headless
```

## Configuration

All config is in `.env` (gitignored). Required: `CODEX_EMAIL`, `CODEX_PASSWORD`. Optional: `CODEX_TOTP_SECRET` for auto-MFA.

## Key selectors (Codex UI)

The Codex web UI is a single-page app. Key selectors discovered from the live UI:

- **Main page task list**: `a[href*='/codex/tasks/']` — each task is a link
- **Task input**: `[role='textbox']` or `[contenteditable='true']` — not a textarea
- **Send button**: `button[aria-label='Submit']`
- **Environment dropdown**: `button[aria-label='View all code environments']`
- **Branch dropdown**: `button[aria-label='Search for your branch']`
- **Back button** (task detail): `button[aria-label='Go back to tasks']`
- **Task detail chat input**: `[contenteditable='true']`
- **Files toggle**: `button[aria-label='Toggle file list diffs']`
- **Logs tab**: `button[aria-label='Tab to view the work logs']`
- **Diff tab**: `button:has-text('Diff')`
- **Worked-for sections**: `button:has-text('Worked for')`
- **User messages**: `[class*='self-end'][class*='bg-token-bg-tertiary']`

These selectors may change when OpenAI updates the Codex UI. Check `codex_page_client.py` constants at the top of the file.

## State files (all gitignored)

- `.playwright_storage_state.json` — Browser session (cookies/localStorage)
- `.codex_task_cache.json` — Cached task list
- `.codex_current_task.json` — Current working task
- `.ticket_runner_state.json` — Ticket worker progress
- `.env` — Credentials

## Testing

```bash
python -m pytest tests/ -v
```

Tests cover ticket parsing and client initialization. Live browser tests require a valid session.

## Infinite scroll

The Codex UI uses infinite scroll for the task list. `codex_page_client.py` has `_scroll_to_bottom()` and `_scroll_to_top()` methods that scroll all scrollable containers to trigger content loading. These are used by `get_task_list()`, `get_conversation_history()`, and `get_task_logs()`.

## Error handling

- Screenshots are saved to `screenshots/` on errors
- Ticket worker retries failed tickets (configurable via `CODEX_MAX_RETRIES`)
- Session is re-saved after each operation
- State file is saved after each completed ticket (crash-safe)

## Adding new commands

1. Add a `cmd_xyz(args, config)` function in `cli.py`
2. Add argparse entry in `build_parser()`
3. Add to `COMMANDS` dict
4. If the command needs browser interaction, add methods to `CodexPageClient` in `codex_page_client.py`
5. Discover selectors by running with `--show-browser` and using browser dev tools or the probe scripts in git history
