# 블로그 콘셉트 분석 (analysis)

## 실행 방법

```bash
cd analysis
pip install -r requirements.txt
python src/run_analysis.py
```

## 분석 범위

- 원본: `../data/posts.csv` 등 (원본 변경 없음)
- 기간: 2025-01-01 ~ 2026-10-31
- 본분석: 개인 경험 + analysis_eligible=포함 + 본문 성공
- 코딩: 규칙 기반 패턴 (`src/codebook.py`), 생성형 AI 미사용
- seed: 20261120

## 주요 결과 파일

| 파일 | 설명 |
|---|---|
| concept_research_report.md | 팀 공유용 보고서 |
| keyword_summary.csv | 주제별 언급·선호 집계 |
| evidence_table.csv | 근거 문장 단위 테이블 |
| codebook.xlsx | 코드북 |
| concept_comparison.xlsx | 콘셉트 후보 비교 |
| analysis_results.xlsx | 통합 결과 |
| charts/ | 시각화 PNG/SVG |
| data_quality_report.md | 품질 |
| analysis_review.md | 재검토 |

## 주의

언급 빈도 ≠ 선호도. 표본 ≠ 전체 세대 선호. search_hits는 검색량이 아님.
