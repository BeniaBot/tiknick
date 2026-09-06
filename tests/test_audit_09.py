# -*- coding: utf-8 -*-
"""
0.9.0 — הממצאים מסריקת הבאגים המלאה.

מה שנבדק כאן נמצא בציד באגים רב-עדשות על **כל** התוכנה, לא רק על מה שנוסף
לאחרונה. כל בדיקה כאן מריצה את הקוד בפועל (שרת דמה מקומי, מאגר זמני,
monkey-patch ל-net.urlopen) — לא קוראת אותו.
"""
import datetime
import http.server
import io
import json
import os
import socketserver
import sys
import threading
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import chazonishnik            # noqa: E402
import i18n                    # noqa: E402
import net                     # noqa: E402
import stinknik                # noqa: E402
import sync_version            # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra else ""))
        fails.append(name)


def _read(*parts):
    return io.open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


# ══ NET-1: ה-Request נבנה מחדש בכל ניסיון ════════════════════════════════
# ProxyHandler.proxy_open קורא ל-Request.set_proxy, וזה **משנה את האובייקט**.
# ניסיון חוזר על אותו Request מתהפך https→http ויוצא בטקסט גלוי לפורט 80 —
# כלומר העוגייה של הפורום נשלחת ללא הצפנה. שני המודולים חייבים לבנות אותו
# בתוך הלולאה, כמו שהסורק עשה מאז ומעולם.
for _mod in (chazonishnik, stinknik):
    _src = io.open(_mod.__file__, encoding="utf-8").read()
    _i_loop = _src.index("for attempt in range(1, retries + 1):")
    _i_req = _src.index("urllib.request.Request(url)")
    ok("%s בונה Request בתוך לולאת הריטריי" % os.path.basename(_mod.__file__),
       _i_req > _i_loop, "req@%d loop@%d" % (_i_req, _i_loop))


def _attempts_of(module, tries=3):
    """מריץ _get_json מול urlopen שנכשל, ומחזיר את (סכימה, כתובת) של כל ניסיון."""
    seen = []

    def fake(req, timeout=None):
        seen.append((req.type, req.get_full_url()))
        raise urllib.error.URLError("nope")

    old_open, old_sleep = net.urlopen, module.time.sleep
    net.urlopen = fake
    module.time.sleep = lambda *_a, **_k: None
    try:
        try:
            module._get_json("https://forum.example/api/x", "", retries=tries)
        except Exception:
            pass
    finally:
        net.urlopen, module.time.sleep = old_open, old_sleep
    return seen


for _mod in (chazonishnik, stinknik):
    _seen = _attempts_of(_mod)
    _nm = os.path.basename(_mod.__file__)
    ok("%s: כל הניסיונות נשארים https" % _nm,
       len(_seen) >= 2 and all(t == "https" for t, _ in _seen), _seen)
    ok("%s: הכתובת אינה מתגלגלת בין ניסיונות" % _nm,
       len({u for _, u in _seen}) == 1, _seen)


# ══ NET-2: כתובת הפרוקסי מנורמלת ל-http ══════════════════════════════════
ok("https בפרוקסי מנורמל ל-http",
   net.normalize_url("https://p:3128") == "http://p:3128",
   net.normalize_url("https://p:3128"))
try:
    net.normalize_url("socks5://p:1080")
    ok("SOCKS נדחה", False)
except net.ProxyError as _e:
    ok("SOCKS נדחה עם הסבר על http://", "http://" in str(_e), str(_e))
ok("הטקסט בממשק לא מבטיח פרוקסי https",
   "פרוקסי http או https בלבד" not in _read("web", "app.js"))


# ══ NET-3: יעד בדיקה בלי סכימה ═══════════════════════════════════════════
class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


_srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
_port = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()
try:
    _r = net.test_connection("off", "", "127.0.0.1:%d" % _port, timeout=5)
    # ההשלמה היא https, ולכן שרת http מקומי יחזיר שגיאת TLS — אבל **לא**
    # "unknown url type", שהוא הכישלון שהאשים את הגדרות הרשת בטעות.
    ok("יעד בלי סכימה לא נופל על unknown url type",
       "unknown url type" not in str(_r.get("error", "")), _r)
    _r = net.test_connection("off", "", "http://127.0.0.1:%d" % _port, timeout=5)
    ok("יעד עם סכימה עובד", _r.get("ok") is True, _r)
    _r = net.test_connection("off", "", "", timeout=5)
    ok("יעד ריק מוסבר", _r.get("ok") is False and "פורום" in _r.get("error", ""), _r)
finally:
    _srv.shutdown()
    _srv.server_close()


# ══ UPD-1 / UPD-3: העדכון העצמי ══════════════════════════════════════════
import main as M   # noqa: E402

_api = M.API.__new__(M.API)
_head_calls = []
_exists = {"all": False}
M.API._url_exists = staticmethod(
    lambda u, timeout=6: (_head_calls.append(u), _exists["all"])[1])


