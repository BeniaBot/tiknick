# -*- coding: utf-8 -*-
"""
התחברות לפורום מתוך התוכנה — במקום לחפש עוגייה בדפדפן.

בנימין: *"שיהיה יותר קל (מונחה אוטומטי) להביא עוגיות"*. עד 0.9.6 הדרך
המומלצת הייתה: להתקין תוסף לכרום, להתחבר לפורום, לייצא קובץ, למצוא בו
שורה בשם express.sid ולהעתיק את הערך שאחריה. שש פעולות, ושלוש מהן במקומות
שהמשתמש הזה לא ביקר בהם מעולם.

עכשיו: כפתור אחד פותח חלון של הפורום **בתוך התוכנה**, המשתמש מתחבר כרגיל,
והתוכנה מזהה שההתחברות הצליחה, לוקחת את עוגיית ההתחברות וסוגרת את החלון.

**מה התוכנה לא עושה**: היא לא קוראת את שדה הסיסמה, לא שומרת אותו ולא
ממלאת אותו. הסיסמה מוקלדת באתר של הפורום עצמו. נשמרת רק עוגיית
ההתחברות — בדיוק מה שהמשתמש היה מדביק ידנית — לפי origin, כמו מאז 0.8.2.

**חלון ההתחברות אינו מקבל את ה-API של התוכנה** (`js_api` נמסר לחלון הראשי
בלבד), כך שדף של פורום אינו יכול לקרוא לפונקציות של Tik-Nick.

המודול הזה הוא ההיגיון בלבד (איזה דף, איזו עוגייה, איך יודעים שהתחברנו),
בלי pywebview — כדי שאפשר יהיה לבדוק אותו בלי חלון. החיווט ב-main.py.
"""
from urllib.parse import urlsplit

TIMEOUT_SEC = 15 * 60
POLL_SEC = 1.2

LOGIN_PATHS = {"nodebb": "/login", "discourse": "/login", "xenforo": "/login/"}

# העוגיות שמזהות את ההתחברות, לפי סדר חשיבות. הראשונה היא זו שחובה.
SESSION_COOKIES = {
    "nodebb": ("express.sid",),
    "discourse": ("_t", "_forum_session"),
    # xf_user קיימת רק כשמסמנים "השאר אותי מחובר"; xf_session תמיד.
    "xenforo": ("xf_user", "xf_session"),
}

# איך יודעים שהמשתמש **מחובר** ולא רק שיש עוגייה: ב-NodeBB עוגיית
# express.sid ניתנת גם לאורח, ולכן שואלים את הדף עצמו.
CHECK_JS = {
    "nodebb": "(function(){try{return (window.app&&app.user&&Number(app.user.uid))||0}"
              "catch(e){return 0}})()",
    "xenforo": "(document.documentElement.getAttribute('data-logged-in')==='true')?1:0",
    # ב-Discourse עוגיית _t נוצרת רק בהתחברות — היא עצמה ההוכחה
    "discourse": None,
}


def supported(platform):
    return platform in LOGIN_PATHS


def login_url(forum_url, platform):
    """
    כתובת דף ההתחברות. **הנתיב נשמר** — פורום שיושב בתת-תיקייה (כמו
    `…/techoclick`) מתחבר דרך `…/techoclick/login`, ולא דרך שורש הדומיין.
    """
    u = (forum_url or "").strip()
    if u and not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    parts = urlsplit(u)
    if not parts.netloc:
        return ""
    path = (parts.path or "").rstrip("/")
    return "%s://%s%s%s" % (parts.scheme or "https", parts.netloc, path, LOGIN_PATHS[platform])


def _host_matches(domain, host):
    d = (domain or "").lstrip(".").lower()
    h = (host or "").lower()
    return not d or h == d or h.endswith("." + d)


def _morsels(cookies):
    """
    pywebview מחזיר רשימה של SimpleCookie. **SimpleCookie יורש מ-dict** —
    ולכן הבדיקה עליו חייבת לבוא לפני הבדיקה על dict רגיל. בסדר ההפוך כל
    עוגייה אמיתית נפלה לענף של ה-dict, לא נמצא בה "name", וההתחברות לא
    הייתה מצליחה לעולם (נתפס בבדיקה, לפני שהגיע לחלון אמיתי).
    """
    from http.cookies import BaseCookie
    for c in cookies or []:
        if isinstance(c, BaseCookie):
            for name, m in c.items():
                yield name, m.value, m.get("domain") or ""
            continue
        if isinstance(c, dict):
            if c.get("name"):
                yield c.get("name"), c.get("value") or "", c.get("domain") or ""
            continue
        try:
            for name, m in c.items():
                yield name, m.value, m.get("domain") or ""
        except Exception:
            continue


def pick_cookie(cookies, platform, host):
    """
    מחרוזת "שם=ערך; שם=ערך" מהעוגיות של הפורום בלבד. עוגייה בשם זהה
    מדומיין אחר (למשל אחרי מעבר דרך שירות התחברות חיצוני) אינה נלקחת.
    """
    want = SESSION_COOKIES.get(platform, ())
    got = {}
    for name, value, domain in _morsels(cookies):
        if name in want and value and _host_matches(domain, host) and name not in got:
            got[name] = value
    return "; ".join("%s=%s" % (n, got[n]) for n in want if n in got)


def logged_in(platform, js_result, cookie_str):
    ck = cookie_str or ""
    if platform == "nodebb":
        try:
            return int(js_result or 0) > 0 and "express.sid=" in ck
        except (TypeError, ValueError):
            return False
    if platform == "discourse":
        return "_t=" in ck
    if platform == "xenforo":
        return bool(js_result) and ("xf_user=" in ck or "xf_session=" in ck)
    return False
