# -*- coding: utf-8 -*-
"""
"חסרה עוגייה" — נאמר בסוף הסריקה שהצליחה, ומוביל לאן שצריך.

בנימין: "אם צריך עוגיה — שתבוא הודעה על כך עם דחיפה לעשות את זה,
בסיום הסריקה שכן הצליחה."

אפס רשת ואפס נגיעה במאגר האמיתי: הפונקציות הטהורות נבדקות ישירות,
ולוגיקת הצד-לקוח נשלפת מ-app.js ורצה ב-node מול DOM מזויף.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


# ══ 1. הצד השרתי: פער עוגייה הוא מצב מובנה, לא מחרוזת ════════════════════
import main       # noqa: E402
import scraper    # noqa: E402

gap = main._cookie_gap("פורום אוצר התורה", "https://forum-otzar-hatorah.co.il/",
                       "xenforo", scraper.AuthRequired("דורש התחברות"))
ok("הפער נושא את שם הפורום", gap["forum"] == "פורום אוצר התורה", gap)
ok("ואת הכתובת", gap["url"].startswith("https://forum-otzar"), gap)
ok("ואת שם העוגייה הנכון לפלטפורמה", gap["cookie_name"] == "xf_user", gap)
ok("NodeBB מקבל express.sid",
   main._cookie_gap("x", "", "nodebb", "e")["cookie_name"] == "express.sid")
ok("Discourse מקבל _t",
   main._cookie_gap("x", "", "discourse", "e")["cookie_name"] == "_t")
# פלטפורמה לא מוכרת לא מפילה כלום ולא ממציאה שם
ok("פלטפורמה חסרה נופלת לברירת מחדל",
   main._cookie_gap("x", "", None, "e")["cookie_name"] == "express.sid")

src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
# AuthRequired חייב להיתפס **לפני** Exception הכללי, אחרת הוא נבלע כדילוג
# רגיל ו"צריך עוגייה" לא ייאמר לעולם.
# ההשוואה היא מול ה-`except Exception` ש**בולע** את הכישלון, ולא מול
# מטפל הניקוי שמריץ finish_scan_run ואז `raise` — הוא אינו בולע דבר.
for fn, swallow in (("start_scrape", '_scrape_state["error"] = str(e)'),
                    ("start_scrape_all", '_scrape_state["skipped"].append(')):
    i = src.index("def %s(" % fn)
    body = src[i:i + 9000]
    auth = body.find("except scraper.AuthRequired")
    generic = -1
    for m in re.finditer(r"except Exception as e:", body):
        tail = body[m.end():m.end() + 400]
        if swallow in tail and "raise" not in tail.split(swallow)[0]:
            generic = m.start()
            break
    ok("%s: AuthRequired נתפס לפני הבולע" % fn, 0 <= auth < generic, (auth, generic))
ok("שני המסלולים מאפסים את cookie_gaps",
   src.count('"cookie_gaps": []') == 2, src.count('"cookie_gaps": []'))


# ══ 2. הצד-לקוחי, מתוך app.js האמיתי ═════════════════════════════════════
app = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()


def grab(name):
    """שולף הצהרת פונקציה שלמה לפי איזון סוגריים מסולסלים."""
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
const esc = s => String(s == null ? '' : s);
%s
%s
const P_ALL = {
  done: true, running: false, error: null, all_mode: true, cancelled: false,
  auto: false, added: 447,
  skipped: [{forum: 'סגור', error: 'התחברות', needs_cookie: true},
            {forum: 'נפל', error: 'אין חיבור'}],
  cookie_gaps: [{forum: 'סגור', url: 'https://a.example', platform: 'xenforo',
                 cookie_name: 'xf_user', error: 'התחברות'}],
};
const out = {
  gaps: cookieGapsOf(P_ALL).map(g => g.forum),
  none: cookieGapsOf({done: true, added: 5}).length,
  // כפילות: אותו פורום נספר פעם אחת בלבד
  dedup: cookieGapsOf({cookie_gaps: [
      {forum: 'א', cookie_name: 'x'}, {forum: 'א', cookie_name: 'x'},
      {forum: 'ב', cookie_name: 'y'}]}).map(g => g.forum),
  // רשומה פגומה לא מפילה את סוף הסריקה
  junk: cookieGapsOf({cookie_gaps: [null, {}, {forum: 'ג'}]}).map(g => g.forum),
  // ההדרכה מדברת על הפורום ועל העוגייה שנמסרו לה
  helpXf: cookieHelpHtml({url: 'https://www.prog.co.il', cookieName: 'xf_user'}),
  helpDefault: cookieHelpHtml(),
};
console.log(JSON.stringify(out));
""" % (grab("cookieGapsOf"), grab("cookieHelpHtml"))

