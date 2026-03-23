#!/usr/bin/env python3
"""Codex CLI — interact with the ChatGPT Codex web UI from the command line."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

# Fix encoding issues on Windows console
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from codex_page_client import CodexPageClient
from auth import ensure_authenticated
from config import Config, load_config

log = logging.getLogger("codex-cli")


# ---------------------------------------------------------------------------
# Session context manager
# ---------------------------------------------------------------------------

@contextmanager
def codex_session(config: Config, navigate: bool = True):
    """Open an authenticated Codex browser session. Yields a CodexPageClient."""
    client = CodexPageClient(
        url=config.codex_url,
        headless=config.headless,
        timeout_ms=60_000,
        storage_state_path=config.storage_state_path,
    )
    try:
        client.open()
        if navigate:
            ensure_authenticated(client._context, client.page, config)
            client.save_storage_state()
        yield client
    finally:
        try:
            client.save_storage_state()
        except Exception:
            pass
        client.close()


# ---------------------------------------------------------------------------
# Task cache and current-task context
# ---------------------------------------------------------------------------

TASK_CACHE_FILE = ".codex_task_cache.json"
CURRENT_TASK_FILE = ".codex_current_task.json"


def _save_task_cache(tasks: list[dict]) -> None:
    """Cache the task list to disk."""
    Path(TASK_CACHE_FILE).write_text(
        json.dumps({"tasks": tasks, "cached_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
        encoding="utf-8",
    )


def _load_task_cache() -> Optional[list[dict]]:
    """Load cached task list. Returns None if cache doesn't exist or is older than 1 hour."""
    p = Path(TASK_CACHE_FILE)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("tasks")
    except Exception:
        return None


def _set_current_task(task: dict) -> None:
    """Save the current working task context."""
    Path(CURRENT_TASK_FILE).write_text(json.dumps(task, indent=2), encoding="utf-8")


def _get_current_task() -> Optional[dict]:
    """Get the current working task context."""
    p = Path(CURRENT_TASK_FILE)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_task(args, config: Config, client=None, task_arg: Optional[str] = None) -> Optional[dict]:
    """Resolve a task from --task arg, current task context, or prompt user.

    Returns the task dict or None.
    """
    target = task_arg or getattr(args, "task", None)

    # If no task specified, use current task context
    if not target:
        current = _get_current_task()
        if current:
            log.info(f"Using current task: {current['title']}")
            return current
        return None

    # Try to find in cache first
    tasks = _load_task_cache()
    if tasks is None and client:
        tasks = client.get_task_list()
        _save_task_cache(tasks)

    if tasks is None:
        return None

    # Match by index or title substring
    if target.isdigit():
        idx = int(target)
        if 0 <= idx < len(tasks):
            return tasks[idx]
    else:
        for t in tasks:
            if target.lower() in t["title"].lower():
                return t

    return None


def _navigate_to_task(client, task: dict) -> None:
    """Navigate to a task and set it as current."""
    client.open_task_by_href(task["href"])
    _set_current_task(task)
    time.sleep(5)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_login(args, config: Config) -> int:
    """Login and save session."""
    with codex_session(config) as client:
        log.info("Login successful! Session saved.")
        print("Logged in. Session saved to", config.storage_state_path)
    return 0


def cmd_logout(args, config: Config) -> int:
    """Delete stored session to force re-login."""
    state_path = Path(config.storage_state_path)
    if state_path.is_file():
        state_path.unlink()
        print("Session deleted. You will need to login again.")
    else:
        print("No stored session found.")
    return 0


def cmd_list_tasks(args, config: Config) -> int:
    """List tasks from the main Codex page."""
    # Use cache if --cached flag is set
    if getattr(args, "cached", False):
        tasks = _load_task_cache()
        if tasks is None:
            print("No cached tasks. Run without --cached first.")
            return 1
    else:
        with codex_session(config) as client:
            time.sleep(3)
            tasks = client.get_task_list()
            _save_task_cache(tasks)

    if args.json:
        print(json.dumps(tasks, indent=2, ensure_ascii=False))
    else:
        if not tasks:
            print("No tasks found.")
            return 0

        # Show current task indicator
        current = _get_current_task()
        current_href = current["href"] if current else ""

        for i, t in enumerate(tasks):
            marker = " *" if t.get("href") == current_href else ""
            status = t.get("status", "")
            status_str = f" [{status}]" if status else ""
            repo = t.get("repo", "")
            repo_str = f" ({repo})" if repo else ""
            diff = t.get("diff", "")
            diff_str = f" {diff}" if diff else ""
            print(f"  [{i}] {t['title']}{status_str}{repo_str}{diff_str}{marker}")

    return 0


