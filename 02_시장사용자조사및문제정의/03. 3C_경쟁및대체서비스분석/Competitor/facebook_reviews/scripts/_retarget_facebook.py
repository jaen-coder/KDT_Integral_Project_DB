from pathlib import Path

ROOT = Path(__file__).resolve().parent
repls = [
    ("Naver Blog review collector", "Facebook review collector"),
    ("네이버 블로그", "Facebook"),
    ("com.nhn.android.blog", "com.facebook.katana"),
    ("328813873", "284882215"),
    ("naver_blog_google_play.csv", "facebook_google_play.csv"),
    ("naver_blog_app_store.csv", "facebook_app_store.csv"),
    ("naver_blog_reviews_all.csv", "facebook_reviews_all.csv"),
]
for p in ROOT.glob("*.py"):
    if p.name.startswith("_"):
        continue
    t = p.read_text(encoding="utf-8")
    for a, b in repls:
        t = t.replace(a, b)
    # keep hl=ko on play source if present
    t = t.replace(
        "id=com.facebook.katana&hl=ko&hl=ko",
        "id=com.facebook.katana&hl=ko",
    )
    p.write_text(t, encoding="utf-8")
    print("ok", p.name)
