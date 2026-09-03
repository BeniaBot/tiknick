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


class AuthRequired(ScrapeError):
    """הפורום החזיר 401/403 — נדרשת עוגיית התחברות."""
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
                raise AuthRequired("אין הרשאה לצפות במשתמשים בפורום זה (ייתכן שנדרשת התחברות)")
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


def scrape_single_user(forum_url, username, cookie=None, platform=None):
    """
    שולף משתמש בודד לפי שם משתמש (NodeBB או Discourse). מחזיר dict ממופה או None.
    """
    try:
        base = _api_base(forum_url)
    except ScrapeError:
        return None
    plat = platform or detect_platform(forum_url, cookie)
    if plat == "discourse":
        try:
            data = _fetch_json(base + f"/u/{urllib.parse.quote(username)}.json", cookie=cookie)
            u = (data.get("user") if isinstance(data, dict) else None) or {}
            if u.get("username") or u.get("id"):
                return _map_discourse_user(u, base)
        except ScrapeError:
            return None
        return None
    # NodeBB (ברירת מחדל)
    slug = urllib.parse.quote(username.lower().replace(" ", "-"))
    endpoints = [f"/api/user/{slug}", f"/api/user/username/{urllib.parse.quote(username)}"]
    for path in endpoints:
        try:
            data = _fetch_json(base + path, cookie=cookie)
            if isinstance(data, dict) and (data.get("uid") or data.get("username")):
                return _map_user(data)
        except ScrapeError:
            continue
    return None


def _try_nodebb(base, cookie):
    """מחזיר (ok, user_count, title) אם זה NodeBB עם רשימת משתמשים, אחרת None. מרים AuthRequired."""
    data = _fetch_json(base + "/api/users", cookie=cookie)
    if not isinstance(data, dict) or "users" not in data:
        return None
    count = data.get("userCount")
    if count is None:
        pag = data.get("pagination") or {}
        pages = pag.get("pageCount")
        if pages:
            count = pages * max(1, len(data.get("users", [])))
    return (True, count, data.get("title") or None)


def _try_discourse(base, cookie):
    """מחזיר (ok, user_count, title) אם זה Discourse עם ספריית משתמשים, אחרת None."""
    data = _fetch_json(base + "/directory_items.json?period=all&order=post_count&page=0",
                       cookie=cookie)
    if not isinstance(data, dict) or "directory_items" not in data:
        return None
    return (True, data.get("total_rows_directory_items"), None)


def detect_platform(forum_url, cookie=None):
    """מזהה את פלטפורמת הפורום: 'nodebb' | 'discourse' | 'unknown'."""
    base = _api_base(forum_url)
    nodebb_auth = False   # /api/users החזיר 401/403 — סימן ל-NodeBB שדורש התחברות
    try:
        if _try_nodebb(base, cookie):
            return "nodebb"
    except AuthRequired:
        nodebb_auth = True   # לא מסיקים מיד — קודם בודקים אם זה בכלל Discourse
    except ScrapeError:
        pass
    try:
        if _try_discourse(base, cookie):
            return "discourse"
    except AuthRequired:
        return "discourse"
    except ScrapeError:
        pass
    # אם רק ה-NodeBB probe נחסם בהרשאה — סביר שזה NodeBB מאחורי התחברות
    return "nodebb" if nodebb_auth else "unknown"


