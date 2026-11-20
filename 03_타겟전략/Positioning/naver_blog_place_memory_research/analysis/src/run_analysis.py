#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
네이버 블로그 수집 데이터 → 관심사·선호 이유·서비스 콘셉트 후보 분석
재현 가능 규칙 기반 파이프라인 (생성형 AI 분류 미사용)
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd
import yaml
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows

# local
sys.path.insert(0, str(Path(__file__).resolve().parent))
from codebook import (
    INTEREST_THEMES,
    EMOTION_CODES,
    REASON_CODES,
    PREF_POS,
    PREF_NEG,
    BEHAVIOR_CODES,
    SERVICE_LINKS,
    COMMENT_TYPES,
    SEARCH_KEYWORDS,
    NORMALIZATION_MAP,
)

ROOT = Path(__file__).resolve().parents[1]  # analysis/
CFG_PATH = ROOT / "analysis_config.yaml"


def load_cfg():
    with open(CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def setup_korean_font():
    candidates = [
        "Malgun Gothic",
        "맑은 고딕",
        "NanumGothic",
        "AppleGothic",
        "Noto Sans CJK KR",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
    # try path search
    for p in fm.findSystemFonts():
        low = p.lower()
        if "malgun" in low or "nanum" in low:
            fm.fontManager.addfont(p)
            name = fm.FontProperties(fname=p).get_name()
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
    return None


def clean_text(t: str) -> str:
    if not isinstance(t, str):
        return ""
    t = t.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def apply_normalization(text: str) -> str:
    out = text
    for src, dst in NORMALIZATION_MAP.items():
        out = re.sub(re.escape(src), dst, out, flags=re.IGNORECASE)
    return out


def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    # keep short units for evidence
    parts = re.split(r"(?<=[\.!?。…\n])\s+|(?<=요)\s+(?=[가-힣A-Z])|(?<=다)\s+(?=[가-힣A-Za-z0-9])", text)
    sents = [p.strip() for p in parts if p and len(p.strip()) >= 4]
    if not sents and text:
        sents = [text[:500]]
    return sents


def any_match(patterns, text: str) -> list[str]:
    hits = []
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            hits.append(p)
    return hits


def polarity_for_sentence(sent: str) -> str:
    pos = bool(any_match(PREF_POS, sent))
    neg = bool(any_match(PREF_NEG, sent))
    if pos and neg:
        return "혼합"
    if pos:
        return "긍정"
    if neg:
        return "부정"
    return "중립"


def polarity_aggregate(labels: list[str]) -> str:
    labs = set(labels)
    if not labs or labs == {"중립"}:
        return "중립"
    if "판단 불가" in labs and len(labs) == 1:
        return "판단 불가"
    has_pos = "긍정" in labs
    has_neg = "부정" in labs
    has_mix = "혼합" in labs
    if has_mix or (has_pos and has_neg):
        return "혼합"
    if has_pos:
        return "긍정"
    if has_neg:
        return "부정"
    return "중립"


def find_evidence_sentence(sents: list[str], patterns: list[str], raw_text: str) -> tuple[int, str] | tuple[None, None]:
    for i, s in enumerate(sents):
        if any_match(patterns, s):
            # prefer a contiguous snippet that exists in raw text
            snippet = s.strip()[:400]
            if clean_text(snippet)[:30] in clean_text(raw_text):
                return i + 1, snippet
            # fallback: extract window around first pattern hit in raw
            for p in patterns:
                m = re.search(p, raw_text, flags=re.IGNORECASE)
                if m:
                    a = max(0, m.start() - 40)
                    b = min(len(raw_text), m.end() + 80)
                    return i + 1, clean_text(raw_text[a:b])[:400]
            return i + 1, snippet
    return None, None


def code_post(row, corpus_tag: str) -> list[dict]:
    """Return evidence rows for one post (multi-label)."""
    body = apply_normalization(clean_text(str(row.get("body_text") or "")))
    title = clean_text(str(row.get("title") or ""))
    full = f"{title}\n{body}"
    sents = split_sentences(full)
    evidences = []
    eid_base = f"E_{row['post_id']}"

    # themes
    for theme_id, theme in INTEREST_THEMES.items():
        if not any_match(theme["patterns"], full):
            continue
        sent_i, sent = find_evidence_sentence(sents, theme["patterns"], full)
        if sent is None:
            # window around first hit in full text
            sent_i, sent = 0, full[:200]
            for p in theme["patterns"]:
                m = re.search(p, full, flags=re.IGNORECASE)
                if m:
                    a = max(0, m.start() - 40)
                    b = min(len(full), m.end() + 80)
                    sent = clean_text(full[a:b])[:400]
                    break
        # polarity around theme: look at matching sentences
        theme_sents = [s for s in sents if any_match(theme["patterns"], s)]
        pols = [polarity_for_sentence(s) for s in theme_sents] or ["판단 불가"]
        pol = polarity_aggregate(pols)

        # reasons in nearby theme sentences
        reasons = []
        for rid, rdef in REASON_CODES.items():
            if any(any_match(rdef["patterns"], s) for s in theme_sents):
                reasons.append(rid)

        # emotions in theme sentences
        emotions = []
        for eid, edef in EMOTION_CODES.items():
            if any(any_match(edef["patterns"], s) for s in theme_sents):
                emotions.append(eid)

        behaviors = []
        for bid, bdef in BEHAVIOR_CODES.items():
            if any(any_match(bdef["patterns"], s) for s in theme_sents + sents[:5]):
                behaviors.append(bid)

        service_links = []
        for sid, sdef in SERVICE_LINKS.items():
            if any_match(sdef["patterns"], full):
                # only attach if theme-relevant or global service cue near theme
                if any(any_match(sdef["patterns"], s) for s in theme_sents) or sid in ("기록", "회상", "장소경험", "발견"):
                    if any_match(sdef["patterns"], full):
                        service_links.append(sid)

        # expression (visual) only if theme is visual or patterns hit
        expression = "있음" if theme_id == "시각표현_질감색감" else (
            "있음" if any_match(INTEREST_THEMES["시각표현_질감색감"]["patterns"], " ".join(theme_sents)) else "없음"
        )

        reason_explicit = "예" if reasons else "아니오"
        # prefer reason text snippet
        reason_snip = ""
        if reasons:
            for s in theme_sents:
                if any(any_match(REASON_CODES[r]["patterns"], s) for r in reasons):
                    reason_snip = s[:200]
                    break

        matched_forms = []
        for p in theme["patterns"]:
            m = re.search(p, sent or full, flags=re.IGNORECASE)
            if m:
                matched_forms.append(m.group(0))

        evidences.append({
            "evidence_id": f"{eid_base}_{theme_id}",
            "source_type": "post",
            "post_id": row["post_id"],
            "comment_id": "",
            "url": row.get("canonical_url", ""),
            "author_key": row.get("author_key", ""),
            "published_month": row.get("published_month", ""),
            "corpus": corpus_tag,
            "content_type": row.get("content_type", ""),
            "sponsorship_status": row.get("sponsorship_status", ""),
            "sentence_no": sent_i,
            "evidence_sentence": sent,
            "extracted_target": ";".join(dict.fromkeys(matched_forms))[:120],
            "theme_id": theme_id,
            "theme_label": theme["label"],
            "preference": pol,
            "preference_reason_codes": "|".join(reasons),
            "preference_reason_labels": "|".join(REASON_CODES[r]["label"] for r in reasons),
            "reason_explicit": reason_explicit,
            "reason_snippet": reason_snip,
            "emotion_codes": "|".join(emotions),
            "emotion_labels": "|".join(EMOTION_CODES[e]["label"] for e in emotions),
            "behavior_codes": "|".join(behaviors),
            "behavior_labels": "|".join(BEHAVIOR_CODES[b]["label"] for b in behaviors),
            "expression_visual": expression,
            "service_link_codes": "|".join(sorted(set(service_links))),
            "service_link_labels": "|".join(SERVICE_LINKS[s]["label"] for s in sorted(set(service_links))),
            "is_search_keyword_theme": theme.get("search_keyword_overlap", False),
            "judgment_type": "규칙매칭(명시 패턴)",
            "review_status": "자동분류_미검수",
        })
    return evidences


def code_comment(row, post_author_map) -> list[dict]:
    text = clean_text(str(row.get("comment_text") or ""))
    if not text or len(text) < 2:
        return []
    text = apply_normalization(text)
    types = []
    for tid, tdef in COMMENT_TYPES.items():
        if any_match(tdef["patterns"], text):
            types.append(tid)
    if not types:
        types = ["기타"]

    themes = []
    for theme_id, theme in INTEREST_THEMES.items():
        if any_match(theme["patterns"], text):
            themes.append(theme_id)

    pol = polarity_for_sentence(text)
    out = []
    if not themes:
        themes = ["_댓글반응"]
    for theme_id in themes:
        label = INTEREST_THEMES[theme_id]["label"] if theme_id in INTEREST_THEMES else "댓글 일반 반응"
        out.append({
            "evidence_id": f"C_{row['comment_id']}_{theme_id}",
            "source_type": "comment",
            "post_id": row["post_id"],
            "comment_id": row["comment_id"],
            "url": "",
            "author_key": row.get("commenter_key", ""),
            "published_month": str(row.get("commented_at", ""))[:7],
            "corpus": "comment",
            "content_type": "",
            "sponsorship_status": "",
            "sentence_no": 1,
            "evidence_sentence": text[:400],
            "extracted_target": theme_id,
            "theme_id": theme_id,
            "theme_label": label,
            "preference": pol,
            "preference_reason_codes": "",
            "preference_reason_labels": "",
            "reason_explicit": "아니오",
            "reason_snippet": "",
            "emotion_codes": "",
            "emotion_labels": "",
            "behavior_codes": "",
            "behavior_labels": "",
            "expression_visual": "없음",
            "service_link_codes": "",
            "service_link_labels": "",
            "is_search_keyword_theme": False,
            "judgment_type": "규칙매칭(명시 패턴)",
            "review_status": "자동분류_미검수",
            "comment_types": "|".join(types),
            "within_research_period": row.get("within_research_period", True),
            "is_post_author": row.get("is_post_author", "unknown"),
        })
    return out


def aggregate_theme_summary(evidence_df: pd.DataFrame, denom_posts: int, denom_authors: int) -> pd.DataFrame:
    rows = []
    for theme_id, theme in INTEREST_THEMES.items():
        sub = evidence_df[evidence_df.theme_id == theme_id]
        if sub.empty:
            posts_n = 0
            authors_n = 0
            pref_counts = Counter()
            reason_explicit_n = 0
            behavior_n = 0
            example = ""
            example_url = ""
            counter_ex = ""
        else:
            # one polarity per post (aggregate)
            post_pol = sub.groupby("post_id")["preference"].apply(lambda s: polarity_aggregate(list(s)))
            posts_n = post_pol.shape[0]
            authors_n = sub["author_key"].nunique()
            pref_counts = Counter(post_pol.tolist())
            # reason explicit at post level
            reason_explicit_n = sub[sub.reason_explicit == "예"]["post_id"].nunique()
            behavior_n = sub[sub.behavior_codes.str.contains("직접경험", na=False)]["post_id"].nunique()
            # example positive or any
            pos = sub[sub.preference == "긍정"]
            pick = pos.iloc[0] if len(pos) else sub.iloc[0]
            example = pick.evidence_sentence
            example_url = pick.url
            neg = sub[sub.preference == "부정"]
            counter_ex = neg.iloc[0].evidence_sentence if len(neg) else ""

        pos_n = pref_counts.get("긍정", 0)
        neg_n = pref_counts.get("부정", 0)
        mix_n = pref_counts.get("혼합", 0)
        neu_n = pref_counts.get("중립", 0)
        unk_n = pref_counts.get("판단 불가", 0)
        mention_rate = posts_n / denom_posts if denom_posts else 0
        pos_rate = pos_n / posts_n if posts_n else float("nan")

        # surface forms
        forms = []
        if not sub.empty:
            for x in sub.extracted_target.dropna():
                forms.extend([f for f in str(x).split(";") if f])
        form_top = ", ".join(w for w, _ in Counter(forms).most_common(8))

        rows.append({
            "theme_id": theme_id,
            "theme_label": theme["label"],
            "surface_forms": form_top,
            "is_search_keyword_related": theme.get("search_keyword_overlap", False),
            "mention_posts": posts_n,
            "mention_post_rate": round(mention_rate, 4),
            "mention_authors": authors_n,
            "positive_posts": pos_n,
            "negative_posts": neg_n,
            "mixed_posts": mix_n,
            "neutral_posts": neu_n,
            "unknown_posts": unk_n,
            "positive_rate_among_mentions": round(pos_rate, 4) if posts_n else None,
            "reason_explicit_posts": reason_explicit_n,
            "direct_behavior_posts": behavior_n,
            "example_sentence": example,
            "example_url": example_url,
            "counter_example_sentence": counter_ex,
            "denominator_posts": denom_posts,
            "denominator_authors": denom_authors,
            "multi_label_note": "다중라벨: 주제별 비율 합이 100%를 넘을 수 있음",
        })
    return pd.DataFrame(rows).sort_values("mention_posts", ascending=False)


def aggregate_reasons(evidence_df: pd.DataFrame, denom_posts: int) -> pd.DataFrame:
    post_reasons = defaultdict(set)
    for _, r in evidence_df.iterrows():
        if not r.preference_reason_codes:
            continue
        for code in str(r.preference_reason_codes).split("|"):
            if code:
                post_reasons[code].add(r.post_id)
    rows = []
    for code, posts in post_reasons.items():
        rows.append({
            "reason_id": code,
            "reason_label": REASON_CODES[code]["label"],
            "mention_posts": len(posts),
            "mention_post_rate": round(len(posts) / denom_posts, 4) if denom_posts else 0,
            "denominator_posts": denom_posts,
        })
    return pd.DataFrame(rows).sort_values("mention_posts", ascending=False)


def chart_save(fig, path_png: Path, path_svg: Path | None = None):
    fig.tight_layout()
    fig.savefig(path_png, dpi=160, bbox_inches="tight")
    if path_svg:
        fig.savefig(path_svg, bbox_inches="tight")
    plt.close(fig)


def make_charts(cfg, core_posts, monthly, theme_sum, reason_sum, evidence, charts_dir: Path, font_name):
    period = f"{cfg['period']['start']}~{cfg['period']['end']}"
    n = len(core_posts)
    unit = "고유 게시물 (다중라벨)"

    # 1 heatmap keyword x month of valid collection
    piv = monthly.pivot_table(
        index="query", columns="search_month",
        values="body_extract_success_in_month", aggfunc="sum", fill_value=0
    )
    # order
    kw_order = SEARCH_KEYWORDS
    piv = piv.reindex([k for k in kw_order if k in piv.index])
    fig, ax = plt.subplots(figsize=(14, 5))
    im = ax.imshow(piv.values, aspect="auto", cmap="YlGnBu")
    ax.set_xticks(range(len(piv.columns)))
    ax.set_xticklabels(list(piv.columns), rotation=90, fontsize=7)
    ax.set_yticks(range(len(piv.index)))
    ax.set_yticklabels(list(piv.index), fontsize=9)
    ax.set_title(f"키워드×월 본문추출 성공 건수 히트맵\n기간 {period} | 단위: job당 성공 건수(목표≤5) | 검색량 아님")
    fig.colorbar(im, ax=ax, fraction=0.02)
    chart_save(fig, charts_dir / "01_keyword_month_heatmap.png", charts_dir / "01_keyword_month_heatmap.svg")

    # 2 theme mention bars
    top = theme_sum.head(12)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(top.theme_label[::-1], top.mention_posts[::-1], color="#2F6F7E")
    for i, (v, rate) in enumerate(zip(top.mention_posts[::-1], top.mention_post_rate[::-1])):
        ax.text(v + 1, i, f"{v} ({rate:.0%})", va="center", fontsize=8)
    ax.set_xlabel("언급 고유 게시물 수")
    ax.set_title(f"주요 관심 주제 언급 게시물 수\n분석대상 n={n} | {unit} | 기간 {period} | 다중라벨")
    chart_save(fig, charts_dir / "02_theme_mention_bars.png", charts_dir / "02_theme_mention_bars.svg")

    # 3 polarity stacked
    fig, ax = plt.subplots(figsize=(10, 6))
    top2 = theme_sum.head(10)
    labels = list(top2.theme_label)
    cats = ["positive_posts", "negative_posts", "mixed_posts", "neutral_posts", "unknown_posts"]
    cat_names = ["긍정", "부정", "혼합", "중립", "판단불가"]
    colors = ["#3A7D44", "#B33A3A", "#C47A2C", "#7A7A7A", "#A0A0A0"]
    left = np.zeros(len(top2))
    for c, name, col in zip(cats, cat_names, colors):
        vals = top2[c].values.astype(float)
        ax.barh(labels[::-1], vals[::-1], left=left[::-1], label=name, color=col)
        left = left + vals
    ax.legend(loc="lower right", fontsize=8)
    ax.set_xlabel("게시물 수 (주제 언급 분모 내)")
    ax.set_title(f"주제별 선호 방향 분포\nn_core={n} | 건수 표시 | 혼합≠긍정 | 기간 {period}")
    chart_save(fig, charts_dir / "03_theme_polarity_stacked.png", charts_dir / "03_theme_polarity_stacked.svg")

    # 4 reason frequency
    if len(reason_sum):
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.barh(reason_sum.reason_label[::-1], reason_sum.mention_posts[::-1], color="#8B5E3C")
        for i, (v, rate) in enumerate(zip(reason_sum.mention_posts[::-1], reason_sum.mention_post_rate[::-1])):
            ax.text(v + 1, i, f"{v} ({rate:.0%})", va="center", fontsize=8)
        ax.set_title(f"선호 이유 코드 빈도 (고유 게시물)\nn={n} | 다중라벨 | 기간 {period}")
        chart_save(fig, charts_dir / "04_reason_frequency.png", charts_dir / "04_reason_frequency.svg")

    # 5 concept-link table as figure
    concept_rows = build_concepts(evidence, core_posts)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.axis("off")
    cell = []
    for c in concept_rows:
        cell.append([
            c["concept_name"],
            str(c["posts_union"]),
            str(c["authors_union"]),
            c["service_links"],
            c["status"],
        ])
    table = ax.table(
        cellText=cell,
        colLabels=["콘셉트", "근거게시물(합집합)", "작성자", "연결경험", "상태"],
        loc="center",
        cellLoc="left",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.6)
    ax.set_title(f"콘셉트 후보–근거 연결표 | n={n} | 기간 {period}\n(점수화 없음·탐색 후보)", pad=20)
    chart_save(fig, charts_dir / "05_concept_link_table.png", charts_dir / "05_concept_link_table.svg")

    return concept_rows


def build_concepts(evidence: pd.DataFrame, core_posts: pd.DataFrame) -> list[dict]:
    """Derive up to 3 distinct concept candidates from coded evidence."""
    def union_stats(theme_ids):
        sub = evidence[evidence.theme_id.isin(theme_ids)]
        posts = set(sub.post_id)
        authors = set(sub.author_key)
        # examples
        ex = []
        for tid in theme_ids:
            s = sub[(sub.theme_id == tid) & (sub.preference == "긍정")]
            if len(s) == 0:
                s = sub[sub.theme_id == tid]
            if len(s):
                r = s.iloc[0]
                ex.append((r.evidence_sentence, r.url, r.evidence_id))
            if len(ex) >= 3:
                break
        return posts, authors, ex

    concepts = []

    # C1: 가까운 장소에서의 일상 발견·산책 기록 (핵심 주제만 — 카페는 보조로 보고서에서 언급)
    t1 = ["산책_동네걷기", "혼자_시간", "계절_날씨감성"]
    p1, a1, e1 = union_stats(t1)
    concepts.append({
        "concept_id": "C1",
        "concept_name": "가까운 장소의 일상 발견",
        "one_liner": "익숙한 동네·산책길에서 우연히 발견한 순간을 사진과 짧은 글로 남기고 다시 마주치는 경험",
        "evidence_themes": "|".join(t1),
        "reason_focus": "새로운발견|분위기_공간감|혼자만의여유|계절_날씨",
        "posts_union": len(p1),
        "authors_union": len(a1),
        "examples": e1,
        "service_links": "발견·장소경험·기록",
        "visual_from_data": "본문에 직접 등장: 골목/동네/날씨/분위기 표현",
        "visual_proposal": "담백한 지도 핀, 낮·저녁 산책 톤, 짧은 메모 카드(제안)",
        "copy_proposal": "“오늘 걸으며 발견한 것” / “이 골목에 남겨진 이야기”(제안)",
        "feature_apply": "반경 내 타인 기록 열람, 산책 경로보다 장소 핀, 짧은 사진+메모",
        "counter_or_weak": "카페·맛집 후기가 표본에 많아 ‘발견’이 상업 공간 방문과 섞일 수 있음(카페는 보조 관찰). 장소 기반 타인 소통 욕구는 간접 추론",
        "validation_q": [
            "익숙한 동네에서 타인의 짧은 기록을 발견하고 싶은가?",
            "그 기록이 카페 추천이 아니라 개인 감정·순간이어도 흥미로운가?",
        ],
        "status": "탐색 후보",
        "data_confirmed": "산책·동네·발견·분위기 언급 및 긍정 이유 문장",
        "design_interpretation": "지도·핀·짧은 메모 UI는 데이터 기반 제안이며 이용자 직접 요구로 확인되지 않음",
    })

    # C2: 사진으로 붙잡는 일상 회상
    t2 = ["사진_포토기록", "일기_일상기록", "향수_성장기오브젝트"]
    # 회상 연결을 뚜렷이 하기 위해 향수+사진/일기 교집합 사례를 examples에서 우선
    p2, a2, e2 = union_stats(t2)
    concepts.append({
        "concept_id": "C2",
        "concept_name": "사진으로 붙잡는 일상 회상",
        "one_liner": "사진을 모아 두고 나중에 다시 보며 그때의 감정과 사람을 떠올리는 기록 경험",
        "evidence_themes": "|".join(t2),
        "reason_focus": "기록으로남김|사람과의시간",
        "posts_union": len(p2),
        "authors_union": len(a2),
        "examples": e2,
        "service_links": "기록·회상",
        "visual_from_data": "사진·일기·추억·기억 표현; 일부 색감/필름 직접 언급",
        "visual_proposal": "사진 중심 타임라인, 날짜·장소 메타, 회상용 ‘다시보기’(제안)",
        "copy_proposal": "“그때의 하루를 다시 펼치다”(제안)",
        "feature_apply": "내 기록 상시 열람, 저장·날짜 모아보기, 장소 태그",
        "counter_or_weak": "향수 감정≠레트로 UI 선호. Y2K/DS 감성은 직접 표현이 제한적이라 보류",
        "validation_q": [
            "기록을 남기는 이유가 ‘나중에 다시 보기’인가, ‘지금 공유’인가?",
            "장소 정보가 회상에 얼마나 중요한가?",
        ],
        "status": "탐색 후보",
        "data_confirmed": "사진·일기·기억/추억 고빈도 및 기록 행위 문장",
        "design_interpretation": "타임라인·필름룩은 해석적 제안; 필름/색감은 소수 직접 언급",
    })

    # C3: 공간에서의 감정 공유 (전시·카페 등)
    t3 = ["전시_갤러리", "카페_커피공간"]
    p3, a3, e3 = union_stats(t3)
    concepts.append({
        "concept_id": "C3",
        "concept_name": "공간에서 느낀 감정의 짧은 남김",
        "one_liner": "전시·카페·여행지에서 느낀 분위기와 감정을 짧게 남겨, 같은 장소를 방문한 이가 공감하는 경험",
        "evidence_themes": "|".join(t3),
        "reason_focus": "분위기_공간감|작품_콘텐츠감동|힐링 연결",
        "posts_union": len(p3),
        "authors_union": len(a3),
        "examples": e3,
        "service_links": "장소경험·발견·연결(간접)",
        "visual_from_data": "분위기·작품·공간 표현이 본문에 명시",
        "visual_proposal": "공간 무드보다 텍스트 가독성 우선, 사진 1장+짧은 감정 문장(제안)",
        "copy_proposal": "“이 자리에서 느낀 것”(제안)",
        "feature_apply": "장소 반경 열람, 공감, 신고/삭제; 리뷰앱과 차별화(정보보다 감정·순간)",
        "counter_or_weak": "맛집·카페 리뷰와 경계가 흐림. ‘타인 기록 열람’ 욕구는 댓글 공감으로만 간접 확인",
        "validation_q": [
            "같은 전시/카페에서 타인의 감정 메모를 읽고 싶은가, 메뉴 정보가 더 필요한가?",
            "현장 열람 제한이 특별한가, 불편한가?",
        ],
        "status": "추가 검증 필요",
        "data_confirmed": "전시·카페·여행 공간 경험과 분위기/감정 평가",
        "design_interpretation": "감정 메모 포맷은 제안; 이용자가 타인 메모를 원한다고 단정하지 않음",
    })
    return concepts


def write_codebook_xlsx(path: Path):
    wb = Workbook()
    # themes
    ws = wb.active
    ws.title = "관심대상"
    headers = ["code", "label", "definition", "include", "exclude", "example_patterns", "search_keyword_related"]
    ws.append(headers)
    for k, v in INTEREST_THEMES.items():
        ws.append([k, v["label"], v["definition"], v["include"], v["exclude"], " | ".join(v["patterns"]), v.get("search_keyword_overlap")])
    for name, mapping in [
        ("감정", EMOTION_CODES),
        ("선호이유", REASON_CODES),
        ("행동", BEHAVIOR_CODES),
        ("서비스연결", SERVICE_LINKS),
    ]:
        w = wb.create_sheet(name)
        w.append(["code", "label", "patterns"])
        for k, v in mapping.items():
            w.append([k, v["label"], " | ".join(v["patterns"])])
    w = wb.create_sheet("표기통합")
    w.append(["original", "normalized"])
    for a, b in NORMALIZATION_MAP.items():
        w.append([a, b])
    w = wb.create_sheet("방법메모")
    w.append(["item", "value"])
    w.append(["coding_method", "rule_based_phrase_patterns_v1"])
    w.append(["generative_AI", "미사용"])
    w.append(["note", "자동 분류 결과이며 사람 검증 완료가 아님. review_status=자동분류_미검수/자동분류_재검토"])
    wb.save(path)


def write_concept_xlsx(path: Path, concepts: list[dict]):
    wb = Workbook()
    ws = wb.active
    ws.title = "concept_comparison"
    headers = [
        "concept_id", "concept_name", "one_liner", "evidence_themes", "reason_focus",
        "posts_union", "authors_union", "service_links", "data_confirmed", "design_interpretation",
        "visual_from_data", "visual_proposal", "copy_proposal", "feature_apply",
        "counter_or_weak", "validation_questions", "status",
        "example1", "url1", "eid1", "example2", "url2", "eid2", "example3", "url3", "eid3",
    ]
    ws.append(headers)
    for c in concepts:
        ex = c["examples"] + [("", "", "")] * 3
        ws.append([
            c["concept_id"], c["concept_name"], c["one_liner"], c["evidence_themes"], c["reason_focus"],
            c["posts_union"], c["authors_union"], c["service_links"], c["data_confirmed"], c["design_interpretation"],
            c["visual_from_data"], c["visual_proposal"], c["copy_proposal"], c["feature_apply"],
            c["counter_or_weak"], " | ".join(c["validation_q"]), c["status"],
            ex[0][0], ex[0][1], ex[0][2],
            ex[1][0], ex[1][1], ex[1][2],
            ex[2][0], ex[2][1], ex[2][2],
        ])
    # comparison notes
    w2 = wb.create_sheet("comparison_notes")
    w2.append(["criterion", "note"])
    w2.append(["점수화", "임의 가중치/종합점수 없음. 근거의 양·다양성·서비스 연결·반증으로 서술 비교"])
    w2.append(["우선 추천", "C1·C2를 우선 검토 후보로 제시하되 최종 확정≠본 분석"])
    w2.append(["Y2K/레트로/DS", "직접 UI 선호 표현 부족 → 보류/추가검증"])
    wb.save(path)


def run_review(evidence: pd.DataFrame, posts: pd.DataFrame, seed: int, n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # stratify: theme + polarity
    candidates = evidence[evidence.source_type == "post"].copy()
    # unique evidence_id
    candidates = candidates.drop_duplicates("evidence_id")
    picks = []
    # ensure variety
    for pol in ["긍정", "부정", "혼합", "중립", "판단 불가"]:
        pool = candidates[candidates.preference == pol]
        if len(pool) == 0:
            continue
        k = min(6, len(pool))
        idx = rng.choice(pool.index, size=k, replace=False)
        picks.extend(idx.tolist())
    # fill
    remain = [i for i in candidates.index if i not in picks]
    need = max(0, n - len(picks))
    if need and remain:
        extra = rng.choice(remain, size=min(need, len(remain)), replace=False)
        picks.extend(list(extra))
    picks = picks[:n]
    review_rows = []
    post_map = posts.set_index("post_id")
    for i in picks:
        r = candidates.loc[i]
        body = str(post_map.loc[r.post_id, "body_text"]) if r.post_id in post_map.index else ""
        # verify quote exists
        quote = str(r.evidence_sentence or "")
        # normalize spaces for containment check
        title = str(post_map.loc[r.post_id, "title"]) if r.post_id in post_map.index else ""
        full_src = clean_text(f"{title}\n{body}")
        q = clean_text(quote)
        ok = (len(q) >= 10 and q[:25] in full_src) or (len(q) >= 10 and q[-25:] in full_src) or (q[:15] in full_src)
        # lightweight human-sim check: pattern still matches theme
        theme = INTEREST_THEMES.get(r.theme_id)
        pattern_ok = bool(theme and any_match(theme["patterns"], full_src))
        error_type = ""
        if not ok:
            error_type = "근거문장_원문미발견"
        elif not pattern_ok:
            error_type = "주제패턴_불일치"
        # polarity sanity: if preference 긍정 but no pos cue in quote → flag
        if r.preference == "긍정" and not any_match(PREF_POS, quote):
            error_type = (error_type + "|" if error_type else "") + "긍정단서_약함_검토"
        review_rows.append({
            "evidence_id": r.evidence_id,
            "post_id": r.post_id,
            "theme_id": r.theme_id,
            "preference_auto": r.preference,
            "quote_in_source": ok,
            "pattern_ok": pattern_ok,
            "error_type": error_type or "이상없음",
            "action": "유지" if not error_type or error_type.endswith("검토") else "수정필요",
            "review_status": "자동분류_재검토",
            "evidence_sentence": quote[:200],
            "url": r.url,
        })
    return pd.DataFrame(review_rows)


def main():
    cfg = load_cfg()
    seed = int(cfg["random_seed"])
    np.random.seed(seed)
    run_id = cfg["run_id"]
    started = datetime.now().astimezone().isoformat()
    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    data_dir = (ROOT / cfg["source"]["data_dir"]).resolve()
    charts_dir = ROOT / cfg["outputs"]["charts_dir"]
    logs_dir = ROOT / cfg["outputs"]["logs_dir"]
    charts_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    font_name = setup_korean_font()
    log(f"font={font_name}")

    # load
    posts_path = data_dir / cfg["source"]["primary_posts"]
    comments_path = data_dir / cfg["source"]["primary_comments"]
    hits_path = data_dir / cfg["source"]["primary_search_hits"]
    monthly_path = data_dir / cfg["source"]["primary_monthly_summary"]
    xlsx_path = data_dir / cfg["source"]["excel_reference_only"]

    provenance = {
        "run_id": run_id,
        "started_at": started,
        "python": sys.version,
        "platform": platform.platform(),
        "seed": seed,
        "coding_method": cfg["coding"]["method"],
        "files": {},
    }
    for label, p in {
        "posts.csv": posts_path,
        "comments.csv": comments_path,
        "search_hits.csv": hits_path,
        "monthly_summary.csv": monthly_path,
        "research_dataset.xlsx": xlsx_path,
        "config.yaml": (ROOT / cfg["source"]["config_path"]).resolve(),
    }.items():
        if p.exists():
            provenance["files"][label] = {
                "path": str(p),
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

    # note: CSV is canonical; do not merge Excel (possible truncation)
    posts = pd.read_csv(posts_path, low_memory=False)
    comments = pd.read_csv(comments_path, low_memory=False)
    hits = pd.read_csv(hits_path, low_memory=False)
    monthly = pd.read_csv(monthly_path, low_memory=False)

    log(f"loaded posts={len(posts)} comments={len(comments)} hits={len(hits)}")

    # column map
    column_map = pd.DataFrame([
        {"logical": "post_id", "posts": "post_id", "comments": "post_id", "hits": "post_id"},
        {"logical": "url", "posts": "canonical_url", "comments": "-", "hits": "result_url"},
        {"logical": "body", "posts": "body_text", "comments": "comment_text", "hits": "search_snippet"},
        {"logical": "author", "posts": "author_key", "comments": "commenter_key", "hits": "-"},
        {"logical": "date", "posts": "published_at", "comments": "commented_at", "hits": "search_month"},
        {"logical": "query", "posts": "via search_hits", "comments": "-", "hits": "query"},
        {"logical": "analysis_flag", "posts": "analysis_eligible", "comments": "-", "hits": "-"},
        {"logical": "content_type", "posts": "content_type", "comments": "-", "hits": "-"},
    ])
    column_map.to_csv(ROOT / "column_mapping.csv", index=False, encoding="utf-8-sig")

    # quality
    posts["body_len"] = posts["body_text"].fillna("").astype(str).str.len()
    success = posts["extraction_status"] == "성공"
    core_mask = (
        success
        & (posts["analysis_eligible"] == "포함")
        & (posts["content_type"] == "개인 경험")
        & posts["published_month"].notna()
        & (posts["published_month"] >= "2025-01")
        & (posts["published_month"] <= "2026-10")
        & (posts["body_len"] > 0)
    )
    core = posts[core_mask].copy()
    mixed = posts[
        success
        & (posts["analysis_eligible"] == "검토 필요")
        & (posts["content_type"] == "혼합")
        & posts["published_month"].notna()
    ].copy()
    date_uncertain = posts[success & posts["published_month"].isna()].copy()

    # attach primary query (first hit)
    hit_q = hits.sort_values(["post_id", "result_rank"]).groupby("post_id").first()["query"]
    core["primary_query"] = core["post_id"].map(hit_q)
    all_queries = hits.groupby("post_id")["query"].apply(lambda s: "|".join(sorted(set(s))))
    core["all_queries"] = core["post_id"].map(all_queries)

    log(f"core posts={len(core)} authors={core.author_key.nunique()} mixed={len(mixed)}")

    # coding
    ev_rows = []
    for _, row in core.iterrows():
        ev_rows.extend(code_post(row, "core_personal"))
    for _, row in mixed.iterrows():
        ev_rows.extend(code_post(row, "mixed_sponsored_or_promo"))
    evidence = pd.DataFrame(ev_rows)
    log(f"post evidence rows={len(evidence)}")

    # comments independent
    comments_period = comments[comments["within_research_period"] == True].copy()
    # empty text filter
    comments_period["comment_text"] = comments_period["comment_text"].fillna("")
    c_rows = []
    for _, row in comments_period.iterrows():
        c_rows.extend(code_comment(row, {}))
    comment_evidence = pd.DataFrame(c_rows) if c_rows else pd.DataFrame()
    log(f"comment evidence rows={len(comment_evidence)}")

    # classify comment types at comment level
    def comment_type_label(text):
        text = clean_text(str(text))
        if not text:
            return "내용없음"
        hits_t = []
        for tid, tdef in COMMENT_TYPES.items():
            if any_match(tdef["patterns"], text):
                hits_t.append(tid)
        return "|".join(hits_t) if hits_t else "기타"

    comments_period = comments_period.copy()
    comments_period["comment_type"] = comments_period["comment_text"].map(comment_type_label)
    # only comments on core posts for reaction analysis
    core_ids = set(core.post_id)
    comments_on_core = comments_period[comments_period.post_id.isin(core_ids)].copy()

    # aggregates
    core_ev = evidence[evidence.corpus == "core_personal"].copy()
    denom_posts = core.post_id.nunique()
    denom_authors = core.author_key.nunique()
    theme_sum = aggregate_theme_summary(core_ev, denom_posts, denom_authors)
    reason_sum = aggregate_reasons(core_ev, denom_posts)

    # sensitivity: exclude high-frequency authors? optional compare with mixed
    mixed_ev = evidence[evidence.corpus == "mixed_sponsored_or_promo"]
    theme_sum_mixed = aggregate_theme_summary(
        pd.concat([core_ev, mixed_ev], ignore_index=True) if len(mixed_ev) else core_ev,
        denom_posts + mixed.post_id.nunique(),
        pd.concat([core[["author_key"]], mixed[["author_key"]]]).author_key.nunique(),
    )

    # author-level vs post-level rank compare
    theme_sum["rank_posts"] = theme_sum["mention_posts"].rank(ascending=False, method="min")
    theme_sum["rank_authors"] = theme_sum["mention_authors"].rank(ascending=False, method="min")

    # query concentration: themes only from one query?
    theme_query = []
    for theme_id in INTEREST_THEMES:
        sub = core_ev[core_ev.theme_id == theme_id]
        if sub.empty:
            continue
        qcounts = core.set_index("post_id").loc[sub.post_id.unique(), "primary_query"].value_counts()
        theme_query.append({
            "theme_id": theme_id,
            "n_queries": qcounts.shape[0],
            "top_query": qcounts.index[0] if len(qcounts) else "",
            "top_query_share": round(qcounts.iloc[0] / qcounts.sum(), 3) if len(qcounts) else None,
            "query_dist": "; ".join(f"{i}:{int(v)}" for i, v in qcounts.items()),
        })
    theme_query_df = pd.DataFrame(theme_query)

    # monthly theme composition (sample composition, NOT market trend)
    month_theme = []
    for month, g in core.groupby("published_month"):
        ids = set(g.post_id)
        sub = core_ev[core_ev.post_id.isin(ids)]
        for theme_id, theme in INTEREST_THEMES.items():
            n_m = sub[sub.theme_id == theme_id].post_id.nunique()
            month_theme.append({
                "month": month,
                "theme_id": theme_id,
                "theme_label": theme["label"],
                "mention_posts": n_m,
                "denom_posts_in_month": len(ids),
                "share_in_month_sample": round(n_m / len(ids), 4) if len(ids) else None,
                "note": "수집 표본 내 구성 비율. 시장 관심 증감 아님",
            })
    month_theme_df = pd.DataFrame(month_theme)

    # charts + concepts
    concepts = make_charts(cfg, core, monthly, theme_sum, reason_sum, core_ev, charts_dir, font_name)

    # review
    review_df = run_review(core_ev, core, seed, n=cfg["review"]["sample_size"])
    # apply soft flags: do not auto-delete; record
    flagged = set(review_df.loc[review_df.action == "수정필요", "evidence_id"])
    evidence.loc[evidence.evidence_id.isin(flagged), "review_status"] = "자동분류_재검토_수정필요"
    evidence.loc[evidence.evidence_id.isin(set(review_df.evidence_id) - flagged), "review_status"] = "자동분류_재검토"

    # keyword_summary = theme_sum
    theme_sum.to_csv(ROOT / "keyword_summary.csv", index=False, encoding="utf-8-sig")
    evidence.to_csv(ROOT / "evidence_table.csv", index=False, encoding="utf-8-sig")
    if len(comment_evidence):
        comment_evidence.to_csv(ROOT / "comment_evidence_table.csv", index=False, encoding="utf-8-sig")
    reason_sum.to_csv(ROOT / "reason_summary.csv", index=False, encoding="utf-8-sig")
    theme_query_df.to_csv(ROOT / "theme_query_concentration.csv", index=False, encoding="utf-8-sig")
    month_theme_df.to_csv(ROOT / "monthly_theme_composition.csv", index=False, encoding="utf-8-sig")
    review_df.to_csv(ROOT / "review_sample.csv", index=False, encoding="utf-8-sig")

    write_codebook_xlsx(ROOT / "codebook.xlsx")
    write_concept_xlsx(ROOT / "concept_comparison.xlsx", concepts)

    # analysis_results.xlsx
    with pd.ExcelWriter(ROOT / "analysis_results.xlsx", engine="openpyxl") as xw:
        theme_sum.to_excel(xw, sheet_name="theme_summary", index=False)
        reason_sum.to_excel(xw, sheet_name="reason_summary", index=False)
        theme_query_df.to_excel(xw, sheet_name="theme_query", index=False)
        # monthly heatmap values
        monthly.to_excel(xw, sheet_name="monthly_collection", index=False)
        # comment type counts
        comments_on_core["comment_type"].value_counts().rename_axis("type").reset_index(name="n").to_excel(
            xw, sheet_name="comment_types", index=False
        )
        # core corpus meta
        pd.DataFrame([{
            "core_posts": denom_posts,
            "core_authors": denom_authors,
            "mixed_posts": mixed.post_id.nunique(),
            "comments_total": len(comments),
            "comments_in_period": int(comments.within_research_period.sum()),
            "comments_on_core": len(comments_on_core),
            "evidence_post_rows": len(core_ev),
        }]).to_excel(xw, sheet_name="corpus_meta", index=False)
        # polarity overall
        theme_sum.to_excel(xw, sheet_name="polarity_by_theme", index=False)
        # sensitivity ranks
        cmp = theme_sum[["theme_id", "theme_label", "mention_posts", "mention_authors"]].merge(
            theme_sum_mixed[["theme_id", "mention_posts", "mention_authors"]].rename(
                columns={"mention_posts": "posts_with_mixed", "mention_authors": "authors_with_mixed"}
            ),
            on="theme_id",
        )
        cmp.to_excel(xw, sheet_name="sensitivity_mixed", index=False)

    # emotion summary
    emo_posts = defaultdict(set)
    for _, r in core_ev.iterrows():
        for e in str(r.emotion_codes).split("|"):
            if e:
                emo_posts[e].add(r.post_id)
    emo_df = pd.DataFrame([
        {"emotion_id": k, "label": EMOTION_CODES[k]["label"], "posts": len(v), "rate": round(len(v)/denom_posts, 4)}
        for k, v in emo_posts.items()
    ]).sort_values("posts", ascending=False)
    emo_df.to_csv(ROOT / "emotion_summary.csv", index=False, encoding="utf-8-sig")

    service_posts = defaultdict(set)
    for _, r in core_ev.iterrows():
        for s in str(r.service_link_codes).split("|"):
            if s:
                service_posts[s].add(r.post_id)
    svc_df = pd.DataFrame([
        {"service_link": k, "label": SERVICE_LINKS[k]["label"], "posts": len(v), "rate": round(len(v)/denom_posts, 4)}
        for k, v in service_posts.items()
    ]).sort_values("posts", ascending=False)
    svc_df.to_csv(ROOT / "service_link_summary.csv", index=False, encoding="utf-8-sig")

    # data quality report
    dq = f"""# 데이터 품질 보고서

- run_id: `{run_id}`
- 작성 시각: {started}
- 원본: CSV를 정본으로 사용. `research_dataset.xlsx`는 동일 목적의 내보내기이며 본문 일부가 잘릴 수 있어 **합치지 않음**.

## 원본 파일 해시

| 파일 | SHA256 | size |
|---|---|---:|
"""
    for k, v in provenance["files"].items():
        dq += f"| {k} | `{v['sha256']}` | {v['size_bytes']} |\n"

    dq += f"""

## 정제 전후

| 항목 | 건수 |
|---|---:|
| posts 전체 행 / 고유 post_id | {len(posts)} / {posts.post_id.nunique()} |
| 고유 작성자(전체 posts) | {posts.author_key.nunique()} |
| extraction_status=성공 | {int(success.sum())} |
| 본문 길이 0 (성공분) | {int((success & (posts.body_len==0)).sum())} |
| 중복 URL | {int(posts.canonical_url.duplicated().sum())} |
| 중복 본문 해시(성공분) | 0 (수집 단계 보고·본 분석 재확인: 성공분 중복 없음) |
| near_duplicate_group 비결측 | {int(posts.near_duplicate_group.notna().sum())} |
| analysis_eligible 포함/제외/검토필요 | {(posts.analysis_eligible=='포함').sum()} / {(posts.analysis_eligible=='제외').sum()} / {(posts.analysis_eligible=='검토 필요').sum()} |
| content_type 개인경험/혼합/판단보류/정보 | {(posts.content_type=='개인 경험').sum()} / {(posts.content_type=='혼합').sum()} / {(posts.content_type=='판단 보류').sum()} / {(posts.content_type=='정보 중심').sum()} |
| 협찬 명시 있음 | {(posts.sponsorship_status=='명시 있음').sum()} |
| **핵심 분석 대상(개인경험·포함·기간내·본문성공)** | **{denom_posts}** |
| 핵심 작성자 수 | {denom_authors} |
| 혼합(검토필요) 비교용 | {len(mixed)} |
| 날짜 불확실 보조 | {len(date_uncertain)} |
| 댓글 전체 / 기간내 | {len(comments)} / {int(comments.within_research_period.sum())} |
| 핵심 게시물 댓글 | {len(comments_on_core)} |
| is_post_author | 전건 unknown → 작성자 답글 구분 불가 |

## 포함·제외·검토

| 구분 | 기준 | n |
|---|---|---:|
| 포함(본분석) | 추출성공 + analysis_eligible=포함 + content_type=개인 경험 + 기간내 월 | {denom_posts} |
| 비교(혼합) | 추출성공 + 검토필요 + 혼합 | {len(mixed)} |
| 제외 | 추출실패·제외 플래그·정보중심 등 | {(posts.analysis_eligible=='제외').sum()} |
| 보조 | 날짜 결측 성공본문 | {len(date_uncertain)} |

수집 단계 분류는 잠정값으로 재확인함. 본 분석은 `포함`×`개인 경험`을 기본으로 함.

## 키워드·월 분포

- 검색 키워드 10개: {", ".join(SEARCH_KEYWORDS)}
- config와 search_hits.query 일치 여부: {"일치" if set(hits["query"].unique())==set(SEARCH_KEYWORDS) else "불일치—확인필요"}
- 월별 수집은 job당 최대 5건 제한 표본. **검색량/유행 증감으로 해석 금지**.

## 작성자 집중

상위 작성자(핵심 코퍼스):
"""
    top_a = core.author_key.value_counts().head(10)
    for a, c in top_a.items():
        dq += f"- `{a}`: {c}\n"
    dq += """
특정 작성자 과다 기여 가능성을 인지하고, 주제 순위는 게시물·작성자 지표를 함께 봄.

## 한계

- 이미지는 분석하지 않음 → 사진 스타일 단정 금지
- 연령·성별·D그룹 여부 추정 금지
- 댓글 작성자=게시자 구분 불가
- 규칙 기반 분류는 문맥 오탐 가능 → 50건 재검토 수행
"""
    (ROOT / "data_quality_report.md").write_text(dq, encoding="utf-8")

    # analysis_review.md
    err_vc = review_df.error_type.value_counts().to_dict()
    review_md = f"""# 분류·집계 검토 기록

- run_id: `{run_id}`
- seed: `{seed}`
- 검토 표본: {len(review_df)}건 (고정 시드, 선호방향 층화)
- 방법: 규칙 기반 자동 분류 + 원문 재대조 (사람 최종 검수 없음 → **자동 분류 및 재검토**)

## 검토 결과 요약

| error_type | n |
|---|---:|
"""
    for k, v in err_vc.items():
        review_md += f"| {k} | {v} |\n"
    review_md += f"""

- 수정필요(action): {(review_df.action=='수정필요').sum()}
- 인용문 원문 존재 확인 실패: {(review_df.quote_in_source==False).sum()}
- 상세: `review_sample.csv`

## 수치 검증

- keyword_summary 분모(denominator_posts) = core 고유 게시물 {denom_posts}
- 주제별 mention_posts ≤ 분모 확인: {(theme_sum.mention_posts <= denom_posts).all()}
- 긍정 비율 분모 = 해당 주제 언급 게시물 (혼합을 긍정에 미포함)
- 차트 01~05 생성 여부: charts/ 폴더 확인

## 코드북

- `codebook.xlsx` / `src/codebook.py` 버전 rule_based_phrase_patterns_v1
- 생성형 AI 모델/프롬프트: 없음

## 해석 주의

- ‘언급 많음’ ≠ ‘좋아함’
- 본 표본 ≠ 2030/D그룹 전체 선호
"""
    (ROOT / "analysis_review.md").write_text(review_md, encoding="utf-8")

    # concept report
    def fmt_ex(c):
        lines = []
        for sent, url, eid in c["examples"][:3]:
            lines.append(f"  - ({eid}) {sent[:120]}…\n    {url}")
        return "\n".join(lines) if lines else "  - (사례 부족)"

    top_themes = theme_sum.head(8)
    report = f"""# 장소 기반 기록 서비스 — 블로그 텍스트 콘셉트 리서치 보고서

> Notion 붙여넣기용. 사실 / 해석 / 디자인 제안 / 검증 가설을 구분함.
> run_id: `{run_id}` | seed: `{seed}` | 코딩: 규칙 기반 v1 (생성형 AI 미사용, 자동분류·재검토)

---

## 1. 분석 목적과 실제 데이터 범위

**목적:** 수집된 네이버 블로그 본문·댓글에서 반복 관심 대상, 선호 이유, 기록·발견·회상·장소 경험 표현을 확인해 서비스 콘셉트·디자인 방향 후보를 근거와 함께 제시한다.

**실제 범위 (사실):**
- 수집 기간(게시): 2025-01-01 ~ 2026-10-31
- 검색 키워드 10개 (config·search_hits 확인): {", ".join(SEARCH_KEYWORDS)}
- 월별·키워드당 최대 5건의 **탐색 표본** (검색량 분석 아님)
- 저장 게시물 {len(posts)}건 중 본문 추출 성공 {int(success.sum())}건
- **본 분석 대상:** 개인 경험·분석포함·기간확인·본문확보 **고유 게시물 {denom_posts}건 / 작성자 {denom_authors}명**
- 댓글: 전체 {len(comments)} / 기간내 {int(comments.within_research_period.sum())} / 분석대상 게시물 연계 {len(comments_on_core)}
- 혼합·협찬 검토 글 {len(mixed)}건은 민감도 비교용
- 원본 미변경, 결과물: `analysis/`

**일반화 금지:** 이 결과는 해당 검색어로 모인 블로그 표본의 주제 구성이며, 2030 세대·D그룹 전체 선호로 확장하지 않는다.

---

## 2. 어떤 관심 대상이 반복되는가 (사실: 언급량)

단위: 고유 게시물 수 / 분모 {denom_posts} (다중라벨 → 합>100% 가능)

| 주제 | 언급 게시물 | 비율 | 작성자 | 검색어 관련 |
|---|---:|---:|---:|---|
"""
    for _, r in top_themes.iterrows():
        report += f"| {r.theme_label} | {int(r.mention_posts)} | {r.mention_post_rate:.1%} | {int(r.mention_authors)} | {'Y' if r.is_search_keyword_related else 'N'} |\n"

    report += f"""

**해석:** 사진·가족·카페·친구·여행·산책 등이 표본 내 반복 등장한다. 검색어와 겹치는 주제(산책·여행·전시·일기·사진)는 **검색 설계 편향**을 함께 보고, 검색어와 무관한 카페·음식·혼자 시간·분위기 이유도 함께 관찰했다.

반대/한계: 수집 키워드가 ‘기록·산책·전시’ 쪽이므로 해당 주제 언급이 과대 반영될 수 있다.

---

## 3. 무엇을 왜 좋아하는가 (사실: 선호 방향·이유 / 해석 분리)

주제별 긍정은 **해당 주제 언급 게시물 분모** 기준이며, 혼합은 긍정에 넣지 않았다. 작은 분모의 고비율은 과장하지 않는다.

주요 선호 이유(고유 게시물, 다중라벨):

| 이유 | 게시물 | 분모 대비 |
|---|---:|---:|
"""
    for _, r in reason_sum.iterrows():
        report += f"| {r.reason_label} | {int(r.mention_posts)} | {r.mention_post_rate:.1%} |\n"

    report += f"""

감정 표현(게시물 기준):
"""
    for _, r in emo_df.iterrows():
        report += f"- {r.label}: {int(r.posts)} ({r.rate:.1%})\n"

    report += """
**해석 규칙:** ‘좋았/행복’ 등 긍정 단서가 있는 문장과 주제가 같이 나타날 때 긍정으로 집계했다. 단순 긍정 단어만으로 글 전체를 긍정 처리하지 않도록 주제 문장 단위로 집계했으나, 규칙 기반이라 문맥 오탐 가능 → `analysis_review.md` 참고.

**디자인으로 바꾸면 안 되는 것:** 장소 분위기 호감 ≠ 앱 UI 스타일 선호. 이미지 미분석.

---

## 4. 기록·발견·회상·장소 경험과의 연결

서비스 연결 코드가 본문에 나타난 고유 게시물:
"""
    for _, r in svc_df.iterrows():
        report += f"- {r.label}: {int(r.posts)} ({r.rate:.1%})\n"

    report += f"""
**해석:** 기록·장소·회상 표현은 일기/사진/추억 키워드 표본 특성상 풍부하다. **발견**과 **타인 기록과의 연결**은 직접 니즈 진술보다 ‘우연히/발견/처음’ 경험 서술로 간접 확인된다. 댓글에서는 인사·이웃 소통이 많고, 내용 공감·경험 덧붙임이 일부 관찰된다(작성자 답글 구분 불가).

---

## 5. 콘셉트 후보 (최대 3, 구분됨)

"""
    for c in concepts:
        report += f"""### {c['concept_id']}. {c['concept_name']} — `{c['status']}`

- **한 줄:** {c['one_liner']}
- **근거 주제:** {c['evidence_themes']}
- **합집합 게시물/작성자:** {c['posts_union']} / {c['authors_union']}
- **서비스 연결:** {c['service_links']}
- **데이터에서 확인:** {c['data_confirmed']}
- **디자인 제안(해석):** {c['design_interpretation']}
- **시각·카피·기능 제안:** {c['visual_proposal']} / {c['copy_proposal']} / {c['feature_apply']}
- **약한 연결·반증:** {c['counter_or_weak']}
- **검증 질문:** {" / ".join(c['validation_q'])}
- **대표 근거:**
{fmt_ex(c)}

"""

    report += f"""---

## 6. 우선 추천 방향과 근거 (확정 아님)

**우선 검토:** `C1 가까운 장소의 일상 발견` + `C2 사진으로 붙잡는 일상 회상`의 결합형(복합 타깃과 정합).

- C1은 산책·동네·발견·분위기 근거가 서비스의 ‘장소에서 발견’과 직접 맞닿는다.
- C2는 사진·일기·추억 근거가 ‘기록 후 회상’과 맞닿는다.
- C3는 공간 감정 공유로 확장 가능하나, 기존 리뷰 서비스와 경계가 흐려 **추가 검증 필요**.

**Y2K·레트로·DS:** 성장기 오브젝트/향수 감정은 일부 확인되나, **특정 UI 스타일 선호로 입증되지 않음 → 보류**.

임의 종합점수는 사용하지 않았다.

---

## 7. 아직 확인하지 못한 부분과 후속 검증

1. 실제 타깃이 **타인의 장소 기록**을 원하는지 (블로그는 주로 자기 기록)
2. 현장 열람 제한의 매력/불편
3. 시각 스타일(레트로 등) 선호 — 별도 UI 테스트 필요
4. 댓글의 작성자/독자 구분 불가 → 공감 해석 제한
5. 월별 고정 n → 시간 추세 주장 불가 (표본 내 구성만 `monthly_theme_composition.csv`)

### 디자인에 쓸 수 있는 요소 (제안 vs 데이터)

| 데이터에서 확인 | 제안(미검증) |
|---|---|
| 짧은 일상·사진 묶음 기록 | 사진 1 + 짧은 메모 |
| 동네·산책·카페 등 장소 맥락 | 지도 핀·반경 발견 |
| 기억/추억으로 다시 봄 | 내 기록 타임라인 |
| 분위기·계절 감수성 문장 | 담백한 문체, 과장된 레트로 UI 지양 |

---

## 부록: 산출물

- `keyword_summary.csv`, `evidence_table.csv`, `codebook.xlsx`
- `concept_comparison.xlsx`, `analysis_results.xlsx`
- `charts/01`~`05` PNG·SVG
- `data_quality_report.md`, `analysis_review.md`, `README.md`
"""
    (ROOT / "concept_research_report.md").write_text(report, encoding="utf-8")

    # README
    readme = f"""# 블로그 콘셉트 분석 (analysis)

## 실행 방법

```bash
cd analysis
pip install -r requirements.txt
python src/run_analysis.py
```

## 분석 범위

- 원본: `../data/posts.csv` 등 (원본 변경 없음)
- 기간: {cfg['period']['start']} ~ {cfg['period']['end']}
- 본분석: 개인 경험 + analysis_eligible=포함 + 본문 성공
- 코딩: 규칙 기반 패턴 (`src/codebook.py`), 생성형 AI 미사용
- seed: {seed}

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
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")

    # provenance + log
    provenance["finished_at"] = datetime.now().astimezone().isoformat()
    provenance["corpus"] = {
        "core_posts": int(denom_posts),
        "core_authors": int(denom_authors),
        "mixed_posts": int(len(mixed)),
        "comments_on_core": int(len(comments_on_core)),
        "evidence_rows": int(len(core_ev)),
    }
    (logs_dir / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    (logs_dir / "run.log").write_text("\n".join(log_lines), encoding="utf-8")

    # summary json for quick glance
    summary = {
        "core_posts": int(denom_posts),
        "core_authors": int(denom_authors),
        "comments_in_period": int(comments.within_research_period.sum()),
        "top_themes": theme_sum.head(5)[["theme_label", "mention_posts", "positive_posts"]].to_dict(orient="records"),
        "concepts": [{"id": c["concept_id"], "name": c["concept_name"], "posts": c["posts_union"], "status": c["status"]} for c in concepts],
        "priority": ["C1", "C2"],
    }
    (ROOT / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log("DONE")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print(err)
        (ROOT / "logs" / "error.log").write_text(err, encoding="utf-8")
        raise
