# -*- coding: utf-8 -*-
"""
Chazonishnik — ניתוח פעילות משתמש בפורום NodeBB.
מבוסס על הסקריפט המקורי, מותאם לשימוש בתוך Tik-Nick:
פונקציה אחת analyze_user(...) שמחזירה HTML (ואופציונלית שומרת קובץ).
משתמש ב-urllib בלבד (ללא תלות ב-requests) כדי לא להוסיף תלויות.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures
from datetime import datetime
import i18n
import net
import html
import logging

DEFAULT_BASE = "https://mitmachim.top"
# 12 בקשות במקביל בלי כל השהיה היו מפציצות פורום קטן באלפי בקשות בדקה —
# הסורק ממתין 0.6 שניות בין עמודים ו-Stinknik 0.4, ואין סיבה שהניתוח יהיה גס יותר.
CONCURRENCY = 4
DETAIL_DELAY = 0.15
PAGE_DELAY = 0.5      # בין עמודי היסטוריה — כמו בסורק ובסטינקניק          # השהיה קצרה בכל בקשת פרטים (per worker)
MAX_PAGES = 1500
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _get_json(url, cookie=None, timeout=15, retries=3):
    """GET JSON עם ניסיונות חוזרים וכיבוד Retry-After (429)."""
    last = None
    for attempt in range(1, retries + 1):
        # ה-Request נבנה מחדש בכל ניסיון: urllib *משנה* אותו כשיש פרוקסי
        # (set_proxy), וניסיון חוזר על אותו אובייקט יוצא בטקסט גלוי לפורט 80.
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _UA)
        req.add_header("Accept", "application/json")
        if cookie:
            val = cookie if cookie.startswith("express.sid=") else f"express.sid={cookie}"
            req.add_header("Cookie", val)
        try:
            with net.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                ra = e.headers.get("Retry-After")
                time.sleep(min(int(ra) if (ra and ra.isdigit()) else attempt * 3, 30))
                last = e
                continue
            if e.code in (401, 403, 404):
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(attempt * 1.5)
    raise last


def _user_slug_variations(username):
    """מחזיר וריאציות סבירות של slug — NodeBB משתמש במקפים במקום רווחים."""
    u = username.strip()
    variations = []
    def add(v):
        if v and v not in variations:
            variations.append(v)
    add(u.replace(" ", "-"))          # רווח → מקף (הנפוץ ב-NodeBB)
    add(u.lower().replace(" ", "-"))  # אותיות קטנות
    add(u)                            # כמו שהוא
    add(u.replace(" ", ""))           # בלי רווחים
    return variations


def _fetch_user(base, username, cookie):
    """מנסה כמה וריאציות עד שנמצא משתמש. מחזיר (uid, slug, data)."""
    last_err = None
    u = username.strip()
    # קודם: חיפוש לפי username מדויק (מטפל ברווחים באופן טבעי)
    try:
        data = _get_json(f"{base}/api/user/username/{urllib.parse.quote(u)}", cookie=cookie)
        if isinstance(data, dict) and (data.get("uid") or data.get("username")):
            slug = data.get("userslug") or u.replace(" ", "-")
            return data.get("uid"), slug, data
    except Exception as e:
        last_err = e
    # אחר כך: וריאציות slug
    for slug in _user_slug_variations(username):
        try:
            data = _get_json(f"{base}/api/user/{urllib.parse.quote(slug)}", cookie=cookie)
            if isinstance(data, dict) and (data.get("uid") or data.get("username")):
                return data.get("uid"), (data.get("userslug") or slug), data
        except Exception as e:
            last_err = e
            continue
    raise last_err or Exception("לא נמצא משתמש")


def _scan_posts(base, slug, cookie, progress=None, cancel_flag=None, max_posts=None,
                stats=None):
    all_posts = []
    page = 1
    while page <= MAX_PAGES:
        if cancel_flag is not None and cancel_flag.is_set():
            break
        url = f"{base}/api/user/{urllib.parse.quote(slug)}/posts?page={page}"
        try:
            data = _get_json(url, cookie=cookie)
        except Exception as e:
            # עצירה על שגיאה = דוח חלקי; מסמנים כדי לדווח למשתמש.
            # וגם רושמים ליומן: בלי זה המשתמש רואה "הדוח חלקי" ואי אפשר
            # לענות לו למה — היומן שקט לגמרי.
            logging.warning("Chazonishnik: page %s of %s failed: %s", page, slug, e)
            if stats is not None:
                if page > 1:
                    stats["stopped_early"] = True
                else:
                    # _fetch_user כבר הצליח והחזיר postcount — כלומר אנחנו
                    # *יודעים* שהמשתמש קיים ופעיל. בלי הסימון הזה כשל ברשת
                    # בעמוד הראשון דווח כ"לא נמצאו פוסטים (או שהמשתמש לא
                    # פעיל / העוגייה לא תקינה)" — אבחנה שגויה ששולחת את
                    # המשתמש לחפש עוגייה שאין בה שום בעיה.
                    stats["first_page_error"] = str(e)
            break
        posts = data.get("posts", []) if isinstance(data, dict) else []
        if not posts:
            break
        all_posts.extend(posts)
        if progress:
            progress({"phase": "scan", "page": page, "count": len(all_posts)})
        if max_posts and len(all_posts) >= max_posts:
            break
        page += 1
        # לולאת העמודים הזו רצה בלי שום השהיה, בזמן שהסורק ממתין 0.6 שניות
        # ו-Stinknik 0.4 — כלומר דווקא הכלי שמושך את כל היסטוריית הפוסטים של
        # משתמש היה הכי אגרסיבי מבין השלושה. אלה התקנות NodeBB קטנות.
        time.sleep(PAGE_DELAY)
    uniq = {p.get("pid"): p for p in all_posts if p.get("pid")}
    posts = list(uniq.values())
    if max_posts and len(posts) > max_posts:
        posts = posts[:max_posts]
    return posts


# שמות הימים נכנסים לדוח כנתונים (תוויות ציר), ולכן מתורגמים כאן ולא בתבנית
_DAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]

# מילים קצרות שאסור להן להיכנס לקטלוג המשותף — "שני" הוא גם יום וגם המספר,
# ו-translate_template היה הופך "משתמש שני" ל-"משתמש Monday".
_DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_LOCAL_EN = {"תגובה": "Reply"}

# חיבורים קצרים בתוך ה-JS של הדוחות. הם לא יכולים לשבת בקטלוג המשותף —
# "מול" או "פי " היו נדרסים בכל מקום בתוכנה — אבל בתבניות האלה הם חד-משמעיים.
_TPL_EN = {
    "פוסטים": "Posts",
    # שלושת המקטעים החדשים. הטקסטים חיים בתוך ה-<script>, ולכן הם אינם
    # מפתחות בקטלוג המשותף — הם מתורגמים כאן, בתבנית של המודול הזה בלבד.
    "👥 עם מי הוא מדבר": "👥 Who they talk to",
    "— תגובה בלי אזכור מפורש אינה נראית לניתוח.":
        "— a reply with no explicit mention is invisible to this analysis.",
    "הקרובים אליו": "Closest to him",
    "מעריצים שקטים": "Quiet admirers",
    "פוסטים שלו בשרשורים של ": "of his posts in threads by ",
    " לייקים, אבל שמות המצביעים דורשים עוגיית התחברות":
        " upvotes, but the voter names need a login cookie",
    "אין מידע על פותחי השרשורים": "No information about who opened the threads",
    "אין מידע על קטגוריות בפוסטים שנסרקו": "No category information in the scanned posts",
    " אנשים שונים · ובשרשורים שהוא עצמו פתח: ": " different people · and in threads he opened himself: ",
    "אף פוסט שנסרק אינו תגובה לפוסט מסוים": "No scanned post is a reply to a specific post",
    " קטגוריות שונות בסך הכול": " different categories in total",
    "הוא זה שהתחיל את השיחה": "He is the one who started the conversation",
    "הצטרף לשיחה קיימת": "Joined an existing conversation",
    "פתח שרשורים": "Opened threads",
    "הגיב בשרשור של מישהו": "Replied in a thread by someone else",
    "תגובות ישירות שלו אליו": "direct replies from him",
    "לא הצלחנו לזהות למי הוא ענה": "Could not identify whom he replied to",
    "אף פוסט שנסרק לא קיבל תגובה ישירה": "No scanned post received a direct reply",
    " תגובות שהפוסטים שלו עוררו · ממוצע ": " replies his posts drew · average ",
    " לפוסט</div>": " per post</div>",
    "מבוסס על ": "Based on ",
    " התגובות (": " of the replies (",
    ") — האחרונות שבהן. ": ") — the most recent ones. ",
    "זה מה שמראה עם מי הוא מדבר ": "That shows whom he is talking to ",
    "עכשיו": "right now",
    " תגובות</div>": " replies</div>",
    "לא נמצאו שמות מצביעים": "No voter names were found",
    "בפוסטים שנסרקו": "in the scanned posts",
    "ומולם ": "and against them ",
    " דיסלייקים בפוסטים שנסרקו": " downvotes in the scanned posts",
    "בלי עוגיית התחברות אין שמות של מי שעשה לייק, ולכן לא מוצגת הקבוצה השלישית": "Without a login cookie there are no voter names, so the third group is not shown",
    " תגובות לכל פוסט": " replies per post",
    "% מהפוסטים שנסרקו הם תגובות": "% of the scanned posts are replies",
    " פוסטים שנסרקו)": " posts scanned)",
    "אף פוסט שנסרק אינו תגובה לאדם אחר":
        "No scanned post is a reply to another person",
    "כל התגובות שנפתרו היו לפוסטים שלו עצמו":
        "Every resolved reply was to one of his own posts",
    "שמות המצביעים ידועים רק לחלק מהלייקים, ולכן לא מוצגת הקבוצה של מי שלא החזיר לייק":
        "The voter names are known for only part of the upvotes, so the group of those who did not upvote back is not shown",
    "הלייקים נספרו, אבל שמות המצביעים לא הגיעו":
        "The upvotes were counted, but the voter names did not arrive",
    "מבוסס על ": "Based on ",
    " הלייקים — לשאר לא הגיעו שמות": " of the upvotes — no names arrived for the rest",
    "בשרשורים של מי הוא חי": "Whose threads he lives in",
    "מה הצית שיחה": "What sparked conversation",
    "למי הוא באמת עונה": "Whom he actually answers",
    "איפה בפורום הוא חי": "Where in the forum he lives",
    "יוזם או מגיב": "Starter or responder",
    "הלייקים נספרו, אבל שמות המצביעים דורשים עוגיית התחברות":
        "The upvotes were counted, but the voter names need a login cookie",
    " · תגובות ישירות לפוסט הזה": " · direct replies to this post",
    "% מהפוסטים שלו הם תגובות": "% of his posts are replies",
    ", ולא סיכום של כל השנים.": ", not a summary of all the years.",
    "מזכיר אותם, ולא הגיע מהם לייק": "He mentions them, and no upvote came back",
    "נספר רק @אזכור או ציטוט — כפי שהפורום עצמו מסמן אותם. תגובה בשרשור בלי תיוג אינה נספרת, וזו הדרך הנפוצה לדבר כאן: אפשר לשוחח עם מישהו מאות פעמים ולהופיע כאן עם מספר חד-ספרתי.":
        "Only an @mention or a quote is counted — as the forum itself marks them. A reply in a thread without tagging is not counted, and that is the common way to talk here: you can converse with someone hundreds of times and appear here with a single-digit number.",
    "אזכורים בפוסטים שנסרקו": "mentions in the scanned posts",
    "נספר רק @אזכור או ציטוט — כפי שהפורום עצמו מסמן אותם. **תגובה בשרשור בלי תיוג אינה נספרת**, וזו הדרך הנפוצה לדבר כאן: אפשר לשוחח עם מישהו מאות פעמים ולהופיע כאן עם מספר חד-ספרתי.":
        "Only an @mention or a quote is counted — as the forum itself marks them. **A reply in a thread without tagging is not counted**, and that is the common way to talk here: you can converse with someone hundreds of times and appear here with a single-digit number.",
    "לא נמצאו אזכורים או לייקים בפוסטים שנסרקו":
        "No mentions or upvotes were found in the scanned posts",
    "הזכיר ": "mentioned ",
    "הזכיר": "mentioned",
    " · לייקים ": " · upvotes ",
    "עושים לו לייק, והוא לא מזכיר אותם": "They upvote him; he never mentions them",
    "פניות בפוסטים שנסרקו": "approaches in the scanned posts",
    "לא נמצאו אזכורים או ציטוטים בפוסטים שנסרקו":
        "No mentions or quotes were found in the scanned posts",
    "הקרובים אליו": "Closest to them",
    " — הוא פונה אליהם, והם מחזירים בלייקים":
        " — they reach out, and get likes back",
    "פונה אליהם, ובפוסטים שנסרקו לא הגיע מהם לייק":
        "They reach out, and in the scanned posts no like came back",
    "מעריצים שקטים": "Silent admirers",
    " — עושים לו לייקים, ולא נמצא שפנה אליהם":
        " — they give likes, and no approach was found",
    "⚠️ ספירת הלייקים הייתה חלקית, ולכן לא מוצגת קבוצת \"לא הגיע מהם לייק\"":
        "⚠️ The like counts were incomplete, so the \"no like came back\" group is hidden",
    "הכול מתוך הפוסטים שנסרקו בלבד. אזכור נספר כשהוא מופיע בטקסט (@שם או ציטוט) — תגובה בלי אזכור מפורש אינה נראית לניתוח.":
        "All of this covers the scanned posts only. A mention counts when it appears in the text (@name or a quote) — a reply with no explicit mention is invisible to the analysis.",
    " פניות · ": " approaches · ",
    " פניות": " approaches",
    " לייקים": " likes",
    "לא נמצאו הפסקות בפוסטים שנסרקו (הסריקה חלקית)":
        "No breaks were found in the scanned posts (the scan is partial)",
    " פוסטים לא נכללו — ספירת הלייקים שלהם נכשלה":
        " posts were excluded — their like counts failed",
    "נסרקו ": "scanned ",
    "הפער הוא פוסטים שהסריקה אינה יכולה לקרוא: מחוקים, או בקטגוריות שדורשות הרשאה. כל שאר הנתונים בדוח מחושבים מהפוסטים שנסרקו.":
        "The gap is posts the scan cannot read: deleted, or in categories that require permission. Everything else in this report is computed from the posts that were scanned.",
    "ספירת הלייקים נכשלה בכל הפוסטים שנסרקו":
        "The like counts failed for every scanned post",
    "ספירת הלייקים נכשלה ב-": "Like counting failed for ",
    " מתוך ": " of ",
    " פוסטים": " posts",
    "ספירת הלייקים נכשלה — אי אפשר לדעת מי אהב את הפוסטים":
        "Like counting failed — there is no way to know who liked the posts",
    "לא התקבלו לייקים על הפוסטים שנסרקו":
        "No likes were received on the scanned posts",
    "ספירת הלייקים נכשלה — אי אפשר לדרג פוסטים":
        "Like counting failed — posts cannot be ranked",
    "💤 תקופות שקט": "💤 Periods of silence",
    "🔥 מתי הוא הכי חד": "🔥 When they are at their sharpest",
    "💬 כמה הוא נשאר בשרשור": "💬 How long they stay in a thread",
    " — מאז ": " — since ",
    "אין מספיק פוסטים כדי למדוד שתיקות":
        "Not enough posts to measure periods of silence",
    "לא היו הפסקות של חודש ומעלה — כתיבה רציפה":
        "No breaks of a month or more — continuous posting",
    "שותק כרגע": "Currently silent",
    " ימים": " days",
    "ספירת הלייקים הייתה חלקית בסריקה הזו, ולכן המקטע הזה מושבת":
        "The like counts were incomplete in this scan, so this section is disabled",
    "אין מספיק פוסטים בשעה מסוימת כדי להשוות":
        "Not enough posts in any single hour to compare",
    "השעה המוצלחת שלו": "Their best hour",
    "הכי פחות — ": "Weakest — ",
    "הממוצע הכללי שלו": "Their overall average",
    " לייקים לפוסט": " likes per post",
    "שרשורים שבהם כתב פעם אחת ועבר הלאה":
        "Threads where they posted once and moved on",
    "שרשורים עם 2–4 הודעות שלו": "Threads with 2-4 of their posts",
    "שרשורים שבהם נשאר (5 ומעלה)": "Threads they stayed in (5 or more)",
    'סה"כ שרשורים שהשתתף בהם': "Total threads they took part in",
    " הודעות": " posts",
    "אין נתונים": "No data",
    "דק'": "min",
    "קצר": "Short", "בינוני": "Medium", "ארוך": "Long",
    'const dayOrder=["ראשון","שני","שלישי","רביעי","חמישי","שישי","שבת"];':
        'const dayOrder=["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];',
}

_CMP_EN = {
    'const DAYS = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"];':
        'const DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];',
    "השוואה:": "Comparison:",
    "מול": "vs.",
    "נסרקו ": "scanned ",
    " מתוך ": " of ",
    " פוסטים; השאר כנראה בקטגוריות שדורשות התחברות.":
        " posts; the rest are probably in categories that require signing in.",
    " כתב ": " wrote ",
    "פי ": "\u00d7", "יותר": "more",
    " פוסטים מ־": " posts compared with ",
    " (לפי סך הפוסטים בפורום)": " (based on the total post count in the forum)",
    " (מתוך מה שנסרק בלבד)": " (out of what was scanned only)",
    " מילים לפוסט מול ": " words per post vs. ",
    " ב־": " at ",
}



def _t(s):
    return _LOCAL_EN.get(s, s) if i18n.lang() == "en" else s



def _days():
    return _DAYS_EN if i18n.lang() == "en" else _DAYS_HE


# כל ספירת לייק בדוח מגיעה מבקשה אחת לפוסט. כשל שם נבלע בשקט, הפוסט נרשם עם
# likes=0, והמשתמש קיבל דוח שה-KPI הראשי שלו ("לייקים שהתקבלו") ופאנל
# "מקורות לייקים" כולו שקריים — מתחת לסיכום ירוק "נותחו N מתוך N פוסטים ✓".
# עכשיו סופרים את הכישלונות, מדווחים עליהם, ואחרי סף מפסיקים לנסות: לירות
# עוד שלושה ריטריי לכל פוסט מול שרת שמגביל קצב זה בדיוק מה שלא עושים כאן.
_VOTE_FAIL_GIVEUP = 10
_vote_lock = threading.Lock()
_vote_fails = {"n": 0}


# NodeBB מרנדר גם אזכור (@שם) וגם כותרת ציטוט ("@שם said in ...") כטקסט
# שמתחיל ב-@. לכן ביטוי אחד תופס את שניהם — בלי אף בקשה נוספת.
#
# הכלל זהה לזה שבשדות התיוג בממשק (ראו TAG_OPEN ב-app.js), ומאותה סיבה:
# @ באמצע מילה הוא כתובת מייל, לא אזכור. `beni@gmail.com` היה מייצר
# "gmail.com" כאיש קשר.
_MENTION_RX = re.compile(
    r'@([0-9A-Za-z\u0590-\u05ff_][0-9A-Za-z\u0590-\u05ff._-]{1,30})')
# \u05d4\u05db\u05dc\u05dc \u05d0\u05d9\u05e0\u05d5 "@ \u05e4\u05d5\u05ea\u05d7 \u05de\u05d9\u05dc\u05d4" \u05d0\u05dc\u05d0 "\u05de\u05d4 \u05e9\u05dc\u05e4\u05e0\u05d9\u05d5 \u05d0\u05d9\u05e0\u05d5 \u05e0\u05e8\u05d0\u05d4 \u05db\u05de\u05d5 \u05de\u05d9\u05d9\u05dc". \u05d1\u05e2\u05d1\u05e8\u05d9\u05ea \u05d5'
# \u05d4\u05d7\u05d9\u05d1\u05d5\u05e8 \u05e0\u05d3\u05d1\u05e7\u05ea \u05dc\u05de\u05d9\u05dc\u05d4 \u2014 "\u05d5@\u05e9\u05e8\u05d4" \u05d4\u05d5\u05d0 \u05d0\u05d6\u05db\u05d5\u05e8 \u05dc\u05d2\u05de\u05e8\u05d9 \u05ea\u05e7\u05d9\u05df, \u05d5\u05d4\u05db\u05dc\u05dc \u05d4\u05de\u05d7\u05de\u05d9\u05e8 \u05e4\u05e1\u05e4\u05e1 \u05d0\u05d5\u05ea\u05d5.
# \u05de\u05d4 \u05e9\u05db\u05df \u05d7\u05d9\u05d9\u05d1 \u05dc\u05d4\u05d9\u05e4\u05e1\u05dc \u05d4\u05d5\u05d0 `beni@gmail.com`, \u05d5\u05e9\u05dd \u05dc\u05e4\u05e0\u05d9 \u05d4-@ \u05ea\u05de\u05d9\u05d3 \u05d9\u05e9 \u05ea\u05d5 \u05dc\u05d8\u05d9\u05e0\u05d9.
_EMAILISH_BEFORE = re.compile(r"[0-9A-Za-z._%+-]")
# קטע כתובת שנמשך עד ה-@ בלי רווח — youtube.com/@handle וכדומה
_URLISH_BEFORE = re.compile(r"(?:https?://|www\.)\S*$", re.I)
# שמות שאינם אדם
_NOT_A_PERSON = {"everyone", "here", "all", "channel", "כולם"}
_LOOKS_LIKE_DOMAIN = re.compile(r"\.[a-z]{2,}$", re.I)
MAX_MENTIONS_PER_POST = 8


# ── "עם מי הוא מדבר" — הוסר מ-0.9.0, והקוד נשמר לגרסה הבאה ───────────────
# הרעיון נכון: להצליב את מי שהמשתמש פונה אליו מול מי שעושה לו לייקים. חצי
# ממנו ודאי — `voters` מגיע כרשימה מפורשת. החצי השני, "את מי הוא מזכיר",
# נחלץ מתוך ה-HTML המרונדר של הפוסט, **ושם התחיל לנחש**:
#
#   • גרסה ראשונה השוותה slug מול שם תצוגה ולא התאימה אף שם. בנימין תפס.
#   • גרסה שנייה הסירה גופי ציטוט — וייתכן שדווקא מחקה את הפניות האמיתיות,
#     כי בפורומים האלה עונים בציטוט ולא ב-@.
#
# שתי טעויות באותו מקום, ושתיהן נבעו מאותו דבר: אין כאן דגימה של HTML
# אמיתי מהפורום, רק הנחות עליו. הפונקציות והבדיקות נשארות; הכרטיס יחזור
# כשיהיה מול מה לאמת אותו.

_BLOCKQUOTE_RX = re.compile(r"<blockquote[^>]*>.*?</blockquote>", re.I | re.S)
_BQ_TAG_RX = re.compile(r"</?blockquote[^>]*>", re.I)
# כותרת הציטוט של NodeBB ("@שם said in ...") היא כן פנייה שלו — היא נשמרת.
_QUOTE_HEAD_RX = re.compile(
    r"<blockquote[^>]*>(?P<head>.{0,200}?)(?:</p>|</blockquote>)", re.I | re.S)


def _drop_blockquotes(s):
    """
    מסיר בלוקי ציטוט כולל מקוננים, בסריקה אחת עם מונה עומק.

    רגקס לא-חמדני נכשל כאן: על ציטוט בתוך ציטוט הוא מתחיל בפותח החיצוני
    ונעצר בסוגר ה**פנימי**, ומשאיר את שארית הציטוט החיצוני כאילו הנבדק
    כתב אותה. ציטוט-של-ציטוט הוא המצב הרגיל בשרשור.
    """
    out, i, depth = [], 0, 0
    for m in _BQ_TAG_RX.finditer(s):
        if depth == 0:
            out.append(s[i:m.start()])
        if m.group(0).lower().startswith("</"):
            depth = max(0, depth - 1)
            if depth == 0:
                i = m.end()
        else:
            depth += 1
    if depth == 0:
        out.append(s[i:])
    return " ".join(out)


def _strip_quotes(raw_html):
    """
    מסיר את **גוף** הציטוטים ומשאיר רק את שורת הכותרת שלהם.

    ציטוט הוא טקסט שאדם אחר כתב. כל @ שבתוכו שייך לו, לא למשתמש הנבדק —
    ובלי ההפרדה הזו אנשים שמעולם לא היה איתם קשר נספרו כ"פניות" שלו, ומשם
    נחתו ברשימה "פונה אליהם ולא הגיע מהם לייק". מה שכן נשמר היא השורה
    "@פלוני said in ..." שמכניס NodeBB, כי היא אכן מציינת את מי הוא ציטט.
    גם צורת המרקדאון (שורה שמתחילה ב->) מטופלת.
    """
    s = raw_html or ""
    # **רק כותרת הציטוט החיצוני** היא פנייה שלו. בציטוט-של-ציטוט, הכותרת
    # הפנימית ("@פלוני said in") שייכת למי שהוא ציטט, לא לו — וספירתה
    # זקפה לו פניות לאנשים שמעולם לא פנה אליהם.
    heads = []
    depth = 0
    for m in _BQ_TAG_RX.finditer(s):
        if m.group(0).lower().startswith("</"):
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            h = _QUOTE_HEAD_RX.match(s, m.start())
            if h:
                heads.append(h.group("head"))
        depth += 1
    s = _drop_blockquotes(s)
    lines = [ln for ln in s.split(chr(10))
             if not ln.lstrip().startswith(">") and not ln.lstrip().startswith("&gt;")]
    return chr(10).join(lines) + " " + " ".join(heads)


def _mentions_in(text, me=""):
    """מי מוזכר או מצוטט בפוסט אחד. מוחזר בלי כפילויות ובלי המשתמש עצמו."""
    out = []
    txt = text or ""
    low_me = (me or "").strip().lower()
    for m in _MENTION_RX.finditer(txt):
        i = m.start()
        # התו שלפני ה-@ הוא מה שמכריע: אות לטינית או ספרה = כתובת מייל.
        if i > 0 and _EMAILISH_BEFORE.match(txt[i - 1]):
            continue
        # @ בתוך כתובת אינטרנט אינו חבר בפורום. קישור ליוטיוב או ל-X הפך
        # את ה-handle שם ל"אדם שהוא פונה אליו", ומשם לרשימה השלילית.
        before = txt[max(0, i - 90):i]
        if _URLISH_BEFORE.search(before):
            continue
        name = m.group(1).rstrip("._-")
        if not name or _LOOKS_LIKE_DOMAIN.search(name):
            continue
        if name.lower() == low_me or name in out:
            continue
        if name.lower() in _NOT_A_PERSON:
            continue
        out.append(name)
        if len(out) >= MAX_MENTIONS_PER_POST:
            break
    return out


def _reset_vote_stats():
    with _vote_lock:
        _vote_fails["n"] = 0


def _vote_failures():
    with _vote_lock:
        return _vote_fails["n"]


# ── האזכורים, בפעם השלישית — והפעם מתוך מה שהפורום באמת שולח ────────────
# הכרטיס "עם מי הוא מדבר" נמשך מ-0.9.0 אחרי ששתי גרסאות שלו נתנו תוצאות
# שגויות אצל בנימין. הסיבה התבררה רק כשהסתכלתי סוף סוף בתוכן אמיתי:
# **`content` הוא HTML, ובאזכור ה-@ והשם מופרדים בתגית.** NodeBB שולח
#
#   <a class="plugin-mentions-user" href="/user/%D7%A6%D7%95%D7%9C-%D7%92%D7%90%D7%94"
#      aria-label="Profile: צול-גאה">@<bdi>צול-גאה</bdi></a>
#
# (שלושת המקומות נושאים את ה-**slug**; שם התצוגה אינו בסימון האזכור כלל, והוא מגיע מרשימת המצביעים.)
#
# ולכן רגקס שמחפש שם **מיד אחרי** ה-@ לא מוצא כלום. נמדד על החשבון של
# בנימין: 0 אזכורים ב-26 פוסטים שכולם מזכירים מישהו, ובהם `צול-גאה` —
# בדיוק האדם שהוא אמר שפנה אליו והכרטיס טען שלא.
#
# החילוץ הזה אינו ניחוש: ה-href הוא ה-slug עצמו, וזה **אותו מפתח** שרשימת
# המצביעים מפתחת לפיו. אין כאן מיילים, אין ו' החיבור, ואין דומיינים.
_MENTION_A_RX = re.compile(
    r'<a[^>]+>', re.I)
_MENTION_CLASS_RX = re.compile(r'class="[^"]*plugin-mentions-user', re.I)
_MENTION_HREF_RX = re.compile(r'href="[^"]*?/user/([^"#?]+)"', re.I)
_ARIA_NAME_RX = re.compile(r'aria-label="Profile:\s*([^"]+)"', re.I)


def _mentions_from_html(raw_html, me_slug=""):
    """
    מי מוזכר בפוסט — לפי העוגנים ש-NodeBB עצמו מסמן.

    מחזיר [(slug, display)] בלי כפילויות ובלי המשתמש עצמו. `_strip_quotes`
    מופעל קודם, כדי שאזכור שיושב **בתוך גוף ציטוט** לא ייזקף לו: הטקסט הזה
    נכתב על ידי אדם אחר. שורת הכותרת של הציטוט ("@פלוני said in") כן נשמרת,
    כי היא מציינת את מי הוא ציטט.
    """
    body = _strip_quotes(raw_html or "")
    out, seen = [], set()
    low_me = (me_slug or "").strip().lower()
    for m in _MENTION_A_RX.finditer(body):
        tag = m.group(0)
        # סדר המאפיינים אינו מובטח, וההתקנה יכולה לשבת בתת-תיקייה
        if not _MENTION_CLASS_RX.search(tag):
            continue
        href = _MENTION_HREF_RX.search(tag)
        if not href:
            continue
        slug = urllib.parse.unquote(href.group(1)).strip()
        key = _norm_key(slug)
        if not key or key == _norm_key(low_me) or key in seen:
            continue
        seen.add(key)
        nm = _ARIA_NAME_RX.search(tag)
        out.append((slug, _unesc(nm.group(1)).strip() if nm else slug.replace("-", " ")))
        if len(out) >= MAX_MENTIONS_PER_POST:
            break
    return out


def _norm_key(s):
    """
    מפתח אחד לשני הצדדים.

    NodeBB מחזיר באזכור את ה-**slug** (`צול-גאה`) וברשימת המצביעים את **שם
    התצוגה** (`צול גאה`). השוואה ישירה ביניהם לא מתאימה אף שם לאף שם, ומכאן
    יצאו שתי הקבוצות השליליות השקריות שבנימין דיווח עליהן.
    """
    return re.sub(r"[\s_\-]+", "", _unesc(str(s or ""))).strip().lower()


def _fetch_detail(base, cookie, post, me=""):
    try:
        time.sleep(DETAIL_DELAY)   # נימוס: 4 עובדים × 0.15s ≈ 27 בקשות לשנייה לכל היותר
        pid = post["pid"]
        raw = post.get("content", "") or ""
        # ציטוט הוא טקסט שאדם אחר כתב. עד כאן הוא נספר כמילים **שלו**,
        # וניפח את "מילים שנכתבו", "זמן קריאה" ואת גרף אורך התוכן. אותו
        # `_strip_quotes` שכבר משמש לאזכורים משמש עכשיו גם כאן.
        clean = re.sub(r"<[^<]+?>", "", _strip_quotes(raw))
        words = len(clean.split())
        # `me` הוא ה-slug (ראו הקריאה ב-_collect), וזה בדיוק מה שצריך כאן:
        # האזכור נושא slug, ולכן ההשוואה נעשית באותה מטבע.
        mentions = _mentions_from_html(raw, me)
        # ── ספירת הלייקים מגיעה **חינם עם הפוסט** ────────────────────
        # `upvotes` יושב על אובייקט הפוסט. נמדד מול 36 פוסטים של בנימין:
        # סכום השדה הזה = 41, ובדיוק אותם 41 שנספרו ב-36 בקשות הצבעה עם
        # עוגייה. כלומר הדוח שרף ~1,800 בקשות בשביל מספר שכבר היה בידיים,
        # והציג "—" כשלא הייתה עוגייה.
        # הבקשה הנוספת נחוצה רק ל**שמות** של המצביעים, ובלי עוגייה היא
        # מחזירה 403 — ולכן היא לא נשלחת כלל.
        likes = int(post.get("upvotes") or 0)
        downs = int(post.get("downvotes") or 0)
        upvoters = []
        with _vote_lock:
            give_up = _vote_fails["n"] >= _VOTE_FAIL_GIVEUP
        votes_ok = False
        if not cookie:
            give_up = True          # בלי עוגייה אין שמות, ואין טעם לשאול
        if not give_up and likes:
            try:
                v = _get_json(f"{base}/api/v3/posts/{pid}/voters", cookie=cookie, timeout=10)
                upvoters = (v.get("response", {}) or {}).get("upvoters", []) or []
                votes_ok = True
            except Exception as e:
                with _vote_lock:
                    _vote_fails["n"] += 1
                    first = _vote_fails["n"] == 1
                if first:
                    logging.warning("Chazonishnik: voters fetch failed for pid %s: %s", pid, e)
        ts = post.get("timestamp") or 0
        dt = datetime.fromtimestamp(ts / 1000) if ts else datetime.now()
        return {
            "pid": pid,
            "title": _unesc((post.get("topic", {}) or {}).get("title", "")) or _t("תגובה"),
            "tid": (post.get("topic") or {}).get("tid"),
            "ts": ts,
            "date": dt.strftime("%Y-%m-%d"),
            "hour": dt.hour,
            # המספר הוא הנתון; השם הוא תצוגה. קודם נשמר כאן שם מתורגם,
            # ואם השפה התחלפה באמצע ריצה החיפוש החוזר נכשל וגרף הימים יצא ריק.
            "dow": dt.weekday(),
            "day": _days()[dt.weekday()],
            "month": dt.strftime("%Y-%m"),
            # `likes` הוא המספר האמיתי מהפוסט; `votes_ok` אומר אם יש לנו
            # גם **שמות**. הפרדה בין השניים היא כל העניין.
            "likes": likes,
            "down": downs,
            "voters": upvoters,
            "votes_ok": votes_ok,
            # ── מה שכבר הגיע עם הפוסט, ואיש לא נגע בו ──────────────────
            "is_main": bool(post.get("isMainPost")),
            "replies": int(post.get("replies") or 0),
            "to_pid": post.get("toPid") or None,
            "topic_uid": (post.get("topic") or {}).get("uid"),
            "topic_posts": int((post.get("topic") or {}).get("postcount") or 0),
            "cat": _unesc((post.get("category") or {}).get("name") or ""),
            # [{k, name, slug}] — k הוא המפתח המנורמל, וגם צד המצביעים
            # ייבנה לפיו. שני הצדדים חייבים להיות באותה מטבע.
            "mentions": [{"k": _norm_key(sl), "name": nm, "slug": sl}
                         for sl, nm in mentions],
            "words": words,
        }
    except Exception:
        return None


# ── למי הוא באמת ענה ─────────────────────────────────────────────────────
# בפורום הזה **מגיבים בשרשור בלי לתייג**: נמדד על בנימין — 85% מהפוסטים
# שלו הם תגובה לפוסט מסוים (`toPid`), אבל רק ~1,870 אזכורי @ בכל ההיסטוריה.
# כלומר "עם מי הוא מדבר" לפי @ בלבד מפספס את רוב השיחות.
#
# `toPid` הוא pid של פוסט האב, ו-`/api/v3/posts/<pid>` מחזיר את ה-uid שלו
# **בלי עוגייה**. זו בקשה אחת לתגובה.
#
# **למה זה מוגבל, ולמה זה נאמר בדוח**: כיסוי מלא אצל בנימין הוא 1,485
# בקשות. התקרה כאן חוסמת את זה, ולכן הכרטיס עובד על **התגובות האחרונות**
# ואומר במפורש כמה מתוך כמה. חלון אחרון אינו מדגם מוטה לטובת אף אחד — הוא
# פשוט מתאר את התקופה האחרונה, וזו גם השאלה המעניינת יותר: עם מי הוא
# מדבר **עכשיו**.
# (לפי שרשור זה דווקא יקר יותר: השרשורים שהוא פעיל בהם הם הארוכים, ו-20
#  מהם לבדם עולים 710 בקשות בגלל העימוד.)
REPLY_RESOLVE_MAX = 900


def _reply_layer(base, cookie, processed, my_uid, cancel_flag=None, progress=None):
    """
    פותר "למי הוא ענה" ומביא שמות תצוגה. מחזיר dict ל-meta, או None אם בוטל.

    **שני המסלולים חייבים לעבור כאן.** כשזה ישב בתוך `_collect` בלבד, הדוח
    שהמשתמש מפעיל (analyze_user) לא הריץ את זה כלל: הכרטיס הכריז "אף פוסט
    שנסרק אינו תגובה לפוסט מסוים" על מי שכל הפוסטים שלו תגובות, והשמות
    הוצגו כ-"uid 4211".
    """
    if progress:
        progress({"phase": "replies", "done": 0, "total": 0})
    r_ok, r_tot, r_req = _resolve_replies(
        base, cookie, processed, cancel_flag,
        lambda d, t: progress and progress({"phase": "replies", "done": d, "total": t}))
    if cancel_flag is not None and cancel_flag.is_set():
        return None

    # מונה הכיסוי חייב לספור בדיוק את מה שהשורות מציגות — כלומר בלי תגובות
    # של המשתמש לעצמו, שהכרטיס מסנן החוצה. אחרת נכתב "30 מתוך 30" מעל
    # רשימה שסכומה 20.
    r_ok = sum(1 for p in processed
               if p.get("reply_uid") and p.get("reply_uid") != my_uid)
    r_tot = sum(1 for p in processed
                if p.get("to_pid") and p.get("reply_uid") != my_uid)

    # שם תצוגה רק למי שבאמת יוצג. המיון כאן והמיון ב-JS חייבים לשבור שוויון
    # באותה צורה, אחרת שורה שמוצגת נשארת בלי שם ונופלת ל-"uid N".
    top_reply = _top_uids([p.get("reply_uid") for p in processed
                           if p.get("reply_uid") != my_uid], 10)
    top_host = _top_uids([p.get("topic_uid") for p in processed
                          if p.get("topic_uid") != my_uid], 10)
    names = _names_for_uids(base, cookie, list(dict.fromkeys(top_reply + top_host)),
                            limit=20)
    return {"names": {str(k): v for k, v in names.items()},
            "reply_resolved": r_ok, "reply_total": r_tot, "reply_requests": r_req}


def _top_uids(uids, n):
    """ה-uid-ים השכיחים ביותר, בלי ריקים."""
    c = {}
    for u in uids:
        if u:
            c[u] = c.get(u, 0) + 1
    # שובר שוויון לפי uid, כדי שהבחירה כאן והדירוג ב-JS יסכימו. בלי זה
    # `processed` מגיע בסדר as_completed (שרירותי) ושורה שמוצגת יכולה
    # להישאר בלי שם.
    return [u for u, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:n]]


def _resolve_replies(base, cookie, posts, cancel_flag=None, progress=None):
    """
    ממלא `reply_uid` בפוסטים שהם תגובה. מחזיר (resolved, total, requests).

    `posts` ממוין מהחדש לישן לפני החיתוך, כדי שהחלון יהיה "האחרונות".
    כישלון בודד אינו מפיל דבר — הפוסט פשוט נשאר בלי `reply_uid`.
    """
    targets = [p for p in posts if p.get("to_pid")]
    total = len(targets)
    if not total:
        return 0, 0, 0
    targets.sort(key=lambda p: -(p.get("ts") or 0))
    todo = targets[:REPLY_RESOLVE_MAX]

    cache, lock = {}, threading.Lock()
    stats = {"req": 0, "ok": 0}

    def one(p):
        if cancel_flag is not None and cancel_flag.is_set():
            return
        pid = p["to_pid"]
        with lock:
            hit = cache.get(pid, "miss")
        if hit != "miss":
            if hit:
                p["reply_uid"] = hit
                with lock:
                    stats["ok"] += 1
            return
        try:
            time.sleep(DETAIL_DELAY)
            d = _get_json("%s/api/v3/posts/%s" % (base, pid), cookie=cookie, timeout=10)
            body = (d or {}).get("response") or d or {}
            uid = body.get("uid")
        except Exception:                            # noqa: BLE001
            uid = None
        with lock:
            stats["req"] += 1
            cache[pid] = uid
            if uid:
                p["reply_uid"] = uid
                stats["ok"] += 1
            if progress and stats["req"] % 25 == 0:
                progress(stats["req"], len(todo))

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        list(ex.map(one, todo))
    return stats["ok"], total, stats["req"]


def _names_for_uids(base, cookie, uids, limit=12):
    """שם תצוגה ל-uid — רק למי שיוצג בפועל, ולכן בקשה אחת לכל שורה."""
    out = {}
    for uid in list(uids)[:limit]:
        try:
            time.sleep(DETAIL_DELAY)
            d = _get_json("%s/api/user/uid/%s" % (base, uid), cookie=cookie, timeout=10)
            out[uid] = {"name": _unesc(d.get("username") or ""),
                        "slug": _unesc(d.get("userslug") or "")}
        except Exception:                            # noqa: BLE001
            continue
    return out


def _collect(username, cookie, base, progress=None, cancel_flag=None,
             max_posts=None, label="", with_replies=False):
    """
    סורק ומעבד משתמש אחד ומחזיר (slug, uid, posts, meta) — או (None, None, None, err).
    הוצא מ-analyze_user כדי שההשוואה תשתמש בדיוק באותו מסלול, כולל ההשהיות
    והריטריי, ולא תיצור נתיב רשת שני.
    """
    scan_stats = {"stopped_early": False}
    try:
        uid, slug, udata = _fetch_user(base, username, cookie)
        postcount = int((udata or {}).get("postcount") or 0)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None, None, None, {"error": f"{label}נדרשת עוגייה תקינה (שגיאת הרשאה)"}
        return None, None, None, {"error": f"{label}שגיאת רשת: {e.code}"}
    except Exception as e:
        return None, None, None, {"error": f"{label}לא ניתן למצוא משתמש: {e}"}

    _reset_vote_stats()
    raw = _scan_posts(base, slug, cookie, progress=progress,
                      cancel_flag=cancel_flag, max_posts=max_posts, stats=scan_stats)
    if cancel_flag is not None and cancel_flag.is_set():
        return None, None, None, {"cancelled": True, "error": "בוטל"}
    if not raw:
        return None, None, None, {"error": f"{label}לא נמצאו פוסטים"}

    processed = []
    total = len(raw)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(_fetch_detail, base, cookie, x, slug): x for x in raw}
        for fut in concurrent.futures.as_completed(futs):
            if cancel_flag is not None and cancel_flag.is_set():
                for f2 in futs:
                    f2.cancel()
                return None, None, None, {"cancelled": True, "error": "בוטל"}
            r = fut.result()
            done += 1
            if progress and done % 15 == 0:
                progress({"phase": "analyze", "done": done, "total": total})
            if r:
                processed.append(r)
    # דוח ההשוואה אינו מציג את הכרטיסים האלה, ולכן אינו משלם עליהם.
    extra = (_reply_layer(base, cookie, processed, uid, cancel_flag, progress)
             if with_replies else {})
    if extra is None:
        return None, None, None, {"cancelled": True, "error": "בוטל"}

    processed.sort(key=lambda x: x["ts"])
    limited = bool(max_posts and len(raw) >= max_posts)
    meta = {
        "postcount": postcount, "limited": limited,
        "stopped_early": scan_stats["stopped_early"],
        # ספירת הלייקים מגיעה מבקשה נפרדת לכל פוסט. כשל שם החזיר 0 בשקט
        # ודוח ירוק ששיקר בדיוק ב-KPI הראשי שלו.
        "names_missing": _vote_failures(),
        "partial": scan_stats["stopped_early"] or (
            bool(postcount) and len(raw) < postcount * 0.95 and not limited),
    }
    meta.update(extra)
    return slug, uid, processed, meta


def _summarize(posts):
    """מדדים להשוואה. מחושב כאן ולא ב-JS כדי שהדוח השמור יהיה עצמאי."""
    hours = [0] * 24
    days = [0] * 7
    months = {}
    likes = words = 0
    cats = {}
    for p in posts:
        hours[p["hour"] % 24] += 1
        dow = p.get("dow")
        if dow is None:                      # דוח שנשמר בגרסה ישנה
            try:
                dow = _days().index(p.get("day"))
            except ValueError:
                dow = None
        if dow is not None:
            days[dow % 7] += 1
        months[p["month"]] = months.get(p["month"], 0) + 1
        likes += p.get("likes", 0)
        words += p.get("words", 0)
        t = (p.get("title") or "").strip()
        if t:
            cats[t] = cats.get(t, 0) + 1
    n = len(posts) or 1
    return {
        "posts": len(posts), "likes": likes,
        "avg_words": round(words / n, 1),
        "avg_likes": round(likes / n, 2),
        "hours": hours, "days": days, "months": months,
        "top_hour": hours.index(max(hours)) if posts else 0,
        "top_day": _days()[days.index(max(days))] if posts else "",
        "first": posts[0]["date"] if posts else "",
        "last": posts[-1]["date"] if posts else "",
        "top_topics": sorted(cats.items(), key=lambda kv: -kv[1])[:5],
    }


def analyze_pair(user_a, user_b, cookie, base_url=DEFAULT_BASE, progress=None,
                 save_path=None, cancel_flag=None, max_posts=None):
    """
    משווה שני משתמשים. הסריקות רצות **בזו אחר זו ולא במקביל** — שתי סריקות
    בו-זמנית מכפילות את העומס על אותו פורום, וכל מנגנון הנימוס כאן (השהיה בין
    עמודים, כיבוד Retry-After) בנוי סביב זרם אחד.
    כל משתמש מדווח על החלקיות שלו בנפרד: "א' הושלם, ב' נעצר" הוא מצב אמיתי.
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")
    out = []
    for i, uname in enumerate((user_a, user_b)):
        def _p(d, _i=i, _u=uname):
            if progress:
                progress({**d, "which": _i + 1, "of": 2, "user": _u})
        slug, uid, posts, meta = _collect(uname, cookie, base, progress=_p,
                                          cancel_flag=cancel_flag, max_posts=max_posts,
                                          label=f"{uname}: ")
        if slug is None:
            return {"ok": False, **meta}
        out.append({"slug": slug, "uid": uid, "posts": posts, "meta": meta,
                    "stats": _summarize(posts)})

    html = _build_compare_html(base, out[0], out[1])
    path = None
    if save_path:
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
            path = save_path
        except Exception:
            path = None
    return {"ok": True, "html": html, "path": path,
            "posts": out[0]["stats"]["posts"] + out[1]["stats"]["posts"],
            "compare": True,
            "a": {"user": out[0]["slug"], **out[0]["meta"], "posts": out[0]["stats"]["posts"]},
            "b": {"user": out[1]["slug"], **out[1]["meta"], "posts": out[1]["stats"]["posts"]}}


