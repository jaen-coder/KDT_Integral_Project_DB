from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from dateutil.relativedelta import relativedelta


FORMULA_PREFIXES = ("=", "+", "-", "@")


def now_seoul(tz_name: str = "Asia/Seoul") -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def parse_ymd(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def month_windows(start: date, end: date) -> list[tuple[str, date, date]]:
    """Inclusive month windows from start month through end month."""
    windows: list[tuple[str, date, date]] = []
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cursor <= last:
        month_start = cursor
        next_month = cursor + relativedelta(months=1)
        month_end = next_month - relativedelta(days=1)
        if month_start < start:
            month_start = start
        if month_end > end:
            month_end = end
        key = f"{cursor.year:04d}-{cursor.month:02d}"
        windows.append((key, month_start, month_end))
        cursor = next_month
    return windows


def in_half_open_month(published: datetime, month_start: date, next_month_start: date, tz: ZoneInfo) -> bool:
    start_dt = datetime(month_start.year, month_start.month, month_start.day, 0, 0, 0, tzinfo=tz)
    end_dt = datetime(next_month_start.year, next_month_start.month, next_month_start.day, 0, 0, 0, tzinfo=tz)
    return start_dt <= published < end_dt


def next_month_first(d: date) -> date:
    return (date(d.year, d.month, 1) + relativedelta(months=1))


def normalize_blog_url(url: str) -> tuple[str | None, str | None, str | None]:
    """Return (post_id, canonical_url, raw_normalized) from blog URL variants."""
    if not url:
        return None, None, None
    url = url.strip()
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().replace("m.blog.naver.com", "blog.naver.com")
    path = parsed.path or ""
    qs = parse_qs(parsed.query)

    blog_id = None
    log_no = None

    m = re.search(r"/PostView\.naver", path, re.I)
    if m or "PostView.naver" in path:
        blog_id = (qs.get("blogId") or [None])[0]
        log_no = (qs.get("logNo") or [None])[0]
    else:
        m2 = re.match(r"^/([^/]+)/(\d+)/?$", path)
        if m2:
            blog_id, log_no = m2.group(1), m2.group(2)
        else:
            m3 = re.match(r"^/([^/]+)/?$", path)
            if m3 and (qs.get("logNo") or [None])[0]:
                blog_id = m3.group(1)
                log_no = qs.get("logNo")[0]

    if not blog_id or not log_no:
        return None, None, None
    if blog_id.lower() in {"postview.naver", "postlist.naver", "myblog.naver"}:
        return None, None, None

    post_id = f"{blog_id}_{log_no}"
    canonical = f"https://blog.naver.com/{blog_id}/{log_no}"
    return post_id, canonical, urlunparse(("https", "blog.naver.com", f"/{blog_id}/{log_no}", "", "", ""))


def author_key_for(blog_id: str, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:{blog_id}".encode("utf-8")).hexdigest()[:16]
    return f"author_{digest}"


def commenter_key_for(raw: str, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:c:{raw}".encode("utf-8")).hexdigest()[:16]
    return f"commenter_{digest}"


def parse_naver_datetime(text: str | None, tz: ZoneInfo) -> tuple[datetime | None, str]:
    if not text:
        return None, "missing"
    cleaned = re.sub(r"\s+", " ", text.strip())
    patterns = [
        ("%Y. %m. %d. %H:%M", True),
        ("%Y. %m. %d.", False),
        ("%Y.%m.%d. %H:%M", True),
        ("%Y.%m.%d.", False),
        ("%Y-%m-%d %H:%M:%S", True),
        ("%Y-%m-%dT%H:%M:%S%z", True),
        ("%Y-%m-%d", False),
    ]
    for fmt, has_time in patterns:
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt, "parsed_with_time" if has_time else "parsed_date_only"
        except ValueError:
            continue
    m = re.search(r"(20\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})", cleaned)
    if m:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=tz)
        return dt, "parsed_date_only"
    return None, "unparsed"


def mask_pii(text: str | None) -> str | None:
    if text is None:
        return None
    out = text
    out = re.sub(r"\b01[016789]-?\d{3,4}-?\d{4}\b", "[PHONE]", out)
    out = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", out)
    out = re.sub(r"\b\d{3}-\d{2}-\d{5}\b", "[ID]", out)
    return out


def excel_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    s = str(value)
    if s.startswith(FORMULA_PREFIXES):
        return "'" + s
    return s


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {k: excel_safe(row.get(k)) for k in fieldnames}
            writer.writerow(safe)


def atomic_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def request_with_retries(
    session: requests.Session,
    url: str,
    *,
    max_retries: int,
    backoff: list[float],
    timeout: float,
    headers: dict[str, str] | None = None,
) -> tuple[requests.Response | None, str | None]:
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = session.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After") or (backoff[min(attempt, len(backoff) - 1)]))
                time.sleep(wait)
                last_err = "http_429"
                continue
            if resp.status_code >= 500:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
                last_err = f"http_{resp.status_code}"
                continue
            return resp, None
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(backoff[min(attempt, len(backoff) - 1)])
    return None, last_err
