#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Save pagesData JSON (from Playwright) into appstore_pages/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "checkpoints" / "appstore_pages"


def main() -> None:
    src = Path(sys.argv[1])
    data = json.loads(src.read_text(encoding="utf-8"))
    pages = data.get("pagesData") or data.get("data") or data
    if isinstance(pages, dict) and "pagesData" in pages:
        pages = pages["pagesData"]
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for page in pages:
        off = int(page.get("offset", 0))
        path = OUT / f"offset_{off:04d}.json"
        path.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1
        print(off, page.get("count"))
    print("saved", n, "total", len(list(OUT.glob('*.json'))))


if __name__ == "__main__":
    main()
