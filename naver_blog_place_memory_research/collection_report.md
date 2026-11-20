# Collection Report

## Environment and methods

- AGENTS.md: 저장소에 없음 (확인함)
- MCP 연결: Playwright (`user-playwright`), Firecrawl (`plugin-firecrawl-firecrawl`)
- Scrapy MCP: 없음 / Scrapy Python 패키지는 설치 가능했으나 본 파이프라인은 Playwright+HTTP 큐로 구현
- 네이버 공식 블로그 검색 API: `NAVER_CLIENT_ID/SECRET` 미설정 → 미사용
- 검색 경로: Playwright로 `section.blog.naver.com` PERIOD+최신순 검색 (월별 startDate/endDate)
- 본문 경로: HTTP `PostView.naver` + like API + cbox comment API
- Firecrawl: 본 수집 본문 추출에 미사용 (잔여 크레딧 제한, 예산 보존)

### Robots / policy notes

- `search.naver.com` robots: `User-agent: * Disallow: /` → 해당 검색 경로 미사용
- `section.blog.naver.com` robots: `User-agent: * Disallow: /` → 재귀 크롤 없음, 월별 키워드 검색만 rate-limit 브라우저 조회
- `blog.naver.com` robots: 일부 경로 Disallow, 개별 공개 PostView는 허용 범위에서 수집
- 로그인 우회/CAPTCHA 우회 없음. 차단 시 해당 경로 중단 후 로그 기록

## Scope (from config)

- keywords (10): 일상 기록, 사진 일기, 주간일기, 월간일기, 일상모음, 포토덤프, 여행 기록, 산책 기록, 동네 산책, 전시 후기
- months (22): 2025-01 ~ 2026-10
- jobs: 220 (= keywords × months)
- per-job body success target: 5
- per-job candidate cap: 30
- derived max before dedupe: 1100
- 이 수량은 작업 범위이며 통계적 대표 표본 수가 아님
- 최신순 월별 수집이므로 월 내 최근 게시물에 치우칠 수 있음 (무작위 표본 아님)

## Overall totals

- search_hits rows (키워드 연결, 중복 제거 전 관측): 1456
- unique posts stored: 1273
- unique posts with extraction_status=성공: 974
- unique authors: 867
- comments collected: 4737
- comments within research period (2025-01-01~2026-10-31): 4550
- published_at range (성공 본문): 2025-01-31T23:51:00+09:00 ~ 2026-10-31T23:59:00+09:00

### Author concentration (top 20)

- author_2934bc5e184b4aad: 10
- author_cc71cc93c8d0615b: 9
- author_cb21a490891803a7: 7
- author_575c00b0ee70639f: 6
- author_4cec2b2bc0ec05d9: 6
- author_1070303cff04b5bb: 5
- author_e161670176225a4a: 5
- author_a2b52cc97c0d001f: 5
- author_db6dd9eca8393501: 5
- author_f29299cb4f4dc4b1: 4
- author_7db5682b43e69eb5: 3
- author_96723632152cc4ab: 3
- author_3b42a65f5fab29ad: 3
- author_6f6b1d062c0fa008: 3
- author_6acc8e0686b6a240: 2
- author_b2ea4886f90eb223: 2
- author_19089f8de15ec758: 2
- author_659309eb7b3cfbe2: 2
- author_009962e752b37a16: 2
- author_5c4beea1bd1a18d8: 2

## Tool call counts

- playwright_search_calls: 220
- http_postview_calls: 1331
- reaction_api_calls: 1331
- comment_api_calls: 974
- firecrawl_calls: 0
- blocked_paths: 0

## Keyword × month summary

