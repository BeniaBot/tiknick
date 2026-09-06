# -*- coding: utf-8 -*-
"""
0.8.23: שלושת החורים ש-PR #1 חשף — נבדקים בהרצה בפועל, לא בקריאה.

הבדיקות כאן מזייפות תשובות רשת ומריצות את הקוד האמיתי, כי שלושת הדברים
האלה נראים נכון בקריאה: לולאת עמודים "עם השהיה" (שאין בה), הודעת שגיאה
"ברורה" (שמפנה לפתרון הלא נכון), ודיווח חלקי "שנרשם" (שלא נרשם בשום מקום).
"""
import io
import logging
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scraper        # noqa: E402
import chazonishnik   # noqa: E402
import stinknik       # noqa: E402

fails = []


def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)


class _Resp:
    """תשובת HTTP מזויפת שמתנהגת כמנהל הקשר, כמו urlopen."""
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


CHALLENGE = ("<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
             "<body><div class='cf-browser-verification'></div>"
             "<script>window._cf_chl_opt={};</script></body></html>")

# ══ 1. Cloudflare: לומר את האמת במקום מסקנה שגויה ════════════════════════
_real_urlopen = scraper.net.urlopen
_real_sleep = scraper.time.sleep
scraper.time.sleep = lambda *_a, **_k: None      # בלי המתנות בבדיקה

try:
    # (א) אתגר שחוזר עם קוד 200 ו-HTML
    scraper.net.urlopen = lambda *a, **k: _Resp(CHALLENGE)
    try:
        scraper._fetch_json("https://x.example/api/users")
        ok("אתגר Cloudflare ב-200 מזוהה", False, "לא הורמה שגיאה")
    except scraper.ScrapeError as e:
        ok("אתגר Cloudflare ב-200 מזוהה", "Cloudflare" in str(e), str(e)[:70])
    except Exception as e:
        ok("אתגר Cloudflare ב-200 מזוהה", False, type(e).__name__)

    # (ב) HTML רגיל שאינו אתגר — ההודעה הישנה חייבת להישאר
    scraper.net.urlopen = lambda *a, **k: _Resp("<html><body>שלום</body></html>")
    try:
        scraper._fetch_json("https://x.example/api/users")
        ok("HTML רגיל עדיין מדווח 'אין API'", False, "לא הורמה שגיאה")
    except scraper.ScrapeError as e:
        ok("HTML רגיל עדיין מדווח 'אין API'",
           "Cloudflare" not in str(e) and "API" in str(e), str(e)[:70])

    # (ג) אתגר שחוזר כ-403 — קודם נשלח המשתמש לחפש עוגייה שלא תעזור
    def _raise_403(*a, **k):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {},
                                     io.BytesIO(CHALLENGE.encode("utf-8")))
    scraper.net.urlopen = _raise_403
    try:
        scraper._fetch_json("https://x.example/api/users")
        ok("אתגר Cloudflare ב-403 אינו 'נדרשת עוגייה'", False, "לא הורמה שגיאה")
    except scraper.AuthRequired as e:
        ok("אתגר Cloudflare ב-403 אינו 'נדרשת עוגייה'", False, "AuthRequired: " + str(e)[:50])
    except scraper.ScrapeError as e:
        ok("אתגר Cloudflare ב-403 אינו 'נדרשת עוגייה'", "Cloudflare" in str(e), str(e)[:70])

    # (ד) 403 אמיתי של הרשאה — חייב להישאר AuthRequired
    def _raise_403_plain(*a, **k):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {},
                                     io.BytesIO(b'{"error":"not-allowed"}'))
    scraper.net.urlopen = _raise_403_plain
    try:
        scraper._fetch_json("https://x.example/api/users")
        ok("403 רגיל נשאר 'נדרשת התחברות'", False, "לא הורמה שגיאה")
    except scraper.AuthRequired:
        ok("403 רגיל נשאר 'נדרשת התחברות'", True)
    except Exception as e:
        ok("403 רגיל נשאר 'נדרשת התחברות'", False, type(e).__name__ + ": " + str(e)[:40])
finally:
    scraper.net.urlopen = _real_urlopen
    scraper.time.sleep = _real_sleep

ok("הזיהוי אינו תופס טקסט רגיל", not scraper._looks_like_challenge("שלום עולם"))
ok("הזיהוי תופס גם באותיות גדולות",
   scraper._looks_like_challenge("<TITLE>JUST A MOMENT...</TITLE>"))

