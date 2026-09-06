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

# ── צד הפייתון: הדוחות והגיליון להדפסה ───────────────────────────────────
py_cat = os.path.join(ROOT, "i18n_en.json")
ok("i18n_en.json קיים (הקטלוג של הדוחות)", os.path.exists(py_cat))

import i18n as pyi18n  # noqa: E402
import chazonishnik, stinknik, profile_sheet  # noqa: E402

# בעברית שום דבר לא זז — זו ברירת המחדל וחייבת להישאר זהה בת-בית
pyi18n.set_lang("he")
ok("בעברית התבנית חוזרת כמו שהיא",
   pyi18n.translate_template(stinknik._TEMPLATE) == stinknik._TEMPLATE)
ok("בעברית t() מחזירה את המקור", pyi18n.t("ניק חדש") == "ניק חדש")
ok("שמות הימים בעברית", chazonishnik._days()[0] == "שני")

pyi18n.set_lang("en")
ok("באנגלית t() מתרגמת", pyi18n.t("ניק חדש") == "New nick", pyi18n.t("ניק חדש"))
ok("שמות הימים באנגלית", chazonishnik._days()[0] == "Monday")

# מפתח קצר בן מילה אחת חייב להישאר מחוץ למנוע התבניות: "כל" היה הופך כל
# מופע בתבנית — כולל בהערות קוד — ל-"Every".
pyi18n._load()
short = [k for k in pyi18n._MAP if len(k) < 6 and " " not in k]
ok("יש מפתחות קצרים בקטלוג (הבדיקה רלוונטית)", len(short) > 0, str(len(short)))
ok("מפתח קצר לא נכנס למנוע התבניות",
   all(not pyi18n._RX.fullmatch(k) for k in short[:40]))

# הערת קוד עברית בתוך <script> אינה ממשק ואסור לתרגם אותה
probe = "\n".join(["<script>", "// הערה בעברית: ניק חדש", "const x=1;",
                  "</script>", "<div>ניק חדש</div>"])
out = pyi18n.translate_template(probe)
ok("הערת קוד לא מתורגמת", "// הערה בעברית: ניק חדש" in out)
ok("טקסט ממשק כן מתורגם", "<div>New nick</div>" in out, out[-40:])

# ארבע התבניות חייבות לצאת נקיות לגמרי מעברית (מלבד הערות קוד)
def leftovers(html):
    out = []
    for ln in html.splitlines():
        if ln.strip().startswith("//") or not HE.search(ln):
            continue
        out += [h.strip() for h in re.findall(r"[^<>\"'{};()]*[֐-׿][^<>\"'{};()]*", ln) if h.strip()]
    return sorted(set(out))

for nm, html in (
    ("Stinknik", pyi18n.translate_template(stinknik._TEMPLATE, stinknik._TPL_EN)),
    ("Chazonishnik", pyi18n.translate_template(chazonishnik.HTML_TEMPLATE, chazonishnik._TPL_EN)),
    ("השוואה", pyi18n.translate_template(chazonishnik.COMPARE_TEMPLATE, chazonishnik._CMP_EN)),
    ("גיליון הדפסה", pyi18n.translate_template(profile_sheet._TEMPLATE)),
):
    lo = leftovers(html)
    ok("תבנית %s מתורגמת במלואה" % nm, not lo, str(lo[:3]))

ok("מסמך באנגלית אינו RTL",
   'dir="rtl"' not in pyi18n.translate_template(stinknik._TEMPLATE, stinknik._TPL_EN))

# הדוח כולו, כולל מה שנבנה בקוד ולא בתבנית
report = stinknik._build_html("beni", [], 120, 5, 3, 2, postcount=300)
ok("דוח Stinknik מלא יוצא באנגלית", not HE.search(report),
   str(sorted(set(re.findall(r"[֐-׿]+", report)))[:3]))

sheet = profile_sheet.build_sheet(
    {"nick": {"username": "beni", "forum": "F", "notes": "n"}, "members": [],
     "fields": [], "contacts": [], "history": [],
     "truncated_members": 0, "truncated_history": 0}, generated="x")
ok("גיליון ההדפסה יוצא באנגלית", not HE.search(sheet),
   str(sorted(set(re.findall(r"[֐-׿]+", sheet)))[:3]))

pyi18n.set_lang("he")
ok("חוזרים לעברית בסוף", pyi18n.lang() == "he")

# בלי זה הקטלוג לא נארז ב-EXE, והדוחות היו נשארים בעברית רק בגרסה הבנויה
spec = io.open(os.path.join(ROOT, "TikNick.spec"), encoding="utf-8").read()
ok("i18n_en.json נארז ב-EXE", "('i18n_en.json', '.')" in spec)

ok("main מחבר את השפה לצד הפייתון",
   'i18n.set_lang(db.get_setting("display_lang", "he"))' in
   io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read())

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("I18N TESTS PASSED")
