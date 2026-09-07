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
                    get innerHTML(){ return this._h; }, innerText: '' });
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


# ══ 👥 עם מי הוא מדבר ═════════════════════════════════════════════════════
def v(name, uid=2):
    return {"uid": uid, "username": name}


social = [
    # חבר: הוא פונה אליו והוא מחזיר בלייקים
    post(1, BASE_TS, 10, 2, 1, "א", mentions=["דוד"], voters=[v("דוד"), v("שרה")]),
    post(2, BASE_TS + DAY, 10, 1, 2, "ב", mentions=["דוד"], voters=[v("דוד")]),
    # פונה אליו והוא שותק — שלוש פעמים, אפס לייקים
    post(3, BASE_TS + 2 * DAY, 10, 0, 3, "ג", mentions=["יריב"]),
    post(4, BASE_TS + 3 * DAY, 10, 0, 4, "ד", mentions=["יריב"]),
    post(5, BASE_TS + 4 * DAY, 10, 0, 5, "ה", mentions=["יריב"]),
    # מעריץ שקט: שרה עושה לייקים, הוא לא מזכיר אותה מעולם
    post(6, BASE_TS + 5 * DAY, 10, 1, 6, "ו", voters=[v("שרה")]),
]
out = render(build(social), "social")
ok("הקרובים אליו מוצגים", "הקרובים אליו" in out, out[:200])
ok("דוד שם עם שני הצדדים", "2 פניות · 2 לייקים" in out, out[:400])
ok("מי שפונה אליהם ולא קיבל לייק",
   "3 פניות" in out and "לא הגיע מהם לייק" in out, out[:600])
ok("מעריץ שקט מזוהה", "מעריצים שקטים" in out and "שרה" in out, out[:800])
ok("יש קישור לפרופיל", "/user/" in out, out[:300])
ok("הוא עצמו לא ברשימה", "someone" not in out, out[:400])

# בלי אזכורים בכלל — נאמר במפורש, בלי להמציא
none_ = [post(i, BASE_TS + i * DAY, 10, 1, 800 + i, "x", voters=[v("שרה")])
         for i in range(3)]
out = render(build(none_), "social")
ok("בלי אזכורים — מעריצים בלבד", "מעריצים שקטים" in out or "לא נמצאו אזכורים" in out,
   out[:300])

# חילוץ האזכורים עצמו — הכלל זהה לזה של שדות התיוג
ok("אזכור פשוט", CZ._mentions_in("שלום @דוד", "x") == ["דוד"])
ok("ציטוט של NodeBB", CZ._mentions_in("@משה said in נושא:", "x") == ["משה"])
ok("מייל אינו אזכור", CZ._mentions_in("beni@gmail.com", "x") == [])
ok("גם מייל מסובך", CZ._mentions_in("a.b_c%d+e@example.co.il", "x") == [])
# בעברית ו'/ה' החיבור נדבקות למילה. הכלל "@ פותח מילה" פספס את זה, ולכן
# הכלל הוא "מה שלפני ה-@ אינו נראה כמו מייל".
ok("ו' החיבור לפני אזכור", CZ._mentions_in("@דוד ו@שרה גם", "x") == ["דוד", "שרה"])
ok("גם ה' הידיעה", CZ._mentions_in("ה@מנהל אמר", "x") == ["מנהל"])
ok("בלי כפילויות", CZ._mentions_in("@דוד וגם @שרה, ושוב @דוד", "x") == ["דוד", "שרה"])
ok("בלי המשתמש עצמו", CZ._mentions_in("@לומדעס", "לומדעס") == [])


# ── 🚨 הבאג שבנימין תפס: הסלאג מול שם התצוגה ─────────────────────────────
# NodeBB מכניס באזכור את ה-slug ("@צול-גאה") ומחזיר ברשימת המצביעים את שם
# התצוגה ("צול גאה"). השוואה ישירה ביניהם לא מתאימה אף פעם, והתוצאה סימטרית
# ומטעה: כל מי שפנה אליו נראה "שותק", וכל מי שעשה לו לייק נראה "לא נפנו אליו".
slugcase = [
    post(1, BASE_TS, 10, 1, 1, "א", mentions=["צול-גאה"],
         voters=[{"uid": 9, "username": "צול גאה", "userslug": "צול-גאה"}]),
    post(2, BASE_TS + DAY, 10, 1, 2, "ב", mentions=["צול-גאה"],
         voters=[{"uid": 9, "username": "צול גאה", "userslug": "צול-גאה"}]),
    post(3, BASE_TS + 2 * DAY, 10, 1, 3, "ג", mentions=["צול-גאה"],
         voters=[{"uid": 9, "username": "צול גאה", "userslug": "צול-גאה"}]),
]
out = render(build(slugcase), "social")
ok("הסלאג ושם התצוגה התאחדו", "הקרובים אליו" in out, out[:300])
ok("ולא הוכרז 'לא הגיע מהם לייק'", "לא הגיע מהם לייק" not in out, out[:300])
ok("ולא הוכרז 'מעריצים שקטים'", "מעריצים שקטים" not in out, out[:300])
ok("הספירה משני הצדדים נכונה", "3 פניות · 3 לייקים" in out, out[:300])
ok("מוצג שם התצוגה, לא הסלאג", "צול גאה" in out, out[:300])
ok("והקישור לפי הסלאג",
   "%D7%A6%D7%95%D7%9C-%D7%92%D7%90%D7%94" in out or "צול-גאה" in out, out[:300])

# אותיות גדולות/קטנות וקו תחתון — אותו אדם
mixed = [post(i, BASE_TS + i * DAY, 10, 1, 10 + i, "x", mentions=["David_Cohen"],
              voters=[{"uid": 8, "username": "david cohen", "userslug": "david-cohen"}])
         for i in range(3)]
out = render(build(mixed), "social")
ok("קו תחתון מול רווח מול אותיות גדולות", "3 פניות · 3 לייקים" in out, out[:300])

# ספירת לייקים חלקית — לא טוענים "לא הגיע מהם לייק"
partial = [post(i, BASE_TS + i * DAY, 10, 0, 20 + i, "x", mentions=["יריב"],
                votes_ok=(i > 1)) for i in range(4)]
out = render(build(partial), "social")
# האזהרה עצמה מזכירה את שם הקבוצה, ולכן בודקים את **הכותרת** ולא את המחרוזת
ok("ספירה חלקית מסתירה את הקבוצה השלילית",
   "<b>פונה אליהם" not in out, out[:400])
ok("ואומרת למה", "חלקית" in out, out[:400])

# הערת ההיקף תמיד מופיעה
ok("מוצג היקף הניתוח", "מתוך הפוסטים שנסרקו בלבד" in out, out[-300:])


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

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("CHAZONISHNIK INSIGHT TESTS PASSED")
