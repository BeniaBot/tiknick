# -*- coding: utf-8 -*-
"""
תרגום צד-פייתון — לדוחות ולגיליון ההדפסה בלבד.

הממשק עצמו מתורגם בדפדפן (`web/i18n.js`, תרגום ה-DOM אחרי הבנייה), אבל הדוחות
של Chazonishnik ו-Stinknik והגיליון להדפסה הם **מסמכים נפרדים** שנוצרים כאן:
הדוחות יושבים ב-iframe עם sandbox ללא allow-same-origin, ולכן ה-observer של
החלון הראשי לא יכול לגעת בהם, והגיליון בכלל נפתח בדפדפן החיצוני.

הדפוס: כל הדוחות בנויים כתבנית סטטית עם מצייני מקום (`__USER__`, `__FIELDS__`)
שמוחלפים בנתונים **אחרי** הבנייה. לכן מתרגמים את **התבנית**, לפני ההחלפה —
כך שהתרגום נוגע אך ורק בטקסט הממשק ולעולם לא בנתוני המשתמש או הפורום.
"""
import io
import json
import os
import re
import sys

_MAP = None
_RX = None
_LANG = "he"

_HE_LETTER = re.compile(r"[א-ת]")


def _resource(rel):
    """אותה לוגיקה כמו main.resource_path — הקובץ ארוז בתוך ה-EXE."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _load():
    global _MAP, _RX
    if _MAP is not None:
        return
    try:
        _MAP = json.load(io.open(_resource("i18n_en.json"), encoding="utf-8"))
    except Exception:
        _MAP = {}          # בלי קטלוג פשוט לא מתרגמים; לא מפילים דוח
    # מפתח קצר בן מילה אחת אסור להיכנס להחלפה על טקסט חופשי: "כל" היה הופך
    # כל "כל" בתבנית — כולל בתוך הערות קוד — ל-"Every", ו"שני" ל-"Monday".
    # ביטוי בן כמה מילים, או מילה ארוכה, אינו מתנגש בפועל.
    keys = [k for k in _MAP if len(k) >= 6 or " " in k]
    if keys:
        # הארוכות קודם: חלופה ב-alternation נבחרת לפי הסדר, ולכן מיון לפי אורך
        # יורד נותן "התאמה ארוכה ביותר" בכל מיקום.
        keys.sort(key=len, reverse=True)
        _RX = re.compile("|".join(re.escape(k) for k in keys))
    else:
        _RX = None


def set_lang(lang):
    global _LANG
    _LANG = "en" if lang == "en" else "he"


def lang():
    return _LANG


def t(s):
    """תרגום מחרוזת בודדת. מחזירה אותה כמו שהיא אם אין תרגום."""
    if _LANG != "en" or not s:
        return s
    _load()
    return _MAP.get(str(s).strip(), s)


def translate_template(html, extra=None):
    """
    מתרגמת תבנית HTML שלמה. **חובה להריץ לפני הזרקת הנתונים** — התבנית
    מכילה רק טקסט ממשק, ולכן החלפה בה בטוחה לחלוטין.

    `extra` הוא מילון מקומי של המודול, למחרוזות קצרות שאסור להן לשבת בקטלוג
    המשותף (חיבורים כמו "מול" או "פי ") אבל בתבנית הספציפית הזו הן חד-משמעיות.
    """
    if _LANG != "en" or not html:
        return html
    _load()
    rx, mp = _RX, _MAP
    if extra:
        mp = dict(_MAP)
        mp.update(extra)
        keys = [k for k in mp if len(k) >= 6 or " " in k or k in extra]
        keys.sort(key=len, reverse=True)
        rx = re.compile("|".join(re.escape(k) for k in keys))
    if not rx:
        return html

    def sub(m):
        i, j = m.start(), m.end()
        # לא להחליף באמצע מילה עברית ארוכה יותר שאינה עצמה מפתח בקטלוג
        before = html[i - 1] if i else ""
        after = html[j] if j < len(html) else ""
        if _HE_LETTER.match(before) or _HE_LETTER.match(after):
            return m.group(0)
        # הערות קוד בתוך <script> אינן ממשק. הן כתובות בעברית, וללא הסינון
        # הזה תרגום של ביטוי מתוכן הופך אותן לג'יבריש דו-לשוני.
        line_start = html.rfind("\n", 0, i) + 1
        if "//" in html[line_start:i]:
            return m.group(0)
        return mp[m.group(0)]

    # מסמך באנגלית אינו RTL
    html = html.replace('dir="rtl"', 'dir="ltr"').replace('lang="he"', 'lang="en"')
    return rx.sub(sub, html)
