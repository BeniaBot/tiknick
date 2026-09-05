# -*- coding: utf-8 -*-
"""
0.8.19: ממשק באנגלית.

התרגום נעשה על ה-DOM אחרי הבנייה, ולכן הסיכון האמיתי הוא לא "מחרוזת שלא
תורגמה" אלא **מנוע שרץ גם בעברית** או קובץ שנוצר לא מסונכרן עם הקטלוג.
הבדיקות כאן שומרות בדיוק על זה.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

fails = []


def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)


HE = re.compile(r"[֐-׿]")

# ── הקטלוג עצמו ───────────────────────────────────────────────────────────
cat_path = os.path.join(ROOT, "i18n_catalog.json")
ok("קטלוג התרגום קיים", os.path.exists(cat_path))
catalog = json.load(io.open(cat_path, encoding="utf-8"))
ok("יש בקטלוג מאות מחרוזות", len(catalog) > 800, str(len(catalog)))

extra_path = os.path.join(ROOT, "i18n_extra.json")
extra = json.load(io.open(extra_path, encoding="utf-8")) if os.path.exists(extra_path) else []
allrows = catalog + extra

ok("לכל רשומה יש he/en/kind",
   all(r.get("he") and r.get("en") and r.get("kind") in ("static", "pattern") for r in allrows))
ok("אין תרגום ריק", all(r["en"].strip() for r in allrows))
# רשומה שזהה למקור מותרת רק כשאין בה מה לתרגם (שם מותג, תבנית ריקה) —
# הבנייה מדלגת עליהן ממילא. עברית זהה = תרגום שנשכח.
same = [r["he"] for r in allrows if r["en"].strip() == r["he"].strip() and HE.search(r["he"])]
ok("אין מחרוזת עברית שנשארה בלי תרגום", not same, str(same[:3]))
ok("לתרגום אין אותיות עבריות",
   all(not HE.search(r["en"]) for r in allrows),
   str([r["en"] for r in allrows if HE.search(r["en"])][:2]))

# תבנית: כל סוגר באנגלית חייב להופיע גם בעברית, אחרת ההחלפה תיצור "$3" גלוי
bad = []
for r in allrows:
    if r["kind"] != "pattern":
        continue
    src = set(re.findall(r"\{(\d+)\}", r["he"]))
    dst = set(re.findall(r"\{(\d+)\}", r["en"]))
    if not src or not dst <= src:
        bad.append(r["he"][:40])
ok("סוגרי התבניות מתאימים בין השפות", not bad, str(bad[:3]))

# ── הקובץ שנוצר חייב להיות מסונכרן עם הקטלוג ──────────────────────────────
js_path = os.path.join(ROOT, "web", "i18n.js")
ok("web/i18n.js קיים", os.path.exists(js_path))
js = io.open(js_path, encoding="utf-8").read()

import build_i18n  # noqa: E402

body, n_static, n_pat = build_i18n.build(allrows)
ok("i18n.js מסונכרן עם הקטלוג (הרץ tools/build_i18n.py)",
   js.startswith(body), "%d/%d" % (n_static, n_pat))

for sym in ("I18N_EN", "I18N_EN_NORM", "I18N_EN_PAT", "applyLang", "i18nBlocks", "i18nStart"):
    ok("המנוע כולל %s" % sym, sym in js)

# המנוע לא רץ בעברית — זו ההגנה על מצב ברירת המחדל
ok("ה-observer מותנה בשפה", "if (I18N_LANG === 'en') i18nStart(); else i18nStop();" in js)
ok("i18nTree יוצא מיד בעברית", "if (I18N_LANG !== 'en' || !root) return;" in js)

# ── החיווט בממשק ──────────────────────────────────────────────────────────
idx = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
ok("i18n.js נטען לפני app.js",
   idx.index('src="i18n.js"') < idx.index('src="app.js"'))
ok("הטבלה מסומנת כנתונים ולא כממשק", 'id="tbody" data-no-i18n' in idx)
ok("הכרטיסים מסומנים כנתונים", 'id="cards-grid" data-no-i18n' in idx)

app = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
ok("DISPLAY מחזיק שפה", "lang: 'he'" in app)
ok("השפה מוחלת בטעינת ההגדרות", "applyLang(DISPLAY.lang || 'he')" in app)
ok("החלפת שפה טוענת מחדש", "location.reload();   // הטקסט הוחלף במקום" in app)
ok("יש בורר שפה בהגדרות התצוגה", "שפה / Language" in app)

# גרירת רוחב עמודה חייבת להתהפך ב-LTR, אחרת הגרירה עובדת הפוך באנגלית
ok("גרירת העמודות מודעת לכיוון", "_rtl ? (_colDrag.startX - e.clientX)" in app)

css = io.open(os.path.join(ROOT, "web", "style.css"), encoding="utf-8").read()
ok("יש בלוק פריסה ל-LTR", '[data-lang="en"] body{direction:ltr}' in css)
ok("הסרגל מחליף צד באנגלית", '[data-lang="en"] #sidebar{border-left:none' in css)

# ── מחרוזות מפתח שחייבות להיות מכוסות ─────────────────────────────────────
keys = {r["he"] for r in allrows}
must = ["ניק חדש", "תצוגת משתמש", "זהויות", "ערוך ניק", "מחק ניק", "ייצוא", "ייבוא",
        "גיבוי מלא", "שחזור מגיבוי", "ניהול פורומים", "הגדרות סנכרון", "הגדרות תצוגה",
        "סנכרון לאינטרנט", "סל מחזור", "בריאות המאגר", "איפוס נתונים", "אודות"]
missing = [m for m in must if m not in keys]
ok("כל כפתורי התפריט מתורגמים", not missing, str(missing))

# כל תווית של כפתור בתפריט חייבת להיות בקטלוג — התפריט הוא הדבר הראשון שרואים
nav_labels = re.findall(r'<span class="icon">[^<]*</span>\s*([^\n<]+)', idx)
nav_missing = [t.strip() for t in nav_labels if t.strip() and t.strip() not in keys]
ok("אין תווית תפריט שנשארה בלי תרגום", not nav_missing, str(nav_missing))

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("I18N TESTS PASSED")
