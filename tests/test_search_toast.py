# -*- coding: utf-8 -*-
"""
שלושה דברים קטנים שבנימין דיווח, ושכל אחד מהם מרגיש כמו "התוכנה לא עובדת":

1. "בשורת חיפוש למעלה אין איקס לסגירת החיפוש וחזרה לרשימה"
2. "בכל הפעלה של התוכנה מופיע אותו חיפוש מקודם ולא מרועננת התוכנה"
3. "את ההודעות הצפות אי אפשר לסגור באיקס" — והגרוע: הודעת שגיאה **הציגה**
   ✕ (סמל מצויר ב-CSS) שלא הגיב ללחיצה, כי ההודעה כולה הייתה
   pointer-events:none.

החלק הפונקציונלי מריץ ב-node את הפונקציות האמיתיות מתוך app.js מול DOM
מזויף מינימלי — לחיצה על ה-✕, טיימר, ריחוף — ולא רק מחפש מחרוזות.
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
html = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
css = io.open(os.path.join(ROOT, "web", "style.css"), encoding="utf-8").read()

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


def fn_src(name):
    m = re.search(r"^(?:async\s+)?function %s\([\s\S]*?^}" % re.escape(name), app, re.M)
    assert m, "function %s not found" % name
    return m.group(0)


# ══ 1. ✕ בחיפוש ═══════════════════════════════════════════════════════════
btn = re.search(r'<button[^>]*id="search-clear"[^>]*>', html)
ok("יש כפתור ✕ בתוך תיבת החיפוש", btn is not None)
ok("   הוא מנקה דרך clearSearch()", btn is not None and 'onclick="clearSearch()"' in btn.group(0))
ok("   מוסתר כשאין מה לנקות (hidden בהתחלה)", btn is not None and " hidden" in btn.group(0))
ok("   יושב בתוך search-wrap, ליד השדה",
   re.search(r'id="search-input"[\s\S]{0,300}id="search-clear"[\s\S]{0,600}?</button>\s*</div>', html)
   is not None)
ok("   הסמלים בתיבה הם קו דק (SVG), לא אימוג'י צבעוני",
   "🔍" not in html and re.search(r'class="search-icon"><svg', html) is not None
   and btn is not None and "<svg" in html[btn.end():btn.end() + 40])
ok("   ובתצוגת משתמש אותה זכוכית מגדלת",
   '<span class="search-icon">🔍</span>' not in app
   and '<span class="search-icon">${ICON_SEARCH}</span>' in app)
ok("🚨 במיקוד אין זוהר עבה ואין מסגרת שנייה על השדה",
   re.search(r"\.search-wrap:focus-within\{[^}]*accent-glow", css) is None
   and ".search-wrap input:focus-visible{outline:none}" in css)
ok("   השדה מתכווץ — ה-✕ לא נדחק אל מחוץ לתיבה בחלון צר",
   ".search-wrap input{min-width:0}" in css)
ok("   ל-hidden יש קדימות על display:flex של הכפתור",
   ".search-clear[hidden]{display:none!important}" in css)
ok("loadNicks מעדכן את ה-✕ (כל מסלול שמציב ערך בקוד)",
   re.search(r"async function loadNicks\(search = '', opts = \{\}\) \{\n  syncSearchClear\(\);", app)
   is not None)
ok("Esc בתוך החיפוש מנקה אותו",
   "if (e.key === 'Escape' && search.value) { e.preventDefault(); clearSearch(); return; }" in app)

# ══ 2. פתיחה נקייה ════════════════════════════════════════════════════════
ok("🚨 החיפוש האחרון אינו נקרא ואינו נשמר יותר", "last_search" not in app)
init = fn_src("_origInit")
ok("ההפעלה טוענת את כל הרשימה", "await loadNicks('');" in init and "lastSearch" not in init)
ok("   ושדה החיפוש מתחיל ריק", "if (si) si.value = '';" in init)
ok("   המיון כן נזכר (העדפה, לא סינון)", "DISPLAY.sort" in init)

# ══ 3. ✕ בהודעות — עיצוב ═════════════════════════════════════════════════
ok("🚨 סמל השגיאה אינו ✕ (נראה ככפתור סגירה ולא הגיב)",
   ".toast-error::before   { content: '✕'; }" not in css)
ok("ההודעה עצמה קולטת לחיצות", re.search(r"\.toast\{[^}]*pointer-events:auto", css) is not None)
ok("   המיכל נשאר שקוף ללחיצות (לא חוסם את מה שמתחת לרווחים)",
   re.search(r"#toast-container\{[^}]*pointer-events:none", css) is not None)
ok("   הודעה ארוכה לא נמתחת על כל המסך", re.search(r"\.toast\{[^}]*max-width:", css) is not None)

# ══ 4. הקוד עצמו, ב-node ═════════════════════════════════════════════════
node = shutil.which("node")
if not node:
    ok("node זמין להרצת הבדיקה הפונקציונלית", False, "node not found")
else:
    js = r"""
