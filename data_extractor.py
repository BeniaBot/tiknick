# -*- coding: utf-8 -*-
"""
data_extractor — חילוץ מידע אישי מתוך פוסטים בפורום NodeBB.

מודול זה סורק את כל הפוסטים של משתמש בפורום, מחלץ מהם מידע אישי
(טלפונים, מיילים, שמות, כתובות, טלגרם, וואטסאפ) באמצעות ביטויים רגולריים,
ומייצר דוח HTML אינטראקטיבי עם הממצאים.

השימוש מתוך Tik-Nick:
    result = analyze_user_posts(base_url, username, cookie, progress, cancel_flag)
    if result["ok"]:
        html = result["html"]

ללא תלויות חיצוניות — ספרייה סטנדרטית בלבד.
"""
import html as _html_mod
import json
import re
import time
import threading
import urllib.request
import urllib.parse
import urllib.error

# ──────────────────────── קבועים ────────────────────────

DEFAULT_BASE = "https://mitmachim.top"
MAX_PAGES = 1500
PAGE_DELAY = 1.0  # שניות בין בקשות עמודים — כדי לא להעמיס על השרת

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ──────────────── ייבוא אופציונלי של SmartSession ────────────────

try:
    from anti_detect import SmartSession
    _HAS_SMART = True
except ImportError:
    _HAS_SMART = False

# ──────────────────────── ביטויים רגולריים ────────────────────────

# --- טלפונים ישראליים ---
# פלאפון עם קידומת 05X (עם/בלי מקפים)
_RE_MOBILE = re.compile(r'05\d[-–]?\d{3}[-–]?\d{4}')
# טלפון קווי ישראלי (0X-XXXXXXX)
_RE_LANDLINE = re.compile(r'0[2-9][-–]?\d{7}')
# פלאפון עם קידומת בינלאומית +972
_RE_INTL_PLUS = re.compile(r'\+972[-–]?5\d[-–]?\d{3}[-–]?\d{4}')
# פלאפון עם קידומת 972 (ללא פלוס)
_RE_INTL_NO_PLUS = re.compile(r'(?<!\+)972[-–]?5\d[-–]?\d{3}[-–]?\d{4}')

# --- אימיילים ---
_RE_EMAIL = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)

# --- שמות (בעברית, אחרי ביטויים נפוצים) ---
# מילה עברית: לפחות 2 אותיות עבריות (כולל ניקוד אופציונלי)
_HEB_WORD = r'[\u05D0-\u05EA\u05F0-\u05F4][\u05D0-\u05EA\u05B0-\u05BD\u05F0-\u05F4\'"]{1,}'
_NAME_PREFIXES = [
    r'שמי\s+',
    r'(?:אני|אנכי)\s+',
    r'קוראים\s+לי\s+',
    r'השם\s+שלי\s+(?:הוא\s+|היא\s+)?',
    r'שמי\s+(?:הוא\s+|היא\s+)?',
]
# בונים ביטוי שמחפש 2-4 מילים עבריות אחרי כל אחד מהקידומות
_NAME_PATTERN = '(?:' + '|'.join(_NAME_PREFIXES) + ')(' + \
    _HEB_WORD + r'(?:\s+' + _HEB_WORD + r'){0,3})'
_RE_NAME = re.compile(_NAME_PATTERN)

# --- כתובות (ביטויי הקשר) ---
_ADDRESS_PREFIXES = [
    r'גר\s+ב',
    r'מתגורר(?:ת)?\s+ב',
    r'(?:מ|מ-)\s*',
    r'מרחוב\s+',
    r'ממושב\s+',
    r'מקיבוץ\s+',
    r'מישוב\s+',
    r'מיישוב\s+',
    r'מהעיר\s+',
    r'מהיישוב\s+',
    r'בעיר\s+',
    r'ביישוב\s+',
    r'במושב\s+',
    r'בקיבוץ\s+',
]
_ADDRESS_PATTERN = '(?:' + '|'.join(_ADDRESS_PREFIXES) + ')(' + \
    _HEB_WORD + r'(?:\s+' + _HEB_WORD + r'){0,3})'
