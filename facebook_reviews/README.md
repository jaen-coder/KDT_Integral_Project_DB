# Facebook 리뷰 수집 (Google Play + App Store)

위치 기반 기록·소통 서비스 경쟁 리서치용. Facebook 최신 작성순 리뷰를 출처별로 최대 500개씩(합계 1,000) 수집합니다.

## 결과 파일

| 파일 | 설명 |
|------|------|
| `data/facebook_google_play.csv` | Google Play Store 고유 리뷰 (UTF-8 BOM) |
| `data/facebook_app_store.csv` | App Store(KR) 고유 리뷰 (UTF-8 BOM) |
| `data/facebook_reviews_all.csv` | 통합 CSV |
| `data/collection_summary.json` | 건수·날짜범위·정렬·제한사항 요약 |
| `checkpoints/` | 중간 저장(이어받기용) |

### CSV 컬럼

`service_name`, `platform`, `review_id`, `created_at`, `updated_at`, `rating`, `title`, `body`, `app_version`, `helpful_count`, `source_url`, `collected_at`, `sort_date_field`, `developer_reply`

- 작성자 실명·프로필 등 PII 미저장
- 개발자 답변은 `developer_reply`에만 분리 (Play 제공 시)
- 텍스트가 있는 리뷰만 포함 (별점/키워드/감성 필터 없음)

## 재실행

### Google Play

```powershell
cd "c:\Users\user\Desktop\융합프로젝트\facebook_reviews"
python scripts\collect_reviews.py --platform play --fresh
python scripts\collect_reviews.py --platform play --resume
```

### App Store

`apps.apple.com` catalog API (`sort=recent` = most recent). Playwright로 동일 엔드포인트·정렬을 확인했습니다.

```powershell
node scripts\collect_appstore_node.mjs
python scripts\finalize_outputs.py
python scripts\validate_and_summarize.py
```

## 정렬·정확성

| 출처 | 정렬 | 확인 |
|------|------|------|
| Google Play | 최신순 (`newest` / RPC sort=2) | Alexandria `sort=newest` 첫 리뷰 ID 일치 |
| App Store | 최신순 (`sort=recent`) | Playwright 브라우저 fetch로 동일 피드·날짜 내림차순 확인 |

- 정렬 날짜 필드: `created_at`
- `updated_at`: 공개 API에 별도 수정일 없음 → 공란

## 출처

- Play: https://play.google.com/store/apps/details?id=com.facebook.katana&hl=ko
- App Store: https://apps.apple.com/kr/app/facebook/id284882215

## 수집 제한

- 이번 실행에서 Firecrawl Alexandria App Store 다건 호출은 타임아웃 → CAPTCHA/차단 우회 없이 Node catalog API + Playwright 검증으로 동일 최신순 피드 수집
- 별점·키워드·타 국가로 부족분 보충하지 않음
