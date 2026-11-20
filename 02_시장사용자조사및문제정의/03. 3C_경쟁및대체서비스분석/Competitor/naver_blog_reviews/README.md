# 네이버 블로그 리뷰 수집 (Google Play + App Store)

위치 기반 기록·소통 서비스 경쟁 리서치용. 네이버 블로그 최신 작성순 리뷰를 출처별로 최대 500개씩(합계 1,000) 수집합니다.

## 결과 파일

| 파일 | 설명 |
|------|------|
| `data/naver_blog_google_play.csv` | Google Play Store 고유 리뷰 (UTF-8 BOM) |
| `data/naver_blog_app_store.csv` | App Store(KR) 고유 리뷰 (UTF-8 BOM) |
| `data/naver_blog_reviews_all.csv` | 통합 CSV |
| `data/collection_summary.json` | 건수·날짜범위·정렬·제한사항 요약 |
| `checkpoints/` | 중간 저장(이어받기용) |

### CSV 컬럼

`service_name`, `platform`, `review_id`, `created_at`, `updated_at`, `rating`, `title`, `body`, `app_version`, `helpful_count`, `source_url`, `collected_at`, `sort_date_field`, `developer_reply`

- 작성자 실명·프로필 등 PII 미저장
- 개발자 답변은 `developer_reply`에만 분리 (Play 제공 시)
- 텍스트가 있는 리뷰만 포함 (별점/키워드/감성 필터 없음)

## 재실행

### Google Play

Play Store 공개 batchexecute RPC (`UsvDTd`, **sort=2 = newest**).

```powershell
cd "c:\Users\user\Desktop\융합프로젝트\naver_blog_reviews"
python scripts\collect_reviews.py --platform play --fresh
# 이어받기
python scripts\collect_reviews.py --platform play --resume
```

### App Store

Firecrawl Alexandria `apps-apple-com` / `apps/reviews` (`sort=most_recent`, `country=kr`, offset 페이지네이션).  
페이지 JSON을 `checkpoints/appstore_pages/offset_XXXX.json`에 저장한 뒤:

```powershell
python scripts\finalize_outputs.py
# 또는
python scripts\merge_alexandria_pages.py
python scripts\finalize_outputs.py
```

Alexandria 응답 덤프를 저장할 때:

```powershell
python scripts\save_alexandria_batch.py "<agent-tools-json-path>"
```

### 요약·검증

```powershell
python scripts\validate_and_summarize.py
```

## 정렬·정확성

| 출처 | 정렬 | 확인 |
|------|------|------|
| Google Play | 최신순 (`newest` / RPC sort=2) | `created_at` 내림차순; Alexandria `sort=newest` 첫 리뷰 ID 일치 |
| App Store | 최신순 (`most_recent`) | offset 페이지 날짜 전반 감소; 도움됨순 미사용 |

- 정렬 날짜 필드: `created_at`
- `updated_at`: 공개 API에 별도 수정일 없음 → 공란

## 출처

- Play: https://play.google.com/store/apps/details?id=com.nhn.android.blog&hl=ko
- App Store: https://apps.apple.com/kr/app/네이버-블로그-naver-blog/id328813873
