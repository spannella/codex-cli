#!/usr/bin/env python3
"""CLI/library for interacting with Codex task pages and exported HTML."""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

try:
    from playwright.sync_api import sync_playwright
except Exception:  # playwright is optional for static parsing workflows
    sync_playwright = None

PROMPT_SELECTORS = [
    "textarea#prompt-textarea",
    "textarea[placeholder*='Message']",
    "textarea[placeholder*='task']",
    "textarea[aria-label*='Message']",
    "div[contenteditable='true'][data-lexical-editor='true']",
    "div[contenteditable='true'][role='textbox']",
]

SEND_BUTTON_SELECTORS = [
    "button[data-testid='send-button']",
    "button[aria-label*='Send']",
    "button:has-text('Submit')",
    "button:has(svg)",
]

STOP_BUTTON_SELECTORS = [
    "button[data-testid='stop-button']",
    "button[aria-label*='Stop']",
]

BACK_BUTTON_SELECTORS = [
    "button[aria-label*='Back']",
    "a[aria-label*='Back']",
]

ENV_TRIGGER_SELECTORS = [
    "button[aria-label*='Environment']",
    "button:has-text('Environment')",
    "button:has-text('Env')",
    "[role='combobox'][aria-label*='Environment']",
]

TASK_LINK_RE = re.compile(r"https?://[^\s\"']+/codex/tasks/[\w-]+|/codex/tasks/[\w-]+", re.IGNORECASE)
DIFF_BLOCK_RE = re.compile(
    r"diff --git a/(?P<file>[^\s]+) b/(?P=file)(?P<body>.*?)(?=\n\s*diff --git a/|\Z)",
    re.DOTALL,
)
FILE_MENTION_RE = re.compile(r"\b([\w./-]+\.[a-zA-Z0-9]+)\b")
ENV_TOKEN_RE = re.compile(r"\b(env|environment)\b\s*[:=-]?\s*([A-Za-z0-9_.\-/]{2,32})", re.IGNORECASE)


@dataclass
class DiffFile:
    path: str
    content: str


@dataclass
class TaskSummary:
    title: str
    link: str
    status: str  # normal|open|merged


