# -*- coding: utf-8 -*-
"""בדיקות ל-0.8.2: עוגיות, תצוגה מאוחדת, מצבי ייצוא, פלטפורמות, Discourse."""
import os, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db
import scraper

tmpdir = tempfile.mkdtemp(prefix="tiknick_b2_")
db.DB_PATH = os.path.join(tmpdir, "test.db")
db.init_db()

fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# ── 1. עוגיות לפי origin ─────────────────────────────────────────────
db.save_cookie_for_url("https://mitmachim.top/", "express.sid=abc")
check("cookie by origin (trailing slash)", db.get_cookie_for_url("https://mitmachim.top") == "express.sid=abc")
check("cookie by origin (with path)", db.get_cookie_for_url("https://mitmachim.top/user/x") == "express.sid=abc")
check("cookie other origin empty", db.get_cookie_for_url("https://bina.top") == "")
db.save_cookie_for_url("https://mitmachim.top", "")   # ריקון מוחק
check("empty cookie deletes", db.get_cookie_for_url("https://mitmachim.top") == "")

# ── 2. פלטפורמות בפורומים מוכרים ─────────────────────────────────────
db.add_forum("פורום לתורה")   # מ-KNOWN — xenforo
db.add_forum("פורום ימות המשיח")  # מ-KNOWN — nodebb
db.add_forum("פורום אוצר החכמה")  # phpbb + profile_pattern
check("known xenforo platform", db.get_forum_platform("פורום לתורה") == "xenforo",
      db.get_forum_platform("פורום לתורה"))
check("known nodebb platform", db.get_forum_platform("פורום ימות המשיח") == "nodebb")
forums = {f["name"]: f for f in db.get_forums()}
check("phpbb profile_pattern stored", "memberlist.php" in (forums["פורום אוצר החכמה"].get("profile_pattern") or ""),
      forums["פורום אוצר החכמה"].get("profile_pattern"))
check("set_forum_platform_by_url", (
    db.set_forum_platform_by_url(forums["פורום לתורה"]["url"], "discourse") or
    db.get_forum_platform("פורום לתורה") == "discourse"))

# ── 3. סריקת Discourse (fetch מזויף) ─────────────────────────────────
db.add_forum("דיסקורס טסט", "#123456", "https://disc.example")
_orig_fetch = scraper._fetch_json
def _fake_fetch(url, cookie=None):
    if "directory_items" in url and "page=0" in url:
        return {"total_rows_directory_items": 2, "directory_items": [
            {"user": {"username": "avi", "name": "אבי כהן", "id": 5,
                      "avatar_template": "/user_avatar/disc.example/avi/{size}/5.png"},
             "likes_received": 42, "post_count": 130},
            {"user": {"username": "beni", "name": "בני לוי", "id": 6,
                      "avatar_template": "/user_avatar/disc.example/beni/{size}/6.png"},
             "likes_received": 7, "post_count": 12},
        ]}
    return {"directory_items": []}
scraper._fetch_json = _fake_fetch
try:
    stats = scraper.scrape_forum("דיסקורס טסט", "https://disc.example", db,
                                 platform="discourse")
    check("discourse scrape 2 added", stats.get("added") == 2, str(stats))
    avi = db.find_nick("דיסקורס טסט", "avi")
    check("discourse mapped full_name", avi and avi["full_name"] == "אבי כהן", avi and avi["full_name"])
    check("discourse mapped reputation", avi and str(avi["reputation"]) == "42", avi and avi["reputation"])
    check("discourse avatar absolute url", avi and avi["avatar_url"].startswith("https://disc.example/"),
          avi and avi["avatar_url"])
finally:
    scraper._fetch_json = _orig_fetch

# ── 4. דיספאטץ' פלטפורמה לא נתמכת ────────────────────────────────────
try:
    scraper.scrape_forum("פורום לתורה", "https://tora-forum.co.il", db, platform="xenforo")
    check("xenforo raises", False, "no exception")
except scraper.ScrapeError as e:
    check("xenforo raises ScrapeError", "XenForo" in str(e) or "אוטומטית" in str(e), str(e))

# ── 5. תצוגת משתמש מאוחדת ────────────────────────────────────────────
db.add_forum("פורום א", "#111", "https://a.example")
db.add_forum("פורום ב", "#222", "https://b.example")
id1 = db.create_nick({"forum": "פורום א", "username": "moshe1", "real_name": "משה", "phone": "050"})
id2 = db.create_nick({"forum": "פורום ב", "username": "moshe2", "email": "m@x.com", "address": "בני ברק"})
db.add_identity(id1, id2)
db.add_contact(id2, "phone", "052-999", "עבודה", 0)
prof = db.get_merged_profile(id1)
check("merged has 2 members", len(prof["members"]) == 2, str(len(prof["members"])))
field_keys = {f["key"] for f in prof["fields"]}
check("merged gathers real_name", "real_name" in field_keys)
check("merged gathers email from other identity", "email" in field_keys)
check("merged gathers address from other identity", "address" in field_keys)
check("merged contacts included", len(prof["contacts"]) == 1, str(len(prof["contacts"])))

# lookup search
res = db.search_nicks_for_lookup("moshe")
check("lookup finds both", len(res) == 2, str(len(res)))
res2 = db.search_nicks_for_lookup("משה")
check("lookup by real_name", any(r["username"] == "moshe1" for r in res2))

# ── 6. מצבי ייצוא (all / has_info / my_info) ─────────────────────────
# ניק בלי מידע (רק מסריקה) — לא has_info ולא my_info
scrape_sid = db.get_scrape_source()["id"]
id3 = db.create_nick({"forum": "פורום א", "username": "scraped_only"})
db.record_field_value(id3, "post_count", "50", scrape_sid)   # ערך מסריקה בלבד
counts = db.count_export_modes()
check("count all >= 3", counts["all"] >= 3, str(counts))
# has_info: moshe1 (real_name/phone), moshe2 (email/address+contact+identity) → כלולים; scraped_only → לא
exp_info = db.export_data("has_info")
names_info = {n["username"] for n in exp_info["nicks"]}
check("has_info includes moshe1", "moshe1" in names_info)
check("has_info excludes scraped_only", "scraped_only" not in names_info, str(names_info))
# my_info: moshe1/moshe2 יש בהם ערכי "אני"; scraped_only אין
exp_mine = db.export_data("my_info")
names_mine = {n["username"] for n in exp_mine["nicks"]}
check("my_info includes moshe1", "moshe1" in names_mine)
check("my_info excludes scraped_only", "scraped_only" not in names_mine, str(names_mine))
check("all includes scraped_only", "scraped_only" in {n["username"] for n in db.export_data("all")["nicks"]})

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("ALL BATCH-2 TESTS PASSED")
shutil.rmtree(tmpdir, ignore_errors=True)
