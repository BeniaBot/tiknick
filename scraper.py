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

import gzip
import json
import logging
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import net
import html

USER_AGENT = "Tik-Nick/1.0 (+https://github.com/BeniaBot/tiknick)"
PAGE_DELAY_SEC = 0.6          # השהיה בין עמודים — לא להעמיס על השרת
HARD_PAGE_CAP = 4000          # בלם ביטחון: פורום תקול שמחזיר עמודים בלי סוף
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


# שם עוגיית ההתחברות לכל פלטפורמה — משמש לנרמול מה שהמשתמש הדביק.
COOKIE_NAMES = {"nodebb": "express.sid", "discourse": "_t",
                "xenforo": "xf_user"}

def normalize_cookie(cookie, platform="nodebb"):
    """
    ההדרכה בממשק מבקשת מהמשתמש להעתיק את *הערך* של express.sid (מחרוזת
    שמתחילה ב-s%3A), אבל כותרת Cookie חייבת להיות "שם=ערך". עד 0.8.5 הערך
    נשלח כמו שהוא, השרת התעלם ממנו, והמשתמש נחשב אורח — כל התוכן שדורש
    התחברות פשוט נעלם, והסריקה דיווחה "הושלמה".
    מקבל: ערך בלבד, "שם=ערך", או הדבקה של כל שורת ה-Cookie.
    """
    c = (cookie or "").strip().strip(";").strip()
    if not c:
        return ""
    name = COOKIE_NAMES.get(platform, "express.sid")
    # הדבקה של כמה עוגיות, או "שם=ערך" — כבר תקין
    if "=" in c.split(";")[0]:
        return c
    return f"{name}={c}"

# חתימות של דף אתגר. אנחנו רק *מזהים* אותו כדי לומר למשתמש את האמת —
# אין כאן שום ניסיון לעקוף אותו, וזו החלטה: הפורומים האלה הם התקנות קטנות
# שמתנדבים מתחזקים, והסורק מזדהה בשמו במפורש (USER_AGENT).
_CHALLENGE_MARKS = ("cf-browser-verification", "cf_chl_opt", "__cf_chl",
                    "just a moment", "checking your browser",
                    "attention required! | cloudflare")


def _looks_like_challenge(text):
    t = (text or "")[:4000].lower()
    return any(m in t for m in _CHALLENGE_MARKS)


def _cookie_platform_for(url):
    """
    ה-API של NodeBB יושב תחת /api/ ושל Discourse לא. זה מספיק כדי לבחור את
    שם העוגייה הנכון בלי לגרור את הפלטפורמה דרך כל מסלול קריאה.
    """
    try:
        return "nodebb" if urllib.parse.urlsplit(url).path.startswith("/api/") \
            else "discourse"
    except Exception:
        return "nodebb"


def _fetch_json(url, cookie=None):
    """בקשת GET אחת שמחזירה JSON, עם ניסיונות חוזרים וכיבוד Retry-After.
    cookie — מחרוזת עוגייה אופציונלית (למשל 'express.sid=...') לפורומים
    שדורשים התחברות כדי לצפות ברשימת המשתמשים."""
    # הנרמול כאן ולא בקוראים: check_forum, detect_platform ו-
    # scrape_single_user לא נרמלו כלל, ולכן ערך שהמשתמש הדביק לפי ההדרכה
    # ("s%3A...") נשלח בלי "express.sid=" — כותרת Cookie לא חוקית. הפורום
    # התייחס אלינו כאורח, "בדוק פורום" ענה "דורש התחברות" על עוגייה תקינה,
    # ו"סנכרן נבחרים" החזיר "לא נמצא" לכל ניק. normalize_cookie אידמפוטנטי,
    # ולכן scrape_forum שכבר נרמל אינו נפגע.
    cookie = normalize_cookie(cookie, _cookie_platform_for(url)) if cookie else None
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        raw = ""
        try:
            with net.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
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
                # 403 של Cloudflare אינו חוסר הרשאה — עוגייה לא תפתור אותו
                body = ""
                try:
                    body = e.read(4096).decode("utf-8", "replace")
                except Exception:
                    pass
                if _looks_like_challenge(body):
                    raise ScrapeError(
                        "הפורום מוגן ב-Cloudflare וחוסם כרגע גישה אוטומטית. "
                        "אפשר לנסות שוב מאוחר יותר.")
                raise AuthRequired("אין הרשאה לצפות במשתמשים בפורום זה (ייתכן שנדרשת התחברות)")
            if e.code == 404:
                raise ScrapeError("נתיב ה-API לא נמצא — ייתכן שאין תמיכת API בפורום זה")
            if 400 <= e.code < 500:
                # שגיאת לקוח לא תיפתר בניסיון נוסף. זה נראה רק כשנוסף מסלול
                # שלישי לזיהוי: XenForo מחזיר 400 (no_api_key_in_request) על
                # /api/users, ושתי הבדיקות הכושלות שלפניו בזבזו 12 שניות של
                # שינה על תשובה שלא תשתנה. "בדוק פורום" ארך 26 שניות.
                raise ScrapeError(f"שגיאת בקשה {e.code}")
            last_err = ScrapeError(f"שגיאת שרת {e.code}")
            time.sleep(attempt * 2)
        except urllib.error.URLError as e:
            last_err = ScrapeError(f"בעיית רשת: {e.reason}")
            time.sleep(attempt * 2)
        except (TimeoutError, OSError) as e:
            # תקלה בזמן **קריאת גוף** התשובה אינה URLError אלא OSError גולמי.
            # קודם היא חמקה מהריטריי וממניין failed_pages כאחת, יצאה מ-
            # scrape_forum, והפורום כולו סומן כמדולג — עם שורה ביומן הסריקות
            # שאומרת אפס שינויים על סריקה שדווקא כן הספיקה לעדכן.
            # (URLError הוא תת-מחלקה של OSError, ולכן הוא נתפס למעלה.)
            last_err = ScrapeError(f"החיבור נקטע באמצע קבלת התשובה: {e}")
            time.sleep(attempt * 2)
        except json.JSONDecodeError:
            # דף אתגר של Cloudflare חוזר כ-HTML עם קוד 200, וההודעה הקודמת
            # אמרה "אין API בכתובת זו" — מסקנה שגויה שמצדיקה ויתור. עם 403
            # זה היה גרוע יותר: המשתמש נשלח לחפש עוגייה שלא תעזור.
            if _looks_like_challenge(raw):
                raise ScrapeError(
                    "הפורום מוגן ב-Cloudflare וחוסם כרגע גישה אוטומטית. "
                    "אפשר לנסות שוב מאוחר יותר.")
            raise ScrapeError("התקבלה תשובה שאינה JSON — ככל הנראה אין API בכתובת זו")
    raise last_err or ScrapeError("הבקשה נכשלה")


