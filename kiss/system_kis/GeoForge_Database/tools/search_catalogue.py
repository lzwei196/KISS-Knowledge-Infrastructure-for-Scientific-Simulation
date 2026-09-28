#!/usr/bin/env python3
"""Query metadata and estimate clips through Desktop; never approve jobs."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Search GeoForge Database")
    result.add_argument("keywords", nargs="?", default="")
    result.add_argument("--query", dest="query", default="")
    result.add_argument("--bbox", default="", help="min_lon,min_lat,max_lon,max_lat")
    result.add_argument("--start", default="", help="YYYY-MM-DD")
    result.add_argument("--end", default="", help="YYYY-MM-DD")
    result.add_argument("--variable", default="")
    result.add_argument("--describe", dest="describe_dataset_id", default="", help="Read the actual source schema before selecting subset variables")
    result.add_argument("--resolve", dest="resolve_dataset_id", default="")
    result.add_argument("--subset", default="", help="Estimate a server-side subset; approval is required in Project status")
    result.add_argument("--time-step", default="", choices=["", "daily", "3hr"])
    result.add_argument("--category", default="")
    result.add_argument("--delivery", default="", choices=["", "served", "manual"])
    result.add_argument("--offset", type=int, default=0)
    result.add_argument("--limit", type=int, default=25)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    endpoint = os.environ.get("GEOFORGE_AGENT_DATABASE_URL", "").strip()
    capability = os.environ.get("GEOFORGE_AGENT_DATABASE_TOKEN", "").strip()
    if not endpoint or not capability:
        print(
            "GeoForge Database is not available in this agent session. "
            "Start the search from GeoForge Desktop.",
            file=sys.stderr,
        )
        return 3
    params = urllib.parse.urlencode({
        "q": args.query or args.keywords,
        "bbox": args.bbox, "start": args.start, "end": args.end,
        "variable": args.variable, "category": args.category, "delivery": args.delivery,
        "describe_dataset_id": args.describe_dataset_id,
        "resolve_dataset_id": args.resolve_dataset_id, "time_step": args.time_step,
        "subset_dataset_id": args.subset, "cwd": os.getcwd() if args.subset else "",
        "offset": max(0, args.offset),
        "limit": max(1, min(args.limit, 100)),
    })
    request = urllib.request.Request(
        endpoint + ("&" if "?" in endpoint else "?") + params,
        headers={
            "X-GeoForge-Agent-Token": capability,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(
                error.read().decode("utf-8", "replace")
            ).get("message")
        except Exception:
            detail = None
        print(
            "GeoForge Database search failed: "
            + (detail or f"HTTP {error.code}"),
            file=sys.stderr,
        )
        return 3
    except Exception as error:
        print(
            f"GeoForge Database search failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
