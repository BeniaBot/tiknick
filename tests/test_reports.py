# -*- coding: utf-8 -*-
"""
0.9.7 — חזונישניק ושטינקניק: דוחות קודמים, שם הניק בשם הקובץ, נתוני הפרופיל
שכבר הגיעו, קצב ורצפים, שנויים במחלוקת, והמתנה שלא הייתה צריכה להיות.

בנימין: "ושיוכלו לפתוח את הדוחות האחרונים — גם יותר מאשר הדוח האחרון. ושבשם
הקובץ (גם בשטינקניק) יהיה שם הניק". ו"יש הרבה נתונים מעניינים שאפשר להביא
... וכרגע מושמטים וחבל".

תיקייה זמנית בלבד, אפס בקשות רשת, ואפס נגיעה במאגר האמיתי.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import report_store as RS      # noqa: E402
import chazonishnik as CZ      # noqa: E402
import i18n                    # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


DOC = "<!DOCTYPE html>\n<html><head><title>x</title></head><body>דוח</body></html>"

# ══ 1. שמירה ושם הקובץ ════════════════════════════════════════════════════
d = tempfile.mkdtemp()
n1 = RS.save(d, "chz", "צול גאה", "https://mitmachim.top/", DOC, {"posts": 1791, "partial": True})
ok("🚨 שם הקובץ כולל את הכלי, הניק והפורום", n1.startswith("חזונישניק - צול גאה - mitmachim.top - "), n1)
ok("   ותאריך ושעה שאדם קורא", re.search(r" - \d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.html$", n1), n1)
n2 = RS.save(d, "stink", "צול גאה", "https://mitmachim.top", DOC)
ok("שטינקניק מקבל שם משלו", n2.startswith("שטינקניק - צול גאה - "), n2)
n3 = RS.save(d, "chz", "צול גאה", "https://mitmachim.top", DOC)
ok("שני דוחות באותה דקה לא דורסים זה את זה", n3 != n1 and n3.endswith("(2).html"), n3)
bad = RS.save(d, "chz", 'a<b>:c"d/e\\f|g?h*i. ', "https://x.org", DOC)
ok("תווים שאסורים בשם קובץ ב-Windows יורדים", not re.search(r'[<>:"/\\|?*]', bad[:-5].split(" - ")[1]), bad)
ok("   ואין נקודה או רווח בסוף הניק", not bad.split(" - ")[1].endswith((".", " ")), bad)
ok("ניק ריק מקבל שם, לא מחרוזת ריקה", " - ללא שם - " in RS.save(d, "chz", "", "https://x.org", DOC))

raw = io.open(os.path.join(d, "reports", n1), encoding="utf-8").read()
ok("🚨 ה-DOCTYPE נשאר ראשון (הערה לפניו = מצב quirks)", raw.startswith("<!DOCTYPE html>"), raw[:60])
ok("   והמטא-דאטה מיד אחריו, בתוך הערה", raw.split("\n")[1].startswith("<!--tiknick-report {"))
tricky = RS.save(d, "chz", "a--b-->c", "https://x.org", DOC)
rawt = io.open(os.path.join(d, "reports", tricky), encoding="utf-8").read()
ok("🚨 '--' בשם הניק אינו סוגר את ההערה", rawt.count("-->") == 1, rawt[:200])

# ══ 2. רשימה ═══════════════════════════════════════════════════════════════
lst = RS.list_reports(d)
by = {r["name"]: r for r in lst}
ok("כל הדוחות ברשימה", len(lst) == 6, len(lst))
ok("המטא-דאטה נקראת חזרה", by[n1]["tool"] == "chz" and by[n1]["nick"] == "צול גאה"
   and by[n1]["forum"] == "mitmachim.top" and by[n1]["posts"] == 1791 and by[n1]["partial"] is True,
   by[n1])
ok("   גם ניק עם מקפים", by[tricky]["nick"] == "a--b-->c", by[tricky]["nick"])
ok("החדש ראשון", lst[0]["created"] >= lst[-1]["created"])
io.open(os.path.join(d, "reports", "ידני.html"), "w", encoding="utf-8").write("<html>x</html>")
ok("קובץ בלי מטא-דאטה עדיין מופיע (לא נעלם)", any(r["name"] == "ידני.html" for r in RS.list_reports(d)))
io.open(os.path.join(d, "reports", "notes.txt"), "w").write("x")
ok("רק HTML נספר", not any(r["name"] == "notes.txt" for r in RS.list_reports(d)))

# ══ 3. 🚨 הגשר מעביר שם — ולא נתיב ═══════════════════════════════════════════
outside = os.path.join(d, "secret.html")
io.open(outside, "w").write("<html>סוד</html>")
for nm in ("../secret.html", "..\\secret.html", outside, "reports/" + n1, "/" + n1,
           "C:\\Windows\\win.ini", "notes.txt", "", None, 5, ".hidden.html", "nope.html"):
    ok("נדחה: %r" % (nm,), RS.read(d, nm) is None and RS.delete(d, nm) is False)
ok("והקובץ שמחוץ לתיקייה לא נמחק", os.path.exists(outside))
ok("שם תקין נקרא", "דוח" in RS.read(d, n1))
ok("ומחיקה של שם תקין עובדת", RS.delete(d, n3) and not os.path.exists(os.path.join(d, "reports", n3)))
ok("   ונעלמת מהרשימה", not any(r["name"] == n3 for r in RS.list_reports(d)))
ok("🚨 מחיקה הפיכה — '↩ בטל' מחזיר את הדוח", RS.undelete(d, n3) and RS.read(d, n3) is not None)
ok("   ביטול על שם שלא נמחק — לא עושה כלום", RS.undelete(d, n3) is False)
ok("   ביטול על נתיב — מסורב", RS.undelete(d, "../secret.html") is False)
RS.delete(d, n3)
tp = os.path.join(d, "reports", "_deleted", n3)
os.utime(tp, (time.time() - 7200, time.time() - 7200))
RS.prune(d)
ok("   ואחרי שעה הוא נמחק באמת", not os.path.exists(tp))

# ══ 4. תקרה ═══════════════════════════════════════════════════════════════
d2 = tempfile.mkdtemp()
for i in range(8):
    nm = RS.save(d2, "chz", "u%d" % i, "https://x.org", DOC)
    p = os.path.join(d2, "reports", nm)
    os.utime(p, (time.time() - 1000 + i, time.time() - 1000 + i))
removed = RS.prune(d2, keep=5)
left = sorted(r["nick"] for r in RS.list_reports(d2))
ok("נשמרים רק האחרונים", removed == 3 and left == ["u3", "u4", "u5", "u6", "u7"], (removed, left))
big = "<!DOCTYPE html>\n" + "x" * 4000
for i in range(4):
    nm = RS.save(d2, "chz", "big%d" % i, "https://x.org", big)
    os.utime(os.path.join(d2, "reports", nm), (time.time() + i, time.time() + i))
RS.prune(d2, keep=100, max_bytes=9000)
ok("ותקרת נפח — החדשים נשארים", sorted(r["nick"] for r in RS.list_reports(d2)) == ["big2", "big3"],
   [r["nick"] for r in RS.list_reports(d2)])
part = os.path.join(d2, "reports", "x.html.part")
io.open(part, "w").write("x")
os.utime(part, (time.time() - 7200, time.time() - 7200))
RS.prune(d2)
ok("שארית כתיבה ישנה נמחקת", not os.path.exists(part))

# ══ 5. הדוחות הישנים שליד המאגר ═════════════════════════════════════════════
d3 = tempfile.mkdtemp()
io.open(os.path.join(d3, "chazonishnik_צולגאה.html"), "w", encoding="utf-8").write(DOC)
io.open(os.path.join(d3, "stinknik_moshe.html"), "w", encoding="utf-8").write(DOC)
io.open(os.path.join(d3, "tiknick.db"), "w").write("x")
moved = RS.adopt_legacy(d3)
names = sorted(r["nick"] for r in RS.list_reports(d3))
ok("דוחות מגרסאות קודמות עוברים לרשימה", moved == 2 and names == ["moshe", "צולגאה"], (moved, names))
ok("   ונעלמים מליד המאגר", not os.path.exists(os.path.join(d3, "chazonishnik_צולגאה.html")))
ok("   והמאגר עצמו לא נגעו בו", os.path.exists(os.path.join(d3, "tiknick.db")))
ok("   ופעם שנייה לא עושה כלום", RS.adopt_legacy(d3) == 0)

# ══ 6. הגשר ═══════════════════════════════════════════════════════════════
import database as db   # noqa: E402
import main             # noqa: E402
db.close_pool()
db.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
db.init_db()
api = main.API()
dd = os.path.dirname(db.DB_PATH)
nm = RS.save(dd, "chz", "דוד", "https://bina.top", DOC)
ok("list_reports דרך הגשר", [r["name"] for r in api.list_reports()] == [nm])
r = api.open_report(nm)
ok("open_report מחזיר את הדוח", r["ok"] and "דוח" in r["html"])
ok("open_report על נתיב — מסורב", not api.open_report("../t.db")["ok"])
content, fname = api._report_content(None, nm, {})
ok("🚨 'שמור כ-HTML' מציע את שם הדוח — עם הניק", fname == nm and "דוד" in fname, fname)
content, fname = api._report_content("<html/>", None, {"report": nm})
ok("   גם כשהממשק לא מסר שם — לפי הדוח האחרון במצב", fname == nm)
ok("delete_report", api.delete_report(nm)["ok"] and api.list_reports() == [])
ok("restore_report", api.restore_report(nm)["ok"] and len(api.list_reports()) == 1)
api.delete_report(nm)
src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
ok("🚨 chazonishnik_<שם>.html לא נכתב יותר ליד המאגר", "chazonishnik_{safe}.html" not in src
   and "chazonishnik_compare_" not in src)
ok("שלושת המסלולים שומרים במאגר הדוחות",
   all(('report_store.save(\n                        os.path.dirname(db.DB_PATH), "%s"' % t) in src
       for t in ("chz", "cmp", "stink")))
ok("המצב מתאפס בכל הרצה", src.count('"report": ""') >= 2)

# ══ 7. נתוני הפרופיל שכבר הגיעו ════════════════════════════════════════════
U = {"uid": 27057, "username": "cfopuser", "displayname": "cfo&quot;user",
     "joindate": 1748898589757, "lastonline": 1795558381592, "profileviews": 6491,
     "reputation": 2802, "postcount": 3648, "topiccount": 32, "followerCount": 27,
     "followingCount": 4, "banned": False, "muted": False,
     "groupTitleArray": ["מנהלי תוכן", "registered-users"],
     "groups": [{"name": "מנהלי תוכן", "displayName": "מנהלי תוכן"},
                {"name": "secret", "hidden": 1}, {"name": "מתנדבים"}],
     "isGlobalModerator": True, "counts": {"posts": 3382, "topics": 28},
     "location": "x@y.com", "website": "http://x", "birthday": "1990-01-01",
     "aboutme": "אני", "signature": "חתימה", "downvote:disabled": False}
P = CZ._profile_meta(U)
ok("שם תצוגה מפוענח", P["display"] == 'cfo"user', P["display"])
ok("הצטרף / נראה / צפיות / עוקבים", P["joindate"] == 1748898589757 and P["lastonline"] == 1795558381592
   and P["profileviews"] == 6491 and P["followers"] == 27 and P["following"] == 4)
ok("קבוצות בלי כפילות, בלי נסתרות ובלי ברירת המחדל", P["groups"] == ["מנהלי תוכן", "מתנדבים"], P["groups"])
ok("תפקיד — כקוד, והטקסט נבנה בדוח", P["role"] == "gmod", P["role"])
ok("🚨 פוסטים מחוקים או מוסתרים = הרשמי פחות הגלויים", P["hidden_posts"] == 266, P["hidden_posts"])
ok("🚨 פרטים אישיים אינם נכנסים לדוח", not set(P) & {"location", "website", "birthday", "aboutme",
                                                    "signature", "email"})
ok("פרופיל ריק לא מפיל", CZ._profile_meta(None)["display"] == "" and CZ._profile_meta({})["hidden_posts"] == 0)
ok("ערך זבל במונה לא מפיל", CZ._profile_meta({"joindate": "x", "counts": {"posts": "y"}})["joindate"] == 0)

# ══ 8. המתנה רק לפני בקשה ═══════════════════════════════════════════════════
slept = []
real_sleep = CZ.time.sleep
CZ.time.sleep = lambda s: slept.append(s)
try:
    p = {"pid": 1, "content": "<p>שלום</p>", "upvotes": 3, "downvotes": 1, "timestamp": 1735689600000,
         "topic": {"tid": 5, "title": "x", "uid": 2, "postcount": 4}, "category": {"name": "כללי"}}
    for _ in range(50):
        CZ._fetch_detail("https://x.org", "", dict(p), "me")
    ok("🚨 בלי עוגייה אין בקשה — ולכן אין המתנה", slept == [], len(slept))
    p0 = dict(p, upvotes=0)
    calls = []
    real_get = CZ._get_json
    CZ._get_json = lambda *a, **k: calls.append(a) or {"response": {"upvoters": []}}
    try:
        CZ._fetch_detail("https://x.org", "express.sid=s%3Ax", dict(p0), "me")
        ok("   ופוסט בלי לייקים עם עוגייה — גם לא", slept == [] and calls == [])
        CZ._reset_vote_stats()
        CZ._fetch_detail("https://x.org", "express.sid=s%3Ax", dict(p), "me")
        ok("   ובקשה אמיתית כן ממתינה, פעם אחת", slept == [CZ.DETAIL_DELAY] and len(calls) == 1,
           (slept, len(calls)))
    finally:
        CZ._get_json = real_get
finally:
    CZ.time.sleep = real_sleep

# ══ 9. הדוח עצמו — ראש, קצב, מחלוקת ═══════════════════════════════════════════
DAY = 86400000
BASE = 1735689600000      # 2025-01-01, קבוע


def post(i, ts, likes=1, down=0, title="שרשור"):
    return {"pid": i, "title": title, "tid": i, "ts": ts, "date": "2025-01-0%d" % (i % 9 + 1),
            "hour": 10, "dow": 2, "day": "רביעי", "month": "2025-01", "likes": likes,
            "down": down, "voters": [], "votes_ok": False, "mentions": [], "words": 40,
            "is_main": False, "replies": 0, "to_pid": None, "reply_uid": None,
            "topic_uid": 55, "topic_posts": 10, "cat": "כללי"}


def render(html):
    body = html[html.index("const data="):html.rindex("</script>")]
    js = """
