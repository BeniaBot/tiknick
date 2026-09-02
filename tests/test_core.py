# -*- coding: utf-8 -*-
"""בדיקות פונקציונליות + מדידת ביצועים ל-database.py המשופר של Tik-Nick."""
import os, sys, time, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
import database as db

tmpdir = tempfile.mkdtemp(prefix="tiknick_test_")
db.DB_PATH = os.path.join(tmpdir, "test.db")
db.init_db()

fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        fails.append(name)

FORUM = "מתמחים טופ"
db.add_forum(FORUM, "#5865f2", "https://mitmachim.top")

# ── 1. מיזוג עמוד: יצירה ─────────────────────────────────────────────
page = [
    (f"user{i}", {
        "full_name": f"שם {i}", "reputation": 10 + i, "post_count": str(100 + i),
        "groups": "חברים", "status": "", "join_date": "2024-01-01",
        "avatar_url": f"https://x/{i}.png", "extra_info": f"מיקום: עיר {i}",
        "email": f"u{i}@x.com", "forum_uid": str(i),
    }) for i in range(50)
]
st = db.merge_scraped_users(FORUM, page, "NodeBB:טסט")
check("page create: 50 added", st == {"added": 50, "updated": 0, "unchanged": 0}, str(st))

n = db.find_nick(FORUM, "user7")
check("cache resolved (full_name)", n["full_name"] == "שם 7", n["full_name"])
check("cache resolved (reputation)", str(n["reputation"]) == "17", str(n["reputation"]))
check("trust_level=4 for scraped", n["trust_level"] == 4, str(n["trust_level"]))
check("scraped_email set on create", n["scraped_email"] == "u7@x.com", n["scraped_email"])

# ── 2. סריקה חוזרת זהה: הכול unchanged ───────────────────────────────
st2 = db.merge_scraped_users(FORUM, page, "NodeBB:טסט")
check("rescan identical: 50 unchanged", st2 == {"added": 0, "updated": 0, "unchanged": 50}, str(st2))

# ── 3. שינוי שדה אחד: רק הוא updated ────────────────────────────────
page[3][1]["full_name"] = "שם חדש"
st3 = db.merge_scraped_users(FORUM, page, "NodeBB:טסט")
check("rescan 1 change: 1 updated 49 unchanged",
      st3 == {"added": 0, "updated": 1, "unchanged": 49}, str(st3))
check("changed value resolved", db.find_nick(FORUM, "user3")["full_name"] == "שם חדש")

# ── 4. כללי הכרעה: אני (10) מול סריקה (9) ────────────────────────────
nid = db.find_nick(FORUM, "user5")["id"]
db.record_field_value(nid, "full_name", "ידני שלי", 1)  # מקור "אני"
check("me(10) beats scrape(9)", db.get_nick(nid)["full_name"] == "ידני שלי")

# status: סריקה אבסולוטית — גוברת גם על "אני"
db.record_field_value(nid, "status", "פעיל", 1)
st_page = [("user5", {"status": "מורחק"})]
db.merge_scraped_users(FORUM, st_page, "NodeBB:טסט")
check("status: scrape absolute beats me", db.get_nick(nid)["status"] == "מורחק",
      db.get_nick(nid)["status"])

# reputation: רק סריקה נחשבת, החדש מנצח
db.record_field_value(nid, "reputation", "999", 1)   # "אני" — צריך להתעלם
check("reputation ignores 'me'", str(db.get_nick(nid)["reputation"]) == "15",
      str(db.get_nick(nid)["reputation"]))
time.sleep(1.1)  # created_at ברזולוציית שנייה — ודא שהחדש באמת חדש
db.merge_scraped_users(FORUM, [("user5", {"reputation": 500})], "NodeBB:טסט")
check("reputation newest scrape wins", str(db.get_nick(nid)["reputation"]) == "500",
      str(db.get_nick(nid)["reputation"]))

# ── 5. force_scraped_values: הסרוק מנצח למרות אמינות "אני" ───────────
cnt = db.force_scraped_values(nid, {"full_name": "מהאינטרנט", "post_count": "777"})
check("force writes 2 fields", cnt == 2, str(cnt))
check("forced value shown despite me(10)", db.get_nick(nid)["full_name"] == "מהאינטרנט")

# ── 6. ריקון ידני מחזיר את הערך הבא באמינות ─────────────────────────
# (ערך הסריקה השמור עודכן ל"מהאינטרנט" ע"י force_scraped_values — הוא הבא בתור)
full = db.get_nick(nid)
data = {f: full.get(f, "") for f in db._NICK_FIELDS if f != "source"}
data["full_name"] = ""   # ריקון ידני
db.update_nick(nid, data)
check("clearing my value falls back to scrape", db.get_nick(nid)["full_name"] == "מהאינטרנט",
      db.get_nick(nid)["full_name"])

