"""Export one workspace-compatible plugin; exclude local data and marketplaces."""

from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_ROOTS = {".agents", ".github"}
EXCLUDED_FILES = {"plugin.json", "mcp.json"}


def package(output):
    from publication import check_publication

    check_publication(ROOT)
    paths = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout.decode().split("\0")
    output.parent.mkdir(parents=True, exist_ok=True)
    included = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(set(paths) - {""}):
            parts = Path(relative).parts
            if parts[0] in EXCLUDED_ROOTS or relative in EXCLUDED_FILES:
                continue
            source = ROOT / relative
            if not source.is_file():
                continue
            assert not source.is_symlink() and ".." not in parts
            archive.write(source, "naver-land/" + relative)
            included.append(relative)
    assert ".codex-plugin/plugin.json" in included and ".mcp.json" in included
    assert "uv.lock" in included and "stdio_server.py" in included
    return len(included)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".verification/naver-land-plugin.zip")
    args = parser.parse_args()
    print(f"Workspace plugin packaged: {package(args.output)} files")
