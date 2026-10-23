"""Tests for the MkDocs link and anchor hooks."""

from __future__ import annotations

import unittest
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import mkdocs_hooks as hooks

try:
    from markdown import Markdown
except ImportError:  # pragma: no cover - the docs workflow installs Markdown
    Markdown = None

PAGE = SimpleNamespace(
    file=SimpleNamespace(src_path="docs/development/documentation-site.md")
)
FILES = [
    SimpleNamespace(src_path="docs/development/documentation-site.md"),
    SimpleNamespace(src_path="docs/README.md"),
    SimpleNamespace(src_path="docs/examples/README.md"),
]
CONFIG = {"mdx_configs": {"toc": {}}}


def render(markdown: str) -> str:
    return hooks.on_page_markdown(markdown, PAGE, CONFIG, FILES)


def render_for(page_path: str, markdown: str) -> str:
    page = SimpleNamespace(file=SimpleNamespace(src_path=page_path))
    return hooks.on_page_markdown(markdown, page, CONFIG, FILES)


class LinkHookTests(unittest.TestCase):
    def test_rewrites_inline_source_links(self):
        result = render("[stage](../../scripts/docs/stage.py)")
        self.assertIn(
            "https://github.com/redhat-et/secure-single-server/blob/main/"
            "scripts/docs/stage.py",
            result,
        )

    def test_rewrites_reference_definitions_and_preserves_angle_brackets(self):
        result = render(
            "[stage][stage]\n\n[stage]: <../../scripts/docs/stage.py>\n"
        )
        self.assertIn("[stage][stage]", result)
        self.assertIn(
            "[stage]: <https://github.com/redhat-et/secure-single-server/"
            "blob/main/scripts/docs/stage.py>",
            result,
        )

    def test_rewrites_angle_bracket_inline_links_with_titles(self):
        result = render("[stage](<../../scripts/docs/stage.py> 'Stage sources')")
        self.assertIn(
            "https://github.com/redhat-et/secure-single-server/blob/main/"
            "scripts/docs/stage.py",
            result,
        )
        self.assertIn("'Stage sources'", result)

    def test_rewrites_balanced_parentheses_and_url_significant_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "topic_(v2).md").write_text("topic", encoding="utf-8")
            (root / "hash#file.md").write_text("hash", encoding="utf-8")
            page = SimpleNamespace(file=SimpleNamespace(src_path="docs/page.md"))
            config = {"mdx_configs": {"toc": {}}}

            with patch.object(hooks, "REPO_ROOT", root):
                result = hooks.on_page_markdown(
                    "[guide](../topic_(v2).md)", page, config, []
                )
                self.assertIn(
                    "https://github.com/redhat-et/secure-single-server/blob/main/"
                    "topic_%28v2%29.md",
                    result,
                )

                result = hooks.on_page_markdown(
                    "[hash](../hash%23file.md)", page, config, []
                )
                self.assertIn(
                    "https://github.com/redhat-et/secure-single-server/blob/main/"
                    "hash%23file.md",
                    result,
                )

                result = hooks.on_page_markdown(
                    "[literal hash](<../hash#file.md>)", page, config, []
                )
                self.assertIn(
                    "https://github.com/redhat-et/secure-single-server/blob/main/"
                    "hash%23file.md",
                    result,
                )

    def test_preserves_query_strings_when_rewriting_source_links(self):
        result = render("[stage](../../scripts/docs/stage.py?raw=1#top)")
        self.assertIn(
            "https://github.com/redhat-et/secure-single-server/blob/main/"
            "scripts/docs/stage.py?raw=1#top",
            result,
        )

    def test_preserves_query_strings_in_angle_bracket_source_links(self):
        result = render("[stage](<../../scripts/docs/stage.py?raw=1#top>)")
        self.assertIn(
            "https://github.com/redhat-et/secure-single-server/blob/main/"
            "scripts/docs/stage.py?raw=1#top",
            result,
        )

    def test_does_not_rewrite_link_syntax_in_code(self):
        result = render(
            "`[missing](../missing.sh)`\n\n"
            "`[missing]: ../missing.sh`\n\n"
            "```text\n"
            "[missing](../missing.sh)\n"
            "[missing]: ../missing.sh\n"
            "```\n\n"
            "```\n[missing](../missing.sh)\n```\n\n"
            "[stage](../../scripts/docs/stage.py)"
        )
        self.assertIn("`[missing](../missing.sh)`", result)
        self.assertIn("`[missing]: ../missing.sh`", result)
        self.assertIn("[missing](../missing.sh)", result)
        self.assertIn("[missing]: ../missing.sh", result)
        self.assertIn(
            "https://github.com/redhat-et/secure-single-server/blob/main/"
            "scripts/docs/stage.py",
            result,
        )

    def test_rewrites_nested_component_links(self):
        openshell = render_for(
            "openshell/docs/policy-walkthrough.md",
            "[smoke](../../tests/openshell-praxis/smoke.sh)",
        )
        self.assertIn(
            "https://github.com/redhat-et/secure-single-server/blob/main/"
            "tests/openshell-praxis/smoke.sh",
            openshell,
        )

        bootc = render_for(
            "bootc/VALIDATION.md",
            "[pins](../scripts/common/lib.sh)",
        )
        self.assertIn(
            "https://github.com/redhat-et/secure-single-server/blob/main/"
            "scripts/common/lib.sh",
            bootc,
        )

    def test_rewrites_reference_definition_with_multiline_title(self):
        result = render(
            "[stage][stage]\n\n"
            "[stage]: ../../scripts/docs/stage.py\n"
            '    "Stage sources"\n'
        )
        self.assertIn(
            "[stage]: https://github.com/redhat-et/secure-single-server/"
            "blob/main/scripts/docs/stage.py",
            result,
        )
        self.assertIn('    "Stage sources"', result)

    def test_leaves_markdown_pages_and_directories_unchanged(self):
        result = render(
            "[map](../README.md)\n"
            "[examples](../examples/)\n"
            "[details]: #details\n"
            "[external](https://example.com)\n"
        )
        self.assertIn("[map](../README.md)", result)
        self.assertIn("[examples](../examples/)", result)
        self.assertIn("[details]: #details", result)
        self.assertIn("[external](https://example.com)", result)


