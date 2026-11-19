#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Save a Firecrawl Alexandria agent-tools JSON dump into appstore_pages/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "checkpoints" / "appstore_pages"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: save_alexandria_batch.py <agent-tools-json>")
    src = Path(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(src.read_text(encoding="utf-8"))
    items = data.get("data", {}).get("alexandria") or []
    ok = 0
    for i, item in enumerate(items):
        d = item.get("data") or {}
        reviews = d.get("reviews") or []
        if not reviews:
            print("fail", i, list(item.keys()))
            continue
        off = d.get("offset", i * 10)
        path = OUT / f"offset_{int(off):04d}.json"
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(off, d.get("count"), d.get("next_offset"))
        ok += 1
    print("saved", ok, "total_files", len(list(OUT.glob("*.json"))))


if __name__ == "__main__":
    main()
