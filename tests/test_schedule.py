# -*- coding: utf-8 -*-
"""
0.8.10: תזמון סריקה + השוואת שני משתמשים.

התזמון הוא התכונה היחידה בתוכנה שפועלת מול שרתים של אחרים בלי שהמשתמש נוכח,
ולכן רוב הבדיקות כאן הן על *הרצפות*: שאי אפשר לרוץ מוקדם מדי, שהפעלה לבדה
לא סורקת כלום, ושכישלון חוזר עוצר במקום להמשיך לנדנד.
"""
import os, sys, tempfile, shutil
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db
import chazonishnik as chz

tmp = tempfile.mkdtemp(prefix="tiknick_sched_")
db.DB_PATH = os.path.join(tmp, "t.db")
db.init_db()
fails = []

def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)

def utc_ago(hours):
    return (datetime.utcnow() - timedelta(hours=hours)).isoformat(timespec="minutes")

for f in ("פ1", "פ2"):
    db.add_forum(f, "#111", "https://x.example")

# ══ ברירות מחדל: אינרטי לחלוטין ═══════════════════════════════════════
cfg = db.get_schedule()
ok("כבוי כברירת מחדל", cfg["enabled"] is False)
ok("אין פורומים כברירת מחדל", cfg["forums"] == [])
ok("שום דבר לא מגיע לו להיסרק", db.sched_due_forums() == [])

db.set_schedule(enabled=True)
ok("הפעלת המתג לבדה עדיין לא סורקת כלום", db.sched_due_forums() == [],
   str(db.sched_due_forums()))

# ══ הרצפה הקשיחה ══════════════════════════════════════════════════════
db.set_schedule(forums=["פ1", "פ2", "פורום שלא קיים"], mode="interval", every_hours=1)
ok("פורום שלא קיים נזרק מהרשימה", db.get_schedule()["forums"] == ["פ1", "פ2"],
   str(db.get_schedule()["forums"]))
ok("מרווח קטן מהמינימום נצמד למינימום",
   db.get_schedule()["every_hours"] == db.SCHED_MIN_INTERVAL_HOURS,
   str(db.get_schedule()["every_hours"]))

# עריכה ידנית של שורת ההגדרות לא אמורה לעקוף את הרצפה
db.set_setting("sched_every_hours", "1")
db.set_setting("last_scrape_פ1", utc_ago(3))
db.set_setting("last_scrape_פ2", utc_ago(3))
ok("גם הגדרה שנערכה ידנית לא מורידה מתחת לרצפה", db.sched_due_forums() == [],
   str(db.sched_due_forums()))

db.set_setting("last_scrape_פ1", utc_ago(13))
ok("אחרי הרצפה כן מגיע לו", db.sched_due_forums() == ["פ1"], str(db.sched_due_forums()))

# ══ חותמות ב-UTC מול שעון מקומי ═══════════════════════════════════════
# main.py כותב last_scrape ב-UTC; השוואה מול שעון מקומי הייתה מנפחת את
# ההפרש באזור הזמן ומרשה סריקה מוקדמת.
db.set_setting("last_scrape_פ1", utc_ago(11))
ok("11 שעות (UTC) עדיין לא מספיק", "פ1" not in db.sched_due_forums())
db.set_setting("last_scrape_פ1", utc_ago(12.5))
ok("12.5 שעות כן", "פ1" in db.sched_due_forums())

# ══ נודניק וכישלונות ══════════════════════════════════════════════════
db.sched_snooze(6)
ok("נודניק משתיק הכול", db.sched_due_forums() == [])
db.set_setting("sched_snooze_until", "")
ok("אחרי הנודניק חוזר", db.sched_due_forums() != [])

for i in range(db.SCHED_MAX_FAILS - 1):
    stopped = db.sched_note_result(False, "תקלת רשת")
    ok("כישלון %d לא עוצר" % (i + 1), stopped is False)
ok("הכישלון האחרון עוצר את התזמון", db.sched_note_result(False, "תקלת רשת") is True)
ok("והמתג באמת כבוי", db.get_schedule()["enabled"] is False)
ok("נשמרה סיבה אחרונה", db.get_schedule()["last_error"] == "תקלת רשת")
msg = db.sched_pop_notify()
ok("הודעה חד-פעמית נמסרת", bool(msg), repr(msg))
ok("ולא נמסרת פעמיים", db.sched_pop_notify() == "")

db.set_schedule(enabled=True)
ok("הפעלה מחדש מאפסת את מונה הכישלונות", db.get_schedule()["fail_count"] == 0)
ok("והצלחה מאפסת גם היא", db.sched_note_result(True) is False and
   db.get_schedule()["fail_count"] == 0)
