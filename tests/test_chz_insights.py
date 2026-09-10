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
    # mentions בפורמט שהדוח באמת מקבל: [{k, name, slug}]
    ms = [{"k": CZ._norm_key(m), "name": str(m).replace("-", " "), "slug": m}
          for m in (mentions or [])]
    return {"pid": i, "title": title, "tid": tid, "ts": ts,
            "date": "2025-01-01", "hour": hour, "dow": 2, "day": "רביעי",
            "month": "2025-01", "likes": likes, "down": 0, "voters": voters or [],
            "votes_ok": votes_ok, "mentions": ms, "words": 40,
            # השדות שמגיעים חינם עם הפוסט
            "is_main": False, "replies": 0, "to_pid": None, "reply_uid": None,
            "topic_uid": 55, "topic_posts": 10, "cat": "כללי"}


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
                  'list-replyto','list-hosts','list-role','list-cats','list-spark',
                  'stat-posts','stat-posts-sub','stat-likes','stat-words','stat-time'])
  boxes[id] = mk();
globalThis.document = { getElementById: id => boxes[id] || mk() };
globalThis.Chart = function(){ return {}; };
Chart.defaults = {};
%s
console.log(JSON.stringify({ gaps: boxes['list-gaps'].innerHTML,
                             sharp: boxes['list-sharp'].innerHTML,
                             social: boxes['list-social'].innerHTML,
                             threads: boxes['list-threads'].innerHTML,
                             replyto: boxes['list-replyto'].innerHTML,
                             hosts: boxes['list-hosts'].innerHTML,
                             role: boxes['list-role'].innerHTML,
                             cats: boxes['list-cats'].innerHTML,
                             spark: boxes['list-spark'].innerHTML,
                             likes: boxes['stat-likes'].innerHTML
                                    || boxes['stat-likes'].innerText }));
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

# ספירת הלייקים מגיעה חינם עם הפוסט, ולכן המקטע הזה כבר **אינו** תלוי
# בעוגייה ואינו משבית את עצמו. נמדד: סכום `upvotes` על 36 פוסטים = 41,
# בדיוק כמו 36 בקשות הצבעה עם עוגייה.
# שתי שעות, כדי שיהיה מה להשוות — בלי שמות מצביעים בכלל
nonames = ([post(i, BASE_TS + i * DAY, 23, 9, 500 + i, "x", votes_ok=False)
            for i in range(6)]
           + [post(60 + i, BASE_TS + i * DAY, 8, 1, 560 + i, "x", votes_ok=False)
              for i in range(6)])
out = render(build(nonames), "sharp")
ok("בלי שמות מצביעים המקטע עדיין עובד", "מושבת" not in out, out[:220])
ok("והוא מציג לייקים לפוסט", "לייקים לפוסט" in out, out[:220])


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

# ══ 👥 עם מי הוא מדבר — הכרטיס שחזר, והפעם מול מה שהפורום באמת שולח ══════
# הוא נמשך מ-0.9.0 אחרי ששתי גרסאות נתנו תוצאות שגויות אצל בנימין. הסיבה
# התבררה רק כשהסתכלנו בתוכן אמיתי: `content` הוא HTML, ובאזכור ה-@ והשם
# מופרדים בתגית — ולכן רגקס שמחפש שם אחרי ה-@ מצא **אפס** ב-26 פוסטים
# שכולם מזכירים מישהו. נמדד על החשבון של בנימין ב-mitmachim.top.

A = ('<p><a class="plugin-mentions-user plugin-mentions-a" '
     'href="/user/%D7%A6%D7%95%D7%9C-%D7%92%D7%90%D7%94" '
     'aria-label="Profile: צול גאה">@<bdi>צול גאה</bdi></a> תודה רבה</p>')
ok("אזכור אמיתי מחולץ", CZ._mentions_from_html(A, "בנימין-מחשבים")
   == [("צול-גאה", "צול גאה")], CZ._mentions_from_html(A, "בנימין-מחשבים"))
ok("הרגקס הישן היה מחזיר ריק", CZ._mentions_in(A, "x") == [], CZ._mentions_in(A, "x"))
ok("המשתמש עצמו מוחרג", CZ._mentions_from_html(A, "צול גאה") == [])
ok("גם לפי הצורה עם המקף", CZ._mentions_from_html(A, "צול-גאה") == [])
ok("בלי כפילויות", len(CZ._mentions_from_html(A + A, "x")) == 1)
ok("טקסט בלי אזכור", CZ._mentions_from_html("<p>שלום עולם</p>", "x") == [])
ok("קישור רגיל אינו אזכור",
   CZ._mentions_from_html('<a href="/user/דוד">דוד</a>', "x") == [])

