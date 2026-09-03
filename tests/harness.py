# -*- coding: utf-8 -*-
"""
ארגז חול לממשק: מריץ את web/ האמיתי בדפדפן מול גשר pywebview מזויף.

למה: אין שום בדיקת UI בפרויקט, והתוכנה עצמה היא חלון PyWebView שאי אפשר
לפתוח בלי מסך. כאן מקבלים את אותו app.js ואותו style.css עם נתוני דמה, וכך
אפשר לראות ולנהוג בטבלה — רוחב עמודות, גרירה, RTL, ערכות נושא — בלי מאגר
ובלי רשת.

    python tests/harness.py            # מגיש על http://localhost:5173
    python tests/harness.py --port 8080 --rows 5000

מה שנבדק כאן הוא הרנדור והאינטראקציה בלבד. הלוגיקה של הצד השרתי נבדקת
בחבילות ה-Python, והפונקציות הטהורות של פריסת העמודות ב-tests/test_columns.js.
"""
import argparse
import http.server
import io
import json
import os
import shutil
import socketserver
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORUMS = [("מתמחים טופ", "#f59e0b"), ("בינה", "#0ea5e9"),
          ("ימות המשיח", "#10b981"), ("נטפרי", "#ec4899")]


def make_rows(n):
    rows = []
    for i in range(n):
        forum = FORUMS[i % len(FORUMS)][0]
        rows.append({
            "id": i + 1, "forum": forum, "username": "משתמש_%d" % i,
            "full_name": "שם מלא %d" % i,
            "real_name": "ישראל ישראלי" if i % 3 == 0 else "",
            "groups": "מנהלים" if i % 7 == 0 else "רגיל",
            "reputation": i * 3,
            "phone": "05012345%02d" % (i % 100) if i % 2 else "",
            "email": "u%d@example.com" % i if i % 4 == 0 else "",
            "address": "בני ברק, רחוב עקיבא %d" % i if i % 5 == 0 else "",
            "status": "מורחק" if i % 11 == 0 else "פעיל",
            "last_seen": "2026-08-%02d" % (i % 28 + 1),
            "join_date": "2019-0%d-01" % (i % 9 + 1),
            "post_count": i * 17, "trust_level": (i % 10) + 1,
            "updated_at": "2026-09-01 10:00:00",
            "extra_info": "פרטים נוספים ארוכים לבדיקת חיתוך " * (i % 3),
            "notes": "הערה כלשהי" if i % 6 == 0 else "", "private_notes": "",
            "nick_color": "", "has_avatar": 0,
            "has_identity": 1 if i % 9 == 0 else 0,
            "extra_contacts": 1 if i % 8 == 0 else 0,
            "conflict_count": 0, "conflict_fields": None,
            "has_info": 1 if (i % 2 or i % 6 == 0) else 0,
        })
    return rows


STUB = """// גשר מזויף: כל מתודה שלא הוגדרה כאן מחזירה null, כדי שדף שקורא למשהו
// חדש לא יתפוצץ אלא פשוט יראה ריק.
const FORUMS = %(forums)s;
const ROWS = %(rows)s;
const SETTINGS = %(settings)s;
const API = {
  get_forums: async () => FORUMS,
  get_nicks: async () => ({ rows: ROWS, total: ROWS.length }),
  get_display_settings: async () => SETTINGS,
  set_display_setting: async (k, v) => { SETTINGS[k] = v; window.__saved = { ...SETTINGS }; return { ok: true }; },
  get_app_version: async () => '%(version)s',
  get_avatars: async () => ({}),
  get_known_forums: async () => [],
  get_last_scrapes: async () => ({}),
  get_setting: async () => '',
  consume_update_failure: async () => null,
  check_for_updates: async () => ({ ok: false }),
  touch_recent: async () => ({ ok: true }),
  get_recent_views: async () => [],
  get_identity_map: async () => ({ ok: true, groups: [], total_groups: 0, linked_nicks: 0 }),
};
window.pywebview = { api: new Proxy(API, { get: (t, k) => (k in t ? t[k] : async () => null) }) };
"""


def build(dest, rows):
    for name in os.listdir(os.path.join(ROOT, "web")):
        if name.rsplit(".", 1)[-1] in ("js", "css", "html"):
            shutil.copy(os.path.join(ROOT, "web", name), os.path.join(dest, name))
    version = "dev"
    try:
        src = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
        version = src.split('APP_VERSION = "')[1].split('"')[0]
    except Exception:
        pass
    io.open(os.path.join(dest, "stub.js"), "w", encoding="utf-8").write(STUB % {
        "forums": json.dumps([{"id": i + 1, "name": n, "color": c, "url": ""}
                              for i, (n, c) in enumerate(FORUMS)], ensure_ascii=False),
        "rows": json.dumps(make_rows(rows), ensure_ascii=False),
        "settings": json.dumps({"theme": "dark", "accent": "amber", "view": "table",
                                "density": "normal", "hidden_cols": "", "col_layout": ""}),
        "version": version,
    })
    idx_path = os.path.join(dest, "index.html")
    idx = io.open(idx_path, encoding="utf-8").read()
    if "stub.js" not in idx:
        idx = idx.replace('<script src="app.js"></script>',
                          '<script src="stub.js"></script>\n  <script src="app.js"></script>')
    io.open(idx_path, "w", encoding="utf-8").write(idx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5173)
    ap.add_argument("--rows", type=int, default=220)
    args = ap.parse_args()

    dest = tempfile.mkdtemp(prefix="tiknick_harness_")
    build(dest, args.rows)
    os.chdir(dest)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), Quiet) as httpd:
        print("ארגז החול רץ: http://localhost:%d   (%d שורות)" % (args.port, args.rows))
        print("קבצים: %s" % dest)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nנעצר")
    shutil.rmtree(dest, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
