# -*- coding: utf-8 -*-
"""
Forumstats — מי היה כאן ראשון.

חזונישניק ושטינקניק מסתכלים על **אדם**. זה מסתכל על **מקום**: מי נרשם ראשון
לפורום, מתי הוא נפתח, מה גדל בו, ומה הנושאים שהכי הרבה אנשים ראו.

הבקשה של בנימין הייתה רחבה יותר — "מי המשתמש הראשון והשני והלאה, מה הפוסט
הראשון, מה הפוסט הכי פופולארי, מה הפוסט הכי הרבה דיסים". **שניים מהם אינם
ניתנים למענה מה-API הציבורי, והדוח אומר את זה במפורש במקום לנחש** (ראו
`_LIMITS` למטה). זה הלקח מכרטיס "עם מי הוא מדבר" שנמשך מ-0.9: פיקסצ'רים
שעוברים אינם הוכחה, וכרטיס שאי אפשר לאמת מול פורום אמיתי לא נשלח.

מה שכן — נבדק חי מול mitmachim.top (31,034 משתמשים) ומול bina.top (170),
ובשניהם התוצאה נכונה: ב-bina.top החבר הראשון הוא uid=1 שנרשם ב-2026-05-09.

**עלות: שש-שבע בקשות בסך הכול.** לא סריקה — שליפה. הפורומים האלה הם התקנות
NodeBB שמתנדבים מתחזקים, ולכן כל מקטע הוא בקשה אחת ולא מעבר על הארכיון.

**אין JavaScript בדוח כלל.** כל הגרפים הם רוחבי div ב-CSS. דוח בלי סקריפט
הוא דוח שאין בו מה לפרוץ, והוא נפתח זהה בכל מקום גם שנים אחרי שנשמר.
"""
import html
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import i18n
import net
import scraper

REPORT_NAME = "תיק הפורום"

DEFAULT_BASE = "https://mitmachim.top"

# ── ה-User-Agent המזוהה, ולמה דווקא הוא ──────────────────────────────────
# נמדד מול mitmachim.top, פעמיים לכל צד ויציב לחלוטין:
#   Tik-Nick/1.0            → 10 קטגוריות,   938,662 פוסטים
#   Chrome/120 (כמו דפדפן)  → 11 קטגוריות, 1,089,188 פוסטים
# כלומר הפורום מראה קטגוריה נוספת למי שנראה כמו דפדפן. לקחת את המספר הגדול
# פירושו להשיג נתונים **בזכות זה שלא הזדהינו** — וזו בדיוק ההחלטה שכבר
# הוכרעה כאן: הסורק מזדהה בשמו, בלי סיבוב UA ובלי התחזות.
# לכן הכלי הזה משתמש ב-UA של הסורק, מקבל את המספר הקטן יותר, והכותרת אומרת
# במפורש "בקטגוריות הגלויות".
# (chazonishnik ו-stinknik עדיין נושאים UA של דפדפן — קדם להחלטה, ושינוי
#  שלהם הוא שינוי התנהגות של כלי קיים, לא חלק מהתוספת הזו.)
_UA = scraper.USER_AGENT

PAGE_DELAY = 0.5           # אותו נימוס כמו בשאר המודולים
REQ_TIMEOUT = 12
TOTAL_DEADLINE = 45.0      # תקרה קשיחה לכל הדוח; מה שלא הספיק — מדווח כחסר
FIRST_MEMBERS = 12
TOP_ROWS = 8
USERS_PER_PAGE = 50        # NodeBB מחזיר 50 בעמוד ב-/api/users
_MAX_PROBE = 8             # תקרה על אימות העמוד האחרון — שליפה, לא סריקה

# ── מה שאי אפשר לענות עליו, ולמה ─────────────────────────────────────────
# שתי השורות האלה נכנסות לדוח עצמו. משתמש שרואה "הכי הרבה דיסלייקים בפורום"
# חסר ולא מבין למה, יניח שהכלי שבור; משתמש שקורא למה — יודע בדיוק מה הוא
# מחזיק ביד.
_LIMITS = [
    ("הפוסט הראשון בפורום",
     "ל-NodeBB אין נתיב ציבורי לנושא הישן ביותר: הפרמטר sort=oldest_to_newest "
     "מתעלם מאורח (נבדק — התשובה חוזרת עם recently_replied), ו-‎/api/topic/1 "
     "מחזיר 404. במקום לנחש, מוצג כאן הוותיק ביותר מבין הנושאים הבולטים."),
    ("מונה הנושאים והפוסטים",
     "הוא סכום הקטגוריות שהפורום מציג לכלי הזה. קטגוריה שדורשת הרשאה אינה "
     "נספרת, ולכן זו רצפה ולא סך הכול האמיתי של הפורום."),
    ("הפוסט עם הכי הרבה דיסלייקים בפורום",
     "דיסלייקים אינם נחשפים ברמת הפורום — רק פר-פוסט. שטינקניק מוצא אותם "
     "למשתמש אחד כי הוא עובר על הפוסטים שלו; לעשות את זה לפורום שלם פירושו "
     "אלפי בקשות לשרת של מתנדבים, וזה לא ייעשה. **המשתמש** עם הכי הרבה "
     "דיסלייקים כן מוערך למטה, מתוך המוניטין שכבר נסרק."),
]


def _t(s):
    """
    תרגום של מחרוזת שנבנית **בזמן ריצה** ולא יושבת בתבנית.

    `translate_template` רץ על התבנית בלבד, ולכן כל תווית שמוזרקת אחר כך
    (שם הדוח, "צפיות", "נרשם", "במאגר") נשארה עברית באנגלית למרות שהמפתח
    כבר היה ב-`_TPL_EN`. אותו דפוס כמו `stinknik._t` עם `_LOCAL_EN`.
    """
    if i18n.lang() != "en":
        return s
    return _TPL_EN.get(s) or i18n.t(s)


# ══ רשת ═══════════════════════════════════════════════════════════════════
class ChallengeError(Exception):
    """הפורום החזיר דף אתגר (Cloudflare) ולא JSON. **אין שום ניסיון לעקוף** —
    זיהוי בלבד, כדי לומר את האמת במקום 'אין API בכתובת'. ראו 0.8.23."""


