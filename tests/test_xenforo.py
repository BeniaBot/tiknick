# -*- coding: utf-8 -*-
"""
סריקת XenForo — פרוג ולתורה.

אפס בקשות לפורום אמיתי: הכול מול שרת מזויף מקומי (tests/fake_xenforo.py)
שמשחזר את הסימון שנמדד, כולל המלכודות. אפס נגיעה במאגר של המשתמש: מאגר
זמני שנוצר כאן, ומאגר-בובה ללולאה.
"""
import io
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import scraper                 # noqa: E402
import database as db          # noqa: E402
import fake_xenforo as fake    # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


class DummyDB(object):
    """מאגר-בובה: הלולאה נבדקת בלי לגעת ב-SQLite בכלל."""

    def __init__(self):
        self.rows = {}

    def merge_scraped_users(self, forum, users, source_label="", run_id=None):
        added = 0
        for name, mapped in users:
            key = mapped.get("forum_uid") or name
            if key not in self.rows:
                added += 1
            self.rows[key] = (name, mapped)
        return {"added": added, "updated": 0, "unchanged": 0}


def run(members, per_page=10, **kw):
    srv, base = fake.start(members, per_page=per_page,
                           login_wall=kw.pop("login_wall", False),
                           fail_pages=kw.pop("fail_pages", ()))
    d = DummyDB()
    try:
        stats = scraper.scrape_forum("בדיקה", base, d, platform="xenforo", **kw)
    finally:
        srv.shutdown()
    return stats, d, list(fake._Handler.hits)


# ══ 1. המפרשים, מול סימון אמיתי ══════════════════════════════════════════
# הסימון כאן מועתק בצורתו מהעמודים שנמדדו בפרוג ובלתורה.
ROW = ('<li class="block-row block-row--separated">'
       '<div class="contentRow"><div class="contentRow-figure">'
       '<a href="/members/x.55/" class="avatar" data-user-id="55"></a></div>'
       '<div class="contentRow-main">'
       '<h3 class="contentRow-header"><a href="/members/x.55/" class="username " '
       'dir="auto" data-user-id="55">&quot;דוד&quot;</a></h3>'
       '<div class="contentRow-lesser"><span class="userTitle">חבר ותיק</span></div>'
       '<div class="contentRow-minor"><ul class="listInline listInline--bullet">'
       '<li><dl class="pairs pairs--inline"><dt>הודעות</dt><dd>3,605</dd></dl></li>'
       '<li><dl class="pairs pairs--inline"><dt>תודות שהתקבלו</dt><dd>17,228</dd></dl></li>'
       '<li><dl class="pairs pairs--inline"><dt>נקודות</dt><dd>420</dd></dl></li>'
       '</ul></div></div></div></li>')
PAGE = ('<html data-template="member_list" data-logged-in="false">'
        '<ol class="block-body">' + ROW + '</ol>'
        '<a href="/members/staff.999/">צוות</a>'          # זיהום סרגל צד
        '<input type="number" min="1" max="562" value="1">'
        '<a href="/members/list/?page=562">562</a></html>')

rows = scraper._xf_rows(scraper._xf_body(PAGE))
ok("שורה אחת בתוך התיחום", len(rows) == 1, len(rows))

# 🚨 הרגרסיה המרכזית של המפרש: שורת חבר מכילה <li> מקוננים (כל זוג dt/dd
# הוא פריט ברשימה), ולכן ביטוי לא-חמדני עד </li> נעצר בסוגר הפנימי הראשון.
# מספר השורות יוצא נכון, "הודעות" נמצא — ו"תודות שהתקבלו" נעלם בשקט.
mapped = scraper._map_xenforo_row(rows[0], "https://f.example/members/list/")
ok("המזהה נקרא", mapped.get("forum_uid") == "55", mapped)
ok("פסיקים במספר ההודעות מטופלים", mapped.get("post_count") == "3605", mapped)
ok("🚨 המוניטין לא אבד ב-</li> המקונן", mapped.get("reputation") == "17228", mapped)
ok("שם מקודד פוענח", scraper._xf_name(rows[0]) == '"דוד"', scraper._xf_name(rows[0]))
ok("קישור סרגל הצד לא נספר כשורה",
   len(scraper._XF_UID_RX.findall(PAGE)) > len(rows),
   "%d מזהים במסמך מול %d שורות" % (len(scraper._XF_UID_RX.findall(PAGE)), len(rows)))

# שם עטוף ב-span של צבע קבוצה — 4 מתוך 250 בפרוג, ולכידה של ([^<]*) מפספסת
# בדיוק אותם בזמן שהיא מקבלת 30/30 בלתורה ונראית מושלמת.
styled = ROW.replace('data-user-id="55">&quot;דוד&quot;</a>',
                     'data-user-id="55"><span class="username--style175">רבקה</span></a>')
