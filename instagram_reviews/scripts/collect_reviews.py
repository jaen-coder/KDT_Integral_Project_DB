#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram review collector — Google Play + App Store (KR), newest first.

Re-run:
  python scripts/collect_reviews.py
  python scripts/collect_reviews.py --platform play
  python scripts/collect_reviews.py --platform appstore
  python scripts/collect_reviews.py --resume

Outputs (UTF-8 BOM CSV):
  data/instagram_google_play.csv
  data/instagram_app_store.csv
  data/instagram_reviews_all.csv
  data/collection_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CKPT = ROOT / "checkpoints"
SERVICE = "Instagram"
PLAY_PKG = "com.instagram.android"
APP_ID = "389801252"
TARGET_PER_PLATFORM = 500
REQUEST_GAP_SEC = 1.2
MAX_RETRIES = 3

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


def ms_to_iso(ms: int | float | None) -> str:
    if ms is None:
        return ""
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OSError, OverflowError, ValueError):
        return ""


def ensure_dirs() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CKPT.mkdir(parents=True, exist_ok=True)


def http_request(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 45,
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, method=method)
    default = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    for k, v in {**default, **(headers or {})}.items():
        req.add_header(k, v)
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.getcode(), resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            if e.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(REQUEST_GAP_SEC * attempt * 2)
                last_err = e
                continue
            return e.code, body
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_GAP_SEC * attempt * 2)
                continue
            raise
    raise RuntimeError(f"request failed: {last_err}")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def has_text(body: str, title: str = "") -> bool:
    return bool((body or "").strip() or (title or "").strip())


# ---------------------------------------------------------------------------
# Google Play (batchexecute UsvDTd, sort=2 newest)
# ---------------------------------------------------------------------------

def play_build_body(token: str | None, count: int = 150, sort: int = 2) -> str:
    tok = f'\\"{token}\\"' if token else "null"
    inner = f'[null,null,[2,{sort},[{count},null,{tok}],null,[]],[\\"{PLAY_PKG}\\",7]]'
    freq = f'[[["UsvDTd","{inner}",null,"generic"]]]'
    return "f.req=" + urllib.parse.quote(freq)