def _get_json(url, cookie=None, timeout=REQ_TIMEOUT, retries=2, budget=None):
    """
    GET JSON עם ריטריי וכיבוד Retry-After.

    `budget` הוא פונקציה שמחזירה כמה שניות נשארו לכל הדוח. בלעדיה תקרת הזמן
    הייתה הצהרה בלבד: הבדיקה נעשתה רק **לפני** הבקשה, ואז לולאת הריטריי הוסיפה
    עוד עד 25 שניות אחריה. נמדד בביקורת: 67.6 שניות מול תקרה מוצהרת של 45.
    """
    def left():
        return REQ_TIMEOUT if budget is None else budget()

    last = None
    for attempt in range(1, retries + 1):
        t = max(1.0, min(timeout, left()))
        # ה-Request נבנה מחדש בכל ניסיון: ProxyHandler.set_proxy **משנה** את
        # האובייקט, וניסיון חוזר על אותו אחד יוצא בטקסט גלוי לפורט 80.
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _UA)
        req.add_header("Accept", "application/json")
        if cookie:
            val = cookie if cookie.startswith("express.sid=") else "express.sid=" + cookie
            req.add_header("Cookie", val)
        try:
            with net.urlopen(req, timeout=t) as resp:
                raw = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(raw)
            except ValueError:
                # גוף שאינו JSON: לרוב דף אתגר שחוזר דווקא עם 200. אין טעם
                # לנסות שוב — ניסיון שני יקבל בדיוק את אותו דף.
                if scraper._looks_like_challenge(raw):
                    raise ChallengeError(
                        "הפורום מוגן ב-Cloudflare וחוסם כרגע גישה אוטומטית")
                raise
        except ChallengeError:
            raise
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 and attempt < retries and left() > 3:
                try:
                    time.sleep(min(10, max(0.0, left() - 1),
                                   float(e.headers.get("Retry-After") or 2)))
                except (TypeError, ValueError):
                    time.sleep(2)
                continue
            raise
        except Exception as e:                       # noqa: BLE001
            last = e
            if attempt < retries and left() > 3:
                time.sleep(1.0)
                continue
            raise
    raise last


class _Fetcher:
    """
    כל מקטע בדוח הוא בקשה אחת, וכל בקשה יכולה להיכשל בלי להפיל את השאר.

    זה הדפוס של "דיווח כן על חלקיות" שכבר נהוג כאן: עדיף דוח עם מקטע אחד
    שאומר "לא זמין" מאשר דוח שנופל כולו, או — גרוע מזה — מקטע שממציא מספר.
    """

    def __init__(self, base, cookie=None, deadline=TOTAL_DEADLINE):
        # כתובת בלי סכימה היא מצב נפוץ: `add_forum` שומרת בדיוק מה שהוקלד, וכל
        # שאר מסלולי הרשת בתוכנה משלימים https בעצמם (scraper._api_base,
        # db._origin, net.test_connection). בלי זה "bina.top" נכשל כאן בלבד,
        # עם הודעה שמאשימה את הפורום.
        b = (base or "").strip().rstrip("/")
        self.base = b if b.startswith(("http://", "https://")) else "https://" + b
        self.cookie = cookie or None
        self.t0 = time.time()
        self.deadline = deadline
        self.calls = 0            # בקשות HTTP בפועל, כולל ריטריי — הפוטר מצטט אותו
        self.failed = []
        self.challenge = ""
        self._first = True

    def left(self):
        return self.deadline - (time.time() - self.t0)

    def out_of_time(self):
        return self.left() <= 0

    def get(self, path):
        if self.out_of_time():
            self.failed.append((path, "חריגה מהזמן המוקצב"))
            return None
        if not self._first:
            time.sleep(min(PAGE_DELAY, max(0.0, self.left())))
        self._first = False

        def budget():
            self.calls += 1       # נספר פר-ניסיון, לא פר-קריאה
            return self.left()

        try:
            return _get_json(self.base + path, self.cookie, budget=budget)
        except ChallengeError as e:
            self.challenge = str(e)
            logging.warning("forumstats: %s -> challenge page", path)
            self.failed.append((path, "Cloudflare"))
            return None
        except Exception as e:                       # noqa: BLE001
            logging.warning("forumstats: %s failed: %s", path, e)
            self.failed.append((path, type(e).__name__))
            return None


