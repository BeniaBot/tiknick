# -*- coding: utf-8 -*-
"""Tests for the review-driven fixes: stinknik slug variants + detect_platform ordering."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
import scraper, stinknik
from scraper import AuthRequired, ScrapeError

fails = []
def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond: fails.append(name)

# ── stinknik._resolve_slug: username lookup fails, hyphen variant resolves ──
def mk_get(handler):
    return handler
orig = stinknik._get_json
def fake_get(url, cookie=None, timeout=15):
    # username endpoint fails
    if "/api/user/username/" in url:
        raise Exception("404")
    # /api/user/{slug}: only the hyphenated slug resolves
    if url.endswith("/api/user/Some%20Name"):
        raise Exception("404")
    if url.endswith("/api/user/Some-Name"):
        return {"uid": 5, "userslug": "some-name"}
    raise Exception("404")
stinknik._get_json = fake_get
try:
    slug = stinknik._resolve_slug("https://x", "Some Name")
    ok("stinknik resolves hyphen variant", slug == "some-name", slug)
finally:
    stinknik._get_json = orig

# ── detect_platform: nodebb AuthRequired but site is Discourse → 'discourse' ──
orig2 = scraper._fetch_json
def fake_fetch_discourse_authwall(url, cookie=None):
    if "/api/users" in url:
        raise AuthRequired("403")           # nodebb probe blocked
    if "directory_items" in url:
        return {"directory_items": [], "total_rows_directory_items": 0}  # discourse present
    raise ScrapeError("nope")
scraper._fetch_json = fake_fetch_discourse_authwall
try:
    ok("detect: nodebb-auth + discourse => discourse",
       scraper.detect_platform("https://x") == "discourse")
finally:
    scraper._fetch_json = orig2

# ── detect_platform: nodebb AuthRequired, discourse absent → 'nodebb' ──
def fake_fetch_nodebb_authwall(url, cookie=None):
    if "/api/users" in url:
        raise AuthRequired("403")
    raise ScrapeError("404")   # discourse not present
scraper._fetch_json = fake_fetch_nodebb_authwall
try:
    ok("detect: nodebb-auth + no discourse => nodebb",
       scraper.detect_platform("https://x") == "nodebb")
finally:
    scraper._fetch_json = orig2

# ── detect_platform: nothing → unknown ──
def fake_fetch_nothing(url, cookie=None):
    raise ScrapeError("404")
scraper._fetch_json = fake_fetch_nothing
try:
    ok("detect: nothing => unknown", scraper.detect_platform("https://x") == "unknown")
finally:
    scraper._fetch_json = orig2


# ── 0.8.4: stinknik/chazonishnik honest scan reporting ──
import json as _json
def _fake_posts(nposts, per=20):
    pages = {}
    for i in range(0, nposts, per):
        pages[i // per + 1] = [{"pid": 1000 + j, "upvotes": 0, "downvotes": (1 if j % 50 == 0 else 0),
                                "votes": 0, "topic": {"title": "נושא"}, "timestamp": 0}
                               for j in range(i, min(i + per, nposts))]
    return pages

_orig = stinknik._get_json
def _mk(pagesmap, postcount, fail_at=None):
    def f(url, cookie=None, timeout=15, retries=3):
        if "/api/user/username/" in url:
            return {"userslug": "u", "uid": 1, "postcount": postcount}
        if "/posts?page=" in url:
            p = int(url.rsplit("page=", 1)[1])
            if fail_at and p >= fail_at:
                raise Exception("network blip")
            return {"posts": pagesmap.get(p, [])}
        raise Exception("404")
    return f

stinknik._get_json = _mk(_fake_posts(100), 100)
try:
    r = stinknik.analyze_dislikes("u")
    ok("stinknik scans all pages", r["checked"] == 100, str(r["checked"]))
    ok("stinknik reports postcount", r["postcount"] == 100)
    ok("full scan is not partial", r["partial"] is False, str(r))
finally:
    stinknik._get_json = _orig

# guest sees only part of the posts -> must be reported as partial
stinknik._get_json = _mk(_fake_posts(100), 500)
try:
    r = stinknik.analyze_dislikes("u")
    ok("partial when postcount >> scanned", r["partial"] is True and r["stopped_early"] is False, str(r))
finally:
    stinknik._get_json = _orig

# network failure mid-scan -> stopped_early, never silently "complete"
stinknik._get_json = _mk(_fake_posts(200), 200, fail_at=4)
try:
    r = stinknik.analyze_dislikes("u")
    ok("stopped_early on mid-scan failure", r["stopped_early"] is True and r["partial"] is True, str(r))
    ok("still returns the partial data", r["ok"] and r["checked"] == 60, str(r["checked"]))
finally:
    stinknik._get_json = _orig

# explicit max_posts -> limited, not flagged as a failure
stinknik._get_json = _mk(_fake_posts(500), 500)
try:
    r = stinknik.analyze_dislikes("u", max_posts=40)
    ok("max_posts marked limited not partial", r["limited"] is True and r["partial"] is False, str(r))
finally:
    stinknik._get_json = _orig

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("FIX TESTS PASSED")
