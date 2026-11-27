# -*- coding: utf-8 -*-
"""
מאגר הדוחות — כל דוח שהופק נשמר, ואפשר לפתוח אותו שוב.

בנימין: *"ושיוכלו לפתוח את הדוחות האחרונים — גם יותר מאשר הדוח האחרון.
ושבשם הקובץ (גם בשטינקניק) יהיה שם הניק"*.

עד 0.9.6 הדוח חי בזיכרון של החלון (`_lastReport`) ונעלם בסגירת התוכנה.
חזונישניק גם כתב עותק ל-`chazonishnik_<שם>.html` ליד המאגר — אבל דרס אותו
בכל ניתוח של אותו משתמש, לא ציין פורום, ושום מסך לא הראה שהוא קיים.

**המבנה**: תיקייה אחת, קובץ HTML לכל דוח, ושם קובץ שאדם קורא:
`חזונישניק - <ניק> - <פורום> - 2026-11-27 14.05.html`. המטא-דאטה (כלי, ניק,
פורום, תאריך, כמה פוסטים) יושבת **בתוך הקובץ**, בהערה מיד אחרי ה-DOCTYPE —
בלי קובץ אינדקס שיכול להשתבש או לסטות ממה שבאמת בתיקייה. קובץ שהמשתמש
מחק בסייר פשוט נעלם מהרשימה.

**תקרה**: התיקייה יושבת ב-%APPDATA% על C:, ודוח של חזונישניק עם Chart.js
המוטמע שוקל 1–2MB. נשמרים 40 האחרונים ועד 250MB.

**ביטחון**: הממשק מעביר שם קובץ, ולכן כל פעולה מקבלת **שם בלבד** — בלי
נתיב, רק סיומת `.html`, ורק קובץ שבאמת יושב בתיקייה. כך אי אפשר לבקש דרך
הגשר לקרוא או למחוק קובץ אחר במחשב.
"""
import io
import json
import logging
import os
import re
import time
from datetime import datetime

KEEP = 40
MAX_BYTES = 250 * 1024 * 1024
_HEAD = 4096                      # המטא-דאטה נקראת מתחילת הקובץ בלבד

TOOLS = {
    "chz": "חזונישניק",
    "cmp": "השוואה",
    "stink": "שטינקניק",
}
_META_RX = re.compile(r"<!--tiknick-report (\{.*?\})-->")
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def reports_dir(data_dir):
    d = os.path.join(data_dir, "reports")
    os.makedirs(d, exist_ok=True)
    return d


def _clean(s, limit=60):
    """שם שמגיע מהפורום הופך לחלק משם קובץ: בלי תווים אסורים ב-Windows,
    בלי נקודה או רווח בסוף (Windows קוטע אותם בשקט), ובאורך סביר."""
    s = _BAD_CHARS.sub("", str(s or "")).strip()
    s = re.sub(r"\s+", " ", s)[:limit].rstrip(" .")
    return s or "ללא שם"


def _host(url):
    u = (url or "").strip()
    u = re.sub(r"^[a-z]+://", "", u, flags=re.I)
    return u.split("/")[0].lower() or ""


def _meta_comment(meta):
    # בתוך הערת HTML אסור "--". ‏ensure_ascii + בריחת המקף כ-- נותנים
    # JSON תקין שלא יכול לסגור את ההערה, גם כשבשם הניק יש מקפים.
    j = json.dumps(meta, ensure_ascii=True).replace("-", "\\u002d")
    return "<!--tiknick-report " + j + "-->"


def _with_meta(html, meta):
    """ההערה נכנסת **אחרי** ה-DOCTYPE: הערה לפניו מעבירה את הדפדפן למצב
    quirks, והדוח היה מצויר אחרת מהגרסה שנפתחה מיד אחרי הניתוח."""
    c = _meta_comment(meta)
    m = re.match(r"\s*<!DOCTYPE[^>]*>", html or "", re.I)
    if m:
        return html[:m.end()] + "\n" + c + html[m.end():]
    return c + "\n" + (html or "")