# **המפתח המנורמל הוא כל הסיפור**: האזכור נושא slug והמצביע נושא שם תצוגה.
ok("slug ושם תצוגה מתאימים", CZ._norm_key("צול-גאה") == CZ._norm_key("צול גאה"))
ok("וגם קו תחתון", CZ._norm_key("א_ב") == CZ._norm_key("א ב"))
ok("אבל אנשים שונים לא מתמזגים", CZ._norm_key("דוד") != CZ._norm_key("דויד"))

# אזכור בתוך **גוף** ציטוט שייך למי שכתב אותו, לא לנבדק
# כותרת הציטוט של NodeBB ("@פלוני said in") היא **כן** פנייה שלו ונשמרת;
# אזכור שקבור בתוך גוף הציטוט שייך למי שכתב אותו ויורד.
HEAD = ('<blockquote><p>' + A + ' said in נושא:</p>'
        + 'טקסט של מישהו אחר ' * 40 + '</blockquote><p>מסכים</p>')
ok("כותרת הציטוט נספרת", CZ._mentions_from_html(HEAD, "x") == [("צול-גאה", "צול גאה")],
   CZ._mentions_from_html(HEAD, "x"))
DEEP = ('<blockquote><p>מישהו said in נושא:</p>' + 'מילוי ארוך ' * 40
        + A + '</blockquote><p>מסכים</p>')
ok("אזכור עמוק בתוך גוף הציטוט יורד", CZ._mentions_from_html(DEEP, "x") == [],
   CZ._mentions_from_html(DEEP, "x"))

# ── והכרטיס עצמו, מול DOM אמיתי ─────────────────────────────────────────
def voter(uid, name, slug):
    return {"uid": uid, "username": name, "userslug": slug}

# חבר: הוא מזכיר אותו והוא עושה לו לייק. שים לב שהאזכור בא כ-slug
# והמצביע כשם תצוגה — בדיוק המצב שהפיל את הגרסאות הקודמות.
soc = [
    post(1, BASE_TS, 10, 1, 100, "א", mentions=["צול-גאה"],
         voters=[voter(9, "צול גאה", "צול-גאה")]),
    post(2, BASE_TS + DAY, 10, 1, 100, "א", mentions=["צול-גאה"],
         voters=[voter(9, "צול גאה", "צול-גאה")]),
    # מעריץ שקט: עושה לייק, לא מוזכר
    post(3, BASE_TS + 2 * DAY, 10, 1, 101, "ב",
         voters=[voter(11, "מעריץ שקט", "מעריץ-שקט")]),
    # פונה אליו שלוש פעמים ולא מקבל לייק
    post(4, BASE_TS + 3 * DAY, 10, 0, 102, "ג", mentions=["מתעלם"]),
    post(5, BASE_TS + 4 * DAY, 10, 0, 102, "ג", mentions=["מתעלם"]),
    post(6, BASE_TS + 5 * DAY, 10, 0, 102, "ג", mentions=["מתעלם"]),
]
out = render(build(soc), "social")
ok("הקרובים אליו", "הקרובים אליו" in out and "צול גאה" in out, out[:200])
ok("מעריצים שקטים", "מעריצים שקטים" in out and "מעריץ שקט" in out)
ok("פונה אליהם ולא הגיע לייק", "לא הגיע מהם לייק" in out and "מתעלם" in out)
ok("החבר לא נספר כמעריץ שקט",
   out.index("צול גאה") < out.index("מעריץ שקט"), "סדר הקבוצות")
ok("הקישור נבנה מהסלאג",
   "/user/" + __import__("urllib.parse", fromlist=["x"]).quote("צול-גאה") in out,
   [x for x in out.split('"') if "/user/" in x][:2])

# ספירת לייקים חלקית — הקבוצה השלילית נעלמת, כי "לא הגיע לייק" אינו ידוע
part = [dict(p, votes_ok=False) for p in soc]
out2 = render(build(part), "social")
ok("בלי ספירת לייקים אין קבוצה שלילית", "🙊 פונה אליהם" not in out2)
ok("והמשתמש מקבל הסבר", "ידועים רק לחלק מהלייקים" in out2, out2[-260:])

