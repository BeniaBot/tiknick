# -*- coding: utf-8 -*-
"""0.8.6: cache/engine drift, restore fidelity, identity unlink, paging honesty, pooling.

כל בדיקה כאן מייצגת באג שאומת אמפירית מול מאגר אמיתי לפני שתוקן — אם אחת מהן
נשברת, התנהגות שהמשתמש כבר נתקל בה חזרה.
"""
import os, sys, tempfile, shutil, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db
import scraper

tmp = tempfile.mkdtemp(prefix="tiknick_int_")
db.DB_PATH = os.path.join(tmp, "t.db")
db.init_db()
fails = []

def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)

db.add_forum("פ1", "#111", "https://a.example")
db.add_forum("פ2", "#222", "https://b.example")
sid = db.get_scrape_source()["id"]

# ── ה-cache חייב להסכים עם מנוע המקורות ────────────────────────────────
n1 = db.create_nick({"forum": "פ1", "username": "u1"})
db.record_field_value(n1, "full_name", "מהסריקה", sid)
db.bulk_update_field([n1], "full_name", "")
ok("ריקון בפעולה מרובה מכריע מחדש ולא משאיר תצוגה ריקה",
   db.get_nick(n1)["full_name"] == "מהסריקה", repr(db.get_nick(n1)["full_name"]))

n1b = db.create_nick({"forum": "פ1", "username": "u1b"})
db.record_field_value(n1b, "notes", "מהסריקה", sid)
db.record_field_value(n1b, "notes", "שלי", 1)
db.bulk_update_field([n1b], "notes", "")
ok("ריקון מסיר את התרומה שלי ומחזיר את הבאה בתור",
   db.get_nick(n1b)["notes"] == "מהסריקה", repr(db.get_nick(n1b)["notes"]))

# ── שמירת ניק לא נוגעת בעמודות שהטופס לא שלח ──────────────────────────
n2 = db.create_nick({"forum": "פ1", "username": "u2"})
db.merge_scraped_users("פ1", [("u2", {"email": "scr@x.com", "last_seen": "2026-08-30"})], "NodeBB:t")
db.update_nick(n2, {"phone": "0501112222"})       # רק שדה אחד, כמו טופס חלקי
row = db.get_nick(n2)
ok("scraped_email שורד שמירה", row["scraped_email"] == "scr@x.com", repr(row["scraped_email"]))
ok("last_seen שורד שמירה", row["last_seen"] == "2026-08-30", repr(row["last_seen"]))
ok("השדה שנשלח כן נשמר", row["phone"] == "0501112222", repr(row["phone"]))

# ── "אפס עמודות" מוחק באמת, לא רק את התצוגה ───────────────────────────
n3 = db.create_nick({"forum": "פ1", "username": "u3"})
db.record_field_value(n3, "phone", "0509998888", sid)
db.reset_columns(["phone"])
db.resolve_field(n3, "phone")
ok("איפוס עמודה מוחק גם את הערך במנוע ולא רק את ה-cache",
   db.get_nick(n3)["phone"] == "", repr(db.get_nick(n3)["phone"]))

# ── פאנל המקורות מסמן את הערך שבאמת מוצג ──────────────────────────────
n4 = db.create_nick({"forum": "פ1", "username": "u4"})
db.record_field_value(n4, "status", "מורחק", sid)
db.record_field_value(n4, "status", "פעיל", 1)
srcs = db.get_field_sources(n4, "status")
win = [x for x in srcs if x.get("is_winner")]
ok("המנצח מסומן, ולא הראשון לפי אמינות",
   len(win) == 1 and win[0]["value"] == db.get_nick(n4)["status"],
   str([(x["value"], x.get("is_winner")) for x in srcs]))

# ── סל המחזור משמר את ציר הזמן ─────────────────────────────────────────
n5 = db.create_nick({"forum": "פ1", "username": "u5", "status": "פעיל"})
db.record_field_value(n5, "status", "מורחק", sid)
before = len(db.get_field_history(n5))
batch = db.delete_nicks([n5])["batch_id"]
db.restore_trash(batch)
ok("ציר הזמן חוזר אחרי מחיקה ושחזור",
   before > 0 and len(db.get_field_history(n5)) == before,
   f"before={before} after={len(db.get_field_history(n5))}")
ok("הערכים עצמם חזרו", db.get_nick(n5)["status"] == "מורחק", db.get_nick(n5)["status"])

# ── ✕ בזהויות מוציא את מי שלחצו עליו ──────────────────────────────────
a = db.create_nick({"forum": "פ1", "username": "A"})
b = db.create_nick({"forum": "פ2", "username": "B"})
c = db.create_nick({"forum": "פ2", "username": "C"})
db.bulk_link_identities([a, b, c])
db.remove_identity(a, c)                     # פתחתי את A ולחצתי ✕ ליד C
ok("הניק שנלחץ יצא מהקבוצה", db.get_identities(c) == [],
   str([x["username"] for x in db.get_identities(c)]))
ok("הניק הפתוח נשאר מקושר לשאר",
   {x["id"] for x in db.get_identities(a)} == {b},
   str([x["username"] for x in db.get_identities(a)]))

# ── ייבוא לא יוצר כפילויות ─────────────────────────────────────────────
db.import_data({"version": 2, "exported_fields": ["forum", "username", "phone"],
                "nicks": [{"forum": "פ1", "username": "dup", "phone": "050"},
                          {"forum": "פ1", "username": "dup", "phone": "051"}]},
               "t", None, import_name="imp1")
with db.get_connection() as conn:
    dups = conn.execute("SELECT COUNT(*) FROM nicks WHERE forum='פ1' AND username='dup'").fetchone()[0]
