from __future__ import annotations

import json
import re
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .utils import mask_pii, parse_naver_datetime, request_with_retries


LOGIN_MARKERS = ["로그인", "nid.naver.com", "로그인이 필요합니다"]
ERROR_MARKERS = ["존재하지 않는 게시물", "비공개", "삭제되었", "접근할 수 없"]


def fetch_reaction_count(
    session: requests.Session,
    blog_id: str,
    log_no: str,
    *,
    max_retries: int,
    backoff: list[float],
    timeout: float,
    user_agent: str,
) -> int | None:
    q = f"BLOG[{blog_id}_{log_no}]"
    url = (
        "https://apis.naver.com/blogserver/like/v1/search/contents"
        f"?suppress_response_codes=true&pool=blogid&q={requests.utils.quote(q)}"
        "&isDuplication=false"
    )
    resp, err = request_with_retries(
        session,
        url,
        max_retries=max_retries,
        backoff=backoff,
        timeout=timeout,
        headers={"User-Agent": user_agent, "Referer": f"https://blog.naver.com/{blog_id}/{log_no}"},
    )
    if err or resp is None or resp.status_code != 200:
        return None
    text = resp.text
    # may be JSONP
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        contents = data.get("contents") or []
        if not contents:
            return None
        reactions = contents[0].get("reactions") or []
        total = 0
        found = False
        for r in reactions:
            if "count" in r:
                total += int(r["count"])
                found = True
        return total if found else None
    except Exception:
        return None


def extract_post(
    session: requests.Session,
    blog_id: str,
    log_no: str,
    *,
    tz: ZoneInfo,
    max_retries: int,
    backoff: list[float],
    timeout: float,
    user_agent: str,
) -> dict[str, Any]:
    url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}&redirect=Dlog"
    resp, err = request_with_retries(
        session,
        url,
        max_retries=max_retries,
        backoff=backoff,
        timeout=timeout,
        headers={"User-Agent": user_agent, "Referer": "https://section.blog.naver.com/"},
    )
    if err or resp is None:
        return {
            "extraction_status": "실패",
            "error_reason": err or "no_response",
            "collection_method": "http_postview",
        }
    if resp.status_code == 403:
        return {
            "extraction_status": "접근 제한",
            "error_reason": "http_403",
            "collection_method": "http_postview",
        }
    if resp.status_code != 200:
        return {
            "extraction_status": "실패",
            "error_reason": f"http_{resp.status_code}",
            "collection_method": "http_postview",
        }

    html = resp.text
    text_probe = re.sub(r"<[^>]+>", " ", html)
    if any(m in text_probe for m in ERROR_MARKERS):
        return {
            "extraction_status": "실패",
            "error_reason": "private_or_missing",
            "collection_method": "http_postview",
        }
    if "nid.naver.com" in resp.url and any(m in text_probe for m in LOGIN_MARKERS):
        return {
            "extraction_status": "접근 제한",
            "error_reason": "login_wall",
            "collection_method": "http_postview",
        }

    soup = BeautifulSoup(html, "lxml")

    # Remove known non-body regions before body extraction
    for sel in [
        "#post_footer",
        ".post_footer",
        ".area_comment",
        ".area_sympathy",
        "#blog-side",
        ".blog2_series",
        ".wrap_buddy",
        "#relatedPost",
        ".list_related",
        "script",
        "style",
        "noscript",
    ]:
        for el in soup.select(sel):
            el.decompose()

    title_el = soup.select_one(".se-title-text") or soup.select_one("#title_1") or soup.select_one(".pcol1")
    title = title_el.get_text(" ", strip=True) if title_el else None

    date_el = soup.select_one(".se_publishDate") or soup.select_one(".blog2_series_date") or soup.select_one(".date")
    date_text = date_el.get_text(" ", strip=True) if date_el else None
    published_at, date_status = parse_naver_datetime(date_text, tz)

    body_el = soup.select_one(".se-main-container") or soup.select_one("#postViewArea") or soup.select_one(".post-view")
    body_text = None
    if body_el:
        # keep sponsorship notices inside body
        body_text = body_el.get_text("\n", strip=True)
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()

    hashtags = []
    for a in soup.select("a.tag, #tagList a, a[href*='PostListByTagName']"):
        t = a.get_text(" ", strip=True)
        if t.startswith("#"):
            hashtags.append(t)
        elif t:
            hashtags.append("#" + t)
    # dedupe preserve order
    seen = set()
    hashtags = [h for h in hashtags if not (h in seen or seen.add(h))]

    displayed_comment_count = None
    m_c = re.search(r"댓글\s*([0-9]+)", soup.get_text(" ", strip=True))
    if m_c:
        displayed_comment_count = int(m_c.group(1))

    reaction_count = fetch_reaction_count(
        session,
        blog_id,
        log_no,
        max_retries=max_retries,
        backoff=backoff,
        timeout=timeout,
        user_agent=user_agent,
    )

    if not body_text:
        return {
            "extraction_status": "실패",
            "error_reason": "empty_body",
            "title": title,
            "published_at": published_at.isoformat() if published_at else None,
            "date_status": date_status,
            "date_text_raw": date_text,
            "collection_method": "http_postview",
            "reaction_count": reaction_count,
            "displayed_comment_count": displayed_comment_count,
        }

    # Distinguish truncated garbage vs short legitimate posts
    if len(body_text) < 15 and "로그인" in body_text:
        return {
            "extraction_status": "실패",
            "error_reason": "login_fragment",
            "collection_method": "http_postview",
        }

    return {
        "extraction_status": "성공",
        "error_reason": None,
        "title": title,
        "published_at": published_at.isoformat() if published_at else None,
        "published_month": published_at.strftime("%Y-%m") if published_at else None,
        "date_status": date_status,
        "date_text_raw": date_text,
        "body_text": mask_pii(body_text),
        "body_text_raw_len": len(body_text),
        "hashtags": json.dumps(hashtags, ensure_ascii=False) if hashtags else None,
        "reaction_count": reaction_count,
        "displayed_comment_count": displayed_comment_count,
        "collection_method": "http_postview",
        "author_blog_id": blog_id,
    }