def play_parse(raw: str) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Return (reviews, next_token, error)."""
    if "captcha" in raw.lower() or "unusual traffic" in raw.lower():
        return [], None, "CAPTCHA_OR_BLOCK"
    try:
        envelope = json.loads(raw[raw.index("[") :])
        inner = envelope[0][2]
        if not inner:
            return [], None, None
        data = json.loads(inner)
    except Exception as e:  # noqa: BLE001
        return [], None, f"PARSE_ERROR:{e}"

    items = data[0] if data and data[0] else []
    next_token = None
    try:
        next_token = data[1][1] if data[1] else None
    except Exception:  # noqa: BLE001
        next_token = None

    reviews: list[dict[str, Any]] = []
    collected = now_iso()
    for r in items:
        try:
            review_id = r[0]
            rating = r[2]
            body = r[4] or ""
            created_ms = r[5][0] * 1000 if r[5] else None
            helpful = r[6] if len(r) > 6 else ""
            reply = ""
            if len(r) > 7 and r[7]:
                reply = r[7][1] if len(r[7]) > 1 else ""
            app_version = r[10] if len(r) > 10 and r[10] else ""
            if not has_text(body):
                continue
            reviews.append(
                {
                    "service_name": SERVICE,
                    "platform": "Google Play Store",
                    "review_id": review_id,
                    "created_at": ms_to_iso(created_ms),
                    "updated_at": "",
                    "rating": rating,
                    "title": "",
                    "body": body,
                    "app_version": app_version or "",
                    "helpful_count": helpful if helpful is not None else "",
                    "source_url": (
                        f"https://play.google.com/store/apps/details?"
                        f"id={PLAY_PKG}&hl=ko&gl=KR&reviewId={review_id}"
                    ),
                    "collected_at": collected,
                    "sort_date_field": "created_at",
                    "developer_reply": reply or "",
                    "_created_ms": created_ms or 0,
                }
            )
        except Exception:  # noqa: BLE001
            continue
    return reviews, next_token, None


def collect_play(resume: bool = True) -> dict[str, Any]:
    ckpt_path = CKPT / "play_checkpoint.json"
    state = load_json(
        ckpt_path,
        {
            "reviews": {},
            "token": None,
            "pages": 0,
            "duplicates_skipped": 0,
            "status": "in_progress",
            "errors": [],
            "sort": "newest (UsvDTd sort=2)",
            "country": "KR",
            "language": "ko",
            "source": "https://play.google.com/store/apps/details?id=com.instagram.android",
        },
    )
    by_id: dict[str, dict] = state.get("reviews", {})
    token = state.get("token") if resume else None
    if not resume:
        by_id = {}
        token = None
        state["duplicates_skipped"] = 0
        state["errors"] = []
        state["pages"] = 0

    url = "https://play.google.com/_/PlayStoreUi/data/batchexecute?hl=ko&gl=KR"
    while len(by_id) < TARGET_PER_PLATFORM:
        body = play_build_body(token, count=150, sort=2).encode("utf-8")
        code, raw = http_request(
            url,
            method="POST",
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Origin": "https://play.google.com",
                "Referer": f"https://play.google.com/store/apps/details?id={PLAY_PKG}&hl=ko&gl=KR",
            },
        )
        if code != 200:
            err = f"HTTP_{code}"
            state["errors"].append({"at": now_iso(), "error": err, "snippet": raw[:300]})
            if code in (403, 429) or "captcha" in raw.lower():
                state["status"] = "blocked"
                state["block_reason"] = err
                break
            if len(state["errors"]) >= 5:
                state["status"] = "error"
                break
            time.sleep(REQUEST_GAP_SEC * 2)
            continue

        batch, next_token, parse_err = play_parse(raw)
        if parse_err == "CAPTCHA_OR_BLOCK":
            state["status"] = "blocked"
            state["block_reason"] = parse_err
            state["errors"].append({"at": now_iso(), "error": parse_err})
            break
        if parse_err:
            state["errors"].append({"at": now_iso(), "error": parse_err, "snippet": raw[:300]})
            break
        if not batch:
            state["status"] = "exhausted"
            break

        for row in batch:
            rid = row["review_id"]
            if rid in by_id:
                state["duplicates_skipped"] = state.get("duplicates_skipped", 0) + 1
                continue
            by_id[rid] = row
            if len(by_id) >= TARGET_PER_PLATFORM:
                break

        state["pages"] = state.get("pages", 0) + 1
        state["reviews"] = by_id
        state["token"] = next_token
        state["last_saved_at"] = now_iso()
        state["unique_count"] = len(by_id)
        save_json(ckpt_path, state)
        # intermediate CSV
        rows = sorted(by_id.values(), key=lambda x: x.get("_created_ms", 0), reverse=True)
        write_csv(DATA / "instagram_google_play.csv", rows[:TARGET_PER_PLATFORM])
        print(f"[Play] pages={state['pages']} unique={len(by_id)} next_token={'yes' if next_token else 'no'}")

        if not next_token:
            state["status"] = "exhausted"
            break
        token = next_token
        time.sleep(REQUEST_GAP_SEC)

    rows = sorted(by_id.values(), key=lambda x: x.get("_created_ms", 0), reverse=True)[
        :TARGET_PER_PLATFORM
    ]
    # drop helper
    for r in rows:
        r.pop("_created_ms", None)
    write_csv(DATA / "instagram_google_play.csv", rows)
    state["reviews"] = {r["review_id"]: {**r, "_created_ms": 0} for r in rows}
    # restore ms for date range from created_at
    state["unique_count"] = len(rows)
    state["status"] = state.get("status") if state.get("status") in ("blocked", "error", "exhausted") else "complete"
    if len(rows) >= TARGET_PER_PLATFORM:
        state["status"] = "complete"
    state["finished_at"] = now_iso()
    save_json(ckpt_path, {**state, "reviews": {r["review_id"]: r for r in rows}})
    return {"rows": rows, "meta": state}


# ---------------------------------------------------------------------------
# App Store (Apple Media API / amp-api, sort=mostRecent)
# ---------------------------------------------------------------------------

def normalize_iso(created: str) -> tuple[str, int]:
    if not created:
        return "", 0
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return (
            dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            int(dt.timestamp() * 1000),
        )
    except ValueError:
        return created, 0


def appstore_rows_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize either amp-api shape or Alexandria/apps.apple.com/api shape."""
    collected = now_iso()
    reviews: list[dict[str, Any]] = []
    for item in items:
        # Alexandria flat shape
        if "body" in item and "id" in item and "attributes" not in item:
            body = item.get("body") or ""
            title = item.get("title") or ""
            if not has_text(body, title):
                continue
            created_iso, created_ms = normalize_iso(item.get("date") or "")
            reviews.append(
                {
                    "service_name": SERVICE,
                    "platform": "App Store",
                    "review_id": str(item.get("id") or ""),
                    "created_at": created_iso,
                    "updated_at": "",
                    "rating": item.get("rating", ""),
                    "title": title,
                    "body": body,
                    "app_version": item.get("version") or "",
                    "helpful_count": item.get("voteSum", item.get("helpful_count", "")),
                    "source_url": (
                        f"https://apps.apple.com/kr/app/instagram/id{APP_ID}"
                        f"?see-all=reviews&sort=recent"
                    ),
                    "collected_at": collected,
                    "sort_date_field": "created_at",
                    "developer_reply": "",
                    "_created_ms": created_ms,
                    "_is_edited": bool(item.get("is_edited")),
                }
            )
            continue

        attrs = item.get("attributes") or item
        body = attrs.get("review") or attrs.get("body") or ""
        title = attrs.get("title") or ""
        if not has_text(body, title):
            continue
        review_id = str(item.get("id") or attrs.get("id") or "")
        created_iso, created_ms = normalize_iso(
            attrs.get("date") or attrs.get("createdDate") or ""
        )
        reviews.append(
            {
                "service_name": SERVICE,
                "platform": "App Store",
                "review_id": review_id,
                "created_at": created_iso,
                "updated_at": "",
                "rating": attrs.get("rating", ""),
                "title": title,
                "body": body,
                "app_version": attrs.get("version") or attrs.get("userVersion") or "",
                "helpful_count": (
                    attrs.get("voteSum")
                    if attrs.get("voteSum") is not None
                    else attrs.get("voteCount", "")
                ),
                "source_url": (
                    f"https://apps.apple.com/kr/app/instagram/id{APP_ID}"
                    f"?see-all=reviews&sort=recent"
                ),
                "collected_at": collected,
                "sort_date_field": "created_at",
                "developer_reply": "",
                "_created_ms": created_ms,
            }
        )
    return reviews