def cmd_use_task(args, config: Config) -> int:
    """Set the current working task context."""
    target = args.task

    # Try cache first
    tasks = _load_task_cache()
    if tasks is None:
        with codex_session(config) as client:
            time.sleep(3)
            tasks = client.get_task_list()
            _save_task_cache(tasks)

    task = None
    if target.isdigit():
        idx = int(target)
        if 0 <= idx < len(tasks):
            task = tasks[idx]
        else:
            print(f"Index {idx} out of range (0-{len(tasks)-1})")
            return 1
    else:
        for t in tasks:
            if target.lower() in t["title"].lower():
                task = t
                break

    if task is None:
        print(f"No task matching '{target}' found.")
        return 1

    _set_current_task(task)
    print(f"Current task set to: {task['title']}")
    print(f"  href: {task['href']}")
    return 0


def cmd_refresh_tasks(args, config: Config) -> int:
    """Force refresh the task cache."""
    with codex_session(config) as client:
        time.sleep(3)
        tasks = client.get_task_list()
        _save_task_cache(tasks)
        print(f"Cached {len(tasks)} tasks.")
    return 0


def cmd_list_envs(args, config: Config) -> int:
    """List available environments."""
    with codex_session(config) as client:
        time.sleep(3)
        envs = client.get_environments()
        if args.json:
            print(json.dumps(envs, indent=2))
        else:
            if not envs:
                print("No environments found.")
                return 0
            for i, e in enumerate(envs):
                print(f"  [{i}] {e}")
    return 0


def cmd_submit_task(args, config: Config) -> int:
    """Submit a new task."""
    with codex_session(config) as client:
        time.sleep(3)

        if args.env:
            log.info(f"Selecting environment: {args.env}")
            client.select_environment(args.env)
            time.sleep(2)

        if args.branch:
            log.info(f"Selecting branch: {args.branch}")
            client.select_branch(args.branch)
            time.sleep(2)

        log.info(f"Submitting task: {args.text[:80]}...")
        client.submit_new_task(args.text)

        if args.wait:
            log.info("Waiting for task to complete...")
            client.wait_for_task_completion(timeout_s=config.task_timeout_s)
            log.info("Task completed!")

        print("Task submitted.")
    return 0


def cmd_open_task(args, config: Config) -> int:
    """Open a task by index or title match, set as current."""
    task = _resolve_task(args, config, task_arg=args.task)
    if task is None:
        # Need to fetch from browser
        with codex_session(config) as client:
            time.sleep(3)
            task = _resolve_task(args, config, client=client, task_arg=args.task)
            if task is None:
                print(f"No task matching '{args.task}' found.")
                return 1

    _set_current_task(task)

    with codex_session(config) as client:
        time.sleep(3)
        log.info(f"Opening task: {task['title']}")
        _navigate_to_task(client, task)
        print(f"Opened: {task['title']}")

        if args.json:
            info = client.get_task_detail()
            print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


def cmd_back(args, config: Config) -> int:
    """Navigate back to Codex main screen."""
    with codex_session(config) as client:
        time.sleep(3)
        client.go_back_to_tasks()
        print("Navigated back to main Codex page.")
    return 0


def _ensure_task_open(client, args, config) -> Optional[dict]:
    """Helper: resolve task and navigate to it. Returns the task dict or None."""
    task = _resolve_task(args, config, client=client)
    if task:
        _navigate_to_task(client, task)
    return task


