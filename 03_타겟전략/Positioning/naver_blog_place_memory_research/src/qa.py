from __future__ import annotations

import random
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

from .pipeline import CollectionPipeline
from .utils import normalize_blog_url


def _snippet(text: str | None, n: int = 80) -> str:
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    return t[:n]


def verify_sample(session: requests.Session, post: dict[str, Any], user_agent: str) -> dict[str, Any]:
    url = post.get("canonical_url")
    result = {
        "post_id": post.get("post_id"),
        "url": url,
        "title_match": "미검증",
        "date_match": "미검증",
        "body_prefix_match": "미검증",
        "body_mid_match": "미검증",
        "body_suffix_match": "미검증",
        "notes": [],
    }
    try:
        blog_id, log_no = post["post_id"].split("_", 1)
        postview = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}&redirect=Dlog"
        resp = session.get(postview, headers={"User-Agent": user_agent}, timeout=45)
        if resp.status_code != 200:
            result["notes"].append(f"http_{resp.status_code}")
            return result
        soup = BeautifulSoup(resp.text, "lxml")
        title_el = soup.select_one(".se-title-text") or soup.select_one("#title_1")
        date_el = soup.select_one(".se_publishDate")
        body_el = soup.select_one(".se-main-container") or soup.select_one("#postViewArea")
        live_title = title_el.get_text(" ", strip=True) if title_el else ""
        live_date = date_el.get_text(" ", strip=True) if date_el else ""
        live_body = body_el.get_text("\n", strip=True) if body_el else ""

        stored_title = post.get("title") or ""
        result["title_match"] = (
            "일치"
            if stored_title and (stored_title in live_title or live_title in stored_title)
            else "불일치"
        )

        stored_pub = post.get("published_at") or ""
        # compare yyyy. m. d
        m = re.search(r"(20\d{2}).\s*(\d{1,2}).\s*(\d{1,2})", live_date)
        if m and stored_pub:
            live_key = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            result["date_match"] = "일치" if stored_pub.startswith(live_key) else "불일치"
        else:
            result["date_match"] = "미검증"

        body = post.get("body_text") or ""
        if body and live_body:
            prefix = _snippet(body, 60)
            mid_start = max(0, len(body) // 2 - 30)
            mid = _snippet(body[mid_start:], 60)
            suffix = _snippet(body[-80:], 60)
            result["body_prefix_match"] = "일치" if prefix and prefix[:40] in live_body.replace("\n", " ") else "불일치"
            live_flat = re.sub(r"\s+", " ", live_body)
            result["body_mid_match"] = "일치" if mid and mid[:30] in live_flat else ("미검증" if len(body) < 120 else "불일치")
            result["body_suffix_match"] = "일치" if suffix and suffix[:30] in live_flat else ("미검증" if len(body) < 80 else "불일치")
        else:
            result["notes"].append("empty_body_compare")
    except Exception as e:
        result["notes"].append(str(e))
    return result


def run_qa(root: Path) -> str:
    pipe = CollectionPipeline(root)
    cfg = pipe.cfg
    seed = int(cfg["qa"]["random_seed"])
    n_per_kw = int(cfg["qa"]["samples_per_keyword"])
    rng = random.Random(seed)

    # Group successful posts by keyword via hits
    by_kw: dict[str, list[str]] = defaultdict(list)
    for h in pipe.hits:
        if h.get("discovery_status") in {"extracted_success", "reused_body"} and h.get("post_id"):
            pid = h["post_id"]
            p = pipe.posts.get(pid)
            if p and p.get("extraction_status") == "성공":
                by_kw[h["query"]].append(pid)

    selected: list[tuple[str, str]] = []
    for kw in pipe.keywords:
        ids = sorted(set(by_kw.get(kw, [])))
        # prefer diverse months
        by_month: dict[str, list[str]] = defaultdict(list)
        for pid in ids:
            by_month[pipe.posts[pid].get("published_month") or "unknown"].append(pid)
        months = list(by_month.keys())
        rng.shuffle(months)
        picked = []
        for m in months:
            if len(picked) >= n_per_kw:
                break
            cand = by_month[m][:]
            rng.shuffle(cand)
            picked.append(cand[0])
        if len(picked) < n_per_kw:
            rest = [pid for pid in ids if pid not in picked]
            rng.shuffle(rest)
            picked.extend(rest[: n_per_kw - len(picked)])
        for pid in picked:
            selected.append((kw, pid))

    session = requests.Session()
    checks = []
    for kw, pid in selected:
        post = pipe.posts[pid]
        checks.append({"query": kw, **verify_sample(session, post, pipe.user_agent)})

    # Integrity checks
    post_ids = set(pipe.posts.keys())
    hit_post_ids = {h.get("post_id") for h in pipe.hits if h.get("post_id")}
    orphan_hits = sorted(hit_post_ids - post_ids)
    comment_post_ids = {c.get("post_id") for c in pipe.comments}
    orphan_comments = sorted(comment_post_ids - post_ids)

    parent_ok = 0
    parent_bad = 0
    comment_ids = {c.get("comment_id") for c in pipe.comments}
    for c in pipe.comments:
        parent = c.get("parent_comment_id")
        if parent is None:
            parent_ok += 1
        elif parent in comment_ids:
            parent_ok += 1
        else:
            parent_bad += 1

    lines = []
    lines.append("# QA Report")
    lines.append("")
    lines.append(f"- run_id: `{pipe.state['run_id']}`")
    lines.append(f"- random_seed: `{seed}`")
    lines.append(f"- samples_requested_per_keyword: `{n_per_kw}`")
    lines.append(f"- samples_checked: `{len(checks)}`")
    lines.append("")
    lines.append("## Sample re-fetch checks")
    lines.append("")
    lines.append("| query | post_id | title | date | body_prefix | body_mid | body_suffix | notes |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for c in checks:
        notes = "; ".join(c.get("notes") or []) or ""
        lines.append(
            f"| {c['query']} | {c['post_id']} | {c['title_match']} | {c['date_match']} | "
            f"{c['body_prefix_match']} | {c['body_mid_match']} | {c['body_suffix_match']} | {notes} |"
        )

    lines.append("")
    lines.append("## Integrity")
    lines.append("")
    lines.append(f"- orphan search_hits post_ids (no posts row): {len(orphan_hits)}")
    if orphan_hits[:20]:
        lines.append(f"  - examples: {', '.join(orphan_hits[:20])}")
    lines.append(f"- orphan comments post_ids: {len(orphan_comments)}")
    lines.append(f"- comment parent links ok/missing-parent-row: {parent_ok}/{parent_bad}")
    lines.append("")
    lines.append("## Comment sample")
    lines.append("")
    # pick up to 5 posts with comments among checked samples
    shown = 0
    for c in checks:
        pid = c["post_id"]
        cms = [x for x in pipe.comments if x.get("post_id") == pid][:5]
        if not cms:
            continue
        lines.append(f"### {pid}")
        for cm in cms:
            lines.append(
                f"- `{cm.get('comment_id')}` parent=`{cm.get('parent_comment_id')}` "
                f"text=`{(cm.get('comment_text') or '')[:80]}`"
            )
        shown += 1
        if shown >= 5:
            break
    if shown == 0:
        lines.append("- 검증 표본 중 댓글이 있는 게시물이 없거나 댓글 미수집 (미검증)")

    lines.append("")
    lines.append("## Unverified items")
    lines.append("")
    lines.append("- 이미지 내용/스타일: 미검증 (다운로드·분석 없음)")
    lines.append("- 작성자 연령·성별: 추정하지 않음 / 미검증")
    lines.append("- 검색 API 경로: 환경에 인증정보 없어 미사용")
    lines.append("- Firecrawl 본문 추출: 본 수집 경로에 미사용 (크레딧 보존)")

    report = "\n".join(lines) + "\n"
    out = root / "qa_report.md"
    out.write_text(report, encoding="utf-8")
    return report
