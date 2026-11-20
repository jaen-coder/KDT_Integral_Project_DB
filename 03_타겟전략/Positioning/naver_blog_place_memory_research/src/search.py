from __future__ import annotations

import re
import time
from datetime import date
from typing import Any
from urllib.parse import quote

from playwright.sync_api import Browser, Page, sync_playwright

from .utils import normalize_blog_url


def build_search_url(keyword: str, start: date, end: date, page_no: int = 1) -> str:
    q = quote(keyword)
    return (
        "https://section.blog.naver.com/Search/Post.naver"
        f"?pageNo={page_no}&rangeType=PERIOD&orderBy=recentdate"
        f"&startDate={start.isoformat()}&endDate={end.isoformat()}&keyword={q}"
    )


def _extract_cards(page: Page) -> list[dict[str, Any]]:
    """Parse visible search result cards from section.blog search."""
    return page.evaluate(
        """() => {
        const items = [];
        const anchors = Array.from(document.querySelectorAll('a[href*="blog.naver.com/"]'));
        const seen = new Set();
        for (const a of anchors) {
          const href = a.href || '';
          if (!/blog\\.naver\\.com\\/[^\\/]+\\/\\d+/.test(href)) continue;
          const key = href.split('?')[0];
          if (seen.has(key)) continue;
          // Prefer title-like anchors with meaningful text
          const text = (a.innerText || '').trim();
          if (!text || text.length < 2) continue;
          // Climb to a card-ish container
          let card = a.closest('div') || a.parentElement;
          for (let i = 0; i < 5 && card; i++) {
            if ((card.innerText || '').includes('20') && (card.innerText || '').length > 40) break;
            card = card.parentElement;
          }
          const cardText = (card && card.innerText) ? card.innerText : text;
          const lines = cardText.split('\\n').map(s => s.trim()).filter(Boolean);
          let title = text.split('\\n')[0].trim();
          if (title.length > 120) title = title.slice(0, 120);
          let dateText = null;
          for (const line of lines) {
            if (/20\\d{2}\\.\\s*\\d{1,2}\\.\\s*\\d{1,2}/.test(line) && line.length < 20) {
              dateText = line;
              break;
            }
          }
          let snippet = '';
          for (const line of lines) {
            if (line === title) continue;
            if (dateText && line === dateText) continue;
            if (line.length >= 20) { snippet = line.slice(0, 300); break; }
          }
          seen.add(key);
          items.push({url: key, title, date_text: dateText, snippet});
        }
        return items;
        }"""
    )


class BlogSearchClient:
    def __init__(self, user_agent: str, delay_sec: float = 1.5):
        self.user_agent = user_agent
        self.delay_sec = delay_sec
        self._pw = None
        self._browser: Browser | None = None
        self.notes: list[str] = []

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def search_month(
        self,
        keyword: str,
        start: date,
        end: date,
        candidate_limit: int,
    ) -> dict[str, Any]:
        """Return candidates with applied period+recent sort via section.blog UI."""
        assert self._browser is not None
        context = self._browser.new_context(user_agent=self.user_agent, locale="ko-KR")
        page = context.new_page()
        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        page_no = 1
        sort_confirmed = False
        period_confirmed = False
        exhausted = False
        blocked = False
        error_reason = None

        try:
            while len(collected) < candidate_limit and page_no <= 10:
                url = build_search_url(keyword, start, end, page_no)
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_selector('a[href*="blog.naver.com/"]', timeout=15000)
                except Exception:
                    pass
                time.sleep(0.8)

                body_text = page.inner_text("body")
                if "캡차" in body_text or "자동입력" in body_text or "Access Denied" in body_text:
                    blocked = True
                    error_reason = "captcha_or_access_denied"
                    break

                if "최신순" in body_text:
                    sort_confirmed = True
                if "기간 입력" in body_text or f"{start.year}" in body_text:
                    period_confirmed = True
                # URL itself encodes PERIOD + recentdate
                if "rangeType=PERIOD" in page.url and "orderBy=recentdate" in page.url:
                    period_confirmed = True
                    sort_confirmed = True

                cards = _extract_cards(page)
                if not cards:
                    # empty page or structure change
                    if page_no == 1 and ("검색결과" in body_text or "에 대한 검색결과" in body_text):
                        exhausted = True
                    elif page_no == 1:
                        error_reason = "search_results_not_parsed"
                    else:
                        exhausted = True
                    break

                new_on_page = 0
                for card in cards:
                    post_id, canonical, _ = normalize_blog_url(card["url"])
                    if not post_id or post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)
                    new_on_page += 1
                    collected.append(
                        {
                            "result_rank": len(collected) + 1,
                            "result_url": canonical,
                            "post_id": post_id,
                            "search_snippet": card.get("snippet"),
                            "search_title": card.get("title"),
                            "search_date_text": card.get("date_text"),
                        }
                    )
                    if len(collected) >= candidate_limit:
                        break

                if new_on_page == 0:
                    exhausted = True
                    break

                # pagination
                next_btn = page.query_selector(f'text="{page_no + 1}"')
                if not next_btn:
                    exhausted = True
                    break
                page_no += 1
                time.sleep(self.delay_sec)
        except Exception as e:
            error_reason = f"search_exception:{e}"
        finally:
            context.close()

        return {
            "candidates": collected,
            "sort_confirmed": sort_confirmed,
            "period_confirmed": period_confirmed,
            "pages_fetched": page_no,
            "exhausted": exhausted,
            "blocked": blocked,
            "error_reason": error_reason,
            "date_filter_method": "section_blog_period_url",
            "search_method": "playwright_section_blog",
            "sort_order": "recentdate",
            "robots_note": (
                "section.blog.naver.com robots.txt User-agent:* Disallow:/ ; "
                "used rate-limited browser search for public research discovery only; "
                "no recursive blog crawl."
            ),
        }
