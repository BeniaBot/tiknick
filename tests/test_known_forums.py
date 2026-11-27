# -*- coding: utf-8 -*-
"""
0.9.7 — רשימת הפורומים המוכרים.

בנימין: "לבדוק אם כל הפורומים החרדיים וכדו' נמצאים בתוכנה (כולל פורום המטבח,
בנקל וטכנוקליק שהכתובת שלו החדשה היא https://tochnot-css.duckdns.org/techoclick)".

נבדק חי ב-27.11.2026 (בקשה אחת-שתיים לכל פורום): המטבח והמוזיקאי יושבים
בתת-תיקייה ‎/forum‎ ונרשמו בשורש; טכנוקליק, מרחבים ורכבים זה לזה — NodeBB
עם ‎/api/users‎ ציבורי; מורשת מרן — XenForo; אידטיש — phpBB.
כאן: הרשימה עצמה, והמיגרציה למי שכבר רשם את הכתובת הישנה. מאגר זמני בלבד.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import database as db   # noqa: E402
import scraper          # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


K = {k["name"]: k for k in db.KNOWN_FORUMS}
ok("🚨 טכנוקליק בכתובת החדשה", K.get("פורום טכנוקליק", {}).get("url")
   == "https://tochnot-css.duckdns.org/techoclick")
ok("🚨 המטבח בתת-התיקייה, ובלי 'דורש התחברות'",
   K["פורום המטבח"]["url"] == "https://hamitbach.me/forum" and not K["פורום המטבח"].get("needs_login"))
ok("המוזיקאי בתת-התיקייה", K["פורום המוזיקאי"]["url"] == "https://hamusicay.com/forum")
ok("בנקל ברשימה", "פורום בנקל" in K)
for n, plat in (("פורום מרחבים", "nodebb"), ("פורום רכבים זה לזה", "nodebb"),
                ("פורום מורשת מרן", "xenforo"), ("פורום אידטיש", "phpbb")):
    ok("נוסף: %s (%s)" % (n, plat), n in K and (K[n].get("platform") or "nodebb") == plat)
ok("אידטיש — קישור פרופיל כמו בשאר phpBB", "{user}" in K["פורום אידטיש"].get("profile_pattern", ""))
names = [k["name"] for k in db.KNOWN_FORUMS]
urls = [db._origin(k["url"]) + "|" + k["url"].rstrip("/").split("/", 3)[-1] for k in db.KNOWN_FORUMS]
ok("אין שם כפול ברשימה", len(names) == len(set(names)))
ok("אין כתובת כפולה ברשימה", len(urls) == len(set(urls)))
ok("🚨 הסורק שומר את תת-התיקייה", scraper._api_base("https://tochnot-css.duckdns.org/techoclick/")
   == "https://tochnot-css.duckdns.org/techoclick")

# ══ מיגרציה ═══════════════════════════════════════════════════════════════
db.close_pool()
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
db.init_db()
with db.get_connection() as c:
    c.execute("DELETE FROM settings WHERE key='known_urls_repaired_v1'")
db.add_forum("פורום המטבח", "#111", "https://hamitbach.me/")
db.add_forum("מוזיקה שלי", "#222", "hamusicay.com")              # שם אחר, בלי סכימה
db.add_forum("פורום בנקל", "#333", "https://forum.benakel.org/")
db.add_forum("מטבח אחר", "#444", "https://hamitbach.me/recipes")  # כתובת אחרת באותו דומיין
db.save_cookie_for_url("https://hamitbach.me/", "express.sid=s%3Ax")
db._repair_known_urls_once()
U = {f["name"]: f["url"] for f in db.get_forums()}
ok("🚨 המטבח עבר לכתובת החדשה", U["פורום המטבח"] == "https://hamitbach.me/forum", U["פורום המטבח"])
ok("🚨 גם בשם אחר — לפי הכתובת", U["מוזיקה שלי"] == "https://hamusicay.com/forum", U["מוזיקה שלי"])
ok("פורום אחר לא נגעו בו", U["פורום בנקל"] == "https://forum.benakel.org/")
ok("כתובת אחרת באותו דומיין — לא נגעו בה", U["מטבח אחר"] == "https://hamitbach.me/recipes")
ok("העוגייה השמורה עדיין חלה (אותו origin)",
   db.get_cookie_for_url("https://hamitbach.me/forum") == "express.sid=s%3Ax")
with db.get_connection() as c:
    c.execute("UPDATE forums SET url='https://hamitbach.me/' WHERE name='פורום המטבח'")
db._repair_known_urls_once()
ok("חד-פעמי — לא רץ שוב", {f["name"]: f["url"] for f in db.get_forums()}["פורום המטבח"]
   == "https://hamitbach.me/")
ok("הדגל נכתב", db.get_setting("known_urls_repaired_v1", "") == "1")

# ══ סוג הפורום ניתן לשינוי מהממשק (פתוח מ-0.9.5) ═══════════════════════════════
import main   # noqa: E402
main.db = db
api = main.API()
fid = [f for f in db.get_forums() if f["name"] == "פורום בנקל"][0]["id"]
ok("שינוי סוג", api.update_forum(fid, "פורום בנקל", "#333", "https://forum.benakel.org/", "discourse")["ok"]
   and db.get_forum_platform("פורום בנקל") == "discourse")
ok("🚨 סוג שאינו ברשימה — מסורב", not api.update_forum(fid, "פורום בנקל", "#333", "", "<script>")["ok"]
   and db.get_forum_platform("פורום בנקל") == "discourse")
ok("בלי סוג — הסוג לא משתנה", api.update_forum(fid, "פורום בנקל", "#333", "https://forum.benakel.org/")["ok"]
   and db.get_forum_platform("פורום בנקל") == "discourse")
ok("שם ריק — מסורב", not api.update_forum(fid, "  ", "#333", "")["ok"])
r = api.update_forum(fid, "פורום המטבח", "#333", "")
ok("🚨 שם שכבר קיים — הודעה, לא חריגה", r["ok"] is False and r.get("error"), r)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("KNOWN FORUMS TESTS PASSED")