# בלי כלום — מצב ריק מפורש
out3 = render(build([post(1, BASE_TS, 10, 0, 1, "א")]), "social")
ok("מצב ריק מפורש", "לא נמצאו אזכורים" in out3, out3[:120])

# בריחה: שם עוין מהפורום
bad = [post(1, BASE_TS, 10, 1, 1, "א", mentions=["x"],
            voters=[voter(9, '<img src=x onerror=alert(1)>', "x")])]
out4 = render(build(bad), "social")
ok("שם עוין עובר בריחה", "<img src=x" not in out4)

# ══ חמשת המקטעים מהשדות שכבר הגיעו — אפס בקשות ═══════════════════════════
# `isMainPost`, `replies`, `category`, `topic.uid` — כולם היו בתשובה מהיום
# הראשון ואיש לא נגע בהם. נמדד על בנימין: 98% מהפוסטים שלו הם תגובות,
# הוא חי בשרשורים של 431 אנשים, ו-1,433 תגובות נענו לפוסטים שלו.
def rich(i, **kw):
    p = post(i, BASE_TS + i * DAY, 10, kw.pop("likes", 0), kw.pop("tid", 100 + i), "נושא %d" % i)
    p.update(kw)
    return p


def build_meta(posts, meta):
    return CZ._build_html("someone", "https://forum.example", 7, posts, meta)


def render_meta(posts, meta, section):
    return render(build_meta(posts, meta), section)


NAMES = {"names": {"99": {"name": "דוד כהן", "slug": "דוד-כהן"},
                   "88": {"name": "שרה", "slug": "שרה"},
                   "77": {"name": "המארח", "slug": "המארח"}},
         "reply_resolved": 8, "reply_total": 20}

rows = ([rich(i, reply_uid=99, to_pid=900 + i, topic_uid=77, cat="מחשבים",
              replies=(3 if i == 1 else 0)) for i in range(1, 6)]
        + [rich(i, reply_uid=88, to_pid=900 + i, topic_uid=55, cat="סלולרי")
           for i in range(6, 9)]
        + [rich(9, is_main=True, topic_uid=7, cat="מחשבים")])

# 🎭 יוזם או מגיב
out = render_meta(rows, NAMES, "role")
ok("נספרו שרשורים שנפתחו", ">1<" in out, out[:200])
ok("ונספרו תגובות", ">8<" in out, out[:200])
ok("והאחוז מוצג", "89%" in out, out[-160:])

# 📍 קטגוריות
out = render_meta(rows, NAMES, "cats")
ok("הקטגוריה השכיחה ראשונה", out.index("מחשבים") < out.index("סלולרי"), out[:200])
ok("מספר הקטגוריות מוצג", "2 קטגוריות" in out, out[-120:])

# 🏠 בשרשורים של מי
out = render_meta(rows, NAMES, "hosts")
ok("המארח המוביל מוצג בשמו", "המארח" in out, out[:200])
ok("שרשורים שלו עצמו נספרים בנפרד", "פתח: 1" in out, out[-160:])
ok("המשתמש עצמו אינו מארח של עצמו ברשימה",
   out.index("המארח") < (out.index("פתח: 1")), out[:80])

# 💥 מה הצית שיחה
out = render_meta(rows, NAMES, "spark")
ok("הפוסט שעורר תגובות מוצג", "3 תגובות" in out, out[:200])
ok("והממוצע מחושב", "0.33" in out, out[-160:])

# 🗣️ למי הוא עונה — **וכיסוי חלקי נאמר במפורש**
out = render_meta(rows, NAMES, "replyto")
ok("היעד המוביל מוצג בשמו", "דוד כהן" in out, out[:200])
ok("והשני אחריו", out.index("דוד כהן") < out.index("שרה"), out[:200])
ok("הכיסוי מוצהר", "8 מתוך 20" in out and "40%" in out, out[-260:])
ok("ונאמר שזה החלון האחרון", "עכשיו" in out, out[-260:])

# בלי תגובות בכלל — מצב ריק מפורש, לא כרטיס ריק
out = render_meta([rich(1)], {"reply_total": 0}, "replyto")
ok("בלי תגובות נאמר במפורש", "אינו תגובה לאדם אחר" in out, out[:160])

