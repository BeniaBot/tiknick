# -*- coding: utf-8 -*-
"""
0.9.7 — התחברות לפורום מתוך התוכנה, במקום תוסף לכרום ושורה בקובץ.

בנימין: "שיהיה יותר קל (מונחה אוטומטי) להביא עוגיות".

החלון האמיתי הוא pywebview, ולכן כאן הוא מוחלף בחלון מזויף שמדמה דף של
פורום: אורח, ואז מחובר. מאגר זמני בלבד, אפס בקשות רשת.
"""
import io
import os
import re
import sys
import tempfile
import time
import types
from http.cookies import SimpleCookie

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import forum_login as FL   # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


# ══ 1. דף ההתחברות ══════════════════════════════════════════════════════════
ok("NodeBB", FL.login_url("https://mitmachim.top", "nodebb") == "https://mitmachim.top/login")
ok("סלאש בסוף", FL.login_url("https://mitmachim.top/", "nodebb") == "https://mitmachim.top/login")
ok("🚨 פורום בתת-תיקייה מתחבר דרך התיקייה שלו",
   FL.login_url("https://tochnot-css.duckdns.org/techoclick/", "nodebb")
   == "https://tochnot-css.duckdns.org/techoclick/login",
   FL.login_url("https://tochnot-css.duckdns.org/techoclick/", "nodebb"))
ok("כתובת בלי סכימה", FL.login_url("bina.top", "nodebb") == "https://bina.top/login")
ok("XenForo", FL.login_url("https://www.prog.co.il", "xenforo") == "https://www.prog.co.il/login/")
ok("כתובת ריקה", FL.login_url("", "nodebb") == "")
ok("phpBB אינו נתמך (אין לו דף אחיד)", not FL.supported("phpbb") and FL.supported("discourse"))

# ══ 2. העוגייה הנכונה, מהדומיין הנכון ═════════════════════════════════════════
ck = [{"name": "express.sid", "value": "s%3Aabc", "domain": "mitmachim.top"},
      {"name": "_ga", "value": "x", "domain": ".mitmachim.top"}]
ok("רק עוגיית ההתחברות", FL.pick_cookie(ck, "nodebb", "mitmachim.top") == "express.sid=s%3Aabc")
ok("🚨 עוגייה באותו שם מדומיין אחר — לא נלקחת",
   FL.pick_cookie([{"name": "express.sid", "value": "evil", "domain": "attacker.example"}],
                  "nodebb", "mitmachim.top") == "")
ok("דומיין עם נקודה מובילה", FL.pick_cookie(
    [{"name": "express.sid", "value": "v", "domain": ".mitmachim.top"}], "nodebb", "www.mitmachim.top")
   == "express.sid=v")
sc = SimpleCookie()
sc["xf_session"] = "S1"
sc["xf_session"]["domain"] = "www.prog.co.il"
sc2 = SimpleCookie()
sc2["xf_user"] = "U1"
ok("SimpleCookie (מה ש-pywebview מחזיר), ובסדר הקבוע",
   FL.pick_cookie([sc, sc2], "xenforo", "www.prog.co.il") == "xf_user=U1; xf_session=S1")
ok("ערך ריק — לא עוגייה", FL.pick_cookie([{"name": "_t", "value": ""}], "discourse", "x.org") == "")

# ══ 3. מתי מחוברים ══════════════════════════════════════════════════════════
ok("🚨 NodeBB: לאורח יש express.sid — וזה לא התחברות", not FL.logged_in("nodebb", 0, "express.sid=s%3Aa"))
ok("NodeBB: uid>0 + עוגייה = מחובר", FL.logged_in("nodebb", 7, "express.sid=s%3Aa"))
ok("NodeBB: uid בלי עוגייה — עוד לא", not FL.logged_in("nodebb", 7, ""))
ok("NodeBB: תשובה זבל מהדף", not FL.logged_in("nodebb", "abc", "express.sid=x"))
ok("Discourse: _t היא ההוכחה", FL.logged_in("discourse", None, "_t=abc; _forum_session=z")
   and not FL.logged_in("discourse", None, "_forum_session=z"))
ok("XenForo: data-logged-in + עוגייה", FL.logged_in("xenforo", 1, "xf_session=S")
   and not FL.logged_in("xenforo", 0, "xf_session=S"))

# ══ 4. הזרימה דרך הגשר, מול חלון מזויף ═══════════════════════════════════════
import database as db   # noqa: E402
db.close_pool()
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
db.init_db()
db.add_forum("טכנוקליק", "#123", "https://tochnot-css.duckdns.org/techoclick")
db.add_forum("פורום phpbb", "#456", "https://old.example")
with db.get_connection() as c:
    c.execute("UPDATE forums SET platform='phpbb' WHERE url='https://old.example'")


class Ev:
    def __init__(self):
        self.fns = []

    def __iadd__(self, f):
        self.fns.append(f)
        return self

    def fire(self):
        for f in self.fns:
            f()


