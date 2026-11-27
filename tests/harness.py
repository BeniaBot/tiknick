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

// ── הטבלה כחלון על רשימת מזהים ─────────────────────────────────────────
// השורות נוצרות לפי דרישה (אותם שדות כמו make_rows בפייתון), כך שאפשר לדמות
// 250 אלף ניקים בלי להטמיע מאה מגה של JSON. ‎window.__rowCalls/__rowsServed
// סופרים כמה שורות הממשק ביקש בפועל — זה המדד שהשינוי בא לשפר.
const N_ROWS = %(n)d;
const _FN = FORUMS.map(f => f.name);
function rowFor(id) {
  const i = id - 1;
  return {
    id, forum: _FN[i %% _FN.length], username: 'משתמש_' + i, full_name: 'שם מלא ' + i,
    real_name: i %% 3 === 0 ? 'ישראל ישראלי' : '', groups: i %% 7 === 0 ? 'מנהלים' : 'רגיל',
    reputation: String(i * 3), phone: i %% 2 ? '05012345' + String(i %% 100).padStart(2, '0') : '',
    email: i %% 4 === 0 ? 'u' + i + '@example.com' : '',
    address: i %% 5 === 0 ? 'בני ברק, רחוב עקיבא ' + i : '',
    status: i %% 11 === 0 ? 'מורחק' : 'פעיל',
    last_seen: '2026-08-' + String(i %% 28 + 1).padStart(2, '0'),
    join_date: '2019-0' + (i %% 9 + 1) + '-01', post_count: String(i * 17),
    trust_level: (i %% 10) + 1, updated_at: '2026-09-01 10:00:00',
    extra_info: 'פרטים נוספים ארוכים לבדיקת חיתוך '.repeat(i %% 3),
    notes: i %% 6 === 0 ? 'הערה כלשהי' : '', private_notes: '', nick_color: '',
    has_avatar: 0, has_identity: i %% 9 === 0 ? 1 : 0, extra_contacts: i %% 8 === 0 ? 1 : 0,
    conflict_count: 0, conflict_fields: null, has_info: (i %% 2 || i %% 6 === 0) ? 1 : 0,
  };
}
window.__rowCalls = 0; window.__rowsServed = 0; window.__idCalls = 0;
const API = {
  get_forums: async () => FORUMS,
  get_nick_ids: async (view) => {
    window.__idCalls++;
    window.__lastView = view;
    let ids = Array.from({ length: N_ROWS }, (_, k) => k + 1);
    const q = ((view && view.search) || '').trim();
    if (q) ids = ids.filter(id => rowFor(id).username.includes(q));
    if (view && view.sort_col === 'username' && view.sort_dir < 0) ids.reverse();
    let wi = 0; for (const id of ids) if (rowFor(id).has_info) wi++;
    return { ids, total: ids.length, with_info: wi, fuzzy: false };
  },
  get_nick_rows: async (ids) => {
    window.__rowCalls++;
    window.__rowsServed += ids.length;
    return ids.map(rowFor);
  },
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
  get_scrapable_forums: async () => FORUMS.map(function (f) {
    return { name: f.name, url: 'https://' + encodeURIComponent(f.name) + '.example',
             platform: 'nodebb' };
  }),
  get_schedule: async () => ({ enabled: false, mode: 'daily', at: '03:00',
    every_hours: 24, forums: [], fail_count: 0, last_error: '', last_run: '',
    min_hours: 12, due: [], notify: '' }),
  set_schedule: async () => ({ ok: true, enabled: true, forums: [] }),
  get_backup_status: async () => ({ enabled: true, last: '', count: 0, bytes: 0,
                                    dir: 'C:/tmp', files: [] }),
  get_db_health: async () => ({ ok: true, quick_check: 'ok', version: '%(version)s',
    install_type: 'portable', size: 1024, wal: 0, counts: {}, fts: true, path: 'C:/tmp/x.db' }),
  get_import_log: async () => [],
  list_reports: async () => (window.__reports || (window.__reports = [
    { name: 'חזונישניק - צול גאה - mitmachim.top - 2026-11-27 10.05.html', tool: 'chz',
      nick: 'צול גאה', forum: 'mitmachim.top', created: '2026-11-27T10:05:00', posts: 1791, partial: true },
    { name: 'שטינקניק - דוד - bina.top - 2026-11-26 21.40.html', tool: 'stink',
      nick: 'דוד', forum: 'bina.top', created: '2026-11-26T21:40:00', posts: 640, partial: false },
    { name: 'השוואה - א מול ב - mitmachim.top - 2026-11-20 08.00.html', tool: 'cmp',
      nick: 'א מול ב', forum: 'mitmachim.top', created: '2026-11-20T08:00:00', posts: null, partial: false },
  ])).slice(),
  open_report: async (n) => ({ ok: true, name: n,
    html: '<!DOCTYPE html><html dir="rtl"><body style="background:#0f172a;color:#fff;font:20px sans-serif;padding:40px">דוח לדוגמה: ' + n + '</body></html>' }),
  delete_report: async (n) => { window.__deleted = (window.__deleted || []).concat([n]);
    window.__reports = (window.__reports || []).filter(r => r.name !== n); return { ok: true }; },
  restore_report: async (n) => { window.__restored = (window.__restored || []).concat([n]); return { ok: true }; },
  save_chazonishnik_report: async (h, n) => { window.__savedAs = n; return { ok: true }; },
  get_my_trust: async () => 10,
  get_sources: async () => [],
  get_sync_settings: async () => ({}),
  get_all_nick_fields: async () => [],
  get_forum_io_flags: async () => ({}),
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
        "rows": json.dumps(make_rows(min(rows, 300)), ensure_ascii=False),
        "n": rows,
        "settings": json.dumps({"theme": "dark", "accent": "amber", "view": "table",
                                "density": "normal", "hidden_cols": "", "col_layout": "",
                                # מאגר שעבר מגרסה קודמת: חיפוש שנשמר. מ-0.9.6 ההפעלה
                                # מתעלמת ממנו ונפתחת עם כל הרשימה.
                                "last_search": "משתמש_12"}, ensure_ascii=False),
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
