"""Discord message formatting helpers.

Two responsibilities:
1. Convert markdown tables in the LLM's reply to monospace code blocks (Discord
   doesn't render markdown tables — they show up as raw `| col | col |` text).
2. Split long replies on paragraph / line / word boundaries to stay under
   Discord's 2000-char limit, keeping fenced code blocks balanced across chunks.
"""

from __future__ import annotations

import re

MAX_LEN = 2000

_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
# Separator like "|---|---|" or "| :--- | ---: |" — only dashes, colons, spaces, pipes.
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _split_table_row(line: str) -> list[str]:
    """Parse a `| a | b | c |` row into `['a','b','c']`."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _clean_cell(s: str) -> str:
    """Strip inline markdown (bold/italic/code) so monospace alignment is honest."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    return s


def _render_table(header: list[str], rows: list[list[str]]) -> str:
    """Fixed-width monospace table inside a Discord code fence."""
    cols = max(len(header), max((len(r) for r in rows), default=0))
    header = [_clean_cell(c) for c in header] + [""] * (cols - len(header))
    body = [
        [_clean_cell(c) for c in r] + [""] * (cols - len(r))
        for r in rows
    ]
    widths = [len(header[c]) for c in range(cols)]
    for r in body:
        for c in range(cols):
            if len(r[c]) > widths[c]:
                widths[c] = len(r[c])

    def fmt(cells: list[str]) -> str:
        return "  ".join(cells[c].ljust(widths[c]) for c in range(cols)).rstrip()

    sep = "  ".join("-" * widths[c] for c in range(cols))
    lines = [fmt(header), sep, *[fmt(r) for r in body]]
    return "```\n" + "\n".join(lines) + "\n```"


def markdown_tables_to_code_blocks(text: str) -> str:
    """Find markdown tables (header + |---| separator + rows) and rewrite them.

    A leading line of `|...|` followed by a separator line counts as a table.
    Anything that doesn't match (e.g. a stray `|`-bearing line in prose) is
    left untouched.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if (
            i + 1 < len(lines)
            and _TABLE_LINE_RE.match(lines[i])
            and _TABLE_SEP_RE.match(lines[i + 1])
        ):
            header = _split_table_row(lines[i])
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and _TABLE_LINE_RE.match(lines[i]):
                # Skip stray separator lines mid-table (some LLMs emit them).
                if _TABLE_SEP_RE.match(lines[i]):
                    i += 1
                    continue
                rows.append(_split_table_row(lines[i]))
                i += 1
            out.append(_render_table(header, rows))
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _balance_code_fences(chunks: list[str]) -> list[str]:
    """Ensure each chunk's ``` fences are balanced.

    If a chunk has an odd number of ``` markers, append a closing ``` to it and
    prepend an opening ``` to the next chunk so the code block keeps rendering
    across the message boundary.
    """
    out: list[str] = []
    carry = ""
    for chunk in chunks:
        body = (carry + chunk) if carry else chunk
        fences = body.count("```")
        if fences % 2 == 1:
            out.append(body.rstrip() + "\n```")
            carry = "```\n"
        else:
            out.append(body)
            carry = ""
    return out


def split_for_discord(text: str, max_len: int = MAX_LEN) -> list[str]:
    """Convert markdown tables, then chunk on safe boundaries, then re-balance
    fenced code blocks so each chunk renders correctly on its own.
    """
    if not text:
        return []
    text = markdown_tables_to_code_blocks(text)
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        # Prefer paragraph break, then line, then word.
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return _balance_code_fences(chunks)


__all__ = [
    "MAX_LEN",
    "markdown_tables_to_code_blocks",
    "split_for_discord",
]