_RE_ADDRESS = re.compile(_ADDRESS_PATTERN)

# רשימת ערים ישראליות מוכרות (מדגם רחב)
_KNOWN_CITIES = [
    "ירושלים", "תל אביב", "חיפה", "באר שבע", "ראשון לציון", "פתח תקווה",
    "אשדוד", "נתניה", "חולון", "בני ברק", "רמת גן", "אשקלון", "בת ים",
    "הרצליה", "כפר סבא", "רעננה", "מודיעין", "חדרה", "לוד", "רמלה",
    "נצרת", "עכו", "אילת", "קריית גת", "קריית אתא", "קריית ביאליק",
    "קריית מוצקין", "קריית ים", "קריית שמונה", "צפת", "טבריה",
    "עפולה", "יבנה", "אור יהודה", "גבעתיים", "רחובות", "ראש העין",
    "נהריה", "דימונה", "ערד", "ביתר עילית", "מודיעין עילית",
    "אלעד", "בית שמש", "נס ציונה", "שוהם", "גבעת שמואל",
    "כפר יונה", "קרית אונו", "קריית אונו", "זכרון יעקב",
    "טירת הכרמל", "נשר", "מגדל העמק", "יקנעם", "כרמיאל",
    "מעלות", "שלומי", "מעלה אדומים", "אריאל", "גני תקווה",
    "אור עקיבא", "פרדס חנה", "עתלית", "קיסריה", "בנימינה",
    "ראשון", "פ\"ת", "ת\"א", "ב\"ש", "ק\"ג", "ר\"ג",
]
# בונים ביטוי שמזהה שמות ערים בתוך הטקסט
_RE_CITY = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in _KNOWN_CITIES) + r')\b'
)

# --- טלגרם ---
_RE_TELEGRAM_HANDLE = re.compile(r'@([a-zA-Z0-9_]{5,})')
_RE_TELEGRAM_LINK = re.compile(r'(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)')

# --- וואטסאפ ---
_RE_WHATSAPP_LINK = re.compile(r'wa\.me/(\d+)')
_RE_WHATSAPP_API = re.compile(r'api\.whatsapp\.com/send\?phone=(\d+)')


# ──────────────────────── פונקציות עזר ────────────────────────

def _strip_html(text):
    """מסיר תגיות HTML ומנקה ישויות — מחזיר טקסט נקי."""
    if not text:
        return ""
    # מנקים ישויות HTML לפני הסרת תגיות
    text = _html_mod.unescape(text)
    # מסירים תגיות HTML
    text = re.sub(r'<[^>]+>', ' ', text)
    # מנקים רווחים מיותרים
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_context(text, start, end, radius=40):
    """מחלץ הקשר סביב ממצא — כ-40 תווים לכל צד."""
    ctx_start = max(0, start - radius)
    ctx_end = min(len(text), end + radius)
    prefix = "..." if ctx_start > 0 else ""
    suffix = "..." if ctx_end < len(text) else ""
    return prefix + text[ctx_start:ctx_end] + suffix