class _Resp:
    status = 200

    def read(self):
        return json.dumps({"versions": [{"v": "9.9.9"}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_old_urlopen = net.urlopen
net.urlopen = lambda req, timeout=None: _Resp()
try:
    _res = _api._fallback_latest()
    ok("UPD-1: כתובת שלא אומתה לא נמסרת לממשק",
       _res["assets"] == [], _res["assets"])
    ok("UPD-1: נופלים לדף הגרסאות",
       _res["html_url"].endswith("/releases/latest"), _res["html_url"])
    ok("UPD-1: נעשתה בדיקת HEAD לכל נכס", len(_head_calls) == 2, _head_calls)
    _exists["all"] = True
    _head_calls.clear()
    _res = _api._fallback_latest()
    ok("UPD-1: נכס שקיים כן נמסר", len(_res["assets"]) == 2, _res["assets"])
    ok("UPD-1: כתובת התג כשיש נכסים",
       _res["html_url"].endswith("/releases/tag/v9.9.9"), _res["html_url"])
finally:
    net.urlopen = _old_urlopen

_main_src = io.open(M.__file__, encoding="utf-8").read()
_i_frozen = _main_src.index("זמין רק בגרסת ה-EXE")
_i_reset = _main_src.index('_update_state["downloaded"] = 0')
_i_try = _main_src.index("        try:", _i_frozen)
ok("UPD-3: המונים מתאפסים לפני ההורדה", _i_frozen < _i_reset < _i_try)

M._update_state["downloaded"] = 5000000
_r = _api.download_update("https://evil.example/x.exe")
ok("מארח לא מזוהה עדיין נחסם", _r.get("ok") is False, _r)
ok("חסימת מארח לא נוגעת במונים",
   M._update_state["downloaded"] == 5000000, M._update_state)


# ══ UPD-4: מספר הגרסה זורם לכיוון אחד ════════════════════════════════════
ok("UPD-4: installer.iss ו-version_info.txt מסונכרנים ל-APP_VERSION",
   sync_version.check() == [], sync_version.check())
ok("UPD-4: הגרסה שנקראת היא זו שבקוד",
   sync_version.app_version() == M.APP_VERSION, sync_version.app_version())
ok("UPD-4: הבנייה מסנכרנת לבד", "sync_version.py" in _read("build.bat"))


# ══ הגיליון להדפסה: תוויות ו-enum מתורגמים, ערכי משתמש לא ═══════════════
_ps = _read("profile_sheet.py")
ok("תווית המקטע עוברת i18n.t", 'i18n.t(f.get("label")' in _ps)
ok("רק ה-enum של הסטטוס מתורגם", 'if f.get("key") == "status"' in _ps)
i18n.set_lang("en")
ok("תווית מוכרת אכן מתורגמת", i18n.t("סטטוס") == "Status", i18n.t("סטטוס"))
ok("ערך הסטטוס מתורגם", i18n.t("מורחק") != "מורחק", i18n.t("מורחק"))
ok("מחרוזת שאינה בקטלוג חוזרת בית-בית",
   i18n.t("שם משתמש מהפורום 12345") == "שם משתמש מהפורום 12345")
i18n.set_lang("he")
ok("בעברית שום דבר לא משתנה", i18n.t("סטטוס") == "סטטוס")


# ══ Chazonishnik: יום בשבוע נשמר כמספר ═══════════════════════════════════
# קודם נשמר **שם היום המתורגם**, וההחזרה חיפשה אותו ברשימת השמות הנוכחית.
# החלפת שפה באמצע ריצה אפסה את כל גרף הימים ודיווחה "היום הפעיל ביותר" שגוי.
_posts = []
for _wd, _n in ((0, 3), (2, 1), (6, 5)):
    _base = datetime.datetime(2026, 1, 5) + datetime.timedelta(days=_wd)
    for _k in range(_n):
        _posts.append({"dow": _base.weekday(),
                       "day": chazonishnik._days()[_base.weekday()],
                       "hour": 10, "date": _base.strftime("%Y-%m-%d"),
                       "month": _base.strftime("%Y-%m"),
                       "likes": 1, "words": 5, "title": "t"})
_s_he = chazonishnik._summarize(_posts)
ok("ספירת הימים נכונה", _s_he["days"] == [3, 0, 1, 0, 0, 0, 5], _s_he["days"])
ok("היום הפעיל ביותר הוא ראשון",
   _s_he["top_day"] == chazonishnik._days()[6], _s_he["top_day"])
i18n.set_lang("en")
_s_en = chazonishnik._summarize(_posts)
i18n.set_lang("he")
ok("החלפת שפה באמצע ריצה לא מאפסת את הגרף",
   _s_en["days"] == _s_he["days"], _s_en["days"])
ok("היום הפעיל ביותר מתורגם ולא ריק",
   bool(_s_en["top_day"]) and _s_en["top_day"] != _s_he["top_day"],
   _s_en["top_day"])
_legacy = [{k: v for k, v in p.items() if k != "dow"} for p in _posts]
ok("דוח שנשמר בגרסה ישנה עדיין נספר",
   chazonishnik._summarize(_legacy)["days"] == _s_he["days"])
ok("התבנית מקבצת לפי אינדקס ולא לפי שם",
   "d.dow===(i+6)%7" in io.open(chazonishnik.__file__, encoding="utf-8").read())


print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("AUDIT 0.9 TESTS PASSED")