ok("שם עטוף בתגית נקרא נכון", scraper._xf_name(styled) == "רבקה", scraper._xf_name(styled))

ok("עמוד אחרון נקרא מהעימוד", scraper._xf_last_page(PAGE) == 562,
   scraper._xf_last_page(PAGE))
# **לעולם לא 1 כברירת מחדל**: ערך כזה היה עוצר את הלולאה אחרי עמוד אחד
# ומדווח "הושלמה" על פורום עם 140 אלף חברים.
ok("בלי עימוד מוחזר None ולא 1", scraper._xf_last_page("<html></html>") is None,
   scraper._xf_last_page("<html></html>"))
ok("התבנית מזוהה", scraper._xf_template(PAGE) == "member_list")

# תוויות לא בסדר קנוני — 37 מתוך 250 השורות בפרוג. אינדוקס לפי מיקום היה
# כותב "תגובות למאמר" לתוך עמודת המוניטין.
shuffled = ROW.replace("<dt>הודעות</dt><dd>3,605</dd>",
                       "<dt>תגובות למאמר</dt><dd>9</dd>") \
              .replace("<dt>נקודות</dt><dd>420</dd>",
                       "<dt>הודעות</dt><dd>3,605</dd>")
m2 = scraper._map_xenforo_row(shuffled, "https://f.example/")
ok("מפתחים לפי תווית ולא לפי מיקום",
   m2.get("post_count") == "3605" and m2.get("reputation") == "17228", m2)

# שדות שאין ברשימה — מפתח חסר נשמר כחסר, ולכן ערך שהוקלד ידנית אינו נמחק
for absent in ("status", "join_date", "email", "groups", "nick_color"):
    ok("לא נכתב שדה שאינו ברשימה: " + absent, absent not in mapped, mapped)

ok("עוגיית XenForo מנורמלת בשמה",
   scraper.normalize_cookie("abc", "xenforo") == "xf_user=abc",
   scraper.normalize_cookie("abc", "xenforo"))

# ══ 2. הלולאה — המלכודת שנמדדה ═══════════════════════════════════════════
# פרוג 563 == 562, לתורה 570 == 569: עמוד אחרי האחרון מחזיר את האחרון שוב.
# לולאה שממתינה לעמוד ריק לא תיעצר לעולם.
stats, dummy, hits = run(fake.make_members(25, 10), per_page=10)
ok("כל 25 החברים נאספו", len(dummy.rows) == 25, len(dummy.rows))
ok("שלושה עמודים", stats["pages"] == 3, stats["pages"])
ok("🚨 העצירה מאומתת בתצפית", stats["stop_reason"] == "confirmed_end",
   stats["stop_reason"])
pages = [h for h in hits if "members/list" in h]
ok("בקשה אחת בלבד מעבר לסוף", len(pages) == 4, "%d: %s" % (len(pages), pages))
ok("אף עמוד לא נדרש פעמיים", len(pages) == len(set(pages)), pages)
ok("לא סומן חלקי", not stats.get("incomplete"), stats.get("incomplete"))

# ══ 3. מינימום הודעות — הבחירה של בנימין ═════════════════════════════════
# בפורומים האלה ~60% מהחשבונות מעולם לא כתבו דבר (מדגם: 627 מתוך 1,000
# בפרוג, 71 מתוך 120 בלתורה). ההחלטה שלו, בכל סריקה מחדש.
s3, d3, _ = run(fake.make_members(25, 10), per_page=10, min_posts=1)
zeros = [1 for _, m in d3.rows.values() if int(m.get("post_count") or 0) == 0]
ok("מי שלא כתב לא נכנס", not zeros, len(zeros))
ok("מספר הדילוגים מדווח", s3.get("skipped_low", 0) > 0, s3.get("skipped_low"))
ok("הסכום נשמר", len(d3.rows) + s3["skipped_low"] == 25,
   "%d + %d" % (len(d3.rows), s3["skipped_low"]))

s3b, d3b, _ = run(fake.make_members(25, 10), per_page=10, min_posts=0)
ok("מינימום 0 מכניס את כולם", len(d3b.rows) == 25, len(d3b.rows))

# ══ 4. רשימה מאחורי התחברות — כמו פורום אוצר התורה ═══════════════════════
try:
    run(fake.make_members(10, 10), login_wall=True)
    ok("רשימה חסומה מרימה AuthRequired", False, "לא הורמה חריגה")
except scraper.AuthRequired:
    ok("רשימה חסומה מרימה AuthRequired", True)
except Exception as e:
    ok("רשימה חסומה מרימה AuthRequired", False, "%s: %s" % (type(e).__name__, e))

