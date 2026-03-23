# codex-cli

Command-line interface for the [ChatGPT Codex](https://chatgpt.com/codex) web UI. Automates task management, code review, and ticket-driven development workflows via Playwright browser automation.

![Demo](videos/demo.gif)

[Watch full video (webm)](videos/demo.webm)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Configure credentials
cp .env.example .env
# Edit .env with your ChatGPT email, password, and TOTP secret

# Login (first run — use --show-browser to handle any CAPTCHA)
python cli.py --show-browser login

# List your tasks
python cli.py list-tasks --cached

# Work on a task
python cli.py use-task "My task name"
python cli.py --show-browser history
python cli.py --show-browser list-files
```

## Installation

### Requirements

- Python 3.9+
- A ChatGPT account with Codex access (Pro/Plus plan)

### Setup

```bash
git clone https://github.com/spannella/codex-cli.git
cd codex-cli
pip install -r requirements.txt
python -m playwright install chromium
```

## Configuration

All configuration is via environment variables. Create a `.env` file in the project root (see `.env.example`):

```bash
# Required
CODEX_EMAIL=you@example.com
CODEX_PASSWORD=your-password

# Optional: TOTP secret for automatic MFA (base32 key from authenticator setup)
CODEX_TOTP_SECRET=YOUR_BASE32_SECRET

# Optional: Codex base URL (default: https://chatgpt.com/codex)
CODEX_URL=https://chatgpt.com/codex

# Optional: Default environment/repo
CODEX_ENV=your-org/your-repo

# Optional: Run headless (default: true). Set to false for first login or debugging.
CODEX_HEADLESS=true

# Optional: Task timeout in seconds (default: 900)
CODEX_TASK_TIMEOUT=900

# Optional: Max retries per ticket (default: 2)
CODEX_MAX_RETRIES=2

# Optional: Request PR after each ticket (default: true)
CODEX_REQUEST_PR=true

# Optional: Poll interval in seconds (default: 3)
CODEX_POLL_INTERVAL=3
```

### First-time login

On first run, use `--show-browser` so you can see the browser and handle any CAPTCHA or unexpected prompts:

```bash
python cli.py --show-browser login
```

After successful login, the session is saved to `.playwright_storage_state.json` and subsequent runs will reuse it automatically (even headless).

### TOTP/MFA Setup

If your ChatGPT account has TOTP-based MFA, set `CODEX_TOTP_SECRET` to the base32 secret key from your authenticator app setup. The CLI will auto-generate TOTP codes during login.

## CLI Reference

```
python cli.py [global-options] <command> [command-options]
```

### Global Options

| Flag | Description |
|------|-------------|
| `--show-browser` | Show the browser window (default: headless) |
| `--json` | Output as JSON where supported |
| `--env-file PATH` | Path to `.env` config file |
| `--timeout SECONDS` | Override task timeout |
| `--log-level LEVEL` | Set log level (DEBUG, INFO, WARNING, ERROR) |

---

### Authentication

#### `login`

Login to ChatGPT and save the session.

```bash
python cli.py --show-browser login    # First time (visible browser)
python cli.py login                   # Subsequent (headless, reuses session)
```

#### `logout`

Delete the stored session. Next command will require a fresh login.

```bash
python cli.py logout
```

---

### Task Management

#### `list-tasks`

List all tasks from the Codex dashboard. Uses infinite scroll to load the full history.

```bash
python cli.py list-tasks                # Live (opens browser, scrolls)
python cli.py list-tasks --cached       # From cache (instant, no browser)
python cli.py list-tasks --json         # JSON output
python cli.py list-tasks --cached --json
```

Output shows: `[index] Title [Status] (repo) +additions -deletions`

The current task (set via `use-task`) is marked with `*`.

#### `refresh-tasks`

Force-refresh the task cache by loading all tasks from the browser.

```bash
python cli.py --show-browser refresh-tasks
```

#### `use-task`

Set the current working task. Task-specific commands will use this task by default (no need for `--task` each time).

```bash
python cli.py use-task 5                    # By index
python cli.py use-task "Parse tickets"      # By title substring
```

#### `open-task`

Open a task in the browser and set it as current.

```bash
python cli.py --show-browser open-task 0
python cli.py --show-browser open-task "Implement billing"
```

#### `status`

Check a task's status (works from cache, no browser needed).

```bash
python cli.py status                         # Current task
python cli.py status --task "Parse tickets"  # By name
python cli.py status --task 3               # By index
```

#### `submit-task`

Submit a new task from the main Codex page.

```bash
python cli.py --show-browser submit-task --text "Add user authentication"
python cli.py --show-browser submit-task --text "Fix login bug" --env "my-org/my-repo"
python cli.py --show-browser submit-task --text "Add tests" --env "my-repo" --branch "develop" --wait
```

| Flag | Description |
|------|-------------|
| `--text TEXT` | Task description (required) |
| `--env NAME` | Select environment/repo |
| `--branch NAME` | Select branch |
| `--wait` | Wait for the task to complete |

#### `cancel`

Cancel a running task.

```bash
python cli.py --show-browser cancel                       # Current task
python cli.py --show-browser cancel --task "My task"      # By name
```

#### `back`

Navigate from a task detail view back to the main Codex page.

```bash
python cli.py --show-browser back
```

---

### Task Detail Operations

These commands operate on a task detail view. They use the current task (set via `use-task`) or accept `--task`.

#### `history`

Get the conversation history (user messages and assistant responses).

```bash
python cli.py --show-browser history
python cli.py --show-browser history --task "My task"
python cli.py --show-browser history --json
```

#### `list-files`

List changed files in a task.

```bash
python cli.py --show-browser list-files
python cli.py --show-browser list-files --task "My task" --json
```

Output shows: `path (status) +additions -deletions`

#### `get-file`

Get the diff content of a specific file.

```bash
python cli.py --show-browser get-file "src/main.py"
python cli.py --show-browser get-file "README.md" --task "My task"
```

#### `logs`

Get execution logs from the "Worked for" sections.

```bash
python cli.py --show-browser logs
python cli.py --show-browser logs --task "My task" --json
```

#### `send`

Send a follow-up message in a task.

```bash
python cli.py --show-browser send "Can you add tests for this?"
python cli.py --show-browser send "Fix the linting errors" --wait
python cli.py --show-browser send "please create a pull request" --task "My task"
```

#### `create-pr`

Send a PR creation request in a task.

```bash
python cli.py --show-browser create-pr
python cli.py --show-browser create-pr --task "My task" --wait
python cli.py --show-browser create-pr --message "Create PR with title: Add auth feature"
```

---

### Environments

#### `list-envs`

List available environments (repos connected to Codex).

```bash
python cli.py --show-browser list-envs
python cli.py --show-browser list-envs --json
```

---

## Ticket Worker

The ticket worker (`ticket_implementation_runner.py`) automates sequential ticket implementation. It reads tickets from a markdown file, submits them one by one as Codex tasks, waits for completion, and optionally requests PRs.

### Ticket Format

Tickets are parsed from markdown with this header format:

```markdown
### PROJ-001 — Ticket title here
**Type:** Feature
**Priority:** P0
**Dependencies:** None

Description and acceptance criteria...

---
```

### Usage

```bash
# See what's next
python ticket_implementation_runner.py --dry-run

# Run 1 ticket (visible browser, recommended for first run)
python ticket_implementation_runner.py --show-browser --count 1 --env "my-org/my-repo"

# Run 5 tickets headless
python ticket_implementation_runner.py --count 5 --env "my-org/my-repo"

# Run all remaining tickets
python ticket_implementation_runner.py --env "my-org/my-repo"

# Skip specific tickets
python ticket_implementation_runner.py --skip PDM-003 PDM-007

# Retry previously failed tickets
python ticket_implementation_runner.py --retry-failed

# Run without PR requests
python ticket_implementation_runner.py --no-pr --count 3
```

### Ticket Worker Options

| Flag | Description |
|------|-------------|
| `--tickets FILE` | Path to tickets markdown (default: `docspayment-dispute-management-tickets.md`) |
| `--state FILE` | State tracking file (default: `.ticket_runner_state.json`) |
| `--count N` | Max tickets to process (0 = all) |
| `--dry-run` | Print next ticket without running |
| `--retry-failed` | Re-attempt failed tickets |
| `--skip ID [ID ...]` | Ticket IDs to skip |
| `--show-browser` | Show browser window |
| `--no-pr` | Skip PR request after each ticket |
| `--env NAME` | Codex environment/repo |
| `--branch NAME` | Git branch |
| `--timeout SECONDS` | Task timeout |
| `--log-file PATH` | Log file (default: `codex_runner.log`) |
| `--screenshot-dir DIR` | Error screenshot directory (default: `screenshots/`) |

### State Tracking

Progress is tracked in `.ticket_runner_state.json`:

```json
{
  "implemented": ["PDM-001", "PDM-002"],
  "failed": {"PDM-003": "TimeoutError: ..."},
  "skipped": ["PDM-007"],
  "last_run": "2026-03-22T20:28:51+00:00",
  "total_runs": 5
}
```

State is saved after each ticket completes, so a crash loses at most one ticket's progress.

---

## Demo Video Recording

Record a demo video showing login, task browsing, and ticket submission:

```bash
python record_demo.py --env "my-org/my-repo"
python record_demo.py --work-ticket --env "my-org/my-repo" --wait-time 60
```

Videos are saved to the `videos/` directory as `.webm` files.

---

## Architecture

```
codex-cli/
├── cli.py                          # Main CLI entry point (17 commands)
├── codex_page_client.py            # Playwright browser automation client
├── auth.py                         # Login flow (email/password/TOTP/session)
├── config.py                       # Configuration from env vars / .env
├── ticket_implementation_runner.py # Autonomous ticket worker
├── record_demo.py                  # Video recording utility
├── requirements.txt                # Python dependencies
├── .env.example                    # Configuration template
├── .gitignore                      # Excludes credentials, state, cache
└── tests/                          # Test suite
```

### Session Persistence

Sessions are stored in `.playwright_storage_state.json` (gitignored). This file contains browser cookies and localStorage, allowing subsequent runs to skip login.

### Task Caching

The task list is cached in `.codex_task_cache.json` after each `list-tasks` or `refresh-tasks` call. Use `--cached` to read from cache without opening a browser.

### Current Task Context

`use-task` saves the current task to `.codex_current_task.json`. All task-specific commands (`history`, `logs`, `list-files`, `send`, etc.) use this task by default.

---

## Troubleshooting

**"Could not find email input field"**
The login page structure may have changed. Run with `--show-browser` to see what's happening. The auth selectors in `auth.py` may need updating.

**"CAPTCHA detected"**
Run with `CODEX_HEADLESS=false` (or `--show-browser`) and solve the CAPTCHA manually. After that, the session persists.

**"MFA was not completed within timeout"**
Set `CODEX_TOTP_SECRET` in `.env` for automatic TOTP code generation. Without it, you need `--show-browser` to enter the code manually.

**Tasks not loading (empty list)**
Make sure you're logged in (`python cli.py --show-browser login`). The session may have expired — run `logout` then `login` again.

**Encoding errors on Windows**
The CLI sets UTF-8 encoding automatically. If you still see errors, set `PYTHONIOENCODING=utf-8` in your environment.