class AnchorHookTests(unittest.TestCase):
    @unittest.skipIf(Markdown is None, "Markdown is not installed")
    def test_page_scoped_slugifier_is_used_by_markdown(self):
        config = {"mdx_configs": {"toc": {}}}
        hooks.on_config(config)
        source = hooks.on_page_markdown(
            "## Repeated heading\n\n## Repeated heading\n", PAGE, config, FILES
        )
        html = Markdown(
            extensions=["toc"], extension_configs=config["mdx_configs"]
        ).convert(source)
        self.assertIn('id="repeated-heading"', html)
        self.assertIn('id="repeated-heading-1"', html)

    def test_duplicate_headings_use_github_style_suffixes(self):
        hooks._SLUGIFIER_STATE.seen = set()
        slugify = hooks.github_slugify
        self.assertEqual(
            "quota-error-and-recovery",
            slugify("Quota error and recovery", "-"),
        )
        self.assertEqual(
            "quota-error-and-recovery-1",
            slugify("Quota error and recovery", "-"),
        )

    def test_preserves_accented_letters_like_github(self):
        # GitHub renders "## Café" with id="user-content-café".
        hooks._SLUGIFIER_STATE.seen = set()
        slugify = hooks.github_slugify
        self.assertEqual("café", slugify("Café", "-"))

    def test_unresolved_relative_links_fail(self):
        with self.assertRaises(ValueError):
            render("[missing](../does-not-exist.md)")

    def test_rejects_paths_outside_the_repository(self):
        with self.assertRaises(ValueError):
            render("[up](../../../../etc/passwd)")
        with self.assertRaises(ValueError):
            render("[encoded-up](%2e%2e/%2e%2e/%2e%2e/etc/passwd)")
        result = render("[absolute](%2Fetc%2Fpasswd)")
        self.assertIn("[absolute](%2Fetc%2Fpasswd)", result)

    def test_handles_underscores_punctuation_and_repeated_spaces(self):
        hooks._SLUGIFIER_STATE.seen = set()
        slugify = hooks.github_slugify
        self.assertEqual("foo_bar", slugify("foo_bar", "-"))
        self.assertEqual("whats-new", slugify("What's new?", "-"))
        # GitHub's slugger replaces each space with a hyphen rather than
        # collapsing runs, so repeated spaces become repeated hyphens.
        self.assertEqual("a--b", slugify("A  B", "-"))


if __name__ == "__main__":
    unittest.main()
