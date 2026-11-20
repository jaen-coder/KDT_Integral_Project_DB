from __future__ import annotations

from collections import Counter
from pathlib import Path

from .export_outputs import export_all
from .pipeline import CollectionPipeline


def write_collection_report(root: Path) -> str:
    stats = export_all(root)
    pipe = CollectionPipeline(root)

    lines = []
    lines.append("# Collection Report")
    lines.append("")
    lines.append("## Environment and methods")
    lines.append("")
    lines.append("- AGENTS.md: 저장소에 없음 (확인함)")
    lines.append("- MCP 연결: Playwright (`user-playwright`), Firecrawl (`plugin-firecrawl-firecrawl`)")
    lines.append("- Scrapy MCP: 없음 / Scrapy Python 패키지는 설치 가능했으나 본 파이프라인은 Playwright+HTTP 큐로 구현")
    lines.append("- 네이버 공식 블로그 검색 API: `NAVER_CLIENT_ID/SECRET` 미설정 → 미사용")
    lines.append("- 검색 경로: Playwright로 `section.blog.naver.com` PERIOD+최신순 검색 (월별 startDate/endDate)")
    lines.append("- 본문 경로: HTTP `PostView.naver` + like API + cbox comment API")
    lines.append("- Firecrawl: 본 수집 본문 추출에 미사용 (잔여 크레딧 제한, 예산 보존)")
    lines.append("")
    lines.append("### Robots / policy notes")
    lines.append("")
    lines.append("- `search.naver.com` robots: `User-agent: * Disallow: /` → 해당 검색 경로 미사용")
    lines.append("- `section.blog.naver.com` robots: `User-agent: * Disallow: /` → 재귀 크롤 없음, 월별 키워드 검색만 rate-limit 브라우저 조회")
    lines.append("- `blog.naver.com` robots: 일부 경로 Disallow, 개별 공개 PostView는 허용 범위에서 수집")
    lines.append("- 로그인 우회/CAPTCHA 우회 없음. 차단 시 해당 경로 중단 후 로그 기록")
    lines.append("")
    lines.append("## Scope (from config)")
    lines.append("")
    lines.append(f"- keywords ({len(stats['keywords'])}): {', '.join(stats['keywords'])}")
    lines.append(f"- months ({len(stats['months'])}): {stats['months'][0]} ~ {stats['months'][-1]}")
    lines.append(f"- jobs: {stats['jobs_total']} (= keywords × months)")
    lines.append(f"- per-job body success target: {pipe.posts_per_month}")
    lines.append(f"- per-job candidate cap: {pipe.candidate_limit}")
    lines.append(
        f"- derived max before dedupe: {len(stats['keywords']) * len(stats['months']) * pipe.posts_per_month}"
    )
    lines.append("- 이 수량은 작업 범위이며 통계적 대표 표본 수가 아님")
    lines.append("- 최신순 월별 수집이므로 월 내 최근 게시물에 치우칠 수 있음 (무작위 표본 아님)")
    lines.append("")
    lines.append("## Overall totals")
    lines.append("")
    lines.append(f"- search_hits rows (키워드 연결, 중복 제거 전 관측): {stats['search_hits_before_dedupe']}")
    lines.append(f"- unique posts stored: {stats['unique_posts_stored']}")
    lines.append(f"- unique posts with extraction_status=성공: {stats['unique_posts_extract_success']}")
    lines.append(f"- unique authors: {stats['unique_authors']}")
    lines.append(f"- comments collected: {stats['comments_total']}")
    lines.append(f"- comments within research period (2025-01-01~2026-10-31): {stats['comments_within_research_period']}")
    lines.append(f"- published_at range (성공 본문): {stats['published_at_min']} ~ {stats['published_at_max']}")
    lines.append("")
    lines.append("### Author concentration (top 20)")
    lines.append("")
    for author, cnt in stats["author_post_counts_top20"]:
        lines.append(f"- {author}: {cnt}")
    lines.append("")
    lines.append("## Tool call counts")
    lines.append("")
    for k, v in (stats.get("tool_stats") or {}).items():
        if k == "blocked_paths":
            lines.append(f"- blocked_paths: {len(v)}")
        else:
            lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## Keyword × month summary")
    lines.append("")
    lines.append(
        "| query | month | candidates | success | include | exclude | review | comment_ok | shortfall | reason | sort | period |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|")
    for r in stats["monthly_summary"]:
        lines.append(
            f"| {r['query']} | {r['search_month']} | {r['candidates_seen']} | {r['body_extract_success_in_month']} | "
            f"{r['analysis_include']} | {r['analysis_exclude']} | {r['analysis_review']} | "
            f"{r['comment_collection_ok_posts']} | {r['shortfall']} | {r.get('shortfall_reason')} | "
            f"{r.get('sort_confirmed')} | {r.get('period_confirmed')} |"
        )

    short = [r for r in stats["monthly_summary"] if r.get("shortfall", 0) > 0]
    lines.append("")
    lines.append(f"## Shortfall jobs: {len(short)} / {len(stats['monthly_summary'])}")
    lines.append("")
    lines.append("미달 사유는 검색 경로 소진·후보 상한·추출 실패·게시월 불일치 등이며,")
    lines.append("해당 월에 게시물이 없다고 단정하지 않음. ‘검색 경로에서 추가 결과 확보 불가’와 ‘조건 확인 0건’을 구분함.")
    lines.append("")
    lines.append("## Incomplete / non-completed jobs")
    lines.append("")
    incomplete = stats.get("incomplete_or_short_jobs") or []
    lines.append(f"- count: {len(incomplete)}")
    for item in incomplete[:50]:
        lines.append(f"- {item}")
    if len(incomplete) > 50:
        lines.append(f"- ... and {len(incomplete) - 50} more")
    lines.append("")
    lines.append("## Interpretation guardrails")
    lines.append("")
    lines.append("- 월별 고정 수집량은 검색량/생산량을 의미하지 않음")
    lines.append("- 수집 건수로 월별 유행 증감을 주장하지 않음")
    lines.append("- 후속 분석의 월별 비율 비교 시 분석 가능 게시물 수를 분모로 명시할 것")
    lines.append("- 결과를 2030 전체/D그룹 전체/전체 검색량으로 해석하지 말 것")
    lines.append("")
    lines.append("## Outputs")
    lines.append("")
    lines.append("- `data/posts.csv`, `search_hits.csv`, `comments.csv`, `collection_log.csv`, `monthly_summary.csv`")
    lines.append("- `data/research_dataset.xlsx`")
    lines.append("- `qa_report.md`")
    if stats.get("excel_body_truncated_post_ids"):
        lines.append(f"- Excel truncated bodies: {len(stats['excel_body_truncated_post_ids'])} posts (full text kept in CSV)")

    text = "\n".join(lines) + "\n"
    (root / "collection_report.md").write_text(text, encoding="utf-8")
    return text
