import tempfile
import unittest
from pathlib import Path

from codex_page_client import (
    get_diff_file_content,
    list_diff_files,
    list_envs_from_html,
    list_tasks_from_html,
    parse_diff_files_from_html,
)


class TestCodexPageClientParsing(unittest.TestCase):
    def test_parse_diff_files_from_html_extracts_blocks(self):
        html = """
        <html><body>
        <pre>
        diff --git a/foo.py b/foo.py
        index 111..222 100644
        --- a/foo.py
        +++ b/foo.py
        @@ -1 +1 @@
        -old
        +new
        diff --git a/bar.md b/bar.md
        index 111..222 100644
        --- a/bar.md
        +++ b/bar.md
        @@ -1 +1 @@
        -a
        +b
        </pre>
        </body></html>
        """
        files = parse_diff_files_from_html(html)
        self.assertEqual([f.path for f in files], ["foo.py", "bar.md"])
        self.assertIn("diff --git a/foo.py b/foo.py", files[0].content)

    def test_list_diff_files_fallback_to_mentions(self):
        with tempfile.TemporaryDirectory() as td:
            page = Path(td) / "page.html"
            page.write_text("<html><body>Updated app/main.py and docs/readme.md</body></html>", encoding="utf-8")
            self.assertEqual(list_diff_files(page), ["app/main.py", "docs/readme.md"])

    def test_get_diff_file_content_falls_back_to_local_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            page = root / "page.html"
            target = root / "notes.md"
            page.write_text("<html><body>No diff blocks here</body></html>", encoding="utf-8")
            target.write_text("hello", encoding="utf-8")
            self.assertEqual(get_diff_file_content(page, "notes.md"), "hello")

    def test_list_tasks_from_html_statuses(self):
        with tempfile.TemporaryDirectory() as td:
            page = Path(td) / "page2.html"
            page.write_text(
                """
                <html><body>
                  <div>Task A Open PR <a href=\"/codex/tasks/abc123\">link</a></div>
                  <div>Task B merged <a href=\"https://chatgpt.com/codex/tasks/def456\">link</a></div>
                  <div>Task C <a href=\"/codex/tasks/ghi789\">link</a></div>
                </body></html>
                """,
                encoding="utf-8",
            )
            tasks = list_tasks_from_html(page)
            self.assertEqual([t.status for t in tasks], ["open", "merged", "normal"])
            self.assertEqual([t.link for t in tasks], ["/codex/tasks/abc123", "https://chatgpt.com/codex/tasks/def456", "/codex/tasks/ghi789"])

    def test_list_envs_from_html(self):
        with tempfile.TemporaryDirectory() as td:
            page = Path(td) / "page2.html"
            page.write_text("<html><body>Environment: default Env staging</body></html>", encoding="utf-8")
            envs = list_envs_from_html(page)
            self.assertIn("default", [e.lower() for e in envs])
            self.assertIn("staging", [e.lower() for e in envs])


if __name__ == "__main__":
    unittest.main()
