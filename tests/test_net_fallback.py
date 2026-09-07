# -*- coding: utf-8 -*-
"""
0.9.1 — "פרוקסי רק אם הישיר נכשל", לכל פורום בנפרד.

מי שיושב מאחורי סינון מגלה שחלק מהפורומים נגישים ישירות והפרוקסי רק מאט
אותם, וחלק חסומים ובלעדיו לא ייפתחו כלל. מצב גלובלי אחד לא יכול לענות על
שניהם, ולכן ההחלטה נלמדת ונזכרת **לכל origin בנפרד**.

שלוש הבחנות שהבדיקות כאן שומרות עליהן:
  • כשל **רשת** (חסימה/DNS/timeout) → מנסים דרך הפרוקסי.
  • תשובת **שרת** (401/403/5xx) → הפורום ענה. פרוקסי לא יעזור, ולא מנסים.
  • מה שנלמד פג אחרי 6 שעות, ומתאפס כשמשנים הגדרות.
"""
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import net   # noqa: E402

fails = []


def ok(name, cond, extra=""):
    if cond:
        print("PASS  " + name)
    else:
        print("FAIL  " + name + ("  <- " + str(extra) if extra != "" else ""))
        fails.append(name)


def serve(handler):
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


HITS = {"direct": 0, "proxy": 0}


class _Direct(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        HITS["direct"] += 1
        body = b'{"ok":true,"via":"direct"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Forbidden(_Direct):
    def do_GET(self):
        HITS["direct"] += 1
        self.send_response(403)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


class _Proxy(http.server.BaseHTTPRequestHandler):
    """פרוקסי מדומה: עונה על בקשה עם URL מוחלט."""
    def do_GET(self):
        HITS["proxy"] += 1
        body = b'{"ok":true,"via":"proxy"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


good_srv, good_port = serve(_Direct)
deny_srv, deny_port = serve(_Forbidden)
prox_srv, prox_port = serve(_Proxy)

GOOD = "http://127.0.0.1:%d/api/x" % good_port          # נגיש ישירות
DENY = "http://127.0.0.1:%d/api/x" % deny_port          # עונה 403


def _closed_port():
    """פורט שאיש לא מאזין בו — כשל רשת אמיתי."""
    import socket as _s
    s = _s.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


BLOCKED = "http://127.0.0.1:%d/api/x" % _closed_port()  # כשל חיבור

# מאגר הגדרות מדומה, כדי לבדוק שהזיכרון שורד
STORE = {}
net.set_route_store(lambda k, d="": STORE.get(k, d),
                    lambda k, v: STORE.__setitem__(k, v))
net.forget_routes()
net.apply("fallback", "http://127.0.0.1:%d" % prox_port)

ok("המצב הוחל", net.current()["mode"] == "fallback", net.current())
ok("התיאור אומר מה קורה", "כשנכשל" in net.current()["description"],
   net.current()["description"])


# ══ 1. פורום נגיש ישירות — הפרוקסי לא נוגע בו ═════════════════════════════
HITS.update(direct=0, proxy=0)
with net.urlopen(GOOD, timeout=5) as r:
    body = json.loads(r.read())
ok("נענה ישירות", body["via"] == "direct", body)
ok("הפרוקסי לא הופעל", HITS["proxy"] == 0, HITS)
ok("נזכר כישיר", net.routes_snapshot().get(net._origin_of(GOOD)) == "direct",
   net.routes_snapshot())

# בקשה שנייה — עדיין ישיר, בלי ניסיון מיותר
HITS.update(direct=0, proxy=0)
net.urlopen(GOOD, timeout=5).close()
ok("בקשה חוזרת נשארת ישירה", HITS["direct"] == 1 and HITS["proxy"] == 0, HITS)


# ══ 2. פורום חסום — נופלים לפרוקסי, ונזכרים ═══════════════════════════════
HITS.update(direct=0, proxy=0)
with net.urlopen(BLOCKED, timeout=5) as r:
    body = json.loads(r.read())
ok("נענה דרך הפרוקסי", body["via"] == "proxy", body)
ok("הפרוקסי הופעל פעם אחת", HITS["proxy"] == 1, HITS)
ok("נזכר כפרוקסי",
   net.routes_snapshot().get(net._origin_of(BLOCKED)) == "proxy",
   net.routes_snapshot())

# בקשה שנייה — היישר לפרוקסי, בלי לשלם שוב על הכישלון
HITS.update(direct=0, proxy=0)
t0 = time.perf_counter()
net.urlopen(BLOCKED, timeout=5).close()
dt = time.perf_counter() - t0
ok("בקשה חוזרת הולכת ישר לפרוקסי", HITS["proxy"] == 1, HITS)
ok("ובלי המתנה על ניסיון כושל", dt < 1.0, "%.2fs" % dt)


# ══ 3. 403 הוא תשובה, לא חסימה ════════════════════════════════════════════
HITS.update(direct=0, proxy=0)
try:
    net.urlopen(DENY, timeout=5)
    ok("403 מגיע כשגיאה", False)
except urllib.error.HTTPError as e:
    ok("403 מגיע כשגיאה", e.code == 403, e.code)
ok("ולא נוסה פרוקסי", HITS["proxy"] == 0, HITS)
ok("ונזכר כישיר — הפורום ענה",
   net.routes_snapshot().get(net._origin_of(DENY)) == "direct",
   net.routes_snapshot())


# ══ 4. הזיכרון נשמר, נטען, ופג ════════════════════════════════════════════
ok("נשמר להגדרות", net.SETTING_ROUTES in STORE, list(STORE))
saved = json.loads(STORE[net.SETTING_ROUTES])
ok("ומכיל את שלושת ה-origins", len(saved) == 3, saved)

net._routes.clear()
net._load_routes()
ok("נטען מחדש אחרי הפעלה", len(net.routes_snapshot()) == 3,
   net.routes_snapshot())

# תפוגה
o = net._origin_of(BLOCKED)
net._routes[o] = ("proxy", time.time() - 1)
ok("רשומה שפגה אינה נספרת", net._route_for(o) is None)
ok("והיא נמחקת", o not in net._routes)

# שינוי הגדרות מאפס
net.apply("fallback", "http://127.0.0.1:%d" % prox_port)
net.forget_routes()
ok("forget_routes מנקה", net.routes_snapshot() == {}, net.routes_snapshot())
ok("וגם את מה ששמור", json.loads(STORE[net.SETTING_ROUTES]) == {},
   STORE[net.SETTING_ROUTES])


# ══ 5. שאר המצבים לא השתנו ════════════════════════════════════════════════
HITS.update(direct=0, proxy=0)
net.apply("off")
net.urlopen(GOOD, timeout=5).close()
ok("מצב ישיר עדיין ישיר", HITS["direct"] == 1 and HITS["proxy"] == 0, HITS)

net.apply("system")
ok("system נשאר system", net.current()["mode"] == "system")
ok("fallback ברשימת המצבים", "fallback" in net.MODES, net.MODES)

try:
    net.apply("fallback", "")
    ok("fallback בלי כתובת נדחה", False)
except net.ProxyError:
    ok("fallback בלי כתובת נדחה", True)

net.apply("system")
for s in (good_srv, deny_srv, prox_srv):
    s.shutdown()
    s.server_close()

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("NET FALLBACK TESTS PASSED")