const out = {};
let now = 0, timers = [], tid = 0;
function setTimeout(fn, ms) { const id = ++tid; timers.push({ id, at: now + ms, fn }); return id; }
function clearTimeout(id) { timers = timers.filter(t => t.id !== id); }
function advance(ms) { now += ms; const due = timers.filter(t => t.at <= now); timers = timers.filter(t => t.at > now); due.forEach(t => t.fn()); }

function mk(tag) {
  const el = { tagName: tag.toUpperCase(), children: [], parent: null, className: '', textContent: '',
    attrs: {}, handlers: {}, hidden: false, value: '', focused: false, type: '', title: '',
    appendChild(c) { c.parent = this; this.children.push(c); return c; },
    remove() { if (this.parent) { this.parent.children = this.parent.children.filter(c => c !== this); this.parent = null; } },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    addEventListener(k, f) { this.handlers[k] = f; },
    focus() { this.focused = true; },
  };
  return el;
}
const container = mk('div');
const input = mk('input'); const clearBtn = mk('button'); clearBtn.hidden = true;
const byId = { 'toast-container': container, 'search-input': input, 'search-clear': clearBtn };
const document = { createElement: mk, getElementById: id => byId[id] || null };
const S = { searchTimer: 0 };
const loads = [];
function loadNicks(q) { loads.push(q); }
const stop = { stopPropagation() {} };

__FUNCS__

// -- הודעה רגילה
toast('נשמר', 'success');
let t = container.children[0];
out.hasText = t.children.some(c => c.className === 'toast-text' && c.textContent === 'נשמר');
const x = t.children.find(c => c.className === 'toast-close');
out.hasClose = !!x && /<svg/.test(x.innerHTML || '') && x.attrs['aria-label'] === 'סגור';
out.closeIsLast = t.children[t.children.length - 1] === x;
x.onclick(stop);
out.closeRemoves = container.children.length === 0;
out.closeClearsTimer = timers.length === 0;

// -- סגירה אוטומטית, וריחוף שעוצר אותה
toast('קצר', 'info');
t = container.children[0];
advance(3400); out.stillAt3400 = container.children.length === 1;
advance(200);  out.goneAt3600 = container.children.length === 0;
toast('קצר', 'info');
t = container.children[0];
advance(3000); t.handlers.mouseenter();
advance(20000); out.hoverHolds = container.children.length === 1;
t.handlers.mouseleave();
advance(3400); out.leaveRearmsFull = container.children.length === 1;
advance(200);  out.leaveThenGone = container.children.length === 0;

// -- זמן לפי אורך, עם תקרה
toast('א'.repeat(150), 'error');
advance(10400); out.longStays = container.children.length === 1;
advance(200);   out.longGoneAt10600 = container.children.length === 0;
toast('א'.repeat(1000), 'error');
advance(12000); out.capped = container.children.length === 0;
toast('קצר', 'info', { ms: 9000 });
advance(8900); out.explicitMs = container.children.length === 1; advance(200);
out.role = (toast('x', 'error'), container.children[0].attrs.role);
container.children[0].children.find(c => c.className === 'toast-close').onclick(stop);

// -- כפתור פעולה
let acted = 0;
toast('נמחק', 'info', { actionLabel: '↩ בטל', onAction: () => acted++ });
t = container.children[0];
const a = t.children.find(c => c.className === 'toast-action');
out.actionBeforeClose = t.children.indexOf(a) < t.children.findIndex(c => c.className === 'toast-close');
out.actionMin7s = (advance(6900), container.children.length === 1);
a.onclick(stop);
out.actionRuns = acted === 1 && container.children.length === 0 && timers.length === 0;

// -- HTML בהודעה הוא טקסט
toast('<img src=x onerror=1>', 'info');
out.textOnly = container.children[0].children[0].textContent === '<img src=x onerror=1>';
container.children[0].children.find(c => c.className === 'toast-close').onclick(stop);

