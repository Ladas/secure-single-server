"""MkDocs hooks that adapt repository Markdown for the published site.

The site is built from ``.docs-build/``, a copy of the repository's Markdown
with repository-relative paths. Links to Markdown pages work unchanged. Links
to scripts, configuration, workflows, and other source files cannot be served
by GitHub Pages, so those are mapped to the corresponding GitHub URL.
"""

from __future__ import annotations

import posixpath
import re
import threading
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

REPO_URL = "https://github.com/redhat-et/secure-single-server"
DEFAULT_BRANCH = "main"
REPO_ROOT = Path(__file__).resolve().parents[2]

# Markdown inline links, excluding images. Angle-bracket destinations may
# contain spaces; unbracketed destinations may contain balanced parentheses.
LINK_RE = re.compile(
    r"(?<!!)\[(?P<label>[^\]]+)\]"
    r"\(\s*(?P<target><[^>\n]*>|(?:[^()\s]|\([^()\n]*\))+)"
    r"(?P<title>\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
# Reference definitions such as ``[guide]: ../path/to/file``. Rewriting the
# definition covers reference-style and shortcut reference links.
REFERENCE_DEF_RE = re.compile(
    r"^(?P<prefix>[ \t]{0,3}\[[^\]\n]+\]:[ \t]*)"
    r"(?P<target><[^>\n]+>|\S+)"
    r"(?P<title>[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$",
    re.MULTILINE,
)
EXTERNAL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
FENCE_OPEN_RE = re.compile(r" {0,3}(?P<marker>`{3,}|~{3,})")
FENCE_CLOSE_RE = re.compile(
    r"(?m)^ {0,3}(?P<marker>`{3,}|~{3,})[ \t]*$"
)
CODE_SPAN_RE = re.compile(r"`+")


def _is_external(target: str) -> bool:
    return (
        not target
        or target.startswith(("#", "/", "//"))
        or EXTERNAL_RE.match(target) is not None
    )


def _is_document(path: str, documents: set[str]) -> bool:
    # MkDocs serves a directory README as the directory URL, so leave those
    # links unchanged.
    return (
        path in documents
        or f"{path}/README.md" in documents
        or f"{path}/index.md" in documents
    )


def _github_url(path: str, repo_root: Path) -> str | None:
    target = repo_root / path
    if target.is_dir():
        return f"{REPO_URL}/tree/{DEFAULT_BRANCH}/{quote(path, safe='/')}"
    if target.is_file():
        return f"{REPO_URL}/blob/{DEFAULT_BRANCH}/{quote(path, safe='/')}"
    return None


def _rewrite_target(
    target: str, page_path: Path, documents: set[str]
) -> str | None:
    """Return a GitHub URL for a source-file target, or ``None`` to leave it."""
    if _is_external(target):
        return None

    angle_bracket = target.startswith("<") and target.endswith(">")
    destination = target[1:-1] if angle_bracket else target
    if angle_bracket:
        query_separator = destination.find("?")
        if query_separator >= 0:
            path = unquote(destination[:query_separator])
            query, _, anchor = destination[query_separator + 1 :].partition("#")
        else:
            path = unquote(destination)
            query = ""
            anchor = ""
    else:
        parsed = urlsplit(destination)
        path = unquote(parsed.path)
        query = parsed.query
        anchor = parsed.fragment
    if not path or path.startswith("/"):
        return None

    resolved = posixpath.normpath(
        posixpath.join(posixpath.dirname(page_path.as_posix()), path)
    )
    if resolved == ".." or resolved.startswith("../"):
        raise ValueError(f"repository-relative link escapes the root: {target}")
    if _is_document(resolved, documents):
        return None

    repo_root = REPO_ROOT.resolve()
    resolved_path = (repo_root / resolved).resolve()
    try:
        resolved_path.relative_to(repo_root)
    except ValueError:
        raise ValueError(f"repository-relative link escapes the root: {target}")

    url = _github_url(resolved, REPO_ROOT)
    if url is None:
        raise ValueError(f"unresolved repository-relative link: {target}")

    query_suffix = f"?{query}" if query else ""
    fragment = f"#{anchor}" if anchor else ""
    return f"{url}{query_suffix}{fragment}"


def _code_region_bounds(markdown: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    index = 0

    while index < len(markdown):
        if index == 0 or markdown[index - 1] == "\n":
            opening = FENCE_OPEN_RE.match(markdown, index)
            if opening:
                marker = opening.group("marker")
                fence_end = len(markdown)
                opening_line_end = markdown.find("\n", opening.end())
                search_start = (
                    opening_line_end + 1 if opening_line_end != -1 else len(markdown)
                )
                for closing in FENCE_CLOSE_RE.finditer(markdown, search_start):
                    closing_marker = closing.group("marker")
                    if (
                        closing_marker[0] == marker[0]
                        and len(closing_marker) >= len(marker)
                    ):
                        fence_end = closing.end()
                        break
                regions.append((index, fence_end))
                index = fence_end
                continue

        if markdown[index] == "`":
            delimiter_length = len(CODE_SPAN_RE.match(markdown, index).group())
            delimiter = "`" * delimiter_length
            closing = markdown.find(delimiter, index + delimiter_length)
            if closing != -1:
                code_end = closing + delimiter_length
                regions.append((index, code_end))
                index = code_end
                continue
            index += delimiter_length
            continue

        index += 1

    return regions


def _target_in_code(match: re.Match[str], regions: list[tuple[int, int]]) -> bool:
    start = match.start("target")
    end = match.end("target")
    return any(
        start < region_end and end > region_start
        for region_start, region_end in regions
    )


def on_page_markdown(markdown, page, config, files):
    page_path = Path(page.file.src_path)
    documents = {Path(item.src_path).as_posix() for item in files}
    _SLUGIFIER_STATE.seen = set()
    code_regions = _code_region_bounds(markdown)

    def replace(match: re.Match[str]) -> str:
        if _target_in_code(match, code_regions):
            return match.group(0)
        url = _rewrite_target(match.group("target"), page_path, documents)
        if url is None:
            return match.group(0)
        title = match.group("title") or ""
        return f"[{match.group('label')}]({url}{title})"

    def replace_reference(match: re.Match[str]) -> str:
        if _target_in_code(match, code_regions):
            return match.group(0)
        raw_target = match.group("target")
        bracketed = raw_target.startswith("<") and raw_target.endswith(">")
        url = _rewrite_target(raw_target, page_path, documents)
        if url is None:
            return match.group(0)
        rendered = f"<{url}>" if bracketed else url
        title = match.group("title") or ""
        return f"{match.group('prefix')}{rendered}{title}"

    markdown = REFERENCE_DEF_RE.sub(replace_reference, markdown)
    return LINK_RE.sub(replace, markdown)


_SLUGIFIER_STATE = threading.local()


def github_slugify(value: str, separator: str) -> str:
    """Return the GitHub-compatible anchor for the current page.

    Python-Markdown otherwise makes duplicates unique with ``_1`` while GitHub
    uses ``-1``. Thread-local state keeps duplicate anchors unique per page.
    """
    seen: set[str] = getattr(_SLUGIFIER_STATE, "seen", set())
    value = value.lower()
    value = re.sub(r"[^\w\s-]", "", value)
    base = re.sub(r"\s", separator, value)
    slug = base
    suffix = 1
    while slug in seen:
        slug = f"{base}-{suffix}"
        suffix += 1
    seen.add(slug)
    _SLUGIFIER_STATE.seen = seen
    return slug


def on_config(config):
    """Use GitHub-compatible anchors so links work on both GitHub and the site."""
    toc = config.setdefault("mdx_configs", {}).setdefault("toc", {})
    toc["slugify"] = github_slugify
    return config
