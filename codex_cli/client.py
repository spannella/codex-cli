"""High-level Python library for the ChatGPT Codex web UI.

Usage::

    from codex_cli import CodexClient, load_config

    config = load_config()
    with CodexClient(config) as client:
        tasks = client.list_tasks()
        client.submit_task("implement feature X", env="org/repo", wait=True)
        client.create_pr()
        usage = client.get_usage()
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Union

from ._page_client import CodexPageClient
from ._auth import ensure_authenticated
from .config import Config, load_config

log = logging.getLogger(__name__)


class CodexClient:
    """High-level client for the ChatGPT Codex web UI.

    Wraps browser automation into clean Pythonic methods.
    Use as a context manager for automatic session management.
    """

    def __init__(self, config: Optional[Config] = None, **kwargs):
        """Create a CodexClient.

        Args:
            config: A Config object. If None, loads from environment/.env.
            **kwargs: Override config fields (email, password, headless, etc.)
        """
        if config is None:
            config = load_config()
        # Apply overrides
        for key, val in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, val)
        self.config = config
        self._client: Optional[CodexPageClient] = None
        self._task_cache: Optional[list[dict]] = None

    def __enter__(self) -> "CodexClient":
        """Open browser, authenticate, return self."""
        self._client = CodexPageClient(
            url=self.config.codex_url,
            headless=self.config.headless,
            timeout_ms=60_000,
            storage_state_path=self.config.storage_state_path,
        )
        self._client.open()
        ensure_authenticated(self._client._context, self._client.page, self.config)
        self._client.save_storage_state()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Save session and close browser."""
        if self._client:
            try:
                self._client.save_storage_state()
            except Exception:
                pass
            self._client.close()
            self._client = None

    @property
    def page_client(self) -> CodexPageClient:
        """Access the underlying CodexPageClient (advanced use)."""
        if self._client is None:
            raise RuntimeError("Client not open. Use 'with CodexClient(...) as client:'")
        return self._client

    # --- Task Management ---

    def list_tasks(self, use_cache: bool = False) -> list[dict]:
        """List all tasks. Returns list of {title, href, date, repo, status, diff}.

        Args:
            use_cache: If True, return cached tasks without opening a browser.
                       Requires a prior call to list_tasks() or refresh_tasks().
        """
        if use_cache and self._task_cache is not None:
            return self._task_cache
        pc = self.page_client
        pc.navigate_to(self.config.codex_url)
        time.sleep(3)
        tasks = pc.get_task_list()
        self._task_cache = tasks
        return tasks

    def refresh_tasks(self) -> list[dict]:
        """Force-refresh the task list from the browser."""
        self._task_cache = None
        return self.list_tasks()

    def _find_task(self, task_id: Union[str, int]) -> dict:
        """Resolve a task by index (int) or title substring (str)."""
        tasks = self._task_cache or self.list_tasks()
        if isinstance(task_id, int):
            if 0 <= task_id < len(tasks):
                return tasks[task_id]
            raise IndexError(f"Task index {task_id} out of range (0-{len(tasks)-1})")
        for t in tasks:
            if str(task_id).lower() in t["title"].lower():
                return t
        raise KeyError(f"No task matching '{task_id}'")

    def get_task(self, task_id: Union[str, int]) -> dict:
        """Get a task by index or title substring."""
        return self._find_task(task_id)

    def submit_task(
        self,
        text: str,
        env: Optional[str] = None,
        branch: Optional[str] = None,
        wait: bool = False,
    ) -> None:
        """Submit a new task from the main Codex page.

        Args:
            text: Task description.
            env: Environment/repo to select.
            branch: Branch to select.
            wait: If True, wait for the task to complete.
        """
        pc = self.page_client
        pc.navigate_to(self.config.codex_url)
        time.sleep(3)

        if env:
            pc.select_environment(env)
            time.sleep(2)
        if branch:
            pc.select_branch(branch)
            time.sleep(2)

        pc.submit_new_task(text)

        if wait:
            time.sleep(5)
            # Navigate to the new task and wait
            tasks = pc.get_task_list(scroll=False)
            if tasks:
                pc.open_task_by_href(tasks[0]["href"])
                time.sleep(5)
                pc.wait_for_task_completion(timeout_s=self.config.task_timeout_s)

    def open_task(self, task_id: Union[str, int]) -> dict:
        """Open a task by index or title substring. Returns the task dict."""
        task = self._find_task(task_id)
        self.page_client.open_task_by_href(task["href"])
        time.sleep(5)
        return task

    def cancel_task(self, task_id: Optional[Union[str, int]] = None) -> bool:
        """Cancel a running task. If task_id given, navigates to it first."""
        if task_id is not None:
            self.open_task(task_id)
        return self.page_client.cancel_task()

    def send_message(
        self,
        message: str,
        task_id: Optional[Union[str, int]] = None,
        wait: bool = False,
    ) -> None:
        """Send a chat message in a task.

        Args:
            message: The message to send.
            task_id: Task to navigate to first (index or title). If None, uses current view.
            wait: If True, wait for the task to complete after sending.
        """
        if task_id is not None:
            self.open_task(task_id)
        self.page_client.send_task_message(message)
        if wait:
            time.sleep(5)
            self.page_client.wait_for_task_completion(timeout_s=self.config.task_timeout_s)

    def create_pr(
        self,
        task_id: Optional[Union[str, int]] = None,
        message: str = "please create a pull request",
        wait: bool = False,
    ) -> None:
        """Send a PR creation request in a task."""
        self.send_message(message, task_id=task_id, wait=wait)

    # --- Task Inspection ---

    def get_status(self, task_id: Optional[Union[str, int]] = None) -> dict:
        """Get task status. If task_id given, looks it up; otherwise returns detail of current view."""
        if task_id is not None:
            return self._find_task(task_id)
        return self.page_client.get_task_detail()

    def get_files(self, task_id: Optional[Union[str, int]] = None) -> list[dict]:
        """Get changed files in a task. Returns list of {path, status, additions, deletions}."""
        if task_id is not None:
            self.open_task(task_id)
        return self.page_client.get_task_files()

    def get_file_content(self, filepath: str, task_id: Optional[Union[str, int]] = None) -> Optional[str]:
        """Get the diff content of a file in a task."""
        if task_id is not None:
            self.open_task(task_id)
        return self.page_client.get_file_content(filepath)

    def get_history(self, task_id: Optional[Union[str, int]] = None) -> list[dict]:
        """Get conversation history. Returns list of {role, content}."""
        if task_id is not None:
            self.open_task(task_id)
        return self.page_client.get_conversation_history()

    def get_logs(self, task_id: Optional[Union[str, int]] = None) -> list[str]:
        """Get execution logs from a task."""
        if task_id is not None:
            self.open_task(task_id)
        return self.page_client.get_task_logs()

    # --- Account ---

    def get_usage(self) -> dict:
        """Get usage dashboard data (limits, credits, history)."""
        return self.page_client.get_usage()

    def get_environments(self) -> list[str]:
        """List available environments/repos."""
        pc = self.page_client
        pc.navigate_to(self.config.codex_url)
        time.sleep(3)
        return pc.get_environments()

    def go_back(self) -> None:
        """Navigate back to the main Codex task list."""
        self.page_client.go_back_to_tasks()
