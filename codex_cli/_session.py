"""Session context manager for authenticated Codex browser sessions."""

from __future__ import annotations

from contextlib import contextmanager

from ._page_client import CodexPageClient
from ._auth import ensure_authenticated
from .config import Config


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