def _fetch_html(url, cookie=None, platform="xenforo"):
    """
    בקשת GET אחת שמחזירה HTML, עם אותם ריטריי, 429 ו-Retry-After כמו
    `_fetch_json`. זהו נתיב הרשת הראשון בפרויקט שאינו API מתועד, ולכן הוא
    מעתיק את שלד הנימוס במקום להמציא אחד.

    שני הבדלים מהותיים מ-`_fetch_json`:

    * **gzip.** עמוד רשימה של XenForo הוא ~600KB, ו-562 עמודים בפרוג הם 328
      מגה. בקשת דחיסה חותכת 88% מזה (נמדד: 611,573 → 73,200 בתים) וגם
      מהירה פי ארבעה. זו בקשת HTTP רגילה, לא התחזות לדפדפן.
    * **בדיקת אתגר על כל 200.** למסלול JSON יש JSONDecodeError שתופס דף
      אתגר; ל-HTML אין, ובלי הבדיקה הזו דף Cloudflare מתפרש כאפס שורות —
      כלומר "הרשימה נגמרה". הפריסה חייבת לקרות לפני הבדיקה, אחרת היא
      מחפשת מחרוזות בתוך בתים דחוסים ולעולם לא מוצאת.

    מחזיר (טקסט, הכתובת הסופית) — הסופית כדי לזהות הפניה שנעקבה.
    """
    cookie = normalize_cookie(cookie, platform) if cookie else None
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        headers = {"User-Agent": USER_AGENT,
                   "Accept": "text/html,application/xhtml+xml",
                   "Accept-Encoding": "gzip"}
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, headers=headers)
        try:
            with net.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = resp.read()
                if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                    data = gzip.decompress(data)
                raw = data.decode("utf-8", errors="replace")
                if _looks_like_challenge(raw):
                    raise ScrapeError(
                        "הפורום מוגן ב-Cloudflare וחוסם כרגע גישה אוטומטית. "
                        "אפשר לנסות שוב מאוחר יותר.")
                return raw, resp.geturl()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if (retry_after or "").isdigit() else attempt * 5
                time.sleep(min(wait, 30))
                last_err = ScrapeError("הפורום מגביל קצב בקשות (429)")
                continue
            if e.code in (401, 403):
                try:
                    body = e.read(4096).decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                if _looks_like_challenge(body):
                    raise ScrapeError(
                        "הפורום מוגן ב-Cloudflare וחוסם כרגע גישה אוטומטית. "
                        "אפשר לנסות שוב מאוחר יותר.")
                raise AuthRequired(
                    "אין הרשאה לצפות ברשימת המשתמשים — ייתכן שנדרשת עוגיית התחברות")
            if e.code == 404:
                raise ScrapeError("עמוד רשימת המשתמשים לא נמצא בכתובת זו")
            last_err = ScrapeError("שגיאת שרת %s" % e.code)
            time.sleep(attempt * 2)
        except urllib.error.URLError as e:
            last_err = ScrapeError("אין חיבור לפורום (%s)" % getattr(e, "reason", e))
            time.sleep(attempt * 2)
        except (TimeoutError, OSError) as e:
            # קריאה שנקטעת באמצע הגוף מגיעה כ-OSError גולמי ולא כ-URLError.
            # בלי הענף הזה עמוד בודד שנקטע מסמן את כל הפורום כמדולג.
            last_err = ScrapeError("הבקשה נכשלה (%s)" % type(e).__name__)
            time.sleep(attempt * 2)
    raise last_err or ScrapeError("הבקשה נכשלה")


