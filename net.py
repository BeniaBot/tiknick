# -*- coding: utf-8 -*-
"""
net.py — יציאה אחת לאינטרנט לכל התוכנה.

כל בקשה יוצאת — סריקה, Chazonishnik, Stinknik, בדיקת עדכון והורדתו — עוברת
דרך `net.urlopen`. הסיבה היא לא רק פרוקסי: ברגע שיש נקודה אחת, אפשר להוסיף
בה בעתיד timeout אחיד, User-Agent או מדידה, בלי לחזר אחרי כל קריאה בנפרד.

שלושה מצבים:
  system  — ברירת המחדל. פרוקסי המערכת ומשתני הסביבה, כלומר בדיוק ההתנהגות
            שהייתה עד היום. לא נוגעים בכלום.
  off     — התעלמות מפרוקסי שהוגדר במערכת (חיבור ישיר).
  manual  — כתובת http/https מפורשת.

ההגדרה נשמרת ב-settings ונטענת בעליית התוכנה, לפני הבקשה היוצאת הראשונה.
הגדרה שמורה פגומה **לא משתקת את הרשת**: נופלים ל-system ורושמים ליומן.
"""
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MODE_SYSTEM, MODE_OFF, MODE_MANUAL = "system", "off", "manual"
MODES = (MODE_SYSTEM, MODE_OFF, MODE_MANUAL)
SETTING_MODE, SETTING_URL = "proxy_mode", "proxy_url"
DEFAULT_PORT = 8080

_DEFAULT_TIMEOUT = socket._GLOBAL_DEFAULT_TIMEOUT
_lock = threading.RLock()
_state = {"mode": MODE_SYSTEM, "url": "", "opener": None}


class ProxyError(Exception):
    """הגדרה שאי אפשר להשתמש בה. ההודעה מוצגת למשתמש כמו שהיא."""


def normalize_url(raw):
    """'10.0.0.5:8080' → 'http://10.0.0.5:8080'. כל קלט אחר מרים ProxyError."""
    s = (raw or "").strip()
    if not s:
        raise ProxyError("לא הוזנה כתובת פרוקסי")
    if any(c.isspace() for c in s):
        raise ProxyError("כתובת הפרוקסי מכילה רווח")
    if "://" not in s:
        s = "http://" + s
    try:
        p = urllib.parse.urlsplit(s)
        host, port = p.hostname, p.port
    except ValueError:
        raise ProxyError("הפורט חייב להיות מספר בין 1 ל-65535")
    if p.scheme not in ("http", "https"):
        raise ProxyError("כתובת הפרוקסי נכתבת עם http:// (גם פרוקסי שמעביר "
                         "תעבורת https). SOCKS אינו נתמך.")
    if not host:
        raise ProxyError("חסרה כתובת של שרת הפרוקסי")
    if p.path.strip("/") or p.query or p.fragment:
        raise ProxyError("כתובת פרוקסי היא שרת ופורט בלבד — בלי נתיב")
    # שם המשתמש והסיסמה נשארים כפי שהודבקו — urllib מפענח %XX בעצמו
    userinfo = p.netloc.rpartition("@")[0]
    hostpart = "[%s]" % host if ":" in host else host
    # אל *הפרוקסי עצמו* פונים תמיד ב-HTTP רגיל, גם כשהוא מעביר תעבורת https:
    # urllib שולח CONNECT על הסוקט הגולמי ורק אחר כך עוטף ב-TLS. "https://"
    # בכתובת הפרוקסי היה מבטיח הצפנה שלא קיימת, ולכן הוא מנורמל.
    return "http://%s%s:%d" % (userinfo + "@" if userinfo else "",
                               hostpart, port or DEFAULT_PORT)


def mask_url(url):
    """אותה כתובת בלי הסיסמה — ליומן ולתצוגה."""
    try:
        pw = urllib.parse.urlsplit(url).password if url else None
    except ValueError:
        pw = None
    return url.replace(":" + pw + "@", ":***@", 1) if pw else (url or "")