class CodexPageClient:
    def __init__(self, url: str, headless: bool = True, timeout_ms: int = 30_000):
        if sync_playwright is None:
            raise RuntimeError("playwright is not installed. Install with: pip install playwright")
        self.url = url
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self.page = None

    def __enter__(self) -> "CodexPageClient":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        context = self._browser.new_context()
        self.page = context.new_page()
        self.page.goto(self.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _first_visible(self, selectors: Iterable[str]):
        assert self.page is not None
        for selector in selectors:
            loc = self.page.locator(selector)
            if loc.count() and loc.first.is_visible():
                return loc.first
        return None

    def send_message(self, message: str) -> None:
        assert self.page is not None
        prompt = self._first_visible(PROMPT_SELECTORS)
        if prompt is None:
            raise RuntimeError("Could not find prompt/task input element.")
        prompt.click()
        prompt.fill(message)
        send_btn = self._first_visible(SEND_BUTTON_SELECTORS)
        if send_btn is None:
            prompt.press("Enter")
        else:
            send_btn.click()

    def is_working(self) -> bool:
        return self._first_visible(STOP_BUTTON_SELECTORS) is not None

    def wait_until_done(self, poll_interval_s: float = 1.0, timeout_s: float = 300.0) -> None:
        start = time.time()
        while time.time() - start < timeout_s:
            if not self.is_working():
                return
            time.sleep(poll_interval_s)
        raise TimeoutError("Timed out waiting for assistant to finish.")

    def request_pr(self, pr_request: str = "please create a pull request") -> None:
        self.send_message(pr_request)

    def go_back(self) -> None:
        assert self.page is not None
        back_btn = self._first_visible(BACK_BUTTON_SELECTORS)
        if back_btn is not None:
            back_btn.click()
        else:
            self.page.go_back()

    def select_env(self, env_name: str) -> None:
        assert self.page is not None
        trigger = self._first_visible(ENV_TRIGGER_SELECTORS)
        if trigger is None:
            return
        trigger.click()
        option = self.page.locator(f"[role='option']:has-text('{env_name}')")
        if option.count() and option.first.is_visible():
            option.first.click()
            return
        option = self.page.locator(f"button:has-text('{env_name}')")
        if option.count() and option.first.is_visible():
            option.first.click()

    def submit_task(self, task_text: str, env_name: Optional[str] = None) -> None:
        if env_name:
            self.select_env(env_name)
        self.send_message(task_text)


def strip_html(raw_html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def parse_diff_files_from_html(html_text: str) -> list[DiffFile]:
    unescaped = html.unescape(html_text)
    files: list[DiffFile] = []
    for m in DIFF_BLOCK_RE.finditer(unescaped):
        files.append(
            DiffFile(
                path=m.group("file"),
                content=("diff --git a/" + m.group("file") + " b/" + m.group("file") + m.group("body")).strip(),
            )
        )
    return files


def _status_from_window(window: str) -> str:
    w = window.lower()
    if "merged" in w:
        return "merged"
    if "open" in w and "pr" in w:
        return "open"
    if "open" in w:
        return "open"
    return "normal"


def list_tasks_from_html(page_html_path: Path) -> list[TaskSummary]:
    html_text = page_html_path.read_text(encoding="utf-8", errors="ignore")
    href_re = re.compile(r'href=["\'](?P<link>https?://[^"\']+/codex/tasks/[\w-]+|/codex/tasks/[\w-]+)["\']', re.IGNORECASE)
    out: list[TaskSummary] = []
    seen: set[str] = set()
    for m in href_re.finditer(html_text):
        link = html.unescape(m.group("link"))
        if link in seen:
            continue
        seen.add(link)

        div_start = html_text.rfind("<div", 0, m.start())
        div_end = html_text.find("</div>", m.end())
        if div_start != -1 and div_end != -1:
            raw_window = html_text[div_start : div_end + len("</div>")]
        else:
            start = max(0, m.start() - 220)
            end = min(len(html_text), m.end() + 220)
            raw_window = html_text[start:end]

        window = strip_html(raw_window)
        title = re.sub(r"https?://\S+|/codex/tasks/[\w-]+", "", window, flags=re.IGNORECASE)
        title = re.sub(r"\b(open|merged|pr|link)\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s+", " ", title).strip(" -:\n\t") or "(untitled task)"
        out.append(TaskSummary(title=title, link=link, status=_status_from_window(window)))
    return out


def list_envs_from_html(page_html_path: Path) -> list[str]:
    html_text = page_html_path.read_text(encoding="utf-8", errors="ignore")
    plain = strip_html(html_text)
    envs: list[str] = []
    for m in ENV_TOKEN_RE.finditer(plain):
        candidate = re.sub(r"\s+", " ", m.group(2)).strip(" -:,.|")
        if 1 < len(candidate) <= 40 and not candidate.lower().startswith("is"):
            envs.append(candidate)
    # fallback: common env labels often present in task pages
    for candidate in ("default", "dev", "staging", "prod"):
        if re.search(rf"\b{candidate}\b", plain, flags=re.IGNORECASE):
            envs.append(candidate)
    out = []
    seen = set()
    for e in envs:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def list_diff_files(page_html_path: Path) -> list[str]:
    html_text = page_html_path.read_text(encoding="utf-8", errors="ignore")
    diff_files = [d.path for d in parse_diff_files_from_html(html_text)]
    if diff_files:
        return diff_files
    mentions = []
    text = strip_html(html_text)
    for m in FILE_MENTION_RE.finditer(text):
        token = m.group(1)
        if any(token.lower().endswith(ext) for ext in (".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yml", ".yaml", ".toml", ".rs", ".go")):
            mentions.append(token)
    out = []
    seen = set()
    for item in mentions:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def get_diff_file_content(page_html_path: Path, file_name: str) -> Optional[str]:
    html_text = page_html_path.read_text(encoding="utf-8", errors="ignore")
    for d in parse_diff_files_from_html(html_text):
        if d.path.lower() == file_name.lower() or Path(d.path).name.lower() == file_name.lower():
            return d.content
    p = Path(file_name)
    if not p.exists():
        p = Path(page_html_path.parent, file_name)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore")
    return None


def _cmd_list_diff(args: argparse.Namespace) -> int:
    print("\n".join(list_diff_files(Path(args.page))))
    return 0


def _cmd_get_diff(args: argparse.Namespace) -> int:
    content = get_diff_file_content(Path(args.page), args.file)
    if content is None:
        raise SystemExit(f"No diff file found for: {args.file}")
    print(content)
    return 0


def _cmd_list_tasks(args: argparse.Namespace) -> int:
    tasks = list_tasks_from_html(Path(args.page))
    if args.json:
        print(json.dumps([asdict(t) for t in tasks], indent=2))
    else:
        for t in tasks:
            print(f"{t.status}\t{t.link}\t{t.title}")
    return 0


def _cmd_list_envs(args: argparse.Namespace) -> int:
    envs = list_envs_from_html(Path(args.page))
    if args.json:
        print(json.dumps(envs, indent=2))
    else:
        print("\n".join(envs))
    return 0


def _cmd_send(args: argparse.Namespace) -> int:
    with CodexPageClient(args.url, headless=not args.show_browser) as client:
        client.send_message(args.message)
        if args.wait:
            client.wait_until_done(timeout_s=args.timeout_s)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    with CodexPageClient(args.url, headless=not args.show_browser) as client:
        print("working" if client.is_working() else "done")
    return 0


def _cmd_request_pr(args: argparse.Namespace) -> int:
    with CodexPageClient(args.url, headless=not args.show_browser) as client:
        client.request_pr(args.message)
        if args.wait:
            client.wait_until_done(timeout_s=args.timeout_s)
    return 0


def _cmd_back(args: argparse.Namespace) -> int:
    with CodexPageClient(args.url, headless=not args.show_browser) as client:
        client.go_back()
    return 0


def _cmd_submit_task(args: argparse.Namespace) -> int:
    with CodexPageClient(args.url, headless=not args.show_browser) as client:
        client.submit_task(args.text, env_name=args.env)
        if args.wait:
            client.wait_until_done(timeout_s=args.timeout_s)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list-diff-files", help="List diff file paths from exported page HTML")
    s.add_argument("--page", default="page.html")
    s.set_defaults(func=_cmd_list_diff)

    s = sub.add_parser("get-diff-file", help="Get a diff file block by name/path from exported page HTML")
    s.add_argument("file")
    s.add_argument("--page", default="page.html")
    s.set_defaults(func=_cmd_get_diff)

    s = sub.add_parser("list-tasks", help="List tasks and status from main page export (e.g. page2.html)")
    s.add_argument("--page", default="page2.html")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_list_tasks)

    s = sub.add_parser("list-envs", help="List environments from main page export (e.g. page2.html)")
    s.add_argument("--page", default="page2.html")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_cmd_list_envs)

    for name, handler, help_text in [
        ("send", _cmd_send, "Send a message to a live task URL"),
        ("status", _cmd_status, "Check if assistant is working/done on live task URL"),
        ("request-pr", _cmd_request_pr, "Send a PR request message"),
        ("back", _cmd_back, "Click back arrow or browser-back"),
    ]:
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--url", required=True)
        s.add_argument("--show-browser", action="store_true")
        if name in {"send", "request-pr"}:
            s.add_argument("message", nargs="?", default="please create a pull request" if name == "request-pr" else None)
            s.add_argument("--wait", action="store_true")
            s.add_argument("--timeout-s", type=float, default=300)
        s.set_defaults(func=handler)

    s = sub.add_parser("submit-task", help="Submit a new task on main page URL, optionally selecting env")
    s.add_argument("--url", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--env", help="Environment label to select before submit")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--timeout-s", type=float, default=300)
    s.add_argument("--show-browser", action="store_true")
    s.set_defaults(func=_cmd_submit_task)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
