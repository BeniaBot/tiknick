# -*- coding: utf-8 -*-
"""
0.9 — שלושת המקטעים החדשים בחזונישניק.

כולם מחושבים מהפוסטים שהדוח כבר הוריד, בתוך ה-<script> שלו: **אפס בקשות
רשת נוספות**. זה מה שהופך אותם ליציבים — אין נתיב רשת חדש שיכול להיכשל,
אין עומס נוסף על פורום של מתנדבים, והדוח השמור עובד אופליין כמו קודם.

הבדיקה מריצה את ה-JS האמיתי מתוך הדוח שנוצר, מול DOM מזויף.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chazonishnik as CZ   # noqa: E402
import i18n                 # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


DAY = 86400000
BASE_TS = 1735689600000          # 2025-01-01, קבוע — הבדיקה לא תלויה בשעון


def post(i, ts, hour, likes, tid, title, votes_ok=True,
         mentions=None, voters=None):
    return {"pid": i, "title": title, "tid": tid, "ts": ts,
            "date": "2025-01-01", "hour": hour, "dow": 2, "day": "רביעי",
            "month": "2025-01", "likes": likes, "voters": voters or [],
            "votes_ok": votes_ok, "mentions": mentions or [], "words": 40}


def build(posts):
    return CZ._build_html("someone", "https://forum.example", 7, posts)


def render(html, section):
    """מריץ את ה-<script> של הדוח מול DOM מזויף ומחזיר את תוכן המקטע."""
    m = re.search(r"const data=(\[[\s\S]*?\]);", html)
    assert m, "data array not found in report"
    body = html[html.index("const data="):html.rindex("</script>")]
    js = """
const boxes = {};
const mk = () => ({ _h: '', set innerHTML(v){ this._h = v; },
                    get innerHTML(){ return this._h; }, innerText: '',
                    title: '', style: {} });
for (const id of ['list-gaps','list-sharp','list-threads','list-social','list-fans','list-best',
                  'stat-posts','stat-likes','stat-words','stat-time'])
  boxes[id] = mk();
globalThis.document = { getElementById: id => boxes[id] || mk() };
globalThis.Chart = function(){ return {}; };
Chart.defaults = {};
%s
console.log(JSON.stringify({ gaps: boxes['list-gaps'].innerHTML,
                             sharp: boxes['list-sharp'].innerHTML,
                             social: boxes['list-social'].innerHTML,
                             threads: boxes['list-threads'].innerHTML }));