# ── 7. ייבוא במצב ידני (אחרי תיקון ה-N+1) ────────────────────────────
imp = {"version": 2, "exported_fields": ["forum", "username", "full_name", "phone"],
       "nicks": [{"forum": FORUM, "username": "user9", "full_name": "שם אחר", "phone": "050"},
                 {"forum": FORUM, "username": "חדשניק", "full_name": "פלוני", "phone": ""}]}
res = db.import_data(imp, "קובץ טסט", {}, import_name="טסט", import_trust=6, manual_conflicts=True)
check("manual import: 1 new nick", res["imported"] == 1, str(res))
confs = res["conflicts"]
check("manual import: conflict on full_name", any(c["field"] == "full_name" for c in confs), str(confs))
check("manual import: phone (empty old) not a conflict", all(c["field"] != "phone" for c in confs))

# ── 8. FTS עדיין מסונכרן אחרי מיזוג עמוד + עמודות החיפוש החדשות ──────
hits = db.get_all_nicks("חדשניק")
check("FTS finds imported nick", hits["total"] == 1, str(hits["total"]))
hits2 = db.get_all_nicks("שם חדש")
check("FTS finds full_name (new search col)", hits2["total"] >= 1, str(hits2["total"]))

# ── 8ב. מיגרציית FTS: סכימה ישנה (בלי full_name) נבנית מחדש אוטומטית ──
with db.get_connection() as _c:
    _c.executescript("""
        DROP TRIGGER IF EXISTS nicks_fts_ai; DROP TRIGGER IF EXISTS nicks_fts_ad;
        DROP TRIGGER IF EXISTS nicks_fts_au; DROP TABLE IF EXISTS nicks_fts;
        CREATE VIRTUAL TABLE nicks_fts USING fts5(
            username, real_name, phone, email, notes, groups, forum, extra_info, private_notes,
            content='nicks', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2');
    """)
db._init_fts()   # אמור לזהות סכימה ישנה, לבנות מחדש ולמלא
hits3 = db.get_all_nicks("שם חדש")
check("FTS migration rebuilds with full_name", hits3["total"] >= 1, str(hits3["total"]))

# ── 9. מדד ביצועים: מסלול ישן (שדה-שדה) מול עמוד-אחד ────────────────
BN, BF = 300, 9
def bench_old(forum):
    src = db.get_scrape_source()["id"]
    t0 = time.perf_counter()
    for i in range(BN):
        uname = f"old{i}"
        ex = db.find_nick(forum, uname)
        if not ex:
            db.create_nick({"forum": forum, "username": uname, "source": "x", "trust_level": 4})
            ex = db.find_nick(forum, uname)
        for j in range(BF):
            db.record_field_value(ex["id"], ["full_name","groups","post_count","join_date",
                "avatar_url","extra_info","forum_uid","address","nick_color"][j], f"v{i}-{j}", src)
    return time.perf_counter() - t0

def bench_new(forum):
    users = [(f"new{i}", {k: f"v{i}-{j}" for j, k in enumerate(
        ["full_name","groups","post_count","join_date","avatar_url",
         "extra_info","forum_uid","address","nick_color"])}) for i in range(BN)]
    t0 = time.perf_counter()
    db.merge_scraped_users(forum, users, "bench")
    return time.perf_counter() - t0

db.add_forum("בנץ׳", "#111111", "")
t_old = bench_old("בנץ׳")
t_new = bench_new("בנץ׳")
print(f"\nBENCH  {BN} users x {BF} fields")
print(f"  old per-field path : {t_old:.2f}s")
print(f"  new page batch     : {t_new:.2f}s")
print(f"  speedup            : x{t_old / max(t_new, 1e-9):.1f}")

# סריקה חוזרת (המקרה הנפוץ ביותר) — עם זיהוי השינויים
users2 = [(f"new{i}", {k: f"v{i}-{j}" for j, k in enumerate(
    ["full_name","groups","post_count","join_date","avatar_url",
     "extra_info","forum_uid","address","nick_color"])}) for i in range(BN)]
t0 = time.perf_counter()
r = db.merge_scraped_users("בנץ׳", users2, "bench")
t_re = time.perf_counter() - t0
print(f"  rescan (no changes): {t_re:.2f}s  ({r})")

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("ALL TESTS PASSED")
shutil.rmtree(tmpdir, ignore_errors=True)
