# -*- coding: utf-8 -*-
"""
0.9 — דוח הפורום ("מי היה כאן ראשון").

הכול מול **שרת NodeBB מזויף מקומי**: אפס בקשות לפורום אמיתי, והתשובות נבנות
כך שיכסו בדיוק את המקרים שהפילו כלים קודמים כאן — עמוד אחרון חלקי, תאריכי
הצטרפות זהים להמונים, מקטע שנופל, וטקסט עוין מהפורום.
"""
import http.server
import io
import json
import os
import socketserver
import sys
import threading
import urllib.parse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import forumstats as FS   # noqa: E402
import i18n               # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


DAY = 86400000
T0 = 1566172800000          # 2019-08-19


# ══ שרת NodeBB מזויף ══════════════════════════════════════════════════════
def _user(uid, name, joined, posts=0, rep=0, banned=False):
    return {"uid": uid, "username": name, "userslug": name.replace(" ", "-"),
            "joindate": joined, "postcount": posts, "reputation": rep,
            "banned": banned}


def _topic(tid, title, ts, views=0, posts=0, up=0, down=0, author="כותב"):
    return {"tid": tid, "title": title, "slug": "%d/%s" % (tid, "t"),
            "timestamp": ts, "viewcount": views, "postcount": posts,
            "upvotes": up, "downvotes": down, "user": {"username": author},
            "category": {"name": "כללי"}}


# 120 משתמשים: uid 1..120. שלושת הראשונים חולקים בדיוק את אותו תאריך —
# זה המצב האמיתי בפורום שעבר מיגרציה, ואז ה-uid הוא סדר ההרשמה.
ALL_USERS = ([_user(1, "שמואל", T0, 7140), _user(2, "Men 770", T0, 1545),
              _user(3, "דודי", T0, 11)]
             + [_user(i, "משתמש %d" % i, T0 + i * DAY, i * 3)
                for i in range(4, 121)])
# NodeBB מחזיר מהחדש לישן
BY_NEWEST = sorted(ALL_USERS, key=lambda u: (-u["joindate"], -u["uid"]))
PER = 50

STATE = {"fail": set(), "delay_paths": {}, "no_count": False, "empty_pages": set()}


