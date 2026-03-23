"""Backward-compatibility shim. Use codex_cli.ticket_runner instead."""
from codex_cli.ticket_runner import *  # noqa: F401, F403
from codex_cli.ticket_runner import main, parse_tickets, build_message, next_ticket, load_state  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