const boxes = {};
const mk = () => ({ _h: '', set innerHTML(v){ this._h = v; }, get innerHTML(){ return this._h; },
                    innerText: '', textContent: '', title: '', style: {} });
for (const id of ['hdr-name','hdr-sub','hdr-chips','list-pace','list-contro']) boxes[id] = mk();
globalThis.document = { getElementById: id => boxes[id] || mk() };
globalThis.Chart = function(){ return {}; };
Chart.defaults = {};
%s
console.log(JSON.stringify({ name: boxes['hdr-name'].textContent, sub: boxes['hdr-sub'].textContent,
  chips: boxes['hdr-chips'].innerHTML, pace: boxes['list-pace'].innerHTML,
  contro: boxes['list-contro'].innerHTML }));
""" % body
    p = os.path.join(tempfile.mkdtemp(), "r.js")
    io.open(p, "w", encoding="utf-8").write(js)
    r = subprocess.run(["node", p], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout.strip())


posts = [post(1, BASE + 10 * 3600000, 5, 0), post(2, BASE + DAY + 10 * 3600000, 2, 7, "<b>ויכוח</b>"),
         post(3, BASE + 2 * DAY + 3600000, 0, 3), post(4, BASE + 2 * DAY + 2 * 3600000, 9, 0),
         post(5, BASE + 10 * DAY + 10 * 3600000, 1, 0)]
meta = {"profile": dict(P, banned=True, banned_until=0, muted=True, muted_until=BASE + 30 * DAY)}
out = render(CZ._build_html("cfopuser", "https://mitmachim.top", 7, posts, meta))
ok("🚨 הכותרת היא שם התצוגה ולא ה-slug", out["name"] == 'cfo"user', out["name"])
ok("שורת המשנה: הפורום ותאריך הסריקה", out["sub"].lstrip("\u200f").startswith("mitmachim.top · נסרק ב-"), out["sub"])
for frag, label in (("מורחק מהפורום", "הרחקה"), ("מושתק", "השתקה"), ("מפקח כללי", "תפקיד"),
                    ("מנהלי תוכן", "קבוצה"), ("הצטרף ב-", "הצטרפות"), ("נראה לאחרונה ב-", "נראה לאחרונה"),
                    ("6,491 צפיות בפרופיל", "צפיות"), ("27 עוקבים", "עוקבים"),
                    ("266 פוסטים מחוקים או מוסתרים", "מוסתרים")):
    ok("ראש הדוח: %s" % label, frag in out["chips"], out["chips"][:300])
ok("הרחקה בלי תאריך סיום — בלי 'עד'", "מורחק מהפורום</span>" in out["chips"], out["chips"][:200])
ok("השתקה עם תאריך — עם 'עד'", re.search(r"מושתק · עד [^<]+</span>", out["chips"]), out["chips"][:300])
evil = render(CZ._build_html("x", "https://f.org", 7, posts,
                             {"profile": {"display": "<img src=x onerror=1>",
                                          "groups": ["<script>alert(1)</script>"], "role": "<b>x</b>"}}))
ok("🚨 שם ותגיות מהפורום עוברים בריחה", "<script>" not in evil["chips"] and "<b>" not in evil["chips"]
   and "&lt;script&gt;" in evil["chips"], evil["chips"][:200])
ok("   שם התצוגה נכנס כטקסט (textContent)", evil["name"] == "<img src=x onerror=1>")

ok("קצב: ימים שבהם כתב", "ימים שבהם כתב</span><span class=\"badge\">4<" in out["pace"], out["pace"][:300])
ok("קצב: הרצף הארוך ביותר — 3 ימים", ">3 ימים<" in out["pace"], out["pace"])
ok("קצב: היום העמוס ביותר — 2 פוסטים", ">2 פוסטים<" in out["pace"], out["pace"])
ok("קצב: ממוצע ביום — 1.3", ">1.3<" in out["pace"], out["pace"])
ok("מחלוקת: הכי הרבה דיסלייקים ראשון", out["contro"].index("👎 7") < out["contro"].index("👎 3"), out["contro"][:300])
ok("מחלוקת: פוסט בלי דיסלייק לא ברשימה", "👎 0" not in out["contro"])
ok("🚨 מחלוקת: כותרת מהפורום עוברת בריחה", "<b>ויכוח</b>" not in out["contro"] and "&lt;b&gt;" in out["contro"])
ok("מחלוקת: סיכום", "10 דיסלייקים" in out["contro"] and "2 פוסטים שקיבלו לפחות אחד" in out["contro"],
   out["contro"][-200:])
none = render(CZ._build_html("x", "https://f.org", 7, [post(1, BASE, 3, 0)], {"profile": {}}))
ok("בלי דיסלייקים — אומר זאת", "אף פוסט שנסרק לא קיבל דיסלייק" in none["contro"])
off = render(CZ._build_html("x", "https://f.org", 7, [post(1, BASE, 3, 0)], {"profile": {"downvote_disabled": True}}))
ok("ובפורום שכיבה דיסלייקים — לא טוען שאין", "כבויים" in off["contro"])
ok("בלי פרופיל — בלי תגיות, בלי שגיאה", none["chips"] == "" and none["name"] == "")

i18n.set_lang("en")
try:
    en = render(CZ._build_html("x", "https://f.org", 7, posts, meta))
    he_left = re.findall(r"[֐-׿]+", en["chips"] + en["pace"] + en["contro"] + en["sub"])
    # שמות קבוצות ותפקיד מהפורום הם נתונים — הם נשארים כפי שהם
    he_left = [w for w in he_left if w not in ("מנהלי", "תוכן", "מתנדבים", "ויכוח", "שרשור")]
    ok("🚨 באנגלית: ראש הדוח והכרטיסים בלי עברית", not he_left, he_left[:6])
    ok("   ותפקיד מתורגם", "Global moderator" in en["chips"], en["chips"][:200])
finally:
    i18n.set_lang("he")

# ══ 10. 🚨 עמוד ריק באמצע ההיסטוריה אינו סוף ההיסטוריה ═════════════════════════
# NodeBB חותך את העמוד מכל הפוסטים ורק אחר כך מסנן לפי הרשאות — פוסטים
# בקטגוריה חסומה משאירים עמוד ריק באמצע (נמדד במתמחים, 15.11.2026).
import stinknik as SK   # noqa: E402


def fake_pages(pages, postcount):
    seen = []

    def get(url, *a, **k):
        if "/posts?page=" in url:
            p = int(url.rsplit("=", 1)[1])
            seen.append(p)
            n = pages[p - 1] if p <= len(pages) else 0
            base = sum(pages[:p - 1])
            return {"posts": [{"pid": base + i + 1, "upvotes": 0, "downvotes": 1, "votes": -1,
                               "topic": {"title": "t"}, "timestamp": BASE} for i in range(n)]}
        return {"uid": 1, "userslug": "u", "username": "u", "postcount": postcount}
    return get, seen


real_cz_get, real_sk_get = CZ._get_json, SK._get_json
CZ.time.sleep = lambda s: None
SK.time.sleep = lambda s: None
try:
    # 20, ריק, 20, 7 — ו-postcount 67 (+20 חסומים)
    CZ._get_json, seen = fake_pages([20, 0, 20, 7], 67)
    st = {}
    got = CZ._scan_posts("https://f.org", "u", None, stats=st, expected_posts=67)
    ok("🚨 חזונישניק: ממשיך אחרי עמוד ריק באמצע", len(got) == 47, (len(got), seen))
    ok("   ועוצר בסוף — לא סורק לנצח", max(seen) <= 5, seen)
    ok("   וסופר את העמודים הריקים", st.get("empty_pages") == 1, st)
    CZ._get_json, seen = fake_pages([20, 0, 20], 0)
    got = CZ._scan_posts("https://f.org", "u", None, stats={}, expected_posts=0)
    ok("   בלי מונה רשמי — כמו קודם, עוצר בריק הראשון", len(got) == 20 and seen == [1, 2], seen)
    CZ._get_json, seen = fake_pages([50, 50, 0, 0, 0, 0], 100)
    got = CZ._scan_posts("https://f.org", "u", None, stats={}, expected_posts=100)
    ok("   פורום עם 50 בעמוד — לא מבזבז בקשות על עמודים ריקים בסוף", len(got) == 100 and max(seen) == 3,
       seen)

    SK._get_json, seen = fake_pages([20, 0, 0, 20, 3], 83)
    r = SK.analyze_dislikes("u", base_url="https://f.org")
    ok("🚨 שטינקניק: ממשיך אחרי עמודים ריקים באמצע", r["ok"] and r["checked"] == 43, (r.get("checked"), seen))
    ok("   ועוצר בסוף", max(seen) <= 6, seen)
finally:
    CZ._get_json, SK._get_json = real_cz_get, real_sk_get
    CZ.time.sleep = real_sleep
    SK.time.sleep = real_sleep

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("REPORT TESTS PASSED")