def _esc(s):
    """בריחה של תווים מיוחדים ל-HTML."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ──────────────────────── חילוץ מידע ────────────────────────

def extract_info(text):
    """
    מחלץ מידע אישי מתוכן פוסט גולמי (HTML).

    מקבל: text — תוכן הפוסט כ-HTML גולמי.
    מחזיר: מילון עם הקטגוריות הבאות:
        phones    — מספרי טלפון ישראליים
        emails    — כתובות דואר אלקטרוני
        names     — שמות פרטיים/משפחה
        addresses — כתובות / ערים
        telegram  — חשבונות/קישורי טלגרם
        whatsapp  — קישורי וואטסאפ

    כל ממצא הוא dict עם: value, context, confidence
    """
    # ניקוי HTML — עובדים על טקסט נקי
    clean = _strip_html(text)

    findings = {
        "phones": [],
        "emails": [],
        "names": [],
        "addresses": [],
        "telegram": [],
        "whatsapp": [],
    }

    # סט לזיהוי כפילויות
    seen = set()

    def _add(category, value, match_obj, confidence):
        """מוסיף ממצא אם עוד לא ראינו אותו."""
        key = (category, value)
        if key in seen:
            return
        seen.add(key)
        context = _extract_context(clean, match_obj.start(), match_obj.end())
        findings[category].append({
            "value": value,
            "context": context,
            "confidence": confidence,
        })

    # ── טלפונים ──
    # קידומת בינלאומית +972 — ביטחון גבוה
    for m in _RE_INTL_PLUS.finditer(clean):
        _add("phones", m.group(), m, "high")

    # קידומת 972 ללא פלוס — ביטחון גבוה
    for m in _RE_INTL_NO_PLUS.finditer(clean):
        _add("phones", m.group(), m, "high")

    # פלאפון 05X — ביטחון גבוה
    for m in _RE_MOBILE.finditer(clean):
        _add("phones", m.group(), m, "high")

    # קווי 0X — ביטחון גבוה
    for m in _RE_LANDLINE.finditer(clean):
        val = m.group()
        # מסננים תבניות שלא נראות כמו טלפון אמיתי
        digits_only = re.sub(r'[-–]', '', val)
        # בודקים שזה לא סתם מספר עם אפס מוביל
        if len(digits_only) >= 9:
            _add("phones", val, m, "high")

    # ── אימיילים ──
    for m in _RE_EMAIL.finditer(clean):
        _add("emails", m.group(), m, "high")

    # ── שמות ──
    for m in _RE_NAME.finditer(clean):
        name = m.group(1).strip()
        # מסננים "שמות" קצרים מדי (מילה אחת של 2 אותיות)
        words = name.split()
        if len(words) >= 1 and any(len(w) > 2 for w in words):
            _add("names", name, m, "medium")

    # ── כתובות (עם הקשר) ──
    for m in _RE_ADDRESS.finditer(clean):
        addr = m.group(1).strip()
        if len(addr) > 2:
            _add("addresses", addr, m, "medium")

    # ── ערים מוכרות (ללא הקשר — ביטחון נמוך) ──
    for m in _RE_CITY.finditer(clean):
        city = m.group(1)
        # בודקים אם העיר כבר נמצאה עם הקשר של כתובת
        if ("addresses", city) not in seen:
            _add("addresses", city, m, "low")

    # ── טלגרם ──
    for m in _RE_TELEGRAM_LINK.finditer(clean):
        _add("telegram", m.group(1), m, "high")

    for m in _RE_TELEGRAM_HANDLE.finditer(clean):
        handle = m.group(1)
        # מסננים מזהים שנראים כמו מילה באנגלית רגילה
        if not handle.lower() in ("admin", "moderator", "member", "guest",
                                   "everyone", "channel", "group", "support"):
            _add("telegram", f"@{handle}", m, "high")

    # ── וואטסאפ ──
    for m in _RE_WHATSAPP_LINK.finditer(clean):
        _add("whatsapp", m.group(1), m, "high")

    for m in _RE_WHATSAPP_API.finditer(clean):
        _add("whatsapp", m.group(1), m, "high")

    return findings


# ──────────────────────── בקשות HTTP ────────────────────────

def _get_json(url, cookie=None, timeout=15):
    """
    בקשת GET שמחזירה JSON — משתמש ב-SmartSession אם זמין, אחרת urllib רגיל.
    """
    if _HAS_SMART:
        try:
            session = SmartSession()
            return session.get_json(url, cookie=cookie, timeout=timeout)
        except Exception:
            # נפילה לגיבוי אם SmartSession נכשל
            pass

    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    req.add_header("Accept", "application/json")
    if cookie:
        val = cookie if cookie.startswith("express.sid=") else f"express.sid={cookie}"
        req.add_header("Cookie", val)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# ──────────────────────── רזולוציית slug ────────────────────────

def _resolve_slug(base, user_input, cookie=None):
    """
    מנסה למצוא את ה-userslug הקנוני של המשתמש.
    מנסה קודם חיפוש לפי username מדויק, אחר כך וריאציות slug.
    """
    raw = (user_input or "").strip().strip("/")
    if "/" in raw:
        raw = raw.split("/")[-1]

    # ניסיון ראשון: חיפוש לפי שם משתמש מדויק
    try:
        data = _get_json(
            f"{base}/api/user/username/{urllib.parse.quote(raw)}",
            cookie=cookie
        )
        if isinstance(data, dict) and data.get("userslug"):
            return data["userslug"]
    except Exception:
        pass

    # וריאציות slug — מקפים, אותיות קטנות
    candidates = [
        raw,
        raw.replace(" ", "-"),
        raw.lower().replace(" ", "-"),
        raw.replace(" ", ""),
    ]
    # מסירים כפילויות תוך שמירה על סדר
    seen_slugs = set()
    unique = []
    for c in candidates:
        if c and c not in seen_slugs:
            seen_slugs.add(c)
            unique.append(c)

    for slug in unique:
        try:
            data = _get_json(
                f"{base}/api/user/{urllib.parse.quote(slug)}",
                cookie=cookie
            )
            if isinstance(data, dict) and (data.get("uid") or data.get("username")):
                return data.get("userslug") or slug
        except Exception:
            continue

    # אם לא מצאנו — מחזירים את הניחוש הטוב ביותר
    return unique[0] if unique else raw


# ──────────────────────── ניתוח פוסטים ────────────────────────

def analyze_user_posts(base_url, username, cookie,
                       progress=None, cancel_flag=None):
    """
    סורק את כל הפוסטים של משתמש ומחלץ מהם מידע אישי.

    פרמטרים:
        base_url    — כתובת בסיס הפורום (לדוגמה: https://mitmachim.top)
        username    — שם המשתמש או ה-slug שלו
        cookie      — עוגיית express.sid לאימות
        progress    — פונקציית callback לדיווח התקדמות (אופציונלית)
        cancel_flag — threading.Event לביטול (אופציונלי)

    מחזיר:
        הצלחה: {"ok": True, "html": "...", "findings": {...}, "post_count": N, "error": None}
        כישלון: {"ok": False, "error": "...", "cancelled": bool}
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")

    # שלב 1: רזולוציית slug
    try:
        slug = _resolve_slug(base, username, cookie=cookie)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "error": "נדרשת עוגייה תקינה (שגיאת הרשאה)",
                    "cancelled": False}
        return {"ok": False, "error": f"שגיאת רשת: {e.code}",
                "cancelled": False}
    except Exception as e:
        return {"ok": False, "error": f"לא ניתן למצוא משתמש: {e}",
                "cancelled": False}

    api = f"{base}/api/user/{urllib.parse.quote(slug)}/posts"

    # שלב 2: סריקת כל הפוסטים
    all_posts = []
    page = 1

    while page <= MAX_PAGES:
        # בדיקת ביטול
        if cancel_flag is not None and cancel_flag.is_set():
            return {"ok": False, "error": "בוטל על ידי המשתמש",
                    "cancelled": True}

        try:
            data = _get_json(f"{api}?page={page}", cookie=cookie)
        except urllib.error.HTTPError as e:
            if page == 1:
                if e.code in (401, 403):
                    return {"ok": False,
                            "error": "נדרשת עוגייה / הרשאה לצפייה בפוסטים",
                            "cancelled": False}
                return {"ok": False, "error": f"שגיאת רשת: {e.code}",
                        "cancelled": False}
            # עמוד שאינו ראשון נכשל — מפסיקים בשקט
            break
        except Exception as e:
            if page == 1:
                return {"ok": False, "error": f"שגיאה בגישה לפוסטים: {e}",
                        "cancelled": False}
            break

        posts = data.get("posts", []) if isinstance(data, dict) else []
        if not posts:
            break

        all_posts.extend(posts)

        # דיווח התקדמות — שלב סריקה
        if progress:
            progress({
                "phase": "scan",
                "count": len(all_posts),
                "total": 0,  # לא ידוע מראש
            })

        page += 1
        time.sleep(PAGE_DELAY)

    if not all_posts:
        return {"ok": False,
                "error": "לא נמצאו פוסטים למשתמש זה",
                "cancelled": False}

    # שלב 3: חילוץ מידע מכל פוסט
    # מילון מצטבר של כל הממצאים
    all_findings = {
        "phones": [],
        "emails": [],
        "names": [],
        "addresses": [],
        "telegram": [],
        "whatsapp": [],
    }
    # סט גלובלי לסינון כפילויות בין פוסטים
    global_seen = set()

    total_posts = len(all_posts)
    for idx, post in enumerate(all_posts):
        # בדיקת ביטול
        if cancel_flag is not None and cancel_flag.is_set():
            return {"ok": False, "error": "בוטל על ידי המשתמש",
                    "cancelled": True}

        content = post.get("content") or ""
        pid = post.get("pid")

        # כותרת הנושא
        topic = post.get("topic") or {}
        title = topic.get("title", "") if isinstance(topic, dict) else ""

        post_findings = extract_info(content)

        # מוסיפים pid ו-title לכל ממצא, ומסננים כפילויות גלובליות
        for category, items in post_findings.items():
            for item in items:
                gkey = (category, item["value"])
                if gkey not in global_seen:
                    global_seen.add(gkey)
                    item["pid"] = pid
                    item["title"] = title
                    all_findings[category].append(item)

        # דיווח התקדמות — שלב חילוץ
        if progress and (idx + 1) % 10 == 0:
            progress({
                "phase": "extract",
                "count": idx + 1,
                "total": total_posts,
            })

    # דיווח סופי
    if progress:
        progress({
            "phase": "extract",
            "count": total_posts,
            "total": total_posts,
        })

    # שלב 4: בניית דוח HTML
    html = _build_html(slug, all_findings, total_posts, base)

    return {
        "ok": True,
        "html": html,
        "findings": all_findings,
        "post_count": total_posts,
        "error": None,
    }


