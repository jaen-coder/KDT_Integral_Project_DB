from __future__ import annotations

import hashlib
import json
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml
from dateutil.relativedelta import relativedelta

from .comments import fetch_comments
from .extract import extract_post
from .screen import classify_post
from .search import BlogSearchClient
from .utils import (
    atomic_json_write,
    author_key_for,
    load_json,
    month_windows,
    next_month_first,
    normalize_blog_url,
    now_seoul,
    parse_ymd,
)


POST_FIELDS = [
    "post_id", "canonical_url", "author_key", "title", "published_at", "published_month",
    "date_status", "collected_at", "body_text", "hashtags", "reaction_count",
    "displayed_comment_count", "content_type", "sponsorship_status", "screening_reason",
    "screening_evidence", "analysis_eligible", "collection_method", "extraction_status",
    "comment_collection_status", "comment_coverage", "near_duplicate_group",
]

HIT_FIELDS = [
    "run_id", "query", "search_month", "searched_at", "search_method", "sort_order",
    "requested_start_date", "requested_end_date", "date_filter_method", "result_rank",
    "result_url", "search_snippet", "post_id", "discovery_status",
]

COMMENT_FIELDS = [
    "comment_id", "post_id", "parent_comment_id", "commenter_key", "is_post_author",
    "comment_text", "commented_at", "within_research_period", "collected_at",
    "display_order", "sort_order", "collection_method",
]

LOG_FIELDS = [
    "run_id", "query", "search_month", "url", "stage", "status", "error_reason",
    "retry_count", "tool", "processed_at",
]