def _build_compare_html(base_url, a, b):
    payload = {
        "a": {"user": a["slug"], "stats": a["stats"], "meta": a["meta"]},
        "b": {"user": b["slug"], "stats": b["stats"], "meta": b["meta"]},
        "base": base_url,
    }
    # התבנית מתורגמת *לפני* הזרקת הנתונים — כך התרגום לא נוגע בתוכן מהפורום
    return _fill(i18n.translate_template(COMPARE_TEMPLATE, _CMP_EN), {
        "CHARTJS": _chartjs_tag(),
        "A": _esc(a["slug"]),
        "B": _esc(b["slug"]),
        "JSON_DATA": _json_for_script(payload),
    })


def analyze_user(username, cookie, base_url=DEFAULT_BASE, progress=None, save_path=None,
                 cancel_flag=None, max_posts=None):
    """
    מריץ ניתוח מלא ומחזיר dict: {ok, html, path, posts, error}
    progress(dict) — קריאה אופציונלית לעדכוני התקדמות.
    max_posts — הגבלת מספר הפוסטים הנסרקים (None = הכל).
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")
    scan_stats = {"stopped_early": False}
    try:
        my_uid, slug, _udata = _fetch_user(base, username, cookie)
        postcount = int((_udata or {}).get("postcount") or 0)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "error": "נדרשת עוגייה תקינה (שגיאת הרשאה)"}
        return {"ok": False, "error": f"שגיאת רשת: {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"לא ניתן למצוא משתמש: {e}"}

    _reset_vote_stats()
    raw_posts = _scan_posts(base, slug, cookie, progress=progress,
                            cancel_flag=cancel_flag, max_posts=max_posts, stats=scan_stats)
    if cancel_flag is not None and cancel_flag.is_set():
        return {"ok": False, "cancelled": True, "error": "בוטל"}
    if not raw_posts:
        if scan_stats.get("first_page_error"):
            return {"ok": False,
                    "error": "הפורום לא החזיר את הפוסטים ("
                             + str(scan_stats["first_page_error"]) + ")"}
        return {"ok": False, "error": "לא נמצאו פוסטים (או שהמשתמש לא פעיל / העוגייה לא תקינה)"}

    processed = []
    total = len(raw_posts)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(_fetch_detail, base, cookie, p, slug): p for p in raw_posts}
        for fut in concurrent.futures.as_completed(futs):
            if cancel_flag is not None and cancel_flag.is_set():
                for f in futs:
                    f.cancel()
                return {"ok": False, "cancelled": True, "error": "בוטל"}
            r = fut.result()
            done += 1
            if progress and done % 15 == 0:
                progress({"phase": "analyze", "done": done, "total": total})
            if r:
                processed.append(r)

    # שכבת התגובות והשמות — אותה שכבה בדיוק שמריץ מסלול ההשוואה
    extra = _reply_layer(base, cookie, processed, my_uid, cancel_flag, progress)
    if extra is None:
        return {"ok": False, "cancelled": True, "error": "בוטל"}

    processed.sort(key=lambda x: x["ts"])
    _limited = bool(max_posts and len(raw_posts) >= max_posts)
    meta = {
        "limited": _limited,
        "stopped_early": scan_stats["stopped_early"],
        "partial": scan_stats["stopped_early"] or (
            bool(postcount) and len(raw_posts) < postcount * 0.95 and not _limited),
        "postcount": postcount,
        "names_missing": _vote_failures(),
    }
    meta.update(extra)
    html = _build_html(slug, base, my_uid, processed, meta)

    path = None
    if save_path:
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
            path = save_path
        except Exception:
            path = None

    limited = bool(max_posts and len(raw_posts) >= max_posts)
    partial = scan_stats["stopped_early"] or (
        bool(postcount) and len(raw_posts) < postcount * 0.95 and not limited)
    return {"ok": True, "html": html, "path": path, "posts": len(processed),
            "postcount": postcount, "partial": partial, "limited": limited,
            "likes_incomplete": _vote_failures(),
            "stopped_early": scan_stats["stopped_early"]}


def _chartjs_tag():
    """
    Chart.js מוטמע בדוח כך שהקובץ השמור עובד גם בלי אינטרנט.
    הספרייה ארוזה ב-web/chart.umd.min.js (נכללת ב-EXE יחד עם שאר web/);
    אם הקובץ חסר משום מה — נופלים חזרה ל-CDN.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "web", "chart.umd.min.js")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return "<script>" + f.read() + "</script>"
    except Exception:
        return ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/'
                'dist/chart.umd.min.js"></script>')