// -- ✓ כפול: לסמל ההצלחה יש כבר ✓
const last = () => container.children[container.children.length - 1].children[0].textContent;
toast('המאגר שוחזר ✓', 'success'); out.noDoubleCheck = last() === 'המאגר שוחזר';
toast('מחובר ✓ העוגייה נשמרה', 'success'); out.midCheckKept = last() === 'מחובר ✓ העוגייה נשמרה';
toast('משהו ✓', 'info'); out.infoUntouched = last() === 'משהו ✓';
container.children = [];

// -- ✕ בחיפוש
input.value = 'כהן'; onSearch('כהן');
out.showsWhenTyped = clearBtn.hidden === false;
advance(250); out.searchLoads = loads[loads.length - 1] === 'כהן';
input.value = 'כה'; onSearch('כה');
clearSearch();
out.clearEmpties = input.value === '' && clearBtn.hidden === true && input.focused;
out.clearLoadsAll = loads[loads.length - 1] === '';
advance(500); out.pendingTypingCancelled = loads[loads.length - 1] === '';
input.value = ''; syncSearchClear(); out.hiddenWhenEmpty = clearBtn.hidden === true;
console.log(JSON.stringify(out));
"""
    icons = re.search(r"^const ICON_SEARCH = .*\n^const ICON_CLOSE = .*$", app, re.M)
    assert icons, "ICON constants not found in app.js"
    funcs = icons.group(0) + "\n" + "\n".join(
        fn_src(n) for n in ("toast", "onSearch", "syncSearchClear", "clearSearch"))
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "t.js")
    io.open(p, "w", encoding="utf-8").write(js.replace("__FUNCS__", funcs))
    r = subprocess.run([node, p], capture_output=True, text=True, encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        ok("הקוד רץ ב-node", False, r.stderr[-600:])
    else:
        o = json.loads(r.stdout.strip().splitlines()[-1])
        for key, label in (
            ("hasText", "הטקסט בתוך span משלו"),
            ("hasClose", "🚨 יש ✕ אמיתי עם תווית נגישות"),
            ("closeIsLast", "   ה-✕ אחרון (בקצה ההודעה)"),
            ("closeRemoves", "🚨 לחיצה על ה-✕ סוגרת"),
            ("closeClearsTimer", "   ומבטלת את הטיימר"),
            ("stillAt3400", "הודעה קצרה עדיין מוצגת אחרי 3.4 שניות"),
            ("goneAt3600", "   ונעלמת לבד אחרי 3.5"),
            ("hoverHolds", "עכבר מעל ההודעה עוצר את ההיעלמות"),
            ("leaveRearmsFull", "   יציאת העכבר מתחילה ספירה מלאה מחדש"),
            ("leaveThenGone", "   ואז היא נעלמת"),
            ("longStays", "משפט של 150 תווים נשאר 10.5 שניות (70ms לתו)"),
            ("longGoneAt10600", "   ונעלם אחריהן"),
            ("capped", "   עם תקרה של 12 שניות"),
            ("explicitMs", "ms מפורש עדיין גובר"),
            ("actionBeforeClose", "כפתור הפעולה לפני ה-✕"),
            ("actionMin7s", "   הודעה עם פעולה נשארת לפחות 7 שניות"),
            ("actionRuns", "   הפעולה רצה, ההודעה נסגרת והטיימר מבוטל"),
            ("textOnly", "תוכן ההודעה הוא טקסט, לא HTML"),
            ("showsWhenTyped", "ה-✕ בחיפוש מופיע ברגע שמקלידים"),
            ("searchLoads", "   החיפוש עצמו רץ כרגיל"),
            ("clearEmpties", "🚨 לחיצה על ה-✕ מרוקנת, מסתירה ומחזירה את הסמן לשדה"),
            ("clearLoadsAll", "   וטוענת את כל הרשימה"),
            ("pendingTypingCancelled", "   הקלדה שעוד ממתינה לא דורסת את הניקוי"),
            ("hiddenWhenEmpty", "ה-✕ מוסתר כשהשדה ריק"),
            ("noDoubleCheck", "🚨 הודעת הצלחה בלי ✓ כפול"),
            ("midCheckKept", "   ✓ באמצע משפט נשאר"),
            ("infoUntouched", "   הודעה שאינה הצלחה — לא נוגעים"),
        ):
            ok(label, o.get(key) is True, o.get(key))
        ok("הודעת שגיאה מוכרזת לקוראי מסך (role=alert)", o.get("role") == "alert", o.get("role"))

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("SEARCH/TOAST TESTS PASSED")
