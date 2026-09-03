# -*- coding: utf-8 -*-
"""
ייבוא CSV/TSV — פענוח קובץ, ניחוש מפריד, והתאמת עמודות לשדות הניק.

הכל כאן פונקציות טהורות: אין sqlite, אין webview, אין גישה למאגר. הפלט הוא
בדיוק המבנה ש-db.import_data מקבל ({"exported_fields": [...], "nicks": [...]}),
כדי שהייבוא מקובץ אקסל יעבור באותו מנוע מקורות כמו קובץ .tiknick — עם מקור
ייבוא, דרגת אמינות והכרעה — ולא ייכתב ישירות לטבלת הניקים.
"""
import csv
import io
import os

from database import ALL_NICK_FIELDS

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 300000

_BOMS = [(b"\xef\xbb\xbf", "utf-8-sig"),
         (b"\xff\xfe\x00\x00", "utf-32"), (b"\x00\x00\xfe\xff", "utf-32"),
         (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")]


def read_text(path):
    """
    מפענח קידוד: BOM ← UTF-16 בלי BOM ← UTF-8 קפדני ← cp1255.
    הסדר קריטי: cp1255 מפענח כמעט כל רצף בתים בלי לזרוק שגיאה, ולכן חייב להיות
    אחרון — אחרת קובץ UTF-8 עברי היה מתפענח בשקט לג'יבריש.
    """
    with open(path, "rb") as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("הקובץ גדול מ-64MB — חתוך אותו לחלקים")
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace"), enc
    head = raw[:4096]
    if head.count(b"\x00") > len(head) // 4:          # Excel "Unicode Text" בלי BOM
        enc = "utf-16-le" if head[1:2] == b"\x00" else "utf-16-be"
        return raw.decode(enc, errors="replace"), enc
    try:
        return raw.decode("utf-8"), "utf-8"           # קפדני בכוונה
    except UnicodeDecodeError:
        pass
    return raw.decode("cp1255", errors="replace"), "cp1255"


_CANDIDATES = ["\t", ",", ";", "|"]


def sniff_delimiter(text, ext=""):
    """
    לא csv.Sniffer: הוא מנחש לפי תדירות פיסוק ונופל על טקסט חופשי בעברית
    (גרשיים, פסיקים בתוך הערות). כאן רשימת מועמדים קבועה, והזוכה הוא זה שנותן
    הכי הרבה עמודות בעקביות על פני השורות הראשונות.
    """
    if (ext or "").lower() == ".tsv":
        return "\t"
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    if not lines:
        return ","
    best, best_score = ",", -1
    for d in _CANDIDATES:
        try:
            counts = [len(r) for r in csv.reader(lines, delimiter=d) if r]
        except Exception:
            continue
        if not counts or counts[0] < 2:
            continue
        agree = sum(1 for c in counts if c == counts[0])
        score = counts[0] * 100 + agree
        if score > best_score:
            best, best_score = d, score
    return best


def unquote_cell(s):
    """
    מבטל את מה ש-export_csv עשה לתא כדי שאקסל לא יהרוס אותו:
      ="0501234567"  →  0501234567          (אפס מוביל שנשמר)
      '=SUM(...)     →  =SUM(...)           (קידומת נגד הזרקת נוסחאות)
    גרש בודד שאינו לפני תו נוסחה נשאר במקומו (ר' משה, ז'אנר).
    """
    s = "" if s is None else str(s)
    s = s.replace("﻿", "").strip()
    if len(s) >= 3 and s.startswith('="') and s.endswith('"'):
        return s[2:-1]
    if len(s) >= 2 and s[0] == "'" and s[1] in "=+-@\t\r":
        return s[1:]
    return s


# שמות שדה שאסור לייבא מ-CSV גם אם מופיעה עמודה כזו:
# האמינות נקבעת ע"י מקור הייבוא, והשדות ה"סרוקים" הם השוואה פנימית של המנוע.
_BLOCKED = {"trust_level", "source", "scraped_real_name", "scraped_email",
            "created_at", "updated_at", "id", "forum_uid"}

FIELD_NOTES = {
    "trust_level": "לא מיובא — האמינות נקבעת לפי מקור הייבוא",
    "status":      "סטטוס שנסרק מהפורום גובר על ערך מהקובץ",
    "reputation":  "מוניטין נקבע לפי הסריקה בלבד",
}

# כינויים נפוצים בעברית ובאנגלית, מעבר לתוויות הרשמיות של ALL_NICK_FIELDS
_ALIASES = {
    "ניק": "username", "שם הניק": "username", "משתמש": "username",
    "שם משתמש": "username", "user": "username", "username": "username",
    "nick": "username", "פורום": "forum", "forum": "forum",
    "אתר": "forum", "טלפון": "phone", "נייד": "phone", "פלאפון": "phone",
    "phone": "phone", "mobile": "phone", "מייל": "email", "אימייל": "email",
    "דואל": "email", "email": "email", "e-mail": "email",
    "שם": "real_name", "שם אמיתי": "real_name", "name": "real_name",
    "שם מלא": "full_name", "full name": "full_name", "fullname": "full_name",
    "כתובת": "address", "address": "address", "עיר": "address",
    "הערות": "notes", "notes": "notes", "הערה": "notes",
    "קבוצות": "groups", "groups": "groups", "תפקיד": "groups",
    "סטטוס": "status", "status": "status",
}


def _norm_header(h):
    return " ".join(str(h or "").replace("﻿", "").strip().lower().split())


def auto_map(headers):
    """
    מיפוי אוטומטי של כותרות → שדות. הקובץ שהתוכנה עצמה מייצאת נפתר ב-100%
    כי export_csv כותב בדיוק את התוויות של ALL_NICK_FIELDS.
    מחזיר {index_as_str: field_key} — רק לעמודות שזוהו.
    """
    by_label = {}
    for key, label, _ in ALL_NICK_FIELDS:
        by_label[_norm_header(label)] = key
        by_label[_norm_header(key)] = key
    out, used = {}, set()
    for i, h in enumerate(headers):
        n = _norm_header(unquote_cell(h))
        key = by_label.get(n) or _ALIASES.get(n)
        if key and key not in _BLOCKED and key not in used:
            out[str(i)] = key
            used.add(key)
    return out


def mappable_fields():
    """השדות שמותר למפות אליהם, לבורר בממשק."""
    return [{"key": k, "label": l, "note": FIELD_NOTES.get(k, "")}
            for k, l, _ in ALL_NICK_FIELDS if k not in _BLOCKED]


def parse_file(path):
    text, enc = read_text(path)
    delim = sniff_delimiter(text, os.path.splitext(path)[1])
    rdr = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    rows, headers = [], None
    for r in rdr:
        if headers is None:
            if not any((c or "").strip() for c in r):
                continue                          # שורות ריקות לפני הכותרת
            headers = [unquote_cell(c) for c in r]
            continue
        if not any((c or "").strip() for c in r):
            continue
        rows.append(r)
        if len(rows) > MAX_ROWS:
            raise ValueError("הקובץ מכיל יותר מ-300,000 שורות")
    if not headers:
        raise ValueError("לא נמצאה שורת כותרות בקובץ")
    sample = {}
    for i in range(len(headers)):
        for r in rows[:20]:
            v = unquote_cell(r[i]) if i < len(r) else ""
            if v:
                sample[str(i)] = v[:60]
                break
    return {"encoding": enc, "delimiter": delim, "headers": headers,
            "rows": rows, "sample": sample, "row_count": len(rows),
            "mapping": auto_map(headers)}


def normalize_rows(headers, rows, mapping, default_forum="כללי", fix_phone=True):
    """
    הופך שורות CSV למבנה ש-db.import_data מקבל.
    שורה בלי שם משתמש מדולגת; שורה בלי פורום מקבלת את ברירת המחדל.
    (פורום, שם משתמש) שחוזר בקובץ מאוחד לרשומה אחת — הערך האחרון מנצח —
    אחרת היו נוצרים שני ניקים שסריקה עתידית תתאים רק לאחד מהם.
    """
    idx = {int(i): f for i, f in (mapping or {}).items()
           if str(f) and str(f) not in _BLOCKED}
    if "username" not in idx.values():
        raise ValueError("חובה למפות עמודה ל'שם משתמש'")
    fields = sorted(set(idx.values()) | {"forum", "username"})
    out, seen = [], {}
    skipped_no_username = merged = 0
    for r in rows:
        rec = {}
        for i, field in idx.items():
            v = unquote_cell(r[i]) if i < len(r) else ""
            if v:
                rec[field] = v
        username = (rec.get("username") or "").strip()
        if not username:
            skipped_no_username += 1
            continue
        forum = (rec.get("forum") or "").strip() or default_forum
        rec["forum"], rec["username"] = forum, username
        if fix_phone and rec.get("phone"):
            p = rec["phone"].strip()
            # אקסל בולע אפס מוביל: 501234567 → 0501234567
            if p.isdigit() and len(p) == 9 and p[0] in "5723489":
                rec["phone"] = "0" + p
        key = (forum, username)
        if key in seen:
            seen[key].update(rec)
            merged += 1
            continue
        seen[key] = rec
        out.append(rec)
    return {"exported_fields": fields, "nicks": out, "version": 2,
            "skipped_no_username": skipped_no_username, "merged_dupes": merged}