# ══ XenForo: מפרשי ה-HTML ════════════════════════════════════════════════
# ל-XenForo אין API ציבורי לרשימת משתמשים (/api/users מחזיר
# no_api_key_in_request), אבל /members/list/ הוא HTML ציבורי לגמרי בשני
# הפורומים שנמדדו. כל מה שכאן עובד על מחרוזות בלבד ונבדק בלי רשת.

_XF_ROW_MARK = '<li class="block-row block-row--separated">'
_XF_UID_RX = re.compile(r'data-user-id="(\d+)"')
_XF_NAME_RX = re.compile(
    r'<h3 class="contentRow-header">\s*<a [^>]*class="username[^"]*"[^>]*>(.*?)</a>',
    re.S)
_XF_PAIR_RX = re.compile(r"<dt>\s*(.*?)\s*</dt>\s*<dd>\s*(.*?)\s*</dd>", re.S)
_XF_IMG_RX = re.compile(r'<div class="contentRow-figure">.*?<img[^>]+src="([^"]+)"', re.S)
_XF_TAG_RX = re.compile(r"<[^>]+>")
_XF_TPL_RX = re.compile(r'data-template="([^"]+)"')
_XF_JUMP_RX = re.compile(r'<input[^>]*type="number"[^>]*\bmax="(\d+)"')
_XF_PAGENAV_RX = re.compile(r'/members/list/\?page=(\d+)')


def _xf_body(html_text):
    """
    גוף רשימת החברים בלבד.

    בעמוד יש קישורי /members/ גם מחוץ לרשימה — ווידג'טים של צוות, "מחוברים
    עכשיו" ומודעות. נמדד: 297 מזהים ייחודיים בעמוד של פרוג מול 250 שורות
    אמיתיות, ו-42 מול 30 בלתורה. בלי התיחום השורה האחרונה בולעת את כל שאר
    המסמך. יש בדיוק <ol> אחד בכל אחד משני העמודים, ולכן הסוגר הראשון הוא
    הנכון.
    """
    i = html_text.find('<ol class="block-body">')
    if i < 0:
        return ""
    j = html_text.find("</ol>", i)
    return html_text[i:j] if j > 0 else html_text[i:]


def _xf_rows(body):
    """
    שורות החברים, מחולקות לפי הפותח הבא.

    🚨 **לא** <li ...>(.*?)</li> לא-חמדני. שורת חבר **מכילה <li> מקוננים** —
    כל זוג dt/dd הוא פריט ברשימה — ולכן ביטוי לא-חמדני נעצר בסוגר הפנימי
    הראשון ומחזיר 845 תווים מתוך 2,013. מספר השורות יוצא נכון (250/250),
    השדה הראשון נמצא, וזה **לא נראה כמו באג** — אבל "תודות שהתקבלו"
    ו"נקודות", שקיימים ב-250 מתוך 250 השורות, נעלמים בשקט.
    """
    if not body:
        return []
    return body.split(_XF_ROW_MARK)[1:]


def _xf_last_page(html_text):
    """
    מספר העמוד האחרון לפי העימוד, או None.

    **לעולם לא 1 כברירת מחדל** — ערך כזה היה עוצר את הלולאה אחרי עמוד אחד
    ומדווח "הושלמה". וגם כשהוא קיים הוא אינו עוצר את הלולאה: הוא רק גודל
    לפס ההתקדמות ותקרה. המספר נלקח משדות הקפיצה (יש **שניים** בעמוד,
    למעלה ולמטה) ומקישורי העימוד, והגבוה מנצח.
    """
    nums = [int(x) for x in _XF_JUMP_RX.findall(html_text)]
    nums += [int(x) for x in _XF_PAGENAV_RX.findall(html_text)]
    return max(nums) if nums else None


def _xf_template(html_text):
    """שם התבנית שהפורום מצהיר עליו: member_list / member_view / login."""
    m = _XF_TPL_RX.search(html_text)
    return m.group(1) if m else ""


def _xf_logged_in(html_text):
    return 'data-logged-in="true"' in html_text


def _xf_text(raw):
    """
    טקסט מתוך HTML של שורה: מסירים תגיות, ואז מפענחים ישויות.

    הסדר חשוב. 4 מתוך 250 השמות בפרוג עטופים ב-<span class="username--styleNN">
    (צבע קבוצה), ולכידה תמימה של ([^<]*) מפספסת בדיוק אותם — בזמן שבלתורה
    היא מקבלת 30 מתוך 30 ונראית מושלמת.
    """
    return " ".join(_txt(_XF_TAG_RX.sub("", raw or "")).split()).strip()