class CollectionPipeline:
    def __init__(self, root: Path | str, config_path: Path | None = None):
        self.root = Path(root)
        self.config_path = Path(config_path) if config_path else (self.root / "config.yaml")
        with self.config_path.open(encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        self.tz = ZoneInfo(self.cfg["run"]["timezone"])
        self.start_date = parse_ymd(self.cfg["run"]["start_date"])
        self.end_date = parse_ymd(self.cfg["run"]["end_date"])
        self.keywords: list[str] = list(self.cfg["keywords"])
        self.months = month_windows(self.start_date, self.end_date)

        col = self.cfg["collection"]
        self.posts_per_month = int(col["posts_per_keyword_month"])
        self.candidate_limit = int(col["candidate_url_limit_per_keyword_month"])
        self.comments_max = int(col["comments_per_post_max"])

        req = self.cfg["request"]
        self.delay_search = float(req["search_delay_sec"])
        self.delay_extract = float(req["extract_delay_sec"])
        self.delay_comment = float(req["comment_delay_sec"])
        self.max_retries = int(req["max_retries"])
        self.backoff = [float(x) for x in req["retry_backoff_sec"]]
        self.timeout = float(req["request_timeout_sec"])
        self.user_agent = req["user_agent"]

        paths = self.cfg["paths"]
        self.data_dir = self.root / paths["data_dir"]
        self.checkpoint_dir = self.root / paths["checkpoint_dir"]
        self.log_dir = self.root / paths["log_dir"]
        for d in (self.data_dir, self.checkpoint_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.state_path = self.checkpoint_dir / "state.json"
        self.posts_path = self.checkpoint_dir / "posts.json"
        self.hits_path = self.checkpoint_dir / "search_hits.json"
        self.comments_path = self.checkpoint_dir / "comments.json"
        self.logs_path = self.checkpoint_dir / "collection_log.json"
        self.tool_stats_path = self.checkpoint_dir / "tool_stats.json"

        self.state = load_json(self.state_path, None)
        if self.state is None:
            salt = hashlib.sha256(str(now_seoul(self.cfg["run"]["timezone"])).encode()).hexdigest()[:12]
            self.state = {
                "run_id": f"{self.cfg['run']['run_id_prefix']}_{now_seoul().strftime('%Y%m%d_%H%M%S')}",
                "author_salt": salt,
                "jobs": {},
                "created_at": now_seoul().isoformat(),
                "config_fingerprint": self._config_fingerprint(),
            }
        self._validate_config_fingerprint()

        self.posts: dict[str, dict[str, Any]] = load_json(self.posts_path, {})
        self.hits: list[dict[str, Any]] = load_json(self.hits_path, [])
        self.comments: list[dict[str, Any]] = load_json(self.comments_path, [])
        self.logs: list[dict[str, Any]] = load_json(self.logs_path, [])
        self.tool_stats: dict[str, Any] = load_json(
            self.tool_stats_path,
            {
                "playwright_search_calls": 0,
                "http_postview_calls": 0,
                "reaction_api_calls": 0,
                "comment_api_calls": 0,
                "firecrawl_calls": 0,
                "blocked_paths": [],
            },
        )

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def _config_fingerprint(self) -> str:
        payload = {
            "start": self.cfg["run"]["start_date"],
            "end": self.cfg["run"]["end_date"],
            "keywords": self.keywords,
            "posts_per_month": self.posts_per_month,
            "candidate_limit": self.candidate_limit,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]

    def _validate_config_fingerprint(self) -> None:
        fp = self._config_fingerprint()
        existing = self.state.get("config_fingerprint")
        if existing and existing != fp:
            raise RuntimeError(
                "Config period/keywords changed since checkpoint was created. "
                "Use a fresh checkpoint directory or restore the original config."
            )
        self.state["config_fingerprint"] = fp

    def job_key(self, query: str, month: str) -> str:
        return f"{query}||{month}"

    def iter_jobs(self) -> list[tuple[str, str, Any, Any]]:
        jobs = []
        for query in self.keywords:
            for month_key, m_start, m_end in self.months:
                jobs.append((query, month_key, m_start, m_end))
        return jobs

    def log(self, query: str, month: str, url: str | None, stage: str, status: str,
            error_reason: str | None = None, tool: str | None = None, retry_count: int = 0) -> None:
        self.logs.append(
            {
                "run_id": self.state["run_id"],
                "query": query,
                "search_month": month,
                "url": url,
                "stage": stage,
                "status": status,
                "error_reason": error_reason,
                "retry_count": retry_count,
                "tool": tool,
                "processed_at": now_seoul().isoformat(),
            }
        )

    def save(self) -> None:
        atomic_json_write(self.state_path, self.state)
        atomic_json_write(self.posts_path, self.posts)
        atomic_json_write(self.hits_path, self.hits)
        atomic_json_write(self.comments_path, self.comments)
        atomic_json_write(self.logs_path, self.logs)
        atomic_json_write(self.tool_stats_path, self.tool_stats)

    def _published_in_month(self, published_iso: str | None, month_start, month_end) -> bool:
        if not published_iso:
            return False
        try:
            dt = datetime.fromisoformat(published_iso)
        except ValueError:
            return False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)
        start_dt = datetime(month_start.year, month_start.month, month_start.day, 0, 0, 0, tzinfo=self.tz)
        end_exclusive = datetime(
            next_month_first(month_start).year,
            next_month_first(month_start).month,
            1, 0, 0, 0, tzinfo=self.tz,
        )
        # Also clamp to configured month_end inclusively via half-open next month
        return start_dt <= dt < end_exclusive and dt.date() <= month_end

    def process_job(self, search_client: BlogSearchClient, query: str, month: str, m_start, m_end) -> None:
        jk = self.job_key(query, month)
        job = self.state["jobs"].get(jk, {
            "status": "pending",
            "success_count": 0,
            "candidates_seen": 0,
            "failures": 0,
            "reason": None,
        })
        if job.get("status") == "completed":
            return

        job["status"] = "running"
        self.state["jobs"][jk] = job
        self.save()

        self.log(query, month, None, "search", "start", tool="playwright")
        search_result = search_client.search_month(query, m_start, m_end, self.candidate_limit)
        self.tool_stats["playwright_search_calls"] += 1

        if search_result.get("blocked"):
            job["status"] = "blocked"
            job["reason"] = search_result.get("error_reason")
            self.tool_stats["blocked_paths"].append(
                {"query": query, "month": month, "reason": job["reason"], "at": now_seoul().isoformat()}
            )
            self.log(query, month, None, "search", "blocked", error_reason=job["reason"], tool="playwright")
            self.state["jobs"][jk] = job
            self.save()
            return

        candidates = search_result.get("candidates") or []
        job["candidates_seen"] = len(candidates)
        job["sort_confirmed"] = search_result.get("sort_confirmed")
        job["period_confirmed"] = search_result.get("period_confirmed")
        job["search_exhausted"] = search_result.get("exhausted")
        job["search_error"] = search_result.get("error_reason")
        job["robots_note"] = search_result.get("robots_note")

        if search_result.get("error_reason") and not candidates:
            job["status"] = "failed_search"
            job["reason"] = search_result.get("error_reason")
            self.log(query, month, None, "search", "fail", error_reason=job["reason"], tool="playwright")
            self.state["jobs"][jk] = job
            self.save()
            return

        self.log(
            query, month, None, "search", "ok",
            error_reason=None if candidates else "no_candidates_in_search_path",
            tool="playwright",
        )

        success = int(job.get("success_count") or 0)
        # Resume mid-job: skip already linked hits for this job success posts
        already_success_ids = set(job.get("success_post_ids") or [])

        for cand in candidates:
            if success >= self.posts_per_month:
                break

            post_id = cand["post_id"]
            canonical = cand["result_url"]
            searched_at = now_seoul().isoformat()

            hit = {
                "run_id": self.state["run_id"],
                "query": query,
                "search_month": month,
                "searched_at": searched_at,
                "search_method": search_result.get("search_method"),
                "sort_order": search_result.get("sort_order"),
                "requested_start_date": m_start.isoformat(),
                "requested_end_date": m_end.isoformat(),
                "date_filter_method": search_result.get("date_filter_method"),
                "result_rank": cand["result_rank"],
                "result_url": canonical,
                "search_snippet": cand.get("search_snippet"),
                "post_id": post_id,
                "discovery_status": "candidate",
            }

            # If body already collected previously (other keyword/month), reuse body but still validate month
            if post_id in self.posts and self.posts[post_id].get("extraction_status") == "성공":
                existing = self.posts[post_id]
                in_month = self._published_in_month(existing.get("published_at"), m_start, m_end)
                if in_month:
                    hit["discovery_status"] = "reused_body"
                    self.hits.append(hit)
                    if post_id not in already_success_ids and success < self.posts_per_month:
                        # Count toward this month only if published in this month
                        already_success_ids.add(post_id)
                        success += 1
                        self.log(query, month, canonical, "extract", "reused", tool="cache")
                else:
                    hit["discovery_status"] = "month_mismatch_on_reuse"
                    self.hits.append(hit)
                    self.log(query, month, canonical, "extract", "skip", error_reason="published_month_mismatch", tool="cache")
                continue

            blog_id, log_no = post_id.split("_", 1)
            self.tool_stats["http_postview_calls"] += 1
            self.tool_stats["reaction_api_calls"] += 1
            extracted = extract_post(
                self.session,
                blog_id,
                log_no,
                tz=self.tz,
                max_retries=self.max_retries,
                backoff=self.backoff,
                timeout=self.timeout,
                user_agent=self.user_agent,
            )
            time.sleep(self.delay_extract)

            if extracted.get("extraction_status") != "성공":
                hit["discovery_status"] = "extract_failed"
                self.hits.append(hit)
                job["failures"] = int(job.get("failures") or 0) + 1
                self.log(
                    query, month, canonical, "extract", "fail",
                    error_reason=extracted.get("error_reason"), tool="http_postview",
                )
                # Store failure shell? only if not present
                if post_id not in self.posts:
                    self.posts[post_id] = {
                        "post_id": post_id,
                        "canonical_url": canonical,
                        "author_key": author_key_for(blog_id, self.state["author_salt"]),
                        "title": extracted.get("title"),
                        "published_at": extracted.get("published_at"),
                        "published_month": extracted.get("published_month"),
                        "date_status": extracted.get("date_status"),
                        "collected_at": now_seoul().isoformat(),
                        "body_text": None,
                        "hashtags": None,
                        "reaction_count": extracted.get("reaction_count"),
                        "displayed_comment_count": extracted.get("displayed_comment_count"),
                        "content_type": None,
                        "sponsorship_status": None,
                        "screening_reason": "본문 추출 실패",
                        "screening_evidence": extracted.get("error_reason"),
                        "analysis_eligible": "제외",
                        "collection_method": extracted.get("collection_method"),
                        "extraction_status": extracted.get("extraction_status"),
                        "comment_collection_status": "확인 불가",
                        "comment_coverage": "확인 불가",
                        "near_duplicate_group": None,
                    }
                continue

            in_month = self._published_in_month(extracted.get("published_at"), m_start, m_end)
            date_mismatch = False
            search_date = cand.get("search_date_text")
            if search_date and extracted.get("date_text_raw"):
                if search_date.replace(" ", "")[:10] not in (extracted.get("date_text_raw") or "").replace(" ", ""):
                    date_mismatch = True

            if not extracted.get("published_at"):
                hit["discovery_status"] = "date_unconfirmed"
                self.hits.append(hit)
                self.log(query, month, canonical, "extract", "skip", error_reason="published_at_missing", tool="http_postview")
                continue

            screened = classify_post(extracted.get("title"), extracted.get("body_text"), query)
            post_row = self._build_post_row(
                post_id,
                canonical,
                blog_id,
                extracted,
                screened,
                date_mismatch_note=(
                    "search_month_mismatch"
                    if not in_month
                    else ("search_vs_body_date_mismatch" if date_mismatch else None)
                ),
            )

            # Comments (even if month mismatched — body may still be useful once)
            self.tool_stats["comment_api_calls"] += 1
            cresult = fetch_comments(
                self.session,
                blog_id,
                log_no,
                author_nickname_hints=[],
                salt=self.state["author_salt"],
                tz=self.tz,
                research_start=parse_ymd(self.cfg["research_period"]["comment_inclusive_start"]),
                research_end=parse_ymd(self.cfg["research_period"]["comment_inclusive_end"]),
                max_comments=self.comments_max,
                max_retries=self.max_retries,
                backoff=self.backoff,
                timeout=self.timeout,
                user_agent=self.user_agent,
            )
            time.sleep(self.delay_comment)
            post_row["comment_collection_status"] = cresult.get("comment_collection_status")
            post_row["comment_coverage"] = cresult.get("comment_coverage")
            if cresult.get("displayed_total") is not None and post_row.get("displayed_comment_count") is None:
                post_row["displayed_comment_count"] = cresult.get("displayed_total")
            for c in cresult.get("comments") or []:
                c = dict(c)
                c["post_id"] = post_id
                self.comments.append(c)

            self.posts[post_id] = post_row

            if not in_month:
                hit["discovery_status"] = "month_mismatch"
                self.hits.append(hit)
                self.log(query, month, canonical, "extract", "skip", error_reason="published_month_mismatch", tool="http_postview")
                continue

            hit["discovery_status"] = "extracted_success"
            self.hits.append(hit)
            already_success_ids.add(post_id)
            success += 1
            self.log(query, month, canonical, "extract", "ok", tool="http_postview")

        job["success_count"] = success
        job["success_post_ids"] = sorted(already_success_ids)
        if success >= self.posts_per_month:
            job["status"] = "completed"
            job["reason"] = "target_reached"
        elif search_result.get("exhausted") or len(candidates) < self.candidate_limit:
            job["status"] = "completed"
            job["reason"] = "search_path_exhausted_or_short"
        else:
            job["status"] = "completed"
            job["reason"] = "candidate_limit_reached_without_full_target"

        self.state["jobs"][jk] = job
        self.save()

    def _build_post_row(self, post_id, canonical, blog_id, extracted, screened, date_mismatch_note=None):
        reason = screened.get("screening_reason")
        if date_mismatch_note:
            reason = f"{reason}; {date_mismatch_note}"
        return {
            "post_id": post_id,
            "canonical_url": canonical,
            "author_key": author_key_for(blog_id, self.state["author_salt"]),
            "title": extracted.get("title"),
            "published_at": extracted.get("published_at"),
            "published_month": extracted.get("published_month"),
            "date_status": extracted.get("date_status"),
            "collected_at": now_seoul().isoformat(),
            "body_text": extracted.get("body_text"),
            "hashtags": extracted.get("hashtags"),
            "reaction_count": extracted.get("reaction_count"),
            "displayed_comment_count": extracted.get("displayed_comment_count"),
            "content_type": screened.get("content_type"),
            "sponsorship_status": screened.get("sponsorship_status"),
            "screening_reason": reason,
            "screening_evidence": screened.get("screening_evidence"),
            "analysis_eligible": screened.get("analysis_eligible"),
            "collection_method": extracted.get("collection_method"),
            "extraction_status": extracted.get("extraction_status"),
            "comment_collection_status": None,
            "comment_coverage": None,
            "near_duplicate_group": None,
            "commerciality": screened.get("commerciality"),
            "personal_experience": screened.get("personal_experience"),
        }

    def mark_near_duplicates(self) -> None:
        # Simple near-duplicate by normalized body prefix hash
        groups: dict[str, list[str]] = defaultdict(list)
        for pid, post in self.posts.items():
            body = (post.get("body_text") or "").strip()
            if len(body) < 80:
                continue
            norm = " ".join(body.split())[:400]
            key = hashlib.md5(norm.encode("utf-8")).hexdigest()[:12]
            groups[key].append(pid)
        gid = 1
        for key, ids in groups.items():
            if len(ids) < 2:
                continue
            label = f"nd_{gid:04d}"
            gid += 1
            for pid in ids:
                self.posts[pid]["near_duplicate_group"] = label

    def run(self) -> None:
        jobs = self.iter_jobs()
        print(f"run_id={self.state['run_id']}")
        print(f"keywords={len(self.keywords)} months={len(self.months)} jobs={len(jobs)}")
        print(f"target_per_job={self.posts_per_month} candidate_cap={self.candidate_limit}")
        print(f"derived_max_posts_before_dedupe={len(self.keywords) * len(self.months) * self.posts_per_month}")

        with BlogSearchClient(self.user_agent, delay_sec=self.delay_search) as search_client:
            for i, (query, month, m_start, m_end) in enumerate(jobs, 1):
                jk = self.job_key(query, month)
                st = self.state["jobs"].get(jk, {}).get("status")
                if st == "completed":
                    print(f"[{i}/{len(jobs)}] SKIP {query} {month}")
                    continue
                if st == "blocked":
                    print(f"[{i}/{len(jobs)}] BLOCKED previously {query} {month}")
                    continue
                print(f"[{i}/{len(jobs)}] RUN {query} {month} ({m_start}~{m_end})")
                try:
                    self.process_job(search_client, query, month, m_start, m_end)
                except Exception as e:
                    self.log(query, month, None, "job", "fail", error_reason=str(e), tool="pipeline")
                    self.state["jobs"][jk] = {
                        **self.state["jobs"].get(jk, {}),
                        "status": "error",
                        "reason": str(e),
                        "traceback": traceback.format_exc()[-1000:],
                    }
                    self.save()
                    print(f"  ERROR: {e}")

        self.mark_near_duplicates()
        self.save()
        print("Collection loop finished.")
