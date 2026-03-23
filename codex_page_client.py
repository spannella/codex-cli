#!/usr/bin/env python3
"""Browser automation client for the ChatGPT Codex web UI."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Iterable, Optional

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Selectors — discovered from live Codex UI (March 2026)
# ---------------------------------------------------------------------------

# Main page: task input (may be contenteditable div or textarea)
MAIN_PROMPT_SELECTORS = [
    "[role='textbox']",
    "[contenteditable='true']",
    "textarea[placeholder*='Describe a task']",
    "textarea[placeholder*='Ask Codex']",
    "textarea#prompt-textarea",
]

# Main page: submit button
MAIN_SUBMIT_SELECTORS = [
    "button[aria-label*='Submit']",
    "button[aria-label*='Send']",
]

# Main page: environment selector (opens a dialog)
ENV_SELECTOR = "button[aria-label='View all code environments']"

# Main page: branch selector
BRANCH_SELECTOR = "button[aria-label='Search for your branch']"

# Main page: task list items — <a> tags with /codex/tasks/ hrefs
TASK_LINK_SELECTOR = "a[href*='/codex/tasks/']"

# Main page: task items with class containing "task"
TASK_ITEM_SELECTOR = "[class*='task']"

# Main page: tabs
TAB_TASKS = "button:has-text('Tasks')"
TAB_CODE_REVIEWS = "button:has-text('Code reviews')"
TAB_ARCHIVE = "button:has-text('Archive')"

# Task detail: back button
BACK_BUTTON_SELECTOR = "button[aria-label='Go back to tasks']"

# Task detail: chat input (may be contenteditable div or textarea)
TASK_PROMPT_SELECTORS = [
    "[contenteditable='true']",
    "textarea[placeholder*='Request changes']",
    "textarea[placeholder*='ask a question']",
    "textarea[placeholder*='Describe a task']",
    "textarea[placeholder*='Ask Codex']",
]

# Task detail: send/submit button
TASK_SEND_SELECTORS = [
    "button[aria-label='Submit']",
    "button[aria-label*='Submit']",
    "button[aria-label*='Send']",
]

# Task detail: files toggle
FILES_TOGGLE_SELECTOR = "button[aria-label='Toggle file list diffs']"

# Task detail: worked-for sections (expandable log headers)
WORKED_FOR_SELECTOR = "button:has-text('Worked for')"

# Task detail: user messages
USER_MESSAGE_SELECTOR = "[class*='self-end'][class*='bg-token-bg-tertiary']"

# Task detail: action buttons
ARCHIVE_BUTTON = "button[aria-label='Archive Task']"
SHARE_BUTTON = "button[aria-label='Share task']"

# Task detail: PR/commit
VIEW_PR_SELECTOR = "a:has-text('View PR')"
COMMIT_BUTTON_SELECTOR = "button:has-text('Commit')"

# Task detail: cancel/stop
STOP_BUTTON_SELECTORS = [
    "button[aria-label*='Stop']",
    "button[aria-label*='Cancel']",
    "button:has-text('Stop')",
]


class CodexPageClient:
    def __init__(
        self,
        url: str,
        headless: bool = True,
        timeout_ms: int = 30_000,
        storage_state_path: Optional[str] = None,
    ):
        if sync_playwright is None:
            raise RuntimeError("playwright is not installed. Install with: pip install playwright")
        self.url = url
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._storage_state_path = storage_state_path
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    # --- Lifecycle ---

    def open(self) -> "CodexPageClient":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx_kwargs: dict = {}
        if self._storage_state_path and Path(self._storage_state_path).is_file():
            ctx_kwargs["storage_state"] = self._storage_state_path
        self._context = self._browser.new_context(**ctx_kwargs)
        self.page = self._context.new_page()
        self.page.goto(self.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        return self

    def close(self) -> None:
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None
        self._context = None
        self.page = None

    def __enter__(self) -> "CodexPageClient":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def save_storage_state(self, path: Optional[str] = None) -> None:
        dest = path or self._storage_state_path
        if dest and self._context:
            self._context.storage_state(path=dest)

    # --- Scrolling ---

    def _scroll_to_bottom(self, max_rounds: int = 20, pause_s: float = 2.0) -> None:
        """Scroll all scrollable containers to the bottom repeatedly to trigger infinite scroll."""
        assert self.page is not None
        for _ in range(max_rounds):
            prev_height = self.page.evaluate("""() => {
                let maxSH = 0;
                for (const el of document.querySelectorAll('*')) {
                    if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
                        el.scrollTop = el.scrollHeight;
                        maxSH = Math.max(maxSH, el.scrollHeight);
                    }
                }
                return maxSH;
            }""")
            time.sleep(pause_s)
            new_height = self.page.evaluate("""() => {
                let maxSH = 0;
                for (const el of document.querySelectorAll('*')) {
                    if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
                        maxSH = Math.max(maxSH, el.scrollHeight);
                    }
                }
                return maxSH;
            }""")
            if new_height == prev_height:
                break

    def _scroll_to_top(self, max_rounds: int = 20, pause_s: float = 2.0) -> None:
        """Scroll all scrollable containers to the top repeatedly to trigger reverse infinite scroll."""
        assert self.page is not None
        for _ in range(max_rounds):
            changed = self.page.evaluate("""() => {
                let scrolled = false;
                for (const el of document.querySelectorAll('*')) {
                    if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 100) {
                        if (el.scrollTop > 0) {
                            el.scrollTop = 0;
                            scrolled = true;
                        }
                    }
                }
                return scrolled;
            }""")
            if not changed:
                break
            time.sleep(pause_s)

    # --- Navigation ---

    def navigate_to(self, url: str) -> None:
        assert self.page is not None
        self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)

    def reload(self) -> None:
        assert self.page is not None
        self.page.reload(wait_until="domcontentloaded", timeout=self.timeout_ms)

    # --- Screenshots ---

    def screenshot(self, path: str) -> None:
        try:
            if self.page:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=path, full_page=True)
        except Exception:
            pass

    # --- Element helpers ---

    def _first_visible(self, selectors: Iterable[str]):
        assert self.page is not None
        for selector in selectors:
            try:
                loc = self.page.locator(selector)
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
        return None

    # ===================================================================
    # MAIN PAGE OPERATIONS
    # ===================================================================

    def get_task_list(self, scroll: bool = True, max_scroll_rounds: int = 20) -> list[dict]:
        """Get all tasks from the main Codex page.

        If scroll=True, scrolls to load all tasks via infinite scroll.
        Returns list of {title, href, date, repo, status, diff}.
        """
        assert self.page is not None

        if scroll:
            self._scroll_to_bottom(max_rounds=max_scroll_rounds)

        links = self.page.locator(TASK_LINK_SELECTOR)
        count = links.count()
        tasks = []
        seen_hrefs: set[str] = set()

        for i in range(count):
            try:
                el = links.nth(i)
                if not el.is_visible():
                    continue
                href = el.get_attribute("href") or ""
                if not href or href in seen_hrefs:
                    continue
                # Skip non-task links (like docs links)
                if "/codex/tasks/" not in href:
                    continue
                seen_hrefs.add(href)

                raw_text = el.inner_text().strip()
                lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

                title = lines[0] if lines else "(untitled)"
                date = ""
                repo = ""
                status = ""
                diff = ""

                for line in lines[1:]:
                    if re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d", line):
                        date = line
                    elif "/" in line and not line.startswith("+") and not line.startswith("-"):
                        repo = line
                    elif line in ("Merged", "Open", "Closed", "In progress", "Queued", "Completed"):
                        status = line
                    elif re.match(r"^[+\-]\d", line):
                        diff = (diff + " " + line).strip()

                tasks.append({
                    "title": title,
                    "href": href,
                    "date": date,
                    "repo": repo,
                    "status": status,
                    "diff": diff,
                })
            except Exception:
                continue

        return tasks

    def get_environments(self) -> list[str]:
        """Open the environment selector dialog and extract available environments."""
        assert self.page is not None
        trigger = self.page.locator(ENV_SELECTOR)
        if not trigger.count() or not trigger.first.is_visible():
            return []

        trigger.first.click()
        time.sleep(2)

        envs = []
        # Look for items in the dialog/popover that opened
        for sel in ["[role='option']", "[role='menuitem']", "[role='listbox'] button",
                     "[data-state='open'] button", "[role='dialog'] button"]:
            try:
                items = self.page.locator(sel)
                for i in range(items.count()):
                    if items.nth(i).is_visible():
                        text = items.nth(i).inner_text().strip()
                        if text and text not in envs and len(text) < 60:
                            envs.append(text)
            except Exception:
                continue

        # Close the dialog
        self.page.keyboard.press("Escape")
        time.sleep(1)
        return envs

    def select_environment(self, env_name: str) -> None:
        """Select an environment from the environment dropdown."""
        assert self.page is not None
        trigger = self.page.locator(ENV_SELECTOR)
        if not trigger.count() or not trigger.first.is_visible():
            log.warning("Environment selector not found")
            return

        trigger.first.click()
        time.sleep(2)

        # Find and click the matching option
        for sel in [f"[role='option']:has-text('{env_name}')",
                     f"[role='menuitem']:has-text('{env_name}')",
                     f"button:has-text('{env_name}')"]:
            try:
                opt = self.page.locator(sel)
                if opt.count() and opt.first.is_visible():
                    opt.first.click()
                    time.sleep(1)
                    return
            except Exception:
                continue

        # Close if we didn't find it
        self.page.keyboard.press("Escape")
        log.warning(f"Environment '{env_name}' not found in selector")

    def select_branch(self, branch_name: str) -> None:
        """Select a branch from the branch dropdown."""
        assert self.page is not None
        trigger = self.page.locator(BRANCH_SELECTOR)
        if not trigger.count() or not trigger.first.is_visible():
            log.warning("Branch selector not found")
            return

        trigger.first.click()
        time.sleep(2)

        # Type the branch name in search if there's an input
        search = self.page.locator("input[placeholder*='branch'], input[placeholder*='Branch'], input[type='text']")
        if search.count() and search.first.is_visible():
            search.first.fill(branch_name)
            time.sleep(1)

        # Click matching option
        for sel in [f"[role='option']:has-text('{branch_name}')",
                     f"button:has-text('{branch_name}')"]:
            try:
                opt = self.page.locator(sel)
                if opt.count() and opt.first.is_visible():
                    opt.first.click()
                    time.sleep(1)
                    return
            except Exception:
                continue

        self.page.keyboard.press("Escape")
        log.warning(f"Branch '{branch_name}' not found")

    def submit_new_task(self, task_text: str) -> None:
        """Submit a new task from the main Codex page."""
        assert self.page is not None
        prompt = self._first_visible(MAIN_PROMPT_SELECTORS)
        if prompt is None:
            raise RuntimeError("Could not find task input on main page.")

        prompt.click()
        time.sleep(0.5)

        # Clear existing content and type the new task
        is_editable = prompt.evaluate("el => el.contentEditable === 'true'")
        if is_editable:
            # Select all and replace for contenteditable
            prompt.press("Control+a")
            prompt.type(task_text)
        else:
            prompt.fill(task_text)
        time.sleep(1)

        send_btn = self._first_visible(MAIN_SUBMIT_SELECTORS)
        if send_btn:
            send_btn.click()
        else:
            prompt.press("Enter")

    def open_task_by_href(self, href: str) -> None:
        """Navigate to a task by its href."""
        assert self.page is not None
        if href.startswith("/"):
            href = "https://chatgpt.com" + href
        self.navigate_to(href)

    # ===================================================================
    # TASK DETAIL OPERATIONS
    # ===================================================================

    def is_in_task_view(self) -> bool:
        """Check if we're currently in a task detail view."""
        assert self.page is not None
        back = self.page.locator(BACK_BUTTON_SELECTOR)
        return back.count() > 0 and back.first.is_visible()

    def go_back_to_tasks(self) -> None:
        """Click the back button to return to main task list."""
        assert self.page is not None
        back = self.page.locator(BACK_BUTTON_SELECTOR)
        if back.count() and back.first.is_visible():
            back.first.click()
            time.sleep(3)
        else:
            self.navigate_to(self.url)

    def get_task_detail(self) -> dict:
        """Get details about the currently open task."""
        assert self.page is not None
        info: dict = {"in_task_view": self.is_in_task_view()}

        # Title - usually the first heading or prominent text
        try:
            # Task title is typically in the header area
            body_text = self.page.locator("body").inner_text()
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            if lines:
                info["first_lines"] = lines[:5]
        except Exception:
            pass

        # PR link
        pr_link = self.page.locator(VIEW_PR_SELECTOR)
        if pr_link.count() and pr_link.first.is_visible():
            info["pr_url"] = pr_link.first.get_attribute("href") or ""

        # Files count
        files_btns = self.page.locator(FILES_TOGGLE_SELECTOR)
        info["file_sections"] = files_btns.count()

        # Worked-for entries
        worked = self.page.locator(WORKED_FOR_SELECTOR)
        info["work_entries"] = worked.count()

        return info

    def send_task_message(self, message: str) -> None:
        """Send a chat message in the task detail view."""
        assert self.page is not None
        prompt = self._first_visible(TASK_PROMPT_SELECTORS)
        if prompt is None:
            prompt = self._first_visible(MAIN_PROMPT_SELECTORS)
        if prompt is None:
            raise RuntimeError("Could not find chat input in task view.")

        prompt.click()
        time.sleep(0.5)

        # contenteditable divs need type() instead of fill()
        tag = prompt.evaluate("el => el.tagName")
        is_editable = prompt.evaluate("el => el.contentEditable === 'true'")
        if is_editable or tag == "DIV":
            prompt.type(message)
        else:
            prompt.fill(message)
        time.sleep(1)

        send_btn = self._first_visible(TASK_SEND_SELECTORS)
        if send_btn:
            send_btn.click()
        else:
            prompt.press("Enter")

    def get_task_files(self) -> list[dict]:
        """Get list of changed files from task detail view.

        Clicks all 'Files (N)' toggle buttons to reveal file names, then collects them.
        Returns list of {path, status, additions, deletions}.
        """
        assert self.page is not None
        files: list[dict] = []
        seen: set[str] = set()

        # Click all Files toggle buttons to expand them
        toggles = self.page.locator(FILES_TOGGLE_SELECTOR)
        for i in range(toggles.count()):
            try:
                if toggles.nth(i).is_visible():
                    toggles.nth(i).click()
                    time.sleep(1)
            except Exception:
                continue

        time.sleep(2)

        # Look for file paths in the expanded sections
        all_buttons = self.page.locator("button")
        for i in range(all_buttons.count()):
            try:
                if not all_buttons.nth(i).is_visible():
                    continue
                raw = all_buttons.nth(i).inner_text().strip()
                lines = [l.strip() for l in raw.split("\n") if l.strip()]
                if not lines:
                    continue

                # First line should be a filename (basename)
                first = lines[0]
                if not re.match(r"^[\w./\-]+\.\w+$", first):
                    continue

                # Second line might be the full path
                full_path = lines[1] if len(lines) > 1 and "/" in lines[1] else first

                # Check for status like "New", "+N", "-N"
                status = ""
                additions = ""
                deletions = ""
                for line in lines[1:]:
                    if line == "New":
                        status = "new"
                    elif line.startswith("+"):
                        additions = line
                    elif line.startswith("-"):
                        deletions = line

                if full_path not in seen:
                    seen.add(full_path)
                    files.append({
                        "path": full_path,
                        "status": status,
                        "additions": additions,
                        "deletions": deletions,
                    })
            except Exception:
                continue

        return files

    def get_file_content(self, filename: str) -> Optional[str]:
        """Get the diff/content of a specific file from the task detail view.

        Expands 'Worked for' sections, switches to Diff tab, and finds the file.
        """
        assert self.page is not None

        # First try expanding Worked For sections and using the Diff tab
        worked = self.page.locator(WORKED_FOR_SELECTOR)
        for i in range(worked.count()):
            try:
                if not worked.nth(i).is_visible():
                    continue

                worked.nth(i).click()
                time.sleep(2)

                # Make sure we're on the Diff tab
                diff_tab = self.page.locator("button[aria-label*='Tab']:has-text('Diff')")
                if diff_tab.count() and diff_tab.first.is_visible():
                    diff_tab.first.click()
                    time.sleep(1)

                # Expand file list if there's a toggle
                toggles = self.page.locator(FILES_TOGGLE_SELECTOR)
                for t in range(toggles.count()):
                    try:
                        if toggles.nth(t).is_visible():
                            toggles.nth(t).click()
                            time.sleep(1)
                    except Exception:
                        continue

                # Look for the file button and click it
                all_buttons = self.page.locator("button")
                for b in range(all_buttons.count()):
                    try:
                        if not all_buttons.nth(b).is_visible():
                            continue
                        raw = all_buttons.nth(b).inner_text().strip()
                        lines = [l.strip() for l in raw.split("\n") if l.strip()]
                        if not lines:
                            continue
                        # Match by full path (second line) or basename (first line)
                        btn_basename = lines[0]
                        btn_fullpath = lines[1] if len(lines) > 1 and "/" in lines[1] else lines[0]
                        fn_lower = filename.lower()
                        if btn_fullpath.lower() == fn_lower or btn_basename.lower() == fn_lower.split("/")[-1]:
                            all_buttons.nth(b).click()
                            time.sleep(3)

                            # Look for diff content — it's rendered in a table
                            for sel in ["table", "[class*='diff']"]:
                                code_els = self.page.locator(sel)
                                for j in range(code_els.count()):
                                    try:
                                        if code_els.nth(j).is_visible():
                                            content = code_els.nth(j).inner_text()
                                            if content.strip() and len(content.strip()) > 10:
                                                return content
                                    except Exception:
                                        continue
                    except Exception:
                        continue

                # Collapse the section
                worked.nth(i).click()
                time.sleep(1)
            except Exception:
                continue

        return None

    def get_conversation_history(self, scroll: bool = True) -> list[dict]:
        """Get conversation messages from the task detail view."""
        assert self.page is not None

        # Scroll to load full conversation history
        if scroll:
            self._scroll_to_top(max_rounds=10)
            time.sleep(1)
            self._scroll_to_bottom(max_rounds=10)

        messages = []

        # User messages have self-end class
        user_msgs = self.page.locator(USER_MESSAGE_SELECTOR)
        for i in range(user_msgs.count()):
            try:
                if user_msgs.nth(i).is_visible():
                    text = user_msgs.nth(i).inner_text().strip()
                    # Remove "Copy" button text that gets included
                    text = re.sub(r"\s*Copy\s*$", "", text)
                    if text:
                        messages.append({"role": "user", "content": text, "index": i})
            except Exception:
                continue

        # Assistant messages — everything between user messages and "Worked for" sections
        # The assistant responses are the main content blocks that aren't user messages
        worked_sections = self.page.locator(WORKED_FOR_SELECTOR)
        for i in range(worked_sections.count()):
            try:
                if worked_sections.nth(i).is_visible():
                    # Get the parent container's text as the assistant response summary
                    parent = worked_sections.nth(i).locator("..")
                    if parent.count():
                        text = parent.first.inner_text().strip()
                        text = re.sub(r"\s*Copy\s*", "", text)
                        if text:
                            messages.append({"role": "assistant", "content": text[:500], "index": i})
            except Exception:
                continue

        # Sort by index to maintain conversation order
        messages.sort(key=lambda m: m.get("index", 0))
        return messages

    def get_task_logs(self, scroll: bool = True) -> list[str]:
        """Get execution logs from the task detail view.

        Clicks 'Worked for' sections, switches to Logs tab, and extracts log content.
        """
        assert self.page is not None

        # Scroll to load full log history
        if scroll:
            self._scroll_to_top(max_rounds=10)
            time.sleep(1)
            self._scroll_to_bottom(max_rounds=10)

        logs = []

        worked = self.page.locator(WORKED_FOR_SELECTOR)
        for i in range(worked.count()):
            try:
                if not worked.nth(i).is_visible():
                    continue

                # Get the label text
                label = worked.nth(i).inner_text().strip()

                # Expand this section
                worked.nth(i).click()
                time.sleep(2)

                # Switch to Logs tab if available
                logs_tab = self.page.locator("button[aria-label='Tab to view the work logs']")
                if logs_tab.count() and logs_tab.first.is_visible():
                    logs_tab.first.click()
                    time.sleep(2)

                # Extract log content from overflow divs and pre elements
                section_logs = []
                for sel in ["pre", "div[class*='overflow']"]:
                    els = self.page.locator(sel)
                    for j in range(els.count()):
                        try:
                            if els.nth(j).is_visible():
                                text = els.nth(j).inner_text().strip()
                                # Filter out short text and non-log content
                                if text and len(text) > 20 and any(
                                    kw in text.lower() for kw in
                                    ["$", "#", "environment", "workspace", "install",
                                     "git", "npm", "pip", "python", "node", "shell",
                                     "error", "warning", "configur", "running", "->"]
                                ):
                                    section_logs.append(text)
                        except Exception:
                            continue

                if section_logs:
                    logs.append(f"=== {label} ===")
                    logs.extend(section_logs)

                # Collapse the section
                worked.nth(i).click()
                time.sleep(1)
            except Exception:
                continue

        return logs

    def cancel_task(self) -> bool:
        """Cancel a running task by clicking the stop button."""
        assert self.page is not None
        stop_btn = self._first_visible(STOP_BUTTON_SELECTORS)
        if stop_btn:
            stop_btn.click()
            time.sleep(2)
            return True
        return False

    def wait_for_task_completion(
        self,
        timeout_s: float = 900,
        poll_interval_s: float = 5.0,
        on_tick: Optional[callable] = None,
    ) -> None:
        """Wait for the current task to complete.

        Works by monitoring the page for stop/working indicators to disappear
        and checking for the task page to settle.
        """
        assert self.page is not None
        start = time.time()

        # Wait for working state to start first
        working_deadline = time.time() + 120
        started = False
        while time.time() < working_deadline:
            if self._first_visible(STOP_BUTTON_SELECTORS):
                started = True
                break
            # Check if task is already done (very fast task)
            worked = self.page.locator(WORKED_FOR_SELECTOR)
            if worked.count():
                return
            time.sleep(2)

        if not started:
            log.warning("Task may not have started (no stop button detected)")

        # Now wait for completion
        while time.time() - start < timeout_s:
            # If stop button is gone, task is done
            if not self._first_visible(STOP_BUTTON_SELECTORS):
                time.sleep(3)  # Brief pause to confirm
                if not self._first_visible(STOP_BUTTON_SELECTORS):
                    return
            if on_tick:
                on_tick(time.time() - start)
            time.sleep(poll_interval_s)

        raise TimeoutError("Timed out waiting for task to complete.")

    # ===================================================================
    # USAGE / SETTINGS
    # ===================================================================

    USAGE_URL = "https://chatgpt.com/codex/settings/general"

    def get_usage(self) -> dict:
        """Navigate to the usage dashboard and extract usage data.

        Returns dict with keys: hourly, weekly, code_review, credits, history.
        """
        assert self.page is not None
        self.navigate_to(self.USAGE_URL)
        time.sleep(5)

        # Click "Usage" in the sidebar
        usage_link = self.page.locator(":text-is('Usage')")
        if usage_link.count() and usage_link.first.is_visible():
            usage_link.first.click()
            time.sleep(3)

        body_text = self.page.locator("body").inner_text()
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]

        usage: dict = {
            "hourly": {},
            "weekly": {},
            "code_review": {},
            "credits": {},
            "history": [],
        }

        # Parse the structured text
        i = 0
        while i < len(lines):
            line = lines[i]

            # Hourly limit
            if "hour usage limit" in line.lower():
                pct = lines[i + 1] if i + 1 < len(lines) else ""
                remaining = pct.replace("remaining", "").strip() if "remaining" in (lines[i + 2] if i + 2 < len(lines) else "") else pct
                resets = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].startswith("Resets"):
                        resets = lines[j].replace("Resets ", "")
                        break
                usage["hourly"] = {
                    "label": line,
                    "remaining_pct": remaining,
                    "resets": resets,
                }

            # Weekly limit
            elif "weekly usage limit" in line.lower():
                pct = lines[i + 1] if i + 1 < len(lines) else ""
                remaining = pct.replace("remaining", "").strip() if "remaining" in (lines[i + 2] if i + 2 < len(lines) else "") else pct
                resets = ""
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].startswith("Resets"):
                        resets = lines[j].replace("Resets ", "")
                        break
                usage["weekly"] = {
                    "label": line,
                    "remaining_pct": remaining,
                    "resets": resets,
                }

            # Code review
            elif line.lower() == "code review":
                pct = lines[i + 1] if i + 1 < len(lines) else ""
                usage["code_review"] = {
                    "remaining_pct": pct.replace("remaining", "").strip(),
                }

            # Credits remaining
            elif "credits remaining" in line.lower():
                credits_val = lines[i + 1] if i + 1 < len(lines) else ""
                # Clean up — might be just a number like "2,126"
                credits_val = credits_val.replace(",", "").strip()
                if credits_val.replace(".", "").isdigit():
                    usage["credits"] = {"remaining": credits_val}

            # Usage history table rows: "Mar 5, 2026" followed by service and credits
            elif re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+,\s+\d{4}$", line):
                date = line
                service = lines[i + 1] if i + 1 < len(lines) else ""
                amount = lines[i + 2] if i + 2 < len(lines) else ""
                if "credits" in amount.lower() and re.search(r"\d", amount):
                    usage["history"].append({
                        "date": date,
                        "service": service,
                        "credits_used": re.sub(r"\s*credits\s*", "", amount).strip(),
                    })

            i += 1

        return usage
