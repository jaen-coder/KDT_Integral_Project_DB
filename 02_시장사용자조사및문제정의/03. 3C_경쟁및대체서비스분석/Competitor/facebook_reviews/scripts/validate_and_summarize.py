#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

PLAY_ALEX_FIRST = "ab83b440-3835-4e21-b904-ba82de7bb96d"
APP_PW_FIRST = "14801317975"


def load(name: str):
    with (DATA / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def check(rows, label):
    ids = [r["review_id"] for r in rows]
    dates = [r["created_at"] for r in rows if r.get("created_at")]
    prefix_ok = (
        all(dates[i] >= dates[i + 1] for i in range(min(19, len(dates) - 1)))
        if len(dates) > 1
        else True
    )
    text_n = sum(
        1
        for r in rows
        if (r.get("body") or "").strip() or (r.get("title") or "").strip()
    )
    print(
        label,
        {
            "n": len(rows),
            "unique": len(set(ids)),
            "with_text": text_n,
            "min": min(dates) if dates else "",
            "max": max(dates) if dates else "",
            "newest_prefix": prefix_ok,
            "sample0": (
                (rows[0]["review_id"], rows[0]["created_at"], (rows[0].get("body") or "")[:30])
                if rows
                else None
            ),
        },
    )


def main():
    play = load("facebook_google_play.csv")
    app = load("facebook_app_store.csv")
    all_rows = load("facebook_reviews_all.csv")
    for name in [
        "facebook_google_play.csv",
        "facebook_app_store.csv",
        "facebook_reviews_all.csv",
    ]:
        raw = (DATA / name).read_bytes()[:3]
        print(name, "bom", raw == b"\xef\xbb\xbf", "bytes", (DATA / name).stat().st_size)
    check(play, "PLAY")
    check(app, "APP")
    print("ALL", len(all_rows))
    print("play_matches_alexandria_first", play and play[0]["review_id"] == PLAY_ALEX_FIRST)
    print("app_matches_playwright_first", app and app[0]["review_id"] == APP_PW_FIRST)

    summary = {
        "service": "Facebook",
        "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_per_platform": 500,
        "target_total": 1000,
        "platforms": {
            "Google Play Store": {
                "saved_unique": len(play),
                "duplicates_skipped": 0,
                "date_range_created_at": {
                    "min": min(r["created_at"] for r in play if r.get("created_at")),
                    "max": max(r["created_at"] for r in play if r.get("created_at")),
                },
                "sort": "newest (Play batchexecute UsvDTd sort=2; cross-checked Firecrawl Alexandria media/app_reviews sort=newest)",
                "sort_date_field": "created_at",
                "country_language": {"country": "KR", "language": "ko"},
                "source_url": "https://play.google.com/store/apps/details?id=com.facebook.katana&hl=ko",
                "status": "complete",
                "updated_at_available": False,
                "notes": "Public RPC exposes a single review timestamp mapped to created_at; separate updated_at not available. Author names/avatars not stored. Developer replies in developer_reply when present.",
            },
            "App Store": {
                "saved_unique": len(app),
                "duplicates_skipped": 0,
                "date_range_created_at": {
                    "min": min(r["created_at"] for r in app if r.get("created_at")),
                    "max": max(r["created_at"] for r in app if r.get("created_at")),
                },
                "sort": "most_recent (apps.apple.com catalog API sort=recent; verified via Playwright browser fetch)",
                "sort_date_field": "created_at",
                "country_language": {"country": "kr", "locale": "ko-KR"},
                "source_url": "https://apps.apple.com/kr/app/facebook/id284882215",
                "status": "complete",
                "updated_at_available": False,
                "limitations": [
                    "Firecrawl Alexandria apps/reviews timed out during this run; collected via Node fetch of apps.apple.com catalog API (same most_recent/sort=recent feed), with Playwright verification of sort=recent",
                    "is_edited exists in source but no separate updated_at timestamp; updated_at left blank",
                    "Author user_name not stored",
                ],
                "notes": "Most Helpful / rating sorts were not used.",
            },
        },
        "total_saved_unique": len(play) + len(app),
        "filters": "No rating/sentiment/keyword filter; text-bearing reviews only",
        "pii_policy": "Author display names/avatars not stored",
        "outputs": {
            "play": "data/facebook_google_play.csv",
            "appstore": "data/facebook_app_store.csv",
            "all": "data/facebook_reviews_all.csv",
        },
    }
    (DATA / "collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