def file_name(tool, nick, forum_url, when=None):
    when = when or datetime.now()
    parts = [TOOLS.get(tool, "דוח"), _clean(nick)]
    host = _host(forum_url)
    if host:
        parts.append(_clean(host, 40))
    parts.append(when.strftime("%Y-%m-%d %H.%M"))
    return " - ".join(parts) + ".html"


def save(data_dir, tool, nick, forum_url, html, extra=None):
    """שומר דוח ומחזיר את שם הקובץ. כשל לעולם אינו מפיל את הניתוח — הדוח
    עדיין מוצג למשתמש, הוא פשוט לא יופיע בהיסטוריה."""
    if not html:
        return ""
    try:
        d = reports_dir(data_dir)
        now = datetime.now()
        name = file_name(tool, nick, forum_url, now)
        base, n = name[:-5], 2
        while os.path.exists(os.path.join(d, name)):      # שני דוחות באותה דקה
            name = "%s (%d).html" % (base, n)
            n += 1
        meta = {"tool": tool, "nick": str(nick or ""), "forum": _host(forum_url),
                "url": str(forum_url or ""), "created": now.strftime("%Y-%m-%dT%H:%M:%S")}
        for k, v in (extra or {}).items():
            if isinstance(v, (int, float, bool, str)) or v is None:
                meta[k] = v
        tmp = os.path.join(d, name + ".part")
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(_with_meta(html, meta))
        os.replace(tmp, os.path.join(d, name))
        prune(data_dir)
        return name
    except Exception:
        logging.exception("report_store.save failed")
        return ""


def _read_meta(path):
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            head = f.read(_HEAD)
        m = _META_RX.search(head)
        if m:
            return json.loads(m.group(1))
    except Exception:
        pass
    return None


def list_reports(data_dir):
    d = reports_dir(data_dir)
    out = []
    for fn in os.listdir(d):
        if not fn.lower().endswith(".html"):
            continue
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        meta = _read_meta(p) or {}
        out.append({
            "name": fn,
            "tool": meta.get("tool") or "",
            "nick": meta.get("nick") or "",
            "nick_b": meta.get("nick_b") or "",
            "forum": meta.get("forum") or "",
            "created": meta.get("created")
                or datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S"),
            "posts": meta.get("posts"),
            "partial": bool(meta.get("partial")),
            "size": st.st_size,
            "_mtime": st.st_mtime,
        })
    out.sort(key=lambda r: (r["created"], r["_mtime"]), reverse=True)
    for r in out:
        r.pop("_mtime", None)
    return out


def _safe_path(data_dir, name):
    """שם בלבד, בתוך תיקיית הדוחות בלבד. כל דבר אחר — None."""
    if not isinstance(name, str) or not name or name != os.path.basename(name):
        return None
    if not name.lower().endswith(".html") or name.startswith("."):
        return None
    d = os.path.realpath(reports_dir(data_dir))
    p = os.path.realpath(os.path.join(d, name))
    if os.path.dirname(p) != d or not os.path.isfile(p):
        return None
    return p


def read(data_dir, name):
    p = _safe_path(data_dir, name)
    if not p:
        return None
    with io.open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def path_of(data_dir, name):
    return _safe_path(data_dir, name)


_TRASH = "_deleted"
TRASH_KEEP_SEC = 3600


def _trash_dir(data_dir):
    t = os.path.join(reports_dir(data_dir), _TRASH)
    os.makedirs(t, exist_ok=True)
    return t