def _xf_num(v):
    """
    מספר של XenForo. הם מגיעים מקובצים בפסיקים ("3,605"), ו-`_num_str`
    דוחה אותם לגמרי — merge_scraped_users מתייחס ל-"" כ"לא נסרק", כלומר
    הערך הישן קופא לנצח, ודווקא אצל הכותבים הגדולים. `_num_str` עצמו לא
    משתנה: NodeBB ו-Discourse מזינים אותו במספרים אמיתיים מ-JSON, והשמירה
    הקפדנית שלו היא מה שמונע מחרוזת אקראית מעמודה מספרית.
    """
    t = _xf_text(v)
    for ch in (",", chr(0xA0), chr(0x202F), " "):
        t = t.replace(ch, "")
    return _num_str(t)


# תוויות השדות. מפתחים לפי התווית ולעולם לא לפי מיקום: בעמוד אחד בפרוג יש
# תשע צורות שונות, ו-37 מתוך 250 השורות אינן בסדר הקנוני — אינדוקס לפי
# מיקום היה כותב "תגובות למאמר" לתוך עמודת המוניטין.
_XF_MSG_LABELS = ("הודעות", "messages")
_XF_REACT_LABELS = ("תודות שהתקבלו", "לייקים שהתקבלו", "reaction score")


def _xf_pairs(row):
    """כל זוגות dt/dd בשורה, ממופתחים לפי התווית. הראשון מנצח."""
    out = {}
    for k, v in _XF_PAIR_RX.findall(row):
        out.setdefault(_xf_text(k).strip().lower(), v)
    return out


def _xf_pick(pairs, labels):
    for lab in labels:
        if lab in pairs:
            return pairs[lab]
    return ""


def _xf_name(row):
    m = _XF_NAME_RX.search(row)
    return _xf_text(m.group(1)) if m else ""


def _map_xenforo_row(row, page_url):
    """
    ממפה שורת חבר לשדות של Tik-Nick — רק מה שנמדד, בלי להמציא.

    מה שנשאר בחוץ ולמה:
    * `status` — לרשימה אין סימון הרחקה. כתיבת "פעיל" הייתה ערך בעל אמינות
      **אבסולוטית** שדורס הרחקה אמיתית ממקור אחר, והמשתמש לא יכול לתקן.
    * `nick_color` — ה-style בשורה הוא גוון האווטאר שה**פורום** מייצר למי
      שאין לו תמונה, לא בחירה של המשתמש.
    * דרגה (userTitle) — קיימת ב-100% מהשורות, אבל 64% מהן בפרוג הן אותה
      מחרוזת ("משתמש חדש") ו-90% בלתורה ("חבר רשום"). כתיבתה ל-extra_info
      הייתה משחזרת בדיוק את באג הרעש שתועד ב-0.9.0.
    * "נקודות" — אין עמודה, אין סינון, ואין מי שיקרא.
    * join_date/last_seen/email — אינם ברשימה. מפתח חסר נשמר כחסר, ולכן
      ערך שהמשתמש הקליד ידנית אינו נמחק.
    """
    pairs = _xf_pairs(row)
    uid = _XF_UID_RX.search(row)
    out = {}
    if uid:
        out["forum_uid"] = uid.group(1)
    posts = _xf_num(_xf_pick(pairs, _XF_MSG_LABELS))
    if posts != "":
        out["post_count"] = posts
    # "תודות שהתקבלו" היא ספירת תגובות ואינה יורדת מתחת לאפס, בזמן
    # ש-reputation ב-NodeBB הוא לייקים פחות דיסלייקים. הערבוב אינו חדש —
    # _map_discourse_user כבר כותב likes_received לאותה עמודה.
    react = _xf_num(_xf_pick(pairs, _XF_REACT_LABELS))
    if react != "":
        out["reputation"] = react
    img = _XF_IMG_RX.search(row)
    if img:
        out["avatar_url"] = urllib.parse.urljoin(page_url, _txt(img.group(1)))
    return out


def scrape_single_user(forum_url, username, cookie=None, platform=None):
    """
    שולף משתמש בודד לפי שם משתמש (NodeBB או Discourse). מחזיר dict ממופה או None.
    """
    try:
        base = _api_base(forum_url)
    except ScrapeError:
        return None
    plat = platform or detect_platform(forum_url, cookie)
    if plat == "xenforo":
        # פרופיל XenForo מאותר לפי מזהה מספרי ולא לפי שם, ובחלק מההתקנות הוא
        # מאחורי התחברות. עד כאן הניק נפל ל-/api/user/<slug> — שתי בקשות
        # מתות לכל ניק מול שרת שאין לו את הנתיב הזה בכלל.
        return None
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


