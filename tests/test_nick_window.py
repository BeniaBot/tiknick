# -*- coding: utf-8 -*-
"""
הטבלה כחלון על רשימת מזהים.

בנימין: "התוכנה עובדת מאוד לאט כשיש בה יותר מ-100K ניקים." נמדד על המאגר
שלו (250,420): כל טעינה של הטבלה משכה את כל השורות — 5.3 שניות שאילתה,
2.4 שניות JSON ו-162MB לממשק — אחרי כל עריכה, מחיקה, ייבוא וסריקה.

עכשיו get_nick_ids מחזיר את **הסדר** (מספרים בלבד) ו-get_nick_rows את
**התוכן** לחלון הנראה. הבדיקה הזו מוודאת שהמסלול החדש מחזיר **בדיוק** את
מה שהישן החזיר — אותם ניקים, אותו סדר, אותן שורות — ושומרת על המלכודות
שנמצאו בדרך. מאגר זמני בלבד.
"""
import io
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import database as db   # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


db.close_pool()
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "win.db")
db.init_db()
for name, url in (("מתמחים טופ", "https://mitmachim.top"), ("בינה", "https://bina.top"),
                  ("אוצריא", "https://otzaria.org/forum")):
    db.add_forum(name, "#888", url)

FORUMS = ["מתמחים טופ", "בינה", "אוצריא", "כללי"]
ids = []
for i in range(600):
    d = {"forum": FORUMS[i % 4], "username": "Nick%d" % i if i % 2 else "ניק%d" % i,
         "trust_level": (i % 7) + 1}
    if i % 9 == 0:
        d["phone"] = "050%07d" % i            # has_info
    if i % 13 == 0:
        d["notes"] = "דוד כהן"
    ids.append(db.create_nick(d))
with db.get_connection() as c:
    for k, nid in enumerate(ids):
        c.execute("UPDATE nicks SET post_count=?, reputation=?, status=? WHERE id=?",
                  (str((k * 37) % 1500) if k % 5 else "",
                   str(((k * 53) % 400) - 200) if k % 6 else "",
                   "מורחק" if k % 17 == 0 else "פעיל", nid))
db.add_identity(ids[1], ids[2])
db.add_contact(ids[3], "phone", "0529999999", "")


def old_ids(search=""):
    return [r["id"] for r in db.get_all_nicks(search)["rows"]]


# ══ 1. אותם ניקים, אותו סדר ══════════════════════════════════════════════
new = db.get_nick_ids("")
ok("ברירת מחדל: אותו סדר בדיוק כמו get_all_nicks", new["ids"] == old_ids(), len(new["ids"]))
ok("total", new["total"] == 600, new["total"])
wi = sum(1 for r in db.get_all_nicks("")["rows"] if r["has_info"])
ok("with_info זהה למונה הישן", new["with_info"] == wi, (new["with_info"], wi))
ok("🚨 המטען הוא מספרים בלבד — לא שורות",
   all(isinstance(x, int) for x in new["ids"]))
small = len(json.dumps(new))
big = len(json.dumps(db.get_all_nicks(""), ensure_ascii=False))
ok("המטען קטן בסדרי גודל מהשורות המלאות", small * 15 < big, "%d מול %d" % (small, big))

for term in ("ניק1", "Nick", "דוד", "050", "-מורחק", "ק12"):
    o = db.get_all_nicks(term)
    n = db.get_nick_ids(term)
    ok("חיפוש %r: אותם ניקים ואותו סדר" % term, n["ids"] == [r["id"] for r in o["rows"]],
       (len(n["ids"]), len(o["rows"])))
    ok("   total זהה", n["total"] == o["total"], (n["total"], o["total"]))

# ══ 2. הסינון המתקדם ═════════════════════════════════════════════════════
for conds in ([{"field": "forum", "op": "equals", "value": "בינה"}],
              [{"field": "username", "op": "contains", "value": "Nick1"}],
              [{"field": "phone", "op": "not_empty", "value": ""}],
              [{"field": "notes", "op": "not_contains", "value": "דוד"},
               {"field": "forum", "op": "equals", "value": "אוצריא"}]):
    o = db.filter_nicks_multi(conds)
    n = db.get_nick_ids("", conds)
    lbl = " + ".join("%s %s" % (c["field"], c["op"]) for c in conds)
    ok("סינון %s: אותם ניקים" % lbl, sorted(r["id"] for r in o) == sorted(n["ids"]),
       (len(o), len(n["ids"])))
ok("סינון עם שדה שאינו ברשימה הלבנה — מתעלם ממנו, לא נופל",
   db.get_nick_ids("", [{"field": "id; DROP TABLE nicks", "op": "equals", "value": 1}])["total"]
   == 600)

# ══ 3. מיון לפי כותרת ═════════════════════════════════════════════════════
rows = {r["id"]: r for r in db.get_all_nicks("")["rows"]}


def plain_vals(order, f):
    return [rows[i][f] for i in order if not rows[i]["has_info"]]


for col in ("username", "post_count", "reputation", "forum", "updated_at", "identity"):
    for d in (1, -1):
        o = db.get_nick_ids("", None, col, d)["ids"]
        hi = [rows[i]["has_info"] for i in o]
        ok("מיון %s %+d: has_info תמיד ראשון" % (col, d), hi == sorted(hi, reverse=True))
        ok("   אותה קבוצת ניקים", sorted(o) == sorted(rows))