class FakeWin:
    def __init__(self, login_after=None, host="tochnot-css.duckdns.org"):
        self.events = types.SimpleNamespace(closed=Ev())
        self.calls = 0
        self.login_after = login_after
        self.destroyed = False
        self.host = host
        self.js = []

    def evaluate_js(self, js):
        self.js.append(js)
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("page still loading")     # הדף עדיין נטען
        return 9 if (self.login_after and self.calls >= self.login_after) else 0

    def get_cookies(self):
        return [{"name": "express.sid", "value": "s%3Asess", "domain": self.host}]

    def destroy(self):
        self.destroyed = True


created = []


def fake_create_window(title, url=None, **kw):
    w = NEXT_WIN[0]
    created.append({"title": title, "url": url, "kw": kw, "win": w})
    return w


sys.modules["webview"] = types.SimpleNamespace(create_window=fake_create_window)
import main   # noqa: E402
main.db = db
FL.POLL_SEC = 0.01
api = main.API()


def wait_done(t=5):
    end = time.time() + t
    while time.time() < end:
        if not main._login_state["running"]:
            return True
        time.sleep(0.02)
    return False


URL = "https://tochnot-css.duckdns.org/techoclick"
NEXT_WIN = [FakeWin(login_after=4)]
r = api.start_forum_login(URL)
ok("החלון נפתח", r["ok"] and r["forum"] == "tochnot-css.duckdns.org", r)
ok("🚨 בדף ההתחברות של התיקייה", created[-1]["url"] == URL + "/login", created[-1]["url"])
ok("🚨 החלון בלי js_api — דף של פורום לא מגיע ל-API של התוכנה", "js_api" not in created[-1]["kw"])
r2 = api.start_forum_login(URL)
ok("חלון שני באותו זמן — מסורב", not r2["ok"] and "כבר פתוח" in r2["error"])
ok("הסתיים", wait_done())
st = api.get_forum_login_progress()
ok("הצליח", st["ok"] and not st["cancelled"] and not st["error"], st)
ok("🚨 העוגייה נשמרה לפורום", db.get_cookie_for_url(URL) == "express.sid=s%3Asess",
   db.get_cookie_for_url(URL))
ok("החלון נסגר לבד", NEXT_WIN[0].destroyed)
ok("טעינה שזרקה חריגה לא הפילה את ההמתנה", NEXT_WIN[0].calls >= 4)
ok("🚨 לא נוגעים בשדות הדף — רק שואלים אם מחובר",
   all("password" not in j.lower() and "value" not in j.lower() for j in NEXT_WIN[0].js))

# המשתמש סוגר את החלון לפני שהתחבר
db.save_cookie_for_url("https://mitmachim.top", "")
NEXT_WIN[0] = FakeWin(login_after=None, host="mitmachim.top")
api.start_forum_login("https://mitmachim.top")
time.sleep(0.05)
NEXT_WIN[0].events.closed.fire()
ok("סגירה הסתיימה", wait_done())
st = api.get_forum_login_progress()
ok("🚨 חלון שנסגר = בוטל, לא שגיאה ולא הצלחה", st["cancelled"] and not st["ok"], st)
ok("   ושום עוגייה לא נשמרה", not db.get_cookie_for_url("https://mitmachim.top"))

# אורח שלא התחבר עד הסוף
FL_TIMEOUT = FL.TIMEOUT_SEC
FL.TIMEOUT_SEC = 0.2
NEXT_WIN[0] = FakeWin(login_after=None, host="bina.top")
api.start_forum_login("https://bina.top")
ok("פג הזמן", wait_done())
st = api.get_forum_login_progress()
ok("פג הזמן — הודעה ברורה, והחלון נסגר", st["error"] and "זמן" in st["error"] and NEXT_WIN[0].destroyed, st)
ok("   ועוגיית אורח לא נשמרה", not db.get_cookie_for_url("https://bina.top"))
FL.TIMEOUT_SEC = FL_TIMEOUT

ok("פורום phpBB — הסבר במקום חלון", not api.start_forum_login("https://old.example")["ok"])
ok("בלי פורום", not api.start_forum_login("")["ok"])

# ══ 5. הממשק ══════════════════════════════════════════════════════════════
app = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
ok("כפתור התחברות ליד שדה העוגייה — בשלושת המקומות", app.count("🔑 התחבר לפורום</button>") == 3)
ok("🚨 ההדרכה: הדרך הקלה ראשונה", app.index("הכי קל: להתחבר מתוך התוכנה") < app.index("Get cookies.txt"))
ok("🚨 כתובת הפורום עוברת ב-data-* ולא בתוך מחרוזת JS",
   'data-login-url="${esc(c.url)}"' in app and "onclick=\"forumLogin(this.dataset.loginUrl)\"" in app)
ok("ההדרכה בחזונישניק ובשטינקניק יודעת איזה פורום נבחר",
   "toggleCookieHelp('chz-cookie-help', {url:" in app and "toggleCookieHelp('stink-cookie-help', {url:" in app)
ok("אחרי התחברות — שדות העוגייה מתמלאים", "refreshCookieFields();" in app)
ok("ההבטחה על הסיסמה כתובה", "הסיסמה מוקלדת באתר של הפורום עצמו" in app)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("FORUM LOGIN TESTS PASSED")