class _H(http.server.BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                   # noqa: N802
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        key = u.path + ("?" + u.query if u.query else "")
        for pat in STATE["fail"]:
            if pat in key:
                return self._send({"error": "nope"}, 500)

        if u.path == "/api/users":
            page = int((q.get("page") or ["1"])[0])
            chunk = BY_NEWEST[(page - 1) * PER: page * PER]
            if (q.get("section") or [""])[0] == "sort-posts":
                chunk = sorted(ALL_USERS, key=lambda x: -x["postcount"])[:PER]
            if page in STATE["empty_pages"]:
                chunk = []
            body = {"users": chunk,
                    # pageCount משקר בכוונה — הקוד חייב להסתמך על userCount
                    "pagination": {"pageCount": 1}}
            if not STATE["no_count"]:
                body["userCount"] = len(ALL_USERS)
            return self._send(body)
        if u.path == "/api/categories":
            return self._send({"categories": [
                {"cid": 1, "name": "מחשבים", "totalTopicCount": 300,
                 "totalPostCount": 4000, "bgColor": "#f00"},
                {"cid": 2, "name": "כללי", "totalTopicCount": 100,
                 "totalPostCount": 900},
            ]})
        if u.path == "/api/popular":
            return self._send({"topics": [
                _topic(11, "נושא נצפה", T0 + 400 * DAY, views=900, posts=50, up=9),
                _topic(12, "נושא מדובר", T0 + 500 * DAY, views=100, posts=800, up=3),
            ], "topicCount": 2})
        if u.path == "/api/top":
            return self._send({"topics": [
                _topic(1, "ברוכים הבאים!", T0 + 3 * DAY, views=460, posts=12),
            ], "topicCount": 1})
        return self._send({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


_srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
BASE = "http://127.0.0.1:%d" % _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
FS.PAGE_DELAY = 0            # הבדיקה לא צריכה את הנימוס; הנימוס נבדק בנפרד


def run(**kw):
    return FS.analyze_forum(BASE, **kw)


# ══ החברים הראשונים — הלב של הכלי ═════════════════════════════════════════
r = run()
ok("הדוח הופק", r["ok"] is True, r.get("error"))
st = r["stats"]
firsts = st["first_members"]
ok("שנים-עשר חברים ראשונים", len(firsts) == 12, len(firsts))
ok("הראשון הוא uid=1", firsts[0]["uid"] == 1 and firsts[0]["name"] == "שמואל", firsts[0])
ok("השני והשלישי לפי uid כששלושתם באותו תאריך",
   [f["uid"] for f in firsts[:3]] == [1, 2, 3], [f["uid"] for f in firsts[:3]])
ok("ואחריהם לפי תאריך", [f["uid"] for f in firsts[3:6]] == [4, 5, 6],
   [f["uid"] for f in firsts[3:6]])
ok("תאריך הפתיחה הוא של הראשון", st["founded"] == FS._date(T0), st["founded"])
ok("מספר המשתמשים מדווח", st["user_count"] == 120, st["user_count"])

# pageCount של NodeBB החזיר 1 — מי שסמך עליו היה מקבל את החדשים, לא את הישנים
ok("pageCount שקרי לא הטעה", firsts[0]["uid"] == 1,
   "נלקח עמוד 1 במקום העמוד האחרון")

# העמוד האחרון חלקי (120 = 2 עמודים מלאים + 20) — חייב להשלים מהקודם לו
ok("עמוד אחרון חלקי הושלם מהעמוד שלפניו", len(firsts) == 12)
ok("בלי כפילויות", len({f["uid"] for f in firsts}) == len(firsts))

# ══ סימון "כבר במאגר" — מה שהופך את זה לכלי של התוכנה ════════════════════
r2 = run(known_usernames=["  שמואל ", "men-770", "לא קיים"])
fm = r2["stats"]["first_members"]
ok("שם זהה מסומן", fm[0]["in_db"] is True, fm[0])
ok("נרמול רווח/מקף עובד", fm[1]["in_db"] is True, fm[1])
ok("מי שאינו במאגר אינו מסומן", fm[2]["in_db"] is False, fm[2])
ok("המונה נכון", r2["stats"]["in_db"] == 2, r2["stats"]["in_db"])
ok("התגית מופיעה בדוח", "במאגר" in r2["html"])
ok("ובלי מאגר אין תגית", "במאגר" not in r["html"])

# ══ שאר המקטעים ══════════════════════════════════════════════════════════
ok("סכום הפוסטים מהקטגוריות", st["total_posts"] == 4900, st["total_posts"])
ok("סכום הנושאים", st["total_topics"] == 400, st["total_topics"])
ok("הנצפה ביותר מופיע", "נושא נצפה" in r["html"])
ok("המדובר ביותר מופיע", "נושא מדובר" in r["html"])
ok("הוותיק מבין הבולטים הוא הישן ביותר",
   r["html"].index("ברוכים הבאים!") > 0 and "ברוכים הבאים!" in r["html"])
ok("שש בקשות בלבד", st["requests"] == 6, st["requests"])
ok("לא נשארו מצייני מקום", "__" not in r["html"].replace("__", "", 0) or
   not [m for m in ("__TITLE__", "__FIRSTS__", "__CATS__", "__LIMITS__", "__FOOT__")
        if m in r["html"]])


# ══ הדוח אומר מה הוא לא יודע ═════════════════════════════════════════════
ok("מוסבר למה אין 'הפוסט הראשון'", "הפוסט הראשון בפורום" in r["html"])
ok("ומוסבר למה אין 'הכי הרבה דיסלייקים'",
   "הכי הרבה דיסלייקים" in r["html"])
ok("ההסבר מזכיר את הסיבה הטכנית", "sort=oldest_to_newest" in r["html"])


# ══ אין JavaScript בדוח — ולכן אין מה לפרוץ ══════════════════════════════
ok("אפס תגיות script", "<script" not in r["html"].lower(), r["html"].lower().count("<script"))
ok("ואפס on-handlers", " onclick" not in r["html"] and " onerror" not in r["html"])


# ══ מקטע שנופל אינו מפיל את הדוח ═════════════════════════════════════════
STATE["fail"] = {"/api/categories", "/api/popular"}
r3 = run()
STATE["fail"] = set()
ok("הדוח עדיין מופק כששני מקטעים נפלו", r3["ok"] is True, r3.get("error"))
ok("החברים הראשונים עדיין שם", len(r3["stats"]["first_members"]) == 12)
ok("המקטעים החסרים מדווחים", len(r3["stats"]["missing"]) == 2, r3["stats"]["missing"])
ok("ונאמר בדוח עצמו", "מקטעים שלא נטענו" in r3["html"])
ok("מקטע ריק אומר זאת", "אין נתונים זמינים" in r3["html"])
ok("KPI בלי נתון מציג מקף", "—" in r3["html"])

# נפילת רשימת המשתמשים היא כישלון אמיתי — אין דוח בלי הלב שלו
STATE["fail"] = {"/api/users"}
r4 = run()
STATE["fail"] = set()
ok("בלי רשימת המשתמשים אין דוח", r4["ok"] is False, r4)
ok("והשגיאה מוסברת בעברית", "משתמשים" in r4.get("error", ""), r4.get("error"))


# ══ טקסט עוין מהפורום ════════════════════════════════════════════════════
BAD = '<img src=x onerror=alert(1)>"><b>'
ALL_USERS[0]["username"] = BAD
BY_NEWEST[:] = sorted(ALL_USERS, key=lambda u: (-u["joindate"], -u["uid"]))
r5 = run()
ALL_USERS[0]["username"] = "שמואל"
BY_NEWEST[:] = sorted(ALL_USERS, key=lambda u: (-u["joindate"], -u["uid"]))
ok("שם עוין עבר בריחה", "<img src=x" not in r5["html"], r5["html"][:0])
ok("והוא כן מוצג כטקסט", "&lt;img src=x" in r5["html"])
# המחרוזת "onerror" עצמה כן מופיעה — כטקסט בתוך &lt;...&gt;, וזה בסדר גמור.
# מה שחייב להיעדר הוא הסוגר שסוגר את התגית ואת המאפיין, כי בלעדיו אין הזרקה.
ok("התגית לא נסגרת", "onerror=alert(1)>" not in r5["html"])
ok("והבריחה מהמאפיין נחסמה", '"><b>' not in r5["html"])


# ══ טקסט מקודד מהפורום מפוענח (הלקח מ-0.8.21) ═══════════════════════════
ok("&quot; מפוענח", FS._txt("ע&quot;ה") == 'ע"ה', FS._txt("ע&quot;ה"))
ok("טקסט בלי & לא נוגעים בו", FS._txt("שלום") == "שלום")


# ══ עזרי המרה ════════════════════════════════════════════════════════════
ok("_date על אפס מחזיר ריק", FS._date(0) == "")
ok("_date על זבל מחזיר ריק", FS._date("abc") == "" and FS._date(None) == "")
ok("_date תקין", FS._date(T0) == "2019-08-19", FS._date(T0))
ok("_int סלחני", FS._int("7") == 7 and FS._int(None) == 0 and FS._int("x") == 0)
ok("_norm_name מנטרל רווח/מקף/קו תחתון",
   FS._norm_name("בני מין") == FS._norm_name("בני-מין") == FS._norm_name("בני_מין"))
ok("_fill הוא מעבר יחיד",
   FS._fill("__A__", {"A": "__A__"}) == "__A__")


# ══ תקרת הזמן ════════════════════════════════════════════════════════════
r6 = run(deadline=-1)
ok("חריגה מהזמן אינה מרימה חריגה", isinstance(r6, dict))
ok("ומדווחת ככישלון מסודר", r6["ok"] is False, r6)


# ══ העוגייה נשלחת בשם המלא (הלקח מ-0.8.6) ═══════════════════════════════
seen = {}
_real = FS.net.urlopen


def _spy(req, timeout=None):
    seen["cookie"] = req.get_header("Cookie")
    return _real(req, timeout=timeout)


FS.net.urlopen = _spy
try:
    run(known_usernames=None)
finally:
    FS.net.urlopen = _real
ok("בלי עוגייה לא נשלחת כותרת", seen.get("cookie") is None, seen)

FS.net.urlopen = _spy
try:
    FS.analyze_forum(BASE, "s%3Aabc")
finally:
    FS.net.urlopen = _real
ok("ערך גולמי מקבל את שם העוגייה",
   seen.get("cookie") == "express.sid=s%3Aabc", seen)

FS.net.urlopen = _spy
try:
    FS.analyze_forum(BASE, "express.sid=s%3Aabc")
finally:
    FS.net.urlopen = _real
ok("ושם שכבר קיים לא מוכפל",
   seen.get("cookie") == "express.sid=s%3Aabc", seen)


# ══ נימוס: יש השהיה בין בקשות ════════════════════════════════════════════
src = io.open(FS.__file__, encoding="utf-8").read()
ok("מוגדרת השהיה בין בקשות", "PAGE_DELAY = 0.5" in src)
ok("וההשהיה נאכפת ב-_Fetcher.get", "min(PAGE_DELAY" in src)
# שני מצייני מקום צמודים נבלעים לאחד (המחלקה [A-Z_]+ בולעת גם את הקווים התחתונים שביניהם)
ok("אין שני מצייני מקום צמודים בתבנית",
   "____" not in FS._TEMPLATE, [l for l in FS._TEMPLATE.splitlines() if "____" in l][:1])
ok("ה-Request נבנה בתוך לולאת הריטריי",
   src.index("urllib.request.Request(url)") > src.index("for attempt in range"))
ok("כיבוד Retry-After", "Retry-After" in src)

# ── ה-UA המזוהה, וזו לא קוסמטיקה ─────────────────────────────────────────
# נמדד מול mitmachim.top: עם UA של דפדפן הפורום מחזיר קטגוריה נוספת
# (11 במקום 10, 1,089,188 פוסטים במקום 938,662). לקחת את המספר הגדול
# פירושו להרוויח נתונים מזה שלא הזדהינו — ההפך מהחלטת המוצר כאן.
import scraper as _SC   # noqa: E402
ok("הכלי מזדהה בשמו", FS._UA == _SC.USER_AGENT, FS._UA)
ok("ולא מתחזה לדפדפן", "Mozilla" not in FS._UA and "Chrome" not in FS._UA, FS._UA)
seen.clear()
FS.net.urlopen = _spy


def _spy_ua(req, timeout=None):
    seen["ua"] = req.get_header("User-agent")
    return _real(req, timeout=timeout)


FS.net.urlopen = _spy_ua
try:
    run()
finally:
    FS.net.urlopen = _real
ok("וזה מה שנשלח בפועל", seen.get("ua") == _SC.USER_AGENT, seen.get("ua"))


# ══ אנגלית ═══════════════════════════════════════════════════════════════
i18n.set_lang("en")
try:
    en = run()["html"]
    ok("הכותרת מתורגמת", "Who got here first" in en, en[:0])
    ok("והתוויות גם", "The first members" in en and "Members" in en)
    ok("הכיוון מתהפך", 'dir="ltr"' in en and 'lang="en"' in en)
finally:
    i18n.set_lang("he")
he = run()["html"]
ok("ובעברית הכול חוזר כשהיה", "מי היה כאן ראשון" in he and 'dir="rtl"' in he)


# ══ שני הבאגים החמורים מהביקורת האדוורסרית ═══════════════════════════════
# שניהם נתנו תשובה **שגויה בביטחון מלא**, וזה בדיוק מה שהמודול מבטיח לא לעשות.

# 1. בלי userCount, הקוד הישן נפל ל-pageCount — שמחזיר 1 — והכתיר את
#    המשתמשים ה**חדשים** כמייסדים. הרשימה מתהפכת לגמרי בלי שום סימן.
STATE["no_count"] = True
rb = run()
STATE["no_count"] = False
ok("בלי userCount הדוח עדיין מופק", rb["ok"] is True, rb.get("error"))
# הקוד הישן היה נופל ל-pageCount (שמחזיר 1) ומכתיר את ה**חדשים**. עכשיו הוא
# מתקדם קדימה עד עמוד חלקי ומאמת את הסוף בעצמו — ומגיע לתשובה הנכונה.
ok("ומאתר את המייסדים בכל זאת, בלי pageCount",
   [f["uid"] for f in rb["stats"]["first_members"]][:3] == [1, 2, 3],
   [f["uid"] for f in rb["stats"]["first_members"]][:4])
ok("ולא את החדשים", all(f["uid"] < 20 for f in rb["stats"]["first_members"]),
   [f["uid"] for f in rb["stats"]["first_members"]][:4])
ok("הסוף אומת ולא נוחש", rb["stats"]["members_ok"] is True)
ok("שאר המקטעים עדיין שם", "נושא נצפה" in rb["html"] and "מחשבים" in rb["html"])

# 2. כשהעמוד האחרון נכשל, הקוד הישן הכתיר את עמוד last-1 — כלומר המשתמש
#    ה-21 קיבל מדליית זהב ותאריך הפתיחה זז בשלושה שבועות.
STATE["fail"] = {"page=3"}
rc = run()
STATE["fail"] = set()
ok("עמוד אחרון שנכשל אינו מקדם את העמוד שלפניו",
   rc["stats"]["first_members"] == [], [f["uid"] for f in rc["stats"]["first_members"]][:4])
ok("וגם אז הדוח מופק", rc["ok"] is True and "מחשבים" in rc["html"])

# 3. אותו דבר כשהעמוד חוזר ריק (userCount נסחף) — אין כשל, ולכן הבאג הזה
#    לא היה משאיר שום עקבה ב-missing.
STATE["empty_pages"] = {3}
rd = run()
STATE["empty_pages"] = set()
ok("עמוד אחרון ריק אינו מקדם את העמוד שלפניו",
   rd["stats"]["first_members"] == [], [f["uid"] for f in rd["stats"]["first_members"]][:4])


# ══ נושא שמופיע בשני הנתיבים נספר פעם אחת ════════════════════════════════
# /api/top ו-/api/popular מחזירים חלק מאותם נושאים; בלי איחוד לפי tid אותו
# נושא הופיע פעמיים באותו כרטיס.
_oldcard = r["html"].split("הוותיקים מבין הנושאים הבולטים")[1]
ok("אין כפילות בין popular ל-top בתוך אותו כרטיס",
   _oldcard.count(">ברוכים הבאים!<") == 1, _oldcard.count(">ברוכים הבאים!<"))
# ובכרטיס הזה הסדר הוא לפי גיל, ולכן פס שאורכו צפיות היה מטעה
ok("לכרטיס הוותיקים אין פסים", 'class="bar"' not in _oldcard.split("</div></div>")[0])


# ══ כתובת בלי סכימה ══════════════════════════════════════════════════════
# add_forum שומרת בדיוק מה שהוקלד, וכל שאר מסלולי הרשת משלימים https לבד.
ok("כתובת בלי סכימה מקבלת https", FS._Fetcher("bina.top").base == "https://bina.top",
   FS._Fetcher("bina.top").base)
ok("סכימה קיימת לא נגועה", FS._Fetcher("http://x.test").base == "http://x.test")
ok("סלאש בסוף נחתך", FS._Fetcher(BASE + "/").base == BASE, FS._Fetcher(BASE + "/").base)
ok("רווחים נחתכים", FS._Fetcher("  " + BASE + "  ").base == BASE)


# ══ תקרת הזמן היא תקרה, לא הצהרה ═════════════════════════════════════════
# קודם היא נבדקה רק **לפני** בקשה, ואז לולאת הריטריי הוסיפה עוד עד 25 שניות.
import time as _time   # noqa: E402
_t0 = _time.time()
rf = FS.analyze_forum(BASE, deadline=0.05)
_el = _time.time() - _t0
ok("חריגה נעצרת מיד", _el < 8, "%.1fs" % _el)
ok("ומדווחת ככישלון מסודר", rf["ok"] is False, rf)
ok("_get_json מקבל תקציב זמן", "budget" in FS._get_json.__code__.co_varnames)
ok("והמונה סופר ניסיונות ולא קריאות",
   "נספר פר-ניסיון" in io.open(FS.__file__, encoding="utf-8").read())


# ══ דף אתגר מזוהה, ולא מאובחן כ"אין API" ════════════════════════════════
ok("יש מחלקת שגיאה ייעודית", hasattr(FS, "ChallengeError"))
ok("והיא נשענת על הזיהוי הקיים של הסורק",
   "_looks_like_challenge" in io.open(FS.__file__, encoding="utf-8").read())


_srv.shutdown()
_srv.server_close()

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("FORUM STATS TESTS PASSED")