def check_forum(forum_url, cookie=None):
    """
    בדיקה מקדימה: מזהה את פלטפורמת הפורום (NodeBB/Discourse) ואם יש API פעיל
    לרשימת משתמשים, ומחזיר הערכת מספר המשתמשים.
    מחזיר dict: {"ok", "user_count", "title", "platform", "error"}
    """
    try:
        base = _api_base(forum_url)
    except ScrapeError as e:
        return {"ok": False, "user_count": None, "title": None, "platform": "unknown", "error": str(e)}

    # NodeBB
    try:
        res = _try_nodebb(base, cookie)
        if res:
            ok, count, title = res
            return {"ok": True, "user_count": count, "title": title,
                    "platform": "nodebb", "error": None}
    except AuthRequired:
        return {"ok": False, "user_count": None, "title": None, "platform": "nodebb",
                "error": "הפורום דורש התחברות לצפייה במשתמשים — הזן עוגיית express.sid (ראה '🍪 איך משיגים?')"}
    except ScrapeError:
        pass

    # Discourse
    try:
        res = _try_discourse(base, cookie)
        if res:
            ok, count, title = res
            return {"ok": True, "user_count": count, "title": title,
                    "platform": "discourse", "error": None}
    except AuthRequired:
        return {"ok": False, "user_count": None, "title": None, "platform": "discourse",
                "error": "הפורום דורש התחברות לצפייה במשתמשים — הזן עוגייה מתאימה"}
    except ScrapeError:
        pass

    return {"ok": False, "user_count": None, "title": None, "platform": "unknown",
            "error": "לא זוהתה מערכת פורום נתמכת (NodeBB/Discourse) עם רשימת משתמשים ציבורית בכתובת זו."}


def _num_str(v):
    """מספר → מחרוזת, כולל 0. (g() מתייחס ל-0 כחסר, ולכן ירידת מוניטין ל-0
    או ספירת הודעות 0 לא הייתה מתעדכנת לעולם.)"""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        return str(int(v))
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return str(int(v.strip()))
    return ""


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
    # תקרות אורך — "אודות"/חתימה יכולים להיות בלוב ענק, והוא היה נשמר בשלמותו
    # בטבלה, במקורות ובאינדקס החיפוש
    about = g("aboutme")
    if about:    extra_bits.append(f"אודות: {str(about)[:300]}")
    sig = g("signature")
    if sig:      extra_bits.append(f"חתימה: {str(sig)[:300]}")
    pv = u.get("profileviews")
    if pv:       extra_bits.append(f"צפיות בפרופיל: {pv}")
    if last_online:
        extra_bits.append(f"נראה לאחרונה: {last_online}")
    extra_info = (" · ".join(extra_bits))[:2000]

    return {
        "full_name":    g("fullname"),
        "reputation":   _num_str(u.get("reputation")),
        "post_count":   _num_str(u.get("postcount")),
        "groups":       groups,
        "status":       "מורחק" if u.get("banned") else "",
        "join_date":    join_date,
        "last_seen":    last_online,
        "avatar_url":   avatar,
        "nick_color":   g("icon:bgColor") or "",
        "email":        g("email"),   # כמעט תמיד ריק ב-NodeBB ציבורי
        "forum_uid":    (str(u.get("uid")) if u.get("uid") else ""),
        "extra_info":   extra_info,
    }


def _map_discourse_user(u, base):
    """ממפה משתמש Discourse (מ-/u/{name}.json או מספריית המשתמשים) לשדות Tik-Nick."""
    avatar = ""
    tmpl = u.get("avatar_template") or ""
    if tmpl:
        pic = tmpl.replace("{size}", "120")
        avatar = (base + pic) if pic.startswith("/") else pic

    join_date = ""
    created = u.get("created_at") or ""
    if isinstance(created, str) and len(created) >= 10:
        join_date = created[:10]
    last_seen = ""
    seen = u.get("last_seen_at") or u.get("last_posted_at") or ""
    if isinstance(seen, str) and len(seen) >= 10:
        last_seen = seen[:10]

    extra_bits = []
    loc = u.get("location")
    if loc:      extra_bits.append(f"מיקום: {loc}")
    web = u.get("website_name") or u.get("website")
    if web:      extra_bits.append(f"אתר: {web}")
    bio = (u.get("bio_raw") or "").strip()
    if bio:      extra_bits.append(f"אודות: {bio[:200]}")

    grp = ""
    groups = u.get("groups")
    if isinstance(groups, list):
        names = [g.get("name") for g in groups if isinstance(g, dict) and g.get("name")
                 and not str(g.get("name")).startswith("trust_level_")]
        grp = ", ".join(names)

    return {
        "full_name":   u.get("name") or "",
        "reputation":  str(u.get("likes_received", "") or ""),
        "post_count":  str(u.get("post_count", "") or ""),
        "groups":      grp,
        "status":      "מורחק" if (u.get("suspended_till") or u.get("silenced")) else "",
        "join_date":   join_date,
        "last_seen":   last_seen,
        "avatar_url":  avatar,
        "email":       u.get("email") or "",
        "forum_uid":   str(u.get("id") or ""),
        "extra_info":  " · ".join(extra_bits),
    }


