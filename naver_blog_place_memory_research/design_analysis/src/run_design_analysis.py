#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
네이버 블로그 텍스트 → 시각·디자인 단서 추출 및 디자인 브리프 생성
규칙 기반 (생성형 AI 분류 미사용). 원본 data/ 는 수정하지 않음.
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
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows

sys.path.insert(0, str(Path(__file__).resolve().parent))
from design_codebook import (
    ALL_DIMENSIONS,
    COMMENT_DESIGN_PATTERNS,
    DESIGN_ELEMENTS,
    NORMALIZATION_MAP,
    PREF_NEG,
    PREF_POS,
    REASON_CODES,
    SEARCH_KEYWORDS,
)

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "analysis_config.json"
DATA_DIR = ROOT.parent / "data"


def load_cfg() -> dict:
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def setup_korean_font():
    candidates = ["Malgun Gothic", "맑은 고딕", "NanumGothic", "AppleGothic", "Noto Sans CJK KR"]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = name
            plt.rcParams["axes.unicode_minus"] = False
            return name
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
    parts = re.split(
        r"(?<=[\.!?。…\n])\s+|(?<=요)\s+(?=[가-힣A-Z])|(?<=다)\s+(?=[가-힣A-Za-z0-9])",
        text,
    )
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


def guarded_search(elem: dict, text: str) -> re.Match | None:
    guards = elem.get("false_positive_guards") or []
    for p in elem["patterns"]:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            window = text[max(0, m.start() - 30) : min(len(text), m.end() + 30)]
            if any(re.search(g, window, flags=re.IGNORECASE) for g in guards):
                continue
            return m
    return None


def polarity_for_sentence(sent: str, element_id: str | None = None) -> str:
    pos = bool(any_match(PREF_POS, sent))
    neg = bool(any_match(PREF_NEG, sent))
    # 네컷·필름 등: 인물 귀여움만 있으면 형식 선호로 보지 않음
    if element_id in {"photo_booth_strip", "texture_film_grain", "photo_collage_dump"}:
        strong_pos = bool(
            re.search(
                r"(?:만족|좋았|좋더|좋아|맘에\s*들|마음에\s*들|예쁘|이쁘|느좋|잘\s*나|추천|최고)",
                sent,
                flags=re.IGNORECASE,
            )
        )
        # 귀여움이 사람/동물에만 걸린 경우 제외
        cute_only = bool(re.search(r"귀여|기여", sent)) and not strong_pos
        if cute_only and not neg:
            return "단순 언급"
        pos = strong_pos
    if pos and neg:
        return "혼합"
    if pos:
        return "긍정"
    if neg:
        return "부정"
    return "단순 언급"


def polarity_aggregate(labels: list[str]) -> str:
    labs = set(labels)
    if not labs:
        return "판단 불가"
    if "혼합" in labs or (("긍정" in labs) and ("부정" in labs)):
        return "혼합"
    if "긍정" in labs:
        return "긍정"
    if "부정" in labs:
        return "부정"
    if labs == {"단순 언급"} or "단순 언급" in labs:
        return "단순 언급"
    return "판단 불가"


def extract_original_expression(match: re.Match, text: str) -> str:
    return clean_text(match.group(0))[:120]


def evidence_window(match: re.Match, text: str, pad: int = 60) -> str:
    a = max(0, match.start() - pad)
    b = min(len(text), match.end() + pad)
    return clean_text(text[a:b])[:400]


def infer_object(sent: str, default_domain: str) -> tuple[str, str]:
    """평가 대상·도메인 휴리스틱 (원문 단서 기반)."""
    pairs = [
        (r"사진|네컷|필름|셀카|직캠|인생샷|포토", "사진", "사진"),
        (r"인테리어|카페|매장|공간|골목|건물|조명|벽", "공간·장소", "공간"),
        (r"옷|패션|배색|착용|네일", "패션·외형", "제품"),
        (r"스티커|다이어리|다꾸|키링|굿즈|인형|접시", "제품·소품", "제품"),
        (r"글|일기|포스팅|문체|글씨|폰트|손글씨", "글·콘텐츠", "콘텐츠"),
        (r"앱|어플|화면|UI|UX", "앱·화면", "UI"),
        (r"캐릭터", "캐릭터", "제품"),
    ]
    for pat, obj, dom in pairs:
        if re.search(pat, sent, flags=re.IGNORECASE):
            return obj, dom
    return "문맥상 대상 불명확", default_domain


def reasons_in_text(sent: str) -> list[str]:
    found = []
    for rid, rc in REASON_CODES.items():
        if rid == "이유불명":
            continue
        if rc["patterns"] and any_match(rc["patterns"], sent):
            found.append(rc["label"])
    if not found:
        found = ["이유 불명"]
    return found


def load_data(cfg: dict):
    posts = pd.read_csv(DATA_DIR / cfg["source"]["primary_posts"], dtype=str, keep_default_na=False)
    comments = pd.read_csv(DATA_DIR / cfg["source"]["primary_comments"], dtype=str, keep_default_na=False)
    hits = pd.read_csv(DATA_DIR / cfg["source"]["primary_search_hits"], dtype=str, keep_default_na=False)
    monthly = pd.read_csv(DATA_DIR / cfg["source"]["primary_monthly_summary"], dtype=str, keep_default_na=False)
    with open(DATA_DIR / cfg["source"]["aggregate_stats"], encoding="utf-8") as f:
        agg = json.load(f)
    # normalize flags
    for col in ["within_research_period"]:
        if col in comments.columns:
            comments[col] = comments[col].astype(str).str.lower().isin(["true", "1", "yes"])
    return posts, comments, hits, monthly, agg