def appstore_parse_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    data = payload.get("data") or payload.get("reviews") or []
    reviews = appstore_rows_from_items(data)
    next_offset = payload.get("next_offset")
    if next_offset is None:
        next_url = payload.get("next") or (payload.get("links") or {}).get("next") or ""
        if isinstance(next_url, str) and next_url:
            m = re.search(r"[?&]offset=(\d+)", next_url)
            if m:
                next_offset = int(m.group(1))
    return reviews, next_offset


def collect_appstore(resume: bool = True) -> dict[str, Any]:
    ckpt_path = CKPT / "appstore_checkpoint.json"
    state = load_json(
        ckpt_path,
        {
            "reviews": {},
            "offset": 0,
            "pages": 0,
            "duplicates_skipped": 0,
            "status": "in_progress",
            "errors": [],
            "sort": "most_recent / sort=recent",
            "country": "kr",
            "locale": "ko-KR",
            "source": f"https://apps.apple.com/kr/app/instagram/id{APP_ID}",
            "rss_note": (
                "iTunes RSS returned empty entries at collection time; "
                "using apps.apple.com/api catalog reviews endpoint"
            ),
        },
    )
    by_id: dict[str, dict] = state.get("reviews", {})
    offset = int(state.get("offset") or 0) if resume else 0
    if not resume:
        by_id = {}
        offset = 0
        state["duplicates_skipped"] = 0
        state["errors"] = []
        state["pages"] = 0

    while len(by_id) < TARGET_PER_PLATFORM:
        qs = urllib.parse.urlencode(
            {
                "platform": "web",
                "l": "ko-KR",
                "offset": offset,
                "limit": 10,
                "sort": "recent",
            }
        )
        # Confirmed via Firecrawl Alexandria apps-apple-com provider
        url = f"https://apps.apple.com/api/apps/v1/catalog/kr/apps/{APP_ID}/reviews?{qs}"
        headers = {
            "Origin": "https://apps.apple.com",
            "Referer": f"https://apps.apple.com/kr/app/instagram/id{APP_ID}",
            "Accept": "application/json",
        }
        code, raw = http_request(url, headers=headers)
        if code != 200:
            err = f"HTTP_{code}"
            state["errors"].append({"at": now_iso(), "error": err, "snippet": raw[:400]})
            if code in (401, 403, 429):
                state["status"] = "blocked"
                state["block_reason"] = err
                break
            if len(state["errors"]) >= 5:
                state["status"] = "error"
                break
            time.sleep(REQUEST_GAP_SEC * 2)
            continue

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            state["errors"].append({"at": now_iso(), "error": f"JSON:{e}", "snippet": raw[:300]})
            state["status"] = "error"
            break

        batch, next_offset = appstore_parse_payload(payload)
        if not batch:
            state["status"] = "exhausted_or_empty"
            break

        for row in batch:
            rid = row["review_id"]
            if rid in by_id:
                state["duplicates_skipped"] = state.get("duplicates_skipped", 0) + 1
                continue
            by_id[rid] = row
            if len(by_id) >= TARGET_PER_PLATFORM:
                break

        state["pages"] = state.get("pages", 0) + 1
        state["reviews"] = by_id
        state["offset"] = next_offset if next_offset is not None else offset + len(batch)
        state["last_saved_at"] = now_iso()
        state["unique_count"] = len(by_id)
        save_json(ckpt_path, state)
        rows = sorted(by_id.values(), key=lambda x: x.get("_created_ms", 0), reverse=True)
        write_csv(DATA / "instagram_app_store.csv", rows[:TARGET_PER_PLATFORM])
        print(
            f"[AppStore] pages={state['pages']} unique={len(by_id)} offset={state['offset']}"
        )

        if next_offset is None:
            if len(batch) == 0:
                state["status"] = "exhausted"
                break
            offset = offset + len(batch)
        else:
            if next_offset == offset:
                state["status"] = "exhausted"
                break
            offset = next_offset
        time.sleep(REQUEST_GAP_SEC)

    rows = sorted(by_id.values(), key=lambda x: x.get("_created_ms", 0), reverse=True)[
        :TARGET_PER_PLATFORM
    ]
    for r in rows:
        r.pop("_created_ms", None)
        r.pop("_is_edited", None)
    write_csv(DATA / "instagram_app_store.csv", rows)
    if len(rows) >= TARGET_PER_PLATFORM:
        state["status"] = "complete"
    elif state.get("status") not in ("blocked", "error", "exhausted", "exhausted_or_empty"):
        state["status"] = "partial"
    state["unique_count"] = len(rows)
    state["finished_at"] = now_iso()
    save_json(ckpt_path, {**state, "reviews": {r["review_id"]: r for r in rows}})
    return {"rows": rows, "meta": state}


