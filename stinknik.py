# -*- coding: utf-8 -*-
"""
Stinknik — מביא את רשימת כל הפוסטים של ניק שקיבלו דיסלייקים.
מבוסס על הסקריפט שסופק, מותאם ל-Tik-Nick: פונקציה analyze_dislikes(...)
שמחזירה HTML + סטטיסטיקות. משתמש ב-endpoint הציבורי /api/user/{slug}/posts
(אין צורך בעוגיות ברוב המקרים). urllib בלבד — ללא תלויות חדשות.
"""
import json
import urllib.request
import urllib.parse
import urllib.error
import time

DEFAULT_BASE = "https://mitmachim.top"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
PAGE_DELAY = 0.4
MAX_PAGES = 2000


def _get_json(url, cookie=None, timeout=15, retries=3):
    """GET JSON עם ניסיונות חוזרים וכיבוד Retry-After (429) — בלי זה כל תקלת רשת
    רגעית קטעה את הסריקה בשקט והדוח הוצג כמלא."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    req.add_header("Accept", "application/json")
    if cookie:
        val = cookie if cookie.startswith("express.sid=") else f"express.sid={cookie}"
        req.add_header("Cookie", val)
    last = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                ra = e.headers.get("Retry-After")
                time.sleep(min(int(ra) if (ra and ra.isdigit()) else attempt * 3, 30))
                last = e
                continue
            if e.code in (401, 403, 404):
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(attempt * 1.5)
    raise last


def _slug_from_input(user_input):
    """מחלץ slug מקישור מלא או משם משתמש. תומך גם ברווחים (→ מקף)."""
    s = (user_input or "").strip().strip("/")
    if "/" in s:
        s = s.split("/")[-1]
    return s


def _resolve_slug(base, user_input, cookie=None):
    return _resolve_user(base, user_input, cookie)[0]


def _resolve_user(base, user_input, cookie=None):
    """מחזיר (userslug, postcount). ה-postcount משמש לדיווח 'נסרקו X מתוך Y'."""
    raw = _slug_from_input(user_input)
    # וריאציות סלאג סבירות (NodeBB ממיר רווחים למקפים)
    candidates = []
    for c in (raw, raw.replace(" ", "-"), raw.lower().replace(" ", "-")):
        if c and c not in candidates:
            candidates.append(c)
    # קודם: חיפוש לפי username מדויק (מטפל ברווחים באופן טבעי)
    try:
        data = _get_json(f"{base}/api/user/username/{urllib.parse.quote(raw)}", cookie=cookie)
        if isinstance(data, dict) and data.get("userslug"):
            return data["userslug"], int(data.get("postcount") or 0)
    except Exception:
        pass
    # אחר כך: נסה כל וריאציית סלאג עד שאחת נפתרת
    for slug in candidates:
        try:
            data = _get_json(f"{base}/api/user/{urllib.parse.quote(slug)}", cookie=cookie)
            if isinstance(data, dict) and (data.get("userslug") or data.get("uid")):
                return (data.get("userslug") or slug), int(data.get("postcount") or 0)
        except Exception:
            continue
    # ברירת מחדל: הצורה עם מקפים (הנפוצה ב-NodeBB) ולא הגולמית
    return (candidates[1] if len(candidates) > 1 else raw), 0


def analyze_dislikes(user_input, base_url=DEFAULT_BASE, cookie=None,
                     progress=None, cancel_flag=None, max_posts=None):
    """
    סורק את כל הפוסטים של המשתמש ואוסף את אלה שקיבלו דיסלייקים.
    max_posts — הגבלת מספר הפוסטים הנסרקים (None = הכל).
    מחזיר dict: {ok, html, disliked, checked, up, down, rep, error, cancelled}
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")
    slug, postcount = _resolve_user(base, user_input, cookie=cookie)
    api = f"{base}/api/user/{urllib.parse.quote(slug)}/posts"

    page = 1
    checked = 0
    total_up = total_down = total_rep = 0
    disliked = []
    stopped_early = False   # נעצר באמצע בגלל שגיאה — הדוח חלקי

    while page <= MAX_PAGES:
        if max_posts and checked >= max_posts:
            break
        if cancel_flag is not None and cancel_flag.is_set():
            return {"ok": False, "cancelled": True, "error": "בוטל"}
        try:
            data = _get_json(f"{api}?page={page}", cookie=cookie)
        except urllib.error.HTTPError as e:
            if page == 1:
                if e.code in (401, 403):
                    return {"ok": False, "error": "נדרשת עוגייה / הרשאה"}
                return {"ok": False, "error": f"שגיאת רשת: {e.code}"}
            stopped_early = True
            break
        except Exception as e:
            if page == 1:
                return {"ok": False, "error": f"שגיאה: {e}"}
            stopped_early = True
            break

        posts = data.get("posts", []) if isinstance(data, dict) else []
        if not posts:
            break

        for post in posts:
            checked += 1
            pid = post.get("pid", "?")
            up = post.get("upvotes", 0) or 0
            down = post.get("downvotes", 0) or 0
            rep = post.get("votes", 0) or 0
            total_up += up
            total_down += down
            total_rep += rep
            if down > 0:
                # כותרת הנושא אם קיימת
                title = ""
                topic = post.get("topic") or {}
                if isinstance(topic, dict):
                    title = topic.get("title", "")
                disliked.append({
                    "pid": pid, "upvotes": up, "downvotes": down,
                    "reputation": rep, "title": title or "תגובה",
                    "link": f"{base}/post/{pid}",
                    "timestamp": post.get("timestamp", 0),
                })

        if progress:
            progress({"checked": checked, "page": page, "disliked": len(disliked)})
        page += 1
        time.sleep(PAGE_DELAY)

    # דיווח כן: האם נסרק הכול? (הפרש נובע מפוסטים בפורומים שדורשים התחברות,
    # מהגבלת כמות שהמשתמש קבע, או מעצירה על שגיאת רשת)
    limited = bool(max_posts and checked >= max_posts)
    partial = stopped_early or (bool(postcount) and checked < postcount * 0.95 and not limited)
    disliked.sort(key=lambda p: p["downvotes"], reverse=True)
    html = _build_html(slug, disliked, checked, total_up, total_down, total_rep, postcount)
    return {"ok": True, "html": html, "disliked": len(disliked),
            "checked": checked, "up": total_up, "down": total_down, "rep": total_rep,
            "postcount": postcount, "partial": partial, "stopped_early": stopped_early,
            "limited": limited}


