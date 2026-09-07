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
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MODE_SYSTEM, MODE_OFF, MODE_MANUAL = "system", "off", "manual"
# "ישיר, ופרוקסי רק אם נכשל" — לכל פורום בנפרד.
MODE_FALLBACK = "fallback"
MODES = (MODE_SYSTEM, MODE_OFF, MODE_MANUAL, MODE_FALLBACK)
SETTING_MODE, SETTING_URL = "proxy_mode", "proxy_url"
SETTING_ROUTES = "proxy_routes"
DEFAULT_PORT = 8080

# כמה זמן זוכרים ש-origin מסוים דורש פרוקסי. בלי תפוגה, פורום שהיה למטה
# לדקה היה נשאר נעול על הפרוקסי לתמיד.
ROUTE_TTL_SEC = 6 * 3600
# הניסיון הישיר לפני הנפילה לפרוקסי חייב להיות קצר: מול מארח חסום, timeout
# מלא כפול 24 פורומים הוא סריקה שנתקעת לרבע שעה לפני שהיא בכלל מתחילה.
FALLBACK_PROBE_TIMEOUT = 6

_DEFAULT_TIMEOUT = socket._GLOBAL_DEFAULT_TIMEOUT
_lock = threading.RLock()
_state = {"mode": MODE_SYSTEM, "url": "", "opener": None,
          "direct": None, "proxy": None}
# origin -> (route, expires_at). route: "direct" | "proxy"
_routes = {}
_route_store = {"get": None, "set": None}


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
    if mode == MODE_FALLBACK:
        return "ישיר, ופרוקסי רק כשנכשל: " + mask_url(url)
    return "לפי הגדרות המערכת"