# ══ 2. Chazonishnik: השהיה בין עמודים ═══════════════════════════════════
sleeps = []
_chz_sleep, _chz_get = chazonishnik.time.sleep, chazonishnik._get_json
pages = {1: {"posts": [{"pid": 1}]}, 2: {"posts": [{"pid": 2}]},
         3: {"posts": [{"pid": 3}]}, 4: {"posts": []}}


def _fake_get(url, cookie=None, **k):
    page = int(url.rsplit("page=", 1)[1])
    return pages.get(page, {"posts": []})


chazonishnik.time.sleep = lambda s: sleeps.append(s)
chazonishnik._get_json = _fake_get
try:
    got = chazonishnik._scan_posts("https://x.example", "beni", None, stats={})
finally:
    chazonishnik.time.sleep = _chz_sleep
    chazonishnik._get_json = _chz_get

ok("נסרקו כל העמודים", len(got[0] if isinstance(got, tuple) else got) >= 3, str(got)[:60])
ok("יש השהיה בין עמודים", len(sleeps) >= 3, str(sleeps))
ok("ההשהיה היא PAGE_DELAY", all(s == chazonishnik.PAGE_DELAY for s in sleeps), str(sleeps))
ok("ההשהיה בסדר גודל של שאר הכלים",
   0.3 <= chazonishnik.PAGE_DELAY <= 1.0, str(chazonishnik.PAGE_DELAY))
# הסורק ו-Stinknik ממתינים גם הם — שלושתם צריכים להיות באותו סדר גודל
ok("הסורק ממתין בין עמודים", 0.3 <= scraper.PAGE_DELAY_SEC <= 1.0, str(scraper.PAGE_DELAY_SEC))

# ══ 3. עמוד שנכשל נרשם ליומן ═════════════════════════════════════════════
buf = io.StringIO()
h = logging.StreamHandler(buf)
h.setLevel(logging.WARNING)
root = logging.getLogger()
root.addHandler(h)
prev_level = root.level
root.setLevel(logging.WARNING)


def _boom(url, cookie=None, **k):
    page = int(url.rsplit("page=", 1)[1])
    if page == 1:
        return {"posts": [{"pid": 1}]}
    raise OSError("connection reset")


_chz_sleep, _chz_get = chazonishnik.time.sleep, chazonishnik._get_json
chazonishnik.time.sleep = lambda *_a: None
chazonishnik._get_json = _boom
st = {}
try:
    chazonishnik._scan_posts("https://x.example", "beni", None, stats=st)
finally:
    chazonishnik.time.sleep = _chz_sleep
    chazonishnik._get_json = _chz_get
    root.removeHandler(h)
    root.setLevel(prev_level)

logged = buf.getvalue()
ok("עמוד שנכשל מסומן כדוח חלקי", st.get("stopped_early") is True, str(st))
ok("ועכשיו גם נרשם ליומן", "Chazonishnik" in logged and "failed" in logged, logged[:90])
ok("היומן אומר איזה עמוד", "page 2" in logged, logged[:90])

for mod, name in ((chazonishnik, "chazonishnik"), (stinknik, "stinknik")):
    ok("%s מייבא logging" % name, hasattr(mod, "logging"))

# אותו דבר ב-Stinknik, בהרצה אמיתית של analyze_dislikes
buf2 = io.StringIO()
h2 = logging.StreamHandler(buf2)
h2.setLevel(logging.WARNING)
root.addHandler(h2)
root.setLevel(logging.WARNING)
_sk_resolve, _sk_get, _sk_sleep = stinknik._resolve_user, stinknik._get_json, stinknik.time.sleep
stinknik._resolve_user = lambda base, u, cookie=None: ("beni", 100)
_n = {"i": 0}


def _sk_boom(url, cookie=None, **k):
    _n["i"] += 1
    if _n["i"] == 1:
        return {"posts": [{"pid": 1, "upvotes": 1, "downvotes": 0, "votes": 1,
                           "topic": {"title": "x"}, "timestamp": 0}]}
    raise OSError("connection reset")


stinknik._get_json = _sk_boom
stinknik.time.sleep = lambda *_a: None
try:
    res = stinknik.analyze_dislikes("beni", base_url="https://x.example")
finally:
    stinknik._resolve_user, stinknik._get_json = _sk_resolve, _sk_get
    stinknik.time.sleep = _sk_sleep
    root.removeHandler(h2)
    root.setLevel(prev_level)

sk_log = buf2.getvalue()
ok("Stinknik מדווח דוח חלקי", res.get("stopped_early") is True, str(res.get("stopped_early")))
ok("ו-Stinknik רושם ליומן איזה עמוד",
   "Stinknik" in sk_log and "page 2" in sk_log, sk_log.strip()[:80])

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("SCRAPE-MANNERS TESTS PASSED")
