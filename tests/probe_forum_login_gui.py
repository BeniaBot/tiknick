# -*- coding: utf-8 -*-
"""
בדיקה חיה של "התחבר לפורום" בחלון WebView2 אמיתי — **ידנית, לא ב-run_all**
(היא פותחת חלון על המסך לכמה שניות).

מה רק חלון אמיתי מוכיח, ושום זיוף לא יכול:
  • ש-get_cookies מחזיר גם עוגייה HttpOnly (express.sid של NodeBB היא כזו);
  • ש-evaluate_js עובד על חלון ההתחברות ומבחין בין אורח למחובר;
  • שלדף בחלון ההתחברות **אין** את ה-API של התוכנה.

פורום NodeBB מזויף על 127.0.0.1, מאגר זמני. אפס רשת, אפס נגיעה במאגר האמיתי.
הרצה:  python tests/probe_forum_login_gui.py
"""
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PORT = 7779
SEEN = {}

PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>פורום מזויף</title>
<script>window.app={user:{uid:%(uid)d}};
setTimeout(function(){
  var k = (window.pywebview && window.pywebview.api) ? Object.keys(window.pywebview.api) : [];
  fetch('/probe?where=%(where)s&api=' + encodeURIComponent(JSON.stringify(k)));
}, 800);</script></head>
<body style="font:18px sans-serif;padding:30px" dir="rtl">
<h2>%(title)s</h2>
<form method="post" action="/login"><input name="username" value="probe">
<input type="password" name="password" value="x"><button>התחבר</button></form></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _page(self, uid, where, title, cookie=None):
        body = (PAGE % {"uid": uid, "where": where, "title": title}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        logged = "s%3Alogged" in (self.headers.get("Cookie") or "")
        if u.path == "/probe":
            q = urllib.parse.parse_qs(u.query)
            SEEN[q.get("where", ["?"])[0]] = json.loads(q.get("api", ["[]"])[0])
            self.send_response(204)
            self.end_headers()
            return
        if u.path == "/login":
            # כמו NodeBB: גם אורח מקבל express.sid — HttpOnly
            self._page(0, "login", "דף התחברות (אורח)",
                       None if logged else "express.sid=s%3Aguest; HttpOnly; Path=/")
            return
        self._page(5 if logged else 0, "home", "דף הבית (מחובר)" if logged else "דף הבית (אורח)")

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(302)
        self.send_header("Set-Cookie", "express.sid=s%3Alogged; HttpOnly; Path=/")
        self.send_header("Location", "/")
        self.end_headers()


def main():
    srv = socketserver.TCPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    import database as db
    db.close_pool()
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "probe.db")
    db.init_db()
    url = "http://127.0.0.1:%d" % PORT
    db.add_forum("פורום בדיקה", "#888", url)

    import webview
    import main as M
    api = M.API()
    out = {}

    def drive():
        try:
            time.sleep(1.0)
            out["start"] = api.start_forum_login(url)
            time.sleep(3.0)
            out["guest_saved"] = db.get_cookie_for_url(url)    # אורח — חייב להיות ריק
            login = webview.windows[-1]
            login.evaluate_js("document.forms[0].submit()")    # "המשתמש" לוחץ התחבר
            end = time.time() + 20
            while time.time() < end and M._login_state["running"]:
                time.sleep(0.2)
            time.sleep(0.5)
            out["state"] = dict(M._login_state)
            out["saved"] = db.get_cookie_for_url(url)
            out["windows_left"] = len(webview.windows)
            out["api_seen_in_forum_pages"] = dict(SEEN)
        except Exception as e:      # noqa: BLE001
            out["error"] = repr(e)
        finally:
            for w in list(webview.windows):
                try:
                    w.destroy()
                except Exception:   # noqa: BLE001
                    pass

    webview.create_window("probe", html="<p>probe</p>", js_api=api, width=300, height=200)
    webview.start(drive, private_mode=True)
    srv.shutdown()
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    good = (out.get("start", {}).get("ok") and not out.get("guest_saved")
            and out.get("saved") == "express.sid=s%3Alogged"
            and out.get("state", {}).get("ok")
            and all(v == [] for v in out.get("api_seen_in_forum_pages", {}).values())
            and out.get("api_seen_in_forum_pages"))
    print("PROBE PASSED" if good else "PROBE FAILED")
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
