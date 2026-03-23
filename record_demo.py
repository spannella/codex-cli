"""Backward-compatibility shim. Use codex_cli.record_demo instead."""
from codex_cli.record_demo import main  # noqa: F401

if __name__ == "__main__":
    main()
