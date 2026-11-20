# 네이버 블로그 공개글 수집 (장소 기반 기록 서비스 탐색 리서치)

개인 일상·장소 경험 기록의 표현/관심/반응을 탐색하기 위한 **공개 게시물** 수집 파이프라인입니다.  
기간·키워드·월별 목표 수량은 `config.yaml`에서만 관리하며, 코드는 목록 길이와 설정을 읽어 작업 구간·목표를 계산합니다.

## 실제 사용 도구

| 단계 | 도구 | 비고 |
|------|------|------|
| 월별 검색 (기간+최신순) | Playwright (Python) | `section.blog.naver.com` PERIOD/`orderBy=recentdate` |
| 본문·메타 | HTTP `PostView.naver` + BeautifulSoup | 검색 요약문으로 본문 대체 안 함 |
| 공감 수 | Naver like API | 관측 시점 누적값 |
| 댓글 | Naver cbox API (모바일 comments-info 경유) | 게시물당 최대 N개(설정) |
| 큐/중복/이어받기/저장 | Python | Scrapy MCP 없음; Scrapy 패키지는 선택 의존성 |
| Firecrawl | MCP 연결됨, **본 수집 미사용** | 잔여 크레딧 제한으로 본문 추출 경로에서 제외 |
| 네이버 검색 API | **미사용** | `NAVER_CLIENT_ID/SECRET` 미설정 |

## 제한 사항

- `search.naver.com` robots `Disallow: /` → 해당 경로 미사용
- `section.blog.naver.com` robots `Disallow: /` → 전체 재귀 크롤 금지, 월×키워드 검색만 rate-limit
- 로그인 우회·CAPTCHA 우회 없음
- 이미지는 다운로드하지 않음
- 가상 게시물/댓글로 수량 채우지 않음
- 월별 수집량은 검색량·유행을 의미하지 않음

## 실행

```powershell
cd "c:\Users\user\Desktop\융합프로젝트\naver_blog_place_memory_research"
pip install -r requirements.txt
python -m playwright install chromium

# 본 수집 (중단 후 같은 명령으로 이어받기)
python run_collect.py

# CSV/XLSX + collection_report.md + qa_report.md
python run_finalize.py
```

## 설정

`config.yaml`

- `run.start_date` / `run.end_date` (Asia/Seoul, 양끝 포함)
- `keywords` 목록
- `collection.posts_per_keyword_month`
- `collection.candidate_url_limit_per_keyword_month`
- 요청 지연·재시도

키워드 개수나 1100 같은 총량을 코드에 고정하지 않습니다.

## 결과물

- `data/posts.csv`, `search_hits.csv`, `comments.csv`, `collection_log.csv`, `monthly_summary.csv`
- `data/research_dataset.xlsx`
- `qa_report.md`, `collection_report.md`
- `checkpoints/` 이어받기 상태

CSV는 UTF-8-SIG입니다.