def describe(mode, url=""):
    if mode == MODE_OFF:
        return "חיבור ישיר (מתעלם מפרוקסי המערכת)"
    if mode == MODE_MANUAL:
        return "פרוקסי: " + mask_url(url)
    return "לפי הגדרות המערכת"


def build_opener(mode, url=""):
    """opener של urllib, או None ל-system (שם urlopen הרגיל כבר נכון)."""
    mode = (mode or MODE_SYSTEM).strip().lower()
    if mode == MODE_SYSTEM:
        return None
    if mode == MODE_OFF:
        # ProxyHandler ריק = התעלמות מפרוקסי המערכת ומהמשתנים
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if mode != MODE_MANUAL:
        raise ProxyError("מצב רשת לא מוכר: %s" % mode)
    u = normalize_url(url)
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": u, "https": u}))


def apply(mode, url=""):
    """מחיל על כל התוכנה. הגדרה פסולה מרימה ProxyError ולא משנה כלום."""
    mode = (mode or MODE_SYSTEM).strip().lower()
    url = normalize_url(url) if mode == MODE_MANUAL else ""
    opener = build_opener(mode, url)      # קודם בונים, ורק אז מחליפים
    with _lock:
        _state.update(mode=mode, url=url, opener=opener)
    return current()


def current():
    with _lock:
        mode, url = _state["mode"], _state["url"]
    return {"mode": mode, "url": url, "masked": mask_url(url),
            "description": describe(mode, url)}


def apply_from_settings(get_setting):
    """טוען ומחיל את השמור. הגדרה פגומה לא משאירה את התוכנה בלי רשת."""
    try:
        return dict(apply(get_setting(SETTING_MODE, MODE_SYSTEM),
                          get_setting(SETTING_URL, "")), ok=True)
    except Exception as e:
        apply(MODE_SYSTEM)
        return dict(current(), ok=False, error=str(e))


def urlopen(url, data=None, timeout=_DEFAULT_TIMEOUT):
    """כמו urllib.request.urlopen — אותן שגיאות בדיוק, רק דרך ההגדרה שנבחרה."""
    with _lock:
        opener = _state["opener"]
    if opener:
        return opener.open(url, data, timeout)
    return urllib.request.urlopen(url, data, timeout)


def test_connection(mode, url="", target=None, timeout=12):
    """
    בודק הגדרה **בלי להחיל אותה** — אחרת כתובת שגויה הייתה שוברת סריקה
    שרצה באותו רגע ברקע.
    """
    target = (target or "").strip()
    if not target:
        return {"ok": False, "error": "אין פורום עם כתובת לבדוק מולו"}
    # כתובת פורום נשמרת לפעמים בלי סכימה. בלי ההשלמה הזו הבדיקה נכשלה
    # ב-"unknown url type" והאשימה את הגדרות הרשת במשהו שאינו קשור אליהן.
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    try:
        opener = build_opener(mode, url)
        req = urllib.request.Request(target, headers={"User-Agent": "Tik-Nick"})
        t0 = time.monotonic()
        resp = opener.open(req, timeout=timeout) if opener else \
            urllib.request.urlopen(req, timeout=timeout)
        with resp:
            return {"ok": True, "ms": int((time.monotonic() - t0) * 1000)}
    except ProxyError as e:
        return {"ok": False, "error": str(e)}
    except urllib.error.HTTPError as e:
        # 401/403 מהפורום עדיין אומרים שהחיבור עצמו עבד
        if e.code in (401, 403):
            return {"ok": True, "ms": 0, "note": "החיבור עובד (הפורום דורש התחברות)"}
        return {"ok": False, "error": "השרת החזיר שגיאה %s" % e.code}
    except Exception as e:
        return {"ok": False, "error": "לא ניתן להתחבר: %s" % getattr(e, "reason", e)}
