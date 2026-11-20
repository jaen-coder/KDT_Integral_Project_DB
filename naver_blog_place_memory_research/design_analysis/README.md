# 디자인 단서 분석 (design_analysis)

네이버 블로그 공개글 텍스트에서 **시각·디자인 관련 표현**을 추출하고, 위치 기반 기록 서비스의 디자인 방향을 검토하기 위한 근거·브리프를 만듭니다.

## 실행

```bash
cd design_analysis
pip install -r requirements.txt
python src/run_design_analysis.py
```

## 입력

- 정본: `../data/posts.csv`, `comments.csv`, `search_hits.csv` 등
- Excel(`research_dataset.xlsx`)은 동일 데이터의 다른 형식 → **중복 합산하지 않음**
- 원본 `data/`는 수정하지 않음

## 분석 범위

- 기간(실제 본문 일자): 2025-01-31T23:51:00+09:00 ~ 2026-10-31T23:59:00+09:00
- 검색 키워드(실제): 일상 기록, 사진 일기, 주간일기, 월간일기, 일상모음, 포토덤프, 여행 기록, 산책 기록, 동네 산책, 전시 후기
- 본분석 코퍼스: analysis_eligible=포함 ∩ content_type=개인 경험 ∩ 추출 성공 → **843게시물 / 764작성자**
- 방법: 규칙 기반 문맥 패턴 (`src/design_codebook.py`), 생성형 AI 분류 미사용
- 이미지 다운로드·색상 HEX·블로그 스킨 분석 **미실시**

## 주요 결과

| 파일 | 설명 |
|---|---|
| design_analysis_report.md | 분석 보고서 |
| design_brief.md | 디자인 브리프 |
| design_evidence.csv | 근거 문장 테이블 |
| design_element_summary.csv | 요소별 집계 |
| design_codebook.xlsx | 코드북 |
| design_direction_comparison.xlsx | 방향 비교·연결표 |
| design_research_results.xlsx | 통합 결과 |
| review_log.md | 재검토 로그 |
| charts/ | PNG·SVG 시각화 |

## 해석 주의

- 언급 비율 ≠ 전체 이용자 디자인 선호율
- A(직접)·B(간접)·C(디자이너 제안)를 합쳐 '사용자 선호'로 집계하지 않음
- 공간·패션·제품 미감을 앱 UI 선호로 비약하지 않음
