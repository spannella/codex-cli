"""Tests for codex_cli.ticket_runner module."""

import unittest

from codex_cli.ticket_runner import build_message, next_ticket, parse_tickets


class TestTicketRunner(unittest.TestCase):
    def test_parse_tickets_and_next_ticket(self):
        md = """
### PDM-001 — One
Body1
### PDM-002 — Two
Body2
"""
        tickets = parse_tickets(md)
        self.assertEqual(len(tickets), 2)
        self.assertEqual(tickets[0].ticket_id, "PDM-001")
        nxt = next_ticket(tickets, {"PDM-001"})
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.ticket_id, "PDM-002")

    def test_build_message(self):
        md = """
### PDM-001 — One
Body1
"""
        ticket = parse_tickets(md)[0]
        self.assertTrue(build_message(ticket).startswith("please implement: ### PDM-001"))


class TestLibraryImport(unittest.TestCase):
    def test_import_codex_client(self):
        from codex_cli import CodexClient, Config, load_config
        self.assertTrue(callable(CodexClient))
        self.assertTrue(callable(load_config))

    def test_version(self):
        import codex_cli
        self.assertEqual(codex_cli.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