pc = [int(v) for v in plain_vals(db.get_nick_ids("", None, "post_count", 1)["ids"], "post_count") if v]
ok("🚨 מספר הודעות ממוין כמספר ולא כטקסט ('10' אחרי '9')", pc == sorted(pc))
rp = [int(v) for v in plain_vals(db.get_nick_ids("", None, "reputation", 1)["ids"], "reputation") if v]
ok("🚨 מוניטין שלילי ממוין נכון ('-200' לפני '-9')", rp == sorted(rp) and rp[0] < 0, rp[:3])
fo = plain_vals(db.get_nick_ids("", None, "forum", 1)["ids"], "forum")
ok("מיון לפי פורום — מתמחים ראשון", fo[0] == "מתמחים טופ", fo[:2])
un_up = db.get_nick_ids("", None, "username", 1)["ids"]
un_dn = db.get_nick_ids("", None, "username", -1)["ids"]
ok("כיוון המיון מתהפך", plain_vals(un_up, "username") == plain_vals(un_dn, "username")[::-1])
ok("🚨 שם עמודה זדוני אינו נכנס ל-SQL — חוזר לברירת המחדל",
   db.get_nick_ids("", None, "username; DROP TABLE nicks", 1)["ids"] == old_ids())

# ══ 4. השורות לחלון ═══════════════════════════════════════════════════════
win = new["ids"][100:160]
got = db.get_nick_rows(win)
ok("החלון חוזר בסדר שהתבקש", [r["id"] for r in got] == win)
ok("והשורות זהות עמודה-עמודה לרשימה הישנה", all(r == rows[r["id"]] for r in got))
ok("🚨 מזהה שנמחק בינתיים פשוט אינו חוזר", len(db.get_nick_rows([ids[0], 99999999, ids[1]])) == 2)
ok("ערכים זבלים במזהים אינם מפילים", len(db.get_nick_rows(["x", None, ids[0]])) == 1)
ok("תקרה לבקשה אחת", len(db.get_nick_rows(list(range(1, 20000)))) <= db._ROWS_PER_CALL_MAX)
ok("רשימה ריקה → ריק", db.get_nick_rows([]) == [] and db.get_nick_rows(None) == [])

# ══ 5. הגשר ═══════════════════════════════════════════════════════════════
import main   # noqa: E402
main.db = db
api = main.API()
r = api.get_nick_ids({"search": "Nick1", "sort_col": "username", "sort_dir": "-1"})
ok("הגשר מעביר חיפוש, מיון וכיוון", r["ids"] == db.get_nick_ids("Nick1", None, "username", -1)["ids"])
ok("הגשר סובל view חסר או פגום", api.get_nick_ids(None)["total"] == 600
   and api.get_nick_ids({"sort_dir": "x"})["total"] == 600)

# ══ 6. הממשק ═════════════════════════════════════════════════════════════
app = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()

# 🚨 המלכודת שנתפסה בארגז החול: יש ב-app.js כבר `function applyView()` (מחליף
# טבלה/כרטיסים). פונקציה חדשה באותו שם **החליפה אותה בשקט** — ב-JS ההצהרה
# האחרונה גוברת — והטעינה הפעילה את מחליף התצוגה. הטבלה נשארה ריקה בלי שגיאה.
names = re.findall(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", app, re.M)
dups = sorted({n for n in names if names.count(n) > 1})
ok("🚨 אין שתי פונקציות באותו שם ב-app.js", not dups, dups)

ok("אין עוד S.nicks — כל השורות בזיכרון", "S.nicks" not in app)
ok("loadNicks מבקש מזהים ולא שורות", "api('get_nick_ids'" in app and
   "await api('get_nicks', search)" not in app)
ok("הסינון המתקדם באותו מסלול", "api('filter_nicks_multi'" not in app)
ok("הטבלה מציירת מ-rowAt", "const n = rowAt(i);" in app)
ok("🚨 שורת 'טוען' אינה נמדדת כגובה שורה",
   "tr:not(.v-spacer):not(.row-pending)" in app)
ok("שורה חסרה מבקשת את החלון ומציירת מחדש",
   "if (missing) ensureRows(start, end).then(ch => { if (ch) renderTableWindow(); });" in app)
ok("🚨 מזהה שנמחק מסומן ולא מבוקש שוב ושוב",
   "S.rowCache.set(id, null)" in app)
ok("🚨 הסינון מקדם את טוקן הטעינה (טעינה שעוד בדרך לא תדרוס אותו)",
   re.search(r"async function runFieldFilter[\s\S]*?const tok = \+\+S\.loadToken;", app) is not None)
ok("מיון מחדש שומר את הבחירה",
   "return loadNicks(S.currentSearch || '', { keepSelection: true });" in app)
ok("המטמון חסום", "const ROW_CACHE_MAX" in app and "S.rowCache.size > ROW_CACHE_MAX" in app)
ok("בחר הכול עובד מול כל המזהים", "S.ids.forEach(id => S.multiSelected.add(id))" in app)
ok("ייצוא 'התצוגה הנוכחית' — כל המזהים ולא רק מה שנטען",
   "ids = S.ids.slice();" in app)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("NICK WINDOW TESTS PASSED")
