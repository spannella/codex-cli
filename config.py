#!/usr/bin/env python3
"""Centralized configuration for the Codex automation bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]


@dataclass
class Config:
    email: str = ""
    password: str = ""
    totp_secret: str = ""
    codex_url: str = "https://chatgpt.com/codex"
    storage_state_path: str = ".playwright_storage_state.json"
    screenshot_dir: str = "screenshots"
    env_name: Optional[str] = None
    headless: bool = True
    task_timeout_s: float = 900.0
    login_timeout_s: float = 120.0
    max_retries: int = 2
    request_pr: bool = True
    poll_interval_s: float = 3.0

    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password)

    @property
    def has_stored_session(self) -> bool:
        return Path(self.storage_state_path).is_file()

    def validate(self) -> None:
        if not self.has_credentials and not self.has_stored_session:
            raise ValueError(
                "No credentials found and no stored session exists.\n"
                "Set CODEX_EMAIL and CODEX_PASSWORD environment variables,\n"
                "or create a .env file with those values."
            )


def load_config(env_file: Optional[str] = None) -> Config:
    """Load config from environment variables, with optional .env file."""
    if load_dotenv is not None:
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv(dotenv_path=".env", override=False)

    def _bool(key: str, default: bool) -> bool:
        val = os.environ.get(key, "").lower()
        if val in ("1", "true", "yes"):
            return True
        if val in ("0", "false", "no"):
            return False
        return default

    return Config(
        email=os.environ.get("CODEX_EMAIL", ""),
        password=os.environ.get("CODEX_PASSWORD", ""),
        totp_secret=os.environ.get("CODEX_TOTP_SECRET", ""),
        codex_url=os.environ.get("CODEX_URL", "https://chatgpt.com/codex"),
        storage_state_path=os.environ.get("CODEX_STORAGE_STATE", ".playwright_storage_state.json"),
        screenshot_dir=os.environ.get("CODEX_SCREENSHOT_DIR", "screenshots"),
        env_name=os.environ.get("CODEX_ENV") or None,
        headless=_bool("CODEX_HEADLESS", True),
        task_timeout_s=float(os.environ.get("CODEX_TASK_TIMEOUT", "900")),
        login_timeout_s=float(os.environ.get("CODEX_LOGIN_TIMEOUT", "120")),
        max_retries=int(os.environ.get("CODEX_MAX_RETRIES", "2")),
        request_pr=_bool("CODEX_REQUEST_PR", True),
        poll_interval_s=float(os.environ.get("CODEX_POLL_INTERVAL", "3")),
    )