""" % body
    p = os.path.join(tempfile.mkdtemp(), "r.js")
    io.open(p, "w", encoding="utf-8").write(js)
    r = subprocess.run(["node", p], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-600:])
    return json.loads(r.stdout.strip())[section]


# ══ אפס בקשות נוספות — זה העיקר ═══════════════════════════════════════════
src = io.open(CZ.__file__, encoding="utf-8").read()
head = src[:src.index("HTML_TEMPLATE")] if "HTML_TEMPLATE" in src else src
ok("לא נוסף אף נתיב רשת חדש",
   src.count("_get_json(") == head.count("_get_json("),
   (src.count("_get_json("), head.count("_get_json(")))
ok("מזהה השרשור נאסף מהתשובה הקיימת",
   '"tid": (post.get("topic") or {}).get("tid"),' in src)
ok("ופעם אחת בלבד", src.count('"tid": (post.get("topic")') == 1)


# ══ 💤 תקופות שקט ═════════════════════════════════════════════════════════
posts = [post(1, BASE_TS, 10, 1, 100, "א"),
         post(2, BASE_TS + 2 * DAY, 10, 1, 100, "א"),
         post(3, BASE_TS + 200 * DAY, 10, 1, 101, "ב"),   # שתיקה של 198 יום
         post(4, BASE_TS + 245 * DAY, 10, 1, 102, "ג")]   # ועוד 45
out = render(build(posts), "gaps")
ok("שתי השתיקות זוהו", out.count("list-item") >= 2, out[:200])
ok("הארוכה נמדדה נכון", "198 ימים" in out, out[:200])
ok("והקצרה גם", "45 ימים" in out, out[:200])
ok("הארוכה מוצגת ראשונה", out.index("198") < out.index("45"), out[:120])

# הפסקה קצרה אינה שתיקה
tight = [post(i, BASE_TS + i * DAY, 10, 1, 100, "א") for i in range(1, 12)]
out = render(build(tight), "gaps")
# החץ מופיע רק בשורת שתיקה *בין* פוסטים. "שותק כרגע" הוא שורה לגיטימית
# נפרדת — הפוסטים בפיקסצ'ר מתוארכים לעבר, והדוח אומר על כך את האמת.
gap_rows = out.count("←")
ok("הפסקות של ימים אינן נספרות כשתיקה", gap_rows == 0, out[:200])

out = render(build([post(1, BASE_TS, 10, 1, 100, "א")]), "gaps")
ok("פוסט בודד — נאמר במפורש", "אין מספיק פוסטים" in out, out[:160])


# ══ 🔥 מתי הוא הכי חד ═════════════════════════════════════════════════════
sharp = ([post(i, BASE_TS + i * DAY, 23, 10, 200 + i, "לילה") for i in range(6)] +
         [post(50 + i, BASE_TS + i * DAY, 8, 1, 300 + i, "בוקר") for i in range(6)])
out = render(build(sharp), "sharp")
ok("השעה המוצלחת היא 23", "23:00" in out and "10.0" in out, out[:260])
ok("והחלשה היא 08", "08:00" in out, out[:260])
ok("הממוצע הכללי מוצג", "5.5" in out, out[:300])

# מדגם קטן מדי — לא ממציאים ממצא
tiny = [post(i, BASE_TS + i * DAY, i % 24, i, 400 + i, "x") for i in range(6)]
out = render(build(tiny), "sharp")
ok("מדגם קטן לא מפיק מסקנה", "אין מספיק פוסטים בשעה" in out, out[:200])

# ספירת לייקים חלקית — המקטע מושבת במקום לשקר
broken = [post(i, BASE_TS + i * DAY, 23, 0, 500 + i, "x", votes_ok=(i > 8))
          for i in range(10)]
out = render(build(broken), "sharp")
ok("ספירה חלקית משביתה את המקטע", "מושבת" in out, out[:220])


# ══ 💬 כמה הוא נשאר בשרשור ════════════════════════════════════════════════
threads = ([post(1, BASE_TS, 10, 1, 900, "שרשור ארוך")] * 0 +
           [post(i, BASE_TS + i * DAY, 10, 1, 900, "שרשור ארוך") for i in range(1, 8)] +
           [post(20 + i, BASE_TS + i * DAY, 10, 1, 901, "בינוני") for i in range(3)] +
           [post(40 + i, BASE_TS + i * DAY, 10, 1, 910 + i, "חד פעמי") for i in range(4)])
out = render(build(threads), "threads")
ok("שרשורים חד-פעמיים נספרו", "4 · 67%" in out, out[:400])
ok("שרשור ארוך זוהה", "7 הודעות" in out, out[:400])
ok('סה"כ שרשורים', "6" in out, out[:400])
ok("יש קישור לשרשור לפי מזהה", "/topic/900" in out, out[:400])

# כותרת ריקה: כל הפוסטים מקבלים "תגובה" — קיבוץ לפי כותרת היה מאחד אותם
noname = [post(i, BASE_TS + i * DAY, 10, 1, 700 + i, "תגובה") for i in range(5)]
out = render(build(noname), "threads")
# חמישה מזהים שונים = חמישה שרשורים נפרדים, בכל אחד פוסט אחד.
# קיבוץ לפי הכותרת "תגובה" היה נותן שרשור מזויף אחד עם חמישה פוסטים.
ok("קיבוץ לפי מזהה ולא לפי כותרת", "5 · 100%" in out, out[:300])


# ══ חילוץ אזכורים — הכרטיס הוסר מ-0.9.0, הפונקציות נשארו ═════════════════
# הכרטיס "עם מי הוא מדבר" ירד כי החצי שמנחש (מי הוא מזכיר) לא היה מול מה
# לאמת. החילוץ עצמו נכון ומכוסה, כדי שהחזרה אליו תתחיל מבסיס בדוק.
ok("הכרטיס אינו בתבנית", "list-social" not in io.open(
    CZ.__file__, encoding="utf-8").read())
ok("mentions אינו נשלח לדוח", '"mentions": mentions' not in io.open(
    CZ.__file__, encoding="utf-8").read())

ok("אזכור פשוט", CZ._mentions_in("שלום @דוד", "x") == ["דוד"])
ok("ציטוט של NodeBB", CZ._mentions_in("@משה said in נושא:", "x") == ["משה"])
ok("מייל אינו אזכור", CZ._mentions_in("beni@gmail.com", "x") == [])
ok("גם מייל מסובך", CZ._mentions_in("a.b_c%d+e@example.co.il", "x") == [])
ok("ו' החיבור לפני אזכור", CZ._mentions_in("@דוד ו@שרה גם", "x") == ["דוד", "שרה"])
ok("גם ה' הידיעה", CZ._mentions_in("ה@מנהל אמר", "x") == ["מנהל"])
ok("בלי כפילויות", CZ._mentions_in("@דוד וגם @שרה, ושוב @דוד", "x") == ["דוד", "שרה"])
ok("בלי המשתמש עצמו", CZ._mentions_in("@לומדעס", "לומדעס") == [])
ok("@ בתוך כתובת אינו אדם",
   CZ._mentions_in("ראו https://youtube.com/@Chan וגם @יוסי", "x") == ["יוסי"])
ok("@everyone אינו אדם", CZ._mentions_in("@everyone שימו לב @דוד", "x") == ["דוד"])
ok("גוף ציטוט מוסר",
   CZ._mentions_in(CZ._strip_quotes(
       "<p>@דוד</p><blockquote><p><a>@sara</a> said in x:</p>"
       "<p>מסכים עם <a>@moshe</a></p></blockquote>"), "x") == ["דוד", "sara"])


# ══ אנגלית ════════════════════════════════════════════════════════════════
i18n.set_lang("en")
try:
    en = build(posts)
    ok("הכותרות תורגמו", "Periods of silence" in en or "silence" in en.lower(),
       [l for l in en.splitlines() if "list-gaps" in l][:1])
    out = render(en, "gaps")
    ok("גם הטקסט שבתוך ה-JS", "days" in out and "ימים" not in out, out[:200])
finally:
    i18n.set_lang("he")

he = build(posts)
ok("ובעברית הכול חוזר כשהיה", "תקופות שקט" in he)

# ══ מספר הפוסטים הרשמי, ולא מה שהסריקה הצליחה למשוך ══════════════════════
# בנימין: "שהדוח יציג את מספר הפוסטים הרשמי מדף הפרופיל ולא מהסריקה שלו, כי
# יש פוסטים שהסריקה לא מצליחה לגשת אליהם כי אין הרשאה (הם מחוקים)".
# הנתון כבר היה בדוח (`meta.postcount`) — ה-KPI פשוט לא קרא אותו.
def kpi(posts, meta=None):
    """מריץ את הדוח מול DOM מזויף ומחזיר את ערכי מוני הכותרת."""
    html = CZ._build_html("someone", "https://forum.example", 7, posts, meta)
    body = html[html.index("const data="):html.rindex("</script>")]
    js = """