def _try_xenforo(base, cookie):
    """
    מחזיר (ok, user_count, title) אם זו רשימת חברים של XenForo, אחרת None.

    user_count הוא **חסם עליון**: עמוד_אחרון × שורות_בעמוד. בפרוג זה
    140,500 מול 140,392 אמיתיים (‎+0.08%), כי העמוד האחרון חלקי. הממשק
    מציג אותו עם "~". מספר מדויק היה דורש בקשה שנייה לעמוד האחרון, ולבדיקה
    מקדימה זה מיותר.
    """
    html_text, _url = _fetch_html(base + "/members/list/", cookie=cookie,
                                  platform="xenforo")
    # התבנית שהפורום מצהיר עליה — הדרך היחידה להבדיל בין רשימת חברים לבין
    # דף התחברות שהוחזר עם 200, או תבנית אחרת לגמרי.
    if _xf_template(html_text) != "member_list":
        return None
    rows = _xf_rows(_xf_body(html_text))
    if not rows:
        return None
    last = _xf_last_page(html_text)
    count = (last * len(rows)) if last else len(rows)
    m = re.search(r"<title>(.*?)</title>", html_text, re.S)
    # הכותרת היא "משתמשים רשומים | פרוג ..." — שם הפורום הוא החלק האחרון.
    title = _xf_text(m.group(1)).split("|")[-1].strip() if m else ""
    return (True, count, title or None)


def detect_platform(forum_url, cookie=None):
    """מזהה את פלטפורמת הפורום: 'nodebb' | 'discourse' | 'xenforo' | 'unknown'."""
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
    # XenForo נבדק **אחרון**: הבדיקה שלו היא HTML ולא API, והצבתה ראשונה
    # הייתה משנה את הזיהוי של 24 הפורומים המוכרים.
    try:
        if _try_xenforo(base, cookie):
            return "xenforo"
    except AuthRequired:
        return "xenforo"   # יש שם רשימה, היא פשוט דורשת התחברות
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

    # 🚨 חסימת הרשאה **אינה** זיהוי. 401/403 מוכיח שמשהו סירב לנו, לא איזו
    # תוכנה רצה שם — ולכן היא נזכרת וההרצה ממשיכה, בדיוק כמו ב-detect_platform.
    # קודם הבדיקה חזרה על ה-AuthRequired הראשון עם "platform": "nodebb",
    # ו-main.py שמר את זה במאגר: פורום XenForo מאחורי התחברות נרשם כ-NodeBB
    # לתמיד, והמשתמש נשלח לחפש עוגייה שהשרת מתעלם משמה.
    blocked = None

    # NodeBB
    try:
        res = _try_nodebb(base, cookie)
        if res:
            ok, count, title = res
            return {"ok": True, "user_count": count, "title": title,
                    "platform": "nodebb", "error": None}
    except AuthRequired:
        blocked = ("nodebb", "הפורום דורש התחברות לצפייה במשתמשים — "
                             "הזן עוגיית express.sid (ראה '🍪 איך משיגים?')")
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
        blocked = blocked or ("discourse", "הפורום דורש התחברות לצפייה במשתמשים — "
                                           "הזן עוגייה מתאימה")
    except ScrapeError:
        pass

    # XenForo — רשימת חברים ב-HTML, לא API
    try:
        res = _try_xenforo(base, cookie)
        if res:
            ok, count, title = res
            return {"ok": True, "user_count": count, "title": title,
                    "platform": "xenforo", "error": None}
    except AuthRequired:
        # XenForo גובר על חסימה קודמת: הוא נבדק אחרון, וחסימה שלו היא הראיה
        # הספציפית ביותר שיש לנו (ה-probe שלו מכוון לעמוד חברים ולא ל-API).
        blocked = ("xenforo", "רשימת החברים בפורום זה דורשת התחברות — "
                              "הזן עוגיית xf_user")
    except ScrapeError:
        pass

    if blocked:
        plat, msg = blocked
        return {"ok": False, "user_count": None, "title": None,
                "platform": plat, "error": msg}

    return {"ok": False, "user_count": None, "title": None, "platform": "unknown",
            "error": "לא נמצאה בכתובת זו רשימת משתמשים שניתן לקרוא אוטומטית "
                     "(נבדקו NodeBB, Discourse ו-XenForo)."}


