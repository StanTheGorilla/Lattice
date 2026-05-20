"""Research paper persistence — Markdown files in data/research/.

Papers are saved with YAML-ish frontmatter so they're human-readable and
can be indexed without a full YAML parser.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _research_dir() -> Path:
    from lattice.config import DATA_DIR, settings

    d_str = settings.research_dir
    d = Path(d_str)
    if not d.is_absolute():
        d = DATA_DIR.parent / d_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(text: str, max_len: int = 50) -> str:
    clean = re.sub(r"[^\w\s-]", "", text.lower())
    clean = re.sub(r"[\s_-]+", "_", clean).strip("_")
    return clean[:max_len]


def save_paper(
    title: str,
    topic: str,
    content: str,
    sources: list[str] | None = None,
) -> str:
    """Persist a research paper. Returns the filename."""
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{_slug(title)}.md"
    path = _research_dir() / filename

    source_lines = "\n".join(f"  - {s}" for s in (sources or []))
    frontmatter = (
        f"---\n"
        f"title: {title}\n"
        f"topic: {topic}\n"
        f"date: {datetime.now(UTC).isoformat(timespec='seconds')}\n"
        f"sources:\n{source_lines}\n"
        f"---\n\n"
    )
    path.write_text(frontmatter + content, encoding="utf-8")
    return filename


def list_papers(topic: str | None = None) -> list[dict[str, Any]]:
    """Return metadata for all papers, newest-first. Filter by topic if given."""
    papers: list[dict[str, Any]] = []
    for p in sorted(_research_dir().glob("*.md"), reverse=True):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        meta = _parse_frontmatter(text)
        paper_topic = meta.get("topic", "")
        if topic and paper_topic.lower() != topic.lower():
            continue
        papers.append({
            "filename": p.name,
            "title": meta.get("title", p.stem),
            "topic": paper_topic,
            "date": meta.get("date", ""),
            "sources": meta.get("sources", []),
        })
    return papers


def read_paper(filename: str) -> str:
    """Read a paper by filename. Raises FileNotFoundError if absent."""
    safe = Path(filename).name  # prevent path traversal
    path = _research_dir() / safe
    if not path.exists():
        raise FileNotFoundError(f"Research paper not found: {safe!r}")
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if not text.startswith("---"):
        return meta
    try:
        end = text.index("---", 3)
    except ValueError:
        return meta
    fm = text[3:end]
    sources: list[str] = []
    in_sources = False
    for line in fm.splitlines():
        if line.strip() == "sources:":
            in_sources = True
            continue
        if in_sources:
            if line.startswith("  - "):
                sources.append(line[4:].strip())
                continue
            in_sources = False
        if ": " in line and not line.startswith("  "):
            k, v = line.split(": ", 1)
            meta[k.strip()] = v.strip()
    if sources:
        meta["sources"] = sources
    return meta


__all__ = ["list_papers", "read_paper", "save_paper"]
