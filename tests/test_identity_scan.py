# -*- coding: utf-8 -*-
"""
0.9 — הסריקה מזהה שינוי שם והשתלטות על שם.

הסורק שומר את מזהה המשתמש הפנימי של הפורום ב-`forum_uid` מאז ומעולם, ואף
שאילתה לא קראה אותו. ההתאמה הייתה לפי (פורום, שם משתמש) בלבד, ומכאן שתי
תוצאות שקטות:

  • אדם ששינה את הניק שלו בפורום הופיע כניק **חדש**. התיק שנבנה עליו נשאר
    על השורה הישנה שקופאת, וההיסטוריה התפצלה.
  • מישהו אחר שלקח ניק שהתפנה — הנתונים שלו נמזגו לתוך התיק של האדם
    המקורי. מידע שגוי שנרשם על אדם אמיתי.

הבדיקות כאן מריצות את המיזוג בפועל מול מאגר זמני.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db   # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


db.close_pool()
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
db.init_db()
FORUM = "כללי"


def scraped(uid, **kw):
    d = {"forum_uid": str(uid)}
    d.update(kw)
    return d


def run(pairs, run_id=None):
    return db.merge_scraped_users(FORUM, pairs, run_id=run_id)


def changes(run_id):
    with db.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT kind, username, old_value, new_value FROM scan_changes "
            "WHERE run_id=? ORDER BY id", (run_id,))]


# ══ האינדקס נוצר במיגרציה ═════════════════════════════════════════════════
with db.get_connection() as conn:
    idx = {r[1] for r in conn.execute("PRAGMA index_list(nicks)")}
ok("אינדקס על (פורום, מזהה) קיים", "idx_nicks_forum_uid" in idx, sorted(idx))


# ══ 1. סריקה ראשונה — הכול חדש ════════════════════════════════════════════
r1 = db.start_scan_run(FORUM)
st = run([("דוד", scraped(101, reputation="10")),
          ("משה", scraped(102, reputation="20"))], run_id=r1)
db.finish_scan_run(r1, st)
ok("שני ניקים נוצרו", st["added"] == 2, st)
david = db.find_nick(FORUM, "דוד")
ok("המזהה נשמר", david["forum_uid"] == "101", david["forum_uid"])

# עבודה ידנית שהמשתמש עשה על התיק — זה מה שאסור לאבד
db.update_nick(david["id"], {"phone": "0501234567", "notes": "עבודה של שנים"})


# ══ 2. שינוי שם: אותו מזהה, שם אחר ════════════════════════════════════════
r2 = db.start_scan_run(FORUM)
st = run([("דוד-החדש", scraped(101, reputation="11")),
          ("משה", scraped(102, reputation="20"))], run_id=r2)
db.finish_scan_run(r2, st)

ok("לא נוצר ניק חדש", st["added"] == 0, st)
ok("הניק עודכן", st["updated"] == 1, st)
same = db.find_nick(FORUM, "דוד-החדש")
ok("זו אותה שורה", same and same["id"] == david["id"],
   same and same["id"])
ok("השם הישן כבר לא קיים", db.find_nick(FORUM, "דוד") is None)
ok("הטלפון שהוקלד ידנית שרד", same["phone"] == "0501234567", same["phone"])
ok("וההערות שרדו", same["notes"] == "עבודה של שנים", same["notes"])
# reputation חוזר מה-cache כמספר ולא כמחרוזת — מלכודת חוזרת
ok("המוניטין החדש נקלט", str(same["reputation"]) == "11", same["reputation"])

ev = [c for c in changes(r2) if c["kind"] == "renamed"]
ok("האירוע נרשם ביומן", len(ev) == 1, changes(r2))
ok("ומכיל את שני השמות",
   ev and ev[0]["old_value"] == "דוד" and ev[0]["new_value"] == "דוד-החדש", ev)

with db.get_connection() as conn:
    n = conn.execute("SELECT COUNT(*) FROM nicks WHERE forum=?", (FORUM,)).fetchone()[0]
ok("עדיין שני ניקים בסך הכול (ולא שלושה)", n == 2, n)


# ══ 3. השתלטות: אותו שם, מזהה אחר ═════════════════════════════════════════
# משה עזב, ומישהו אחר לקח את השם. אסור למזג את הנתונים שלו לתיק של משה.
moshe = db.find_nick(FORUM, "משה")
db.update_nick(moshe["id"], {"notes": "התיק של משה המקורי"})

r3 = db.start_scan_run(FORUM)
st = run([("משה", scraped(999, reputation="500"))], run_id=r3)
db.finish_scan_run(r3, st)

after = db.find_nick(FORUM, "משה")
ok("התיק לא זוהם", after["notes"] == "התיק של משה המקורי", after["notes"])
ok("והמוניטין של הזר לא נכנס", after["reputation"] != "500", after["reputation"])
ok("המזהה נשאר של המקורי", after["forum_uid"] == "102", after["forum_uid"])
ev = [c for c in changes(r3) if c["kind"] == "taken_over"]
ok("ההשתלטות דווחה", len(ev) == 1, changes(r3))
ok("ומכילה את שני המזהים",
   ev and ev[0]["old_value"] == "102" and ev[0]["new_value"] == "999", ev)


# ══ 4. שינוי שם לשם שכבר תפוס — לא נוגעים ═════════════════════════════════
r4 = db.start_scan_run(FORUM)
st = run([("משה", scraped(101))], run_id=r4)     # 101 = דוד-החדש
db.finish_scan_run(r4, st)
ok("דוד-החדש לא שינה את שמו", db.find_nick(FORUM, "דוד-החדש") is not None)
ok("ומשה נשאר משה", db.find_nick(FORUM, "משה")["forum_uid"] == "102")
ev = [c for c in changes(r4) if c["kind"] == "rename_blocked"]
ok("ההתנגשות דווחה", len(ev) == 1, changes(r4))


# ══ 5. תאימות לאחור: ניק בלי מזהה ═════════════════════════════════════════
db.create_nick({"forum": FORUM, "username": "ותיק", "notes": "נוצר ידנית"})
r5 = db.start_scan_run(FORUM)
st = run([("ותיק", scraped(777, reputation="7"))], run_id=r5)
db.finish_scan_run(r5, st)
old = db.find_nick(FORUM, "ותיק")
ok("ניק בלי מזהה מותאם לפי שם", st["added"] == 0 and st["updated"] == 1, st)
ok("וההערה הידנית שרדה", old["notes"] == "נוצר ידנית", old["notes"])
ok("והמזהה נכתב עכשיו — המאגר מרפא את עצמו",
   old["forum_uid"] == "777", old["forum_uid"])

# וסריקה שאין בה מזהה כלל (פלטפורמה שלא מחזירה) עדיין עובדת
r6 = db.start_scan_run(FORUM)
st = run([("ותיק", {"reputation": "8"})], run_id=r6)
db.finish_scan_run(r6, st)
ok("סריקה בלי מזהה בכלל עדיין ממזגת",
   str(db.find_nick(FORUM, "ותיק")["reputation"]) == "8",
   db.find_nick(FORUM, "ותיק")["reputation"])


# ══ 6. סריקה חוזרת ללא שינוי — עדיין כמעט לא כותבת ════════════════════════
r7 = db.start_scan_run(FORUM)
st = run([("דוד-החדש", scraped(101, reputation="11")),
          ("משה", scraped(102, reputation="20"))], run_id=r7)
db.finish_scan_run(r7, st)
ok("סריקה חוזרת: אפס שינויים", st["unchanged"] == 2 and st["updated"] == 0, st)


# ══ 7. עלות: השאילתה הנוספת היא אחת למנה, לא אחת למשתמש ═══════════════════
BIG = 2000
big_pairs = [("user%d" % i, scraped(10000 + i, reputation=str(i)))
             for i in range(BIG)]
t0 = time.perf_counter()
st = run(big_pairs)
first = time.perf_counter() - t0
t0 = time.perf_counter()
st2 = run(big_pairs)
second = time.perf_counter() - t0
print("      %d משתמשים: ראשונה %.0fms · חוזרת %.0fms" %
      (BIG, first * 1000, second * 1000))
ok("סריקה חוזרת בקנה מידה נשארת זולה", second < first, (first, second))
ok("ולא נוצרו כפילויות", st2["added"] == 0, st2)

with db.get_connection() as conn:
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
ok("שלמות המאגר", integ == "ok", integ)
ok("מפתחות זרים תקינים", not fk, fk)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("IDENTITY SCAN TESTS PASSED")
