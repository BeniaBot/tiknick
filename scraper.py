# -*- coding: utf-8 -*-
"""
scraper.py — סורק פורומי NodeBB עבור Tik-Nick.

מושך את רשימת המשתמשים המלאה של פורום NodeBB דרך ה-Read API הרשמי
(/api/users, עם עימוד), ממפה כל משתמש לשדות של Tik-Nick, וממזג למאגר
לפי מדיניות ההתנגשויות (מילוי שקט לשדות ריקים, רישום התנגשות לשדה קיים שונה).

עקרונות:
  • "מנומס" — השהיה בין בקשות, כיבוד Retry-After, User-Agent מזוהה.
  • ניתן לביטול באמצע (cancel_flag).
  • דיווח התקדמות דרך callback, כדי שהממשק יראה מד התקדמות חי.
  • שולף רק מידע ציבורי שה-API מחזיר (טלפון/מייל בד"כ מוסתרים ב-NodeBB).
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error

USER_AGENT = "Tik-Nick/1.0 (+https://github.com/BeniaBot/tiknick)"
PAGE_DELAY_SEC = 0.6          # השהיה בין עמודים — לא להעמיס על השרת
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3


class ScrapeError(Exception):
    pass


def _api_base(forum_url):
    """הופך URL של פורום ל-base של ה-API (מוסיף /api, מנקה סלאש כפול)"""
    url = (forum_url or "").strip().rstrip("/")
    if not url:
        raise ScrapeError("כתובת פורום ריקה")
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _fetch_json(url, cookie=None):
    """בקשת GET אחת שמחזירה JSON, עם ניסיונות חוזרים וכיבוד Retry-After.
    cookie — מחרוזת עוגייה אופציונלית (למשל 'express.sid=...') לפורומים
    שדורשים התחברות כדי לצפות ברשימת המשתמשים."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limited
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after and retry_after.isdigit()) else attempt * 5
                time.sleep(min(wait, 30))
                last_err = ScrapeError("הפורום מגביל קצב בקשות (429) — האטתי")
                continue
            if e.code in (403, 401):
                raise ScrapeError("אין הרשאה לצפות במשתמשים בפורום זה (ייתכן שנדרשת התחברות)")
            if e.code == 404:
                raise ScrapeError("נתיב ה-API לא נמצא — ייתכן שאין תמיכת API בפורום זה")
            last_err = ScrapeError(f"שגיאת שרת {e.code}")
            time.sleep(attempt * 2)
        except urllib.error.URLError as e:
            last_err = ScrapeError(f"בעיית רשת: {e.reason}")
            time.sleep(attempt * 2)
        except json.JSONDecodeError:
            raise ScrapeError("התקבלה תשובה שאינה JSON — ככל הנראה אין API בכתובת זו")
    raise last_err or ScrapeError("הבקשה נכשלה")


def scrape_single_user(forum_url, username, cookie=None):
    """
    שולף משתמש בודד מ-NodeBB לפי שם משתמש (endpoint /api/user/{username}).
    מחזיר dict של שדות ממופים, או None אם לא נמצא.
    """
    try:
        base = _api_base(forum_url)
        # NodeBB: /api/user/{userslug} — נסה גם slug וגם username
        import urllib.parse
        slug = urllib.parse.quote(username.lower().replace(" ", "-"))
        for path in (f"/api/user/{slug}", f"/api/user/username/{urllib.parse.quote(username)}"):
            try:
                data = _fetch_json(base + path, cookie=cookie)
                if isinstance(data, dict) and (data.get("uid") or data.get("username")):
                    return _map_user(data)
            except ScrapeError:
                continue
    except ScrapeError:
        return None
    return None


def check_forum(forum_url, cookie=None):
    """
    בדיקה מקדימה: מאמת שהכתובת היא פורום NodeBB עם API פעיל,
    ומחזיר כמה משתמשים בערך יש (אם ה-API חושף זאת).
    מחזיר dict: {"ok": bool, "user_count": int|None, "title": str|None, "error": str|None}
    """
    try:
        base = _api_base(forum_url)
        data = _fetch_json(base + "/api/users", cookie=cookie)
    except ScrapeError as e:
        msg = str(e)
        # זיהוי מקרה של דרישת התחברות
        if any(x in msg for x in ("401", "403", "not-authori", "login", "unauthor")):
            return {"ok": False, "user_count": None, "title": None,
                    "error": "הפורום דורש התחברות לצפייה במשתמשים — הזן עוגיית express.sid (ראה '🍪 איך משיגים?')"}
        return {"ok": False, "user_count": None, "title": None, "error": msg}

    # NodeBB מחזיר בד"כ מבנה עם users[] ולעיתים pagination/userCount
    if not isinstance(data, dict) or "users" not in data:
        # אולי זו דרישת התחברות שהוחזרה כ-JSON/HTML
        if isinstance(data, dict) and any(k in data for k in ("error", "status")):
            return {"ok": False, "user_count": None, "title": None,
                    "error": "הפורום דרש התחברות או שאין הרשאה — נסה עם עוגיית express.sid"}
        return {"ok": False, "user_count": None, "title": None,
                "error": "לא נראה שזה פורום NodeBB (אין רשימת משתמשים ב-API). ייתכן שהפורום בנוי על מערכת אחרת ולא ניתן לסריקה."}

    count = data.get("userCount")
    if count is None:
        pag = data.get("pagination") or {}
        # לפעמים אפשר להעריך לפי מספר עמודים * גודל עמוד
        pages = pag.get("pageCount")
        if pages:
            count = pages * max(1, len(data.get("users", [])))
    return {"ok": True, "user_count": count,
            "title": data.get("title") or None, "error": None}


