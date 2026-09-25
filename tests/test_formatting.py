import unittest

from formatting import format_page, format_search_results, validate_wiki_path


class FormattingTests(unittest.TestCase):
    def test_empty_search_results_are_explicit(self):
        self.assertEqual(format_search_results([], True, 1000), "未找到相关知识。")

    def test_manual_search_includes_paths(self):
        text = format_search_results(
            [
                {
                    "title": "TCP congestion control",
                    "path": "wiki/tcp.md",
                    "snippet": "Congestion window controls sending rate.",
                }
            ],
            include_sources=True,
            max_chars=1000,
        )

        self.assertIn("TCP congestion control", text)
        self.assertIn("wiki/tcp.md", text)
        self.assertIn("Congestion window", text)

    def test_automatic_context_omits_paths(self):
        text = format_search_results(
            [
                {
                    "title": "TCP",
                    "path": "wiki/private-path.md",
                    "snippet": "Transmission Control Protocol.",
                }
            ],
            include_sources=False,
            max_chars=1000,
        )

        self.assertIn("TCP", text)
        self.assertNotIn("wiki/private-path.md", text)

    def test_search_results_respect_total_character_limit(self):
        text = format_search_results(
            [{"title": "A", "path": "wiki/a.md", "snippet": "x" * 100}],
            include_sources=True,
            max_chars=50,
        )

        self.assertLessEqual(len(text), 50)
        self.assertTrue(text.endswith("..."))

    def test_page_format_includes_path_and_truncates_content(self):
        text = format_page("wiki/tcp.md", "x" * 100, max_chars=40)

        self.assertLessEqual(len(text), 40)
        self.assertIn("wiki/tcp.md", text)
        self.assertTrue(text.endswith("..."))

    def test_validate_wiki_path_normalizes_leading_slash(self):
        self.assertEqual(validate_wiki_path("/wiki/tcp.md"), "wiki/tcp.md")

    def test_validate_wiki_path_rejects_non_wiki_path(self):
        for path in (
            "raw/source.txt",
            "../wiki/a.md",
            "wiki/../secret.md",
            "wiki/..\\secret.md",
            "wiki/a\\b.md",
            "wiki/",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_wiki_path(path)


if __name__ == "__main__":
    unittest.main()