# ──────────────────────── בניית דוח HTML ────────────────────────

def _build_html(username, findings, post_count, base_url=DEFAULT_BASE):
    """
    מייצר דוח HTML אינטראקטיבי עם כל הממצאים.

    הדוח בעיצוב כהה (דומה ל-stinknik / chazonishnik),
    עם סקציה לכל סוג ממצא, תגיות ביטחון, והקשר ציטוט.
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")

    # ספירת ממצאים כוללת
    total_findings = sum(len(v) for v in findings.values())

    # סמלי קטגוריות
    _ICONS = {
        "phones": "📱",
        "emails": "📧",
        "names": "👤",
        "addresses": "📍",
        "telegram": "✈️",
        "whatsapp": "💬",
    }
    _TITLES = {
        "phones": "מספרי טלפון",
        "emails": "כתובות מייל",
        "names": "שמות",
        "addresses": "כתובות / ערים",
        "telegram": "טלגרם",
        "whatsapp": "וואטסאפ",
    }
    _BORDER_COLORS = {
        "phones": "#38bdf8",
        "emails": "#10b981",
        "names": "#f59e0b",
        "addresses": "#a78bfa",
        "telegram": "#3b82f6",
        "whatsapp": "#22c55e",
    }

    # בניית סקציות HTML
    sections_html = ""
    for category in ("phones", "emails", "names", "addresses", "telegram", "whatsapp"):
        items = findings.get(category, [])
        icon = _ICONS[category]
        title = _TITLES[category]
        border_color = _BORDER_COLORS[category]
        count = len(items)

        if count == 0:
            # סקציה ריקה — מציגים הודעה קצרה
            sections_html += f'''
            <div class="section">
              <h2>{icon} {title} <span class="section-count">0</span></h2>
              <div class="empty-msg">לא נמצאו ממצאים בקטגוריה זו</div>
            </div>'''
            continue

        items_html = ""
        for item in items:
            value = _esc(item["value"])
            context = _esc(item.get("context", ""))
            confidence = item.get("confidence", "medium")
            pid = item.get("pid")
            # תגית ביטחון
            conf_class = {
                "high": "conf-high",
                "medium": "conf-medium",
                "low": "conf-low",
            }.get(confidence, "conf-medium")
            conf_label = {
                "high": "גבוה",
                "medium": "בינוני",
                "low": "נמוך",
            }.get(confidence, "בינוני")

            # קישור לפוסט המקורי
            post_link = ""
            if pid:
                post_link = (
                    f'<a href="{base}/post/{pid}" target="_blank" '
                    f'class="post-link-btn">🔗 פוסט #{pid}</a>'
                )

            items_html += f'''
              <div class="finding-card" style="border-right-color:{border_color}">
                <div class="finding-header">
                  <span class="finding-value">{value}</span>
                  <span class="conf-badge {conf_class}">{conf_label}</span>
                  <button class="apply-btn" onclick="applyToNick('{value}', '{category}')"
                    title="החל ערך זה על הניק הנוכחי">החל על הניק</button>
                </div>
                <div class="finding-context">
                  <span class="quote-mark">❝</span>{context}<span class="quote-mark">❞</span>
                </div>
                <div class="finding-footer">
                  {post_link}
                </div>
              </div>'''

        sections_html += f'''
            <div class="section">
              <h2>{icon} {title} <span class="section-count">{count}</span></h2>
              {items_html}
            </div>'''

    # הרכבת ה-HTML המלא
    html = _REPORT_TEMPLATE \
        .replace("__USERNAME__", _esc(username)) \
        .replace("__POST_COUNT__", str(post_count)) \
        .replace("__FINDING_COUNT__", str(total_findings)) \
        .replace("__SECTIONS__", sections_html) \
        .replace("__BASE_URL__", _esc(base))

    return html


# ──────────────────────── תבנית HTML ────────────────────────

_REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<title>חילוץ מידע — __USERNAME__</title>
<style>
/* ── בסיס ── */
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:'Segoe UI',Tahoma,Arial,sans-serif;
  background:#0f172a;color:#f1f5f9;
  padding:40px 20px;
  line-height:1.6;
}
.container{max-width:900px;margin:auto}

/* ── כותרת ── */
.header{
  background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);
  border:1px solid #334155;border-radius:20px;
  padding:36px 30px;text-align:center;
  margin-bottom:30px;
}
.header h1{color:#38bdf8;font-size:1.8rem;margin-bottom:8px}
.header .subtitle{color:#94a3b8;font-size:1rem}

/* ── כרטיסי סטטיסטיקה ── */
.stats-row{
  display:flex;gap:16px;margin-bottom:30px;flex-wrap:wrap;
  justify-content:center;
}
.stat-card{
  background:#1e293b;border:1px solid #334155;border-radius:14px;
  padding:22px 28px;text-align:center;flex:1;min-width:140px;
}
.stat-card h3{font-size:2.2rem;color:#38bdf8;margin:0}
.stat-card.accent h3{color:#10b981}
.stat-card p{color:#94a3b8;font-size:.85rem;font-weight:600;margin-top:4px}

/* ── סקציות ── */
.section{
  background:#1e293b;border:1px solid #334155;border-radius:16px;
  padding:24px 28px;margin-bottom:20px;
}
.section h2{
  font-size:1.15rem;color:#e2e8f0;
  border-bottom:1px solid #334155;padding-bottom:12px;
  margin-bottom:16px;display:flex;align-items:center;gap:8px;
}
.section-count{
  background:#0c4a6e;color:#38bdf8;
  padding:2px 10px;border-radius:20px;
  font-size:.8rem;font-weight:700;margin-right:auto;
}
.empty-msg{
  color:#64748b;text-align:center;font-size:.95rem;padding:14px 0;
}

/* ── כרטיס ממצא ── */
.finding-card{
  background:#0f172a;border:1px solid #334155;
  border-right:5px solid #38bdf8;
  border-radius:10px;padding:16px 18px;
  margin-bottom:12px;
  transition:transform .2s,border-color .2s;
}
.finding-card:hover{
  transform:translateY(-2px);
  border-color:#475569;
}
.finding-header{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  margin-bottom:10px;
}
.finding-value{
  font-size:1.1rem;font-weight:700;color:#fff;
  direction:ltr;unicode-bidi:embed;
  background:#1e293b;padding:4px 12px;border-radius:6px;
}
.conf-badge{
  font-size:.75rem;font-weight:700;
  padding:3px 10px;border-radius:20px;
}
.conf-high{background:#052e2b;color:#10b981}
.conf-medium{background:#422006;color:#fbbf24}
.conf-low{background:#3b0a0a;color:#f87171}

/* ── כפתור "החל על הניק" ── */
.apply-btn{
  margin-right:auto;
  background:linear-gradient(135deg,#0c4a6e,#1e3a5f);
  color:#38bdf8;border:1px solid #38bdf8;
  padding:5px 14px;border-radius:6px;
  font-weight:700;font-size:.8rem;cursor:pointer;
  font-family:inherit;
  transition:all .2s;
}
.apply-btn:hover{background:#38bdf8;color:#0f172a}

/* ── ציטוט הקשר ── */
.finding-context{
  color:#94a3b8;font-size:.88rem;
  padding:8px 12px;
  background:#1e293b;border-radius:6px;
  direction:rtl;line-height:1.7;
}
.quote-mark{color:#475569;font-size:1rem;margin:0 2px}

/* ── קישור לפוסט ── */
.finding-footer{margin-top:8px}
.post-link-btn{
  color:#38bdf8;text-decoration:none;font-size:.82rem;
  font-weight:600;
}
.post-link-btn:hover{text-decoration:underline}

/* ── סרגל גלילה ── */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-thumb{background:#475569;border-radius:3px}
::-webkit-scrollbar-track{background:#0f172a}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🔍 חילוץ מידע — __USERNAME__</h1>
    <div class="subtitle">ניתוח אוטומטי של פוסטים לזיהוי מידע אישי</div>
  </div>

  <div class="stats-row">
    <div class="stat-card">
      <h3>__POST_COUNT__</h3>
      <p>פוסטים שנסרקו</p>
    </div>
    <div class="stat-card accent">
      <h3>__FINDING_COUNT__</h3>
      <p>ממצאים שנמצאו</p>
    </div>
  </div>

  __SECTIONS__

</div>

<script>
/* כפתור "החל על הניק" — שולח הודעת postMessage לאפליקציית Tik-Nick */
function applyToNick(value, category) {
  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({
        type: "apply_to_nick",
        value: value,
        category: category,
        source: "data_extractor"
      }, "*");
    }
  } catch(e) {
    /* אם postMessage נכשל — לא קורה כלום */
  }
}
</script>
</body>
</html>"""


# ──────────────────────── נקודת כניסה לבדיקה ────────────────────────

if __name__ == "__main__":
    # בדיקה מהירה של חילוץ מידע מטקסט לדוגמה
    sample = """
    <p>שלום לכולם, שמי <b>משה כהן</b> ואני גר בבני ברק.
    אפשר ליצור איתי קשר בטלפון 054-1234567 או במייל moshe@gmail.com.
    אפשר גם דרך הטלגרם שלי @moshe_cohen123 או בוואטסאפ wa.me/972541234567.
    אני מרחוב הרצל 15.</p>
    """
    results = extract_info(sample)
    print(json.dumps(results, ensure_ascii=False, indent=2))