f = os.path.join(tempfile.mkdtemp(), "t.js")
io.open(f, "w", encoding="utf-8").write(JS)
r = subprocess.run(["node", f], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
if r.returncode:
    print(r.stderr[-800:])
    sys.exit(1)
res = json.loads(r.stdout.strip())

ok("הפער מזוהה בסוף הסריקה", res["gaps"] == ["סגור"], res["gaps"])
ok("סריקה נקייה אינה מנדנדת", res["none"] == 0, res["none"])
ok("אותו פורום נספר פעם אחת", res["dedup"] == ["א", "ב"], res["dedup"])
ok("רשומה פגומה אינה מפילה", res["junk"] == ["ג"], res["junk"])

hx, hd = res["helpXf"], res["helpDefault"]
# 🚨 ההדרכה הייתה מקובעת ל-mitmachim.top ול-express.sid בחמישה מקומות.
# נדנוד להוסיף עוגייה לפרוג ששולח את המשתמש למתמחים אינו רק חסר תועלת —
# הוא מטעה, ובדיוק ברגע שבו הוא אמור לעזור.
ok("🚨 ההדרכה נוקבת בפורום הנכון", "www.prog.co.il" in hx)
ok("🚨 ובשם העוגייה הנכון", "xf_user" in hx)
ok("ולא נשאר בה mitmachim", "mitmachim" not in hx, hx[:120])
ok("ולא נשאר בה express.sid", "express.sid" not in hx)
ok("בלי הקשר ההתנהגות נשמרת", "mitmachim.top" in hd and "express.sid" in hd)

# ══ 3. החיווט בסוף הסריקה ════════════════════════════════════════════════
# החלון הזה נפתח **גם כשחלון הסנכרון פתוח**: הוא נשאר פתוח לאורך כל
# הסריקה (פס ההתקדמות יושב בתוכו), ו-isModalOpen הסתיר את רשימת המדולגים
# בדיוק במקרה הנפוץ ביותר.
ok("הנדנוד אינו מותנה בכך שאין חלון פתוח",
   re.search(r"if \(gaps\.length && !p\.cancelled && !p\.auto\) \{\s*"
             r"promptForCookie\(gaps\);", app) is not None)
ok("סריקה שבוטלה אינה מנדנדת", "gaps.length && !p.cancelled" in app)
ok("סריקה אוטומטית ברקע אינה קופצת למסך", "!p.auto) {\n          promptForCookie" in app)
ok("מדולגים שאינם עוגייה עדיין מוצגים בנפרד",
   "const other = (p.skipped || []).filter(x => !x.needs_cookie);" in app)
ok("גם סריקת פורום בודד שנעצרה על התחברות מנדנדת",
   "if (gaps.length && !p.auto) promptForCookie(gaps);" in app)
ok("הכפתור מוביל לחלון הסנכרון עם הפורום הנכון",
   "openInternetSync({ cookieFor: gaps[0] })" in app)
# 🚨 פורום שנמחק בין הסריקה ללחיצה: בלי הבדיקה הזו הסימון הממוקד מחליף את
# ברירת המחדל ואף תיבה אינה מסומנת — חלון שאומר "לא סומן אף פורום".
ok("🚨 פורום שנעלם נופל חזרה לברירת המחדל",
   "if (focus && !forums.some(f => f.name === focus.forum)) focus = null;" in app)
ok("שם העוגייה מתרענן אחרי שהסימון נקבע",
   re.search(r"if \(focus\) \{[^}]*updateSyncHint\(\);", app, re.S) is not None)

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("COOKIE NUDGE TESTS PASSED")
