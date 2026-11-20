# 분류·집계 검토 기록

- run_id: `place_memory_concept_analysis_20261120`
- seed: `20261120`
- 검토 표본: 50건 (고정 시드, 선호방향 층화)
- 방법: 규칙 기반 자동 분류 + 원문 재대조 (사람 최종 검수 없음 → **자동 분류 및 재검토**)

## 검토 결과 요약

| error_type | n |
|---|---:|
| 이상없음 | 44 |
| 긍정단서_약함_검토 | 6 |


- 수정필요(action): 0
- 인용문 원문 존재 확인 실패: 0
- 상세: `review_sample.csv`

## 수치 검증

- keyword_summary 분모(denominator_posts) = core 고유 게시물 843
- 주제별 mention_posts ≤ 분모 확인: True
- 긍정 비율 분모 = 해당 주제 언급 게시물 (혼합을 긍정에 미포함)
- 차트 01~05 생성 여부: charts/ 폴더 확인

## 코드북

- `codebook.xlsx` / `src/codebook.py` 버전 rule_based_phrase_patterns_v1
- 생성형 AI 모델/프롬프트: 없음

## 해석 주의

- ‘언급 많음’ ≠ ‘좋아함’
- 본 표본 ≠ 2030/D그룹 전체 선호