| query | month | candidates | success | include | exclude | review | comment_ok | shortfall | reason | sort | period |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| 일상 기록 | 2025-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-04 | 30 | 5 | 3 | 2 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-06 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-07 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-08 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-09 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-11 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2025-12 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-04 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-07 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상 기록 | 2026-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-01 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-02 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-05 | 12 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-06 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-07 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-08 | 14 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-09 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-10 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-11 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2025-12 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-01 | 20 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-02 | 21 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-06 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-07 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-08 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 사진 일기 | 2026-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2025-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2025-02 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 주간일기 | 2025-03 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 주간일기 | 2025-04 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 주간일기 | 2025-05 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 주간일기 | 2025-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 주간일기 | 2025-07 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2025-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2025-09 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 주간일기 | 2025-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2025-11 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2025-12 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2026-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2026-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 주간일기 | 2026-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2026-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2026-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 주간일기 | 2026-07 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2026-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 주간일기 | 2026-09 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 주간일기 | 2026-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2025-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2025-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2025-03 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2025-04 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2025-05 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 월간일기 | 2025-06 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 월간일기 | 2025-07 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2025-08 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2025-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2025-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2025-11 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2025-12 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2026-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2026-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2026-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2026-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2026-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2026-07 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2026-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 월간일기 | 2026-09 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 월간일기 | 2026-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2025-01 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 일상모음 | 2025-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2025-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2025-04 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2025-05 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2025-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2025-07 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2025-08 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2025-09 | 30 | 5 | 5 | 0 | 0 | 4 | 0 | None | True | True |
| 일상모음 | 2025-10 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 일상모음 | 2025-11 | 7 | 4 | 3 | 1 | 0 | 4 | 1 | search_path_exhausted_or_short | True | True |
| 일상모음 | 2025-12 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2026-01 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2026-02 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2026-03 | 14 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2026-04 | 30 | 5 | 5 | 0 | 0 | 4 | 0 | None | True | True |
| 일상모음 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2026-06 | 30 | 5 | 2 | 2 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2026-07 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 일상모음 | 2026-08 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2026-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 일상모음 | 2026-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-01 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-02 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-03 | 30 | 5 | 3 | 2 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-04 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-05 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-06 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-07 | 30 | 5 | 2 | 1 | 2 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-08 | 30 | 5 | 1 | 4 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-09 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-10 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-11 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2025-12 | 30 | 5 | 3 | 2 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-01 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-02 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-03 | 30 | 5 | 3 | 2 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-04 | 30 | 5 | 1 | 3 | 1 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-06 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-07 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-09 | 30 | 5 | 3 | 2 | 0 | 5 | 0 | None | True | True |
| 포토덤프 | 2026-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-04 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-07 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-10 | 27 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-11 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2025-12 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-01 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-06 | 30 | 5 | 4 | 1 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-07 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 여행 기록 | 2026-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-01 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-02 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-06 | 14 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-07 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-08 | 19 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-09 | 30 | 5 | 5 | 0 | 0 | 4 | 0 | None | True | True |
| 산책 기록 | 2025-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-11 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2025-12 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-01 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-02 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-05 | 27 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-06 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-07 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-08 | 26 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 산책 기록 | 2026-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-01 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-05 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-07 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-08 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-09 | 30 | 5 | 5 | 0 | 0 | 4 | 0 | None | True | True |
| 동네 산책 | 2025-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-11 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2025-12 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-01 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-02 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-03 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-06 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-07 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-08 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-09 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 동네 산책 | 2026-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-01 | 30 | 5 | 3 | 0 | 2 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-02 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-03 | 14 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-04 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-05 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-06 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-07 | 30 | 5 | 2 | 0 | 3 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-08 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-10 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-11 | 30 | 5 | 3 | 1 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2025-12 | 24 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-01 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-02 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-03 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-04 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-05 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-06 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-07 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-08 | 30 | 5 | 4 | 0 | 1 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-09 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |
| 전시 후기 | 2026-10 | 30 | 5 | 5 | 0 | 0 | 5 | 0 | None | True | True |

## Shortfall jobs: 1 / 220

미달 사유는 검색 경로 소진·후보 상한·추출 실패·게시월 불일치 등이며,
해당 월에 게시물이 없다고 단정하지 않음. ‘검색 경로에서 추가 결과 확보 불가’와 ‘조건 확인 0건’을 구분함.

## Incomplete / non-completed jobs

- count: 1
- 일상모음||2025-11

## Interpretation guardrails

- 월별 고정 수집량은 검색량/생산량을 의미하지 않음
- 수집 건수로 월별 유행 증감을 주장하지 않음
- 후속 분석의 월별 비율 비교 시 분석 가능 게시물 수를 분모로 명시할 것
- 결과를 2030 전체/D그룹 전체/전체 검색량으로 해석하지 말 것

## Outputs

- `data/posts.csv`, `search_hits.csv`, `comments.csv`, `collection_log.csv`, `monthly_summary.csv`
- `data/research_dataset.xlsx`
- `qa_report.md`
- Excel truncated bodies: 1 posts (full text kept in CSV)
