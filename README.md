## Codex page automation

This repo has two layers:

1. **`codex_page_client.py`**: reusable CLI/library for interacting with Codex pages and exported HTML.
2. **`ticket_implementation_runner.py`**: higher-level runner that sends sequential `please implement: ...` ticket prompts.

---

## 1) Page interaction library/CLI

### What it can do

- Send message/task text to a page.
- Check working vs done state.
- Wait until completion.
- Request PR by sending a PR message.
- Go back with back-arrow (or browser history fallback).
- Submit a new task with optional environment selection.

### Parse exported HTML

For task pages (`page.html`) and main page exports (`page2.html`):

- list diff files and read one file,
- list tasks with status (`normal`, `open`, `merged`) and task link,
- list loaded/mentioned environments.

### CLI examples

```bash
# diff parsing from task page export
python3 codex_page_client.py list-diff-files --page page.html
python3 codex_page_client.py get-diff-file docspayment-dispute-management-tickets.md --page page.html

# task list + status + links from main page export
python3 codex_page_client.py list-tasks --page page2.html
python3 codex_page_client.py list-tasks --page page2.html --json

# list loaded envs from main page export
python3 codex_page_client.py list-envs --page page2.html

# send a message in a live task URL
python3 codex_page_client.py send --url "https://chatgpt.com/codex/tasks/..." "hello" --wait

# status check for live task URL
python3 codex_page_client.py status --url "https://chatgpt.com/codex/tasks/..."

# request PR in live task URL
python3 codex_page_client.py request-pr --url "https://chatgpt.com/codex/tasks/..." --wait

# go back to main page from a task URL
python3 codex_page_client.py back --url "https://chatgpt.com/codex/tasks/..."

# submit a new task on main page and choose env
python3 codex_page_client.py submit-task \
  --url "https://chatgpt.com/codex" \
  --text "implement ticket PDM-001" \
  --env "default" \
  --wait
```

---

## 2) Ticket implementation runner

`ticket_implementation_runner.py` reads ticket markdown headings (`### PDM-001 — ...`), tracks progress in a state file, and emits/sends the next ticket prompt.

```bash
# print next ticket prompt only
python3 ticket_implementation_runner.py --dry-run

# send next ticket to live URL and wait
python3 ticket_implementation_runner.py \
  --url "https://chatgpt.com/codex/tasks/..." \
  --wait-timeout-s 900

# send multiple tickets in sequence
python3 ticket_implementation_runner.py --url "https://chatgpt.com/codex/tasks/..." --count 3
```

### Defaults

- tickets file: `docspayment-dispute-management-tickets.md`
- state file: `.ticket_runner_state.json`