def _map_user(u):
    """ממפה אובייקט משתמש של NodeBB לשדות של Tik-Nick (רק מה שקיים)."""
    def g(*keys):
        for k in keys:
            v = u.get(k)
            if v not in (None, "", 0):
                return v
        return ""

    groups = ""
    gl = u.get("groupTitleArray") or u.get("groups")
    if isinstance(gl, list):
        names = [x.get("name") if isinstance(x, dict) else str(x) for x in gl]
        groups = ", ".join([n for n in names if n])
    elif isinstance(gl, str):
        groups = gl

    join_ts = u.get("joindate") or u.get("joindateISO")
    join_date = ""
    if isinstance(join_ts, (int, float)):
        try:
            join_date = time.strftime("%Y-%m-%d", time.localtime(join_ts / 1000))
        except Exception:
            join_date = ""
    elif isinstance(join_ts, str):
        join_date = join_ts[:10]

    avatar = ""
    pic = u.get("picture") or u.get("uploadedpicture")
    if pic:
        avatar = pic

    # last online → תאריך
    last_ts = u.get("lastonline") or u.get("lastonlineISO")
    last_online = ""
    if isinstance(last_ts, (int, float)):
        try:
            last_online = time.strftime("%Y-%m-%d", time.localtime(last_ts / 1000))
        except Exception:
            last_online = ""
    elif isinstance(last_ts, str):
        last_online = last_ts[:10]

    # פרטים נוספים חופשיים — נאספים לשדה extra_info
    extra_bits = []
    loc = g("location")
    if loc:      extra_bits.append(f"מיקום: {loc}")
    web = g("website")
    if web:      extra_bits.append(f"אתר: {web}")
    about = g("aboutme")
    if about:    extra_bits.append(f"אודות: {about}")
    sig = g("signature")
    if sig:      extra_bits.append(f"חתימה: {sig}")
    pv = u.get("profileviews")
    if pv:       extra_bits.append(f"צפיות בפרופיל: {pv}")
    if last_online:
        extra_bits.append(f"נראה לאחרונה: {last_online}")
    extra_info = " · ".join(extra_bits)

    return {
        "full_name":    g("fullname"),
        "reputation":   g("reputation") or "",
        "post_count":   g("postcount") or "",
        "groups":       groups,
        "status":       "מורחק" if u.get("banned") else "",
        "join_date":    join_date,
        "avatar_url":   avatar,
        "nick_color":   g("icon:bgColor") or "",
        "email":        g("email"),   # כמעט תמיד ריק ב-NodeBB ציבורי
        "forum_uid":    (str(u.get("uid")) if u.get("uid") else ""),
        "extra_info":   extra_info,
    }


def scrape_forum(forum_name, forum_url, db, cookie=None,
                 progress_cb=None, cancel_flag=None, max_pages=None, skip_flag=None):
    """
    סורק את כל המשתמשים בפורום וממזג למאגר.

    forum_name  — שם הפורום כפי שיישמר בשדה forum של הניקים
    forum_url   — כתובת הבסיס של הפורום
    db          — מודול database (מוזרק, כדי לא ליצור תלות מעגלית)
    progress_cb — פונקציה(dict) לעדכון התקדמות: {page, total_pages, added, updated, conflicts, done}
    cancel_flag — אובייקט עם .is_set() (למשל threading.Event) לביטול
    max_pages   — הגבלת עמודים (לבדיקות); None = הכל

    מחזיר סיכום: {"added", "updated", "unchanged", "conflicts", "pages", "cancelled"}
    """
    base = _api_base(forum_url)
    stats = {"added": 0, "updated": 0, "unchanged": 0,
             "conflicts": 0, "pages": 0, "cancelled": False}

    # עמוד ראשון — כדי לדעת כמה עמודים יש
    first = _fetch_json(base + "/api/users", cookie=cookie)
    if not isinstance(first, dict) or "users" not in first:
        raise ScrapeError("מבנה תשובה לא צפוי — ודא שזה פורום NodeBB")

    pagination = first.get("pagination") or {}
    total_pages = pagination.get("pageCount") or 1
    if max_pages:
        total_pages = min(total_pages, max_pages)

    def handle_users(users):
        for u in users:
            uname = (u.get("username") or "").strip()
            if not uname:
                continue
            mapped = _map_user(u)
            action, _nid, conf = db.merge_scraped_nick(
                forum_name, uname, mapped, source_label=f"NodeBB:{forum_name}")
            key = "added" if action == "created" else action
            stats[key] = stats.get(key, 0) + 1
            stats["conflicts"] += conf

    handle_users(first.get("users", []))
    stats["pages"] = 1
    if progress_cb:
        progress_cb({"page": 1, "total_pages": total_pages, **stats, "done": False})

    for page in range(2, total_pages + 1):
        if cancel_flag is not None and cancel_flag.is_set():
            stats["cancelled"] = True
            break
        if skip_flag is not None and skip_flag.is_set():
            stats["skipped"] = True
            break
        time.sleep(PAGE_DELAY_SEC)
        try:
            data = _fetch_json(base + f"/api/users?page={page}", cookie=cookie)
        except ScrapeError:
            # עמוד בודד נכשל — ממשיכים הלאה במקום לקרוס
            continue
        handle_users(data.get("users", []) if isinstance(data, dict) else [])
        stats["pages"] = page
        if progress_cb:
            progress_cb({"page": page, "total_pages": total_pages, **stats, "done": False})

    if progress_cb:
        progress_cb({"page": stats["pages"], "total_pages": total_pages, **stats, "done": True})
    return stats
