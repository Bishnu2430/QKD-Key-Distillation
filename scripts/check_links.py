"""Check every relative Markdown link and heading anchor in the repository.

Documentation that points at a moved or deleted file is worse than no
documentation, and this project's docs cross-reference heavily.

    uv run python scripts/check_links.py

Exits non-zero if anything is broken, so it can gate a commit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_TOP = {"vivado", ".venv", "tv", ".git"}


def slug(heading: str) -> str:
    """GitHub's anchor rule: lowercase, drop punctuation, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = [p for p in root.rglob("*.md") if not SKIP_TOP & set(p.relative_to(root).parts)]

    anchors: dict[Path, set[str]] = {}
    for path in files:
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        anchors[path.resolve()] = {
            slug(m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.*)$", text, re.M)
        }

    broken = 0
    for path in files:
        for match in re.finditer(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
            link = match.group(1)
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            rel, _, fragment = link.partition("#")
            target = (path.parent / rel).resolve() if rel else path.resolve()
            if not target.exists():
                print(f"MISSING FILE   {path.relative_to(root)} -> {link}")
                broken += 1
                continue
            if fragment and target.suffix == ".md" and fragment not in anchors.get(target, set()):
                print(f"MISSING ANCHOR {path.relative_to(root)} -> {link}")
                broken += 1

    print(f"{len(files)} files checked, {broken} broken link(s)")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