def _unesc(v):
    """טקסט מהפורום מגיע מקודד ל-HTML — ראו scraper._txt."""
    s = "" if v is None else str(v)
    return html.unescape(s) if "&" in s else s


def _esc(s):
    """בריחת HTML — כל טקסט שמקורו בפורום אינו בטוח."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _json_for_script(obj):
    """
    JSON להטמעה בתוך <script>. json.dumps אינו מנטרל '</script>', ולכן כותרת נושא
    או שם משתמש עוינים היו יכולים לפרוץ מהבלוק. מנטרלים < > & כרצפי \\u.
    """
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _fill(template, values):
    """
    מעבר החלפה **יחיד** על מצייני המקום.

    שרשרת .replace סורקת מחדש טקסט שכבר הוזרק, ולכן כותרת פוסט מהפורום שמכילה
    __BASE_URL__ נבלעה והרסה את ה-<script> כולו — דוח שנראה שלם עם 0 פוסטים,
    בלי שום הודעת שגיאה (ה-iframe מוגן ואין בו קונסולה). זהו אותו דפוס שכבר
    נהוג ב-profile_sheet.build_sheet.
    """
    return re.sub(r"__([A-Z_]+)__", lambda m: values.get(m.group(1), m.group(0)),
                  template)


def _build_html(user_slug, base_url, my_uid, posts_data, meta=None):
    """
    meta נכנס לדוח כדי שהכרטיסים יידעו **על מה** הם מדברים.

    בלעדיו הדוח הסיק מסקנות מוחלטות מתוך חלון חלקי: "כתיבה רציפה" למי ששתק
    שנתיים (הסריקה מוגבלת מחזירה את הפוסטים החדשים בלבד), ו"0 לייקים"
    ככותרת ענקית כשספירת הלייקים בכלל נכשלה. שני מקרים שבהם הדוח נראה
    מושלם ואומר דבר שקרי.
    """
    m = dict(meta or {})
    return _fill(i18n.translate_template(HTML_TEMPLATE, _TPL_EN), {
        "CHARTJS": _chartjs_tag(),
        "USER": _esc(user_slug),
        "JSON_DATA": _json_for_script(posts_data),
        "MY_UID": _json_for_script(my_uid),
        "BASE_URL": _json_for_script(base_url),
        # זמן הסריקה קפוא בקובץ. בלעדיו "שותק כרגע" נמדד מול שעון הקורא,
        # וקובץ שנפתח חצי שנה אחרי הסריקה המציא שתיקה שלא הייתה.
        "SCANNED_AT": _json_for_script(
            datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
        "META": _json_for_script({
            "limited": bool(m.get("limited")),
            "stopped_early": bool(m.get("stopped_early")),
            "partial": bool(m.get("partial")),
            "postcount": int(m.get("postcount") or 0),
            "likes_incomplete": int(m.get("names_missing") or m.get("likes_incomplete") or 0),
            # שמות תצוגה ל-uid-ים שיוצגו בפועל, וכיסוי שכבת התגובות
            "names": dict(m.get("names") or {}),
            "reply_resolved": int(m.get("reply_resolved") or 0),
            "reply_total": int(m.get("reply_total") or 0),
        }),
    })


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ניתוח פעילות: __USER__</title>
__CHARTJS__
<style>
:root{--bg:#0f172a;--card-bg:#1e293b;--accent:#38bdf8;--text-main:#f1f5f9;--text-dim:#94a3b8}
body{background:var(--bg);color:var(--text-main);font-family:'Assistant',Arial,sans-serif;margin:0;padding:20px;overflow-x:hidden}
.container{max-width:1300px;margin:0 auto}
.header{text-align:center;margin-bottom:40px;padding:40px;background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border-radius:20px;border:1px solid #334155}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:20px}
.card{background:var(--card-bg);border-radius:16px;padding:24px;border:1px solid #334155;transition:all .3s ease}
.card:hover{transform:translateY(-5px);border-color:var(--accent)}
.col-3{grid-column:span 3}.col-4{grid-column:span 4}.col-6{grid-column:span 6}.col-8{grid-column:span 8}.col-12{grid-column:span 12}
.kpi-title{color:var(--text-dim);font-size:.9rem;font-weight:600;margin-bottom:8px}
.kpi-value{font-size:2.2rem;font-weight:800;color:#fff}
.kpi-sub{color:var(--text-dim);font-size:.78rem;margin-top:4px;min-height:1em}
h3{margin-top:0;font-size:1.1rem;color:var(--accent);margin-bottom:20px}
.list-container{max-height:300px;overflow-y:auto}
.list-item{display:flex;justify-content:space-between;align-items:center;padding:12px;border-bottom:1px solid #334155}
.list-item a{color:var(--text-main);text-decoration:none;font-weight:500}
.badge{background:#0c4a6e;color:#38bdf8;padding:4px 12px;border-radius:20px;font-weight:700;font-size:.85rem}
.grp{color:var(--accent);font-weight:700;font-size:.9rem;margin:14px 0 4px;padding-bottom:4px;border-bottom:1px solid #334155}
.grp:first-child{margin-top:0}
.list-item .sub{color:var(--text-dim,#94a3b8);font-size:.76rem;margin-top:2px}
.list-item .num{font-weight:700;color:#38bdf8;flex:none;margin-inline-start:10px}
.note-sm{color:var(--text-dim,#94a3b8);font-size:.74rem;margin-top:10px;line-height:1.5}
.empty{color:var(--text-dim,#94a3b8);font-size:.85rem;padding:10px 2px}
.chart-box{position:relative;height:300px;width:100%}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-thumb{background:#475569;border-radius:3px}
@media(max-width:900px){.col-3,.col-4,.col-6,.col-8{grid-column:span 12}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1 style="margin:0;font-size:2rem">📊 ניתוח פעילות: __USER__</h1>
<p style="color:var(--text-dim);margin-top:10px">ניתוח נתונים מעמיק של פעילות המשתמש</p>
</div>
<div class="grid">
<div class="card col-3"><div class="kpi-title">סה"כ פוסטים</div><div class="kpi-value" id="stat-posts">0</div><div class="kpi-sub" id="stat-posts-sub"></div></div>
<div class="card col-3"><div class="kpi-title">לייקים שהתקבלו</div><div class="kpi-value" id="stat-likes" style="color:#10b981">0</div></div>
<div class="card col-3"><div class="kpi-title">מילים שנכתבו</div><div class="kpi-value" id="stat-words">0</div></div>
<div class="card col-3"><div class="kpi-title">זמן קריאה כולל</div><div class="kpi-value" id="stat-time" style="color:#f59e0b">0</div></div>
<div class="card col-8"><h3>📈 מגמת פרסום חודשית</h3><div class="chart-box"><canvas id="chart-monthly"></canvas></div></div>
<div class="card col-4"><h3>🕒 פעילות לפי שעות</h3><div class="chart-box"><canvas id="chart-hourly"></canvas></div></div>
<div class="card col-4"><h3>🏆 מקורות לייקים</h3><div class="list-container" id="list-fans"></div></div>
<div class="card col-4"><h3>📅 ימי פעילות מועדפים</h3><div class="chart-box"><canvas id="chart-weekly"></canvas></div></div>
<div class="card col-4"><h3>📏 אורך תוכן</h3><div class="chart-box"><canvas id="chart-length"></canvas></div></div>
<div class="card col-6"><h3>⭐ הפוסטים המוצלחים ביותר</h3><div class="list-container" id="list-best"></div></div>
<div class="card col-6"><h3>🔍 קשר בין אורך פוסט לפופולריות</h3><div class="chart-box"><canvas id="chart-scatter"></canvas></div></div>
<div class="card col-6"><h3>💤 תקופות שקט</h3><div class="list-container" id="list-gaps"></div></div>
<div class="card col-6"><h3>🔥 מתי הוא הכי חד</h3><div class="list-container" id="list-sharp"></div></div>
<div class="card col-6"><h3>🗣️ למי הוא באמת עונה</h3><div class="list-container" id="list-replyto"></div></div>
<div class="card col-6"><h3>🏠 בשרשורים של מי הוא חי</h3><div class="list-container" id="list-hosts"></div></div>
<div class="card col-6"><h3>🎭 יוזם או מגיב</h3><div class="list-container" id="list-role"></div></div>
<div class="card col-6"><h3>📍 איפה בפורום הוא חי</h3><div class="list-container" id="list-cats"></div></div>
<div class="card col-12"><h3>💥 מה הצית שיחה</h3><div class="list-container" id="list-spark"></div></div>
<div class="card col-12"><h3>👥 עם מי הוא מדבר</h3><div class="list-container" id="list-social"></div></div>
<div class="card col-12"><h3>💬 כמה הוא נשאר בשרשור</h3><div class="list-container" id="list-threads"></div></div>
</div>
</div>
<script>
const data=__JSON_DATA__;const myUid=__MY_UID__;const baseUrl=__BASE_URL__;const scannedAt=__SCANNED_AT__;const meta=__META__;
// כל טקסט מהפורום עובר בריחה לפני הזרקה ל-innerHTML
// טקסט מהפורום חוזר מקודד ל-HTML (הלקח מ-0.8.21), ושמות המצביעים לא
// פוענחו. מפענח קטן וקבוע, בלי DOM — הדוח נשמר לקובץ ונפתח בכל מקום.
const _ENT={quot:'"',amp:'&',lt:'<',gt:'>',apos:"'",nbsp:' ','#39':"'",'#34':'"'};
const _U=s=>String(s==null?'':s).replace(/&(#?[a-z0-9]+);/gi,(m,k)=>_ENT[k]!==undefined?_ENT[k]:m);
// שם משתמש מגיע מהפורום ונכנס ל-innerHTML — בריחה חובה.
const _E=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const escAttr=s=>encodeURIComponent(String(s==null?'':s));
// ספירת הלייקים מגיעה **חינם עם הפוסט** (`upvotes`), ולכן היא ידועה
// תמיד — גם בלי עוגייה. מה שתלוי בעוגייה הוא רק **מי** עשה לייק.
// שתי המילים האלה בלבלו זו את זו קודם: הדוח הציג "—" על מספר שכבר היה
// בידיים, ושרף ~1,800 בקשות כדי לגלות אותו שוב.
const totalLikes=data.reduce((a,b)=>a+b.likes,0);
const totalDowns=data.reduce((a,b)=>a+(b.down||0),0);
// הפוסטים שיש להם גם שמות מצביעים. פוסט בלי לייקים כלל אינו "חסר" —
// פשוט אין למי לשאול.
const named=data.filter(d=>d.votes_ok===true);
const withLikes=data.filter(d=>d.likes>0);
const namesMissing=withLikes.length-named.length;
// כמה מהלייקים באמת יש להם שמות. פוסט אחד מתוך 1,800 אינו "יש שמות":
// הקבוצה השלילית מאשימה אנשים, ולכן היא נפתחת רק כשכמעט הכול נמדד.
const likedNamed=named.reduce((a,b)=>a+b.likes,0);
const nameCover=totalLikes?likedNamed/totalLikes:0;
const anyNames=named.length>0;
const namesSolid=nameCover>=0.9;
// לכל פוסט יש ספירת לייקים אמיתית
const measured=data;
const totalWords=data.reduce((a,b)=>a+b.words,0);
// מספר הפוסטים הרשמי מדף הפרופיל, ולא מה שהסריקה הצליחה למשוך. פוסט מחוק,
// או כזה שיושב בקטגוריה שדורשת הרשאה, פשוט אינו חוזר מה-API — ולכן הספירה
// שלנו נמוכה מזו שהפורום מציג, וזה מה שבנימין ראה. הכותרת אומרת עכשיו את
// המספר הרשמי, ושורת המשנה אומרת כמה מתוכו באמת נמדד.
// **שאר הדוח ממשיך לעבוד על `data` בלבד**: ממוצע לייקים או מילים על מכנה
// שכולל פוסטים שאיש לא קרא היה מספר שקרי.
const scannedPosts=data.length;
const officialPosts=meta.postcount||0;
document.getElementById('stat-posts').innerText =
  (officialPosts>scannedPosts?officialPosts:scannedPosts).toLocaleString();
const psub=document.getElementById('stat-posts-sub');
if(psub && officialPosts>scannedPosts){
  psub.innerText='‏'+'נסרקו '+scannedPosts.toLocaleString()+' מתוך '+officialPosts.toLocaleString();
  psub.title='הפער הוא פוסטים שהסריקה אינה יכולה לקרוא: מחוקים, או בקטגוריות שדורשות הרשאה. כל שאר הנתונים בדוח מחושבים מהפוסטים שנסרקו.';
}
document.getElementById('stat-likes').innerText=totalLikes.toLocaleString();
{
  const el=document.getElementById('stat-likes');
  el.title=totalDowns
    ? ('ומולם '+totalDowns.toLocaleString()+' דיסלייקים בפוסטים שנסרקו')
    : 'בפוסטים שנסרקו';
}
document.getElementById('stat-words').innerText=totalWords.toLocaleString();
document.getElementById('stat-time').innerText=Math.ceil(totalWords/200)+" דק'";
Chart.defaults.color='#94a3b8';
const monthCounts={};data.forEach(d=>monthCounts[d.month]=(monthCounts[d.month]||0)+1);
new Chart(document.getElementById('chart-monthly'),{type:'line',data:{labels:Object.keys(monthCounts),datasets:[{label:'פוסטים',data:Object.values(monthCounts),borderColor:'#38bdf8',backgroundColor:'rgba(56,189,248,.1)',fill:true,tension:.4}]},options:{responsive:true,maintainAspectRatio:false}});
const hourlyData=Array(24).fill(0);data.forEach(d=>hourlyData[d.hour]++);
new Chart(document.getElementById('chart-hourly'),{type:'bar',data:{labels:Array.from({length:24},(_,i)=>i+":00"),datasets:[{label:'פוסטים',data:hourlyData,backgroundColor:'#8b5cf6'}]},options:{responsive:true,maintainAspectRatio:false}});
// _U מפענח ישויות HTML — NodeBB מחזיר שמות מקודדים. בלי זה אותו אדם
// מופיע פעמיים בשני כתיבים שונים בין הכרטיסים.
const fans={},fanSlug={};named.forEach(p=>p.voters.forEach(v=>{if(v.uid!=myUid){const nm=_U(v.username);fans[nm]=(fans[nm]||0)+1;fanSlug[nm]=v.userslug||String(nm||'').trim().toLowerCase().replace(/\s+/g,'-');}}));
Object.entries(fans).sort((a,b)=>b[1]-a[1]).slice(0,10).forEach(([name,count])=>{document.getElementById('list-fans').innerHTML+=`<div class="list-item"><a href="${esc(baseUrl)}/user/${escAttr(fanSlug[name]||name)}" target="_blank">${esc(name)}</a><span class="badge">${esc(count)}</span></div>`;});
// כרטיס ריק נקרא כ"אף אחד לא אהב אותו" — טענה על אדם. כשהספירה נכשלה
// אומרים זאת במפורש, וכשהיא הצליחה והוא באמת לא קיבל לייקים — גם כן.
// כרטיס ריק נקרא כ"אף אחד לא אהב אותו" — טענה על אדם. שמות המצביעים
// דורשים עוגייה, וכשאין אחת אומרים בדיוק את זה במקום להשתמע.
if(!Object.keys(fans).length){document.getElementById('list-fans').innerHTML=
  '<div class="list-item" style="opacity:.75">'+(!anyNames&&totalLikes
    ? 'הלייקים נספרו, אבל שמות המצביעים לא הגיעו'
    : (totalLikes? 'לא נמצאו שמות מצביעים' : 'לא התקבלו לייקים על הפוסטים שנסרקו'))+'</div>';}
// הרשימה נבנית משמות שהגיעו בלבד. בלי השורה הזו היא נראית כמו דירוג מלא
// בזמן שמקורם של רוב הלייקים אינו ידוע.
else if(!namesSolid){document.getElementById('list-fans').innerHTML+=
  '<div class="note-sm">מבוסס על '+likedNamed.toLocaleString()+' מתוך '+
  totalLikes.toLocaleString()+' הלייקים — לשאר לא הגיעו שמות</div>';}
const dayOrder=["ראשון","שני","שלישי","רביעי","חמישי","שישי","שבת"];
// קיבוץ לפי מספר היום ולא לפי שמו: השם מתורגם בזמן הבנייה בעוד
// הנתונים נאספו קודם, והשוואת המחרוזות ביניהם החזירה גרף ריק.
// dayOrder מתחיל בראשון ו-weekday של פייתון בשני — מכאן (i+6)%7.
const dayCounts=dayOrder.map((_,i)=>data.filter(d=>d.dow===(i+6)%7).length);
new Chart(document.getElementById('chart-weekly'),{type:'radar',data:{labels:dayOrder,datasets:[{label:'פוסטים',data:dayCounts,borderColor:'#f59e0b',backgroundColor:'rgba(245,158,11,.2)'}]},options:{responsive:true,maintainAspectRatio:false,scales:{r:{grid:{color:'#334155'}}}}});
const lens={'קצר':0,'בינוני':0,'ארוך':0};data.forEach(d=>{if(d.words<20)lens['קצר']++;else if(d.words<100)lens['בינוני']++;else lens['ארוך']++;});
new Chart(document.getElementById('chart-length'),{type:'doughnut',data:{labels:Object.keys(lens),datasets:[{data:Object.values(lens),backgroundColor:['#ef4444','#3b82f6','#10b981'],borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'70%'}});
[...data].sort((a,b)=>b.likes-a.likes).slice(0,10).forEach(p=>{document.getElementById('list-best').innerHTML+=`<div class="list-item"><a href="${esc(baseUrl)}/post/${encodeURIComponent(p.pid)}" target="_blank" style="max-width:80%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.title)}</a><span class="badge">+${esc(p.likes)}</span></div>`;});
if(!totalLikes){document.getElementById('list-best').innerHTML=
  '<div class="list-item" style="opacity:.75">לא התקבלו לייקים על הפוסטים שנסרקו</div>';}
new Chart(document.getElementById('chart-scatter'),{type:'scatter',data:{datasets:[{label:'פוסטים',data:data.map(d=>({x:d.words,y:d.likes})),backgroundColor:'#38bdf888'}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{type:'logarithmic',title:{display:true,text:'כמות מילים'}},y:{title:{display:true,text:'לייקים'}}}}});
// ── שלושה מקטעים שמחושבים מהנתונים שכבר כאן, בלי אף בקשה נוספת ───────────
const li=(a,b)=>`<div class="list-item"><span>${a}</span><span class="badge">${b}</span></div>`;
const note=t=>`<div class="list-item" style="opacity:.75">${t}</div>`;
const dayFmt=ts=>new Date(ts).toLocaleDateString();

// 💤 תקופות שקט — מתי הפסיק לכתוב, ולכמה זמן
(()=>{
  const box=document.getElementById('list-gaps');
  const ts=data.map(d=>d.ts).filter(Boolean).sort((a,b)=>a-b);
  if(ts.length<2){box.innerHTML=note('אין מספיק פוסטים כדי למדוד שתיקות');return;}
  const DAY=86400000, MIN_GAP=30;
  const gaps=[];
  for(let i=1;i<ts.length;i++){
    const d=Math.floor((ts[i]-ts[i-1])/DAY);
    if(d>=MIN_GAP) gaps.push({from:ts[i-1],to:ts[i],days:d});
  }
  // מול **זמן הסריקה** ולא מול שעון הקורא: אותו קובץ בדיוק אמר 'כתיבה
  // רציפה' ביום הסריקה, ו'שותק 240 ימים' כשנפתח מאוחר יותר.
  const scanTs=Date.parse(scannedAt)||Date.now();
  const quiet=Math.floor((scanTs-ts[ts.length-1])/DAY);
  let html='';
  if(quiet>=MIN_GAP) html+=li('<b>שותק כרגע</b> — מאז '+esc(dayFmt(ts[ts.length-1])), quiet+' ימים');
  gaps.sort((a,b)=>b.days-a.days).slice(0,6).forEach(g=>{
    html+=li(esc(dayFmt(g.from))+' ← '+esc(dayFmt(g.to)), g.days+' ימים');
  });
  // הפסקה של פחות מחודש אינה "שתיקה" — זה פשוט שבוע עמוס
  // סריקה מוגבלת מחזירה את הפוסטים החדשים בלבד, ולכן היעדר הפסקות בחלון
  // הזה אינו עדות לכתיבה רציפה. אמירה מוחלטת רק כשנסרק הכול.
  const whole=!meta.limited&&!meta.stopped_early&&!meta.partial;
  box.innerHTML=html||note(whole?'לא היו הפסקות של חודש ומעלה — כתיבה רציפה'
                               :'לא נמצאו הפסקות בפוסטים שנסרקו (הסריקה חלקית)');
})();

// 🔥 מתי הוא הכי חד — לייקים לפוסט לפי שעה, לא כמות פוסטים
(()=>{
  const box=document.getElementById('list-sharp');
  // ספירת הלייקים מגיעה מבקשה נפרדת לכל פוסט. אם חלקן נכשלו, ממוצע
  // הלייקים משקר — ואז עדיף לא להציג מספר מאשר להציג מספר שגוי.
  // ספירת הלייקים ידועה לכל פוסט (היא מגיעה עם הפוסט), ולכן המקטע הזה
  // כבר לא תלוי בעוגייה ולא משבית את עצמו.
  if(data.length<10){
    box.innerHTML=note('אין מספיק פוסטים בשעה מסוימת כדי להשוות');
    return;
  }
  const MIN_SAMPLE=5;
  const sum=Array(24).fill(0), cnt=Array(24).fill(0);
  measured.forEach(d=>{sum[d.hour]+=d.likes;cnt[d.hour]++;});
  const rows=[];
  for(let h=0;h<24;h++) if(cnt[h]>=MIN_SAMPLE) rows.push({h,avg:sum[h]/cnt[h],n:cnt[h]});
  if(rows.length<2){box.innerHTML=note('אין מספיק פוסטים בשעה מסוימת כדי להשוות');return;}
  const overall=totalLikes/measured.length;
  rows.sort((a,b)=>b.avg-a.avg);
  const best=rows[0], worst=rows[rows.length-1];
  const pad=h=>String(h).padStart(2,'0')+':00';
  let html=li('<b>השעה המוצלחת שלו</b> — '+pad(best.h)+' <span style="opacity:.7">('+best.n+' פוסטים)</span>',
              best.avg.toFixed(1)+' לייקים לפוסט');
  html+=li('הכי פחות — '+pad(worst.h)+' <span style="opacity:.7">('+worst.n+' פוסטים)</span>',
           worst.avg.toFixed(1));
  html+=li('הממוצע הכללי שלו', overall.toFixed(1));
  rows.slice(0,5).forEach(r=>{if(r!==best) html+=li(pad(r.h),r.avg.toFixed(1));});
  box.innerHTML=html;
})();

// 💬 כמה הוא נשאר בשרשור — מגיב פעם אחת ועובר הלאה, או נשאר עד הסוף
(()=>{
  const box=document.getElementById('list-threads');
  const by={};
  // קיבוץ לפי מזהה השרשור. כותרת אינה מפתח: פוסט בלי כותרת מקבל את המילה
  // "תגובה", וקיבוץ לפיה היה מאחד את כולם לשרשור מזויף אחד.
  data.forEach(d=>{
    const k=(d.tid!=null?'t'+d.tid:'x'+d.title);
    (by[k]=by[k]||{n:0,title:d.title,tid:d.tid}).n++;
  });
  const list=Object.values(by);
  if(!list.length){box.innerHTML=note('אין נתונים');return;}
  const one=list.filter(t=>t.n===1).length;
  const few=list.filter(t=>t.n>=2&&t.n<=4).length;
  const many=list.filter(t=>t.n>=5).length;
  const pct=n=>Math.round(n*100/list.length)+'%';
  let html=li('שרשורים שבהם כתב פעם אחת ועבר הלאה', one+' · '+pct(one));
  html+=li('שרשורים עם 2–4 הודעות שלו', few+' · '+pct(few));
  html+=li('שרשורים שבהם נשאר (5 ומעלה)', many+' · '+pct(many));
  html+=li('<b>סה"כ שרשורים שהשתתף בהם</b>', list.length.toLocaleString());
  list.sort((a,b)=>b.n-a.n).slice(0,5).forEach(t=>{
    const label=t.tid!=null
      ? `<a href="${esc(baseUrl)}/topic/${escAttr(t.tid)}" target="_blank">${esc(t.title)}</a>`
      : esc(t.title);
    html+=li(label, t.n+' הודעות');
  });
  box.innerHTML=html;
})();
// ══ חמישה מקטעים ממה שכבר הגיע עם הפוסטים ════════════════════════════════
// כל אחד מהם היה בנתונים מהיום הראשון ואיש לא נגע בו: `isMainPost`,
// `replies`, `category`, `topic.uid` ו-`topic.postcount`. אפס בקשות.
(function(){
  const N   = meta.names || {};
  const who = uid => (N[String(uid)] || {}).name || ('uid ' + uid);
  const lnk = uid => esc(baseUrl) + '/user/' +
        encodeURIComponent((N[String(uid)] || {}).slug || String(uid));
  const row = (label, sub, num, href) =>
    '<div class="list-item"><div>' +
    (href ? '<a href="' + esc(href) + '" target="_blank">' + label + '</a>' : label) +
    (sub ? '<div class="sub">' + sub + '</div>' : '') +
    '</div><span class="badge">' + num + '</span></div>';
  const empty = t => '<div class="list-item" style="opacity:.75">' + t + '</div>';
  const put = (id, html) => { const b = document.getElementById(id); if (b) b.innerHTML = html; };
  // כשהסריקה חלקית, כל מספר כאן הוא על תת-קבוצה — ונאמר בדיוק זה.
  const basis = (meta.limited || meta.partial)
    ? ' <span style="opacity:.8">(' + data.length.toLocaleString() +
      (meta.postcount ? ' מתוך ' + Number(meta.postcount).toLocaleString() : '') +
      ' פוסטים שנסרקו)</span>'
    : '';
  const count = (arr, key) => {
    const c = {}; arr.forEach(x => { const k = key(x); if (k || k === 0) c[k] = (c[k]||0)+1; });
    return Object.entries(c).sort((a,b)=>b[1]-a[1]);
  };

  // 🎭 יוזם או מגיב — האם הוא פותח שיחות או מצטרף אליהן
  const opened = data.filter(d => d.is_main).length;
  const replied = data.length - opened;
  put('list-role',
    row('<b>פתח שרשורים</b>', 'הוא זה שהתחיל את השיחה', opened.toLocaleString()) +
    row('<b>הגיב בשרשור של מישהו</b>', 'הצטרף לשיחה קיימת', replied.toLocaleString()) +
    (data.length ? '<div class="note-sm">' +
      Math.round(100 * replied / data.length) + '% מהפוסטים שנסרקו הם תגובות' + basis + '</div>' : ''));

  // 📍 איפה בפורום הוא חי
  const cats = count(data, d => d.cat);
  put('list-cats', cats.length
    ? cats.slice(0,8).map(([c,n]) => row(_E(c), '', n.toLocaleString())).join('')
      + '<div class="note-sm">' + cats.length + ' קטגוריות שונות בסך הכול' + basis + '</div>'
    : empty('אין מידע על קטגוריות בפוסטים שנסרקו'));

  // 🏠 בשרשורים של מי הוא חי — topic.uid, בלי אף בקשה
  const mine = data.filter(d => d.topic_uid === myUid).length;
  const hosts = count(data.filter(d => d.topic_uid && d.topic_uid !== myUid), d => d.topic_uid);
  put('list-hosts', hosts.length
    ? hosts.slice(0,8).map(([u,n]) =>
        row(_E(who(u)), 'פוסטים שלו בשרשורים של ' + _E(who(u)), n.toLocaleString(), lnk(u))).join('')
      + '<div class="note-sm">' + hosts.length + ' אנשים שונים · ובשרשורים שהוא עצמו פתח: '
      + mine.toLocaleString() + ' פוסטים</div>'
    : empty('אין מידע על פותחי השרשורים'));

  // 💥 מה הצית שיחה — replies שהפוסט שלו קיבל
  const sparks = [...data].filter(d => d.replies > 0).sort((a,b)=>b.replies-a.replies);
  const totalRep = data.reduce((a,b)=>a+(b.replies||0),0);
  put('list-spark', sparks.length
    ? sparks.slice(0,8).map(d => row(_E(d.title), _E(d.date) + ' · תגובות ישירות לפוסט הזה',
        String(d.replies), esc(baseUrl) + '/post/' + encodeURIComponent(d.pid))).join('')
      + '<div class="note-sm">' + totalRep.toLocaleString()
      + ' תגובות שהפוסטים שלו עוררו · ממוצע '
      + (data.length ? (totalRep/data.length).toFixed(2) : '0') + ' תגובות לכל פוסט' + basis + '</div>'
    : empty('אף פוסט שנסרק לא קיבל תגובה ישירה'));

  // 🗣️ למי הוא באמת עונה — toPid, וזה החלק שעולה בקשות ולכן מוגבל
  const tgt = count(data.filter(d => d.reply_uid && d.reply_uid !== myUid), d => d.reply_uid);
  const res = meta.reply_resolved || 0, tot = meta.reply_total || 0;
  const cover = tot ? Math.round(100 * res / tot) : 0;
  const note = tot
    ? '<div class="note-sm">מבוסס על <b>' + res.toLocaleString() + ' מתוך ' +
      tot.toLocaleString() + '</b> התגובות (' + cover + '%) — האחרונות שבהן. ' +
      'זה מה שמראה עם מי הוא מדבר <b>עכשיו</b>, ולא סיכום של כל השנים.</div>'
    : '';
  put('list-replyto', tgt.length
    ? tgt.slice(0,8).map(([u,n]) =>
        row(_E(who(u)), 'תגובות ישירות שלו אליו', n.toLocaleString(), lnk(u))).join('') + note
    : empty(!tot ? 'אף פוסט שנסרק אינו תגובה לאדם אחר'
                 : (res ? 'כל התגובות שנפתרו היו לפוסטים שלו עצמו'
                        : 'לא הצלחנו לזהות למי הוא ענה')));
})();

// 👥 עם מי הוא מדבר — הצלבה של שני צדדים שכבר ירדו ולא דיברו זה עם זה:
// את מי הוא מזכיר (מתוך תוכן הפוסטים) מול מי עושה לו לייקים.
//
// **שני הצדדים מפותחים לפי אותו מפתח מנורמל.** האזכור נושא slug
// ("צול-גאה") והמצביע נושא שם תצוגה ("צול גאה"); השוואה ישירה ביניהם לא
// מתאימה אף שם לאף שם, וזה מה שייצר את שתי הקבוצות השליליות השקריות.
(function(){
  const box = document.getElementById('list-social');
  if (!box) return;
  const norm = s => String(s==null?'':s).replace(/[\s_\-]+/g,'').trim().toLowerCase();
  const disp = {}, slugOf = {};
  // **שם התצוגה מגיע מרשימת המצביעים, לא מהאזכור.** נמדד על mitmachim:
  // בסימון האזכור ה-slug יושב בכל שלושת המקומות (href, aria-label וה-<bdi>),
  // ולכן מי שרק הוזכר יוצג בכתיב של הקישור — וזה מה שהפורום עצמו מראה שם.
  // מי שגם עשה לייק מקבל את השם האמיתי, ו-`strong` דואג שהוא יגבר.
  const remember = (k, name, slug, strong) => {
    if (name && (strong || !disp[k])) disp[k] = name;
    if (!disp[k]) disp[k] = slug || k;
    if (slug && !slugOf[k]) slugOf[k] = slug;
  };

  // את מי הוא מזכיר
  const said = {};
  data.forEach(p => (p.mentions||[]).forEach(m => {
    const k = m.k || norm(m.slug || m.name);
    if (!k) return;
    said[k] = (said[k]||0) + 1;
    remember(k, m.name, m.slug, false);
  }));

  // מי עושה לו לייקים — רק מהפוסטים שספירת הלייקים שלהם הצליחה
  const liked = {};
  measured.forEach(p => (p.voters||[]).forEach(v => {
    if (v.uid == myUid) return;
    const k = norm(v.userslug || v.username);
    if (!k) return;
    liked[k] = (liked[k]||0) + 1;
    remember(k, _U(v.username), v.userslug, true);
  }));

  const link = k => esc(baseUrl) + '/user/' + encodeURIComponent(slugOf[k] || k);
  const row = (k, right, left) =>
    '<div class="list-item"><div><a href="' + link(k) + '" target="_blank" class="who">'
    + _E(disp[k]) + '</a><div class="sub">' + right + '</div></div>'
    + '<div class="num">' + left + '</div></div>';

  const keys = Object.keys(said).concat(Object.keys(liked));
  const all = keys.filter((k,i) => keys.indexOf(k) === i);
  const mutual = all.filter(k => said[k] && liked[k])
                    .sort((a,b) => (said[b]+liked[b]) - (said[a]+liked[a])).slice(0,8);
  const quiet  = Object.keys(liked).filter(k => !said[k])
                    .sort((a,b) => liked[b]-liked[a]).slice(0,8);
  // "פונה אליהם ולא הגיע מהם לייק" מוצג **רק** כשספירת הלייקים הייתה
  // שלמה. חלקית = אנחנו לא יודעים שלא הגיע לייק, רק שלא מדדנו.
  // הקבוצה השלילית תלויה ב**שמות** המצביעים, ולכן בעוגייה — לא בספירה.
  const oneWay = !namesSolid ? [] :
    Object.keys(said).filter(k => said[k] >= 3 && !liked[k])
          .sort((a,b) => said[b]-said[a]).slice(0,8);

  if (!all.length) {
    box.innerHTML = '<div class="empty">לא נמצאו אזכורים או לייקים בפוסטים שנסרקו</div>';
    return;
  }
  let h = '';
  if (mutual.length) h += '<div class="grp">🤝 הקרובים אליו</div>'
    + mutual.map(k => row(k, 'הזכיר ' + said[k] + ' · לייקים ' + liked[k],
                          said[k] + liked[k])).join('');
  if (quiet.length) h += '<div class="grp">💗 מעריצים שקטים</div>'
    + quiet.map(k => row(k, 'עושים לו לייק, והוא לא מזכיר אותם', liked[k])).join('');
  if (oneWay.length) h += '<div class="grp">🙊 מזכיר אותם, ולא הגיע מהם לייק</div>'
    + oneWay.map(k => row(k, 'אזכורים בפוסטים שנסרקו', said[k])).join('');
  if (!namesSolid) h += '<div class="note-sm">⚠️ שמות המצביעים ידועים רק לחלק מהלייקים, ולכן לא מוצגת הקבוצה של מי שלא החזיר לייק</div>';
  h += '<div class="note-sm">נספר רק @אזכור או ציטוט — כפי שהפורום עצמו מסמן אותם. תגובה בשרשור בלי תיוג אינה נספרת, וזו הדרך הנפוצה לדבר כאן: אפשר לשוחח עם מישהו מאות פעמים ולהופיע כאן עם מספר חד-ספרתי.</div>';
  box.innerHTML = h;
})();
</script>
</body>
</html>"""


