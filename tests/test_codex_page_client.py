"""Tests for codex_page_client module (non-browser tests)."""

import unittest

from codex_page_client import CodexPageClient


class TestCodexPageClientInit(unittest.TestCase):
    def test_init_defaults(self):
        client = CodexPageClient(url="https://example.com/codex")
        self.assertEqual(client.url, "https://example.com/codex")
        self.assertTrue(client.headless)
        self.assertIsNone(client.page)
        self.assertIsNone(client._storage_state_path)

    def test_init_with_storage_state(self):
        client = CodexPageClient(
            url="https://example.com/codex",
            storage_state_path="/tmp/state.json",
        )
        self.assertEqual(client._storage_state_path, "/tmp/state.json")


if __name__ == "__main__":
    unittest.main()