def _txt(v):
    """
    טקסט מהפורום. NodeBB מחזיר ערכים **מקודדים ל-HTML** (ע"ה → ע&quot;ה), ואם
    שומרים אותם כך הם מוצגים שבורים וגם הקישור לפרופיל לא מוצא את המשתמש.
    הפענוח נעשה כאן, בגבול הרשת, כדי שכל השאר יעבוד על טקסט אמיתי.
    """
    s = "" if v is None else str(v)
    return html.unescape(s) if "&" in s else s


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
                return _txt(v)
        return ""

    groups = ""
    gl = u.get("groupTitleArray") or u.get("groups")
    if isinstance(gl, list):
        names = [x.get("name") if isinstance(x, dict) else str(x) for x in gl]
        groups = ", ".join([_txt(n) for n in names if n])
    elif isinstance(gl, str):
        groups = _txt(gl)

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
    # "נראה לאחרונה" **לא** נכנס לכאן. מ-0.8.5 יש לו שדה משלו (last_seen)
    # עם עמודה, סינון וייצוא — והשורה הזו נשארה מהתקופה שלפני כן, כך שהערך
    # נכתב פעמיים: פעם בשדה שלו, ופעם כטקסט חופשי בתוך "פרטים נוספים".
    # התוצאה היא ש"פרטים נוספים" של כמעט כל ניק סרוק התמלא ברעש הזה.
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
    # _num_str ולא str(x or "") — ירידה ל-0 היא שינוי אמיתי, ו-"" היה נבלע
    # במיזוג כאילו הערך לא נסרק, כך שהמוניטין הישן נשאר תקוע לנצח.
    if item.get("likes_received") is not None:
        mapped["reputation"] = _num_str(item.get("likes_received"))
    if item.get("post_count") is not None:
        mapped["post_count"] = _num_str(item.get("post_count"))
    return mapped


def scrape_forum(forum_name, forum_url, db, cookie=None, progress_cb=None,
                 cancel_flag=None, max_pages=None, skip_flag=None, platform=None,
                 run_id=None, min_posts=0):
    """
    סורק את כל המשתמשים בפורום וממזג למאגר. מנתב לפי פלטפורמה
    (NodeBB / Discourse / XenForo).

    platform    — 'nodebb' | 'discourse' | 'xenforo' | None (זיהוי אוטומטי)
    max_pages   — הגבלת עמודים (None = הכל)
    min_posts   — מינימום הודעות כדי להיכנס למאגר (0 = הכול). נתמך ב-XenForo
                  בלבד, כי רק שם מספר ההודעות מגיע באותה תשובה שמכילה את
                  רשימת החברים. בפורומים האלה 60% מהחשבונות מעולם לא כתבו
                  דבר, וזו החלטה של המשתמש ולא ברירת מחדל שקטה.
    מחזיר סיכום: {"added","updated","unchanged","pages","cancelled"}
    """
    base = _api_base(forum_url)
    plat = platform or detect_platform(forum_url, normalize_cookie(cookie))
    # המשתמש מדביק את *הערך* של העוגייה לפי ההדרכה; כאן הופכים אותו ל"שם=ערך"
    # לפי הפלטפורמה. בלי זה הכותרת חסרת משמעות והפורום מתייחס אלינו כאורח.
    cookie = normalize_cookie(cookie, plat)
    if plat == "nodebb":
        return _scrape_nodebb(forum_name, base, db, cookie, progress_cb,
                              cancel_flag, max_pages, skip_flag, run_id)
    if plat == "discourse":
        return _scrape_discourse(forum_name, base, db, cookie, progress_cb,
                                 cancel_flag, max_pages, skip_flag, run_id)
    if plat == "xenforo":
        return _scrape_xenforo(forum_name, base, db, cookie, progress_cb,
                               cancel_flag, max_pages, skip_flag, run_id,
                               min_posts=min_posts)
    # phpbb/custom/unknown — אין רשימת משתמשים שניתן לקרוא
    names = {"phpbb": "phpBB", "custom": "מערכת ייחודית"}
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
    # pageCount של NodeBB לא אמין — יש התקנות שמחזירות 1 גם כשיש מאות עמודים
    # (מתועד ב-CLAUDE.md לגבי /api/user/{slug}/posts, ותקף גם כאן). משתמשים בו
    # להערכת התקדמות בלבד וממשיכים עד עמוד ריק, כמו במסלול Discourse.
    est_pages = pagination.get("pageCount") or 1
    total_pages = est_pages
    if max_pages:
        total_pages = min(total_pages, max_pages)
        if est_pages > max_pages:
            stats["limited"] = True   # נעצר לבקשת המשתמש — לא "הושלם"

    def handle_users(users):
        # ממפים את כל העמוד ואז ממזגים בטרנזקציית DB אחת — מהיר בסדרי גודל
        pairs = [(_txt(u.get("username") or "").strip(), _map_user(u))
                 for u in users if (u.get("username") or "").strip()]
        if not pairs:
            return
        page_stats = db.merge_scraped_users(
            forum_name, pairs, source_label=f"NodeBB:{forum_name}", run_id=run_id,
            platform="nodebb")
        for key in ("added", "updated", "unchanged"):
            stats[key] += page_stats.get(key, 0)

    handle_users(first.get("users", []))
    stats["pages"] = 1
    if progress_cb:
        progress_cb({"page": 1, "total_pages": total_pages, **stats, "done": False})

    consecutive_fail = 0
    page = 1
    while True:
        page += 1
        if max_pages and page > max_pages:
            stats["limited"] = True
            break
        if page > HARD_PAGE_CAP:        # בלם ביטחון מול פורום שמחזיר עמודים לנצח
            stats["limited"] = True
            break
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
            if page >= est_pages:
                break                    # נגמרה ההערכה וגם נכשלנו — די
            if progress_cb:
                progress_cb({"page": page, "total_pages": max(total_pages, page),
                             **stats, "done": False})
            continue
        users = data.get("users", []) if isinstance(data, dict) else []
        if not users:
            break                        # עמוד ריק = סוף אמיתי של הרשימה
        handle_users(users)
        stats["pages"] = page
        if page > total_pages:
            total_pages = page           # ההערכה הייתה נמוכה מדי — עדכן את הפס
        if progress_cb:
            progress_cb({"page": page, "total_pages": total_pages, **stats, "done": False})

    if progress_cb:
        progress_cb({"page": stats["pages"], "total_pages": total_pages, **stats, "done": True})
    return stats


