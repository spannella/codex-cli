"""codex-cli: CLI and Python library for automating the ChatGPT Codex web UI."""

from .config import Config, load_config
from .client import CodexClient
from ._page_client import CodexPageClient

__all__ = ["CodexClient", "CodexPageClient", "Config", "load_config"]
__version__ = "0.1.0"
