"""Catch accidental private data in files eligible for Git publication."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS = {
    "personal_absolute_path": re.compile(
        r"/Users/[A-Za-z][^/\s]+/|[A-Z]:\\Users\\[^\\\s]+\\"
    ),
    "jwt_literal": re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    ),
    "actual_fixture_listing_id": re.compile(r'"articleNo"\s*:\s*"(?!900000)\d{10}"'),
}


def text_issues(text: str) -> list[str]:
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


def check_publication(root: Path) -> dict:
    process = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    paths = sorted(set(process.stdout.decode("utf-8").split("\0")) - {""})
    problems = []
    for relative in paths:
        path = root / relative
        if path.suffix not in {".py", ".md", ".json", ".toml", ".txt", ".yml", ".yaml"}:
            continue
        if not path.is_file():
            continue
        for issue in text_issues(path.read_text(encoding="utf-8")):
            problems.append({"file": relative, "issue": issue})
    if problems:
        # Describe locations/categories only, never echo the private matching text.
        raise ValueError(f"Publication safety check failed: {problems}")
    return {
        "status": "passed",
        "filesScanned": len(paths),
        "scope": "Git-eligible source and documentation; not a complete secret scanner",
    }
