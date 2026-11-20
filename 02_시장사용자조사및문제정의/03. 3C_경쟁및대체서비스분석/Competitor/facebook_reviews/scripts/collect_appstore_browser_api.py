#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect App Store reviews via apps.apple.com catalog API (sort=recent)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "checkpoints" / "appstore_pages"
APP_ID = "284882215"
TARGET = 500
GAP = 1.0
MAX_RETRIES = 4


def fetch(offset: int) -> tuple[int, str]:
    qs = urllib.parse.urlencode(
        {
            "platform": "web",
            "l": "ko-KR",
            "offset": offset,
            "limit": 10,
            "sort": "recent",
        }
    )
    url = f"https://apps.apple.com/api/apps/v1/catalog/kr/apps/{APP_ID}/reviews?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Origin": "https://apps.apple.com",
            "Referer": f"https://apps.apple.com/kr/app/facebook/id{APP_ID}",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body


def normalize(payload: dict, offset: int) -> dict:
    reviews = []
    for item in payload.get("data") or []:
        attrs = item.get("attributes") or {}
        body = attrs.get("review") or ""
        title = attrs.get("title") or ""
        if not (body.strip() or title.strip()):
            continue
        reviews.append(
            {
                "id": str(item.get("id") or ""),
                "date": attrs.get("date") or "",
                "rating": attrs.get("rating", ""),
                "title": title,
                "body": body,
                "is_edited": bool(attrs.get("isEdited")),
                "version": attrs.get("version") or attrs.get("userVersion") or "",
                "voteSum": attrs.get("voteSum", ""),
            }
        )
    next_offset = None
    nxt = payload.get("next") or ""
    if "offset=" in str(nxt):
        try:
            next_offset = int(str(nxt).split("offset=")[1].split("&")[0])
        except ValueError:
            next_offset = offset + len(reviews) if reviews else None
    elif reviews:
        next_offset = offset + 10
    return {
        "app_id": APP_ID,
        "offset": offset,
        "count": len(reviews),
        "next_offset": next_offset,
        "sort": "most_recent",
        "country": "kr",
        "reviews": reviews,
        "source_url": f"https://apps.apple.com/kr/app/facebook/id{APP_ID}?see-all=reviews&sort=recent",
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    unique = 0
    offset = 0
    pages = 0
    # resume: count existing
    for p in OUT.glob("offset_*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            unique += len(d.get("reviews") or [])
        except Exception:
            pass
    # find next missing offset
    existing = {int(p.stem.split("_")[1]) for p in OUT.glob("offset_*.json")}
    offset = 0
    while unique < TARGET and offset <= 10000:
        path = OUT / f"offset_{offset:04d}.json"
        if offset in existing and path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            n = len(d.get("reviews") or [])
            if n:
                print(f"skip existing offset={offset} n={n}")
                offset = d.get("next_offset") or (offset + 10)
                continue
        ok = False
        for attempt in range(1, MAX_RETRIES + 1):
            code, raw = fetch(offset)
            if code == 429 or code >= 500:
                print(f"retry offset={offset} code={code} attempt={attempt}")
                time.sleep(GAP * attempt * 2)
                continue
            if code != 200:
                print(f"blocked/error offset={offset} code={code} body={raw[:200]}")
                path.write_text(
                    json.dumps({"offset": offset, "error": code, "body": raw[:500]}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return
            payload = json.loads(raw)
            page = normalize(payload, offset)
            path.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
            pages += 1
            unique = sum(
                len(json.loads(p.read_text(encoding="utf-8")).get("reviews") or [])
                for p in OUT.glob("offset_*.json")
                if "error" not in json.loads(p.read_text(encoding="utf-8"))
            )
            # cheaper unique recount via set
            ids = set()
            for p in OUT.glob("offset_*.json"):
                d = json.loads(p.read_text(encoding="utf-8"))
                for r in d.get("reviews") or []:
                    ids.add(str(r.get("id")))
            unique = len(ids)
            print(f"saved offset={offset} page_n={page['count']} unique={unique}")
            if not page["reviews"]:
                print("empty page; stopping")
                return
            offset = page.get("next_offset") or (offset + 10)
            ok = True
            break
        if not ok:
            print(f"failed offset={offset} after retries")
            return
        time.sleep(GAP)
    print(f"done pages={pages} unique~={unique}")


if __name__ == "__main__":
    main()