def _scrape_xenforo(forum_name, base, db, cookie, progress_cb,
                    cancel_flag, max_pages, skip_flag, run_id=None, min_posts=0):
    """
    סורק את /members/list/ של XenForo.

    בנוי על השלד של `_scrape_nodebb` ולא של `_scrape_discourse`, כי שם
    מונה העמוד עולה **בראש** הלולאה — ולכן שום מסלול שגיאה אינו יכול לבקש
    את אותו עמוד פעמיים.

    🚨 **המלכודת המרכזית, מדודה**: XenForo אינו מחזיר עמוד ריק אחרי האחרון —
    הוא מחזיר את **העמוד האחרון שוב**. פרוג 563 == 562, לתורה 570 == 569.
    לולאה שממתינה לעמוד ריק לא תיעצר לעולם. לכן תנאי העצירה הוא "העמוד לא
    תרם אף מזהה חדש", וזו עצירה מבוססת **תצפית** ולא מבוססת מספר שהשרת
    צייר. מספר העמוד האחרון מהעימוד משמש לפס ההתקדמות ולתקרה בלבד.
    """
    stats = {"added": 0, "updated": 0, "unchanged": 0, "pages": 0, "cancelled": False,
             "failed_pages": 0, "members_seen": 0, "skipped_low": 0, "stop_reason": ""}
    seen = set()
    consecutive_fail = 0
    floor = max(0, int(min_posts or 0))

    def fetch(page):
        url = base + "/members/list/" + ("?page=%d" % page if page > 1 else "")
        text, final_url = _fetch_html(url, cookie=cookie, platform="xenforo")
        tpl = _xf_template(text)
        if tpl == "login":
            raise AuthRequired(
                "רשימת החברים בפורום זה דורשת התחברות — הזן עוגיית xf_user")
        if tpl and tpl != "member_list":
            raise ScrapeError(
                "מבנה העמוד לא צפוי — ודא שזו רשימת החברים של פורום XenForo")
        return text, final_url

    def handle(rows, page_url):
        pairs = []
        for r in rows:
            name = _xf_name(r)
            if not name:
                continue
            mapped = _map_xenforo_row(r, page_url)
            if floor and int(mapped.get("post_count") or 0) < floor:
                stats["skipped_low"] += 1
                continue
            pairs.append((name, mapped))
        if not pairs:
            return
        page_stats = db.merge_scraped_users(
            forum_name, pairs, source_label="XenForo:%s" % forum_name, run_id=run_id,
            platform="xenforo")
        for key in ("added", "updated", "unchanged"):
            stats[key] += page_stats.get(key, 0)

    # עמוד ראשון מחוץ ללולאה — כך AuthRequired, אתגר Cloudflare ו-404 עולים
    # החוצה כמו שהם, בדיוק כמו ב-_scrape_nodebb.
    first, first_url = fetch(1)
    rows = _xf_rows(_xf_body(first))
    if not rows:
        raise ScrapeError("לא נמצאו שורות חברים בעמוד — ייתכן שמבנה הדף השתנה")
    last_page = _xf_last_page(first)
    ceiling = min(HARD_PAGE_CAP, (last_page + 3) if last_page else HARD_PAGE_CAP)
    total_pages = last_page or 1
    if max_pages:
        total_pages = min(total_pages, max_pages)
        if (last_page or HARD_PAGE_CAP) > max_pages:
            stats["limited"] = True
    if cookie and not _xf_logged_in(first):
        # דגל, לא שגיאה: הרשימה ציבורית ממילא ולכן הסריקה תקינה לגמרי.
        stats["guest"] = True
        logging.warning("XenForo: cookie supplied but page reports guest (%s)", base)
    seen.update(_XF_UID_RX.findall("".join(rows)))
    handle(rows, first_url)
    stats["pages"] = 1
    stats["members_seen"] = len(seen)
    if progress_cb:
        progress_cb({"page": 1, "total_pages": total_pages, **stats, "done": False})

    page = 1
    while True:
        page += 1                       # קודם כול — אף מסלול שגיאה לא חוזר על עמוד
        if max_pages and page > max_pages:
            stats["limited"] = True
            stats["stop_reason"] = "max_pages"
            break
        if page > ceiling:
            stats["limited"] = True
            stats["stop_reason"] = "runaway"
            logging.warning("XenForo: page %s passed the ceiling (%s)", page, base)
            break
        if cancel_flag is not None and cancel_flag.is_set():
            stats["cancelled"] = True
            stats["stop_reason"] = "cancelled"
            break
        if skip_flag is not None and skip_flag.is_set():
            stats["skipped"] = True
            stats["stop_reason"] = "skipped"
            break
        time.sleep(PAGE_DELAY_SEC)
        try:
            text, page_url = fetch(page)
            consecutive_fail = 0
        except AuthRequired:
            raise
        except ScrapeError:
            stats["failed_pages"] += 1
            consecutive_fail += 1
            logging.warning("XenForo: page %s failed (%s)", page, base)
            if consecutive_fail >= 5:
                stats["aborted"] = True
                stats["stop_reason"] = "aborted"
                break
            if progress_cb:
                progress_cb({"page": page, "total_pages": max(total_pages, page),
                             **stats, "done": False})
            continue
        rows = _xf_rows(_xf_body(text))
        if not rows:
            # עמוד ריק **אינו** סוף הרשימה: XenForo לא מחזיר עמוד ריק אחרי
            # האחרון. דף אתגר, WAF, או שינוי בתבנית נראים בדיוק כך —
            # ו"ריק = סיימנו" הוא בדיוק הדרך שבה סריקה חלקית מדווחת הצלחה.
            stats["failed_pages"] += 1
            consecutive_fail += 1
            logging.warning("XenForo: page %s parsed to zero rows (%s)", page, page_url)
            if consecutive_fail >= 5:
                stats["aborted"] = True
                stats["stop_reason"] = "aborted"
                break
            continue
        uids = set(_XF_UID_RX.findall("".join(rows)))
        if not (uids - seen):
            # אין אף חבר חדש — זו ההתנהגות המדודה של עמוד last+1. הסוף,
            # ומאומת בתצפית ולא במספר שהשרת צייר.
            stats["stop_reason"] = "confirmed_end"
            break
        seen |= uids
        handle(rows, page_url)
        stats["pages"] = page
        stats["members_seen"] = len(seen)
        if page > total_pages:
            total_pages = page
        if progress_cb:
            progress_cb({"page": page, "total_pages": total_pages, **stats, "done": False})

    # סריקה שלא הגיעה לסוף מאומת אינה "הושלמה", **וגם לא** סריקה שהגיעה
    # לסוף אחרי שדילגה על עמוד שנכשל: שם חסרים חברים שלמים באמצע הרשימה,
    # והעצירה המאומתת בסוף אינה מעידה עליהם דבר. limited/cancelled/skipped
    # מדווחים על עצמם ואינם "חלקי" במובן הזה — המשתמש ביקש אותם.
    if stats["failed_pages"]:
        stats["incomplete"] = True
    elif stats["stop_reason"] != "confirmed_end" and not (
            stats["cancelled"] or stats.get("skipped") or stats.get("limited")):
        stats["incomplete"] = True
    if progress_cb:
        progress_cb({"page": stats["pages"], "total_pages": max(total_pages, stats["pages"]),
                     **stats, "done": True})
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
        pairs = [(_txt((it.get("user") or {}).get("username", "")).strip(),
                  _map_discourse_dir_item(it, base))
                 for it in items if (it.get("user") or {}).get("username")]
        pairs = [(u, m) for u, m in pairs if u]
        if not pairs:
            return
        page_stats = db.merge_scraped_users(
            forum_name, pairs, source_label=f"Discourse:{forum_name}", run_id=run_id,
            platform="discourse")
        for key in ("added", "updated", "unchanged"):
            stats[key] += page_stats.get(key, 0)

    handle_items(items0)
    stats["pages"] = 1
    if progress_cb:
        progress_cb({"page": 1, "total_pages": total_pages, **stats, "done": False})

    # עימוד 0-בסיס; ממשיכים עד עמוד ריק (total_pages משמש רק להערכת ההתקדמות)
    page = 1
    seen_sig = None
    while items0:
        if page > HARD_PAGE_CAP:
            # שלוש מארבע לולאות העימוד מוגנות; זו לא הייתה. שרת שמתעלם מ-
            # ?page= (פרוקסי מוטעה, או Discourse מאחורי מטמון) גרם ללולאה
            # שמושכת וממזגת את אותו עמוד לנצח, בקצב בקשה כל PAGE_DELAY_SEC.
            stats["limited"] = True
            break
        if max_pages and page >= max_pages:
            stats["limited"] = True
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
        # שרת שמתעלם מ-?page= מחזיר שוב ושוב את אותם משתמשים. HARD_PAGE_CAP
        # לבדו היה עוצר אחרי 4000 בקשות מיותרות לפורום של מתנדבים; חתימת
        # העמוד עוצרת כבר בשנייה.
        sig = tuple(sorted(str(i.get("user", {}).get("username", "")) for i in items))
        if sig and sig == seen_sig:
            logging.warning("Discourse paging is not advancing at page %s — stopping", page)
            stats["limited"] = True
            break
        seen_sig = sig
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
