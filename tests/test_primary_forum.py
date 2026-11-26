# -*- coding: utf-8 -*-
"""
מתמחים טופ ראשון בכל רשימת פורומים בתוכנה.

בנימין: "בכל הרשימות בתוכנה מתמחים חייב להופיע ראשון."
עד כאן הרשימות מוינו לפי sort_order ואז לפי שם — וכל הפורומים חוץ מ"כללי"
יושבים על sort_order=99, כך שמתמחים יצא שלישי: אחרי "כללי" ואחרי "חרדים
נעייס", שקודם לו באלפבית.

מאגר זמני בלבד; צד הלקוח נשלף מ-app.js ורץ ב-node.
"""
import io
import json
import os
import subprocess
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
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "prim.db")
db.init_db()
# בכוונה: שמות שקודמים למתמחים באלפבית, ומתמחים נוסף אחרון
for name, url in (("חרדים נעייס", "https://charedim-neyes.onrender.com"),
                  ("אוצריא", "https://otzaria.org/forum"),
                  ("בינה", "https://bina.top"),
                  ("מתמחים טופ", "https://mitmachim.top")):
    db.add_forum(name, "#888", url)

names = [f["name"] for f in db.get_forums()]
ok("מתמחים ראשון ב-get_forums", names[0] == "מתמחים טופ", names)
ok("והשאר שומרים על הסדר הקודם (כללי, ואז באלפבית)",
   names[1:] == ["כללי", "אוצריא", "בינה", "חרדים נעייס"], names)

# הזיהוי לפי כתובת: שינוי שם בניהול פורומים לא מוריד אותו מהראש
fid = [f["id"] for f in db.get_forums() if f["name"] == "מתמחים טופ"][0]
db.update_forum(fid, "הפורום שלי", "#888", "https://mitmachim.top/")
ok("שינוי שם — עדיין ראשון, כי הזיהוי לפי הכתובת",
   db.get_forums()[0]["name"] == "הפורום שלי", [f["name"] for f in db.get_forums()][:2])
db.update_forum(fid, "מתמחים טופ", "#888", "https://mitmachim.top/")

# וגם בלי כתובת בכלל — לפי השם
ok("_is_primary_forum לפי כתובת", db._is_primary_forum("x", "https://mitmachim.top"))
ok("ותת-דומיין", db._is_primary_forum("x", "https://www.mitmachim.top/"))
ok("ולפי שם כשאין כתובת", db._is_primary_forum("מתמחים", ""))
ok("ופורום אחר אינו ראשי", not db._is_primary_forum("פרוג", "https://www.prog.co.il"))
ok("דומיין שרק מכיל את המחרוזת אינו ראשי",
   not db._is_primary_forum("x", "https://notmitmachim.top.evil.example"))

# בורר הסנכרון, חזונישניק ושטינקניק נבנים מ-get_scrapable_forums
import main   # noqa: E402
main.db = db
scr = [f["name"] for f in main.API().get_scrapable_forums()]
ok("ברשימת הפורומים לסריקה — ראשון", scr and scr[0] == "מתמחים טופ", scr)

# סטטיסטיקות: מתמחים ראשון גם כשאינו הגדול
for i in range(30):
    db.create_nick({"forum": "בינה", "username": "b%d" % i})
for i in range(3):
    db.create_nick({"forum": "מתמחים טופ", "username": "m%d" % i})
bf = [r["forum"] for r in db.get_stats()["by_forum"]]
ok("בסטטיסטיקות לפי פורום — ראשון גם כשהוא קטן יותר", bf[0] == "מתמחים טופ", bf)

# התצוגה המאוחדת: החשבון במתמחים קודם לשאר חשבונות אותו אדם
a = db.create_nick({"forum": "בינה", "username": "דוד", "trust_level": 9})
b = db.create_nick({"forum": "מתמחים טופ", "username": "דוד"})
db.add_identity(a, b)
mp = db.get_merged_profile(a)
ok("בתצוגה המאוחדת — החשבון במתמחים ראשון",
   mp["members"][0]["forum"] == "מתמחים טופ", [m["forum"] for m in mp["members"]])

# מפת הזהויות
im = db.get_identity_map()
grp = [g for g in im["groups"] if len(g["members"]) == 2][0]
ok("במפת הזהויות — ראשון בתוך הקבוצה",
   grp["members"][0]["forum"] == "מתמחים טופ", [m["forum"] for m in grp["members"]])

# ══ צד הלקוח ═════════════════════════════════════════════════════════════
app = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()


def grab(name):
    i = app.index("function %s(" % name)
    d, j = 0, app.index("{", i)
    for k in range(j, len(app)):
        if app[k] == "{":
            d += 1
        elif app[k] == "}":
            d -= 1
            if d == 0:
                return app[i:k + 1]
    raise AssertionError(name)


JS = """
const HE_COLLATOR = new Intl.Collator('he');
const S = {forums: %s};
S.forumRank = {}; S.forums.forEach((f, i) => { S.forumRank[f.name] = i; });
%s
console.log(JSON.stringify({
  idmap: ['חרדים נעייס', 'בינה', 'מתמחים טופ', 'אוצריא'].sort(forumCmp),
  unknown: ['זר', 'מתמחים טופ', 'אלף'].sort(forumCmp),
}));
""" % (json.dumps([{"name": n} for n in [f["name"] for f in db.get_forums()]],
                  ensure_ascii=False), grab("forumCmp"))
f = os.path.join(tempfile.mkdtemp(), "t.js")
io.open(f, "w", encoding="utf-8").write(JS)
r = subprocess.run(["node", f], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
if r.returncode:
    print(r.stderr[-600:])
    sys.exit(1)
res = json.loads(r.stdout.strip())
ok("forumCmp: מתמחים ראשון במיון בצד הלקוח", res["idmap"][0] == "מתמחים טופ", res["idmap"])
ok("ופורום שאינו ברשימה — אחרי כולם", res["unknown"][0] == "מתמחים טופ"
   and res["unknown"][-1] in ("זר", "אלף"), res["unknown"])

ok("מפת הזהויות ממיינת עם forumCmp", ".sort(forumCmp)" in app)
# מיון הטבלה לפי עמודת הפורום נעשה בשרת (get_nick_ids) — ושם, לא באלפבית
srt = db.get_nick_ids("", None, "forum", 1)["ids"]
rows = {r["id"]: r for r in db.get_nick_rows(srt)}
plain = [rows[i]["forum"] for i in srt if not rows[i]["has_info"]]
ok("מיון הטבלה לפי עמודת הפורום: מתמחים ראשון",
   plain and plain[0] == "מתמחים טופ", plain[:3])
ok("ובכיוון ההפוך — אחרון", db.get_nick_ids("", None, "forum", -1)["ids"]
   and [rows[i]["forum"] for i in db.get_nick_ids("", None, "forum", -1)["ids"]
        if not rows[i]["has_info"]][-1] == "מתמחים טופ")
ok("רשימת הפורומים במפת הזהויות אינה ממוינת עוד באלפבית",
   "flatMap(g => g.forums))].sort(HE_COLLATOR.compare)" not in app)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("PRIMARY FORUM TESTS PASSED")
