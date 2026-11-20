from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .utils import commenter_key_for, mask_pii, parse_naver_datetime, request_with_retries


def _within_period(dt: datetime | None, start: date, end: date) -> str:
    if dt is None:
        return "unknown"
    d = dt.astimezone().date() if dt.tzinfo else dt.date()
    return "true" if start <= d <= end else "false"


def fetch_comments(
    session: requests.Session,
    blog_id: str,
    log_no: str,
    *,
    author_nickname_hints: list[str] | None,
    salt: str,
    tz: ZoneInfo,
    research_start: date,
    research_end: date,
    max_comments: int,
    max_retries: int,
    backoff: list[float],
    timeout: float,
    user_agent: str,
) -> dict[str, Any]:
    headers = {
        "User-Agent": user_agent,
        "Referer": f"https://m.blog.naver.com/{blog_id}/{log_no}",
    }
    info_url = f"https://m.blog.naver.com/api/blogs/{blog_id}/posts/{log_no}/comments-info"
    resp, err = request_with_retries(
        session, info_url, max_retries=max_retries, backoff=backoff, timeout=timeout, headers=headers
    )
    if err or resp is None:
        return {"comment_collection_status": "추출 실패", "comment_coverage": "확인 불가", "comments": [], "error_reason": err}
    if resp.status_code in (401, 403):
        return {"comment_collection_status": "접근 제한", "comment_coverage": "확인 불가", "comments": [], "error_reason": f"http_{resp.status_code}"}
    if resp.status_code != 200:
        return {"comment_collection_status": "추출 실패", "comment_coverage": "확인 불가", "comments": [], "error_reason": f"http_{resp.status_code}"}

    try:
        info = resp.json()
    except Exception:
        # sometimes HTML login page
        if "로그인" in resp.text[:500]:
            return {"comment_collection_status": "접근 제한", "comment_coverage": "확인 불가", "comments": [], "error_reason": "login_html"}
        return {"comment_collection_status": "추출 실패", "comment_coverage": "확인 불가", "comments": [], "error_reason": "invalid_json_info"}

    if not info.get("isSuccess"):
        return {"comment_collection_status": "확인 불가", "comment_coverage": "확인 불가", "comments": [], "error_reason": "comments_info_unsuccessful"}

    result = info.get("result") or {}
    total_count = result.get("totalCount")
    if total_count == 0:
        return {
            "comment_collection_status": "댓글 0개 확인",
            "comment_coverage": "전체",
            "comments": [],
            "displayed_total": 0,
            "error_reason": None,
        }

    blog_no = result.get("blogNo")
    if not blog_no:
        return {"comment_collection_status": "추출 실패", "comment_coverage": "확인 불가", "comments": [], "error_reason": "missing_blog_no"}

    object_id = f"{blog_no}_201_{log_no}"
    list_url = (
        "https://apis.naver.com/commentBox/cbox/web_naver_list_json.json"
        f"?ticket=blog&templateId=default&pool=blogid&lang=ko"
        f"&objectId={object_id}&groupId={blog_no}&listType=OBJECT&pageType=more"
        f"&pageSize={max_comments}&page=1&sort=NEW&initialize=true"
    )
    resp2, err2 = request_with_retries(
        session, list_url, max_retries=max_retries, backoff=backoff, timeout=timeout, headers=headers
    )
    if err2 or resp2 is None or resp2.status_code != 200:
        return {
            "comment_collection_status": "추출 실패",
            "comment_coverage": "확인 불가",
            "comments": [],
            "displayed_total": total_count,
            "error_reason": err2 or f"http_{getattr(resp2, 'status_code', None)}",
        }

    try:
        payload = resp2.json()
    except Exception:
        return {
            "comment_collection_status": "추출 실패",
            "comment_coverage": "확인 불가",
            "comments": [],
            "displayed_total": total_count,
            "error_reason": "invalid_json_list",
        }

    if not payload.get("success"):
        # disabled?
        msg = payload.get("message") or ""
        if "비활성" in msg or "닫혀" in msg:
            status = "댓글 비활성화"
        else:
            status = "추출 실패"
        return {
            "comment_collection_status": status,
            "comment_coverage": "확인 불가",
            "comments": [],
            "displayed_total": total_count,
            "error_reason": msg or payload.get("code"),
        }

    cresult = payload.get("result") or {}
    comment_list = cresult.get("commentList") or []
    collected_at = datetime.now(tz).isoformat()
    rows: list[dict[str, Any]] = []

    hints = [h.lower() for h in (author_nickname_hints or []) if h]

    for idx, c in enumerate(comment_list[:max_comments]):
        comment_no = str(c.get("commentNo"))
        parent_no = str(c.get("parentCommentNo")) if c.get("parentCommentNo") is not None else None
        reply_level = c.get("replyLevel")
        # Top-level comments often set parentCommentNo == commentNo
        parent_comment_id = None
        if reply_level and int(reply_level) > 1 and parent_no and parent_no != comment_no:
            parent_comment_id = f"{blog_id}_{log_no}_{parent_no}"

        user_name = c.get("userName") or ""
        user_id = c.get("userIdNo") or c.get("idNo") or user_name
        commented_at_raw = c.get("modTime") or c.get("regTime")
        commented_at, _ = parse_naver_datetime(commented_at_raw, tz)
        if commented_at is None and commented_at_raw:
            # ISO-like 2025-02-23T10:34:26+0900
            try:
                commented_at = datetime.strptime(commented_at_raw, "%Y-%m-%dT%H:%M:%S%z")
            except Exception:
                commented_at = None

        is_post_author = "unknown"
        if hints and user_name:
            if user_name.lower() in hints:
                is_post_author = "true"
            else:
                is_post_author = "false"

        rows.append(
            {
                "comment_id": f"{blog_id}_{log_no}_{comment_no}",
                "parent_comment_id": parent_comment_id,
                "commenter_key": commenter_key_for(str(user_id), salt),
                "is_post_author": is_post_author,
                "comment_text": mask_pii(c.get("contents") or ""),
                "commented_at": commented_at.isoformat() if commented_at else None,
                "within_research_period": _within_period(commented_at, research_start, research_end),
                "collected_at": collected_at,
                "display_order": idx + 1,
                "sort_order": "NEW",
                "collection_method": "naver_cbox_api",
            }
        )

    coverage = "전체"
    if total_count is not None and total_count > len(rows):
        coverage = "일부"
    elif total_count is None:
        coverage = "확인 불가"

    return {
        "comment_collection_status": "수집 성공",
        "comment_coverage": coverage,
        "comments": rows,
        "displayed_total": total_count,
        "error_reason": None,
    }
