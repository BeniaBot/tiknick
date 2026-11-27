# -*- coding: utf-8 -*-
"""
0.9.8 — סבב ממשק לפי כללי הקהל הלא-טכנולוגי (זיכרון technophobe-ui-rules).

בנימין: "יש עוד 1000 באגים ותיקונים... הרמה בתוכנה הזו טעונה שיפור".
כל בדיקה כאן היא כלל שנשבר בפועל במסך, ונמצא בארגז החול:
  • סדר המסך = סדר הנייר (חלון הניק);
  • פעולה צריכה כפתור עם מילים (ניהול פורומים: ✕ אדום מחק פורום);
  • בלי ז'רגון (WAL, FTS5, API, "מוכרע לפי אמינות");
  • סימן שנקרא כאזהרה (❕) לדבר שאינו אזהרה.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
app = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


def fn_src(name):
    m = re.search(r"^(?:async\s+)?function %s\([\s\S]*?^}" % re.escape(name), app, re.M)
    assert m, name
    return m.group(0)


# ══ חלון הניק ══════════════════════════════════════════════════════════════
dlg = fn_src("openNickDialog")
pos = {k: dlg.index('id="f-%s"' % k) for k in
       ("forum", "username", "real_name", "phone", "email", "address", "extra_info", "notes",
        "private_notes", "full_name", "reputation", "trust_level", "avatar_url")}
ok("🚨 ההערות לפני נתוני הפורום", pos["notes"] < pos["reputation"] and pos["private_notes"] < pos["full_name"])
ok("פרטי האדם לפני ההערות", max(pos[k] for k in ("real_name", "phone", "email", "address"))
   < pos["extra_info"])
box = dlg.index('class="adv-box nick-forum-box"')
ok("נתוני הפורום בתוך מקטע מקופל", all(box < pos[k] for k in ("full_name", "reputation", "trust_level",
                                                              "avatar_url")))
ok("   פתוח בעריכה, סגור בניק חדש", "nick-forum-box\"${nick ? ' open' : ''}" in dlg)
ok("🚨 ניק חדש: מוניטין ריק ולא 0", "value=\"${esc(nick?.reputation ?? '')}\"" in dlg
   and "nick?.reputation ?? 0" not in dlg)
ok("🚨 ניק חדש: סטטוס 'לא ידוע' ולא 'פעיל'", "s === 'לא ידוע'" in dlg)
ok("כפתור ההדפסה בלי '(ברירות מחדל)'", "הדפס (ברירות מחדל)" not in app)
ok("לכפתור בחלון יכול להיות הסבר בריחוף", "${b.title ? ` title=\"${esc(b.title)}\"` : ''}" in app)

# ══ ניהול פורומים ══════════════════════════════════════════════════════════
fm = fn_src("openForumMgr")
ok("🚨 מחיקת פורום — כפתור עם מילה, לא ✕", "🗑️ מחק</button>" in fm and ">✕</button>" not in fm)
ok("עריכה — כפתור עם מילה", "✏️ ערוך</button>" in fm)
ok("🚨 אין יותר 'הפורום שנבחר' (בחירה שאף מילה לא הסבירה)", "שם חדש לפורום שנבחר" not in fm)
ok("סוג הפורום גלוי וניתן לבחירה", 'id="fm-e-plat"' in fm and "PLATFORM_LABEL" in fm)
ok("העדכון שולח את הסוג", "api('update_forum', selectedForum.id, name, color, url, plat)" in fm)
ok("🚨 צבע הפורום עובר safeColor בתוך style", "background:${esc(safeColor(f.color))}" in fm)

# ══ בלי ז'רגון ═════════════════════════════════════════════════════════════
for word in ("יומן WAL", "(FTS5)", "ערכי מקורות", "דרך ה-API שלהם", "מוכרע לפי אמינות", "לא זמין — LIKE"):
    ok("אין '%s' במסך" % word, word not in app)

# ══ "+N" במקום ❕ ═══════════════════════════════════════════════════════════
_code = "\n".join(ln for ln in app.splitlines() if not ln.strip().startswith("//"))
ok("🚨 אין ❕ בטבלה ובכרטיסים", "❕" not in _code)
node = shutil.which("node")
if node:
    js = r"""
function mk(tag){ return { tag, children: [], dataset: {}, appendChild(c){ this.children.push(c); return c; },
  set textContent(v){ this._t = v; }, get textContent(){ return this._t; } }; }
const document = { createElement: mk };
let opened = null;
function openNickDialog(id){ opened = id; }
function contactSpan(type, v){ return { cls: 'contact', textContent: v }; }
function showContactsTooltip(){} function hideTooltip(){}
__FUNCS__
const out = {};
function cells(n){ const p = mk('td'), e = mk('td'); renderPhone(p, n); renderEmail(e, n);
  const b = [...p.children, ...e.children].filter(c => c.className === 'cell-extra'); return b; }
let b = cells({ id: 1, phone: '050', email: 'a@b', extra_contacts: 2 });
out.phoneAndMail = b.length === 1 && b[0].textContent === '+2';
b = cells({ id: 2, phone: '', email: 'a@b', extra_contacts: 1 });
out.mailOnly = b.length === 1 && b[0].textContent === '+1';
b = cells({ id: 3, phone: '', email: '', extra_contacts: 3 });
out.neither = b.length === 1 && b[0].textContent === '+3';
b = cells({ id: 4, phone: '050', email: '', extra_contacts: 0 });
out.none = b.length === 0;
b = cells({ id: 5, phone: '050', email: '', extra_contacts: 1 });
b[0].onclick({ stopPropagation(){} });
out.clickOpens = opened === 5;
out.title = b[0].title;
console.log(JSON.stringify(out));
"""
    funcs = "\n".join(fn_src(n) for n in ("renderPhone", "extraContactsBadge", "renderEmail"))
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "t.js")
    io.open(p, "w", encoding="utf-8").write(js.replace("__FUNCS__", funcs))
    r = subprocess.run([node, p], capture_output=True, text=True, encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode:
        ok("הקוד רץ ב-node", False, r.stderr[-500:])
    else:
        o = json.loads(r.stdout.strip().splitlines()[-1])
        ok("🚨 טלפון וגם מייל — סימון אחד, '+2'", o["phoneAndMail"])
        ok("רק מייל — הסימון ליד המייל, פעם אחת", o["mailOnly"])
        ok("בלי טלפון ובלי מייל — עדיין מופיע", o["neither"])
        ok("בלי פרטי קשר נוספים — בלי סימון", o["none"])
        ok("לחיצה פותחת את הניק", o["clickOpens"])
        ok("ההסבר אומר כמה ומה קורה בלחיצה", "עוד פרט קשר אחד" in o["title"] and "לחץ" in o["title"], o["title"])

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("UI PASS TESTS PASSED")
