# Instagram 리뷰 수집 (Google Play + App Store)

위치 기반 기록·소통 서비스 경쟁 리서치용. Instagram 최신 작성순 리뷰를 출처별로 최대 500개씩(합계 1,000) 수집합니다.

## 결과 파일

| 파일 | 설명 |
|------|------|
| `data/instagram_google_play.csv` | Google Play Store 고유 리뷰 (UTF-8 BOM) |
| `data/instagram_app_store.csv` | App Store(KR) 고유 리뷰 (UTF-8 BOM) |
| `data/instagram_reviews_all.csv` | 통합 CSV |
| `data/collection_summary.json` | 건수·날짜범위·정렬·제한사항 요약 |
| `checkpoints/` | 중간 저장(이어받기용) |

### CSV 컬럼

`service_name`, `platform`, `review_id`, `created_at`, `updated_at`, `rating`, `title`, `body`, `app_version`, `helpful_count`, `source_url`, `collected_at`, `sort_date_field`, `developer_reply`

- 작성자 실명·프로필 URL 등 PII는 저장하지 않음
- 개발자 답변은 `developer_reply`에만 분리 저장 (Play에서 제공 시)
- 텍스트가 있는 리뷰만 포함 (별점/키워드/감성 필터 없음)

## 재실행

### 1) Google Play (로컬 스크립트, 권장)

Play Store 공개 batchexecute RPC (`UsvDTd`, **sort=2 = newest**)로 페이지네이션합니다.

```powershell
cd "c:\Users\user\Desktop\융합프로젝트\instagram_reviews"
python scripts\collect_reviews.py --platform play --fresh
# 중단 후 이어받기
python scripts\collect_reviews.py --platform play --resume
```

### 2) App Store

수집 시점 기준:

- iTunes RSS(`sortBy=mostRecent`)는 Instagram에 대해 **entry 0건**
- `apps.apple.com/api/.../reviews?sort=recent` 직접 호출·Playwright `fetch`는 **HTTP 429**
- 실제 500건은 **Firecrawl Alexandria** `apps-apple-com` / `apps/reviews` (`sort=most_recent`, `country=kr`, offset 0→490, 10건/페이지)로 확보

페이지 JSON이 `checkpoints/appstore_pages/offset_XXXX.json`에 있으면:

```powershell
python scripts\merge_alexandria_pages.py
python scripts\finalize_outputs.py
```

Alexandria로 추가 페이지를 받은 뒤 같은 폴더에 저장하고 merge를 다시 실행하면 됩니다.

### 3) 전체 요약 재생성

```powershell
python scripts\finalize_outputs.py
```

## 정렬·정확성 확인

| 출처 | 정렬 | 확인 |
|------|------|------|
| Google Play | 최신순 (`newest` / RPC sort=2) | 수집 결과 `created_at` 내림차순; Alexandria `media/app_reviews sort=newest`와 동일 리뷰 ID·시각 교차확인 |
| App Store | 최신순 (`most_recent` / `sort=recent`) | offset 페이지별 날짜가 전반적으로 감소; 도움됨순(`most_helpful`) 미사용 |

- 정렬 기준 날짜 필드: `created_at` (`sort_date_field`에 기록)
- `updated_at`: 양쪽 공개 API에서 별도 수정일 미제공 → 공란. App Store에 `is_edited` 플래그는 있으나 수정 시각 없음

## 수집 제한 (기록)

1. App Store RSS 비어 있음 → RSS로 보충하지 않음
2. App Store 직접 API/Playwright 429 → CAPTCHA·차단 우회 없음, Alexandria로 동일 최신순 피드 수집
3. 별점·키워드·타 국가 피드로 부족분 보충하지 않음
4. 리뷰 ID 기준 중복 제거만 수행 (동일 본문이라도 ID가 다르면 유지)
