#!/usr/bin/env python3
"""Record a demo video of the Codex CLI in action using Playwright."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from .config import load_config
from ._auth import ensure_authenticated
from ._page_client import CodexPageClient
from .ticket_runner import parse_tickets, next_ticket, build_message, load_state

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

log = logging.getLogger("codex-demo")


def record_demo(config, args):
    """Record a full demo: login, list tasks, work tickets."""
    from playwright.sync_api import sync_playwright

    video_dir = Path(args.output_dir)
    video_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            record_video_dir=str(video_dir),
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720},
        )
        page = context.new_page()

        try:
            # --- Step 1: Login ---
            log.info("Step 1: Logging in...")
            page.goto(config.codex_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            ensure_authenticated(context, page, config)
            context.storage_state(path=config.storage_state_path)
            log.info("Logged in!")
            time.sleep(3)

            # --- Step 2: List tasks (scroll) ---
            log.info("Step 2: Browsing task list...")
            page.goto(config.codex_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # Slow scroll to show tasks loading
            for i in range(5):
                page.evaluate("""() => {
                    const els = document.querySelectorAll('*');
                    for (const el of els) {
                        if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
                            el.scrollBy(0, 400);
                        }
                    }
                }""")
                time.sleep(2)

            # Scroll back to top
            page.evaluate("""() => {
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
                        el.scrollTop = 0;
                    }
                }
            }""")
            time.sleep(3)

            # --- Step 3: Work a ticket ---
            if args.work_ticket:
                log.info("Step 3: Submitting a ticket...")
                tickets_path = Path(args.tickets)
                if tickets_path.is_file():
                    tickets_md = tickets_path.read_text(encoding="utf-8", errors="ignore")
                    tickets = parse_tickets(tickets_md)
                    state = load_state(Path(args.state))
                    implemented = set(state.get("implemented", []))
                    ticket = next_ticket(tickets, implemented)

                    if ticket:
                        message = build_message(ticket)
                        log.info(f"Submitting: {ticket.ticket_id} — {ticket.title}")

                        # Select environment if configured
                        if config.env_name:
                            env_btn = page.locator("button[aria-label='View all code environments']")
                            if env_btn.count() and env_btn.first.is_visible():
                                env_btn.first.click()
                                time.sleep(2)
                                opt = page.locator(f"button:has-text('{config.env_name}')")
                                if opt.count() and opt.first.is_visible():
                                    opt.first.click()
                                    time.sleep(2)

                        # Type the task message
                        prompt = page.locator("[role='textbox'], [contenteditable='true']").first
                        if prompt.is_visible():
                            prompt.click()
                            prompt.press("Control+a")
                            prompt.type(message[:200] + "...")  # Truncate for demo
                            time.sleep(2)

                            # Submit
                            send_btn = page.locator("button[aria-label*='Submit']")
                            if send_btn.count() and send_btn.first.is_visible():
                                send_btn.first.click()
                                time.sleep(3)

                            log.info("Task submitted!")
                            time.sleep(5)

                            # Step 4: Navigate into the new task
                            log.info("Step 4: Opening the task...")
                            # Reload task list and find the new task
                            page.goto(config.codex_url, wait_until="domcontentloaded", timeout=30000)
                            time.sleep(5)
                            task_links = page.locator("a[href*='/codex/tasks/']")
                            if task_links.count():
                                # Click the first (newest) task
                                task_links.first.click()
                                time.sleep(5)

                                log.info("Step 5: Watching Codex work...")
                                # Wait and show the task processing
                                wait_s = min(args.wait_time, 120)
                                deadline = time.time() + wait_s
                                while time.time() < deadline:
                                    # Check if stop button is gone (task done)
                                    stop = page.locator("button[aria-label*='Stop']")
                                    if not stop.count() or not stop.first.is_visible():
                                        log.info("Task appears to have completed!")
                                        time.sleep(5)
                                        break
                                    time.sleep(5)

                                # Scroll through the result
                                page.evaluate("""() => {
                                    const els = document.querySelectorAll('*');
                                    for (const el of els) {
                                        if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
                                            el.scrollTop = el.scrollHeight;
                                        }
                                    }
                                }""")
                                time.sleep(3)

                    else:
                        log.info("No tickets remaining to submit")

            time.sleep(3)
            log.info("Demo recording complete!")

        finally:
            context.close()
            browser.close()

    # Find the recorded video
    videos = list(video_dir.glob("*.webm"))
    if videos:
        latest = max(videos, key=lambda p: p.stat().st_mtime)
        log.info(f"Video saved to: {latest}")
        print(f"Video: {latest}")
    else:
        log.warning("No video file found")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", default="videos", help="Directory for video files")
    p.add_argument("--work-ticket", action="store_true", help="Include ticket submission in demo")
    p.add_argument("--tickets", default="docspayment-dispute-management-tickets.md")
    p.add_argument("--state", default=".ticket_runner_state.json")
    p.add_argument("--env", help="Environment to select")
    p.add_argument("--wait-time", type=int, default=30, help="Seconds to wait after submitting")
    p.add_argument("--env-file", help="Path to .env file")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    config = load_config(env_file=args.env_file)
    config.headless = False
    if args.env:
        config.env_name = args.env

    record_demo(config, args)


if __name__ == "__main__":
    main()
