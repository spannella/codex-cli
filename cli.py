#!/usr/bin/env python3
"""Backward-compatibility shim. Use codex_cli.cli instead."""
from codex_cli.cli import main
from codex_cli._session import codex_session  # noqa: F401
from codex_cli._task_cache import save_task_cache as _save_task_cache  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