def cmd_status(args, config: Config) -> int:
    """Check task status from cache or live."""
    task = _resolve_task(args, config)
    if task:
        print(f"{task['title']}: {task.get('status', 'unknown')}")
        if task.get("repo"):
            print(f"  Repo: {task['repo']}")
        if task.get("diff"):
            print(f"  Diff: {task['diff']}")
        if task.get("href"):
            print(f"  URL: https://chatgpt.com{task['href']}")
    else:
        print("No task specified or found. Use --task or 'use-task' first.")
        return 1
    return 0


def cmd_create_pr(args, config: Config) -> int:
    """Create a PR from the task screen."""
    with codex_session(config) as client:
        time.sleep(3)
        task = _ensure_task_open(client, args, config)
        if not task:
            print("No task specified. Use --task or 'use-task' first.")
            return 1

        log.info("Requesting PR creation...")
        client.send_task_message(args.message or "please create a pull request")

        if args.wait:
            log.info("Waiting for completion...")
            client.wait_for_task_completion(timeout_s=300)

        print("PR request sent.")
    return 0


def cmd_list_files(args, config: Config) -> int:
    """List files from task screen."""
    with codex_session(config) as client:
        time.sleep(3)
        task = _ensure_task_open(client, args, config)
        if not task:
            print("No task specified. Use --task or 'use-task' first.")
            return 1

        files = client.get_task_files()
        if args.json:
            print(json.dumps(files, indent=2))
        else:
            if not files:
                print("No files found.")
            for f in files:
                status = f" ({f['status']})" if f.get("status") else ""
                diff = ""
                if f.get("additions") or f.get("deletions"):
                    diff = f" {f.get('additions', '')} {f.get('deletions', '')}".strip()
                print(f"  {f['path']}{status} {diff}".rstrip())
    return 0


def cmd_get_file(args, config: Config) -> int:
    """Get file content from task screen."""
    with codex_session(config) as client:
        time.sleep(3)
        task = _ensure_task_open(client, args, config)
        if not task:
            print("No task specified. Use --task or 'use-task' first.")
            return 1

        content = client.get_file_content(args.file)
        if content:
            print(content)
        else:
            print(f"File '{args.file}' not found.")
            return 1
    return 0


def cmd_history(args, config: Config) -> int:
    """Get conversation history from task screen."""
    with codex_session(config) as client:
        time.sleep(3)
        task = _ensure_task_open(client, args, config)
        if not task:
            print("No task specified. Use --task or 'use-task' first.")
            return 1

        messages = client.get_conversation_history()
        if args.json:
            print(json.dumps(messages, indent=2, ensure_ascii=False))
        else:
            for m in messages:
                role = m.get("role", "unknown")
                text = m.get("content", "")
                prefix = ">>> " if role == "user" else "<<< "
                print(f"{prefix}{text[:200]}")
                if len(text) > 200:
                    print(f"    ... ({len(text)} chars total)")
                print()
    return 0


def cmd_logs(args, config: Config) -> int:
    """Get logs from task screen."""
    with codex_session(config) as client:
        time.sleep(3)
        task = _ensure_task_open(client, args, config)
        if not task:
            print("No task specified. Use --task or 'use-task' first.")
            return 1

        logs = client.get_task_logs()
        if args.json:
            print(json.dumps(logs, indent=2, ensure_ascii=False))
        else:
            for entry in logs:
                print(entry)
    return 0


def cmd_send(args, config: Config) -> int:
    """Send a message in the current task."""
    with codex_session(config) as client:
        time.sleep(3)
        task = _ensure_task_open(client, args, config)
        if not task:
            print("No task specified. Use --task or 'use-task' first.")
            return 1

        client.send_task_message(args.message)

        if args.wait:
            log.info("Waiting for completion...")
            client.wait_for_task_completion(timeout_s=config.task_timeout_s)
            log.info("Done.")

        print("Message sent.")
    return 0