const boxes = {};
const mk = () => ({ _h: '', set innerHTML(v){ this._h = v; },
                    get innerHTML(){ return this._h; }, innerText: '',
                    title: '', style: {} });
for (const id of ['list-gaps','list-sharp','list-threads','list-fans','list-best',
                  'stat-posts','stat-posts-sub','stat-likes','stat-words','stat-time'])
  boxes[id] = mk();
globalThis.document = { getElementById: id => boxes[id] || mk() };
globalThis.Chart = function(){ return {}; };
Chart.defaults = {};
%s
console.log(JSON.stringify({ posts: boxes['stat-posts'].innerText,
                             sub: boxes['stat-posts-sub'].innerText,
                             subTitle: boxes['stat-posts-sub'].title,
                             words: boxes['stat-words'].innerText,
                             time: boxes['stat-time'].innerText,
                             likes: boxes['stat-likes'].innerText }));
""" % body
    f = os.path.join(tempfile.mkdtemp(), "k.js")
    io.open(f, "w", encoding="utf-8").write(js)
    r = subprocess.run(["node", f], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-600:])
    return json.loads(r.stdout.strip())


three = [post(i, BASE_TS + i * DAY, 10, 1, 100, "א") for i in range(1, 4)]

k = kpi(three, {"postcount": 250})
ok("הכותרת מציגה את המספר הרשמי", k["posts"] == "250", k)
ok("ושורת המשנה אומרת כמה נמדד",
   "3" in k["sub"] and "250" in k["sub"], k["sub"])
ok("ההסבר לפער מוצמד כטולטיפ",
   "מחוקים" in k["subTitle"] and "הרשאה" in k["subTitle"], k["subTitle"][:80])

# הפער הוא רק כשהוא אמיתי — אחרת שורת המשנה מיותרת ומבלבלת
k = kpi(three, {"postcount": 3})
ok("אין פער — אין שורת משנה", k["posts"] == "3" and k["sub"] == "", k)

# פורום שלא מחזיר postcount בכלל: נופלים לאחור למה שנסרק, בלי להציג 0
k = kpi(three, {"postcount": 0})
ok("בלי postcount נופלים למה שנסרק", k["posts"] == "3" and k["sub"] == "", k)
k = kpi(three)
ok("וגם בלי meta כלל", k["posts"] == "3" and k["sub"] == "", k)

# סריקה שהחזירה **יותר** ממה שהפרופיל מצהיר (המונה של הפורום מתעדכן באיחור)
# לא אמורה להקטין את המספר שהמשתמש רואה.
k = kpi(three, {"postcount": 2})
ok("מונה מיושן בפרופיל לא מקטין את התוצאה",
   k["posts"] == "3" and k["sub"] == "", k)

# הדבר החשוב: **שאר הדוח ממשיך לעבוד על מה שנסרק בלבד.** ממוצע לייקים על
# מכנה שכולל פוסטים שאיש לא מדד היה מספר שקרי.
# נבדק בהתנהגות ולא בטקסט: המונים הנגזרים חייבים לצאת זהים בדיוק, בין אם
# הפרופיל מצהיר 3 פוסטים ובין אם 999.
k_small = kpi(three, {"postcount": 3})
k_big   = kpi(three, {"postcount": 999})
ok("המספר הרשמי לא נגע בשאר החישובים",
   k_small["words"] == k_big["words"] and k_small["time"] == k_big["time"]
   and k_small["likes"] == k_big["likes"],
   (k_small, k_big))
ok("והוא כן שינה את הכותרת", k_big["posts"] == "999" and k_small["posts"] == "3",
   (k_small["posts"], k_big["posts"]))

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("CHAZONISHNIK INSIGHT TESTS PASSED")
