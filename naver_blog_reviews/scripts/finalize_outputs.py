#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild CSVs + collection_summary.json from checkpoints / existing CSVs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CKPT = ROOT / "checkpoints"

CSV_FIELDS = [
    "service_name",
    "platform",
    "review_id",
    "created_at",
    "updated_at",
    "rating",
    "title",
    "body",
    "app_version",
    "helpful_count",
    "source_url",
    "collected_at",
    "sort_date_field",
    "developer_reply",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_play() -> tuple[list[dict], dict]:
    ckpt_path = CKPT / "play_checkpoint.json"
    meta = {}
    rows: list[dict] = []
    if ckpt_path.exists():
        meta = json.loads(ckpt_path.read_text(encoding="utf-8"))
        rows = list((meta.get("reviews") or {}).values())
    if len(rows) < 500:
        csv_rows = load_csv(DATA / "naver_blog_google_play.csv")
        if len(csv_rows) > len(rows):
            rows = csv_rows
    rows = sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)[:500]
    return rows, meta


def load_appstore() -> tuple[list[dict], int]:
    # Prefer page dumps
    by_id: dict[str, dict] = {}
    raw_ids: list[str] = []
    pages = sorted((CKPT / "appstore_pages").glob("*.json"))
    collected = now_iso()
    for p in pages:
        data = json.loads(p.read_text(encoding="utf-8"))
        for r in data.get("reviews") or []:
            rid = str(r.get("id") or "")
            raw_ids.append(rid)
            body = (r.get("body") or "").strip()
            title = (r.get("title") or "").strip()
            if not rid or (not body and not title) or rid in by_id:
                continue
            created = r.get("date") or ""
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                created = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass
            by_id[rid] = {
                "service_name": "네이버 블로그",
                "platform": "App Store",
                "review_id": rid,
                "created_at": created,
                "updated_at": "",
                "rating": r.get("rating", ""),
                "title": title,
                "body": body,
                "app_version": r.get("version") or "",
                "helpful_count": r.get("voteSum", ""),
                "source_url": (
                    "https://apps.apple.com/kr/app/id328813873"
                    "?see-all=reviews&sort=recent"
                ),
                "collected_at": collected,
                "sort_date_field": "created_at",
                "developer_reply": "",
            }
    if not by_id:
        by_id = {r["review_id"]: r for r in load_csv(DATA / "naver_blog_app_store.csv")}
        raw_ids = list(by_id.keys())
    c = Counter(raw_ids)
    dups = sum(v - 1 for v in c.values() if v > 1)
    rows = sorted(by_id.values(), key=lambda r: r.get("created_at") or "", reverse=True)[
        :500
    ]
    return rows, dups


def date_range(rows: list[dict]) -> dict[str, str]:
    dates = [r["created_at"] for r in rows if r.get("created_at")]
    if not dates:
        return {"min": "", "max": ""}
    return {"min": min(dates), "max": max(dates)}


def main() -> None:
    play, play_meta = load_play()
    app, app_dups = load_appstore()
    write_csv(DATA / "naver_blog_google_play.csv", play)
    write_csv(DATA / "naver_blog_app_store.csv", app)
    write_csv(DATA / "naver_blog_reviews_all.csv", play + app)

    summary = {
        "service": "네이버 블로그",
        "collected_at": now_iso(),
        "target_per_platform": 500,
        "target_total": 1000,
        "platforms": {
            "Google Play Store": {
                "saved_unique": len(play),
                "duplicates_skipped": play_meta.get("duplicates_skipped", 0),
                "date_range_created_at": date_range(play),
                "sort": "newest (UsvDTd sort=2 / Alexandria sort=newest)",
                "sort_date_field": "created_at",
                "country_language": {"country": "KR", "language": "ko"},
                "source_url": "https://play.google.com/store/apps/details?id=com.nhn.android.blog",
                "status": "complete" if len(play) >= 500 else "partial",
                "updated_at_available": False,
                "notes": play_meta.get(
                    "notes",
                    "Single public timestamp mapped to created_at; author PII omitted.",
                ),
            },
            "App Store": {
                "saved_unique": len(app),
                "duplicates_skipped": app_dups,
                "date_range_created_at": date_range(app),
                "sort": "most_recent (Alexandria apps/reviews)",
                "sort_date_field": "created_at",
                "country_language": {"country": "kr", "locale": "ko-KR"},
                "source_url": "https://apps.apple.com/kr/app/id328813873",
                "status": "complete" if len(app) >= 500 else "partial",
                "updated_at_available": False,
                "limitations": [
                    "iTunes RSS returned 0 entries",
                    "Direct apps.apple.com/api / Playwright fetch: HTTP 429",
                    "Collected via Firecrawl Alexandria apps-apple-com/apps/reviews",
                ],
            },
        },
        "total_saved_unique": len(play) + len(app),
        "filters": "No rating/sentiment/keyword filter; text-bearing reviews only",
        "pii_policy": "Author display names/avatars not stored",
        "outputs": {
            "play": "data/naver_blog_google_play.csv",
            "appstore": "data/naver_blog_app_store.csv",
            "all": "data/naver_blog_reviews_all.csv",
        },
    }
    (DATA / "collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # appstore checkpoint mirror
    (CKPT / "appstore_checkpoint.json").write_text(
        json.dumps(
            {
                "unique_count": len(app),
                "duplicates_skipped": app_dups,
                "status": summary["platforms"]["App Store"]["status"],
                "sort": "most_recent",
                "country": "kr",
                "locale": "ko-KR",
                "finished_at": now_iso(),
                "reviews": {r["review_id"]: r for r in app},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