def cmd_cancel(args, config: Config) -> int:
    """Cancel a running task."""
    with codex_session(config) as client:
        time.sleep(3)
        task = _ensure_task_open(client, args, config)
        if not task:
            print("No task specified. Use --task or 'use-task' first.")
            return 1

        success = client.cancel_task()
        if success:
            print("Task cancelled.")
        else:
            print("No running task to cancel (or cancel button not found).")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="codex",
        description="CLI for the ChatGPT Codex web UI",
    )
    p.add_argument("--show-browser", action="store_true", help="Show browser window")
    p.add_argument("--json", action="store_true", help="Output as JSON where supported")
    p.add_argument("--env-file", help="Path to .env config file")
    p.add_argument("--timeout", type=float, help="Override task timeout (seconds)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    sub = p.add_subparsers(dest="command", required=True)

    # login / logout
    sub.add_parser("login", help="Login and save session")
    sub.add_parser("logout", help="Delete stored session")

    # list-tasks
    s = sub.add_parser("list-tasks", help="List tasks with title and status")
    s.add_argument("--json", action="store_true", dest="json")
    s.add_argument("--cached", action="store_true", help="Use cached task list (no browser)")

    # use-task
    s = sub.add_parser("use-task", help="Set current working task by index or title")
    s.add_argument("task", help="Task index (number) or title substring")

    # refresh-tasks
    sub.add_parser("refresh-tasks", help="Force refresh the task cache")

    # list-envs
    s = sub.add_parser("list-envs", help="List available environments")
    s.add_argument("--json", action="store_true", dest="json")

    # submit-task
    s = sub.add_parser("submit-task", help="Submit a new task")
    s.add_argument("--text", required=True, help="Task description")
    s.add_argument("--env", help="Environment to select")
    s.add_argument("--branch", help="Branch to select")
    s.add_argument("--wait", action="store_true", help="Wait for completion")

    # open-task
    s = sub.add_parser("open-task", help="Open a task by index or title")
    s.add_argument("task", help="Task index (number) or title substring")
    s.add_argument("--json", action="store_true", dest="json")

    # back
    sub.add_parser("back", help="Navigate back to main Codex page")

    # status
    s = sub.add_parser("status", help="Check task status")
    s.add_argument("--task", help="Task index or title (omit for current task)")

    # create-pr
    s = sub.add_parser("create-pr", help="Create a PR from task")
    s.add_argument("--task", help="Task index or title")
    s.add_argument("--message", help="Custom PR request message")
    s.add_argument("--wait", action="store_true")

    # list-files
    s = sub.add_parser("list-files", help="List changed files in task")
    s.add_argument("--task", help="Task index or title")
    s.add_argument("--json", action="store_true", dest="json")

    # get-file
    s = sub.add_parser("get-file", help="Get file content from task")
    s.add_argument("file", help="File path to retrieve")
    s.add_argument("--task", help="Task index or title")

    # history
    s = sub.add_parser("history", help="Get conversation history")
    s.add_argument("--task", help="Task index or title")
    s.add_argument("--json", action="store_true", dest="json")

    # logs
    s = sub.add_parser("logs", help="Get task logs")
    s.add_argument("--task", help="Task index or title")
    s.add_argument("--json", action="store_true", dest="json")

    # send
    s = sub.add_parser("send", help="Send a message in the current task")
    s.add_argument("message", help="Message to send")
    s.add_argument("--task", help="Task index or title")
    s.add_argument("--wait", action="store_true")

    # cancel
    s = sub.add_parser("cancel", help="Cancel a running task")
    s.add_argument("--task", help="Task index or title")

    return p


COMMANDS = {
    "login": cmd_login,
    "logout": cmd_logout,
    "use-task": cmd_use_task,
    "refresh-tasks": cmd_refresh_tasks,
    "list-tasks": cmd_list_tasks,
    "list-envs": cmd_list_envs,
    "submit-task": cmd_submit_task,
    "open-task": cmd_open_task,
    "back": cmd_back,
    "status": cmd_status,
    "create-pr": cmd_create_pr,
    "list-files": cmd_list_files,
    "get-file": cmd_get_file,
    "history": cmd_history,
    "logs": cmd_logs,
    "send": cmd_send,
    "cancel": cmd_cancel,
}


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = load_config(env_file=args.env_file)
    if args.show_browser:
        config.headless = False
    if args.timeout:
        config.task_timeout_s = args.timeout

    handler = COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
