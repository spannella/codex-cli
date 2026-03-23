#!/usr/bin/env python3
"""Autonomous ticket worker built on top of the Codex CLI.

Reads tickets from a markdown file, submits them as Codex tasks one by one,
waits for completion, optionally requests PRs, and tracks progress.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cli import codex_session, _save_task_cache
from codex_page_client import CodexPageClient
from config import Config, load_config

# Fix Windows encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

log = logging.getLogger("codex-runner")

# ---------------------------------------------------------------------------
# Ticket parsing
# ---------------------------------------------------------------------------

# Generic ticket header: ### ID — Title
TICKET_HEADER_RE = re.compile(
    r"^###\s+([A-Z]+-\d{3,4})\s+[—\-]+\s+(.+?)\s*$", re.MULTILINE
)


@dataclass
class Ticket:
    ticket_id: str
    title: str
    body: str


def parse_tickets(markdown: str) -> list[Ticket]:
    """Parse ticket blocks from markdown using ### ID — Title headers."""
    matches = list(TICKET_HEADER_RE.finditer(markdown))
    tickets: list[Ticket] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        tickets.append(Ticket(
            ticket_id=m.group(1),
            title=m.group(2).strip(),
            body=markdown[start:end].strip(),
        ))
    return tickets


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state(path: Path) -> dict:
    if not path.exists():
        return {"implemented": [], "failed": {}, "skipped": [], "last_run": None, "total_runs": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("failed", {})
    data.setdefault("skipped", [])
    data.setdefault("last_run", None)
    data.setdefault("total_runs", 0)
    return data


def save_state(path: Path, state: dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def next_ticket(
    tickets: list[Ticket],
    implemented: set[str],
    failed: Optional[set[str]] = None,
    skipped: Optional[set[str]] = None,
) -> Optional[Ticket]:
    for t in tickets:
        if t.ticket_id in implemented:
            continue
        if failed and t.ticket_id in failed:
            continue
        if skipped and t.ticket_id in skipped:
            continue
        return t
    return None


def build_message(ticket: Ticket) -> str:
    return f"please implement: {ticket.body}"


# ---------------------------------------------------------------------------
# Tick logger
# ---------------------------------------------------------------------------

def _tick_logger(ticket_id: str):
    last_log = [0.0]

    def _on_tick(elapsed_s: float):
        if elapsed_s - last_log[0] >= 60:
            log.info(f"[{ticket_id}] Still working... ({elapsed_s:.0f}s elapsed)")
            last_log[0] = elapsed_s

    return _on_tick


# ---------------------------------------------------------------------------
# Core: run a single ticket
# ---------------------------------------------------------------------------

def run_ticket(
    client: CodexPageClient,
    ticket: Ticket,
    config: Config,
) -> bool:
    """Submit a ticket as a new Codex task, wait for completion. Returns True on success."""
    ticket_id = ticket.ticket_id
    message = build_message(ticket)

    # Navigate to main page
    log.info(f"[{ticket_id}] Navigating to Codex main page...")
    client.navigate_to(config.codex_url)
    time.sleep(5)

    # Select environment if configured
    if config.env_name:
        log.info(f"[{ticket_id}] Selecting environment: {config.env_name}")
        client.select_environment(config.env_name)
        time.sleep(2)

    # Snapshot task list before submission to detect the new task
    tasks_before = client.get_task_list(scroll=False)
    titles_before = {t["title"] for t in tasks_before}

    # Submit the task
    log.info(f"[{ticket_id}] Submitting: {ticket.title}")
    client.submit_new_task(message)
    time.sleep(5)

    # Wait for the new task to appear in the task list
    log.info(f"[{ticket_id}] Waiting for task to appear...")
    new_task = None
    deadline = time.time() + 120
    while time.time() < deadline:
        tasks_now = client.get_task_list(scroll=False)
        for t in tasks_now:
            if t["title"] not in titles_before:
                new_task = t
                break
        if new_task:
            break
        time.sleep(5)

    if new_task:
        log.info(f"[{ticket_id}] Task created: {new_task['title']}")

        # Navigate into the task
        client.open_task_by_href(new_task["href"])
        time.sleep(5)

        # Wait for task completion
        log.info(f"[{ticket_id}] Waiting for completion (timeout: {config.task_timeout_s}s)...")
        client.wait_for_task_completion(
            timeout_s=config.task_timeout_s,
            on_tick=_tick_logger(ticket_id),
        )
        log.info(f"[{ticket_id}] Task completed!")

        # Request PR if configured
        if config.request_pr:
            log.info(f"[{ticket_id}] Requesting PR...")
            client.send_task_message("please create a pull request")
            time.sleep(5)
            client.wait_for_task_completion(
                timeout_s=300,
                on_tick=_tick_logger(ticket_id + "-pr"),
            )
            log.info(f"[{ticket_id}] PR request completed!")

        return True
    else:
        log.warning(f"[{ticket_id}] Task did not appear in list within 120s")
        # Fallback: maybe it submitted but title didn't match — wait and check
        time.sleep(30)
        client.navigate_to(config.codex_url)
        time.sleep(5)
        return True  # Optimistic — mark as done since we submitted it


def _take_error_screenshot(client: CodexPageClient, ticket_id: str, screenshot_dir: str) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(Path(screenshot_dir) / f"{ticket_id}_error_{ts}.png")
    client.screenshot(path)
    log.info(f"Error screenshot saved to {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _setup_logging(log_file: Optional[str] = None) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tickets", default="docspayment-dispute-management-tickets.md",
                    help="Path to tickets markdown file")
    p.add_argument("--state", default=".ticket_runner_state.json",
                    help="Path to state tracking file")
    p.add_argument("--count", type=int, default=0,
                    help="Max tickets to process (0 = all remaining)")
    p.add_argument("--dry-run", action="store_true",
                    help="Print next ticket without running")
    p.add_argument("--retry-failed", action="store_true",
                    help="Re-attempt previously failed tickets")
    p.add_argument("--skip", nargs="*", default=[],
                    help="Ticket IDs to skip (e.g. PDM-003 PDM-005)")
    p.add_argument("--show-browser", action="store_true",
                    help="Show the browser window")
    p.add_argument("--no-pr", action="store_true",
                    help="Skip PR request after each ticket")
    p.add_argument("--env", help="Codex environment to select")
    p.add_argument("--branch", help="Git branch to use")
    p.add_argument("--env-file", help="Path to .env file for config")
    p.add_argument("--log-file", default="codex_runner.log",
                    help="Path to log file")
    p.add_argument("--screenshot-dir", help="Override screenshot directory")
    p.add_argument("--timeout", type=float, help="Override task timeout (seconds)")

    args = p.parse_args()

    _setup_logging(args.log_file)
    log.info("=" * 60)
    log.info("Codex Ticket Worker starting")
    log.info("=" * 60)

    # Load config
    config = load_config(env_file=args.env_file)
    if args.show_browser:
        config.headless = False
    if args.no_pr:
        config.request_pr = False
    if args.env:
        config.env_name = args.env
    if args.screenshot_dir:
        config.screenshot_dir = args.screenshot_dir
    if args.timeout:
        config.task_timeout_s = args.timeout

    # Load tickets
    tickets_path = Path(args.tickets)
    if not tickets_path.is_file():
        log.error(f"Tickets file not found: {tickets_path}")
        return 1
    tickets_md = tickets_path.read_text(encoding="utf-8", errors="ignore")
    tickets = parse_tickets(tickets_md)
    if not tickets:
        log.error("No tickets found in markdown file")
        return 1
    log.info(f"Found {len(tickets)} tickets in {args.tickets}")

    # Load state
    state_path = Path(args.state)
    state = load_state(state_path)
    state["total_runs"] = state.get("total_runs", 0) + 1
    implemented: set[str] = set(state.get("implemented", []))
    failed: dict[str, str] = state.get("failed", {})
    skipped: set[str] = set(state.get("skipped", []))

    # Add CLI --skip to skipped set
    for s in args.skip:
        skipped.add(s)
        state["skipped"] = sorted(skipped)

    # If retrying failed, move them back to pending
    if args.retry_failed and failed:
        log.info(f"Retrying {len(failed)} previously failed tickets")
        failed.clear()
        state["failed"] = failed

    log.info(f"State: {len(implemented)} implemented, {len(failed)} failed, {len(skipped)} skipped")

    # Dry run mode
    if args.dry_run:
        t = next_ticket(tickets, implemented, failed=set(failed.keys()), skipped=skipped)
        if t is None:
            print("All tickets completed/failed/skipped.")
            remaining = [t for t in tickets if t.ticket_id not in implemented
                         and t.ticket_id not in failed and t.ticket_id not in skipped]
            if not remaining:
                print("Use --retry-failed to retry failures.")
        else:
            print(f"Next ticket: {t.ticket_id} — {t.title}")
            print()
            print(build_message(t))
        return 0

    # Validate
    config.validate()

    max_count = args.count if args.count > 0 else len(tickets)

    # --- Run ---
    log.info(f"Launching browser (headless={config.headless})...")

    with codex_session(config) as client:
        sent = 0
        for _ in range(max_count):
            t = next_ticket(tickets, implemented, failed=set(failed.keys()), skipped=skipped)
            if t is None:
                log.info("No more tickets to process")
                break

            success = False
            last_error = ""
            for attempt in range(1, config.max_retries + 1):
                try:
                    log.info(f"[{t.ticket_id}] Attempt {attempt}/{config.max_retries}")
                    success = run_ticket(client, t, config)
                    break
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    log.error(f"[{t.ticket_id}] Attempt {attempt} failed: {last_error}")
                    _take_error_screenshot(client, t.ticket_id, config.screenshot_dir)

                    if attempt < config.max_retries:
                        wait = min(10 * attempt, 30)
                        log.info(f"[{t.ticket_id}] Retrying in {wait}s...")
                        time.sleep(wait)
                        try:
                            client.navigate_to(config.codex_url)
                            time.sleep(5)
                        except Exception:
                            log.warning(f"[{t.ticket_id}] Navigation failed on retry")

            if success:
                implemented.add(t.ticket_id)
                state["implemented"] = sorted(implemented)
                if t.ticket_id in failed:
                    del failed[t.ticket_id]
                    state["failed"] = failed
                save_state(state_path, state)
                log.info(f"[{t.ticket_id}] Done! State saved.")
                sent += 1
            else:
                failed[t.ticket_id] = last_error
                state["failed"] = failed
                save_state(state_path, state)
                log.error(f"[{t.ticket_id}] Failed after {config.max_retries} attempts.")

        # Refresh task cache after run
        try:
            client.navigate_to(config.codex_url)
            time.sleep(5)
            tasks = client.get_task_list(scroll=False)
            _save_task_cache(tasks)
        except Exception:
            pass

    # Summary
    log.info("=" * 60)
    log.info(f"Run complete: {sent} tickets processed")
    log.info(f"Total implemented: {len(implemented)}/{len(tickets)}")
    if failed:
        log.info(f"Failed: {', '.join(sorted(failed.keys()))}")
    if skipped:
        log.info(f"Skipped: {', '.join(sorted(skipped))}")
    log.info("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