# ══ עזרי טקסט ═════════════════════════════════════════════════════════════
def _txt(v):
    """טקסט מהפורום חוזר מקודד ל-HTML — ראו scraper._txt (הלקח מ-0.8.21)."""
    s = "" if v is None else str(v)
    return html.unescape(s) if "&" in s else s


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _date(ms):
    """חותמת NodeBB היא מילישניות. תאריך בלבד — שעה אינה מוסיפה כאן דבר."""
    n = _int(ms)
    if n <= 0:
        return ""
    try:
        return datetime.fromtimestamp(n / 1000, timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def _norm_name(s):
    """אותו נרמול שמשמש בהצעות הזהות: רווח/מקף/קו תחתון אינם הבדל."""
    return re.sub(r"[\s_\-]+", "", _txt(s)).strip().lower()


def _fill(template, values):
    """מעבר החלפה יחיד — ראו stinknik._fill. שרשרת replace סורקת מה שכבר הוזרק."""
    return re.sub(r"__([A-Z_]+)__", lambda m: values.get(m.group(1), m.group(0)),
                  template)


# ══ איסוף ═════════════════════════════════════════════════════════════════
def _members_page(f, page=None):
    q = "/api/users?section=joindate"
    if page:
        q += "&page=%d" % page
    return f.get(q)


def _first_members(f, want=FIRST_MEMBERS):
    """
    החברים הראשונים. מחזיר (status, rows, meta) —
    status: "ok" · "unavailable" (לא הצלחנו לאמת) · "unreachable" (הפורום לא ענה).

    ‎/api/users?section=joindate ממוין **מהחדש לישן** (הכותרת היא
    users/latest), ולכן הראשונים יושבים בעמוד ה**אחרון**.

    **שני באגים חמורים שנתפסו בביקורת האדוורסרית, ושניהם נתנו תשובה שגויה
    בביטחון מלא — בדיוק מה שהמודול הזה מבטיח לא לעשות:**

    1. *נפילה ל-pageCount.* כשאין `userCount` הקוד לקח `pageCount`, וזה השדה
       שכל הפרויקט כבר יודע שהוא משקר (התקנות שמחזירות 1 גם כשיש מאות עמודים).
       `pageCount=1` הפך את עמוד **החדשים** ל"מייסדים" — הרשימה מתהפכת לגמרי,
       ואין שום סימן לכך בדוח.
    2. *עמוד אחרון שנכשל.* הבקשה לעמוד האחרון היא הכי חשופה לתפוגה (עמוד 621
       ב-mitmachim), וכשהיא נכשלה `pool` נשאר ריק, התנאי "עמוד חלקי" התקיים,
       והקוד הכתיר את עמוד `last-1` כמייסדים. תאריך הפתיחה זז בשלושה שבועות
       והחבר ה-21 קיבל מדליית זהב.

    לכן: **מאמתים את העמוד האחרון במקום לנחש אותו.** הניחוש מגיע מ-`userCount`
    בלבד, ואז מתקדמים קדימה כל עוד העמוד מלא — עמוד חלקי או עמוד ריק אחריו הם
    ההוכחה שהגענו לסוף. אם לא הצלחנו לאמת בתוך `_MAX_PROBE` צעדים, או שבקשה
    נכשלה — **מדווחים שהמקטע לא זמין**, ולא מציגים את מי שבמקרה הגיע.
    """
    head = _members_page(f)
    if not head:
        return "unreachable", None, {}
    users0 = head.get("users") or []
    meta = {
        "user_count": _int(head.get("userCount")),
        "page_count": _int((head.get("pagination") or {}).get("pageCount")),
    }
    per = len(users0) or USERS_PER_PAGE
    cache = {1: users0}

    def page(n):
        if n not in cache:
            d = _members_page(f, n)
            cache[n] = None if d is None else (d.get("users") or [])
        return cache[n]

    guess = max(1, -(-meta["user_count"] // per)) if meta["user_count"] > 0 else 1
    last, steps, confirmed = guess, 0, False
    while steps <= _MAX_PROBE:
        cur = page(last)
        if cur is None:
            return "unavailable", None, meta      # העמוד שמחזיק את הראשונים לא נטען
        if len(cur) < per:
            confirmed = True                       # עמוד חלקי = הסוף
            break
        nxt = page(last + 1)
        if nxt is None:
            return "unavailable", None, meta
        if not nxt:
            confirmed = True                       # אחריו ריק = הוא הסוף
            break
        last += 1
        steps += 1
    if not confirmed:
        return "unavailable", None, meta
    # עמוד אחרון **ריק** אינו "סוף מאומת" אלא ספירה שנסחפה: הוותיקים יושבים
    # בעמוד שלא חזר, והליכה אחורה מכאן הייתה מכתירה את מי שיושב לפניו.
    # (פורום ריק באמת נופל על last == 1, וזו תשובה לגיטימית.)
    if last > 1 and not page(last):
        return "unavailable", None, meta

    # מכאן אחורה, כדי להשלים את הכמות המבוקשת כשהעמוד האחרון קטן ממנה
    pool, seen, n, back = [], set(), last, 0
    while n >= 1 and len(pool) < want and back <= _MAX_PROBE:
        cur = page(n)
        if cur is None:
            break            # מה שכבר נאסף תקף — פשוט לא נשלים אחורה
        for u in cur:
            uid = _int(u.get("uid"))
            if uid not in seen:
                seen.add(uid)
                pool.append(u)
        n -= 1
        back += 1

    # מיון לפי (תאריך, uid) ולא לפי תאריך בלבד: בפורום שעבר מיגרציה עשרות
    # חשבונות נושאים בדיוק את אותו תאריך, ואז ה-uid הוא סדר ההרשמה האמיתי.
    pool.sort(key=lambda u: (_int(u.get("joindate")), _int(u.get("uid"))))
    return "ok", pool[:want], meta


def _people(users, key, want=TOP_ROWS):
    out = []
    for u in (users or [])[:want]:
        out.append({
            "uid": _int(u.get("uid")),
            "name": _txt(u.get("username")),
            "slug": _txt(u.get("userslug")) or _txt(u.get("username")),
            "joined": _date(u.get("joindate")),
            "posts": _int(u.get("postcount")),
            "rep": _int(u.get("reputation")),
            "value": _int(u.get(key)) if key else 0,
            "banned": bool(u.get("banned")),
        })
    return out


def _topics(data, want=TOP_ROWS):
    out = []
    for t in (data or {}).get("topics") or []:
        u = t.get("user") or {}
        out.append({
            "tid": _int(t.get("tid")),
            "title": _txt(t.get("title")),
            "slug": _txt(t.get("slug")),
            "views": _int(t.get("viewcount")),
            "posts": _int(t.get("postcount")),
            "up": _int(t.get("upvotes")),
            "down": _int(t.get("downvotes")),
            "ts": _int(t.get("timestamp")),
            "date": _date(t.get("timestamp")),
            "author": _txt(u.get("username")),
            "cat": _txt((t.get("category") or {}).get("name")),
        })
    return out[:want] if want else out


def _categories(data, want=TOP_ROWS):
    out = []
    for c in (data or {}).get("categories") or []:
        out.append({
            "cid": _int(c.get("cid")),
            "name": _txt(c.get("name")),
            "topics": _int(c.get("totalTopicCount") or c.get("topic_count")),
            "posts": _int(c.get("totalPostCount") or c.get("post_count")),
            "color": _txt(c.get("bgColor")) or "",
        })
    out.sort(key=lambda c: -c["posts"])
    return out[:want], sum(c["posts"] for c in out), sum(c["topics"] for c in out)


NEWLINE = chr(10)


def _collect(base_url=DEFAULT_BASE, cookie=None, known_usernames=None,
             first_n=FIRST_MEMBERS, deadline=TOTAL_DEADLINE, local=None):
    """
    אוסף את כל מה שצריך לפורום אחד ומחזיר את החלקים, בלי לבנות HTML —
    כדי ששני מסלולי הכניסה (פורום אחד / כמה) יחלקו בדיוק את אותו קוד רשת.

    `known_usernames` — שמות הניקים שכבר יש עליהם תיק ב-Tik-Nick באותו פורום.
    זה מה שהופך את הדוח לכלי של התוכנה ולא לדף סטטיסטיקות גנרי: ליד כל חבר
    מייסד מסומן אם הוא כבר במאגר. הנרמול זהה לזה של הצעות הזהות.
    """
    f = _Fetcher(base_url, cookie, deadline)
    known = {_norm_name(n) for n in (known_usernames or ()) if str(n).strip()}

    status, firsts, meta = _first_members(f, first_n)
    if status == "unreachable":
        return {"ok": False, "html": "", "stats": {},
                "error": f.challenge or "לא ניתן לקרוא את רשימת המשתמשים של הפורום"}

    # "unavailable" = הגענו לפורום, אבל לא הצלחנו **לאמת** מי הראשונים. הדוח
    # נבנה בלי הכרטיס הזה ובלי תאריך הפתיחה, במקום להציג את מי שבמקרה הגיע.
    first_rows = _people(firsts or [], None, first_n)
    for r in first_rows:
        r["in_db"] = _norm_name(r["name"]) in known

    cats_raw = f.get("/api/categories")
    cats, total_posts, total_topics = _categories(cats_raw)

    popular = _topics(f.get("/api/popular?term=alltime"), 0)
    top_posters = _people((f.get("/api/users?section=sort-posts") or {}).get("users"),
                          "postcount")
    notable = _topics(f.get("/api/top?term=alltime"), 0)

    # שני הנתיבים מחזירים חלק מאותם נושאים. בלי איחוד לפי tid אותו נושא הופיע
    # פעמיים באותו כרטיס — וגם נושא שכבר הורד נשאר מחוץ לדירוג בלי סיבה.
    by_tid = {}
    for t in notable + popular:
        by_tid.setdefault(t["tid"], t)
    pool = list(by_tid.values())

    most_viewed = sorted(pool, key=lambda t: -t["views"])[:TOP_ROWS]
    most_replied = sorted(pool, key=lambda t: -t["posts"])[:TOP_ROWS]
    # "הוותיק מבין הבולטים" — לא "הראשון בפורום". ראו _LIMITS.
    oldest = sorted([t for t in pool if t["ts"] > 0], key=lambda t: t["ts"])[:TOP_ROWS]

    stats = {
        "base": f.base,
        "user_count": meta.get("user_count", 0),
        "total_posts": total_posts,
        "total_topics": total_topics,
        "categories": len(((cats_raw or {}).get("categories")) or []),
        # התאריך הוא של החבר הראשון שנמצא — ולא תאריך פתיחה רשמי. הכותרת
        # בדוח אומרת בדיוק את זה. כשהרשימה לא אומתה, אין תאריך בכלל.
        "founded": first_rows[0]["joined"] if first_rows else "",
        "first_members": first_rows,
        "members_ok": status == "ok",
        "in_db": sum(1 for r in first_rows if r["in_db"]),
        "local": dict(local or {}),
        "requests": f.calls,
        "missing": [p for p, _ in f.failed],
    }
    # דוח שכל המקטעים שלו ריקים אינו "דוח חלקי" אלא כישלון: מסגרת עם שש
    # פעמים "אין נתונים זמינים" רק מבזבזת למשתמש את הזמן.
    if not (first_rows or cats or pool or top_posters):
        return {"ok": False, "html": "", "stats": stats,
                "error": f.challenge or "הפורום לא החזיר נתונים"}

    return {"ok": True, "stats": stats, "error": "",
            "parts": (stats, cats, most_viewed, most_replied, top_posters,
                      oldest, f.failed, local or {})}


def analyze_forum(base_url=DEFAULT_BASE, cookie=None, known_usernames=None,
                  first_n=FIRST_MEMBERS, deadline=TOTAL_DEADLINE, local=None):
    """דוח של פורום אחד. מחזיר {ok, html, stats, error}."""
    r = _collect(base_url, cookie, known_usernames, first_n, deadline, local)
    if not r["ok"]:
        return {"ok": False, "html": "", "stats": r.get("stats") or {},
                "error": r["error"]}
    return {"ok": True, "stats": r["stats"], "error": "",
            "html": _build_html(*r["parts"])}


def analyze_forums(targets, first_n=FIRST_MEMBERS, deadline=TOTAL_DEADLINE):
    """
    דוח אחד לכמה פורומים.

    בנימין: *"בסנכרון לאינטרנט אפשר לסמן כמה. הבעיה שהפיצ'ר לא עובד עם כמה
    יחד."* — צדק; הכלי לקח את הפורום הפעיל בלבד.

    `targets` הוא רשימת `{name, url, cookie, known, local}`. הפורומים נסרקים
    **בזה אחר זה ולא במקביל** — בדיוק כמו בהשוואת שני המשתמשים בחזונישניק:
    שניים בו-זמנית מכפילים את העומס, וכל מנגנון הנימוס בנוי סביב זרם אחד.
    לכל פורום תקציב זמן משלו, כך שפורום אחד שנתקע לא בולע את כל הדוח.

    פורום שנכשל לגמרי מקבל שורה בטבלה ומקטע שאומר זאת — ולא מפיל את השאר.
    """
    targets = [t for t in (targets or []) if (t.get("url") or "").strip()]
    if not targets:
        return {"ok": False, "html": "", "stats": {}, "error": "לא נבחר אף פורום"}
    if len(targets) == 1:
        t = targets[0]
        return analyze_forum(t["url"], t.get("cookie"), t.get("known"),
                             first_n, deadline, t.get("local"))

    rows, sections, calls, failed_names = [], [], 0, []
    for t in targets:
        name = t.get("name") or t["url"]
        r = _collect(t["url"], t.get("cookie"), t.get("known"), first_n,
                     deadline, t.get("local"))
        st = r.get("stats") or {}
        loc = t.get("local") or {}
        calls += _int(st.get("requests"))
        rows.append({
            "name": name, "founded": st.get("founded") or "",
            "user_count": st.get("user_count"), "total_topics": st.get("total_topics"),
            "total_posts": st.get("total_posts"), "scanned": loc.get("scanned"),
            "banned": loc.get("banned"),
        })
        if r["ok"]:
            sections.append(_build_grid(*r["parts"], section_title=name))
        else:
            failed_names.append(name)
            sections.append(
                '<div class="sect"><bdi>%s</bdi></div>'
                '<div class="card col-12"><div class="empty">%s</div></div>'
                % (_esc(name), _esc(r["error"] or _t("הפורום לא החזיר נתונים"))))

    if len(failed_names) == len(targets):
        return {"ok": False, "html": "", "stats": {},
                "error": "אף אחד מהפורומים שנבחרו לא החזיר נתונים"}
    stats = {"forums": [r["name"] for r in rows], "compare": rows,
             "requests": calls, "failed": failed_names}
    subtitle = "%d %s · %s" % (len(targets), _t("פורומים"),
                               " · ".join(r["name"] for r in rows))
    html_out = _page("📇 " + _t(REPORT_NAME), subtitle,
                     _compare_table(rows), NEWLINE.join(sections), calls)
    return {"ok": True, "html": html_out, "stats": stats, "error": ""}


# ══ הדוח ══════════════════════════════════════════════════════════════════
def _bar(value, top, color="var(--accent)"):
    pct = 0 if top <= 0 else max(2, min(100, round(value * 100.0 / top)))
    return ('<div class="bar"><div class="bar-fill" style="width:%d%%;background:%s">'
            '</div></div>' % (pct, color))


def _rank_badge(i):
    return {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, str(i + 1))


def _topic_rows(base, topics, metric, label, bars=True):
    if not topics:
        return '<div class="empty">' + _esc(_t("אין נתונים זמינים")) + '</div>'
    top = max(t[metric] for t in topics) or 1
    rows = []
    for t in topics:
        link = "%s/topic/%s" % (base, urllib.parse.quote(t["slug"] or str(t["tid"]),
                                                         safe="/"))
        rows.append(
            '<div class="row">'
            '<div class="row-main"><a href="%s" target="_blank" class="tlink">%s</a>'
            '<div class="row-sub">%s%s</div></div>'
            '<div class="row-num">%s<span class="unit">%s</span></div>'
            '%s</div>' % (
                _esc(link), _esc(t["title"]) or _esc(_t("ללא כותרת")),
                _esc(t["date"]),
                (" · " + _esc(t["author"])) if t["author"] else "",
                "{:,}".format(t[metric]), _esc(label),
                _bar(t[metric], top) if bars else ""))
    return "".join(rows)


def _member_rows(base, rows):
    if not rows:
        return '<div class="empty">' + _esc(_t("אין נתונים זמינים")) + '</div>'
    out = []
    for i, r in enumerate(rows):
        link = "%s/user/%s" % (base, urllib.parse.quote(r["slug"], safe=""))
        badge = ('<span class="tag ok">' + _esc(_t("במאגר")) + '</span>') if r["in_db"] else ""
        banned = ('<span class="tag bad">' + _esc(_t("מורחק")) + '</span>') if r["banned"] else ""
        out.append(
            '<div class="row">'
            '<div class="rank">%s</div>'
            '<div class="row-main"><a href="%s" target="_blank" class="tlink">%s</a>%s%s'
            '<div class="row-sub">%s %s · uid %s</div></div>'
            '<div class="row-num">%s<span class="unit">%s</span></div>'
            '</div>' % (
                _rank_badge(i), _esc(link), _esc(r["name"]), badge, banned,
                _esc(_t("נרשם")), _esc(r["joined"]), _esc(r["uid"]),
                "{:,}".format(r["posts"]), _esc(_t("פוסטים"))))
    return "".join(out)


def _people_rows(base, rows, label):
    if not rows:
        return '<div class="empty">' + _esc(_t("אין נתונים זמינים")) + '</div>'
    top = max(r["value"] for r in rows) or 1
    out = []
    for r in rows:
        link = "%s/user/%s" % (base, urllib.parse.quote(r["slug"], safe=""))
        out.append(
            '<div class="row">'
            '<div class="row-main"><a href="%s" target="_blank" class="tlink">%s</a>'
            '<div class="row-sub">%s %s</div></div>'
            '<div class="row-num">%s<span class="unit">%s</span></div>'
            '%s</div>' % (
                _esc(link), _esc(r["name"]), _esc(_t("נרשם")), _esc(r["joined"]),
                "{:,}".format(r["value"]), _esc(label), _bar(r["value"], top)))
    return "".join(out)


def _local_note(local):
    """מה בדיוק עומד מאחורי המקטע הזה — כמה ניקים, ומתי נסרקו."""
    n = _int(local.get("scanned"))
    if not n:
        return _t("אין עדיין ניקים סרוקים מהפורום הזה במאגר. סרוק אותו, "
                  "והמקטע הזה יתמלא — בלי אף בקשה נוספת.")
    bits = [_t("מחושב מ-") + "{:,}".format(n) + _t(" ניקים שסרוקים אצלך")]
    if _int(local.get("banned")):
        bits.append("{:,}".format(_int(local["banned"])) + _t(" מורחקים"))
    if _int(local.get("no_posts")):
        bits.append("{:,}".format(_int(local["no_posts"])) + _t(" בלי אף פוסט"))
    when = str(local.get("last_scrape") or "")[:10]
    if when:
        bits.append(_t("נסרק לאחרונה ") + when)
    return " · ".join(bits) + " · " + _t("אפס בקשות רשת")


def _rep_rows(base, rows, negative):
    """
    שורות מוניטין מהמאגר המקומי.

    **הרעיון של בנימין**: `reputation` נאסף מכל משתמש בכל סריקה מאז ומעולם,
    ומי שהמספר שלו הנמוך ביותר הוא מי שספג הכי הרבה דיסלייקים. זה עונה על
    השאלה שאמרתי שה-API לא יכול לענות עליה — כי התשובה כבר יושבת מקומית,
    באפס בקשות.

    זו **הערכה ולא ספירה**: מוניטין ב-NodeBB הוא הפרש (לייקים פחות
    דיסלייקים), ולכן מי שקיבל אלף לייקים ואלף דיסלייקים ייראה כמו מי שלא
    קיבל דבר. הכרטיס אומר את זה במפורש.
    """
    if not rows:
        return ('<div class="empty">'
                + _esc(_t("אין נתוני מוניטין בניקים שנסרקו")) + "</div>")
    top = max(abs(_int(r.get("rep"))) for r in rows) or 1
    out = []
    for r in rows:
        name = _txt(r.get("username"))
        link = "%s/user/%s" % (base, urllib.parse.quote(
            re.sub(r"\s+", "-", name), safe=""))
        rep = _int(r.get("rep"))
        out.append(
            '<div class="row">'
            '<div class="row-main"><a href="%s" target="_blank" class="tlink">%s</a>'
            '<div class="row-sub">%s %s</div></div>'
            '<div class="row-num" style="color:%s">%s</div>'
            '%s</div>' % (
                _esc(link), _esc(name) or _esc(_t("ללא שם")),
                "{:,}".format(_int(r.get("posts"))), _esc(_t("פוסטים")),
                "var(--bad)" if negative else "var(--ok)",
                "{:,}".format(rep),
                _bar(abs(rep), top, "var(--bad)" if negative else "var(--ok)")))
    return "".join(out)


def _ratio_rows(base, rows):
    """
    מוניטין **לפוסט**: מי שכל פוסט שלו אהוב, ולא מי שכתב הכי הרבה.

    זו הזווית שאף אחד לא רואה — בפורום מדורגים לפי כמות, וכאן מדורגים לפי
    יחס. רצפת 30 פוסטים מונעת ממי שכתב פוסט אחד מוצלח להוביל את הטבלה.
    """
    if not rows:
        return ('<div class="empty">'
                + _esc(_t("אין מספיק כותבים ותיקים בניקים שנסרקו")) + "</div>")
    top = max(float(r.get("ratio") or 0) for r in rows) or 1.0
    out = []
    for r in rows:
        name = _txt(r.get("username"))
        link = "%s/user/%s" % (base, urllib.parse.quote(
            re.sub(r"\s+", "-", name), safe=""))
        ratio = float(r.get("ratio") or 0)
        out.append(
            '<div class="row">'
            '<div class="row-main"><a href="%s" target="_blank" class="tlink">%s</a>'
            '<div class="row-sub">%s %s · %s %s</div></div>'
            '<div class="row-num" style="color:var(--ok)">%s<span class="unit">%s</span></div>'
            '%s</div>' % (
                _esc(link), _esc(name) or _esc(_t("ללא שם")),
                "{:,}".format(_int(r.get("posts"))), _esc(_t("פוסטים")),
                "{:,}".format(_int(r.get("rep"))), _esc(_t("מוניטין")),
                _esc(("%.1f" % ratio) if ratio < 100 else "{:,}".format(int(ratio))),
                _esc(_t("לפוסט")),
                _bar(int(ratio * 100), int(top * 100), "var(--ok)")))
    return "".join(out)


def _gone_rows(base, rows):
    """ותיקים ששקטו — כתבו הרבה, ולא נראו יותר משנה."""
    if not rows:
        return ('<div class="empty">'
                + _esc(_t("אף כותב ותיק לא נעלם מהניקים שנסרקו")) + "</div>")
    top = max(_int(r.get("posts")) for r in rows) or 1
    out = []
    for r in rows:
        name = _txt(r.get("username"))
        link = "%s/user/%s" % (base, urllib.parse.quote(
            re.sub(r"\s+", "-", name), safe=""))
        out.append(
            '<div class="row">'
            '<div class="row-main"><a href="%s" target="_blank" class="tlink">%s</a>'
            '<div class="row-sub">%s %s · %s %s</div></div>'
            '<div class="row-num">%s<span class="unit">%s</span></div>'
            '%s</div>' % (
                _esc(link), _esc(name) or _esc(_t("ללא שם")),
                _esc(_t("נרשם")), _esc(str(r.get("join_date") or "")[:10]),
                _esc(_t("נראה לאחרונה")), _esc(str(r.get("last_seen") or "")[:10]),
                "{:,}".format(_int(r.get("posts"))), _esc(_t("פוסטים")),
                _bar(_int(r.get("posts")), top)))
    return "".join(out)


def _year_rows(rows):
    """גלי ההצטרפות לפי שנה — מתי הפורום גדל, ומתי הוא נעצר."""
    rows = [r for r in (rows or []) if str(r.get("year") or "").isdigit()]
    if not rows:
        return ('<div class="empty">'
                + _esc(_t("אין תאריכי הצטרפות בניקים שנסרקו")) + "</div>")
    top = max(_int(r.get("c")) for r in rows) or 1
    peak = max(rows, key=lambda r: _int(r.get("c")))
    out = []
    for r in rows:
        c = _int(r.get("c"))
        out.append(
            '<div class="row">'
            '<div class="row-main"><span class="tlink plain" dir="ltr">%s</span></div>'
            '<div class="row-num">%s<span class="unit">%s</span></div>'
            '%s</div>' % (
                _esc(r.get("year")), "{:,}".format(c), _esc(_t("נרשמו")),
                _bar(c, top, "var(--accent2)" if r is peak else "var(--accent)")))
    return "".join(out)


def _cat_rows(cats):
    if not cats:
        return '<div class="empty">' + _esc(_t("אין נתונים זמינים")) + '</div>'
    top = max(c["posts"] for c in cats) or 1
    out = []
    for c in cats:
        out.append(
            '<div class="row">'
            '<div class="row-main"><span class="tlink plain">%s</span>'
            '<div class="row-sub">%s %s</div></div>'
            '<div class="row-num">%s<span class="unit">%s</span></div>'
            '%s</div>' % (
                _esc(c["name"]), "{:,}".format(c["topics"]), _esc(_t("נושאים")),
                "{:,}".format(c["posts"]), _esc(_t("פוסטים")),
                _bar(c["posts"], top)))
    return "".join(out)


_TPL_EN = {
    "תיק הפורום": "The forum file",
    "הפוסט הראשון בפורום":
        "The forum's first post",
    "ל-NodeBB אין נתיב ציבורי לנושא הישן ביותר: הפרמטר sort=oldest_to_newest מתעלם מאורח (נבדק — התשובה חוזרת עם recently_replied), ו-‎/api/topic/1 מחזיר 404. במקום לנחש, מוצג כאן הוותיק ביותר מבין הנושאים הבולטים.":
        "NodeBB has no public route to the oldest topic: the sort=oldest_to_newest parameter is ignored for a guest (measured — the answer comes back with recently_replied), and /api/topic/1 returns 404. Rather than guess, what is shown here is the oldest of the notable topics.",
    "מונה הנושאים והפוסטים":
        "The topic and post counters",
    "הוא סכום הקטגוריות שהפורום מציג לכלי הזה. קטגוריה שדורשת הרשאה אינה נספרת, ולכן זו רצפה ולא סך הכול האמיתי של הפורום.":
        "They are the sum of the categories the forum shows this tool. A category that requires permission is not counted, so this is a floor rather than the forum's real total.",
    "הפוסט עם הכי הרבה דיסלייקים בפורום":
        "The forum's most-downvoted post",
    "דיסלייקים אינם נחשפים ברמת הפורום — רק פר-פוסט. שטינקניק מוצא אותם למשתמש אחד כי הוא עובר על הפוסטים שלו; לעשות את זה לפורום שלם פירושו אלפי בקשות לשרת של מתנדבים, וזה לא ייעשה. **המשתמש** עם הכי הרבה דיסלייקים כן מוערך למטה, מתוך המוניטין שכבר נסרק.":
        "Downvotes are not exposed forum-wide — only per post. Stinknik finds them for one user because it walks that user's posts; doing it for a whole forum would mean thousands of requests to a volunteer's server, and it will not be done. The **user** with the most downvotes is estimated below, from the reputation already scanned.",
    "הפורום לא החזיר נתונים":
        "The forum returned no data",
    "השוואה בין פורומים": "Forum comparison",
    "פורומים": "forums",
    "החברים הראשונים": "The first members",
    "הקטגוריות הגדולות": "The largest categories",
    "הנושאים הכי נצפים": "Most viewed topics",
    "הנושאים הכי מדוברים": "Most discussed topics",
    "הכותבים הגדולים": "The biggest posters",
    "הוותיקים מבין הנושאים הבולטים": "The oldest of the notable topics",
    "מה לא מוצג כאן, ולמה": "What is not shown here, and why",
    "נפתח": "Opened",
    "משתמשים": "Members",
    "נושאים": "Topics",
    "פוסטים": "Posts",
    "קטגוריות": "Categories",
    "צפיות": "views",
    "תגובות": "replies",
    "נרשם": "joined",
    "במאגר": "on file",
    "מורחק": "banned",
    "ללא כותרת": "Untitled",
    "אין נתונים זמינים": "No data available",
    "החבר הראשון נרשם": "First member joined",
    "לא תאריך פתיחה רשמי": "not an official opening date",
    "לא ניתן היה לאמת מי נרשם ראשון — הרשימה אינה מוצגת כדי לא להציג את האנשים הלא נכונים":
        "Who joined first could not be verified — the list is withheld rather than show the wrong people",
    "מתוך הנושאים שהפורום מפרסם כפופולריים ומדוברים — לא מתוך כל הארכיון":
        "From the topics the forum publishes as popular and top — not the whole archive",
    "מתוך אותה רשימה": "From that same list",
    "הוותיק ביותר מבין אותם נושאים — לא הנושא הראשון בפורום":
        "The oldest of those topics — not the forum's first topic",
    "בקטגוריות הגלויות": "in the categories a guest can see",
    "מתוך רשימת הנושאים הפופולריים שהפורום מפרסם":
        "From the popular-topics list the forum publishes",
    "מתוך אותה רשימה — לא מתוך כל הארכיון":
        "From that same list — not from the whole archive",
    "מהמאגר שלך": "From your own database",
    "הכי אהובים לפי פוסט": "Best liked per post",
    "מוניטין חלקי מספר הפוסטים — מי שכל פוסט שלו נחשב, ולא מי שכתב הכי הרבה. מ-30 פוסטים ומעלה":
        "Reputation divided by post count — whose every post counts, rather than who wrote the most. From 30 posts up",
    "גלי הצטרפות": "Waves of arrival",
    "לפי שנת ההרשמה של הניקים שסרוקים אצלך": "By the join year of the nicks on file",
    "ותיקים ששקטו": "Veterans who went quiet",
    "כתבו לפחות 50 פוסטים, ולא נראו יותר משנה":
        "Wrote at least 50 posts and have not been seen for over a year",
    "אין מספיק כותבים ותיקים בניקים שנסרקו":
        "Not enough established posters among the scanned nicks",
    "אף כותב ותיק לא נעלם מהניקים שנסרקו":
        "No established poster has gone missing among the scanned nicks",
    "אין תאריכי הצטרפות בניקים שנסרקו": "No join dates among the scanned nicks",
    "מוניטין": "reputation", "לפוסט": "per post", "נרשמו": "joined",
    "נראה לאחרונה": "last seen",
    "הכי הרבה דיסלייקים": "Most downvotes",
    "הכי הרבה לייקים": "Most upvotes",
    "מוערך מהמוניטין: לייקים פחות דיסלייקים. מי שקיבל גם וגם בכמות דומה לא יופיע כאן":
        "Estimated from reputation: upvotes minus downvotes. Someone who got plenty of both will not show up here",
    "אותו מספר, מהקצה השני": "The same number, from the other end",
    "אין נתוני מוניטין בניקים שנסרקו": "No reputation data in the scanned nicks",
    "אין עדיין ניקים סרוקים מהפורום הזה במאגר. סרוק אותו, והמקטע הזה יתמלא — בלי אף בקשה נוספת.":
        "No nicks from this forum are on file yet. Scan it and this section fills in — with no extra request.",
    "מחושב מ-": "Computed from ",
    " ניקים שסרוקים אצלך": " nicks on file",
    " מורחקים": " banned",
    " בלי אף פוסט": " with no posts at all",
    "נסרק לאחרונה ": "last scanned ",
    "אפס בקשות רשת": "zero network requests",
    "ללא שם": "Unnamed",
    "הופק מ-": "Produced from ",
    " בקשות בלבד": " requests only",
    "מקטעים שלא נטענו:": "Sections that did not load:",
}

_GRID = """__SECTION_HEAD__
<div class="grid">
  <div class="card col-3"><div class="kpi-t">החבר הראשון נרשם</div><div class="kpi-v">__FOUNDED__</div><div class="kpi-s">לא תאריך פתיחה רשמי</div></div>
  <div class="card col-3"><div class="kpi-t">משתמשים</div><div class="kpi-v">__USERS__</div></div>
  <div class="card col-3"><div class="kpi-t">נושאים</div><div class="kpi-v">__TOPICS__</div><div class="kpi-s">בקטגוריות הגלויות</div></div>
  <div class="card col-3"><div class="kpi-t">פוסטים</div><div class="kpi-v">__POSTS__</div><div class="kpi-s">בקטגוריות הגלויות</div></div>

  <div class="card col-6"><h3>👑 החברים הראשונים</h3>__FIRSTNOTE__
__FIRSTS__</div>
  <div class="card col-6"><h3>📚 הקטגוריות הגדולות</h3>__CATS__</div>
  <div class="card col-6"><h3>👀 הנושאים הכי נצפים</h3><div class="note">מתוך הנושאים שהפורום מפרסם כפופולריים ומדוברים — לא מתוך כל הארכיון</div>__VIEWED__</div>
  <div class="card col-6"><h3>💬 הנושאים הכי מדוברים</h3><div class="note">מתוך אותה רשימה</div>__REPLIED__</div>
  <div class="card col-6"><h3>✍️ הכותבים הגדולים</h3>__POSTERS__</div>
  <div class="card col-6"><h3>🕰️ הוותיקים מבין הנושאים הבולטים</h3><div class="note">הוותיק ביותר מבין אותם נושאים — לא הנושא הראשון בפורום</div>__OLDEST__</div>

  <div class="card col-12" style="padding-bottom:6px">
    <h3>📇 מהמאגר שלך</h3>
    <div class="note">__LOCALNOTE__</div></div>
  <div class="card col-6"><h3>👎 הכי הרבה דיסלייקים</h3>
    <div class="note">מוערך מהמוניטין: לייקים פחות דיסלייקים. מי שקיבל גם וגם בכמות דומה לא יופיע כאן</div>
__WORST__</div>
  <div class="card col-6"><h3>💚 הכי הרבה לייקים</h3>
    <div class="note">אותו מספר, מהקצה השני</div>
__BEST__</div>

  <div class="card col-6"><h3>⚡ הכי אהובים לפי פוסט</h3>
    <div class="note">מוניטין חלקי מספר הפוסטים — מי שכל פוסט שלו נחשב, ולא מי שכתב הכי הרבה. מ-30 פוסטים ומעלה</div>
__RATIO__</div>
  <div class="card col-6"><h3>📅 גלי הצטרפות</h3>
    <div class="note">לפי שנת ההרשמה של הניקים שסרוקים אצלך</div>
__YEARS__</div>
  <div class="card col-12"><h3>🌙 ותיקים ששקטו</h3>
    <div class="note">כתבו לפחות 50 פוסטים, ולא נראו יותר משנה</div>
__GONE__</div>

  <div class="card col-12"><h3>🔍 מה לא מוצג כאן, ולמה</h3>
    <div class="limits">__LIMITS__</div></div>
</div>"""


_TEMPLATE = """<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
:root{--bg:#0f172a;--card:#1e293b;--card2:#293548;--text:#e2e8f0;
      --dim:#94a3b8;--accent:#f59e0b;--accent2:#38bdf8;--ok:#10b981;--bad:#ef4444;
      --border:#334155}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:"Segoe UI",Arial,sans-serif;
     padding:26px 20px;line-height:1.6}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:1.9rem;margin-bottom:4px}
.sub{color:var(--dim);font-size:.92rem;margin-bottom:22px}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:15px}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;
      padding:17px 19px}
.col-3{grid-column:span 3}.col-4{grid-column:span 4}
.col-6{grid-column:span 6}.col-12{grid-column:span 12}
@media(max-width:900px){.col-3,.col-4,.col-6{grid-column:span 12}}
h3{font-size:1rem;margin-bottom:12px;color:var(--accent)}
.kpi-t{color:var(--dim);font-size:.83rem;font-weight:600;margin-bottom:6px}
.kpi-v{font-size:1.95rem;font-weight:800}
.kpi-s{color:var(--dim);font-size:.71rem;margin-top:3px}
.row{display:flex;align-items:center;gap:11px;padding:7px 0;
     border-bottom:1px solid var(--border);flex-wrap:wrap}
.row:last-child{border-bottom:none}
.rank{width:26px;text-align:center;font-size:1rem;flex:none}
.row-main{flex:1;min-width:150px}
.row-sub{color:var(--dim);font-size:.76rem}
.row-num{font-weight:700;white-space:nowrap;flex:none}
.unit{color:var(--dim);font-weight:400;font-size:.74rem;margin-inline-start:4px}
.bar{flex-basis:100%;height:4px;background:var(--card2);border-radius:99px;
     overflow:hidden}
.bar-fill{height:100%;border-radius:99px}
a.tlink{color:var(--text);text-decoration:none;font-weight:600}
a.tlink:hover{color:var(--accent2);text-decoration:underline}
.tlink.plain{font-weight:600}
.tag{font-size:.66rem;padding:1px 7px;border-radius:99px;margin-inline-start:6px;
     vertical-align:middle;white-space:nowrap}
.tag.ok{background:rgba(16,185,129,.16);color:var(--ok)}
.tag.bad{background:rgba(239,68,68,.16);color:var(--bad)}
.empty{color:var(--dim);font-size:.85rem;padding:8px 0}
.note{color:var(--dim);font-size:.74rem;margin:-6px 0 9px}
.warn-note{color:var(--accent);margin-bottom:10px}
.limits{background:var(--card2);border-inline-start:3px solid var(--accent);
        border-radius:9px;padding:13px 15px;font-size:.85rem}
.limits b{color:var(--accent)}
.limits li{margin:9px 0 0;list-style:none}
.foot{color:var(--dim);font-size:.76rem;margin-top:20px;text-align:center}
.sect{margin:26px 0 13px;padding-bottom:7px;border-bottom:1px solid var(--border);font-size:1.25rem;font-weight:800}
.sect a{color:var(--accent2);text-decoration:none;font-size:.8rem;font-weight:400;margin-inline-start:9px}
.cmp{width:100%;border-collapse:collapse;font-size:.86rem}
.cmp th,.cmp td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:start;white-space:nowrap}
.cmp th{color:var(--dim);font-weight:600;font-size:.78rem}
.cmp td.n{font-weight:700}
.cmp tr:last-child td{border-bottom:none}
.cmp .best{color:var(--accent)}
</style></head>
<body><div class="wrap">
<h1>__HEADING__</h1>
<div class="sub">__FORUM__</div>
__COMPARE__
__SECTIONS__
<div class="foot">__FOOT__</div>
</div></body></html>"""


_CMP_COLS = [
    ("name", "פורום", False),
    ("founded", "החבר הראשון", False),
    ("user_count", "משתמשים", True),
    ("total_topics", "נושאים", True),
    ("total_posts", "פוסטים", True),
    ("scanned", "סרוקים אצלך", True),
    ("banned", "מורחקים", True),
]


def _compare_table(rows):
    """
    טבלת השוואה בין הפורומים שנבחרו.

    זה מה שהופך "כמה פורומים" מרשימה של דוחות זה מתחת לזה לדבר שאי אפשר
    לראות בשום מקום אחר: איזה פורום גדול יותר, איזה ותיק יותר, ואיפה יש לך
    כיסוי. הערך הגבוה בכל עמודה מודגש.
    """
    if len(rows) < 2:
        return ""
    best = {}
    for key, _lbl, numeric in _CMP_COLS:
        if numeric:
            vals = [_int(r.get(key)) for r in rows]
            best[key] = max(vals) if any(vals) else None
    head = "".join("<th>%s</th>" % _esc(_t(lbl)) for _k, lbl, _n in _CMP_COLS)
    body = []
    for r in rows:
        tds = []
        for key, _lbl, numeric in _CMP_COLS:
            if key == "name":
                tds.append('<td class="n"><bdi>%s</bdi></td>' % _esc(r.get("name") or ""))
            elif numeric:
                v = _int(r.get(key))
                cls = "n best" if (best.get(key) and v == best[key]) else "n"
                tds.append('<td class="%s">%s</td>'
                           % (cls, "{:,}".format(v) if v else "—"))
            else:
                tds.append("<td>%s</td>" % _esc(r.get(key) or "—"))
        body.append("<tr>%s</tr>" % "".join(tds))
    return ('<div class="card col-12" style="margin-bottom:4px;overflow-x:auto">'
            '<h3>%s</h3><table class="cmp"><tr>%s</tr>%s</table></div>'
            % (_esc("⚖️ " + _t("השוואה בין פורומים")), head, "".join(body)))


def _build_grid(stats, cats, viewed, replied, posters, oldest, failed,
                local=None, section_title=""):
    """
    רשת הכרטיסים של פורום אחד.

    היא הוצאה מהשלד כדי שדוח אחד יוכל להחזיק כמה פורומים: בנימין דיווח
    שאפשר לסמן כמה פורומים בסנכרון, אבל הכלי עבד רק על הראשון שבהם.
    """
    base = stats["base"]
    limits = "".join(
        "<li><b>%s</b> — %s</li>" % (_esc(_t(a)), _esc(_t(b))) for a, b in _LIMITS)
    if failed:
        limits += ('<li style="color:var(--dim);margin-top:12px">' + _esc(_t("מקטעים שלא נטענו:"))
                   + " " + _esc(", ".join(p for p, _ in failed)) + "</li>")
    head = ""
    if section_title:
        head = ('<div class="sect"><bdi>%s</bdi><a href="%s" target="_blank">%s</a></div>'
                % (_esc(section_title), _esc(base), _esc(base)))
    return _fill(i18n.translate_template(_GRID, _TPL_EN), {
        "SECTION_HEAD": head,
        "FOUNDED": _esc(stats["founded"] or "—"),
        "USERS": "{:,}".format(stats["user_count"]) if stats["user_count"] else "—",
        "TOPICS": "{:,}".format(stats["total_topics"]) if stats["total_topics"] else "—",
        "POSTS": "{:,}".format(stats["total_posts"]) if stats["total_posts"] else "—",
        "FIRSTNOTE": ("" if stats.get("members_ok") else
                      '<div class="note warn-note">' +
                      _esc(_t("לא ניתן היה לאמת מי נרשם ראשון — הרשימה אינה מוצגת ""כדי לא להציג את האנשים הלא נכונים")) + "</div>"),
        "FIRSTS": _member_rows(base, stats["first_members"]),
        "CATS": _cat_rows(cats),
        "VIEWED": _topic_rows(base, viewed, "views", _t("צפיות")),
        "REPLIED": _topic_rows(base, replied, "posts", _t("תגובות")),
        "POSTERS": _people_rows(base, posters, _t("פוסטים")),
        "OLDEST": _topic_rows(base, oldest, "views", _t("צפיות"), bars=False),
        "LOCALNOTE": _esc(_local_note(local or {})),
        "WORST": _rep_rows(base, (local or {}).get("worst") or [], True),
        "BEST": _rep_rows(base, (local or {}).get("best") or [], False),
        "RATIO": _ratio_rows(base, (local or {}).get("per_post") or []),
        "YEARS": _year_rows((local or {}).get("by_year") or []),
        "GONE": _gone_rows(base, (local or {}).get("gone") or []),
        "LIMITS": limits,
    })


def _page(heading, subtitle, compare_html, sections_html, requests):
    foot = "%s%d%s" % (_t("הופק מ-"), requests, _t(" בקשות בלבד"))
    return _fill(i18n.translate_template(_TEMPLATE, _TPL_EN), {
        "TITLE": _esc(_t(REPORT_NAME)),
        "HEADING": _esc(heading),
        "FORUM": _esc(subtitle),
        "COMPARE": compare_html,
        "SECTIONS": sections_html,
        "FOOT": _esc(foot),
    })


def _build_html(stats, cats, viewed, replied, posters, oldest, failed, local=None):
    """דוח של פורום אחד — שלד עם רשת אחת בתוכו."""
    grid = _build_grid(stats, cats, viewed, replied, posters, oldest, failed, local)
    return _page("📇 " + _t(REPORT_NAME), stats["base"], "", grid, stats["requests"])
