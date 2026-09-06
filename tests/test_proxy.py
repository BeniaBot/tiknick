# -*- coding: utf-8 -*-
"""הגדרת הפרוקסי: נרמול הכתובת, בניית ה-opener, וההחלה על *כל* הבקשות."""
import io
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import net  # noqa: E402

fails = []


def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)


# ── נרמול הכתובת ─────────────────────────────────────────────────────
ok("host:port מקבל http", net.normalize_url("10.0.0.5:8080") == "http://10.0.0.5:8080")
ok("בלי פורט — ברירת מחדל 8080", net.normalize_url("http://p.local") == "http://p.local:8080")
ok("https נשמר", net.normalize_url("https://p.local:3128") == "https://p.local:3128")
# קידוד חוזר של הסיסמה היה הופך סיסמה עם @ לסיסמה שגויה — urllib מפענח בעצמו
ok("הזדהות נשארת כפי שהודבקה",
   net.normalize_url("http://u:p%40s@h:3128") == "http://u:p%40s@h:3128")
ok("הסיסמה מוסתרת בתצוגה", net.mask_url("http://u:s3cret@h:1") == "http://u:***@h:1")

for bad in ("", "   ", "socks5://h:1", "http://", "http://h:99999",
            "http://h:8080/path", "http://a b:1"):
    try:
        net.normalize_url(bad)
        ok("כתובת פסולה נדחית: %r" % bad, False)
    except net.ProxyError:
        ok("כתובת פסולה נדחית: %r" % bad, True)


# ── ה-opener ─────────────────────────────────────────────────────────
def proxies(opener):
    return [h.proxies for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]


ok("system לא בונה opener (התנהגות ברירת המחדל)", net.build_opener("system") is None)
ok("off מנטרל את פרוקסי המערכת", proxies(net.build_opener("off")) == [])
ok("manual מכוון גם http וגם https",
   proxies(net.build_opener("manual", "1.2.3.4:8080")) ==
   [{"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}])


# ── ההחלה ────────────────────────────────────────────────────────────
class _FakeOpener:
    def open(self, url, data=None, timeout=None):
        return "through-opener"


net.apply("manual", "1.2.3.4:8080")
ok("apply שומר את הכתובת המנורמלת", net.current()["url"] == "http://1.2.3.4:8080")
net._state["opener"] = _FakeOpener()
ok("כל בקשה עוברת דרך ה-opener", net.urlopen("http://example.invalid/") == "through-opener")

net.apply("system")
ok("system מחזיר את urlopen הרגיל", net._state["opener"] is None)

saved = {"proxy_mode": "manual", "proxy_url": "not a url at all"}
r = net.apply_from_settings(lambda k, d="": saved.get(k, d))
ok("הגדרה שמורה פגומה לא משתקת את הרשת",
   not r["ok"] and net.current()["mode"] == "system", str(r))
ok("הגדרה ריקה = system",
   net.apply_from_settings(lambda k, d="": d)["mode"] == "system")

# ── אין מסלול שעוקף את ההגדרה ────────────────────────────────────────
for mod in ("main.py", "scraper.py", "chazonishnik.py", "stinknik.py"):
    src = io.open(os.path.join(ROOT, mod), encoding="utf-8").read()
    ok("%s יוצא לאינטרנט רק דרך net" % mod, "urllib.request.urlopen(" not in src)

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("PROXY TESTS PASSED")
