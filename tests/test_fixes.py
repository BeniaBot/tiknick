# -*- coding: utf-8 -*-
"""Tests for the review-driven fixes: stinknik slug variants + detect_platform ordering."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("FIX TESTS PASSED")