COMPARE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>השוואה: __A__ מול __B__</title>
__CHARTJS__
<style>
  :root{--a:#f59e0b;--b:#0ea5e9;--bg:#14161c;--card:#1c1f28;--txt:#e8eaf0;--sub:#9aa2b4}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font-family:"Segoe UI",Arial,sans-serif;font-size:14px;line-height:1.6}
  .wrap{max-width:1000px;margin:0 auto;padding:24px 18px 60px}
  h1{font-size:24px;margin:0 0 4px}
  .who{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:20px;font-size:13px}
  .pill{padding:3px 12px;border-radius:99px;font-weight:700}
  .pa{background:rgba(245,158,11,.18);color:var(--a)}
  .pb{background:rgba(14,165,233,.18);color:var(--b)}
  .card{background:var(--card);border-radius:14px;padding:16px 18px;margin-bottom:16px}
  .card h2{font-size:15px;margin:0 0 12px;font-weight:700}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:right;padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.07);font-size:13px}
  th{color:var(--sub);font-weight:600;font-size:12px}
  td.va{color:var(--a);font-weight:700}
  td.vb{color:var(--b);font-weight:700}
  .warn{background:rgba(244,84,76,.12);color:#ff9a94;padding:8px 12px;
        border-radius:8px;font-size:12.5px;margin-bottom:14px}
  .sum{font-size:13.5px;line-height:1.9}
  canvas{max-height:260px}
  .foot{color:var(--sub);font-size:11.5px;text-align:center;margin-top:26px}