def _build_html(slug, disliked, checked, up, down, rep, postcount=0):
    if disliked:
        rows = []
        for p in disliked:
            # כל ערך מהפורום (כולל pid ו-link) עובר בריחה
            rows.append(f"""
            <div class="post-card">
              <div class="post-title">{_esc(p['title'])} <span style="opacity:.5;font-size:13px">#{_esc(p['pid'])}</span></div>
              <div class="post-stats">
                <span>👍 {_esc(p['upvotes'])}</span>
                <span class="dis">👎 {_esc(p['downvotes'])}</span>
                <span>⭐ {_esc(p['reputation'])}</span>
              </div>
              <a href="{_esc(p['link'])}" target="_blank" class="post-link">למעבר לפוסט 🌐</a>
            </div>""")
        posts_html = "".join(rows)
    else:
        posts_html = '<div class="success-message">🎉 לא נמצאו פוסטים עם דיסלייקים כלל.</div>'

    return _TEMPLATE \
        .replace("__SLUG__", _esc(slug)) \
        .replace("__SCANNOTE__", f" מתוך {postcount:,}" if postcount else "") \
        .replace("__CHECKED__", f"{checked:,}") \
        .replace("__UP__", str(up)) \
        .replace("__DOWN__", str(down)) \
        .replace("__REP__", str(rep)) \
        .replace("__DISCOUNT__", str(len(disliked))) \
        .replace("__POSTS__", posts_html)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


_TEMPLATE = r"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<title>Stinknik — דוח דיסלייקים: __SLUG__</title>
<style>
body{font-family:'Segoe UI',Tahoma,Arial,sans-serif;background:#0f172a;color:#f1f5f9;margin:0;padding:40px 20px}
.container{max-width:860px;margin:auto;background:#1e293b;padding:30px;border-radius:16px;border:1px solid #334155}
h1{color:#38bdf8;text-align:center;border-bottom:2px solid #334155;padding-bottom:15px;margin-top:0}
.sub{text-align:center;color:#94a3b8;margin-top:6px}
.summary-cards{display:flex;justify-content:space-between;margin-top:26px;gap:14px;flex-wrap:wrap}
.card{background:#0f172a;padding:20px;border-radius:12px;text-align:center;flex:1;min-width:120px;border:1px solid #334155}
.card h3{margin:0;font-size:28px;color:#38bdf8}
.card.bad h3{color:#ef4444}
.card p{margin:5px 0 0;font-size:14px;color:#94a3b8;font-weight:600}
h2{margin-top:36px;color:#e2e8f0;font-size:1.15rem}
.post-card{background:#0f172a;border:1px solid #334155;border-right:5px solid #ef4444;padding:18px;margin-bottom:14px;border-radius:10px;transition:transform .2s}
.post-card:hover{transform:translateY(-3px);border-color:#ef4444}
.post-title{font-size:16px;font-weight:bold;margin-bottom:10px}
.post-stats span{display:inline-block;background:#1e293b;padding:5px 12px;border-radius:20px;font-size:13px;margin-left:8px;margin-bottom:8px}
.post-stats span.dis{background:#7f1d1d;color:#fecaca}
.post-link{display:inline-block;margin-top:8px;color:#fff;background:#38bdf8;padding:8px 15px;border-radius:6px;text-decoration:none;font-weight:bold;font-size:13px}
.post-link:hover{background:#0ea5e9}
.success-message{text-align:center;font-size:18px;color:#10b981;padding:24px;background:#052e2b;border-radius:10px}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-thumb{background:#475569;border-radius:3px}
</style>
</head>
<body>
<div class="container">
<h1>🦨 Stinknik — דוח דיסלייקים</h1>
<div class="sub">המשתמש: <b>__SLUG__</b></div>
<div class="summary-cards">
<div class="card"><h3>__CHECKED__</h3><p>פוסטים שנסרקו__SCANNOTE__</p></div>
<div class="card"><h3>__UP__</h3><p>👍 לייקים</p></div>
<div class="card bad"><h3>__DOWN__</h3><p>👎 דיסלייקים</p></div>
<div class="card bad"><h3>__DISCOUNT__</h3><p>פוסטים עם דיסים</p></div>
</div>
<h2>🔗 כל הפוסטים שקיבלו דיסלייק (מהרבה למעט):</h2>
__POSTS__
</div>
</body>
</html>"""