def delete(data_dir, name):
    """
    מחיקה **הפיכה**: הקובץ עובר לתת-תיקייה, וההודעה בממשק מציעה "↩ בטל".
    (כלל הממשק לקהל הזה: פעולה הרסנית לא נעשית בלי ביטול בתוך ההודעה.)
    מה שבתת-התיקייה נמחק לגמרי אחרי שעה, ב-prune הבא.
    """
    p = _safe_path(data_dir, name)
    if not p:
        return False
    dst = os.path.join(_trash_dir(data_dir), name)
    if os.path.exists(dst):
        os.remove(dst)
    os.replace(p, dst)
    os.utime(dst, None)            # השעה נספרת מרגע המחיקה
    return True


def undelete(data_dir, name):
    if not isinstance(name, str) or not name or name != os.path.basename(name):
        return False
    if not name.lower().endswith(".html") or name.startswith("."):
        return False
    src = os.path.join(_trash_dir(data_dir), name)
    dst = os.path.join(reports_dir(data_dir), name)
    if not os.path.isfile(src) or os.path.exists(dst):
        return False
    os.replace(src, dst)
    return True


def prune(data_dir, keep=KEEP, max_bytes=MAX_BYTES):
    """הישנים יוצאים קודם. מיון לפי זמן השינוי ואז לפי שם — שני דוחות
    באותה שנייה חייבים סדר יציב (אותו לקח מהגיבוי האוטומטי)."""
    d = reports_dir(data_dir)
    files = []
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if fn.lower().endswith(".part"):
            # שארית של כתיבה שנקטעה, ישנה משעה — אינה דוח
            try:
                if time.time() - os.path.getmtime(p) > 3600:
                    os.remove(p)
            except OSError:
                pass
            continue
        if fn.lower().endswith(".html"):
            try:
                st = os.stat(p)
                files.append((st.st_mtime, fn, st.st_size, p))
            except OSError:
                pass
    try:
        t = _trash_dir(data_dir)
        for fn in os.listdir(t):
            p = os.path.join(t, fn)
            if time.time() - os.path.getmtime(p) > TRASH_KEEP_SEC:
                os.remove(p)
    except OSError:
        pass
    files.sort(key=lambda t: (t[0], t[1]), reverse=True)
    total, removed = 0, 0
    for i, (_, _, size, p) in enumerate(files):
        total += size
        if i >= keep or total > max_bytes:
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
    return removed


_LEGACY_RX = re.compile(r"^(chazonishnik|stinknik)_(.+)\.html$", re.I)


def adopt_legacy(data_dir):
    """
    עד 0.9.6 חזונישניק כתב `chazonishnik_<שם>.html` ליד המאגר, ואיש לא ידע.
    אלה דוחות אמיתיים של המשתמש — הם עוברים לתיקיית הדוחות, עם הניק מתוך שם
    הקובץ ותאריך השינוי שלו, ומופיעים ברשימה. חד-פעמי מטבעו: אחרי ההעברה
    אין יותר קבצים כאלה ליד המאגר.
    """
    moved = 0
    try:
        names = os.listdir(data_dir)
    except OSError:
        return 0
    for fn in names:
        m = _LEGACY_RX.match(fn)
        if not m:
            continue
        src = os.path.join(data_dir, fn)
        try:
            with io.open(src, encoding="utf-8", errors="replace") as f:
                html = f.read()
            when = datetime.fromtimestamp(os.path.getmtime(src))
            tool = "chz" if m.group(1).lower() == "chazonishnik" else "stink"
            d = reports_dir(data_dir)
            name = file_name(tool, m.group(2), "", when)
            base, n = name[:-5], 2
            while os.path.exists(os.path.join(d, name)):
                name = "%s (%d).html" % (base, n)
                n += 1
            meta = {"tool": tool, "nick": m.group(2), "forum": "", "url": "",
                    "created": when.strftime("%Y-%m-%dT%H:%M:%S"), "legacy": True}
            with io.open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(_with_meta(html, meta))
            os.utime(os.path.join(d, name), (when.timestamp(), when.timestamp()))
            os.remove(src)
            moved += 1
        except Exception:
            logging.exception("adopting legacy report %s failed", fn)
    return moved
