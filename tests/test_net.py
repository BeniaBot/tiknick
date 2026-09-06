# -*- coding: utf-8 -*-
"""
0.8.21: יציאה אחת לאינטרנט (net.py), ותיקון הטקסט שהגיע מקודד מהפורום.

הבאג שהוליד את החצי השני: NodeBB מחזיר טקסט **מקודד ל-HTML**, והסורק שמר
אותו כמו שהוא. ניק בשם ע"ה נשמר כ-ע&quot;ה — נראה שבור בטבלה, ובעיקר
"פתח בדפדפן" בנה את הקישור מהשם המקודד ולא מצא את המשתמש בפורום.
"""
import io
import os
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import net            # noqa: E402
import scraper        # noqa: E402
import database as db  # noqa: E402

fails = []


def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)


def _proxies_of(opener):
    for h in opener.handlers:
        if isinstance(h, urllib.request.ProxyHandler):
            return dict(h.proxies)
    return None


# ══ נרמול כתובת פרוקסי ═══════════════════════════════════════════════════
ok("host:port מקבל http", net.normalize_url("10.0.0.5:8080") == "http://10.0.0.5:8080")
ok("בלי פורט — ברירת מחדל 8080", net.normalize_url("http://p.local") == "http://p.local:8080")
# אל הפרוקסי עצמו פונים תמיד ב-HTTP: urllib שולח CONNECT על הסוקט הגולמי
# ורק אחר כך עוטף ב-TLS. "https://" בכתובת הפרוקסי הבטיח הצפנה שלא קיימת.
ok("https מנורמל ל-http", net.normalize_url("https://p.local:3128") == "http://p.local:3128")
ok("https עם פרטי התחברות מנורמל גם הוא",
   net.normalize_url("https://u:p@h:3128") == "http://u:p@h:3128")
ok("ה-opener מצביע על אותה כתובת http לשני הפרוטוקולים",
   _proxies_of(net.build_opener("manual", "https://p.local:3128")) ==
   {"http": "http://p.local:3128", "https": "http://p.local:3128"})
ok("שם משתמש וסיסמה נשמרים",
   net.normalize_url("http://u:p@h:3128") == "http://u:p@h:3128")
ok("IPv6 בסוגריים", net.normalize_url("http://[::1]:8080") == "http://[::1]:8080")

for bad, why in (("", "ריק"), ("   ", "רווחים"), ("socks5://h:1", "SOCKS"),
                 ("http://", "בלי מארח"), ("http://h:99999", "פורט מחוץ לטווח"),
                 ("http://h:8080/path", "עם נתיב"), ("http://a b:1", "רווח בפנים")):
    try:
        net.normalize_url(bad)
        ok("נדחה: %s" % why, False, "התקבל")
    except net.ProxyError:
        ok("נדחה: %s" % why, True)

ok("הסיסמה מוסתרת", net.mask_url("http://u:s3cret@h:1") == "http://u:***@h:1")
ok("בלי סיסמה — ללא שינוי", net.mask_url("http://h:1") == "http://h:1")


def proxies(opener):
    return [h.proxies for h in (opener.handlers if opener else [])
            if hasattr(h, "proxies")]


ok("system לא בונה opener", net.build_opener("system") is None)
# ProxyHandler ריק אינו נכנס בכלל לרשימת ה-handlers (אין לו proxy פעיל אחד),
# ובמקביל הוא *מוציא* את ProxyHandler ברירת המחדל — וזו בדיוק המשמעות של
# "ישיר": opener בלי שום טיפול בפרוקסי.
import urllib.request as _ur  # noqa: E402
ok("off = בלי שום ProxyHandler",
   not any(isinstance(h, _ur.ProxyHandler) for h in net.build_opener("off").handlers))
