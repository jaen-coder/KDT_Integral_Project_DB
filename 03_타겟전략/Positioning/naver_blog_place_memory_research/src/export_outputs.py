from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .pipeline import COMMENT_FIELDS, HIT_FIELDS, LOG_FIELDS, POST_FIELDS, CollectionPipeline
from .utils import excel_safe, write_csv


EXCEL_CELL_LIMIT = 32767


def _truncate_for_excel(value: Any) -> tuple[Any, bool]:
    if value is None:
        return "", False
    s = str(value)
    if len(s) <= EXCEL_CELL_LIMIT:
        return excel_safe(s), False
    return excel_safe(s[: EXCEL_CELL_LIMIT - 20] + "…[TRUNCATED]"), True


def build_monthly_summary(pipe: CollectionPipeline) -> list[dict[str, Any]]:
    rows = []
    posts_by_id = pipe.posts
    hits = pipe.hits

    for query, month, m_start, m_end in pipe.iter_jobs():
        jk = pipe.job_key(query, month)
        job = pipe.state["jobs"].get(jk, {})
        month_hits = [h for h in hits if h.get("query") == query and h.get("search_month") == month]
        success_ids = set(job.get("success_post_ids") or [])
        # Also derive from hits with extracted_success / reused_body for this month
        for h in month_hits:
            if h.get("discovery_status") in {"extracted_success", "reused_body"} and h.get("post_id"):
                success_ids.add(h["post_id"])

        eligible = Counter()
        comment_ok = 0
        for pid in success_ids:
            p = posts_by_id.get(pid) or {}
            eligible[p.get("analysis_eligible") or "확인 불가"] += 1
            if p.get("comment_collection_status") in {"수집 성공", "댓글 0개 확인"}:
                comment_ok += 1

        fail_hits = [h for h in month_hits if h.get("discovery_status") in {"extract_failed", "date_unconfirmed", "month_mismatch"}]
        rows.append(
            {
                "query": query,
                "search_month": month,
                "requested_start_date": m_start.isoformat(),
                "requested_end_date": m_end.isoformat(),
                "candidates_seen": job.get("candidates_seen") or len(month_hits),
                "body_extract_success_in_month": len(success_ids),
                "analysis_include": eligible.get("포함", 0),
                "analysis_exclude": eligible.get("제외", 0),
                "analysis_review": eligible.get("검토 필요", 0),
                "comment_collection_ok_posts": comment_ok,
                "failures_or_skips": len(fail_hits),
                "target": pipe.posts_per_month,
                "shortfall": max(0, pipe.posts_per_month - len(success_ids)),
                "shortfall_reason": None if len(success_ids) >= pipe.posts_per_month else (job.get("reason") or "unknown"),
                "sort_confirmed": job.get("sort_confirmed"),
                "period_confirmed": job.get("period_confirmed"),
                "job_status": job.get("status"),
            }
        )
    return rows


def export_all(root: Path) -> dict[str, Any]:
    pipe = CollectionPipeline(root)
    pipe.mark_near_duplicates()

    posts_rows = []
    excel_trunc = []
    for pid, p in sorted(pipe.posts.items()):
        row = {k: p.get(k) for k in POST_FIELDS}
        posts_rows.append(row)
        body = p.get("body_text") or ""
        if len(str(body)) > EXCEL_CELL_LIMIT:
            excel_trunc.append(pid)

    hits_rows = [{k: h.get(k) for k in HIT_FIELDS} for h in pipe.hits]
    comment_rows = [{k: c.get(k) for k in COMMENT_FIELDS} for c in pipe.comments]
    log_rows = [{k: r.get(k) for k in LOG_FIELDS} for r in pipe.logs]
    monthly = build_monthly_summary(pipe)

    data_dir = pipe.data_dir
    write_csv(data_dir / "posts.csv", posts_rows, POST_FIELDS)
    write_csv(data_dir / "search_hits.csv", hits_rows, HIT_FIELDS)
    write_csv(data_dir / "comments.csv", comment_rows, COMMENT_FIELDS)
    write_csv(data_dir / "collection_log.csv", log_rows, LOG_FIELDS)
    monthly_fields = list(monthly[0].keys()) if monthly else [
        "query", "search_month", "candidates_seen", "body_extract_success_in_month"
    ]
    write_csv(data_dir / "monthly_summary.csv", monthly, monthly_fields)

    # Excel with truncation flags
    xlsx_path = data_dir / "research_dataset.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        def sheet(name: str, rows: list[dict], fields: list[str]):
            out = []
            for r in rows:
                item = {}
                trunc_cols = []
                for f in fields:
                    val, truncated = _truncate_for_excel(r.get(f))
                    item[f] = val
                    if truncated:
                        trunc_cols.append(f)
                item["excel_truncated_fields"] = ",".join(trunc_cols) if trunc_cols else ""
                out.append(item)
            pd.DataFrame(out, columns=fields + ["excel_truncated_fields"]).to_excel(writer, sheet_name=name, index=False)

        sheet("posts", posts_rows, POST_FIELDS)
        sheet("search_hits", hits_rows, HIT_FIELDS)
        sheet("comments", comment_rows, COMMENT_FIELDS)
        sheet("collection_log", log_rows, LOG_FIELDS)
        sheet("monthly_summary", monthly, monthly_fields)

    # Aggregate stats for report
    success_posts = [p for p in pipe.posts.values() if p.get("extraction_status") == "성공"]
    authors = Counter(p.get("author_key") for p in success_posts if p.get("author_key"))
    dates = []
    for p in success_posts:
        if p.get("published_at"):
            try:
                dates.append(datetime.fromisoformat(p["published_at"]))
            except Exception:
                pass

    within_period_comments = sum(1 for c in pipe.comments if c.get("within_research_period") == "true")
    incomplete_jobs = [
        k for k, v in pipe.state["jobs"].items()
        if v.get("status") not in {"completed"} or (v.get("success_count") or 0) < pipe.posts_per_month
    ]

    stats = {
        "run_id": pipe.state["run_id"],
        "keywords": pipe.keywords,
        "months": [m[0] for m in pipe.months],
        "jobs_total": len(pipe.iter_jobs()),
        "search_hits_before_dedupe": len(pipe.hits),
        "unique_posts_stored": len(pipe.posts),
        "unique_posts_extract_success": len(success_posts),
        "unique_authors": len(authors),
        "author_post_counts_top20": authors.most_common(20),
        "comments_total": len(pipe.comments),
        "comments_within_research_period": within_period_comments,
        "published_at_min": min(dates).isoformat() if dates else None,
        "published_at_max": max(dates).isoformat() if dates else None,
        "incomplete_or_short_jobs": incomplete_jobs,
        "tool_stats": pipe.tool_stats,
        "excel_body_truncated_post_ids": excel_trunc,
        "monthly_summary": monthly,
    }
    (data_dir / "aggregate_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return stats