# המשתמש עצמו לא נספר כמי שהוא עונה לו
out = render_meta([rich(1, reply_uid=7, to_pid=901)], NAMES, "replyto")
# הודעה מדויקת: ההבדל בין "לא זיהינו" לבין "זיהינו, וכולן היו לעצמו"
ok("תגובה לעצמו אינה נספרת", "לפוסטים שלו עצמו" in out, out[:160])


# ══ ספירת הלייקים חופשית מהעוגייה ════════════════════════════════════════
# נמדד מול הפורום: סכום `upvotes` על 36 פוסטים = 41, ובדיוק 41 נספרו
# ב-36 בקשות הצבעה עם עוגייה. הדוח הציג "—" על מספר שכבר היה בידיים.
out = render_meta([rich(i, likes=2, votes_ok=False) for i in range(1, 6)],
                  {}, "likes")
ok("לייקים מוצגים גם בלי שמות מצביעים", "10" in out, out)
ok("ולא מוצג מקף", out.strip() != "—", out)

src2 = io.open(CZ.__file__, encoding="utf-8").read()
ok("הספירה נלקחת מהפוסט עצמו", 'int(post.get("upvotes") or 0)' in src2)
ok("בלי עוגייה לא נשלחת בקשת הצבעה", "if not cookie:" in src2)
ok("ופוסט בלי לייקים לא נשאל בכלל", "if not give_up and likes:" in src2)


# ══ המוניטין ומספר השרשורים מדף האודות, לא מהנסרק ════════════════════════
# בנימין: "חישבת פוסטים מהמקור הגלוי בפרופיל וכללת מחוקים וזה טוב. אבל
# בלייקים (מוניטין) כללת רק גלויים ולא לקחת את המספר המלא שגלוי בדף האודות."
# שני מונים סמוכים חייבים לדבר באותה מטבע — אחרת אחד מהם נראה כמו טעות.
ok("מוניטין ומספר שרשורים נקראים מהפרופיל",
   CZ._official_counts({"reputation": 2115, "topiccount": 41, "postcount": 1988})
   == {"reputation": 2115, "topiccount": 41})
ok("ופרופיל שלא חושף אותם מחזיר אפס",
   CZ._official_counts({}) == {"reputation": 0, "topiccount": 0})
ok("וערך פגום אינו מפיל את הדוח",
   CZ._official_counts({"reputation": "לא מספר", "topiccount": None})
   == {"reputation": 0, "topiccount": 0})
ok("גם None עצמו נסבל", CZ._official_counts(None)["reputation"] == 0)

five = [post(i, BASE_TS + i * DAY, 10, 3, 100 + i, "נושא") for i in range(1, 6)]

k = kpi(five, {"postcount": 1988, "reputation": 2115})
ok("ה-KPI מציג את המוניטין הרשמי", k["likes"] == "2,115", k)

# בלי מוניטין בפרופיל נשארת ההתנהגות הישנה — הסכום מהפוסטים שנסרקו
k0 = kpi(five, {"postcount": 1988})
ok("ובלי מוניטין נופלים ללייקים שנספרו", k0["likes"] == "15", k0)

# 🎭 שתי השורות מאותו מקור. postcount סופר גם את הפוסט הפותח, ולכן
# התגובות הרשמיות הן ההפרש — והסכום חייב לצאת בדיוק postcount.
mixed = [rich(1, is_main=True, topic_uid=7)] + [rich(i, topic_uid=7) for i in range(2, 6)]
out = render_meta(mixed, {"postcount": 1988, "topiccount": 41}, "role")
ok("פתח שרשורים לפי דף האודות", ">41<" in out, out[:300])
ok("והתגובות הן ההפרש", ">1,947<" in out, out[:300])
ok("ושתי השורות מציינות כמה נסרק", out.count("לפי דף הפרופיל") == 2, out[:300])
ok("והאחוז מחושב מהמספרים הרשמיים", "98%" in out, out[-200:])

# פרופיל שאינו חושף topiccount ממשיך בדיוק כמו קודם
out0 = render_meta(mixed, {"postcount": 1988}, "role")
ok("בלי topiccount נספר מה שנסרק", ">1<" in out0 and ">4<" in out0, out0[:300])
ok("ואז לא נטען שזה מדף הפרופיל", "לפי דף הפרופיל" not in out0, out0[:300])

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("CHAZONISHNIK INSIGHT TESTS PASSED")