</style></head><body><div class="wrap">
<h1>השוואת פעילות</h1>
<div class="who"><span class="pill pa">__A__</span><span style="color:var(--sub)">מול</span>
  <span class="pill pb">__B__</span></div>
<div id="warn"></div>
<div class="card"><h2>מספרים</h2><table id="tbl"></table></div>
<div class="card"><h2>שעות פעילות</h2><canvas id="c-hours"></canvas></div>
<div class="card"><h2>ימים בשבוע</h2><canvas id="c-days"></canvas></div>
<div class="card"><h2>פעילות לאורך זמן</h2><canvas id="c-months"></canvas></div>
<div class="card"><h2>מה עולה מההשוואה</h2><div class="sum" id="sum"></div></div>
<div class="foot">Tik-Nick · חזונישניק</div>
</div>
<script>
const D = __JSON_DATA__;
const A = D.a, B = D.b, SA = A.stats, SB = B.stats;
// _json_for_script מגן על הבריחה מבלוק ה-script, אבל אחרי ש-JS פירס את המחרוזת
// היא שוב מכילה < > אמיתיים — ולכן כל שם משתמש או כותרת נושא שנכנסים ל-innerHTML
// חייבים בריחה כאן. הדוח החד-משתמשי כבר עושה זאת; ההשוואה לא עשתה.
function esc(v) {
  return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
const DAYS = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"];
const COL_A = "#f59e0b", COL_B = "#0ea5e9";

// דיווח כן על חלקיות — לכל משתמש בנפרד. "א' הושלם, ב' נעצר" הוא מצב אמיתי.
const notes = [];
for (const side of [A, B]) {
  const m = side.meta;
  if (m.limited) notes.push(esc(side.user) + ": נסרקו רק הפוסטים האחרונים לפי ההגבלה שהגדרת.");
  else if (m.stopped_early) notes.push(esc(side.user) + ": הסריקה נעצרה בגלל תקלת רשת — הנתונים חלקיים.");
  else if (m.partial) notes.push(esc(side.user) + ": נסרקו " + side.stats.posts + " מתוך " +
    m.postcount + " פוסטים; השאר כנראה בקטגוריות שדורשות התחברות.");
}
if (notes.length) document.getElementById("warn").innerHTML =
  "<div class=\"warn\">⚠️ " + notes.join("<br>") + "</div>";

const rows = [
  ["פוסטים שנסרקו", SA.posts, SB.posts],
  ["לייקים שהתקבלו", SA.likes, SB.likes],
  ["לייקים לפוסט (ממוצע)", SA.avg_likes, SB.avg_likes],
  ["מילים לפוסט (ממוצע)", SA.avg_words, SB.avg_words],
  ["שעת השיא", SA.top_hour + ":00", SB.top_hour + ":00"],
  ["היום הפעיל ביותר", SA.top_day, SB.top_day],
  ["פוסט ראשון שנסרק", SA.first, SB.first],
  ["פוסט אחרון שנסרק", SA.last, SB.last],
];
document.getElementById("tbl").innerHTML =
  "<tr><th></th><th>" + esc(A.user) + "</th><th>" + esc(B.user) + "</th></tr>" +
  rows.map(function (r) {
    return "<tr><td>" + esc(r[0]) + "</td><td class=\"va\">" + esc(r[1]) +
           "</td><td class=\"vb\">" + esc(r[2]) + "</td></tr>";
  }).join("");

const opts = function () {
  return { responsive: true, plugins: { legend: { labels: { color: "#e8eaf0" } } },
    scales: { x: { ticks: { color: "#9aa2b4" }, grid: { color: "rgba(255,255,255,.05)" } },
              y: { ticks: { color: "#9aa2b4" }, grid: { color: "rgba(255,255,255,.05)" },
                   beginAtZero: true } } };
};

new Chart(document.getElementById("c-hours"), { type: "bar", data: {
  labels: Array.from({length: 24}, function (_, h) { return h + ":00"; }),
  datasets: [{ label: A.user, data: SA.hours, backgroundColor: COL_A },
             { label: B.user, data: SB.hours, backgroundColor: COL_B }] }, options: opts() });

new Chart(document.getElementById("c-days"), { type: "bar", data: {
  labels: DAYS,
  datasets: [{ label: A.user, data: SA.days, backgroundColor: COL_A },
             { label: B.user, data: SB.days, backgroundColor: COL_B }] }, options: opts() });

const months = Object.keys(SA.months).concat(Object.keys(SB.months))
  .filter(function (v, i, a) { return a.indexOf(v) === i; }).sort();
new Chart(document.getElementById("c-months"), { type: "line", data: {
  labels: months,
  datasets: [{ label: A.user, data: months.map(function (m) { return SA.months[m] || 0; }),
               borderColor: COL_A, backgroundColor: COL_A, tension: .3 },
             { label: B.user, data: months.map(function (m) { return SB.months[m] || 0; }),
               borderColor: COL_B, backgroundColor: COL_B, tension: .3 }] }, options: opts() });

// סיכום במילים — מה באמת שונה, לא רק גרפים יפים.
// "כמה כתב" חייב להיחשב מסך הפוסטים בפורום ולא ממה שנסרק: ההגבלה חותכת את שני
// המשתמשים לאותו מספר, וכך המשפט היה יוצא "בערך אותה כמות" בדיוק כשההפרש גדול,
// או אפילו מצביע על ההפוך. אם אין postcount אמין — אומרים במפורש על מה מדובר.
const out = [];
const capped = A.meta.limited || B.meta.limited;
const totA = A.meta.postcount || 0, totB = B.meta.postcount || 0;
const useTotals = totA > 0 && totB > 0;
const mA = useTotals ? totA : SA.posts, mB = useTotals ? totB : SB.posts;
const more = mA >= mB ? A : B, less = mA >= mB ? B : A;
const hi = Math.max(mA, mB), lo = Math.max(1, Math.min(mA, mB));
const rat = (hi / lo).toFixed(1);
const basis = useTotals ? " (לפי סך הפוסטים בפורום)"
                        : (capped ? " (מתוך מה שנסרק בלבד)" : "");
out.push("• <b>" + esc(more.user) + "</b> כתב " +
  (rat > 1.15 ? "פי " + rat + " יותר" : "בערך אותה כמות") +
  " פוסטים מ־<b>" + esc(less.user) + "</b>" + basis + ".");
if (capped) out.push("• שאר ההשוואה מבוססת על " + Math.min(SA.posts, SB.posts) +
  "–" + Math.max(SA.posts, SB.posts) + " הפוסטים האחרונים של כל אחד, לפי ההגבלה שהגדרת.");
if (Math.abs(SA.avg_likes - SB.avg_likes) > 0.2)
  out.push("• פוסט של <b>" + esc(SA.avg_likes > SB.avg_likes ? A.user : B.user) +
    "</b> מקבל בממוצע יותר לייקים (" + Math.max(SA.avg_likes, SB.avg_likes) + " מול " +
    Math.min(SA.avg_likes, SB.avg_likes) + ").");
if (Math.abs(SA.avg_words - SB.avg_words) > 10)
  out.push("• <b>" + esc(SA.avg_words > SB.avg_words ? A.user : B.user) + "</b> כותב ארוך יותר (" +
    Math.max(SA.avg_words, SB.avg_words) + " מילים לפוסט מול " +
    Math.min(SA.avg_words, SB.avg_words) + ").");
out.push(SA.top_hour !== SB.top_hour
  ? "• שעות השיא שונות: " + esc(A.user) + " ב־" + SA.top_hour + ":00, " + esc(B.user) + " ב־" + SB.top_hour + ":00."
  : "• שניהם פעילים בעיקר סביב " + SA.top_hour + ":00.");
if (SA.top_day === SB.top_day) out.push("• שניהם פעילים במיוחד ביום " + esc(SA.top_day) + ".");
const shared = SA.top_topics.map(function (t) { return t[0]; }).filter(function (t) {
  return SB.top_topics.some(function (x) { return x[0] === t; });
});
if (shared.length) out.push("• נושאים משותפים בין הבולטים: " +
  shared.slice(0, 3).map(esc).join(" · ") + ".");
document.getElementById("sum").innerHTML = out.join("<br>");


</script></body></html>"""
