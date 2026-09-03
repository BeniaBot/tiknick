# -*- coding: utf-8 -*-
"""
0.8.11: התיקונים מהביקורת האדוורסרית על 0.8.6–0.8.10.

כל בדיקה כאן מייצגת ממצא שאומת בשחזור לפני שתוקן. הראשונה היא החשובה:
מאגר שנוצר ב-0.8.8 פשוט לא נפתח אחרי עדכון, כלומר המשתמש נעול מחוץ לתוכנה.
"""
import os, sys, tempfile, shutil, sqlite3
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db
import profile_sheet as ps
import chazonishnik as chz

tmp = tempfile.mkdtemp(prefix="tiknick_a11_")
fails = []

def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)

def fresh(name):
    db.close_pool()
    db.DB_PATH = os.path.join(tmp, name)
    db.init_db()

# ══ מיגרציה: מאגר מ-0.8.8 חייב להיפתח ═══════════════════════════════════
fresh("as088.db")
db.add_forum("פ1", "#111", "")
n = db.create_nick({"forum": "פ1", "username": "u1"})
db.touch_recent(n)
with db.get_connection() as conn:
    conn.executescript("""
        DROP INDEX IF EXISTS idx_recent_seq;
        DROP TABLE recent_views;
        CREATE TABLE recent_views (
            nick_id INTEGER PRIMARY KEY,
            viewed_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
            FOREIGN KEY (nick_id) REFERENCES nicks(id) ON DELETE CASCADE);""")
    conn.execute("INSERT INTO recent_views (nick_id) VALUES (?)", (n,))
path088 = db.DB_PATH
db.close_pool()
db.DB_PATH = path088
try:
    db.init_db()
    opened = True
except Exception as e:
    opened = False
    detail = str(e)
ok("מאגר מ-0.8.8 נפתח אחרי עדכון", opened, detail if not opened else "")
if opened:
    with db.get_connection() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(recent_views)")}
        idx = conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' "
                           "AND name='idx_recent_seq'").fetchone()
        kept = conn.execute("SELECT COUNT(*) FROM recent_views").fetchone()[0]
    ok("עמודת seq נוספה במיגרציה", "seq" in cols)
    ok("האינדקס נוצר אחרי העמודה", bool(idx))
    ok("הנתונים הקיימים נשמרו", kept == 1)
    ok("touch_recent עובד אחרי המיגרציה", db.touch_recent(n) is True)

# ══ שחזור: גיבוי שלא נטען לא הורס את המאגר החי ═══════════════════════════
fresh("live.db")
db.add_forum("פ1", "#111", "")
for i in range(4):
    db.create_nick({"forum": "פ1", "username": "live%d" % i})
good = os.path.join(tmp, "good.db")
db.backup_to(good)
db.create_nick({"forum": "פ1", "username": "extra"})
ok("שחזור מגיבוי תקין עובד",
   db.restore_from(good) and db.get_all_nicks("")["total"] == 4,
   str(db.get_all_nicks("")["total"]))

bad = os.path.join(tmp, "bad.db")
c = sqlite3.connect(bad)
c.executescript("CREATE TABLE nicks (id INTEGER PRIMARY KEY, forum TEXT, username TEXT);")
c.commit(); c.close()
before = db.get_all_nicks("")["total"]
try:
    db.restore_from(bad)
    ok("גיבוי שלא נטען נדחה", False, "התקבל")
except ValueError as e:
    ok("גיבוי שלא נטען נדחה עם הסבר בעברית", "לא בוצע שחזור" in str(e), str(e)[:60])
ok("המאגר החי שרד את הדחייה", db.get_all_nicks("")["total"] == before, str(before))

# ══ גיבוי חלקי לא נספר ולא מפנה מקום לגיבוי טוב ═══════════════════════════
r = db.auto_backup("t", force=True)
ok("גיבוי תקין נוצר", r["ok"] and os.path.exists(r["path"]))
ok("לא נשארו קבצי .part", not any(x.endswith(".part") for x in os.listdir(db.backup_dir())))
junk = os.path.join(db.backup_dir(), "tiknick-junk-20260101-000000.db")
open(junk, "wb").write(b"x" * 40)
open(junk + "-wal", "wb").write(b"")
ok("קובץ עם -wal לצידו לא נספר כגיבוי",
   not any("junk" in f["name"] for f in db.list_backups()),
   str([f["name"] for f in db.list_backups()]))

# ══ שינוי שם פורום נושא איתו את ההגדרות ═══════════════════════════════════
fresh("rename.db")
db.add_forum("ישן", "#111", "https://a.example")
db.set_forum_io_flag("ישן", False)
db.set_setting("last_scrape_ישן", (datetime.utcnow() - timedelta(hours=2)).isoformat(timespec="minutes"))
db.set_schedule(enabled=True, forums=["ישן"], mode="interval", every_hours=12)
fid = [f["id"] for f in db.get_forums() if f["name"] == "ישן"][0]
db.update_forum(fid, "חדש", "#111", "https://a.example")
ok("החרגה מייצוא נשארת אחרי שינוי שם",
   db.get_forum_io_flags().get("חדש") is False, str(db.get_forum_io_flags()))
ok("חותמת הסריקה עוברת עם השם", db.get_setting("last_scrape_חדש", "") != "")
ok("רצפת 12 השעות לא נעקפת אחרי שינוי שם", db.sched_due_forums() == [],
   str(db.sched_due_forums()))
ok("הפורום נשאר בתזמון תחת השם החדש", "חדש" in db.get_schedule()["forums"],
   str(db.get_schedule()["forums"]))

