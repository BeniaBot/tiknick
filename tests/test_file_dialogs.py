# -*- coding: utf-8 -*-
"""
כל מסנן קבצים בתוכנה עובר את הבודק **האמיתי** של pywebview.

🚨 הבאג שהבדיקה נולדה ממנו: pywebview מקבל בתיאור המסנן רק אותיות, ספרות
ורווחים (`^([\\w ]+)\\(`), והמקף ב-"Tik-Nick" פסל שלושה דיאלוגים:

  * ייבוא          — שבור מ-0.8.7  ("קובץ Tik-Nick (*.tiknick;*.json)")
  * גיבוי מלא      — שבור מ-0.8.4  ("Tik-Nick backup (*.db)")
  * שחזור מגיבוי   — אותו מסנן

כל שלושת הכפתורים זרקו ValueError ברגע שחלון בחירת הקובץ היה אמור להיפתח.
הייבוא הוא מה שבנימין שם לב אליו; הגיבוי והשחזור — רשת הביטחון של
המאגר — היו מתים באותה מידה, ואיש לא ידע.

הבדיקה סורקת את main.py ולא רשימה ידנית, כך שמסנן חדש שיתווסף ייבדק לבד.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


try:
    from webview.util import parse_file_type
except Exception as e:        # pywebview לא מותקן — אין מה לבדוק מולו
    print("SKIP  pywebview אינו זמין: %s" % e)
    sys.exit(0)

src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()

# כל מחרוזת בצורת "תיאור (*.סיומת...)" בתוך קריאה ל-file_types
blocks = re.findall(r"file_types\s*=\s*\((.*?)\)\s*\)", src, re.S)
filters = []
for b in blocks:
    filters += re.findall(r'"([^"]*\(\*[^"]*\))"', b)

ok("נמצאו מסנני קבצים לבדיקה", len(filters) >= 6, len(filters))

for f in sorted(set(filters)):
    try:
        parse_file_type(f)
        good = True
    except ValueError:
        good = False
    ok("pywebview מקבל: %s" % f, good)

# שלושת הדיאלוגים שנשברו — בשמם, כדי שהבדיקה תיכשל בקול אם ישתנו שוב
for fn in ("load_import_file", "backup_db", "restore_db"):
    i = src.index("def %s(" % fn)
    body = src[i:i + 4000]
    nxt = body.find("\n    def ", 10)
    body = body[:nxt] if nxt > 0 else body
    fs = re.findall(r'"([^"]*\(\*[^"]*\))"', body)
    ok("%s: יש מסנן" % fn, bool(fs))
    for f in fs:
        try:
            parse_file_type(f)
            good = True
        except ValueError:
            good = False
        ok("  %s נפתח" % fn, good, f)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("FILE DIALOG TESTS PASSED")
