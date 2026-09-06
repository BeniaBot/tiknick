# -*- coding: utf-8 -*-
"""
net.py — יציאה אחת לאינטרנט לכל Tik-Nick, עם תמיכה בפרוקסי.

כל בקשה יוצאת בתוכנה (סריקה, Chazonishnik, Stinknik, בדיקת עדכון והורדתו)
עוברת דרך `net.urlopen`, כדי שהגדרה אחת תחול על כולן ולא יישאר מסלול שממשיך
לצאת ישירות. שלושה מצבים: system (ברירת המחדל — פרוקסי המערכת ומשתני
הסביבה, כלומר ההתנהגות שהייתה עד היום), off (ישיר), manual (כתובת מפורשת).
ההגדרה נשמרת ב-settings (proxy_mode / proxy_url) ונטענת בעליית התוכנה.
"""
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MODE_SYSTEM, MODE_OFF, MODE_MANUAL = "system", "off", "manual"
SETTING_MODE, SETTING_URL = "proxy_mode", "proxy_url"
DEFAULT_PORT = 8080
# בדיקת החיבור מכוונת לפורום ולא ל"אינטרנט" — זה מה שהמשתמש רוצה לדעת.
DEFAULT_TEST_URL = "https://mitmachim.top/api/config"

_DEFAULT_TIMEOUT = socket._GLOBAL_DEFAULT_TIMEOUT
_lock = threading.RLock()
_state = {"mode": MODE_SYSTEM, "url": "", "opener": None}


class ProxyError(Exception):
    """הגדרה שאי אפשר להשתמש בה — ההודעה מוצגת למשתמש כמו שהיא."""


def normalize_url(raw):
    """'10.0.0.5:8080' → 'http://10.0.0.5:8080'. כל קלט אחר מרים ProxyError."""
    s = (raw or "").strip()
    if not s:
        raise ProxyError("לא הוזנה כתובת פרוקסי")
    if any(c.isspace() for c in s):
        raise ProxyError("כתובת הפרוקסי מכילה רווח")
    if "://" not in s:
        s = "http://" + s
    p = urllib.parse.urlsplit(s)
    if p.scheme not in ("http", "https"):
        raise ProxyError("נתמכים פרוקסי http ו-https בלבד")
    try:
        host, port = p.hostname, p.port
    except ValueError:
        raise ProxyError("הפורט חייב להיות מספר בין 1 ל-65535")
    if not host:
        raise ProxyError("חסרה כתובת של שרת הפרוקסי")
    if p.path.strip("/") or p.query:
        raise ProxyError("כתובת פרוקסי היא שרת ופורט בלבד — בלי נתיב")
    # שם המשתמש והסיסמה נשארים כפי שהודבקו: urllib מפענח %XX בעצמו.
    user = p.netloc.rpartition("@")[0]
    return "%s://%s%s:%d" % (p.scheme, user + "@" if user else "",
                             "[%s]" % host if ":" in host else host, port or DEFAULT_PORT)


def mask_url(url):
    """אותה כתובת בלי הסיסמה — ללוג ולתצוגה."""
    pw = urllib.parse.urlsplit(url).password if url else None
    return url.replace(":" + pw + "@", ":***@", 1) if pw else (url or "")


def describe(mode, url=""):
    return ("חיבור ישיר (בלי פרוקסי)" if mode == MODE_OFF else
            "פרוקסי: " + mask_url(url) if mode == MODE_MANUAL else
            "לפי הגדרות המערכת")


def build_opener(mode, url=""):
    """opener של urllib להגדרה, או None ל-system (שם urlopen הרגיל כבר נכון)."""
    mode = (mode or MODE_SYSTEM).strip().lower()
    if mode == MODE_SYSTEM:
        return None
    if mode == MODE_OFF:   # ProxyHandler ריק = התעלמות מפרוקסי המערכת
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if mode != MODE_MANUAL:
        raise ProxyError("מצב פרוקסי לא מוכר: %s" % mode)
    u = normalize_url(url)
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": u, "https": u}))


def apply(mode, url=""):
    """מחיל על כל התוכנה. הגדרה פסולה מרימה ProxyError ולא משנה כלום."""
    mode = (mode or MODE_SYSTEM).strip().lower()
    url = normalize_url(url) if mode == MODE_MANUAL else ""
    opener = build_opener(mode, url)
    with _lock:
        _state.update(mode=mode, url=url, opener=opener)
    return current()


def current():
    with _lock:
        mode, url = _state["mode"], _state["url"]
    return {"mode": mode, "url": url, "masked": mask_url(url),
            "description": describe(mode, url)}


def apply_from_settings(get_setting):
    """טוען ומחיל את השמור. הגדרה פגומה לא משתקת את הרשת — נופלים ל-system."""
    try:
        return dict(apply(get_setting(SETTING_MODE, MODE_SYSTEM),
                          get_setting(SETTING_URL, "")), ok=True)
    except Exception as e:
        apply(MODE_SYSTEM)
        return dict(current(), ok=False, error=str(e))


def urlopen(url, data=None, timeout=_DEFAULT_TIMEOUT):
    """כמו urllib.request.urlopen, רק דרך הפרוקסי שנבחר. אותן שגיאות בדיוק."""
    with _lock:
        opener = _state["opener"]
    if opener:
        return opener.open(url, data, timeout)
    return urllib.request.urlopen(url, data, timeout)


def test_connection(mode, url="", target=None, timeout=12):
    """בודק הגדרה *בלי* להחיל אותה, כדי לא לשבור סריקה שרצה ברקע."""
    target = (target or DEFAULT_TEST_URL).strip()
    try:
        opener = build_opener(mode, url)
        req = urllib.request.Request(target, headers={"User-Agent": "Tik-Nick"})
        t0 = time.monotonic()
        with (opener.open(req, timeout=timeout) if opener
              else urllib.request.urlopen(req, timeout=timeout)):
            return {"ok": True, "ms": int((time.monotonic() - t0) * 1000)}
    except ProxyError as e:
        return {"ok": False, "error": str(e)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "השרת החזיר שגיאה %s" % e.code}
    except Exception as e:
        return {"ok": False, "error": "לא ניתן להתחבר: %s" % getattr(e, "reason", e)}