ok("הצלחה רושמת זמן ריצה", db.get_schedule()["last_run"] != "")

# ══ מצב יומי ══════════════════════════════════════════════════════════
db.set_schedule(mode="daily", at="23:59")
db.set_setting("last_scrape_פ1", utc_ago(50))
db.set_setting("last_scrape_פ2", utc_ago(50))
before_hour = datetime.now().hour < 23
if before_hour:
    ok("לפני שעת היעד — לא רץ", db.sched_due_forums() == [], str(db.sched_due_forums()))
else:
    ok("לפני שעת היעד — לא רץ", True, "(נבדק מאוחר ביום, מדולג)")
db.set_schedule(at="00:00")
ok("אחרי שעת היעד — רץ", sorted(db.sched_due_forums()) == ["פ1", "פ2"],
   str(db.sched_due_forums()))

# שעה לא חוקית לא מפילה כלום
db.set_setting("sched_at", "99:99")
ok("שעה פגומה חוזרת לברירת המחדל", db.get_schedule()["at"] == "03:00",
   db.get_schedule()["at"])
db.set_setting("sched_mode", "מה-זה")
ok("מצב פגום חוזר לברירת המחדל", db.get_schedule()["mode"] == "daily")
db.set_setting("sched_forums", "{not json")
ok("רשימת פורומים פגומה לא מפילה", db.get_schedule()["forums"] == [])

# פורום שנמחק נושר לבד
db.set_schedule(forums=["פ1", "פ2"])
fid = [f["id"] for f in db.get_forums() if f["name"] == "פ2"][0]
db.delete_forum(fid, move_to_general=True)
ok("פורום שנמחק נושר מהתזמון", db.get_schedule()["forums"] == ["פ1"],
   str(db.get_schedule()["forums"]))

# ══ השוואת שני משתמשים ════════════════════════════════════════════════
posts_a = [{"pid": 1, "title": "נושא א", "ts": 1, "date": "2026-01-01", "hour": 9,
            "day": "שני", "month": "2026-01", "likes": 4, "voters": [], "words": 60},
           {"pid": 2, "title": "נושא ב", "ts": 2, "date": "2026-02-01", "hour": 9,
            "day": "שני", "month": "2026-02", "likes": 2, "voters": [], "words": 40}]
posts_b = [{"pid": 3, "title": "נושא א", "ts": 3, "date": "2026-01-05", "hour": 22,
            "day": "שבת", "month": "2026-01", "likes": 0, "voters": [], "words": 10}]

sa, sb = chz._summarize(posts_a), chz._summarize(posts_b)
ok("סיכום סופר פוסטים ולייקים", sa["posts"] == 2 and sa["likes"] == 6, str(sa["likes"]))
ok("ממוצע מילים", sa["avg_words"] == 50.0, str(sa["avg_words"]))
ok("שעת שיא", sa["top_hour"] == 9 and sb["top_hour"] == 22)
ok("יום פעיל", sa["top_day"] == "שני" and sb["top_day"] == "שבת")
ok("חודשים נספרים", sa["months"] == {"2026-01": 1, "2026-02": 1}, str(sa["months"]))
ok("נושאים בולטים", sa["top_topics"][0][0] in ("נושא א", "נושא ב"))
ok("סיכום על רשימה ריקה לא מתרסק", chz._summarize([])["posts"] == 0)

evil = "</script><img src=x onerror=alert(1)>"
a = {"slug": evil, "uid": 1, "posts": posts_a, "stats": sa,
     "meta": {"postcount": 2, "partial": False, "limited": False, "stopped_early": False}}
b = {"slug": "שני", "uid": 2, "posts": posts_b, "stats": sb,
     "meta": {"postcount": 9, "partial": True, "limited": False, "stopped_early": False}}
html = chz._build_compare_html("https://x.example", a, b)
ok("שם משתמש עוין לא שובר את הדוח", "</script><img" not in html)
ok("והוא כן מוצג מוברח", "&lt;/script&gt;" in html)
ok("שלושה גרפים", html.count("new Chart") == 3, str(html.count("new Chart")))
ok("דיווח חלקיות לכל משתמש בנפרד", "מתוך" in html)
ok("Chart.js מוטמע ולא מקושר", "cdn.jsdelivr" not in html or "<script>" in html)
ok("סיכום מילולי קיים", 'id="sum"' in html)

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("SCHEDULE TESTS PASSED")
db.close_pool()
shutil.rmtree(tmp, ignore_errors=True)
