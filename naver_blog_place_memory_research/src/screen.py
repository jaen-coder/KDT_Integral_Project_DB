from __future__ import annotations

import re
from typing import Any


PROMO_PATTERNS = [
    r"예약\s*문의",
    r"상담\s*예약",
    r"지금\s*구매",
    r"할인\s*코드",
    r"쿠폰",
    r"광고문의",
    r"협찬\s*문의",
    r"업체\s*제공",
    r"홍보\s*담당",
    r"제품\s*협찬",
    r"원고료",
    r"체험단",
    r"할인\s*이벤트",
    r"카카오톡\s*문의",
    r"DM\s*문의",
]

SPONSOR_PATTERNS = [
    r"협찬",
    r"제공받",
    r"지원받",
    r"광고\s*포함",
    r"#광고",
    r"#협찬",
    r"원고료\s*받았",
    r"유료\s*광고",
]

PERSONAL_PATTERNS = [
    r"나는",
    r"내가",
    r"저는",
    r"제가",
    r"오늘",
    r"어제",
    r"다녀왔",
    r"갔었",
    r"느꼈",
    r"좋았",
    r"힘들",
    r"기록",
    r"일기",
    r"산책",
    r"여행",
    r"방문",
    r"봤어",
    r"먹었",
    r"마셨",
]


def classify_post(title: str | None, body: str | None, query: str) -> dict[str, Any]:
    title = title or ""
    body = body or ""
    text = f"{title}\n{body}"

    sponsor_hits = [p for p in SPONSOR_PATTERNS if re.search(p, text)]
    promo_hits = [p for p in PROMO_PATTERNS if re.search(p, text)]
    personal_hits = [p for p in PERSONAL_PATTERNS if re.search(p, text)]

    sponsorship_status = "명시 있음" if sponsor_hits else "명시 없음"
    if not body.strip():
        sponsorship_status = "확인 불가"

    has_personal = len(personal_hits) >= 2 or (
        len(personal_hits) >= 1 and len(body) >= 80
    )
    promo_heavy = len(promo_hits) >= 2 or (
        bool(promo_hits) and not has_personal and len(body) < 400
    )

    evidence_parts = []
    if personal_hits:
        evidence_parts.append("개인경험단서:" + ",".join(personal_hits[:5]))
    if promo_hits:
        evidence_parts.append("상업성단서:" + ",".join(promo_hits[:5]))
    if sponsor_hits:
        evidence_parts.append("협찬단서:" + ",".join(sponsor_hits[:5]))

    query_tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    related = any(t in text for t in query_tokens) if query_tokens else True

    if not body.strip():
        return {
            "content_type": "판단 보류",
            "sponsorship_status": sponsorship_status,
            "screening_reason": "본문 확인 불가",
            "screening_evidence": "; ".join(evidence_parts) or None,
            "analysis_eligible": "제외",
            "commerciality": "확인 불가",
            "personal_experience": "확인 불가",
        }

    if not related and not has_personal:
        return {
            "content_type": "판단 보류",
            "sponsorship_status": sponsorship_status,
            "screening_reason": "검색어와 무관해 보이고 개인 경험도 약함",
            "screening_evidence": "; ".join(evidence_parts) or title[:120],
            "analysis_eligible": "제외",
            "commerciality": "있음" if promo_hits else "약함",
            "personal_experience": "약함",
        }

    if promo_heavy and not has_personal:
        return {
            "content_type": "업체 홍보",
            "sponsorship_status": sponsorship_status,
            "screening_reason": "판매·예약·홍보 유도가 중심",
            "screening_evidence": "; ".join(evidence_parts),
            "analysis_eligible": "제외",
            "commerciality": "높음",
            "personal_experience": "없음/약함",
        }

    if has_personal and promo_hits:
        return {
            "content_type": "혼합",
            "sponsorship_status": sponsorship_status,
            "screening_reason": "개인 경험과 상업성 단서가 공존",
            "screening_evidence": "; ".join(evidence_parts),
            "analysis_eligible": "검토 필요",
            "commerciality": "있음",
            "personal_experience": "있음",
        }

    if has_personal:
        return {
            "content_type": "개인 경험",
            "sponsorship_status": sponsorship_status,
            "screening_reason": "일상·방문·감상 등 개인 경험 단서 확인",
            "screening_evidence": "; ".join(evidence_parts) or body[:160],
            "analysis_eligible": "포함",
            "commerciality": "약함",
            "personal_experience": "있음",
        }

    # informational list-like
    if len(re.findall(r"[0-9]+\.|•|·|-\s", body)) >= 8 and len(personal_hits) <= 1:
        return {
            "content_type": "정보 중심",
            "sponsorship_status": sponsorship_status,
            "screening_reason": "개인 경험보다 정보 나열 중심",
            "screening_evidence": "; ".join(evidence_parts) or body[:160],
            "analysis_eligible": "제외",
            "commerciality": "있음" if promo_hits else "약함",
            "personal_experience": "약함",
        }

    return {
        "content_type": "판단 보류",
        "sponsorship_status": sponsorship_status,
        "screening_reason": "개인 경험/상업성 판단이 애매함",
        "screening_evidence": "; ".join(evidence_parts) or body[:160],
        "analysis_eligible": "검토 필요",
        "commerciality": "확인 불가",
        "personal_experience": "확인 불가",
    }