def _map_discourse_dir_item(item, base):
    """ממפה פריט מספריית המשתמשים של Discourse (directory_items)."""
    u = item.get("user") or {}
    mapped = _map_discourse_user(u, base)
    # ספריית המשתמשים כוללת סטטיסטיקות עשירות יותר מאשר אובייקט המשתמש הבסיסי
    if item.get("likes_received") is not None:
        mapped["reputation"] = str(item.get("likes_received") or "")
    if item.get("post_count") is not None:
        mapped["post_count"] = str(item.get("post_count") or "")
    return mapped


def scrape_forum(forum_name, forum_url, db, cookie=None, progress_cb=None,
                 cancel_flag=None, max_pages=None, skip_flag=None, platform=None, run_id=None):
    """
    סורק את כל המשתמשים בפורום וממזג למאגר. מנתב לפי פלטפורמה (NodeBB/Discourse).

    platform    — 'nodebb' | 'discourse' | None (זיהוי אוטומטי)
    max_pages   — הגבלת עמודים (None = הכל)
    מחזיר סיכום: {"added","updated","unchanged","pages","cancelled"}
    """
    base = _api_base(forum_url)
    plat = platform or detect_platform(forum_url, cookie)
    if plat == "nodebb":
        return _scrape_nodebb(forum_name, base, db, cookie, progress_cb,
                              cancel_flag, max_pages, skip_flag, run_id)
    if plat == "discourse":
        return _scrape_discourse(forum_name, base, db, cookie, progress_cb,
                                 cancel_flag, max_pages, skip_flag, run_id)
    # xenforo/phpbb/custom/unknown — אין API ציבורי לרשימת משתמשים
    names = {"xenforo": "XenForo", "phpbb": "phpBB", "custom": "מערכת ייחודית"}
    label = names.get(plat, "")
    raise ScrapeError(
        (f"פלטפורמת הפורום ({label}) אינה תומכת בסריקה אוטומטית של רשימת המשתמשים."
         if label else
         "לא זוהתה מערכת פורום נתמכת (NodeBB/Discourse) בכתובת זו.")
        + " עדיין אפשר להוסיף ולנהל ניקים ידנית ולפתוח פרופילים.")


def _scrape_nodebb(forum_name, base, db, cookie, progress_cb,
                   cancel_flag, max_pages, skip_flag, run_id=None):
    stats = {"added": 0, "updated": 0, "unchanged": 0, "pages": 0, "cancelled": False}

    first = _fetch_json(base + "/api/users", cookie=cookie)
    if not isinstance(first, dict) or "users" not in first:
        raise ScrapeError("מבנה תשובה לא צפוי — ודא שזה פורום NodeBB")

    pagination = first.get("pagination") or {}
    total_pages = pagination.get("pageCount") or 1
    if max_pages:
        total_pages = min(total_pages, max_pages)

    def handle_users(users):
        # ממפים את כל העמוד ואז ממזגים בטרנזקציית DB אחת — מהיר בסדרי גודל
        pairs = [((u.get("username") or "").strip(), _map_user(u))
                 for u in users if (u.get("username") or "").strip()]
        if not pairs:
            return
        page_stats = db.merge_scraped_users(
            forum_name, pairs, source_label=f"NodeBB:{forum_name}", run_id=run_id)
        for key in ("added", "updated", "unchanged"):
            stats[key] += page_stats.get(key, 0)

    handle_users(first.get("users", []))
    stats["pages"] = 1
    if progress_cb:
        progress_cb({"page": 1, "total_pages": total_pages, **stats, "done": False})

    consecutive_fail = 0
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
            consecutive_fail = 0
        except ScrapeError:
            # עמוד שנכשל נספר ומדווח — אחרת סריקה חלקית נראית כמוצלחת
            stats["failed_pages"] = stats.get("failed_pages", 0) + 1
            consecutive_fail += 1
            if consecutive_fail >= 5:
                stats["aborted"] = True   # הפורום כנראה נפל — אין טעם להמשיך
                break
            if progress_cb:
                progress_cb({"page": page, "total_pages": total_pages, **stats, "done": False})
            continue
        handle_users(data.get("users", []) if isinstance(data, dict) else [])
        stats["pages"] = page
        if progress_cb:
            progress_cb({"page": page, "total_pages": total_pages, **stats, "done": False})

    if progress_cb:
        progress_cb({"page": stats["pages"], "total_pages": total_pages, **stats, "done": True})
    return stats


