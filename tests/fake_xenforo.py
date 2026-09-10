# -*- coding: utf-8 -*-
"""
שרת XenForo מזויף — משחזר את הסימון שנמדד בפרוג ובלתורה, כולל המלכודות.

הנתונים סינתטיים לגמרי: אין כאן שום שם אמיתי משום פורום.
"""
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── התבנית, מועתקת בצורתה מהסימון שנמדד ────────────────────────────────
_ROW = '''      <li class="block-row block-row--separated">
       <div class="contentRow">
        <div class="contentRow-figure">
         <a href="{href}" class="avatar avatar--s avatar--default" data-user-id="{uid}">
          <span class="avatar-u{uid}-s" role="img" aria-label="{name}">x</span>
         </a>
        </div>
        <div class="contentRow-main">
         <h3 class="contentRow-header"><a href="{href}" class="username " dir="auto" data-user-id="{uid}">{name}</a></h3>
         <div class="contentRow-lesser" dir="auto"><span class="userTitle" dir="auto">{title}</span></div>
         <div class="contentRow-minor">
          <ul class="listInline listInline--bullet">
           <li><dl class="pairs pairs--inline">
            <dt>הודעות</dt>
            <dd>{posts}</dd>
           </dl>
           </li>
          </ul>
         </div>
        </div>
       </div>
      </li>
'''

_PAGE = '''<!DOCTYPE html>
<html dir="rtl" lang="he" data-template="member_list" data-logged-in="false" data-cookie-prefix="xf_">
<head>
 <meta charset="utf-8" />
 <title>חברים רשומים | פורום בדיקה</title>
 <link rel="canonical" href="{base}/members/list/?page={page}" />
 {nextlink}
</head>
<body>
 <div class="block-container">
  <div class="block-body">
   <ol class="block-body">
{rows}   </ol>
  </div>
 </div>
 <!-- זיהום סרגל צד: קישורי /members/ שאינם שורות ברשימה -->
 <div class="block block--messages">
  <a href="/members/staff-one.90001/" class="username">צוות אחד</a>
  <a href="/members/90002/" class="username">צוות שתיים</a>
 </div>
 <nav class="pageNavWrapper">
  <ul class="pageNav-main">
{nav}  </ul>
  <input class="input js-pageJumpPage" type="number" min="1" max="{last}" value="{page}">
 </nav>
</body>
</html>
'''

_LOGIN = ('<!DOCTYPE html><html><body><form action="/login/login">'
          '<label>שמך או כתובת האימייל שלך</label><input name="login">'
          '<label>סיסמא</label><input name="password" type="password">'
          '<a href="/lost-password/">שכחת ססמה?</a></form></body></html>')


def make_members(n, per_page):
    """n חברים סינתטיים, כולל המקרים שמפילים מפרשים תמימים."""
    out = []
    for i in range(1, n + 1):
        uid = 1000 + i
        if i == 1:
            name, title, posts = "&quot;שם במרכאות&quot;", "חבר ותיק", "3,605"
        elif i == 2:
            name, title, posts = "שם עם רווח", "משתמש חדש", "0"
        elif i == 3:
            name, title, posts = "R&amp;D", "מנהל", "12"
        else:
            name, title, posts = "משתמש %d" % i, "חבר רשום", str(i * 7)
        # חצי מהחברים עם סלאג בכתובת, חצי בלי — שני הכתיבים קיימים בפועל
        href = ("/members/user-%d.%d/" % (i, uid)) if i % 2 else ("/members/%d/" % uid)
        out.append({"uid": uid, "name": name, "title": title,
                    "posts": posts, "href": href})
    return out


class _Handler(BaseHTTPRequestHandler):
    members = []
    per_page = 10
    base = ""
    login_wall = False          # כמו אוצר התורה: הרשימה עצמה דורשת התחברות
    fail_pages = set()          # עמודים שיחזירו 500, לבדיקת מונה הכשלים
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _Handler.hits.append(self.path)
        if self.path.startswith("/api/"):
            return self._send(400, '{"errors":[{"code":"no_api_key_in_request"}]}',
                              "application/json")
        if not self.path.startswith("/members/list"):
            return self._send(404, "no", "text/html")
        if _Handler.login_wall:
            return self._send(403, _LOGIN, "text/html")

        m = re.search(r"[?&]page=(\d+)", self.path)
        page = int(m.group(1)) if m else 1
        if page in _Handler.fail_pages:
            return self._send(500, "boom", "text/html")

        per = _Handler.per_page
        total = len(_Handler.members)
        last = max(1, (total + per - 1) // per)
        # ⚠️ המלכודת שנמדדה: עמוד מעבר לסוף מחזיר את העמוד האחרון שוב
        eff = min(page, last)
        chunk = _Handler.members[(eff - 1) * per: eff * per]

        rows = "".join(_ROW.format(**c) for c in chunk)
        nav = "".join(
            '    <li class="pageNav-page"><a href="/members/list/?page=%d">%d</a></li>\n' % (p, p)
            for p in sorted({1, 2, min(3, last), last}))
        nextlink = ('<link rel="next" href="/members/list/?page=%d" />' % (eff + 1)
                    if eff < last else "")
        self._send(200, _PAGE.format(base=_Handler.base, page=eff, rows=rows,
                                     nav=nav, nextlink=nextlink, last=last), "text/html")

    def _send(self, code, body, ctype):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def start(members, per_page=10, login_wall=False, fail_pages=()):
    _Handler.members = members
    _Handler.per_page = per_page
    _Handler.login_wall = login_wall
    _Handler.fail_pages = set(fail_pages)
    _Handler.hits = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    _Handler.base = "http://127.0.0.1:%d" % srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, _Handler.base


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import urllib.request
    from proto_parse import parse_page, last_page

    srv, base = start(make_members(25, 10))
    print("שרת מזויף על", base)

    def g(p):
        return urllib.request.urlopen(base + "/members/list/?page=%d" % p,
                                      timeout=5).read().decode("utf-8")

    for p in (1, 2, 3, 4):
        s = g(p)
        rows = parse_page(s)
        print("  עמוד %d: שורות=%-3d עמוד-אחרון=%s  ראשון=%s"
              % (p, len(rows), last_page(s),
                 (rows[0]["uid"] + " " + rows[0]["username"]) if rows else "-"))
    s3, s4 = parse_page(g(3)), parse_page(g(4))
    same = [r["uid"] for r in s3] == [r["uid"] for r in s4]
    print("  עמוד 4 == עמוד 3 (המלכודת משוחזרת):", same)
    srv.shutdown()
