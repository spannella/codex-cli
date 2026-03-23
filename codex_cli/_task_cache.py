"""Task cache and current-task context helpers."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .config import Config

log = logging.getLogger(__name__)

TASK_CACHE_FILE = ".codex_task_cache.json"
CURRENT_TASK_FILE = ".codex_current_task.json"


def save_task_cache(tasks: list[dict]) -> None:
    Path(TASK_CACHE_FILE).write_text(
        json.dumps({"tasks": tasks, "cached_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=2),
        encoding="utf-8",
    )


def load_task_cache() -> Optional[list[dict]]:
    p = Path(TASK_CACHE_FILE)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("tasks")
    except Exception:
        return None


def set_current_task(task: dict) -> None:
    Path(CURRENT_TASK_FILE).write_text(json.dumps(task, indent=2), encoding="utf-8")


def get_current_task() -> Optional[dict]:
    p = Path(CURRENT_TASK_FILE)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_task(target: Optional[str], config: Config, client=None) -> Optional[dict]:
    """Resolve a task from a target string (index or title substring).

    Falls back to current task context if target is None.
    """
    if not target:
        current = get_current_task()
        if current:
            log.info(f"Using current task: {current['title']}")
            return current
        return None

    tasks = load_task_cache()
    if tasks is None and client:
        tasks = client.get_task_list()
        save_task_cache(tasks)

    if tasks is None:
        return None

    if target.isdigit():
        idx = int(target)
        if 0 <= idx < len(tasks):
            return tasks[idx]
    else:
        for t in tasks:
            if target.lower() in t["title"].lower():
                return t

    return None


def navigate_to_task(client, task: dict) -> None:
    """Navigate to a task and set it as current."""
    client.open_task_by_href(task["href"])
    set_current_task(task)
    import time
    time.sleep(5)
