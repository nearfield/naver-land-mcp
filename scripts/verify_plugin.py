"""Verify a relocated Git-eligible plugin using its actual uv launch contract."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[1]


async def verify(root):
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads(
        (root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
    )
    assert manifest["name"] == marketplace["plugins"][0]["name"]
    entry = marketplace["plugins"][0]
    assert (root / entry["source"]["path"]).resolve() == root.resolve()
    assert (root / "uv.lock").is_file()
    config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["naver-land"]
    assert server["type"] == "stdio" and server["command"] == "uv"
    args = [arg.replace("${PLUGIN_ROOT}", str(root)) for arg in server["args"]]
    assert not any("${" in arg for arg in args)
    transport = StdioTransport(
        command=server["command"],
        args=args,
        # Dependencies are pre-cached by uv sync; verification cannot fetch them.
        env={**server.get("env", {}), "UV_OFFLINE": "1"},
        cwd=tempfile.gettempdir(),
        keep_alive=False,
    )
    async with Client(transport, timeout=55) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert len(names) == 11
        assert {"search_studio_spaces", "get_article_photos"} <= names
        fixture = json.loads(
            (root / "tests/fixtures/office_photos.json").read_text(encoding="utf-8")
        )
        response = await client.call_tool(
            "review_studio_articles", {"articles": [fixture]}
        )
        assert not response.is_error
        payload = json.loads(next(c.text for c in response.content if c.type == "text"))
        assert payload["liveLookupPerformed"] is False
        assert len(payload["matchingAdvertisements"]) == 1
        assert len(payload["matchingAdvertisements"][0]["photoUrls"]) == 7
    return {
        "status": "passed",
        "relocatedPlugin": True,
        "launchSource": "mcp.json",
        "toolsDiscovered": len(names),
        "naverApiRequests": 0,
        "dependencyDownloadsAllowedDuringSetup": True,
    }


def main():
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode().split("\0")
    with tempfile.TemporaryDirectory(prefix="naver plugin relocation ") as directory:
        root = Path(directory)
        for relative in set(tracked) - {""}:
            source = ROOT / relative
            if not source.is_file():
                continue
            assert not source.is_symlink()
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # Model a member's first install, then require offline protocol startup.
        subprocess.run(
            ["uv", "sync", "--project", str(root), "--frozen", "--python", sys.executable],
            check=True,
        )
        print(json.dumps(asyncio.run(verify(root)), ensure_ascii=False))


if __name__ == "__main__":
    main()
