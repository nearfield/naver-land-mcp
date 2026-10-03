"""Fail-closed offline and optional live acceptance gates. No denial retry loops."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPECTED_TOOLS = {
    "watch_complexes",
    "search_apartments",
    "get_complex_info",
    "get_complex_price_info",
    "list_districts",
    "resolve_district",
    "search_studio_spaces",
    "get_studio_article",
    "review_studio_articles",
    "get_article_detail",
    "get_article_photos",
}


class LiveBlocked(RuntimeError):
    pass


def source_digest():
    digest = hashlib.sha256()
    paths = (
        list(ROOT.glob("*.py"))
        + list((ROOT / "scripts").glob("*.py"))
        + list((ROOT / "tests").glob("*.py"))
        + list((ROOT / "tests/fixtures").glob("*.json"))
        + [ROOT / "pyproject.toml", ROOT / "requirements.txt"]
    )
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def command_gate(command):
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if completed.returncode:
        print((completed.stdout + completed.stderr)[-6000:], file=sys.stderr)
        raise RuntimeError(f"{command[2]} validation failed")
    return {"status": "passed", "output": completed.stdout.strip()[-4000:]}


async def call_json(client, name, arguments):
    response = await client.call_tool(name, arguments, raise_on_error=False)
    texts = [c.text for c in response.content if getattr(c, "type", None) == "text"]
    if response.is_error:
        message = " ".join(texts)
        if "접근 제한" in message or "CAPTCHA" in message:
            raise LiveBlocked("Naver access restriction; no further requests attempted")
        # Avoid persisting arbitrary upstream error content or user arguments.
        raise RuntimeError(f"MCP tool {name} returned an error")
    payload = json.loads(texts[0])
    if not isinstance(payload, dict) or payload.get("error"):
        raise AssertionError(f"MCP tool {name} returned an invalid success payload")
    return payload


def assert_photo_contract(payload, *, require_photos=False):
    if payload["photoStatus"] == "available":
        assert payload["photoUrls"], "available without photo URLs"
        assert all(
            urlsplit(url).scheme == "https" and urlsplit(url).hostname
            for url in payload["photoUrls"]
        )
    elif payload["photoStatus"] == "not_published":
        assert payload["upstreamPhotoCount"] == 0 and not payload["photoUrls"]
    else:
        raise AssertionError("Photo contract is unknown or unusable")
    if require_photos:
        assert payload["photoStatus"] == "available", (
            "No public photos; supply --photo-article with a photo listing"
        )


async def protocol_gates(report, args):
    transport = StdioTransport(
        command=sys.executable,
        args=[str(ROOT / "stdio_server.py")],
        cwd=str(ROOT),
        env={"PYTHONUNBUFFERED": "1"},
        keep_alive=False,
    )
    async with Client(transport, timeout=55) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == EXPECTED_TOOLS
        schemas = {t.name: t.input_schema for t in tools}
        assert "detail_limit" in schemas["search_studio_spaces"]["properties"]
        report["checks"]["stdio_discovery"] = {
            "status": "passed",
            "toolCount": len(tools),
        }
        raw = json.loads(
            (ROOT / "tests/fixtures/office_photos.json").read_text(encoding="utf-8")
        )
        offline = await call_json(client, "review_studio_articles", {"articles": [raw]})
        assert offline["liveLookupPerformed"] is False
        assert len(offline["matchingAdvertisements"]) == 1
        assert len(offline["matchingAdvertisements"][0]["photoUrls"]) == 7
        report["checks"]["stdio_offline_review"] = {
            "status": "passed",
            "fixture": "sanitized",
            "networkRequests": 0,
        }
        if not args.live:
            return
        studio = await call_json(
            client,
            "search_studio_spaces",
            {"district": args.district, "limit": 10, "max_pages": 1, "detail_limit": 3},
        )
        assert studio["collected"] > 0, (
            "A live success requires actual listings, not an empty response"
        )
        matches = studio["matchingAdvertisements"]
        assert matches, (
            "No matching advertisements in this limited sample; change explicit scope, not assertions"
        )
        for item in matches:
            assert item["propertyType"] in {"SMS", "SG"} and item["tradeType"] == "B2"
            assert item["monthlyRentManwon"] < 150 and item["floorNumber"] >= 2
            assert not item["unknownFilterFields"] and not item["exclusionReasons"]
        report["checks"]["live_office_store_search"] = {
            "status": "passed",
            "collected": studio["collected"],
            "matchingCount": len(matches),
            "detailLookups": studio["detailLookups"],
            "truncated": studio["truncated"],
        }
        aid = matches[0]["articleNo"]
        detail = await call_json(client, "get_article_detail", {"article_no": aid})
        assert detail["articleNo"] == aid and detail["propertyType"] in {"SMS", "SG"}
        assert (
            detail["monthlyRentManwon"] is not None
            and detail["advertisedExclusiveM2"] is not None
        )
        assert detail["areaPrecision"] == "detail_advertised"
        report["checks"]["live_office_store_detail"] = {
            "status": "passed",
            "identityMatched": True,
        }
        photo_aid = args.photo_article or next(
            (x["articleNo"] for x in matches if x["photoStatus"] == "available"), aid
        )
        photos = await call_json(
            client, "get_article_photos", {"article_no": photo_aid}
        )
        assert_photo_contract(photos, require_photos=True)
        report["checks"]["live_public_photos"] = {
            "status": "passed",
            "propertyType": photos["propertyType"],
            "photoCount": len(photos["photoUrls"]),
        }
        apartments = await call_json(
            client,
            "search_apartments",
            {"district": args.district, "trade_type": "B2", "limit": 1},
        )
        assert apartments["collected"] > 0 and apartments["items"]
        apt = apartments["items"][0]
        assert apt["tradeType"] == "B2" and apt["rentPrice"] is not None
        report["checks"]["live_apartment_regression"] = {
            "status": "passed",
            "collected": apartments["collected"],
        }
        apt_photos = await call_json(
            client, "get_article_photos", {"article_no": apt["articleNo"]}
        )
        assert apt_photos["propertyType"] == "APT"
        assert_photo_contract(apt_photos)
        report["checks"]["live_apartment_photo_response"] = {
            "status": "passed",
            "photoStatus": apt_photos["photoStatus"],
            "photoCount": len(apt_photos["photoUrls"]),
        }


def main():
    from publication import check_publication

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicit opt-in to small live Naver queries",
    )
    parser.add_argument("--district", default="개포동")
    parser.add_argument(
        "--photo-article",
        help="Optional public listing ID with photos; not saved in the report",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".verification/latest.json"
    )
    args = parser.parse_args()
    report = {
        "testedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "live" if args.live else "offline",
        "sourceDigest": source_digest(),
        "checks": {},
        "status": "failed",
        "liveVerified": False,
        "credentialsPersisted": False,
        "rawListingsPersisted": False,
    }
    try:
        report["checks"]["static_analysis"] = command_gate(
            [sys.executable, "-m", "ruff", "check", "."]
        )
        report["checks"]["publication_safety"] = check_publication(ROOT)
        report["checks"]["offline_regressions"] = command_gate(
            [
                sys.executable,
                "-m",
                "pytest",
                "--cov=articles",
                "--cov=studio",
                "--cov-branch",
                "--cov-report=term",
                "--cov-fail-under=85",
                "-q",
            ]
        )
        asyncio.run(protocol_gates(report, args))
        report["status"] = "passed"
        report["liveVerified"] = args.live
    except LiveBlocked as exc:
        report["status"] = "blocked"
        report["failure"] = {"type": "access_restriction", "message": str(exc)}
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report["mode"],
                "checksPassed": len(report["checks"]),
                "liveVerified": report["liveVerified"],
                "failure": report.get("failure"),
            },
            ensure_ascii=False,
        )
    )
    return (
        0 if report["status"] == "passed" else 2 if report["status"] == "blocked" else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
