import tempfile
import unittest
from pathlib import Path

from ticket_implementation_runner import build_message, next_ticket, parse_tickets


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


if __name__ == "__main__":
    unittest.main()