ok("manual מגדיר http ו-https",
   proxies(net.build_opener("manual", "1.2.3.4:8080")) ==
   [{"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}])

# הגדרה פסולה לא משנה את המצב הפעיל — אחרת שמירה שגויה מנתקת את התוכנה
net.apply("system")
before = net.current()
try:
    net.apply("manual", "socks5://x")
    ok("הגדרה פסולה נדחית", False, "התקבלה")
except net.ProxyError:
    ok("הגדרה פסולה נדחית", True)
ok("המצב הפעיל לא השתנה", net.current() == before, str(net.current()))

net.apply("manual", "1.2.3.4:8080")
ok("apply שומר את הכתובת המנורמלת", net.current()["url"] == "http://1.2.3.4:8080")
ok("התיאור מסתיר סיסמה",
   "***" in net.describe("manual", "http://u:pw@h:1"), net.describe("manual", "http://u:pw@h:1"))

# הגדרה שמורה פגומה לא משאירה את התוכנה בלי רשת
saved = {"proxy_mode": "manual", "proxy_url": "socks5://nope"}
r = net.apply_from_settings(lambda k, d="": saved.get(k, d))
ok("הגדרה שמורה פגומה נופלת ל-system", r["ok"] is False and net.current()["mode"] == "system",
   str(r))
r = net.apply_from_settings(lambda k, d="": {"proxy_mode": "off"}.get(k, d))
ok("הגדרה שמורה תקינה נטענת", r["ok"] and net.current()["mode"] == "off")

# כל בקשה עוברת דרך ה-opener שנבחר
net.apply("manual", "1.2.3.4:8080")


class _FakeOpener:
    def open(self, url, data=None, timeout=None):
        return "through-opener"


net._state["opener"] = _FakeOpener()
ok("urlopen משתמש ב-opener", net.urlopen("http://example.invalid/") == "through-opener")
net.apply("system")
ok("system חוזר ל-urlopen הרגיל", net._state["opener"] is None)

ok("בדיקה בלי יעד מחזירה שגיאה ולא קורסת",
   net.test_connection("system", "", target="")["ok"] is False)

# ══ טקסט מקודד מהפורום ═══════════════════════════════════════════════════
ok("_txt מפענח ישויות", scraper._txt("ע&quot;ה דכו&quot;ע") == 'ע"ה דכו"ע')
ok("_txt לא נוגע בטקסט רגיל", scraper._txt("בנימין") == "בנימין")
ok("_txt מטפל ב-None", scraper._txt(None) == "")
m = scraper._map_user({"fullname": "ר&#39; משה", "groups": "מנהלים &amp; עורכים",
                       "location": "בני&quot;ב"})
ok("full_name מפוענח", m["full_name"] == "ר' משה", m["full_name"])
ok("groups מפוענח", m["groups"] == "מנהלים & עורכים", m["groups"])
ok("extra_info מפוענח", 'בני"ב' in m["extra_info"], m["extra_info"])

# ══ תיקון מה שכבר נשמר ═══════════════════════════════════════════════════
tmp = tempfile.mkdtemp(prefix="tiknick_net_")
db.close_pool()
db.DB_PATH = os.path.join(tmp, "enc.db")
db.init_db()
db.add_forum("בינה", "#111", "https://a.example")
NOTE = 'הערה שהמשתמש כתב עם &quot; בכוונה'
nid = db.create_nick({"forum": "בינה", "username": "ע&quot;ה דכו&quot;ע",
                      "full_name": "ר&#39; משה", "notes": NOTE})
db.create_nick({"forum": "בינה", "username": "רגיל"})

c = db.count_encoded_values()
ok("הספירה מוצאת את המקודדים", c["nicks"] == 1 and c["usernames"] == 1, str(c))
r = db.fix_encoded_values()
ok("התיקון דיווח על שינוי", r["nicks"] == 1, str(r))
ok("אחרי התיקון לא נשאר כלום", db.count_encoded_values()["nicks"] == 0)

row = [x for x in db.get_all_nicks("")["rows"] if x["id"] == nid][0]
ok("שם המשתמש פוענח", row["username"] == 'ע"ה דכו"ע', row["username"])
ok("שם מלא פוענח", row["full_name"] == "ר' משה", row["full_name"])
# הערה שהמשתמש הקליד בעצמו אינה "טקסט מהפורום" — אסור לגעת בה
ok("הערה של המשתמש לא נגעו בה", row["notes"] == NOTE, row["notes"])
ok("החיפוש מוצא את השם המתוקן", db.get_all_nicks('דכו"ע')["total"] == 1)
ok("הרצה שנייה אינה משנה כלום", db.fix_encoded_values()["nicks"] == 0)

# ══ כל היציאות לאינטרנט עוברות דרך net ═══════════════════════════════════
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for f in ("scraper.py", "chazonishnik.py", "stinknik.py", "main.py"):
    src = io.open(os.path.join(ROOT, f), encoding="utf-8").read()
    ok("%s אינו קורא ל-urlopen ישירות" % f,
       "urllib.request.urlopen(" not in src)
    ok("%s עובר דרך net" % f, "net.urlopen(" in src)

main_src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
ok("ההגדרה נטענת בעלייה", "net.apply_from_settings(db.get_setting)" in main_src)
ok("יש בדיקה שלא מחילה", "def test_net_settings" in main_src)


# ══ מיגרציית הפענוח — הבאג הקריטי של 0.8.21 ═══════════════════════════════
# שוחזר: הסריקה הראשונה אחרי השדרוג יצרה ניק *כפול* לכל שם עם ישות HTML,
# כי ההתאמה היא לפי (פורום, שם משתמש) והשם החדש לא שווה לשמור.
tmp2 = tempfile.mkdtemp(prefix="tiknick_mig_")
db.close_pool()
db.DB_PATH = os.path.join(tmp2, "mig.db")
db.init_db()
db.add_forum("בינה", "#111", "https://a.example")
db.merge_scraped_users("בינה", [('ע&quot;ה דכו&quot;ע',
                                 {"reputation": "5", "full_name": "ר&#39; משה"})], "סריקה")
with db.get_connection() as _c:
    _c.execute("DELETE FROM settings WHERE key='entities_decoded_done'")

db.close_pool()
db.init_db()          # הפעלה מחדש של התוכנה = המיגרציה רצה
rows = db.get_all_nicks("")["rows"]
ok("המיגרציה מפענחת בעלייה", rows[0]["username"] == 'ע"ה דכו"ע', rows[0]["username"])
ok("גם שדות אחרים", rows[0]["full_name"] == "ר' משה", rows[0]["full_name"])
ok("הדגל נשמר", db.get_setting("entities_decoded_done", "") == "1")

before = db.get_all_nicks("")["total"]
db.merge_scraped_users("בינה", [('ע"ה דכו"ע', {"reputation": "6"})], "סריקה")
ok("הסריקה אחרי המיגרציה לא יוצרת כפול",
   db.get_all_nicks("")["total"] == before, str(db.get_all_nicks("")["total"]))

# ══ מיזוג ניקים כפולים ════════════════════════════════════════════════════
tmp3 = tempfile.mkdtemp(prefix="tiknick_dup_")
db.close_pool()
db.DB_PATH = os.path.join(tmp3, "dup.db")
db.init_db()
db.add_forum("בינה", "#111", "")
db.add_forum("נטפרי", "#222", "")
keep_id = db.create_nick({"forum": "בינה", "username": 'ע&quot;ה',
                          "phone": "0501234567", "notes": "עבודה ידנית"})
other = db.create_nick({"forum": "נטפרי", "username": "אחר"})
db.add_identity(keep_id, other)
db.add_contact(keep_id, "phone", "0521111111", "בית", 0)
db.create_nick({"forum": "בינה", "username": 'ע"ה', "reputation": "50"})
with db.get_connection() as _c:
    _c.execute("DELETE FROM settings WHERE key='entities_decoded_done'")
db.close_pool()
db.init_db()

dups = db.find_duplicate_nicks()
ok("כפילות מזוהה", len(dups) == 1 and dups[0]["keep"] == keep_id, str(dups))
res = db.merge_duplicate_nicks()
ok("המיזוג בוצע", res["merged"] == 1, str(res))
kept = [r for r in db.get_all_nicks("")["rows"] if r["id"] == keep_id][0]
ok("העבודה הידנית נשמרה", kept["phone"] == "0501234567" and kept["notes"] == "עבודה ידנית")
ok("מה שנאסף בכפול עבר", str(kept["reputation"]) == "50", repr(kept["reputation"]))
ok("אנשי הקשר נשמרו", any(c["value"] == "0521111111" for c in db.get_contacts(keep_id)))
ok("הזהות נשמרה", any(i["username"] == "אחר" for i in db.get_identities(keep_id)))
ok("הכפול בסל המחזור (הפיך)", len(db.list_trash()) > 0)
ok("לא נשארו כפילויות", db.find_duplicate_nicks() == [])
ok("הרצה שנייה לא עושה כלום", db.merge_duplicate_nicks()["merged"] == 0)
with db.get_connection() as _c:
    ok("שלמות המאגר", _c.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    ok("מפתחות זרים תקינים", _c.execute("PRAGMA foreign_key_check").fetchall() == [])

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("NET TESTS PASSED")