def build_corpus(posts: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    eligible = set(cfg["corpus"]["analysis_eligible_values"])
    ctypes = set(cfg["corpus"]["content_type_values"])
    core = posts[
        (posts["analysis_eligible"].isin(eligible))
        & (posts["content_type"].isin(ctypes))
        & (posts["extraction_status"] == "성공")
    ].copy()
    # mixed sensitivity set
    mixed = posts[
        (posts["analysis_eligible"].isin(cfg["corpus"]["mixed_eligible_values"]))
        | (posts["content_type"].isin(cfg["corpus"]["mixed_content_types"]))
    ].copy()
    return core, mixed


def post_queries(hits: pd.DataFrame) -> dict[str, list[str]]:
    m = defaultdict(set)
    for _, r in hits.iterrows():
        pid = r.get("post_id") or ""
        q = r.get("query") or ""
        if pid and q:
            m[pid].add(q)
    return {k: sorted(v) for k, v in m.items()}


def code_post_sources(row, queries: list[str], corpus_tag: str) -> list[dict]:
    title = apply_normalization(clean_text(str(row.get("title") or "")))
    body = apply_normalization(clean_text(str(row.get("body_text") or "")))
    tags = apply_normalization(clean_text(str(row.get("hashtags") or "")))
    sources = [
        ("제목", title),
        ("본문", body),
        ("해시태그", tags),
    ]
    evidences = []
    eid_n = 0
    # track which element already coded for post (still allow multi-source but one evidence per element-source)
    seen_elem_source = set()

    for source_type, text in sources:
        if not text or text.lower() == "nan":
            continue
        sents = split_sentences(text)
        direct_hits_in_sent = defaultdict(set)

        # first pass: non-vague elements
        for elem_id, elem in DESIGN_ELEMENTS.items():
            if elem.get("skip_if_other_direct"):
                continue
            m = guarded_search(elem, text)
            if not m:
                continue
            key = (elem_id, source_type)
            if key in seen_elem_source:
                continue
            seen_elem_source.add(key)
            sent = evidence_window(m, text)
            # polarity from matching sentences
            theme_sents = [s for s in sents if guarded_search(elem, s)]
            if not theme_sents:
                theme_sents = [sent]
            pols = [polarity_for_sentence(s, elem_id) for s in theme_sents]
            pol = polarity_aggregate(pols)
            obj, domain = infer_object(sent, elem.get("default_object_domain", "기타"))
            reasons = reasons_in_text(sent)
            # 이유 불명이면 preference_reason 표시
            if pol in ("단순 언급", "판단 불가") and reasons == ["이유 불명"]:
                pref_reason = "평가·이유 불명 또는 단순 언급"
            elif reasons == ["이유 불명"] and pol == "긍정":
                pref_reason = "긍정 평가 있으나 구체 이유 불명"
            else:
                pref_reason = "; ".join(reasons)

            level = elem["default_evidence_level"]
            # 앱 UI 직접 언급이 아니면 UI 선호로 승격하지 않음
            explicit = "명시" if level == "직접 근거" else "해석 가능"
            eid_n += 1
            for s in theme_sents:
                direct_hits_in_sent[s].add(elem_id)

            evidences.append(
                {
                    "evidence_id": f"D_{row['post_id']}_{eid_n:03d}",
                    "post_id": row["post_id"],
                    "comment_id": "",
                    "author_key": row.get("author_key") or "",
                    "commenter_key": "",
                    "source_url": row.get("canonical_url") or "",
                    "published_at": row.get("published_at") or "",
                    "source_type": source_type,
                    "original_expression": extract_original_expression(m, text),
                    "evidence_sentence": sent,
                    "sentence_location": f"{source_type}:{m.start()}-{m.end()}",
                    "evaluated_object": obj,
                    "object_domain": domain,
                    "design_dimension": elem["dimension"],
                    "element_id": elem_id,
                    "normalized_design_element": elem["label"],
                    "sentiment": pol,
                    "preference_reason": pref_reason,
                    "evidence_level": level,
                    "explicit_or_interpreted": explicit,
                    "review_status": "자동 분류",
                    "corpus_tag": corpus_tag,
                    "search_queries": "|".join(queries),
                    "sponsorship_status": row.get("sponsorship_status") or "",
                }
            )

        # second pass: vague aesthetic only if no direct in same window
        vague = DESIGN_ELEMENTS.get("aesthetic_vague")
        if vague:
            m = guarded_search(vague, text)
            if m:
                sent = evidence_window(m, text)
                # skip if any direct element already in this sentence window
                if not any(guarded_search(DESIGN_ELEMENTS[e], sent) for e in DESIGN_ELEMENTS if e != "aesthetic_vague"):
                    key = ("aesthetic_vague", source_type)
                    if key not in seen_elem_source:
                        seen_elem_source.add(key)
                        pol = polarity_for_sentence(sent)
                        if pol == "단순 언급":
                            # '예쁘다' alone is positive-ish but reason unknown
                            if re.search(r"예쁘|이쁘|귀여|감성", sent):
                                pol = "긍정"
                        obj, domain = infer_object(sent, "공간")
                        eid_n += 1
                        evidences.append(
                            {
                                "evidence_id": f"D_{row['post_id']}_{eid_n:03d}",
                                "post_id": row["post_id"],
                                "comment_id": "",
                                "author_key": row.get("author_key") or "",
                                "commenter_key": "",
                                "source_url": row.get("canonical_url") or "",
                                "published_at": row.get("published_at") or "",
                                "source_type": source_type,
                                "original_expression": extract_original_expression(m, text),
                                "evidence_sentence": sent,
                                "sentence_location": f"{source_type}:{m.start()}-{m.end()}",
                                "evaluated_object": obj,
                                "object_domain": domain,
                                "design_dimension": vague["dimension"],
                                "element_id": "aesthetic_vague",
                                "normalized_design_element": vague["label"],
                                "sentiment": pol,
                                "preference_reason": "이유 불명(미감 형용사만)",
                                "evidence_level": "간접 근거",
                                "explicit_or_interpreted": "해석 가능",
                                "review_status": "자동 분류",
                                "corpus_tag": corpus_tag,
                                "search_queries": "|".join(queries),
                                "sponsorship_status": row.get("sponsorship_status") or "",
                            }
                        )
    return evidences


def code_comments(comments: pd.DataFrame, core_ids: set, query_map: dict) -> list[dict]:
    rows = []
    csub = comments[comments["post_id"].isin(core_ids)].copy()
    if "within_research_period" in csub.columns:
        csub = csub[csub["within_research_period"] == True]  # noqa: E712
    n = 0
    for _, r in csub.iterrows():
        raw = str(r.get("comment_text") or "")
        text = apply_normalization(clean_text(re.sub(r"<br\s*/?>", " ", raw, flags=re.I)))
        if not text:
            continue
        is_author = str(r.get("is_post_author") or "").lower()
        for cid, elem in COMMENT_DESIGN_PATTERNS.items():
            m = None
            for p in elem["patterns"]:
                m = re.search(p, text, flags=re.IGNORECASE)
                if m:
                    break
            if not m:
                continue
            # skip generic mutual-neighbor spam if no clear design object beyond template
            if "서로이웃" in text and "사진이랑 분위기가 좋아요" in text:
                # keep but mark as weak template
                review = "자동 분류(서이추 템플릿 가능)"
            else:
                review = "자동 분류"
            pol = polarity_for_sentence(text)
            obj, domain = infer_object(text, elem["default_object_domain"])
            n += 1
            rows.append(
                {
                    "evidence_id": f"C_{r['comment_id']}_{n:03d}"[:80],
                    "post_id": r["post_id"],
                    "comment_id": r["comment_id"],
                    "author_key": "",
                    "commenter_key": r.get("commenter_key") or "",
                    "source_url": "",
                    "published_at": r.get("commented_at") or "",
                    "source_type": "댓글",
                    "original_expression": extract_original_expression(m, text),
                    "evidence_sentence": text[:400],
                    "sentence_location": f"comment:0-{len(text)}",
                    "evaluated_object": obj,
                    "object_domain": domain,
                    "design_dimension": elem["dimension"],
                    "element_id": cid,
                    "normalized_design_element": elem["label"],
                    "sentiment": pol,
                    "preference_reason": "; ".join(reasons_in_text(text)),
                    "evidence_level": elem["default_evidence_level"],
                    "explicit_or_interpreted": "명시" if is_author != "true" else "작성자 답글 가능",
                    "review_status": review,
                    "corpus_tag": "comment",
                    "search_queries": "|".join(query_map.get(r["post_id"], [])),
                    "sponsorship_status": "",
                    "is_post_author": is_author,
                }
            )
    return rows


def aggregate_elements(ev_df: pd.DataFrame, core_n: int, authors_n: int) -> pd.DataFrame:
    """게시물 단위 집계. 댓글 제외."""
    posts_ev = ev_df[ev_df["source_type"] != "댓글"].copy()
    rows = []
    for elem_id, g in posts_ev.groupby("element_id"):
        # post-level sentiment: merge sentiments per post
        post_sent = {}
        for pid, pg in g.groupby("post_id"):
            post_sent[pid] = polarity_aggregate(list(pg["sentiment"]))
        mention_posts = len(post_sent)
        sent_counts = Counter(post_sent.values())
        pos_posts = sent_counts.get("긍정", 0)
        authors = g["author_key"].nunique()
        reason_explicit = g[
            ~g["preference_reason"].str.contains("이유 불명|단순 언급", na=False)
            & (g["sentiment"] == "긍정")
        ]["post_id"].nunique()
        domains = "; ".join(sorted(g["object_domain"].value_counts().head(5).index.astype(str)))
        queries = Counter()
        for qs in g["search_queries"]:
            for q in str(qs).split("|"):
                if q:
                    queries[q] += 1
        label = g["normalized_design_element"].iloc[0]
        dim = g["design_dimension"].iloc[0]
        level_mode = g["evidence_level"].value_counts().index[0]
        rows.append(
            {
                "element_id": elem_id,
                "design_dimension": dim,
                "normalized_design_element": label,
                "primary_evidence_level": level_mode,
                "mention_posts": mention_posts,
                "mention_rate_num": mention_posts,
                "mention_rate_den": core_n,
                "mention_rate": round(mention_posts / core_n, 4) if core_n else 0,
                "positive_posts": pos_posts,
                "negative_posts": sent_counts.get("부정", 0),
                "mixed_posts": sent_counts.get("혼합", 0),
                "mention_only_posts": sent_counts.get("단순 언급", 0),
                "unclear_posts": sent_counts.get("판단 불가", 0),
                "positive_among_mention_rate_num": pos_posts,
                "positive_among_mention_rate_den": mention_posts,
                "positive_among_mention_rate": round(pos_posts / mention_posts, 4) if mention_posts else 0,
                "unique_authors": authors,
                "positive_with_explicit_reason_posts": reason_explicit,
                "top_object_domains": domains,
                "top_search_queries": "; ".join(f"{q}:{c}" for q, c in queries.most_common(5)),
                "note": "비율은 본 분석 표본 내 언급 비율이며 전체 이용자 디자인 선호율이 아님",
            }
        )
    out = pd.DataFrame(rows).sort_values(["mention_posts", "positive_posts"], ascending=False)
    return out


def author_concentration(ev_df: pd.DataFrame, core: pd.DataFrame) -> dict:
    posts_ev = ev_df[ev_df["source_type"] != "댓글"]
    direct = posts_ev[posts_ev["evidence_level"] == "직접 근거"]
    author_posts = direct.groupby("author_key")["post_id"].nunique().sort_values(ascending=False)
    top = author_posts.head(10)
    return {
        "direct_evidence_authors": int(direct["author_key"].nunique()),
        "top10_authors_share_of_direct_posts": round(
            float(top.sum() / max(direct["post_id"].nunique(), 1)), 4
        ),
        "top10_author_keys": list(top.index.astype(str)),
    }


def review_sample(ev_df: pd.DataFrame, posts: pd.DataFrame, seed: int, n: int = 50) -> tuple[pd.DataFrame, list[dict]]:
    """고정 시드로 최대 50건 재검토. 오류 수정 로그 반환."""
    rng = np.random.default_rng(seed)
    posts_ev = ev_df[ev_df["source_type"] != "댓글"].copy()
    if posts_ev.empty:
        return pd.DataFrame(), []

    strata = []
    for level in ["직접 근거", "간접 근거"]:
        for sent in ["긍정", "부정", "혼합", "단순 언급", "판단 불가"]:
            sub = posts_ev[(posts_ev["evidence_level"] == level) & (posts_ev["sentiment"] == sent)]
            if len(sub):
                strata.append(sub)

    target_ids = []
    per = max(1, n // max(len(strata), 1))
    for sub in strata:
        take = min(per, len(sub))
        idxs = rng.choice(sub.index.to_numpy(), size=take, replace=False)
        target_ids.extend(idxs.tolist())

    # fill up to n
    remain = [i for i in posts_ev.index if i not in set(target_ids)]
    if len(target_ids) < n and remain:
        extra = rng.choice(remain, size=min(n - len(target_ids), len(remain)), replace=False)
        target_ids.extend(extra.tolist())
    target_ids = target_ids[:n]

    sample = posts_ev.loc[target_ids].copy()
    post_map = posts.set_index("post_id")
    corrections = []
    statuses = []

    for idx, row in sample.iterrows():
        pid = row["post_id"]
        if pid not in post_map.index:
            statuses.append("원문 없음-제외")
            corrections.append({"evidence_id": row["evidence_id"], "action": "exclude", "reason": "post missing"})
            continue
        prow = post_map.loc[pid]
        if isinstance(prow, pd.DataFrame):
            prow = prow.iloc[0]
        full = apply_normalization(
            clean_text(
                f"{prow.get('title') or ''}\n{prow.get('body_text') or ''}\n{prow.get('hashtags') or ''}"
            )
        )
        expr = str(row["original_expression"])
        sent = str(row["evidence_sentence"])
        ok_expr = (expr[:20] in full) if expr else False
        ok_sent = (sent[:30] in full) if len(sent) >= 30 else (sent in full)
        # false positive heuristics
        fp = False
        reason = ""
        if row["element_id"] == "photo_edit_filter" and re.search(r"커피|에어컨|이어컨|에티오피아", sent):
            fp = True
            reason = "필터 오탐(비시각)"
        if row["element_id"] == "color_named_eval" and re.search(r"골드키위|생크림|휘핑크림", sent):
            fp = True
            reason = "색 이름 오탐(음식)"
        if row["element_id"] == "type_handwriting_font" and re.search(r"폰트\s*용산|카페\s*폰트", sent):
            fp = True
            reason = "상호명 폰트 오탐"
        if row["element_id"] == "writing_length_readability" and re.search(r"한\s*줄\s*요약", sent):
            fp = True
            reason = "한줄요약 템플릿 오탐"
        if row["element_id"] == "layout_busy_dense" and re.search(
            r"정신없이\s*(?:먹|지나|일)|정신없는\s*나날|복잡하게\s*준비", sent
        ):
            fp = True
            reason = "일정·행동 '정신없' 오탐"
        # loose containment: whitespace-insensitive
        compact_full = re.sub(r"\s+", "", full)
        compact_sent = re.sub(r"\s+", "", sent)[:40]
        if compact_sent and compact_sent not in compact_full and not ok_expr:
            fp = True
            reason = reason or "원문 대조 실패(공백무시)"
        if not ok_sent and not ok_expr and not compact_sent:
            fp = True
            reason = "원문 대조 실패"

        if fp:
            statuses.append("오류-제외")
            corrections.append(
                {
                    "evidence_id": row["evidence_id"],
                    "post_id": pid,
                    "action": "exclude",
                    "reason": reason,
                    "element_id": row["element_id"],
                }
            )
        else:
            # soft checks: vague positive without reason stays 이유 불명
            if row["element_id"] == "aesthetic_vague" and "이유 불명" not in str(row["preference_reason"]):
                corrections.append(
                    {
                        "evidence_id": row["evidence_id"],
                        "post_id": pid,
                        "action": "set_reason",
                        "reason": "미감 형용사만 → 이유 불명 유지",
                        "element_id": row["element_id"],
                    }
                )
            statuses.append("원문일치-유지")

    sample = sample.copy()
    sample["manual_review_result"] = statuses
    sample["review_status"] = "자동 분류 및 재검토"
    return sample, corrections


def apply_corrections(ev_df: pd.DataFrame, corrections: list[dict]) -> pd.DataFrame:
    drop_ids = {c["evidence_id"] for c in corrections if c.get("action") == "exclude"}
    out = ev_df[~ev_df["evidence_id"].isin(drop_ids)].copy()
    for c in corrections:
        if c.get("action") == "set_reason":
            out.loc[out["evidence_id"] == c["evidence_id"], "preference_reason"] = "이유 불명(미감 형용사만)"
            out.loc[out["evidence_id"] == c["evidence_id"], "review_status"] = "자동 분류 및 재검토"
    out.loc[out["evidence_id"].isin({c["evidence_id"] for c in corrections}), "review_status"] = (
        "자동 분류 및 재검토"
    )
    return out


def build_directions(summary: pd.DataFrame, ev_df: pd.DataFrame, core_n: int) -> list[dict]:
    """데이터 허용 범위에서 디자인 방향 후보 (최대 3)."""
    posts_ev = ev_df[ev_df["source_type"] != "댓글"]
    direct = posts_ev[posts_ev["evidence_level"] == "직접 근거"]
    direct_posts = direct["post_id"].nunique()

    def elem_stats(eid):
        sub = summary[summary["element_id"] == eid]
        if sub.empty:
            return None
        return sub.iloc[0].to_dict()

    directions = []

    # D1: 사진 기록 형식 (네컷/필름/사진 평가) — 직접 근거
    photo_ids = ["photo_booth_strip", "texture_film_grain", "photo_eval_look", "photo_edit_filter"]
    photo_posts = posts_ev[posts_ev["element_id"].isin(photo_ids)]["post_id"].nunique()
    photo_pos = 0
    eids = []
    for eid in photo_ids:
        st = elem_stats(eid)
        if st and st["mention_posts"] > 0:
            eids.append(eid)
            photo_pos += int(st["positive_posts"])
    if photo_posts >= 15:
        sample_ids = list(
            posts_ev[posts_ev["element_id"].isin(photo_ids)]["evidence_id"].head(12)
        )
        directions.append(
            {
                "direction_id": "D1",
                "name": "순간을 붙잡는 사진 카드",
                "one_liner": "현장에서 남긴 사진 조각(네컷·필름·한 컷)을 짧은 메모와 함께 장소에 붙이는 표현.",
                "linked_ux": ["사진과 메모 작성", "현장에서 타인의 기록 열람", "내 기록을 다시 찾아보기"],
                "data_elements": [DESIGN_ELEMENTS[e]["label"] for e in eids],
                "designer_interpreted": [
                    "네컷/스트립형 카드 레이아웃(제안)",
                    "필름 감 필터는 선택 옵션으로만(제안)",
                    "날짜·짧은 메모 슬롯(제안)",
                ],
                "evidence_post_count": int(photo_posts),
                "evidence_ids_sample": sample_ids,
                "color_direction": "자료에서 앱 색상 HEX는 확인되지 않음. 사진이 주인공이 되도록 중립·저채도 프레임을 디자이너 제안값으로 검토.",
                "image_texture": "네컷·스티커사진·하루필름 등 '물리 사진 매체' 경험이 직접 언급됨(다수는 행위 언급, 소수만 명시적 긍정). 픽셀/Y2K로 단정하지 않음.",
                "typography": "손글씨·폰트 직접 근거는 매우 적음 → 가독성 우선 본문, 손글씨 장식은 선택.",
                "icon_decor_character": "스티커는 제품/다꾸 맥락의 직접 근거와 분리해, 기록 카드의 가벼운 장식 옵션으로만 해석 제안.",
                "photo_memo_layout": "사진 1~4장 + 한두 줄 메모. 콜라주 강제는 근거 부족.",
                "copy_examples": ["여기 빛 좋았음", "오늘 여기 지나침", "이 골목 다시 오고 싶음"],
                "cautions": "보정·필터 강제는 사용 부담. 꾸미기 귀찮음(부정/혼합)과 충돌 가능.",
                "counter_evidence": "꾸미기 부담·귀찮음 직접 언급 존재; UI 색상 선호는 미확인.",
                "validation_questions": [
                    "장소 기록 시 네컷/스트립형 카드가 일반 정사각 카드보다 남기고 싶은가?",
                    "필터는 기본 적용과 선택 적용 중 무엇을 선호하는가?",
                ],
                "status": "우선 검토" if photo_posts >= 30 else "탐색 후보",
            }
        )

    # D2: 장소의 빛·색·정돈된 분위기 발견
    space_ids = ["light_mood", "space_interior_pref", "color_palette_space", "layout_clean_simple", "color_named_eval"]
    space_posts = posts_ev[posts_ev["element_id"].isin(space_ids)]["post_id"].nunique()
    eids2 = [e for e in space_ids if elem_stats(e) and elem_stats(e)["mention_posts"] > 0]
    if space_posts >= 15:
        sample_ids = list(posts_ev[posts_ev["element_id"].isin(space_ids)]["evidence_id"].head(12))
        directions.append(
            {
                "direction_id": "D2",
                "name": "장소의 빛과 색을 발견하는 지도",
                "one_liner": "따뜻한 조명·색채·깔끔한 공간이 좋다는 장소 경험을, 발견 순간의 시각 단서로 절제해 반영.",
                "linked_ux": ["지도에서 기록 발견", "현장에서 타인의 기록 열람"],
                "data_elements": [DESIGN_ELEMENTS[e]["label"] for e in eids2],
                "designer_interpreted": [
                    "지도 핀/카드에 과도한 테마색 대신 사진 썸네일 강조(제안)",
                    "따뜻한 중성 배경 톤은 디자이너 제안값(공간 조명 선호를 UI 색으로 비약하지 않음)",
                    "정보 밀도 낮은 카드(깔끔·한눈에 보기 좋음 근거와 연결)",
                ],
                "evidence_post_count": int(space_posts),
                "evidence_ids_sample": sample_ids,
                "color_direction": "원문에 특정 HEX 없음. 공간의 '따뜻함/무채색/알록달록'은 장소·제품 평가이므로 앱 크로마로 직접 이식 금지. 디자이너 제안: 저채도 웜 그레이 배경 + 사진 본연 색.",
                "image_texture": "한지·자연광·조명 등 공간 질감은 배경 장식이 아니라 사용자 사진으로 전달.",
                "typography": "짧은 장소 메모가 읽히도록 본문 가독성 우선.",
                "icon_decor_character": "장식보다 장소 사진·짧은 단서가 주인공.",
                "photo_memo_layout": "지도 → 카드: 사진 크게, 텍스트 1~2줄, 여백 확보.",
                "copy_examples": ["조명 따뜻한 자리", "벽 색이 조용함", "여긴 사진 잘 나옴"],
                "cautions": "공간 미감을 앱 스킨 전체의 레트로/파스텔로 확장하지 말 것.",
                "counter_evidence": "시대 스타일(Y2K 등) 직접 근거는 소수이며 패션·카페 맥락. UI 스타일 선호로 미검증.",
                "validation_questions": [
                    "지도에서 기록을 고를 때 색 테마보다 사진 썸네일이 더 중요한가?",
                    "따뜻한 분위기 표현이 과하면 가독성을 해치는가?",
                ],
                "status": "우선 검토" if space_posts >= 25 else "탐색 후보",
            }
        )

    # D3: 가벼운 손기록 + 선택적 꾸밈 (근거가 충분할 때만)
    write_ids = ["decor_sticker_frame", "decor_burden", "writing_length_readability", "type_handwriting_font", "photo_collage_dump"]
    write_posts = posts_ev[posts_ev["element_id"].isin(write_ids)]["post_id"].nunique()
    burden = elem_stats("decor_burden")
    sticker = elem_stats("decor_sticker_frame")
    if write_posts >= 10 and (sticker is not None or elem_stats("writing_length_readability") is not None):
        sample_ids = list(posts_ev[posts_ev["element_id"].isin(write_ids)]["evidence_id"].head(12))
        directions.append(
            {
                "direction_id": "D3",
                "name": "가볍게 남기고, 꾸밈은 선택",
                "one_liner": "짧은 메모·사진 모음은 쉽게, 스티커·손꾸밈은 원하지 않으면 건너뛸 수 있게.",
                "linked_ux": ["사진과 메모 작성", "내 기록을 다시 찾아보기"],
                "data_elements": [DESIGN_ELEMENTS[e]["label"] for e in write_ids if elem_stats(e)],
                "designer_interpreted": [
                    "기본 작성 플로는 사진+한 줄(제안)",
                    "스티커/프레임은 옵션 서랍(제안)",
                    "필수 다꾸형 UI 지양",
                ],
                "evidence_post_count": int(write_posts),
                "evidence_ids_sample": sample_ids,
                "color_direction": "작성 화면은 높은 대비·단순한 면 구성(디자이너 제안값). 파스텔 강제 근거 없음.",
                "image_texture": "포토덤프형 모아보기는 간접 근거(형식 언급). 강요하지 않음.",
                "typography": "짧은 글 선호·가독성 댓글 단서와 연결 가능하나 표본 소수의 직접 근거.",
                "icon_decor_character": "스티커 긍정도 있으나 꾸미기 귀찮음 반대 근거 → 기본 OFF.",
                "photo_memo_layout": "작성 최소 단계: 사진 선택 → 한 줄 → 게시. 꾸미기는 이후.",
                "copy_examples": ["한 줄만 남겨도 충분해요", "꾸미기는 나중에", "사진만 올려도 OK"],
                "cautions": "장식 밀도가 현장 작성 속도를 해치면 핵심 과업 우선.",
                "counter_evidence": f"꾸미기 부담 언급 posts={int(burden['mention_posts']) if burden is not None else 0}",
                "validation_questions": [
                    "현장에서 기록할 때 스티커 UI가 있으면 사용하겠는가, 방해되는가?",
                    "한 줄 메모 기본값이 충분한가?",
                ],
                "status": "탐색 후보",
            }
        )

    # 근거 부족 시 억지로 채우지 않음
    return directions[:3]


def save_charts(summary: pd.DataFrame, ev_df: pd.DataFrame, core_n: int, directions: list, charts_dir: Path, font_name):
    charts_dir.mkdir(parents=True, exist_ok=True)
    posts_ev = ev_df[ev_df["source_type"] != "댓글"]
    direct_posts = posts_ev[posts_ev["evidence_level"] == "직접 근거"]["post_id"].nunique()
    indirect_posts = posts_ev[posts_ev["evidence_level"] == "간접 근거"]["post_id"].nunique()

    def save_fig(name):
        png = charts_dir / f"{name}.png"
        svg = charts_dir / f"{name}.svg"
        plt.tight_layout()
        plt.savefig(png, dpi=140, bbox_inches="tight")
        plt.savefig(svg, bbox_inches="tight")
        plt.close()
        return png, svg

    # 01 direct evidence coverage
    fig, ax = plt.subplots(figsize=(7, 4.5))
    vals = [direct_posts, core_n - direct_posts]
    ax.bar(["직접 근거 있는 게시물", "없음"], vals, color=["#2F5D50", "#C8D3CD"])
    ax.set_ylabel("게시물 수")
    ax.set_title(f"디자인 직접 근거 게시물 (n={core_n}, 기간 2025-01~2026-10)")
    for i, v in enumerate(vals):
        ax.text(i, v + max(core_n * 0.01, 2), f"{v}\n({v/core_n:.1%})", ha="center", va="bottom", fontsize=9)
    save_fig("01_direct_evidence_coverage")

    # 02 element mention bars (direct only elements preferred; show level)
    sub = summary[summary["mention_posts"] > 0].head(12).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = ["#2F5D50" if x == "직접 근거" else "#8FA39A" for x in sub["primary_evidence_level"]]
    ax.barh(sub["normalized_design_element"], sub["mention_posts"], color=colors)
    ax.set_xlabel("언급 게시물 수 (게시물당 1회)")
    ax.set_title("주요 디자인 요소별 언급 게시물 수 (직접=진한색, 간접=연한색)")
    save_fig("02_element_mention_bars")

    # 03 sentiment stacked for top elements
    top = summary.head(8)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    labels = top["normalized_design_element"].tolist()
    cats = ["positive_posts", "negative_posts", "mixed_posts", "mention_only_posts", "unclear_posts"]
    cat_names = ["긍정", "부정", "혼합", "단순 언급", "판단 불가"]
    cat_colors = ["#3D7A5A", "#B85C38", "#C4A35A", "#8A8A8A", "#C0C0C0"]
    bottom = np.zeros(len(top))
    x = np.arange(len(top))
    for c, name, col in zip(cats, cat_names, cat_colors):
        vals = top[c].to_numpy(dtype=float)
        ax.bar(x, vals, bottom=bottom, label=name, color=col)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("게시물 수")
    ax.set_title("주요 요소별 감정 분포 (게시물 단위, 직접+간접 요소를 색으로 구분하지 않음·요소별 집계)")
    ax.legend(fontsize=8)
    # footnote in title already; separate direct chart note
    save_fig("03_element_sentiment_stacked")

    # 03b direct-only sentiment for direct elements
    direct_elems = summary[summary["primary_evidence_level"] == "직접 근거"].head(8)
    if len(direct_elems):
        fig, ax = plt.subplots(figsize=(10, 5.5))
        labels = direct_elems["normalized_design_element"].tolist()
        bottom = np.zeros(len(direct_elems))
        x = np.arange(len(direct_elems))
        for c, name, col in zip(cats, cat_names, cat_colors):
            vals = direct_elems[c].to_numpy(dtype=float)
            ax.bar(x, vals, bottom=bottom, label=name, color=col)
            bottom += vals
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax.set_ylabel("게시물 수")
        ax.set_title("직접 근거 요소만 — 감정 분포")
        ax.legend(fontsize=8)
        save_fig("03b_direct_element_sentiment")

    # 04 element-reason link table as heatmap-ish counts
    posts_ev2 = posts_ev.copy()
    reason_rows = []
    for _, r in posts_ev2.iterrows():
        for reason in str(r["preference_reason"]).split("; "):
            reason_rows.append((r["normalized_design_element"], reason, r["post_id"], r["evidence_level"]))
    rdf = pd.DataFrame(reason_rows, columns=["element", "reason", "post_id", "level"])
    # direct only for this chart
    rdf_d = rdf[rdf["level"] == "직접 근거"]
    if len(rdf_d):
        piv = rdf_d.pivot_table(index="element", columns="reason", values="post_id", aggfunc=pd.Series.nunique, fill_value=0)
        # keep top elements / reasons
        piv = piv.loc[piv.sum(axis=1).sort_values(ascending=False).head(8).index]
        piv = piv[piv.sum().sort_values(ascending=False).head(8).index]
        fig, ax = plt.subplots(figsize=(10, 6))
        im = ax.imshow(piv.to_numpy(), cmap="YlGn", aspect="auto")
        ax.set_xticks(range(len(piv.columns)))
        ax.set_yticks(range(len(piv.index)))
        ax.set_xticklabels(piv.columns, rotation=30, ha="right", fontsize=8)
        ax.set_yticklabels(piv.index, fontsize=8)
        ax.set_title("직접 근거: 디자인 요소 × 선호 이유 (고유 게시물 수)")
        for i in range(piv.shape[0]):
            for j in range(piv.shape[1]):
                ax.text(j, i, int(piv.to_numpy()[i, j]), ha="center", va="center", fontsize=8)
        fig.colorbar(im, ax=ax, fraction=0.046)
        save_fig("04_element_reason_link")
    else:
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.axis("off")
        ax.text(0.1, 0.5, "직접 근거 기반 요소-이유 연결 데이터 부족")
        save_fig("04_element_reason_link")

    # 05 direction comparison
    fig, ax = plt.subplots(figsize=(9, 4.5))
    if directions:
        names = [d["name"] for d in directions]
        counts = [d["evidence_post_count"] for d in directions]
        ax.barh(names[::-1], counts[::-1], color="#345C6F")
        ax.set_xlabel("관련 요소 언급 게시물 수(참고)")
        ax.set_title("디자인 방향 후보 비교 (빈도≠검증된 UI 선호)")
    else:
        ax.axis("off")
        ax.text(0.1, 0.5, "데이터 상 디자인 방향 후보 없음")
    save_fig("05_direction_comparison")

    # meta
    with open(charts_dir / "chart_meta.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "core_posts_denominator": core_n,
                "direct_evidence_posts": direct_posts,
                "indirect_evidence_posts": indirect_posts,
                "font": font_name,
                "note": "직접·간접 근거를 합쳐 하나의 '선호' 막대로 그리지 않음. 워드클라우드 미사용.",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def write_codebook_xlsx(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "elements"
    headers = [
        "element_id",
        "dimension",
        "label",
        "definition",
        "include",
        "exclude",
        "default_evidence_level",
        "default_object_domain",
        "patterns",
        "false_positive_guards",
    ]
    ws.append(headers)
    for eid, e in DESIGN_ELEMENTS.items():
        ws.append(
            [
                eid,
                e["dimension"],
                e["label"],
                e["definition"],
                e["include"],
                e["exclude"],
                e["default_evidence_level"],
                e["default_object_domain"],
                " | ".join(e["patterns"]),
                " | ".join(e.get("false_positive_guards") or []),
            ]
        )
    ws2 = wb.create_sheet("reasons")
    ws2.append(["reason_id", "label", "patterns"])
    for rid, r in REASON_CODES.items():
        ws2.append([rid, r["label"], " | ".join(r.get("patterns") or [])])
    ws3 = wb.create_sheet("dimensions")
    ws3.append(["dimension", "note"])
    for d in ALL_DIMENSIONS:
        present = any(e["dimension"] == d for e in DESIGN_ELEMENTS.values())
        ws3.append([d, "코드 정의됨" if present else "관측 범주 목록"])
    ws4 = wb.create_sheet("comments")
    ws4.append(["element_id", "dimension", "label", "patterns", "evidence_level"])
    for cid, c in COMMENT_DESIGN_PATTERNS.items():
        ws4.append([cid, c["dimension"], c["label"], " | ".join(c["patterns"]), c["default_evidence_level"]])
    wb.save(path)


def write_direction_xlsx(path: Path, directions: list, link_rows: list):
    wb = Workbook()
    ws = wb.active
    ws.title = "directions"
    if directions:
        keys = list(directions[0].keys())
        ws.append(keys)
        for d in directions:
            ws.append([json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in [d.get(k) for k in keys]])
    else:
        ws.append(["note"])
        ws.append(["방향 후보 없음 — 근거 부족"])
    ws2 = wb.create_sheet("link_table")
    if link_rows:
        ws2.append(list(link_rows[0].keys()))
        for r in link_rows:
            ws2.append(list(r.values()))
    wb.save(path)


def write_results_xlsx(path: Path, sheets: dict[str, pd.DataFrame]):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)


def main():
    cfg = load_cfg()
    seed = int(cfg["review"]["seed"])
    font_name = setup_korean_font()
    logs_dir = ROOT / cfg["outputs"]["logs_dir"]
    charts_dir = ROOT / cfg["outputs"]["charts_dir"]
    logs_dir.mkdir(parents=True, exist_ok=True)

    run_log = []
    def log(msg):
        line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
        run_log.append(line)
        print(msg)

    try:
        posts, comments, hits, monthly, agg = load_data(cfg)
        log(f"loaded posts={len(posts)} comments={len(comments)} hits={len(hits)}")

        # provenance
        provenance = {
            "run_id": cfg["run_id"],
            "python": sys.version,
            "platform": platform.platform(),
            "font": font_name,
            "files": {},
        }
        for key in ["primary_posts", "primary_comments", "primary_search_hits", "aggregate_stats"]:
            p = DATA_DIR / cfg["source"][key]
            provenance["files"][key] = {
                "path": str(p),
                "sha256": sha256_file(p) if p.exists() else None,
                "rows": None,
            }
        provenance["files"]["primary_posts"]["rows"] = len(posts)
        provenance["files"]["primary_comments"]["rows"] = len(comments)
        provenance["files"]["primary_search_hits"]["rows"] = len(hits)
        provenance["excel_not_double_counted"] = True
        provenance["collection_keywords_actual"] = agg.get("keywords")
        provenance["published_at_min"] = agg.get("published_at_min")
        provenance["published_at_max"] = agg.get("published_at_max")
        provenance["unique_posts_stored"] = agg.get("unique_posts_stored")
        provenance["unique_posts_extract_success"] = agg.get("unique_posts_extract_success")

        core, mixed = build_corpus(posts, cfg)
        log(f"core corpus posts={len(core)} authors={core['author_key'].nunique()}")
        qmap = post_queries(hits)

        # code
        all_ev = []
        for _, row in core.iterrows():
            all_ev.extend(code_post_sources(row, qmap.get(row["post_id"], []), "core"))
        # mixed comparison coding (별도 태그, 본집계 제외 가능)
        for _, row in mixed.iterrows():
            if row["post_id"] in set(core["post_id"]):
                continue
            all_ev.extend(code_post_sources(row, qmap.get(row["post_id"], []), "mixed_sensitivity"))

        comment_ev = code_comments(comments, set(core["post_id"]), qmap)
        all_ev.extend(comment_ev)
        ev_df = pd.DataFrame(all_ev)
        log(f"raw evidence rows={len(ev_df)}")

        # review
        sample, corrections = review_sample(ev_df, posts, seed=seed, n=int(cfg["review"]["sample_size"]))
        ev_df = apply_corrections(ev_df, corrections)
        log(f"after review corrections drop={len([c for c in corrections if c.get('action')=='exclude'])} evidence={len(ev_df)}")

        # aggregates on core only
        core_ev = ev_df[ev_df["corpus_tag"] == "core"].copy()
        comment_only = ev_df[ev_df["source_type"] == "댓글"].copy()
        summary = aggregate_elements(core_ev, core_n=len(core), authors_n=core["author_key"].nunique())

        # mixed sensitivity comparison
        mixed_ev = ev_df[ev_df["corpus_tag"] == "mixed_sensitivity"]
        mixed_note = {
            "mixed_posts_coded": int(mixed_ev["post_id"].nunique()) if len(mixed_ev) else 0,
            "note": "혼합·검토필요 글은 본집계(core)와 분리. 포함 시 홍보성 시각 수사 증가 가능.",
        }

        author_conc = author_concentration(core_ev, core)

        direct_posts_n = core_ev[core_ev["evidence_level"] == "직접 근거"]["post_id"].nunique()
        indirect_posts_n = core_ev[core_ev["evidence_level"] == "간접 근거"]["post_id"].nunique()

        directions = build_directions(summary, core_ev, len(core))

        # link table
        link_rows = []
        for d in directions:
            link_rows.append(
                {
                    "원문에서 확인한 요소": "; ".join(d["data_elements"]),
                    "선호 이유": "요소별 preference_reason 참조(분위기·사진결과·귀여움 등)",
                    "근거 건수·ID": f"posts={d['evidence_post_count']}; sample_ids={','.join(d['evidence_ids_sample'][:5])}",
                    "우리 서비스와의 연결": "; ".join(d["linked_ux"]),
                    "디자인 적용 제안": "; ".join(d["designer_interpreted"]),
                    "적용 시 주의점": d["cautions"],
                    "검증할 질문": "; ".join(d["validation_questions"]),
                }
            )

        # dimension observation table
        dim_obs = []
        for dim in ALL_DIMENSIONS:
            sub = summary[summary["design_dimension"] == dim]
            if sub.empty or sub["mention_posts"].sum() == 0:
                dim_obs.append({"dimension": dim, "status": "관측되지 않음 또는 요약 0", "mention_posts": 0})
            else:
                dim_obs.append(
                    {
                        "dimension": dim,
                        "status": "관측됨",
                        "mention_posts": int(sub["mention_posts"].sum()),
                        "elements": "; ".join(sub["normalized_design_element"].tolist()),
                    }
                )
        dim_df = pd.DataFrame(dim_obs)

        # save tables
        ev_path = ROOT / "design_evidence.csv"
        core_ev_out = pd.concat([core_ev, comment_only], ignore_index=True)
        # ensure columns
        col_order = [
            "evidence_id",
            "post_id",
            "comment_id",
            "author_key",
            "commenter_key",
            "source_url",
            "published_at",
            "source_type",
            "original_expression",
            "evidence_sentence",
            "sentence_location",
            "evaluated_object",
            "object_domain",
            "design_dimension",
            "element_id",
            "normalized_design_element",
            "sentiment",
            "preference_reason",
            "evidence_level",
            "explicit_or_interpreted",
            "review_status",
            "corpus_tag",
            "search_queries",
            "sponsorship_status",
        ]
        for c in col_order:
            if c not in core_ev_out.columns:
                core_ev_out[c] = ""
        core_ev_out[col_order].to_csv(ev_path, index=False, encoding="utf-8-sig")

        summary.to_csv(ROOT / "design_element_summary.csv", index=False, encoding="utf-8-sig")
        write_codebook_xlsx(ROOT / "design_codebook.xlsx")
        write_direction_xlsx(ROOT / "design_direction_comparison.xlsx", directions, link_rows)

        # review sample save
        if len(sample):
            sample.to_csv(ROOT / "review_sample.csv", index=False, encoding="utf-8-sig")

        write_results_xlsx(
            ROOT / "design_research_results.xlsx",
            {
                "run_meta": pd.DataFrame(
                    [
                        {
                            "core_posts": len(core),
                            "core_authors": core["author_key"].nunique(),
                            "comments_in_period_on_core": len(comment_only["comment_id"].unique()) if len(comment_only) else 0,
                            "direct_evidence_posts": direct_posts_n,
                            "indirect_evidence_posts": indirect_posts_n,
                            "period_min": agg.get("published_at_min"),
                            "period_max": agg.get("published_at_max"),
                            "keywords": ", ".join(agg.get("keywords") or []),
                        }
                    ]
                ),
                "element_summary": summary,
                "dimension_observation": dim_df,
                "author_concentration": pd.DataFrame([author_conc]),
                "mixed_sensitivity": pd.DataFrame([mixed_note]),
                "directions": pd.DataFrame(directions) if directions else pd.DataFrame([{"note": "none"}]),
                "link_table": pd.DataFrame(link_rows) if link_rows else pd.DataFrame([{"note": "none"}]),
            },
        )

        save_charts(summary, core_ev, len(core), directions, charts_dir, font_name)

        # reports
        write_reports(
            cfg,
            agg,
            core,
            comments,
            summary,
            core_ev_out,
            directions,
            link_rows,
            dim_df,
            author_conc,
            mixed_note,
            sample,
            corrections,
            direct_posts_n,
            indirect_posts_n,
            comment_only,
            font_name,
            provenance,
        )

        with open(logs_dir / "provenance.json", "w", encoding="utf-8") as f:
            json.dump(provenance, f, ensure_ascii=False, indent=2)
        with open(logs_dir / "run.log", "w", encoding="utf-8") as f:
            f.write("\n".join(run_log))

        summary_json = {
            "core_posts": len(core),
            "core_authors": int(core["author_key"].nunique()),
            "direct_evidence_posts": int(direct_posts_n),
            "indirect_evidence_posts": int(indirect_posts_n),
            "comment_design_evidence": int(comment_only["comment_id"].nunique()) if len(comment_only) else 0,
            "directions": [{"id": d["direction_id"], "name": d["name"], "status": d["status"]} for d in directions],
            "top_elements": summary.head(5)[["normalized_design_element", "mention_posts", "positive_posts"]].to_dict("records"),
        }
        with open(ROOT / "run_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary_json, f, ensure_ascii=False, indent=2)
        log("done")
        print(json.dumps(summary_json, ensure_ascii=False, indent=2))
    except Exception:
        err = traceback.format_exc()
        print(err)
        with open(logs_dir / "run_error.log", "w", encoding="utf-8") as f:
            f.write(err)
        raise


def write_reports(
    cfg,
    agg,
    core,
    comments,
    summary,
    ev_df,
    directions,
    link_rows,
    dim_df,
    author_conc,
    mixed_note,
    sample,
    corrections,
    direct_posts_n,
    indirect_posts_n,
    comment_only,
    font_name,
    provenance,
):
    core_n = len(core)
    authors_n = core["author_key"].nunique()
    # comments count on core in period
    c_on_core = comments[comments["post_id"].isin(set(core["post_id"]))]
    if "within_research_period" in c_on_core.columns:
        c_on_core = c_on_core[c_on_core["within_research_period"] == True]  # noqa: E712
    comments_n = len(c_on_core)
    commenters_n = c_on_core["commenter_key"].nunique() if len(c_on_core) else 0

    period = f"{agg.get('published_at_min')} ~ {agg.get('published_at_max')}"
    keywords = ", ".join(agg.get("keywords") or [])

    # top direct elements
    direct_sum = summary[summary["primary_evidence_level"] == "직접 근거"].head(8)

    brief_dirs = directions
    priority = [d for d in directions if d.get("status") == "우선 검토"]
    if not priority and directions:
        priority = directions[:1]

    # README
    readme = f"""# 디자인 단서 분석 (design_analysis)

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

- 기간(실제 본문 일자): {period}
- 검색 키워드(실제): {keywords}
- 본분석 코퍼스: analysis_eligible=포함 ∩ content_type=개인 경험 ∩ 추출 성공 → **{core_n}게시물 / {authors_n}작성자**
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
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")

    # review log
    excl = [c for c in corrections if c.get("action") == "exclude"]
    review_md = f"""# 재검토 로그 (review_log)

- 검수 방식: **{cfg['review']['status_label']}** (인적 독립 검수자 없음)
- 시드: {cfg['review']['seed']}
- 표본 크기: {len(sample) if sample is not None else 0} / 목표 {cfg['review']['sample_size']}
- 원문 대조 후 제외: {len(excl)}건
- 차트 한글 폰트: {font_name}

## 제외·수정 요약

| evidence_id | action | reason | element_id |
|---|---|---|---|
"""
    for c in corrections:
        review_md += f"| {c.get('evidence_id','')} | {c.get('action')} | {c.get('reason')} | {c.get('element_id','')} |\n"
    if not corrections:
        review_md += "| (없음) | - | - | - |\n"
    review_md += """
## 표본 구성 원칙

직접 근거·간접 근거·긍정·부정·혼합·단순 언급·판단 불가가 포함되도록 층화 후 시드로 추출.
대표 인용문은 `design_evidence.csv`의 evidence_sentence가 원문에 존재하는지 표본에서 대조함.
"""
    (ROOT / "review_log.md").write_text(review_md, encoding="utf-8")

    # element table markdown helper
    def fmt_summary_rows(df, n=10):
        lines = [
            "| 요소 | 차원 | 근거수준 | 언급 게시물 (비율) | 긍정/부정/혼합/단순/불가 | 언급 중 긍정 비율 | 작성자 수 |",
            "|---|---|---|---|---|---|---|",
        ]
        for _, r in df.head(n).iterrows():
            lines.append(
                f"| {r['normalized_design_element']} | {r['design_dimension']} | {r['primary_evidence_level']} | "
                f"{int(r['mention_posts'])}/{int(r['mention_rate_den'])} ({r['mention_rate']:.1%}) | "
                f"{int(r['positive_posts'])}/{int(r['negative_posts'])}/{int(r['mixed_posts'])}/{int(r['mention_only_posts'])}/{int(r['unclear_posts'])} | "
                f"{int(r['positive_among_mention_rate_num'])}/{int(r['positive_among_mention_rate_den'])} ({r['positive_among_mention_rate']:.1%}) | "
                f"{int(r['unique_authors'])} |"
            )
        return "\n".join(lines)

    # quotes from direct positive
    quotes = []
    direct_pos = ev_df[(ev_df["evidence_level"] == "직접 근거") & (ev_df["sentiment"] == "긍정") & (ev_df["source_type"] != "댓글")]
    for _, r in direct_pos.head(12).iterrows():
        quotes.append(
            f"- ({r['normalized_design_element']} / {r['object_domain']}) “{r['evidence_sentence'][:180]}” — `{r['evidence_id']}`"
        )

    report = f"""# 디자인 리서치 분석 보고서

## 1. 실제 분석 범위와 디자인 관련 근거의 양

| 항목 | 값 |
|---|---|
| 수집 게시물(저장) | {agg.get('unique_posts_stored')} |
| 본문 추출 성공 | {agg.get('unique_posts_extract_success')} |
| **본분석 게시물** | **{core_n}** (개인 경험 ∩ 포함 ∩ 추출 성공) |
| 본분석 작성자 | {authors_n} |
| 본분석 게시물 관련 기간 내 댓글 | {comments_n} (작성자키 {commenters_n}) |
| 실제 본문 일자 범위 | {period} |
| 검색 키워드 10개 | {keywords} |
| 디자인 **직접 근거** 게시물 | **{direct_posts_n}** / {core_n} ({direct_posts_n/core_n:.1%}) |
| 디자인 **간접 근거** 게시물 | {indirect_posts_n} / {core_n} ({indirect_posts_n/core_n:.1%}) |
| 디자인 관련 댓글 근거(건) | {comment_only['comment_id'].nunique() if len(comment_only) else 0} |

- CSV와 Excel은 동일 데이터 → 중복 합산하지 않음.
- 월별 목표 수량({monthly_target_note(agg)})을 관심도로 해석하지 않음.
- 이미지·스킨·HEX·캐릭터 형태는 텍스트만으로 확정하지 않음.

작성자 집중도: 직접 근거 게시물 중 상위 10명 작성자 비중 ≈ {author_conc.get('top10_authors_share_of_direct_posts')}.  
혼합·협찬 민감 코퍼스: {mixed_note}.

## 2. 어떤 시각 요소가 언급되었는가

{fmt_summary_rows(summary, 15)}

### 차원별 관측

| 차원 | 상태 | 언급 게시물(요소 합) |
|---|---|---|
"""
    for _, r in dim_df.iterrows():
        report += f"| {r['dimension']} | {r['status']} | {r.get('mention_posts', 0)} |\n"

    report += f"""
## 3. 무엇을 왜 좋아하거나 불편해했는가

직접 근거·긍정 평가가 있는 대표 구간(자동 분류, 원문 일부):

{chr(10).join(quotes) if quotes else '_직접 긍정 인용 부족_'}

### 요약

- **사진 매체·결과물**: 인생네컷·스티커사진·하루필름·보정 후 마음에 든다는 식의 **사진 경험**이 비교적 뚜렷한 직접 근거.
- **공간의 색·빛·인테리어**: 무채색·알록달록·따뜻한 조명·깔끔한 인테리어 등은 **장소/제품** 평가로 확인. 앱 화면 색 선호로 단정 불가.
- **장식**: 스티커·다꾸 긍정과 **꾸미기 귀찮음**이 공존 → 기본 강제 꾸밈에 주의.
- **캐릭터·시대 스타일(Y2K 등)**: 언급은 있으나 표본이 작고, 패션/굿즈/카페 맥락 → UI 스타일 선호로 확장하지 않음.
- **글씨·폰트**: 직접 근거 매우 적음(관측 빈약).
- ‘귀엽다/예쁘다/감성’만 있는 경우 → **이유 불명**의 간접 근거로 분리.

댓글: 사진·색감·글 가독성에 대한 반응은 소수. 서이추 템플릿(“사진이랑 분위기 좋아요”)은 특정 디자인 요소 선호로 과대 집계하지 않음.

## 4. 직접적인 디자인 근거와 간접적인 정서 단서

| 구분 | 정의 | 본 분석에서의 扱い |
|---|---|---|
| A. 직접 근거 | 시각 요소+평가가 원문에 명시 | 요소 집계·방향의 주 근거 |
| B. 간접 근거 | 감정·형식·경험만 확인 | 해석 힌트, 선호율에 합산 안 함 |
| C. 디자이너 제안 | A/B 기반 서비스 적용안 | 사용자 요구 사실과 구분 표기 |

직접 근거 상위 요소:

{fmt_summary_rows(direct_sum, 10)}

## 5. 우리 서비스에 적용할 디자인 방향 후보

"""
    if not directions:
        report += "데이터 상 충분한 직접 근거가 없어 방향 후보를 억지로 채우지 않음.\n"
    for d in directions:
        report += f"""
### {d['direction_id']} {d['name']} ({d['status']})

- 한 줄: {d['one_liner']}
- 연결 UX: {', '.join(d['linked_ux'])}
- 데이터 확인 요소: {', '.join(d['data_elements'])}
- 디자이너 해석 제안: {', '.join(d['designer_interpreted'])}
- 관련 게시물 수(참고): {d['evidence_post_count']}
- 주의: {d['cautions']}
- 반대·미확인: {d['counter_evidence']}
"""

    report += """
## 6. 우선 검토 방향과 반대 근거

"""
    if priority:
        p = priority[0]
        report += f"우선 검토: **{p['direction_id']} {p['name']}** — 사진 기록 형식이 텍스트에서 가장 구체적으로 반복됨. 다만 이는 ‘사진 경험’이지 ‘검증된 앱 UI 스킨’이 아님.\n\n"
        report += f"반대·제약: {p['counter_evidence']}; 꾸미기 부담; 공간 미감→UI 색 비약 금지; Y2K/픽셀 등 사전 결론 채택 안 함.\n"
    else:
        report += "우선 순위를 정할 만큼 직접 근거가 두텁지 않음. 추가 사용자 검증 필요.\n"

    report += """
## 7. 실제 타깃에게 검증할 항목

"""
    qs = []
    for d in directions:
        qs.extend(d.get("validation_questions") or [])
    for q in qs:
        report += f"- {q}\n"
    report += """- 장소 기록 앱에서 ‘예쁜 스킨’과 ‘빠른 남기기’ 중 현장 우선순위는?
- 타인의 기록을 지도에서 볼 때 장식보다 사진·거리·시간 정보가 더 중요한가?

---
분석 코드: `src/run_design_analysis.py` · 시드 {seed} · 폰트 {font}
""".format(seed=cfg["review"]["seed"], font=font_name)

    (ROOT / "design_analysis_report.md").write_text(report, encoding="utf-8")

    # brief
    brief = f"""# 디자인 브리프 — 장소 기반 기록 서비스

> 본 문서의 색상 HEX·컴포넌트 수치는 모두 **디자이너 제안값**이며, 블로그 원문에서 추출한 값이 아닙니다.  
> A/B 근거와 C 제안을 구분합니다.

## 서비스 맥락

사진과 짧은 이야기를 장소에 남기고, 방문자가 발견·회상·연결을 경험하는 위치 기반 기록·소통.

핵심 과업: 지도에서 발견 / 사진·메모 작성 / 현장 열람 / 내 기록 회상.

## 리서치 스냅샷

- 표본: 게시물 {core_n}, 작성자 {authors_n}, 기간 {period}
- 직접 시각 근거 게시물: {direct_posts_n} ({direct_posts_n/core_n:.1%})
- 결론: 시각 선호 **직접 근거는 제한적**. 공간·패션 미감을 앱 테마로 단정하지 말 것.

## 연결표

| 원문 요소 | 선호 이유 | 근거 | 서비스 연결 | 적용 제안(C) | 주의 | 검증 질문 |
|---|---|---|---|---|---|---|
"""
    for r in link_rows:
        brief += (
            f"| {r['원문에서 확인한 요소']} | {r['선호 이유']} | {r['근거 건수·ID'][:80]}… | "
            f"{r['우리 서비스와의 연결']} | {r['디자인 적용 제안']} | {r['적용 시 주의점']} | {r['검증할 질문']} |\n"
        )
    if not link_rows:
        brief += "| (근거 부족) | - | - | - | - | - | - |\n"

    for d in brief_dirs:
        brief += f"""
---

## 후보 {d['direction_id']}: {d['name']} ({d['status']})

**한 문장**  
{d['one_liner']}

**연결 UX**  
{', '.join(d['linked_ux'])}

**데이터에서 확인(A/B)**  
{', '.join(d['data_elements'])}  
관련 게시물 수(참고): {d['evidence_post_count']}

**디자이너 해석 제안(C)**  
- """ + "\n- ".join(d["designer_interpreted"]) + f"""

**색상 방향**  
{d['color_direction']}

**이미지·질감**  
{d['image_texture']}

**타이포**  
{d['typography']}

**아이콘·장식·캐릭터**  
{d['icon_decor_character']}

**사진·메모 카드**  
{d['photo_memo_layout']}

**문체·카피 예시**  
"""
        for c in d["copy_examples"]:
            brief += f"- “{c}”\n"
        brief += f"""
**주의 (가독성·작성 부담·현장)**  
{d['cautions']}

**반대 근거·미확인**  
{d['counter_evidence']}

**검증 질문**  
"""
        for q in d["validation_questions"]:
            brief += f"- {q}\n"

    if not brief_dirs:
        brief += "\n_충분한 직접 근거가 없어 디자인 방향 후보를 제시하지 않습니다._\n"

    brief += """
## 하지 말 것 (이번 자료 기준)

- Y2K·픽셀·DS 감성·파스텔을 사전 결론으로 채택
- 공간의 따뜻함 → 따뜻한 앱 테마로 단정
- 캐릭터 굿즈 구매 → 해당 IP 시각 전체 선호로 확장
- ‘귀엽다/예쁘다’만으로 형태·색 확정
- 기존 시안에 맞추기 위한 선택적 인용

## 다음 액션

1. 우선 검토 방향에 대해 타깃 5~8인 과제 기반 인터뷰/프로토타입 테스트
2. 작성 플로 A/B: (최소 사진+한줄) vs (스티커 포함)
3. 지도 카드: 사진 강조 vs 테마 스킨 강조
"""
    (ROOT / "design_brief.md").write_text(brief, encoding="utf-8")


def monthly_target_note(agg) -> str:
    return "월×키워드 목표 수량은 collection 설정값이며 본 분석 분모로 사용하지 않음"


if __name__ == "__main__":
    main()
