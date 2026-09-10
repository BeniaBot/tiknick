# -*- coding: utf-8 -*-
"""
פורומים שאינם NodeBB — בכל ההקשרים.

🚨 הבאג שהבדיקות האלה נולדו ממנו, ונמדד בארגז החול על משתמש שיש לו רק
פרוג ולתורה: בורר הפורומים של **שטינקניק היה ריק לגמרי**, ו-runStinknik
נפל ל-`|| 'https://mitmachim.top'`. התוצאה — דוח דיסלייקים שלם ומשכנע
**על אדם אחר, בפורום שהמשתמש מעולם לא בחר**, בלי שום סימן שמשהו השתבש.
בחזונישניק הבורר הציג "מתמחים טופ", פורום שאין לו.

זו משפחת הבאגים המרכזית של הפרויקט: תשובה שגויה בביטחון מלא. פורום
ברירת מחדל כאן אינו נוחות — הוא המצאה של נתונים.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


app = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
mainsrc = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()

# ══ 1. אין יותר נפילה לפורום קשיח ════════════════════════════════════════
ok("🚨 runStinknik אינו נופל ל-mitmachim",
   "document.getElementById('stink-forum')?.value || 'https://mitmachim.top'" not in app)
ok("🚨 runChazonishnik אינו נופל ל-mitmachim",
   "document.getElementById('chz-forum')?.value || 'https://mitmachim.top'" not in app)
ok("שטינקניק מסרב כשאין פורום נבחר",
   "if (!baseUrl) { toast('לא נבחר פורום', 'error'); return; }" in app)
ok("חזונישניק מסרב כשאין פורום נבחר", app.count(
   "if (!baseUrl) { toast('לא נבחר פורום', 'error'); return; }") == 2, app.count(
   "if (!baseUrl) { toast('לא נבחר פורום', 'error'); return; }"))
ok("בורר חזונישניק אינו מציע פורום שאין למשתמש",
   "'<option value=\"https://mitmachim.top\">מתמחים טופ</option>'" not in app)

# הנפילות היחידות שנשארו הן דוגמה בהדרכה, כשלא נמסר הקשר — לא מסלול נתונים
left = re.findall(r"\|\| 'https://mitmachim\.top'", app)
ok("נותרו רק הנפילות של ההדרכה", len(left) == 2, len(left))
for m in re.finditer(r"\|\| 'https://mitmachim\.top'", app):
    seg = app[max(0, m.start() - 260):m.start()]
    ok("  הנפילה יושבת ב-cookieHelpHtml", "cookieHelpHtml" in seg or "c.url" in seg,
       seg[-70:])

# ══ 2. שני הכלים מסרבים מפורשות ══════════════════════════════════════════
ok("קיים מסך סירוב משותף", "function openNoNodebb(" in app)
ok("שטינקניק קורא לו", "if (!opts) { openNoNodebb('🦨 Stinknik'); return; }" in app)
ok("חזונישניק קורא לו", "if (!opts) { openNoNodebb('📖 Chazonishnik'); return; }" in app)
ok("הסירוב מגיע לפני openModal של הטופס",
   app.index("openNoNodebb('🦨 Stinknik')") < app.index("🦨 Stinknik — כל הדיסלייקים"))
ok("הסירוב מונה למשתמש אילו פורומים כן יש לו",
   "PLATFORM_LABELS[f.platform]" in app and "noNodebbForumHtml" in app)
ok("ומציע דרך קדימה ולא רק 'לא'", "🏛️ לניהול פורומים" in app)

# ══ 3. הגשר מסרב גם הוא — הגנה אחרונה ════════════════════════════════════
# הממשק הוא לא הגבול היחיד: הגשר נקרא ישירות מ-JS, וברירת מחדל בחתימה
# הייתה ממשיכה להמציא פורום גם אחרי שהממשק תוקן.
for fn in ("run_chazonishnik", "run_stinknik", "run_chazonishnik_compare"):
    i = mainsrc.index("def %s(" % fn)
    sig = mainsrc[i:mainsrc.index(":", mainsrc.index(")", i))]
    body = mainsrc[i:i + 2600]
    ok("%s: אין ברירת מחדל בחתימה" % fn, "mitmachim" not in sig, sig[:110])
    ok("%s: אין נפילה בגוף" % fn, 'base_url or "https://mitmachim.top"' not in body)
    ok("%s: מסרב על פורום ריק" % fn,
       'return {"ok": False, "error": "לא נבחר פורום"}' in body)

# ══ 4. השערים בין הפלטפורמות מסכימים ═════════════════════════════════════
dbsrc = io.open(os.path.join(ROOT, "database.py"), encoding="utf-8").read()
scr = io.open(os.path.join(ROOT, "scraper.py"), encoding="utf-8").read()

ok("שער הממשק כולל את שלוש הפלטפורמות",
   "const SCRAPABLE_PLATFORMS = new Set(['nodebb', 'discourse', 'xenforo']);" in app)
ok("שער התזמון מסכים",
   '("nodebb", "discourse", "xenforo")' in dbsrc)
for plat in ("nodebb", "discourse", "xenforo"):
    ok("הניתוב תומך ב-%s" % plat, 'if plat == "%s":' % plat in scr)
ok("phpBB עדיין מסורב במפורש", '"phpbb": "phpBB"' in scr)

# ══ 5. קישור פרופיל לכל פלטפורמה ═════════════════════════════════════════
ok("XenForo מקבל קישור לפי מזהה", "/members/${encodeURIComponent(uid)}/" in app)
ok("ובלי מזהה נפתח הפורום ולא כתובת שבורה",
   "return uid ? `${base}/members/${encodeURIComponent(uid)}/` : (base || '#');" in app)
ok("כל קורא buildProfileUrl מעביר את המזהה",
   all("n.forum_uid" in ln or "forumUid" in ln
       for ln in app.splitlines() if "buildProfileUrl(" in ln and "function" not in ln))

# ══ 6. שם העוגייה לכל פלטפורמה ═══════════════════════════════════════════
import scraper   # noqa: E402
for plat, name in (("nodebb", "express.sid"), ("discourse", "_t"), ("xenforo", "xf_user")):
    ok("עוגיית %s" % plat, scraper.normalize_cookie("v", plat) == "%s=v" % name,
       scraper.normalize_cookie("v", plat))
ok("הממשק מציג את אותם שמות",
   "const COOKIE_BY_PLAT = { discourse: '_t', xenforo: 'xf_user' };" in app)

# ══ 7. מספרים של XenForo נכנסים כמספרים ══════════════════════════════════
# 🚨 forum_local_snapshot עושה CAST(post_count AS INTEGER); "3,605" היה
# הופך ל-3 ומשמיט בשקט את כל הכותבים הגדולים מכל דירוג מקומי.
ok("פסיק במספר הודעות מנוקה בגבול הרשת", scraper._xf_num("3,605") == "3605")
ok("וגם במוניטין", scraper._xf_num("17,228") == "17228")
ok("אפס נשמר כאפס", scraper._xf_num("0") == "0")
ok("טקסט שאינו מספר נדחה", scraper._xf_num("לא מספר") == "")
int_cast = [ln for ln in dbsrc.splitlines() if "CAST(" in ln and "AS INTEGER" in ln]
ok("קיימות המרות CAST במאגר (ולכן הניקוי חובה)", len(int_cast) >= 2, len(int_cast))



# ══ 8. 🚨 חסימת הרשאה אינה זיהוי ═════════════════════════════════════════
# check_forum החזיר "nodebb" על ה-401 הראשון, לפני ש-Discourse ו-XenForo
# נבדקו בכלל — ו-main.py שמר את הניחוש הזה במאגר גם כשהבדיקה **נכשלה**.
# פורום XenForo מאחורי התחברות נרשם כ-NodeBB לתמיד, וכל שאר התוכנה נגזרת
# מהערך הזה: מנוע הסריקה, שם העוגייה, צורת קישור הפרופיל, התגיות והתזמון.
sys.path.insert(0, os.path.join(HERE))
import fake_xenforo as _fake   # noqa: E402

srv, base = _fake.start(_fake.make_members(8, 10), login_wall=True)
try:
    info = scraper.check_forum(base)
    ok("🚨 רשימה חסומה מזוהה כ-XenForo ולא כ-NodeBB",
       info["platform"] == "xenforo", info)
    ok("והבדיקה מדווחת כישלון", info["ok"] is False, info)
    ok("וההודעה נוקבת בעוגייה הנכונה", "xf_user" in (info["error"] or ""), info["error"])
    ok("detect_platform מסכים", scraper.detect_platform(base) == "xenforo")
finally:
    srv.shutdown()

ok("🚨 בדיקה שנכשלה אינה כותבת פלטפורמה למאגר",
   'if res.get("ok") and res.get("platform") not in (None, "", "unknown"):' in mainsrc)

# ══ 9. 🚨 מזהה פורום ישן אחרי העברה ══════════════════════════════════════
# forum_uid הוא מזהה **בתוך פורום**. ב-XenForo הקישור נבנה ממנו, ולכן
# מזהה ישן פותח עמוד חי של אדם אחר; והסריקה הבאה מתאימה לפיו, משנה את שם
# הניק לשם הזר וממזגת אליו את הפוסטים והמוניטין שלו.
import tempfile               # noqa: E402
import database as db         # noqa: E402

db.close_pool()
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "nn.db")
db.init_db()
db.add_forum("פרוג", "#d35400", "https://www.prog.co.il")
db.add_forum("מתמחים", "#5865f2", "https://mitmachim.top")

nid = db.create_nick({"forum": "פרוג", "username": "דוד"})
with db.get_connection() as c:
    c.execute("UPDATE nicks SET forum_uid=? WHERE id=?", ("4211", nid))
db.update_nick(nid, {"forum": "מתמחים"})
ok("🚨 העברת פורום מאפסת את המזהה", not db.get_nick(nid)["forum_uid"],
   db.get_nick(nid)["forum_uid"])

with db.get_connection() as c:
    c.execute("UPDATE nicks SET forum_uid=? WHERE id=?", ("99", nid))
db.update_nick(nid, {"notes": "הערה"})
ok("עריכה רגילה אינה מוחקת אותו", db.get_nick(nid)["forum_uid"] == "99")
db.update_nick(nid, {"forum": "מתמחים"})
ok("ושמירה לאותו פורום אינה מוחקת", db.get_nick(nid)["forum_uid"] == "99")

n2 = db.create_nick({"forum": "פרוג", "username": "שרה"})
with db.get_connection() as c:
    c.execute("UPDATE nicks SET forum_uid=? WHERE id=?", ("777", n2))
db.bulk_move_forum([n2], "מתמחים")
ok("גם העברה מרובה מאפסת", not db.get_nick(n2)["forum_uid"], db.get_nick(n2)["forum_uid"])

# ══ 10. 🚨 סטטוס שלא נמדד אינו "פעיל" ════════════════════════════════════
# _map_xenforo_row משמיט status **בכוונה** ומסביר למה. אבל ההכנסה מנתה
# עמודות בלי status, ולכן חלה ברירת המחדל בסכימה — וההגנה הובסה שכבה אחת
# מתחת למודול שכתב אותה. ב-NodeBB "לא מורחק" הוא מדידה; ב-XenForo אין
# ברשימת החברים סימון הרחקה בכלל.
db.merge_scraped_users("פרוג", [("חבר חדש", {"post_count": "5"})],
                       source_label="XenForo:פרוג", platform="xenforo")
xf = [r for r in db.get_all_nicks()["rows"] if r["username"] == "חבר חדש"][0]
ok("🚨 ניק XenForo אינו מוצג כ'פעיל'", (xf["status"] or "") == "", repr(xf["status"]))

db.merge_scraped_users("מתמחים", [("חבר נודביבי", {"post_count": "5"})],
                       source_label="NodeBB:מתמחים", platform="nodebb")
nb = [r for r in db.get_all_nicks()["rows"] if r["username"] == "חבר נודביבי"][0]
ok("ו-NodeBB כן — שם זו מדידה", nb["status"] == "פעיל", repr(nb["status"]))
ok("כל מסלולי הסריקה מוסרים פלטפורמה",
   io.open(os.path.join(ROOT, "scraper.py"), encoding="utf-8").read()
   .count("platform=\"") >= 3)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("NON-NODEBB TESTS PASSED")