def _scrape_discourse(forum_name, base, db, cookie, progress_cb,
                      cancel_flag, max_pages, skip_flag, run_id=None):
    """סורק את ספריית המשתמשים של Discourse (directory_items, עימוד 0-בסיס)."""
    stats = {"added": 0, "updated": 0, "unchanged": 0, "pages": 0, "cancelled": False}

    # עמוד ראשון כדי להעריך מספר עמודים
    first = _fetch_json(
        base + "/directory_items.json?period=all&order=post_count&page=0", cookie=cookie)
    if not isinstance(first, dict) or "directory_items" not in first:
        raise ScrapeError("מבנה תשובה לא צפוי — ודא שזה פורום Discourse")

    items0 = first.get("directory_items", [])
    per_page = max(1, len(items0))
    total_rows = first.get("total_rows_directory_items") or 0
    total_pages = max(1, -(-total_rows // per_page)) if total_rows else 1
    if max_pages:
        total_pages = min(total_pages, max_pages)

    def handle_items(items):
        pairs = [((it.get("user") or {}).get("username", "").strip(),
                  _map_discourse_dir_item(it, base))
                 for it in items if (it.get("user") or {}).get("username")]
        pairs = [(u, m) for u, m in pairs if u]
        if not pairs:
            return
        page_stats = db.merge_scraped_users(
            forum_name, pairs, source_label=f"Discourse:{forum_name}", run_id=run_id)
        for key in ("added", "updated", "unchanged"):
            stats[key] += page_stats.get(key, 0)

    handle_items(items0)
    stats["pages"] = 1
    if progress_cb:
        progress_cb({"page": 1, "total_pages": total_pages, **stats, "done": False})

    # עימוד 0-בסיס; ממשיכים עד עמוד ריק (total_pages משמש רק להערכת ההתקדמות)
    page = 1
    while items0:
        if max_pages and page >= max_pages:
            break
        if cancel_flag is not None and cancel_flag.is_set():
            stats["cancelled"] = True
            break
        if skip_flag is not None and skip_flag.is_set():
            stats["skipped"] = True
            break
        time.sleep(PAGE_DELAY_SEC)
        try:
            data = _fetch_json(
                base + f"/directory_items.json?period=all&order=post_count&page={page}",
                cookie=cookie)
        except ScrapeError:
            # כשל רשת — עוצרים (אין total_pages אמין) ומדווחים שהסריקה חלקית
            stats["failed_pages"] = stats.get("failed_pages", 0) + 1
            stats["aborted"] = True
            break
        items = data.get("directory_items", []) if isinstance(data, dict) else []
        if not items:
            break
        handle_items(items)
        page += 1
        stats["pages"] = page
        if progress_cb:
            progress_cb({"page": page, "total_pages": max(total_pages, page),
                         **stats, "done": False})

    if progress_cb:
        progress_cb({"page": stats["pages"], "total_pages": max(total_pages, stats["pages"]),
                     **stats, "done": True})
    return stats