class _StripCookieOnCrossOrigin(urllib.request.HTTPRedirectHandler):
    """
    הכלל "עוגייה של פורום אחד לא נשלחת לפורום אחר" נאכף בכל מסלולי התוכנה —
    ונשבר בהפניה. `HTTPRedirectHandler.redirect_request` מעתיק **כל** כותרת
    (חוץ מ-content-length/content-type) אל הבקשה החדשה, ולכן 302 מפורום A
    לכל מארח אחר נושא איתו את express.sid כמו שהוא. זה לא תרחיש תיאורטי:
    אלה התקנות קטנות שמתנדבים מתחזקים, ופורום שעבר דומיין עונה בהפניה.

    כאן ההפניה עצמה נשמרת (היא לגיטימית), אבל הכותרת יורדת ברגע שה-origin
    משתנה. שינוי סכימה בלבד (http→https) על אותו מארח ופורט אינו חציית origin.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if _same_origin(req.get_full_url(), newurl):
            return new
        for h in list(new.headers):
            if h.lower() == "cookie":
                del new.headers[h]
        for h in list(getattr(new, "unredirected_hdrs", {})):
            if h.lower() == "cookie":
                del new.unredirected_hdrs[h]
        logging.info("Dropped Cookie header on cross-origin redirect to %s",
                     urllib.parse.urlsplit(newurl).netloc)
        return new


def _same_origin(a, b):
    pa, pb = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    if (pa.hostname or "").lower() != (pb.hostname or "").lower():
        return False
    dflt = {"http": 80, "https": 443}
    return (pa.port or dflt.get(pa.scheme, 0)) == (pb.port or dflt.get(pb.scheme, 0))


def build_opener(mode, url=""):
    """opener של urllib, או None ל-system (שם urlopen הרגיל כבר נכון)."""
    mode = (mode or MODE_SYSTEM).strip().lower()
    # מדיניות ההפניה חלה **בכל** מצב, כולל system — קודם system החזיר None
    # ונפל ל-urlopen הרגיל, כלומר דווקא ברירת המחדל הייתה זו שדלפה.
    if mode == MODE_SYSTEM:
        return urllib.request.build_opener(_StripCookieOnCrossOrigin())
    if mode == MODE_OFF:
        # ProxyHandler ריק = התעלמות מפרוקסי המערכת ומהמשתנים
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                           _StripCookieOnCrossOrigin())
    if mode not in (MODE_MANUAL, MODE_FALLBACK):
        raise ProxyError("מצב רשת לא מוכר: %s" % mode)
    u = normalize_url(url)
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": u, "https": u}),
        _StripCookieOnCrossOrigin())


def apply(mode, url=""):
    """מחיל על כל התוכנה. הגדרה פסולה מרימה ProxyError ולא משנה כלום."""
    mode = (mode or MODE_SYSTEM).strip().lower()
    url = normalize_url(url) if mode in (MODE_MANUAL, MODE_FALLBACK) else ""
    opener = build_opener(mode, url)      # קודם בונים, ורק אז מחליפים
    direct = build_opener(MODE_OFF) if mode == MODE_FALLBACK else None
    with _lock:
        _state.update(mode=mode, url=url, opener=opener,
                      direct=direct, proxy=opener if mode == MODE_FALLBACK else None)
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


def _origin_of(url):
    """המפתח שלפיו זוכרים. אותו origin שלפיו נשמרות העוגיות."""
    try:
        u = url if isinstance(url, str) else url.get_full_url()
        p = urllib.parse.urlsplit(u)
        return "%s://%s" % (p.scheme.lower(), (p.netloc or "").lower())
    except Exception:
        return ""


def set_route_store(get_setting, set_setting):
    """
    מחבר את זיכרון הניתוב להגדרות, כדי שהוא ישרוד סגירה של התוכנה.

    בלי זה הוא חי בזיכרון בלבד, ואז **כל הפעלה** משלמת ניסיון ישיר כושל לכל
    פורום חסום — עם 24 פורומים זה דקות של המתנה לפני שהסריקה בכלל מתחילה.
    net.py עצמו לא מכיר את המאגר; main.py מחבר אותו אחרי init_db.
    """
    with _lock:
        _route_store["get"], _route_store["set"] = get_setting, set_setting
    _load_routes()


def _load_routes():
    get = _route_store.get("get")
    if not get:
        return
    try:
        raw = json.loads(get(SETTING_ROUTES, "") or "{}")
    except Exception:
        return
    now = time.time()
    with _lock:
        _routes.clear()
        for origin, ent in (raw or {}).items():
            try:
                route, exp = ent[0], float(ent[1])
            except Exception:
                continue
            if route in ("direct", "proxy") and exp > now:
                _routes[origin] = (route, exp)


def _save_routes():
    setter = _route_store.get("set")
    if not setter:
        return
    with _lock:
        snapshot = {k: [v[0], v[1]] for k, v in _routes.items()}
    try:
        setter(SETTING_ROUTES, json.dumps(snapshot))
    except Exception:
        logging.debug("Could not persist proxy routes", exc_info=True)


def _route_for(origin):
    if not origin:
        return None
    with _lock:
        ent = _routes.get(origin)
    if not ent:
        return None
    if ent[1] <= time.time():
        with _lock:
            _routes.pop(origin, None)
        return None
    return ent[0]


def _remember_route(origin, route):
    if not origin:
        return
    with _lock:
        prev = _routes.get(origin)
        _routes[origin] = (route, time.time() + ROUTE_TTL_SEC)
    if not prev or prev[0] != route:
        logging.info("Network route for %s: %s", origin, route)
    _save_routes()


def forget_routes():
    """שוכח את מה שנלמד — למשל אחרי שהמשתמש שינה את הגדרות הרשת."""
    with _lock:
        _routes.clear()
    _save_routes()


def routes_snapshot():
    """מה שנלמד עד כה, לתצוגה בממשק."""
    now = time.time()
    with _lock:
        return {k: v[0] for k, v in _routes.items() if v[1] > now}


def urlopen(url, data=None, timeout=_DEFAULT_TIMEOUT):
    """כמו urllib.request.urlopen — אותן שגיאות בדיוק, רק דרך ההגדרה שנבחרה."""
    with _lock:
        mode, opener = _state["mode"], _state["opener"]
        direct, proxy = _state["direct"], _state["proxy"]
    if opener is None:                 # לפני apply() בעליית התוכנה
        opener = build_opener(MODE_SYSTEM)
    if mode != MODE_FALLBACK or not direct or not proxy:
        return opener.open(url, data, timeout)

    # ── ישיר, ופרוקסי רק כשנכשל ──────────────────────────────────────────
    origin = _origin_of(url)
    if _route_for(origin) == "proxy":
        return proxy.open(url, data, timeout)

    probe = timeout
    if probe in (None, _DEFAULT_TIMEOUT) or probe > FALLBACK_PROBE_TIMEOUT:
        probe = FALLBACK_PROBE_TIMEOUT
    try:
        resp = direct.open(url, data, probe)
        _remember_route(origin, "direct")
        return resp
    except urllib.error.HTTPError:
        # השרת **ענה**. 401/403 הם תשובה תקפה של פורום שדורש התחברות, ו-5xx
        # הוא תקלה שלו — בשום מקרה לא סימן שהחיבור הישיר חסום. פרוקסי לא
        # יעזור כאן, ולכן לא מנסים דרכו ולא לומדים כלום.
        _remember_route(origin, "direct")
        raise
    except Exception as e:
        # כשל **רשת**: חסימה, DNS, timeout, סירוב חיבור. זה המקרה היחיד
        # שבו יש טעם לנסות דרך הפרוקסי.
        logging.info("Direct connection to %s failed (%s) — trying the proxy",
                     origin, e)
        resp = proxy.open(url, data, timeout)
        _remember_route(origin, "proxy")
        return resp


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
