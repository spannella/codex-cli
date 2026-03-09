#!/usr/bin/env python3
"""Run ticket-by-ticket implementation prompts on top of codex_page_client library."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from codex_page_client import CodexPageClient

TICKET_HEADER_RE = re.compile(r"^###\s+(PDM-\d{3})\s+—\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Ticket:
    ticket_id: str
    title: str
    body: str


def parse_tickets(markdown: str) -> list[Ticket]:
    matches = list(TICKET_HEADER_RE.finditer(markdown))
    tickets: list[Ticket] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        tickets.append(Ticket(ticket_id=m.group(1), title=m.group(2).strip(), body=markdown[start:end].strip()))
    return tickets


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"implemented": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def next_ticket(tickets: list[Ticket], implemented: set[str]) -> Optional[Ticket]:
    for t in tickets:
        if t.ticket_id not in implemented:
            return t
    return None


def build_message(ticket: Ticket) -> str:
    return f"please implement: {ticket.body}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tickets", default="docspayment-dispute-management-tickets.md")
    p.add_argument("--state", default=".ticket_runner_state.json")
    p.add_argument("--url", help="Live task URL. If omitted, prints next prompt only.")
    p.add_argument("--show-browser", action="store_true")
    p.add_argument("--count", type=int, default=1, help="How many tickets to send in sequence")
    p.add_argument("--wait-timeout-s", type=float, default=600)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    tickets_md = Path(args.tickets).read_text(encoding="utf-8", errors="ignore")
    tickets = parse_tickets(tickets_md)
    if not tickets:
        raise SystemExit("No tickets found in markdown file")

    state_path = Path(args.state)
    state = load_state(state_path)
    implemented: set[str] = set(state.get("implemented", []))

    sent = 0
    for _ in range(args.count):
        t = next_ticket(tickets, implemented)
        if t is None:
            print("All tickets completed according to state file.")
            break

        message = build_message(t)
        print(f"Next ticket: {t.ticket_id} — {t.title}")
        print(message)
        print()

        if not args.dry_run and args.url:
            with CodexPageClient(args.url, headless=not args.show_browser) as client:
                client.send_message(message)
                client.wait_until_done(timeout_s=args.wait_timeout_s)

        implemented.add(t.ticket_id)
        sent += 1

    if not args.dry_run:
        state["implemented"] = sorted(implemented)
        save_state(state_path, state)
        print(f"Updated state: {state_path}")
    else:
        print("Dry run: state file not modified.")
    print(f"Tickets advanced this run: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
