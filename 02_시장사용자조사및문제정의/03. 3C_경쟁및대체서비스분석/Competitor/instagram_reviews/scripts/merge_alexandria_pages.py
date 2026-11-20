#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge Alexandria / checkpoint page JSON dumps into platform CSVs."""

from __future__ import annotations

import csv
import json
import sys
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


def ms_to_iso(ms) -> str:
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except Exception:
        return ""


def normalize_iso(created: str) -> str:
    if not created:
        return ""
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return created


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def ingest_play_page(path: Path, by_id: dict) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    # unwrap alexandria envelope if needed
    if "data" in data and "alexandria" in data.get("data", {}):
        data = data["data"]["alexandria"][0]["data"]
    elif "reviews" not in data and isinstance(data.get("data"), dict):
        data = data["data"]
    added = 0
    collected = now_iso()
    for r in data.get("reviews") or []:
        body = (r.get("text") or r.get("body") or "").strip()
        if not body:
            continue
        rid = r.get("review_id") or r.get("id")
        if not rid or rid in by_id:
            continue
        by_id[rid] = {
            "service_name": "Instagram",
            "platform": "Google Play Store",
            "review_id": rid,
            "created_at": ms_to_iso(r.get("created_at_ms")),
            "updated_at": "",
            "rating": r.get("stars", r.get("rating", "")),
            "title": "",
            "body": body,
            "app_version": r.get("app_version") or "",
            "helpful_count": r.get("helpful_count", ""),
            "source_url": r.get("url")
            or f"https://play.google.com/store/apps/details?id=com.instagram.android&reviewId={rid}",
            "collected_at": collected,
            "sort_date_field": "created_at",
            "developer_reply": r.get("reply_text") or "",
            "_sort": r.get("created_at_ms") or 0,
        }
        added += 1
    return added


def ingest_app_page(path: Path, by_id: dict) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "data" in data and "alexandria" in data.get("data", {}):
        data = data["data"]["alexandria"][0]["data"]
    elif "reviews" not in data and isinstance(data.get("data"), dict):
        data = data["data"]
    added = 0
    collected = now_iso()
    for r in data.get("reviews") or []:
        body = (r.get("body") or "").strip()
        title = (r.get("title") or "").strip()
        if not body and not title:
            continue
        rid = str(r.get("id") or r.get("review_id") or "")
        if not rid or rid in by_id:
            continue
        created = normalize_iso(r.get("date") or "")
        by_id[rid] = {
            "service_name": "Instagram",
            "platform": "App Store",
            "review_id": rid,
            "created_at": created,
            "updated_at": "",
            "rating": r.get("rating", ""),
            "title": title,
            "body": body,
            "app_version": r.get("version") or "",
            "helpful_count": r.get("voteSum", ""),
            "source_url": "https://apps.apple.com/kr/app/instagram/id389801252?see-all=reviews&sort=recent",
            "collected_at": collected,
            "sort_date_field": "created_at",
            "developer_reply": "",
            "_sort": created,
        }
        added += 1
    return added


def main() -> None:
    play_dir = CKPT / "play_pages"
    app_dir = CKPT / "appstore_pages"
    play: dict = {}
    app: dict = {}
    if play_dir.exists():
        for p in sorted(play_dir.glob("*.json")):
            ingest_play_page(p, play)
    if app_dir.exists():
        for p in sorted(app_dir.glob("*.json")):
            ingest_app_page(p, app)

    play_rows = sorted(play.values(), key=lambda x: x.get("_sort", 0), reverse=True)[:500]
    app_rows = sorted(app.values(), key=lambda x: x.get("_sort", ""), reverse=True)[:500]
    for r in play_rows + app_rows:
        r.pop("_sort", None)

    # Do not wipe an existing Play CSV if no play_pages were provided
    existing_play = DATA / "instagram_google_play.csv"
    if play_rows:
        write_csv(existing_play, play_rows)
    elif existing_play.exists():
        import csv as _csv

        with existing_play.open(encoding="utf-8-sig") as f:
            play_rows = list(_csv.DictReader(f))

    write_csv(DATA / "instagram_app_store.csv", app_rows)
    write_csv(DATA / "instagram_reviews_all.csv", play_rows + app_rows)
    print(f"play={len(play_rows)} appstore={len(app_rows)} total={len(play_rows)+len(app_rows)}")


if __name__ == "__main__":
    main()