# ══ התזמון לא מציע פלטפורמה שהסורק מסרב לה ════════════════════════════════
fresh("plat.db")
db.add_forum("נודבב", "#111", "https://a.example")
db.add_forum("זנפורו", "#222", "https://b.example")
with db.get_connection() as conn:
    conn.execute("UPDATE forums SET platform='xenforo' WHERE name='זנפורו'")
db.set_schedule(enabled=True, forums=["נודבב", "זנפורו"], mode="interval", every_hours=12)
due = db.sched_due_forums()
ok("XenForo לא נכנס לתור הסריקה", "זנפורו" not in due, str(due))
ok("NodeBB כן", "נודבב" in due, str(due))

# ══ הגיליון המודפס: הכותרת מוברחת ═════════════════════════════════════════
evil = "</title><img src=https://forum/track.png>"
sheet = ps.build_sheet({"nick": {"username": evil}, "members": [], "fields": [],
                        "contacts": [], "history": [],
                        "truncated_members": 0, "truncated_history": 0}, generated="x")
ok("כותרת הגיליון מוברחת", "</title><img" not in sheet)
# הכתובת עדיין מופיעה — אבל כטקסט מוברח בתוך הכותרת, לא כהפניה חיה
ok("אין בגיליון הפניה חיצונית חיה",
   'src="http' not in sheet and "src='http" not in sheet
   and 'href="http' not in sheet and "url(http" not in sheet)
ok("והכתובת העוינת מופיעה כטקסט בלבד", "&lt;img src=https://forum/track.png&gt;" in sheet)

# ══ דוח ההשוואה: בריחה, והמסקנה לא מחושבת ממספרים חתוכים ═════════════════
posts = [{"pid": i, "title": "נושא", "ts": i, "date": "2026-01-01", "hour": 9,
          "day": "שני", "month": "2026-01", "likes": 1, "voters": [], "words": 30}
         for i in range(1, 6)]
st = chz._summarize(posts)
a = {"slug": "<img src=x onerror=alert(1)>", "uid": 1, "posts": posts, "stats": st,
     "meta": {"postcount": 5000, "partial": False, "limited": True, "stopped_early": False}}
b = {"slug": "שני", "uid": 2, "posts": posts, "stats": st,
     "meta": {"postcount": 100, "partial": False, "limited": True, "stopped_early": False}}
html = chz._build_compare_html("https://x.example", a, b)
ok("לדוח ההשוואה יש פונקציית בריחה", "function esc(v)" in html)
ok("שם המשתמש בטבלה מוברח", "esc(A.user)" in html)
ok("המסקנה מחושבת מסך הפוסטים ולא מהחתוך", "A.meta.postcount" in html)
ok("והדוח אומר על מה הוא מבוסס", "לפי סך הפוסטים בפורום" in html)
ok("וגם שההשוואה עצמה מוגבלת", "לפי ההגבלה שהגדרת" in html)

# ══ קידודים: כל מסלול נבדק, כולל UTF-16 בלי BOM שמתחיל בעברית ══════════
import csv_import as ci

_TAB = chr(9)
_NL = chr(10)
_HE = "שם משתמש" + _TAB + "טלפון" + _NL + "דוד" + _TAB + "0501234567" + _NL
_EN = "user" + _TAB + "phone" + _NL + "david" + _TAB + "050" + _NL

enc_tmp = tempfile.mkdtemp()
for enc, text, label in [
    ("utf-16-le", _HE, "UTF-16 LE עברית"),
    ("utf-16-be", _HE, "UTF-16 BE עברית"),
    ("utf-16-le", _EN, "UTF-16 LE אנגלית"),
    ("utf-16-be", _EN, "UTF-16 BE אנגלית"),
]:
    fp = os.path.join(enc_tmp, label.replace(" ", "_") + ".txt")
    open(fp, "wb").write(text.encode(enc))
    r = ci.parse_file(fp)
    ok("%s מפוענח נכון" % label,
       r["encoding"] == enc and r["headers"][0] in ("שם משתמש", "user"),
       "%s %r" % (r["encoding"], r["headers"][0]))

import io as _io
for enc in ("utf-8", "cp1255", "utf-8-sig"):
    fp = os.path.join(enc_tmp, "x_%s.csv" % enc)
    _io.open(fp, "w", encoding=enc, newline="").write(
        "שם משתמש,טלפון" + _NL + "דוד,050" + _NL)
    r = ci.parse_file(fp)
    ok("%s עדיין מפוענח נכון" % enc,
       r["encoding"] == enc and r["headers"][0] == "שם משתמש",
       "%s %r" % (r["encoding"], r["headers"][0]))

def _phone(v):
    return ci.normalize_rows(["שם משתמש", "טלפון"], [["u", v]],
                             {"0": "username", "1": "phone"})["nicks"][0].get("phone")

ok("אפס מוביל מוחזר לנייד", _phone("501234567") == "0501234567", _phone("501234567"))
ok("מספר 9 ספרות שאינו קידומת ישראלית לא נוגעים בו",
   _phone("712345678") == "712345678", _phone("712345678"))
ok("מספר 8 ספרות לא נוגעים בו", _phone("21234567") == "21234567")

try:
    ci.normalize_rows(["a", "b"], [["1", "2"]], {"0": "username", "1": "username"})
    ok("שתי עמודות לאותו שדה נעצרות", False, "לא נעצר")
except ValueError as e:
    ok("שתי עמודות לאותו שדה נעצרות עם הסבר", "אותו שדה" in str(e), str(e)[:50])

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("AUDIT-0811 TESTS PASSED")
db.close_pool()
shutil.rmtree(tmp, ignore_errors=True)
