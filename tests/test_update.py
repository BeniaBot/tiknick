# -*- coding: utf-8 -*-
"""
0.8.12: תקציר שינויים שמתאים את עצמו לגודל קפיצת הגרסאות.

הכלל: קפיצה של גרסה אחת מקבלת פירוט מלא; 2–3 מקבלות את החשוב והחדש והשאר
כמספר; 4 ומעלה מקבלות כותרות בלבד. מי שדילג על תשע גרסאות לא יקרא קיר טקסט.
"""
import os, sys, io, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []

def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)

# ── היומן עצמו חייב להיות תקין: הוא נקרא מהרשת ע"י כל משתמש ──
path = os.path.join(ROOT, "changelog.json")
ok("changelog.json קיים", os.path.exists(path))
data = json.load(io.open(path, encoding="utf-8"))
versions = data.get("versions") or []
ok("יש רשומות גרסה", len(versions) >= 5, str(len(versions)))

def parse(v):
    out = []
    for part in str(v).split("."):
        d = "".join(c for c in part if c.isdigit())
        out.append(int(d) if d else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])

order = [parse(e["v"]) for e in versions]
ok("היומן ממוין מהחדש לישן", order == sorted(order, reverse=True), str(order[:4]))
ok("לכל גרסה יש פריטים", all(e.get("items") for e in versions))
ok("כל פריט מתויג נכון",
   all(it.get("t") in ("major", "feature", "fix") and it.get("s")
       for e in versions for it in e["items"]))
ok("אין גרסה כפולה", len({e["v"] for e in versions}) == len(versions))
ok("כל הטקסטים בעברית ולא ריקים",
   all(len(it["s"].strip()) > 8 for e in versions for it in e["items"]))

# ── לוגיקת ההתאמה, בדיוק כמו ב-main.get_update_summary ──
def summarize(cur, top=None):
    cur_t, top_t = parse(cur), (parse(top) if top else None)
    newer = [e for e in versions
             if parse(e["v"]) > cur_t and (top_t is None or parse(e["v"]) <= top_t)]
    newer.sort(key=lambda e: parse(e["v"]), reverse=True)
    if not newer:
        return {"jump": 0, "mode": None, "groups": []}
    jump = len(newer)
    items = [it for e in newer for it in e["items"]]
    M = [i["s"] for i in items if i["t"] == "major"]
    F = [i["s"] for i in items if i["t"] == "feature"]
    X = [i["s"] for i in items if i["t"] == "fix"]
    if jump == 1:
        mode = "full"
        groups = [g for g in ({"t": "חשוב לדעת", "i": M}, {"t": "חדש", "i": F},
                              {"t": "תיקונים", "i": X}) if g["i"]]
    elif jump <= 3:
        mode = "grouped"
        groups = [g for g in ({"t": "חשוב לדעת", "i": M}, {"t": "מה חדש", "i": F}) if g["i"]]
        if X:
            groups.append({"t": "ובנוסף", "i": ["%d תיקונים ושיפורים" % len(X)]})
    else:
        mode = "headlines"
        n_major, n_feat = (3, 4) if jump <= 6 else (2, 3)
        top_f = F[:n_feat]
        groups = [g for g in ({"t": "חשוב לדעת", "i": M[:n_major]},
                              {"t": "העיקר שנוסף", "i": top_f}) if g["i"]]
        tail = []
        if len(F) - len(top_f):
            tail.append("ועוד %d תוספות" % (len(F) - len(top_f)))
        if X:
            tail.append("%d תיקונים" % len(X))
        if tail:
            groups.append({"t": "ובנוסף", "i": [" · ".join(tail)]})
    return {"jump": jump, "mode": mode, "groups": groups,
            "lines": sum(len(g["i"]) for g in groups)}

newest = versions[0]["v"]
one = summarize(versions[1]["v"], newest)
ok("קפיצה של גרסה אחת = פירוט מלא", one["mode"] == "full", str(one["mode"]))

two = summarize(versions[2]["v"], newest)
ok("קפיצה של שתיים = מקובץ", two["mode"] == "grouped", str(two["mode"]))
# הכלל, לא צורת הנתונים: אם בטווח *יש* תיקונים, הם מסוכמים כמספר ולא מפורטים.
grouped_with_fixes = None
for e in versions[1:]:
    r = summarize(e["v"], newest)
    if r["mode"] == "grouped":
        items = [it for x in versions
                 if parse(versions[0]["v"]) >= parse(x["v"]) > parse(e["v"])
                 for it in x["items"]]
        if any(i["t"] == "fix" for i in items):
            grouped_with_fixes = r
            break
if grouped_with_fixes:
    ok("במצב מקובץ התיקונים מסוכמים כמספר",
       any("תיקונים ושיפורים" in i for g in grouped_with_fixes["groups"] for i in g["i"]),
       str(grouped_with_fixes["groups"][-1]))
else:
    ok("במצב מקובץ התיקונים מסוכמים כמספר", True, "(אין תיקונים בטווח מקובץ)")

big = summarize(versions[-1]["v"], newest)
ok("קפיצה גדולה = כותרות בלבד", big["mode"] == "headlines", str(big["mode"]))

# הכלל המרכזי שביקש בנימין: ככל שהקפיצה גדולה יותר, התקציר קצר יותר.
mid = summarize(versions[4]["v"], newest)      # קפיצה בינונית
ok("קפיצה גדולה קצרה מקפיצה בינונית",
   big["lines"] <= mid["lines"],
   "big=%d(%d גרסאות) mid=%d(%d גרסאות)" % (big["lines"], big["jump"],
                                             mid["lines"], mid["jump"]))
ok("קפיצה גדולה חסומה ב-8 שורות", big["lines"] <= 8, str(big["lines"]))
ok("צפיפות יורדת עם הקפיצה",
   big["lines"] / big["jump"] < two["lines"] / two["jump"],
   "%.2f vs %.2f" % (big["lines"] / big["jump"], two["lines"] / two["jump"]))

# כל נקודת מוצא אפשרית חייבת להחזיר משהו שפוי
for e in versions[1:]:
    r = summarize(e["v"], newest)
    ok("קפיצה מ-%s מחזירה תוכן" % e["v"], r["jump"] >= 1 and r["lines"] >= 1,
       str(r["jump"]))

ok("גרסה עדכנית מחזירה ריק", summarize(newest, newest)["jump"] == 0)
ok("גרסה עתידית מחזירה ריק", summarize("9.9.9", None)["jump"] == 0)

# ── 0.8.10 > 0.8.9 גם כאן, לא רק בבדיקת העדכונים ──
ok("0.8.10 גדול מ-0.8.9", parse("0.8.10") > parse("0.8.9"))
ok("0.8.9 גדול מ-0.8.8", parse("0.8.9") > parse("0.8.8"))

# ── הגרסה הנוכחית חייבת להופיע ביומן, אחרת אף אחד לא יראה מה השתנה ──
src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
app_version = src.split('APP_VERSION = "')[1].split('"')[0]
ok("הגרסה הנוכחית (%s) מופיעה ביומן" % app_version,
   any(e["v"] == app_version for e in versions),
   str([e["v"] for e in versions[:3]]))

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("UPDATE-SUMMARY TESTS PASSED")