# ══ 5. עמוד שנכשל — חובה שיסומן כחלקי ════════════════════════════════════
# 🚨 סריקה שדילגה על עמוד באמצע חסרה חברים שלמים, וגם אם היא הגיעה לסוף
# מאומת היא **אינה** "הושלמה". זו משפחת הבאגים המרכזית של הפרויקט.
s5, d5, _ = run(fake.make_members(50, 10), per_page=10, fail_pages=(3,))
ok("הכישלון נספר", s5["failed_pages"] >= 1, s5["failed_pages"])
ok("🚨 הסריקה מסומנת כחלקית", s5.get("incomplete") is True, s5)
ok("שאר העמודים כן נאספו", len(d5.rows) == 40, len(d5.rows))

# ══ 6. הגבלות שהמשתמש ביקש — לא "חלקי" ═══════════════════════════════════
s6, d6, _ = run(fake.make_members(50, 10), per_page=10, max_pages=2)
ok("הגבלת עמודים מסומנת", s6.get("limited") is True, s6.get("limited"))
ok("הגבלה אינה 'חלקי'", not s6.get("incomplete"), s6.get("incomplete"))
ok("נאספו בדיוק שני עמודים", len(d6.rows) == 20, len(d6.rows))

ev = threading.Event()
ev.set()
s7, _d7, _ = run(fake.make_members(50, 10), per_page=10, cancel_flag=ev)
ok("ביטול מסומן", s7["cancelled"] is True, s7["cancelled"])
ok("ביטול אינו 'חלקי'", not s7.get("incomplete"), s7.get("incomplete"))

# ══ 7. פורום קטן שכולו עמוד אחד ══════════════════════════════════════════
s8, d8, _ = run(fake.make_members(4, 10), per_page=10)
ok("פורום בעמוד אחד נאסף במלואו", len(d8.rows) == 4, len(d8.rows))
ok("ולא סומן חלקי", not s8.get("incomplete"), s8.get("incomplete"))

# ══ 8. הזיהוי ════════════════════════════════════════════════════════════
srv, base = fake.start(fake.make_members(12, 10), per_page=10)
try:
    ok("detect_platform מזהה xenforo",
       scraper.detect_platform(base) == "xenforo", scraper.detect_platform(base))
    info = scraper.check_forum(base)
    ok("check_forum מאשר", info["ok"] is True, info)
    ok("check_forum מדווח xenforo", info["platform"] == "xenforo", info["platform"])
    ok("הערכת מספר החברים היא חסם עליון",
       info["user_count"] and info["user_count"] >= 12, info["user_count"])
    # scrape_single_user לא יורה בקשות NodeBB לשרת XenForo
    ok("scrape_single_user מחזיר None ל-XenForo",
       scraper.scrape_single_user(base, "דוד", platform="xenforo") is None)
finally:
    srv.shutdown()

srv, base = fake.start(fake.make_members(12, 10), per_page=10, login_wall=True)
try:
    info = scraper.check_forum(base)
    ok("רשימה חסומה: check_forum אינו מדווח הצלחה", info["ok"] is False, info)
    ok("ומסביר שצריך עוגייה", "xf_user" in (info["error"] or ""), info["error"])
finally:
    srv.shutdown()

# ══ 9. שילוב עם המאגר האמיתי — על קובץ זמני בלבד ═════════════════════════
db.close_pool()
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "xf.db")
db.init_db()
db.add_forum("פרוג בדיקה", "#d35400", "https://x.example")
srv, base = fake.start(fake.make_members(12, 10), per_page=10)
try:
    stats = scraper.scrape_forum("פרוג בדיקה", base, db, platform="xenforo")
finally:
    srv.shutdown()
nicks = db.get_all_nicks()["rows"]
ok("הניקים נכתבו למאגר", len(nicks) == 12, len(nicks))
by_name = {n["username"]: n for n in nicks}
ok("שם מקודד נשמר מפוענח", '"שם במרכאות"' in by_name, sorted(by_name)[:3])
big = by_name.get('"שם במרכאות"') or {}
ok("מספר עם פסיק נשמר כמספר", str(big.get("post_count") or "") == "3605",
   big.get("post_count"))
ok("המזהה בפורום נשמר", str(big.get("forum_uid") or "") == "1001", big.get("forum_uid"))
ok("מקור הסריקה נרשם", (big.get("source") or "").startswith("XenForo"), big.get("source"))

# סריקה חוזרת אינה מכפילה — ההתאמה לפי forum_uid, בדיוק כמו ב-NodeBB
srv, base2 = fake.start(fake.make_members(12, 10), per_page=10)
try:
    scraper.scrape_forum("פרוג בדיקה", base2, db, platform="xenforo")
finally:
    srv.shutdown()
again = db.get_all_nicks()["rows"]
ok("סריקה חוזרת לא מכפילה", len(again) == 12, len(again))

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("XENFORO TESTS PASSED")
