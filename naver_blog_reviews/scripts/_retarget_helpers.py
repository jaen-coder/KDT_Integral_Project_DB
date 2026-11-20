from pathlib import Path

files = [
    Path(__file__).with_name("merge_alexandria_pages.py"),
    Path(__file__).with_name("finalize_outputs.py"),
]
for p in files:
    t = p.read_text(encoding="utf-8")
    t = t.replace("Instagram", "네이버 블로그")
    t = t.replace("com.instagram.android", "com.nhn.android.blog")
    t = t.replace("389801252", "328813873")
    t = t.replace("instagram_google_play.csv", "naver_blog_google_play.csv")
    t = t.replace("instagram_app_store.csv", "naver_blog_app_store.csv")
    t = t.replace("instagram_reviews_all.csv", "naver_blog_reviews_all.csv")
    t = t.replace(
        "https://apps.apple.com/kr/app/instagram/id328813873",
        "https://apps.apple.com/kr/app/id328813873",
    )
    t = t.replace(
        "https://apps.apple.com/kr/app/instagram/id",
        "https://apps.apple.com/kr/app/id",
    )
    p.write_text(t, encoding="utf-8")
    print("ok", p.name)