ok("אותו (פורום, שם משתמש) פעמיים בקובץ = ניק אחד", dups == 1, f"rows={dups}")

# ── שדה שלא קיים בקובץ ייבוא לא מזהם את מנוע המקורות ─────────────────
db.import_data({"version": 2, "exported_fields": ["forum", "username", "drop_table"],
                "nicks": [{"forum": "פ1", "username": "junkf", "drop_table": "x"}]},
               "t", None, import_name="imp2")
with db.get_connection() as conn:
    junk = conn.execute("SELECT COUNT(*) FROM field_values WHERE field_name='drop_table'").fetchone()[0]
ok("שם שדה לא מוכר מהקובץ נדחה", junk == 0, f"rows={junk}")

# ── פעולות מרובות לא נופלות על בחירה ישנה ─────────────────────────────
gone = db.create_nick({"forum": "פ1", "username": "gone"})
db.delete_nicks([gone])
try:
    n = db.bulk_append_text([gone, n1], "notes", "הערה")
    ok("הוספת הערה מדלגת על ניק שנמחק", n == 1, f"n={n}")
except Exception as e:
    ok("הוספת הערה מדלגת על ניק שנמחק", False, type(e).__name__)
ok("ההערה נרשמה ושרדה הכרעה", "הערה" in (db.get_nick(n1)["notes"] or ""),
   repr(db.get_nick(n1)["notes"]))

# ── נרמול עוגייה: ההדרכה מבקשת ערך בלבד, הכותרת דורשת שם=ערך ──────────
ok("ערך בלבד מקבל שם", scraper.normalize_cookie("s%3Aabc") == "express.sid=s%3Aabc",
   scraper.normalize_cookie("s%3Aabc"))
ok("שם=ערך נשאר כמו שהוא",
   scraper.normalize_cookie("express.sid=s%3Aabc") == "express.sid=s%3Aabc")
ok("Discourse מקבל את השם שלו", scraper.normalize_cookie("abc", "discourse") == "_t=abc")
ok("הדבקה של כמה עוגיות לא נוגעים בה",
   scraper.normalize_cookie("express.sid=a; other=1") == "express.sid=a; other=1")
ok("ריק נשאר ריק", scraper.normalize_cookie("") == "" and scraper.normalize_cookie(None) == "")

# ── מוניטין שירד ל-0 הוא שינוי אמיתי, לא "לא נסרק" ───────────────────
item = {"user": {"username": "d1"}, "likes_received": 0, "post_count": 0}
m = scraper._map_discourse_dir_item(item, "https://d.example")
ok("מוניטין 0 נשמר כ-0 ולא כריק", m["reputation"] == "0", repr(m["reputation"]))

# ── בריכת החיבורים: כל קריאת גשר היא thread חדש ────────────────────────
def call():
    db.get_all_nicks("", limit=5)
for _ in range(5):
    t = threading.Thread(target=call); t.start(); t.join()
with db._pool_lock:
    pooled = len(db._pool)
ok("חיבורים חוזרים לבריכה במקום להיפתח מחדש בכל קריאה", pooled >= 1, f"pool={pooled}")

t0 = time.perf_counter()
for _ in range(40):
    t = threading.Thread(target=call); t.start(); t.join()
per = (time.perf_counter() - t0) / 40 * 1000
ok("קריאת גשר מתחת ל-3ms (בלי בריכה זה היה ~3.4ms)", per < 3.0, f"{per:.2f}ms")


# ── סריקת NodeBB לא סומכת על pageCount ────────────────────────────────
class _FakeDB:
    def __init__(self): self.seen = []
    def merge_scraped_users(self, forum, pairs, source_label=None, run_id=None):
        self.seen += [u for u, _ in pairs]
        return {"added": len(pairs), "updated": 0, "unchanged": 0}

_pages = {}
def _fake_fetch(url, cookie=None):
    page = 1
    if "page=" in url:
        page = int(url.split("page=")[1].split("&")[0])
    users = _pages.get(page, [])
    # השרת משקר: pageCount=1 למרות שיש עוד עמודים
    return {"users": [{"username": u} for u in users], "pagination": {"pageCount": 1}}

_pages.clear()
_pages.update({1: ["a1", "a2"], 2: ["b1", "b2"], 3: ["c1"], 4: []})
_real_fetch, _real_delay = scraper._fetch_json, scraper.PAGE_DELAY_SEC
scraper._fetch_json, scraper.PAGE_DELAY_SEC = _fake_fetch, 0
try:
    fdb = _FakeDB()
    st = scraper._scrape_nodebb("פ1", "https://x.example", fdb, None, None, None, None, None)
    ok("ממשיכים עד עמוד ריק גם כש-pageCount משקר ומחזיר 1",
       fdb.seen == ["a1", "a2", "b1", "b2", "c1"], str(fdb.seen))
    ok("לא דווח שהסריקה הוגבלה", not st.get("limited"), str(st))

    # מקסימום עמודים שהמשתמש הגדיר חייב להיות מדווח, לא להיראות כהשלמה
    fdb2 = _FakeDB()
    st2 = scraper._scrape_nodebb("פ1", "https://x.example", fdb2, None, None, None, 2, None)
    ok("הגבלת עמודים עוצרת בזמן", fdb2.seen == ["a1", "a2", "b1", "b2"], str(fdb2.seen))
    ok("והוגדרה כהגבלה ולא כהשלמה", st2.get("limited") is True, str(st2))
finally:
    scraper._fetch_json, scraper.PAGE_DELAY_SEC = _real_fetch, _real_delay

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("INTEGRITY TESTS PASSED")
shutil.rmtree(tmp, ignore_errors=True)