def date_range(rows: list[dict[str, Any]]) -> dict[str, str]:
    dates = [r.get("created_at") for r in rows if r.get("created_at")]
    if not dates:
        return {"min": "", "max": ""}
    return {"min": min(dates), "max": max(dates)}


def merge_and_summarize(play: dict[str, Any], app: dict[str, Any]) -> None:
    all_rows = play["rows"] + app["rows"]
    write_csv(DATA / "instagram_reviews_all.csv", all_rows)
    summary = {
        "service": SERVICE,
        "collected_at": now_iso(),
        "target_per_platform": TARGET_PER_PLATFORM,
        "target_total": TARGET_PER_PLATFORM * 2,
        "platforms": {
            "Google Play Store": {
                "saved_unique": len(play["rows"]),
                "duplicates_skipped": play["meta"].get("duplicates_skipped", 0),
                "date_range_created_at": date_range(play["rows"]),
                "sort": play["meta"].get("sort"),
                "sort_date_field": "created_at",
                "country_language": {
                    "country": play["meta"].get("country"),
                    "language": play["meta"].get("language"),
                },
                "source_url": play["meta"].get("source"),
                "status": play["meta"].get("status"),
                "limitations": play["meta"].get("errors", [])[:5],
                "block_reason": play["meta"].get("block_reason"),
                "updated_at_available": False,
                "notes": "Play Store provides review timestamp used as created_at; updated_at not separately exposed in public RPC.",
            },
            "App Store": {
                "saved_unique": len(app["rows"]),
                "duplicates_skipped": app["meta"].get("duplicates_skipped", 0),
                "date_range_created_at": date_range(app["rows"]),
                "sort": app["meta"].get("sort"),
                "sort_date_field": "created_at",
                "country_language": {
                    "country": app["meta"].get("country"),
                    "locale": app["meta"].get("locale"),
                },
                "source_url": app["meta"].get("source"),
                "status": app["meta"].get("status"),
                "limitations": app["meta"].get("errors", [])[:5],
                "block_reason": app["meta"].get("block_reason"),
                "updated_at_available": False,
                "notes": app["meta"].get("rss_note", ""),
            },
        },
        "total_saved_unique": len(all_rows),
        "filters": "No rating/sentiment/keyword filter; text-bearing reviews only",
        "pii_policy": "Author display names/avatars not stored",
        "developer_replies": "Stored in separate developer_reply column when present (Play)",
    }
    save_json(DATA / "collection_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["all", "play", "appstore"], default="all")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--fresh", action="store_true", help="Ignore checkpoints")
    args = parser.parse_args()
    resume = not args.fresh
    ensure_dirs()

    play_result = {"rows": [], "meta": {}}
    app_result = {"rows": [], "meta": {}}

    if args.platform in ("all", "play"):
        print("=== Collecting Google Play ===")
        play_result = collect_play(resume=resume)
    else:
        # load existing for merge
        ckpt = load_json(CKPT / "play_checkpoint.json", {})
        play_result = {
            "rows": list((ckpt.get("reviews") or {}).values()),
            "meta": ckpt,
        }

    if args.platform in ("all", "appstore"):
        print("=== Collecting App Store ===")
        app_result = collect_appstore(resume=resume)
    else:
        ckpt = load_json(CKPT / "appstore_checkpoint.json", {})
        app_result = {
            "rows": list((ckpt.get("reviews") or {}).values()),
            "meta": ckpt,
        }

    merge_and_summarize(play_result, app_result)


if __name__ == "__main__":
    main()
