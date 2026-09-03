# -*- coding: utf-8 -*-
"""
Chazonishnik — ניתוח פעילות משתמש בפורום NodeBB.
מבוסס על הסקריפט המקורי, מותאם לשימוש בתוך Tik-Nick:
פונקציה אחת analyze_user(...) שמחזירה HTML (ואופציונלית שומרת קובץ).
משתמש ב-urllib בלבד (ללא תלות ב-requests) כדי לא להוסיף תלויות.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures
from datetime import datetime

DEFAULT_BASE = "https://mitmachim.top"
# 12 בקשות במקביל בלי כל השהיה היו מפציצות פורום קטן באלפי בקשות בדקה —
# הסורק ממתין 0.6 שניות בין עמודים ו-Stinknik 0.4, ואין סיבה שהניתוח יהיה גס יותר.
CONCURRENCY = 4
DETAIL_DELAY = 0.15          # השהיה קצרה בכל בקשת פרטים (per worker)
MAX_PAGES = 1500
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _get_json(url, cookie=None, timeout=15, retries=3):
    """GET JSON עם ניסיונות חוזרים וכיבוד Retry-After (429)."""
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


def _user_slug_variations(username):
    """מחזיר וריאציות סבירות של slug — NodeBB משתמש במקפים במקום רווחים."""
    u = username.strip()
    variations = []
    def add(v):
        if v and v not in variations:
            variations.append(v)
    add(u.replace(" ", "-"))          # רווח → מקף (הנפוץ ב-NodeBB)
    add(u.lower().replace(" ", "-"))  # אותיות קטנות
    add(u)                            # כמו שהוא
    add(u.replace(" ", ""))           # בלי רווחים
    return variations


def _fetch_user(base, username, cookie):
    """מנסה כמה וריאציות עד שנמצא משתמש. מחזיר (uid, slug, data)."""
    last_err = None
    u = username.strip()
    # קודם: חיפוש לפי username מדויק (מטפל ברווחים באופן טבעי)
    try:
        data = _get_json(f"{base}/api/user/username/{urllib.parse.quote(u)}", cookie=cookie)
        if isinstance(data, dict) and (data.get("uid") or data.get("username")):
            slug = data.get("userslug") or u.replace(" ", "-")
            return data.get("uid"), slug, data
    except Exception as e:
        last_err = e
    # אחר כך: וריאציות slug
    for slug in _user_slug_variations(username):
        try:
            data = _get_json(f"{base}/api/user/{urllib.parse.quote(slug)}", cookie=cookie)
            if isinstance(data, dict) and (data.get("uid") or data.get("username")):
                return data.get("uid"), (data.get("userslug") or slug), data
        except Exception as e:
            last_err = e
            continue
    raise last_err or Exception("לא נמצא משתמש")


def _scan_posts(base, slug, cookie, progress=None, cancel_flag=None, max_posts=None,
                stats=None):
    all_posts = []
    page = 1
    while page <= MAX_PAGES:
        if cancel_flag is not None and cancel_flag.is_set():
            break
        url = f"{base}/api/user/{urllib.parse.quote(slug)}/posts?page={page}"
        try:
            data = _get_json(url, cookie=cookie)
        except Exception:
            # עצירה על שגיאה = דוח חלקי; מסמנים כדי לדווח למשתמש
            if stats is not None and page > 1:
                stats["stopped_early"] = True
            break
        posts = data.get("posts", []) if isinstance(data, dict) else []
        if not posts:
            break
        all_posts.extend(posts)
        if progress:
            progress({"phase": "scan", "page": page, "count": len(all_posts)})
        if max_posts and len(all_posts) >= max_posts:
            break
        page += 1
    uniq = {p.get("pid"): p for p in all_posts if p.get("pid")}
    posts = list(uniq.values())
    if max_posts and len(posts) > max_posts:
        posts = posts[:max_posts]
    return posts


_DAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def _fetch_detail(base, cookie, post):
    try:
        time.sleep(DETAIL_DELAY)   # נימוס: 4 עובדים × 0.15s ≈ 27 בקשות לשנייה לכל היותר
        pid = post["pid"]
        clean = re.sub(r"<[^<]+?>", "", post.get("content", "") or "")
        words = len(clean.split())
        upvoters = []
        try:
            v = _get_json(f"{base}/api/v3/posts/{pid}/voters", cookie=cookie, timeout=10)
            upvoters = (v.get("response", {}) or {}).get("upvoters", []) or []
        except Exception:
            upvoters = []
        ts = post.get("timestamp") or 0
        dt = datetime.fromtimestamp(ts / 1000) if ts else datetime.now()
        return {
            "pid": pid,
            "title": (post.get("topic", {}) or {}).get("title", "תגובה"),
            "ts": ts,
            "date": dt.strftime("%Y-%m-%d"),
            "hour": dt.hour,
            "day": _DAYS_HE[dt.weekday()],
            "month": dt.strftime("%Y-%m"),
            "likes": len(upvoters),
            "voters": upvoters,
            "words": words,
        }
    except Exception:
        return None


def _collect(username, cookie, base, progress=None, cancel_flag=None,
             max_posts=None, label=""):
    """
    סורק ומעבד משתמש אחד ומחזיר (slug, uid, posts, meta) — או (None, None, None, err).
    הוצא מ-analyze_user כדי שההשוואה תשתמש בדיוק באותו מסלול, כולל ההשהיות
    והריטריי, ולא תיצור נתיב רשת שני.
    """
    scan_stats = {"stopped_early": False}
    try:
        uid, slug, udata = _fetch_user(base, username, cookie)
        postcount = int((udata or {}).get("postcount") or 0)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None, None, None, {"error": f"{label}נדרשת עוגייה תקינה (שגיאת הרשאה)"}
        return None, None, None, {"error": f"{label}שגיאת רשת: {e.code}"}
    except Exception as e:
        return None, None, None, {"error": f"{label}לא ניתן למצוא משתמש: {e}"}

    raw = _scan_posts(base, slug, cookie, progress=progress,
                      cancel_flag=cancel_flag, max_posts=max_posts, stats=scan_stats)
    if cancel_flag is not None and cancel_flag.is_set():
        return None, None, None, {"cancelled": True, "error": "בוטל"}
    if not raw:
        return None, None, None, {"error": f"{label}לא נמצאו פוסטים"}

    processed = []
    total = len(raw)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(_fetch_detail, base, cookie, x): x for x in raw}
        for fut in concurrent.futures.as_completed(futs):
            if cancel_flag is not None and cancel_flag.is_set():
                for f2 in futs:
                    f2.cancel()
                return None, None, None, {"cancelled": True, "error": "בוטל"}
            r = fut.result()
            done += 1
            if progress and done % 15 == 0:
                progress({"phase": "analyze", "done": done, "total": total})
            if r:
                processed.append(r)
    processed.sort(key=lambda x: x["ts"])
    limited = bool(max_posts and len(raw) >= max_posts)
    meta = {
        "postcount": postcount, "limited": limited,
        "stopped_early": scan_stats["stopped_early"],
        "partial": scan_stats["stopped_early"] or (
            bool(postcount) and len(raw) < postcount * 0.95 and not limited),
    }
    return slug, uid, processed, meta


def _summarize(posts):
    """מדדים להשוואה. מחושב כאן ולא ב-JS כדי שהדוח השמור יהיה עצמאי."""
    hours = [0] * 24
    days = [0] * 7
    months = {}
    likes = words = 0
    cats = {}
    for p in posts:
        hours[p["hour"] % 24] += 1
        try:
            days[_DAYS_HE.index(p["day"])] += 1
        except ValueError:
            pass
        months[p["month"]] = months.get(p["month"], 0) + 1
        likes += p.get("likes", 0)
        words += p.get("words", 0)
        t = (p.get("title") or "").strip()
        if t:
            cats[t] = cats.get(t, 0) + 1
    n = len(posts) or 1
    return {
        "posts": len(posts), "likes": likes,
        "avg_words": round(words / n, 1),
        "avg_likes": round(likes / n, 2),
        "hours": hours, "days": days, "months": months,
        "top_hour": hours.index(max(hours)) if posts else 0,
        "top_day": _DAYS_HE[days.index(max(days))] if posts else "",
        "first": posts[0]["date"] if posts else "",
        "last": posts[-1]["date"] if posts else "",
        "top_topics": sorted(cats.items(), key=lambda kv: -kv[1])[:5],
    }


def analyze_pair(user_a, user_b, cookie, base_url=DEFAULT_BASE, progress=None,
                 save_path=None, cancel_flag=None, max_posts=None):
    """
    משווה שני משתמשים. הסריקות רצות **בזו אחר זו ולא במקביל** — שתי סריקות
    בו-זמנית מכפילות את העומס על אותו פורום, וכל מנגנון הנימוס כאן (השהיה בין
    עמודים, כיבוד Retry-After) בנוי סביב זרם אחד.
    כל משתמש מדווח על החלקיות שלו בנפרד: "א' הושלם, ב' נעצר" הוא מצב אמיתי.
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")
    out = []
    for i, uname in enumerate((user_a, user_b)):
        def _p(d, _i=i, _u=uname):
            if progress:
                progress({**d, "which": _i + 1, "of": 2, "user": _u})
        slug, uid, posts, meta = _collect(uname, cookie, base, progress=_p,
                                          cancel_flag=cancel_flag, max_posts=max_posts,
                                          label=f"{uname}: ")
        if slug is None:
            return {"ok": False, **meta}
        out.append({"slug": slug, "uid": uid, "posts": posts, "meta": meta,
                    "stats": _summarize(posts)})

    html = _build_compare_html(base, out[0], out[1])
    path = None
    if save_path:
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
            path = save_path
        except Exception:
            path = None
    return {"ok": True, "html": html, "path": path,
            "posts": out[0]["stats"]["posts"] + out[1]["stats"]["posts"],
            "compare": True,
            "a": {"user": out[0]["slug"], **out[0]["meta"], "posts": out[0]["stats"]["posts"]},
            "b": {"user": out[1]["slug"], **out[1]["meta"], "posts": out[1]["stats"]["posts"]}}


def _build_compare_html(base_url, a, b):
    payload = {
        "a": {"user": a["slug"], "stats": a["stats"], "meta": a["meta"]},
        "b": {"user": b["slug"], "stats": b["stats"], "meta": b["meta"]},
        "base": base_url,
    }
    return COMPARE_TEMPLATE.replace("__CHARTJS__", _chartjs_tag()) \
        .replace("__A__", _esc(a["slug"])) \
        .replace("__B__", _esc(b["slug"])) \
        .replace("__JSON_DATA__", _json_for_script(payload))


def analyze_user(username, cookie, base_url=DEFAULT_BASE, progress=None, save_path=None,
                 cancel_flag=None, max_posts=None):
    """
    מריץ ניתוח מלא ומחזיר dict: {ok, html, path, posts, error}
    progress(dict) — קריאה אופציונלית לעדכוני התקדמות.
    max_posts — הגבלת מספר הפוסטים הנסרקים (None = הכל).
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")
    scan_stats = {"stopped_early": False}
    try:
        my_uid, slug, _udata = _fetch_user(base, username, cookie)
        postcount = int((_udata or {}).get("postcount") or 0)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "error": "נדרשת עוגייה תקינה (שגיאת הרשאה)"}
        return {"ok": False, "error": f"שגיאת רשת: {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"לא ניתן למצוא משתמש: {e}"}

    raw_posts = _scan_posts(base, slug, cookie, progress=progress,
                            cancel_flag=cancel_flag, max_posts=max_posts, stats=scan_stats)
    if cancel_flag is not None and cancel_flag.is_set():
        return {"ok": False, "cancelled": True, "error": "בוטל"}
    if not raw_posts:
        return {"ok": False, "error": "לא נמצאו פוסטים (או שהמשתמש לא פעיל / העוגייה לא תקינה)"}

    processed = []
    total = len(raw_posts)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(_fetch_detail, base, cookie, p): p for p in raw_posts}
        for fut in concurrent.futures.as_completed(futs):
            if cancel_flag is not None and cancel_flag.is_set():
                for f in futs:
                    f.cancel()
                return {"ok": False, "cancelled": True, "error": "בוטל"}
            r = fut.result()
            done += 1
            if progress and done % 15 == 0:
                progress({"phase": "analyze", "done": done, "total": total})
            if r:
                processed.append(r)

    processed.sort(key=lambda x: x["ts"])
    html = _build_html(slug, base, my_uid, processed)

    path = None
    if save_path:
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
            path = save_path
        except Exception:
            path = None

    limited = bool(max_posts and len(raw_posts) >= max_posts)
    partial = scan_stats["stopped_early"] or (
        bool(postcount) and len(raw_posts) < postcount * 0.95 and not limited)
    return {"ok": True, "html": html, "path": path, "posts": len(processed),
            "postcount": postcount, "partial": partial, "limited": limited,
            "stopped_early": scan_stats["stopped_early"]}


def _chartjs_tag():
    """
    Chart.js מוטמע בדוח כך שהקובץ השמור עובד גם בלי אינטרנט.
    הספרייה ארוזה ב-web/chart.umd.min.js (נכללת ב-EXE יחד עם שאר web/);
    אם הקובץ חסר משום מה — נופלים חזרה ל-CDN.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "web", "chart.umd.min.js")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return "<script>" + f.read() + "</script>"
    except Exception:
        return ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/'
                'dist/chart.umd.min.js"></script>')


def _esc(s):
    """בריחת HTML — כל טקסט שמקורו בפורום אינו בטוח."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _json_for_script(obj):
    """
    JSON להטמעה בתוך <script>. json.dumps אינו מנטרל '</script>', ולכן כותרת נושא
    או שם משתמש עוינים היו יכולים לפרוץ מהבלוק. מנטרלים < > & כרצפי \\u.
    """
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _build_html(user_slug, base_url, my_uid, posts_data):
    return HTML_TEMPLATE.replace("__CHARTJS__", _chartjs_tag()) \
        .replace("__USER__", _esc(user_slug)) \
        .replace("__JSON_DATA__", _json_for_script(posts_data)) \
        .replace("__MY_UID__", _json_for_script(my_uid)) \
        .replace("__BASE_URL__", _json_for_script(base_url))


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ניתוח פעילות: __USER__</title>
__CHARTJS__
<style>
:root{--bg:#0f172a;--card-bg:#1e293b;--accent:#38bdf8;--text-main:#f1f5f9;--text-dim:#94a3b8}
body{background:var(--bg);color:var(--text-main);font-family:'Assistant',Arial,sans-serif;margin:0;padding:20px;overflow-x:hidden}
.container{max-width:1300px;margin:0 auto}
.header{text-align:center;margin-bottom:40px;padding:40px;background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border-radius:20px;border:1px solid #334155}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:20px}
.card{background:var(--card-bg);border-radius:16px;padding:24px;border:1px solid #334155;transition:all .3s ease}
.card:hover{transform:translateY(-5px);border-color:var(--accent)}
.col-3{grid-column:span 3}.col-4{grid-column:span 4}.col-6{grid-column:span 6}.col-8{grid-column:span 8}.col-12{grid-column:span 12}
.kpi-title{color:var(--text-dim);font-size:.9rem;font-weight:600;margin-bottom:8px}
.kpi-value{font-size:2.2rem;font-weight:800;color:#fff}
h3{margin-top:0;font-size:1.1rem;color:var(--accent);margin-bottom:20px}
.list-container{max-height:300px;overflow-y:auto}
.list-item{display:flex;justify-content:space-between;align-items:center;padding:12px;border-bottom:1px solid #334155}
.list-item a{color:var(--text-main);text-decoration:none;font-weight:500}
.badge{background:#0c4a6e;color:#38bdf8;padding:4px 12px;border-radius:20px;font-weight:700;font-size:.85rem}
.chart-box{position:relative;height:300px;width:100%}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-thumb{background:#475569;border-radius:3px}
@media(max-width:900px){.col-3,.col-4,.col-6,.col-8{grid-column:span 12}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1 style="margin:0;font-size:2rem">📊 ניתוח פעילות: __USER__</h1>
<p style="color:var(--text-dim);margin-top:10px">ניתוח נתונים מעמיק של פעילות המשתמש</p>
</div>
<div class="grid">
<div class="card col-3"><div class="kpi-title">סה"כ פוסטים</div><div class="kpi-value" id="stat-posts">0</div></div>
<div class="card col-3"><div class="kpi-title">לייקים שהתקבלו</div><div class="kpi-value" id="stat-likes" style="color:#10b981">0</div></div>
<div class="card col-3"><div class="kpi-title">מילים שנכתבו</div><div class="kpi-value" id="stat-words">0</div></div>
<div class="card col-3"><div class="kpi-title">זמן קריאה כולל</div><div class="kpi-value" id="stat-time" style="color:#f59e0b">0</div></div>
<div class="card col-8"><h3>📈 מגמת פרסום חודשית</h3><div class="chart-box"><canvas id="chart-monthly"></canvas></div></div>
<div class="card col-4"><h3>🕒 פעילות לפי שעות</h3><div class="chart-box"><canvas id="chart-hourly"></canvas></div></div>
<div class="card col-4"><h3>🏆 מקורות לייקים</h3><div class="list-container" id="list-fans"></div></div>
<div class="card col-4"><h3>📅 ימי פעילות מועדפים</h3><div class="chart-box"><canvas id="chart-weekly"></canvas></div></div>
<div class="card col-4"><h3>📏 אורך תוכן</h3><div class="chart-box"><canvas id="chart-length"></canvas></div></div>
<div class="card col-6"><h3>⭐ הפוסטים המוצלחים ביותר</h3><div class="list-container" id="list-best"></div></div>
<div class="card col-6"><h3>🔍 קשר בין אורך פוסט לפופולריות</h3><div class="chart-box"><canvas id="chart-scatter"></canvas></div></div>
</div>
</div>
<script>
const data=__JSON_DATA__;const myUid=__MY_UID__;const baseUrl=__BASE_URL__;
// כל טקסט מהפורום עובר בריחה לפני הזרקה ל-innerHTML
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const escAttr=s=>encodeURIComponent(String(s==null?'':s));
const totalLikes=data.reduce((a,b)=>a+b.likes,0);
const totalWords=data.reduce((a,b)=>a+b.words,0);
document.getElementById('stat-posts').innerText=data.length.toLocaleString();
document.getElementById('stat-likes').innerText=totalLikes.toLocaleString();
document.getElementById('stat-words').innerText=totalWords.toLocaleString();
document.getElementById('stat-time').innerText=Math.ceil(totalWords/200)+" דק'";
Chart.defaults.color='#94a3b8';
const monthCounts={};data.forEach(d=>monthCounts[d.month]=(monthCounts[d.month]||0)+1);
new Chart(document.getElementById('chart-monthly'),{type:'line',data:{labels:Object.keys(monthCounts),datasets:[{label:'פוסטים',data:Object.values(monthCounts),borderColor:'#38bdf8',backgroundColor:'rgba(56,189,248,.1)',fill:true,tension:.4}]},options:{responsive:true,maintainAspectRatio:false}});
const hourlyData=Array(24).fill(0);data.forEach(d=>hourlyData[d.hour]++);
new Chart(document.getElementById('chart-hourly'),{type:'bar',data:{labels:Array.from({length:24},(_,i)=>i+":00"),datasets:[{label:'פוסטים',data:hourlyData,backgroundColor:'#8b5cf6'}]},options:{responsive:true,maintainAspectRatio:false}});
const fans={};data.forEach(p=>p.voters.forEach(v=>{if(v.uid!=myUid)fans[v.username]=(fans[v.username]||0)+1}));
Object.entries(fans).sort((a,b)=>b[1]-a[1]).slice(0,10).forEach(([name,count])=>{document.getElementById('list-fans').innerHTML+=`<div class="list-item"><a href="${esc(baseUrl)}/user/${escAttr(name)}" target="_blank">${esc(name)}</a><span class="badge">${esc(count)}</span></div>`;});
const dayOrder=["ראשון","שני","שלישי","רביעי","חמישי","שישי","שבת"];
const dayCounts=dayOrder.map(day=>data.filter(d=>d.day===day).length);
new Chart(document.getElementById('chart-weekly'),{type:'radar',data:{labels:dayOrder,datasets:[{label:'פוסטים',data:dayCounts,borderColor:'#f59e0b',backgroundColor:'rgba(245,158,11,.2)'}]},options:{responsive:true,maintainAspectRatio:false,scales:{r:{grid:{color:'#334155'}}}}});
const lens={'קצר':0,'בינוני':0,'ארוך':0};data.forEach(d=>{if(d.words<20)lens['קצר']++;else if(d.words<100)lens['בינוני']++;else lens['ארוך']++;});
new Chart(document.getElementById('chart-length'),{type:'doughnut',data:{labels:Object.keys(lens),datasets:[{data:Object.values(lens),backgroundColor:['#ef4444','#3b82f6','#10b981'],borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'70%'}});
[...data].sort((a,b)=>b.likes-a.likes).slice(0,10).forEach(p=>{document.getElementById('list-best').innerHTML+=`<div class="list-item"><a href="${esc(baseUrl)}/post/${encodeURIComponent(p.pid)}" target="_blank" style="max-width:80%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.title)}</a><span class="badge">+${esc(p.likes)}</span></div>`;});
new Chart(document.getElementById('chart-scatter'),{type:'scatter',data:{datasets:[{label:'פוסטים',data:data.map(d=>({x:d.words,y:d.likes})),backgroundColor:'#38bdf888'}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{type:'logarithmic',title:{display:true,text:'כמות מילים'}},y:{title:{display:true,text:'לייקים'}}}}});
</script>
</body>
</html>"""


COMPARE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>השוואה: __A__ מול __B__</title>
__CHARTJS__
<style>
  :root{--a:#f59e0b;--b:#0ea5e9;--bg:#14161c;--card:#1c1f28;--txt:#e8eaf0;--sub:#9aa2b4}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font-family:"Segoe UI",Arial,sans-serif;font-size:14px;line-height:1.6}
  .wrap{max-width:1000px;margin:0 auto;padding:24px 18px 60px}
  h1{font-size:24px;margin:0 0 4px}
  .who{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:20px;font-size:13px}
  .pill{padding:3px 12px;border-radius:99px;font-weight:700}
  .pa{background:rgba(245,158,11,.18);color:var(--a)}
  .pb{background:rgba(14,165,233,.18);color:var(--b)}
  .card{background:var(--card);border-radius:14px;padding:16px 18px;margin-bottom:16px}
  .card h2{font-size:15px;margin:0 0 12px;font-weight:700}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:right;padding:7px 8px;border-bottom:1px solid rgba(255,255,255,.07);font-size:13px}
  th{color:var(--sub);font-weight:600;font-size:12px}
  td.va{color:var(--a);font-weight:700}
  td.vb{color:var(--b);font-weight:700}
  .warn{background:rgba(244,84,76,.12);color:#ff9a94;padding:8px 12px;
        border-radius:8px;font-size:12.5px;margin-bottom:14px}
  .sum{font-size:13.5px;line-height:1.9}
  canvas{max-height:260px}
  .foot{color:var(--sub);font-size:11.5px;text-align:center;margin-top:26px}
</style></head><body><div class="wrap">
<h1>השוואת פעילות</h1>
<div class="who"><span class="pill pa">__A__</span><span style="color:var(--sub)">מול</span>
  <span class="pill pb">__B__</span></div>
<div id="warn"></div>
<div class="card"><h2>מספרים</h2><table id="tbl"></table></div>
<div class="card"><h2>שעות פעילות</h2><canvas id="c-hours"></canvas></div>
<div class="card"><h2>ימים בשבוע</h2><canvas id="c-days"></canvas></div>
<div class="card"><h2>פעילות לאורך זמן</h2><canvas id="c-months"></canvas></div>
<div class="card"><h2>מה עולה מההשוואה</h2><div class="sum" id="sum"></div></div>
<div class="foot">Tik-Nick · חזונישניק</div>
</div>
<script>
const D = __JSON_DATA__;
const A = D.a, B = D.b, SA = A.stats, SB = B.stats;
// _json_for_script מגן על הבריחה מבלוק ה-script, אבל אחרי ש-JS פירס את המחרוזת
// היא שוב מכילה < > אמיתיים — ולכן כל שם משתמש או כותרת נושא שנכנסים ל-innerHTML
// חייבים בריחה כאן. הדוח החד-משתמשי כבר עושה זאת; ההשוואה לא עשתה.
function esc(v) {
  return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
const DAYS = ["שני","שלישי","רביעי","חמישי","שישי","שבת","ראשון"];
const COL_A = "#f59e0b", COL_B = "#0ea5e9";

// דיווח כן על חלקיות — לכל משתמש בנפרד. "א' הושלם, ב' נעצר" הוא מצב אמיתי.
const notes = [];
for (const side of [A, B]) {
  const m = side.meta;
  if (m.limited) notes.push(esc(side.user) + ": נסרקו רק הפוסטים האחרונים לפי ההגבלה שהגדרת.");
  else if (m.stopped_early) notes.push(esc(side.user) + ": הסריקה נעצרה בגלל תקלת רשת — הנתונים חלקיים.");
  else if (m.partial) notes.push(esc(side.user) + ": נסרקו " + side.stats.posts + " מתוך " +
    m.postcount + " פוסטים; השאר כנראה בקטגוריות שדורשות התחברות.");
}
if (notes.length) document.getElementById("warn").innerHTML =
  "<div class=\"warn\">⚠️ " + notes.join("<br>") + "</div>";

const rows = [
  ["פוסטים שנסרקו", SA.posts, SB.posts],
  ["לייקים שהתקבלו", SA.likes, SB.likes],
  ["לייקים לפוסט (ממוצע)", SA.avg_likes, SB.avg_likes],
  ["מילים לפוסט (ממוצע)", SA.avg_words, SB.avg_words],
  ["שעת השיא", SA.top_hour + ":00", SB.top_hour + ":00"],
  ["היום הפעיל ביותר", SA.top_day, SB.top_day],
  ["פוסט ראשון שנסרק", SA.first, SB.first],
  ["פוסט אחרון שנסרק", SA.last, SB.last],
];
document.getElementById("tbl").innerHTML =
  "<tr><th></th><th>" + esc(A.user) + "</th><th>" + esc(B.user) + "</th></tr>" +
  rows.map(function (r) {
    return "<tr><td>" + esc(r[0]) + "</td><td class=\"va\">" + esc(r[1]) +
           "</td><td class=\"vb\">" + esc(r[2]) + "</td></tr>";
  }).join("");

const opts = function () {
  return { responsive: true, plugins: { legend: { labels: { color: "#e8eaf0" } } },
    scales: { x: { ticks: { color: "#9aa2b4" }, grid: { color: "rgba(255,255,255,.05)" } },
              y: { ticks: { color: "#9aa2b4" }, grid: { color: "rgba(255,255,255,.05)" },
                   beginAtZero: true } } };
};

new Chart(document.getElementById("c-hours"), { type: "bar", data: {
  labels: Array.from({length: 24}, function (_, h) { return h + ":00"; }),
  datasets: [{ label: A.user, data: SA.hours, backgroundColor: COL_A },
             { label: B.user, data: SB.hours, backgroundColor: COL_B }] }, options: opts() });

new Chart(document.getElementById("c-days"), { type: "bar", data: {
  labels: DAYS,
  datasets: [{ label: A.user, data: SA.days, backgroundColor: COL_A },
             { label: B.user, data: SB.days, backgroundColor: COL_B }] }, options: opts() });

const months = Object.keys(SA.months).concat(Object.keys(SB.months))
  .filter(function (v, i, a) { return a.indexOf(v) === i; }).sort();
new Chart(document.getElementById("c-months"), { type: "line", data: {
  labels: months,
  datasets: [{ label: A.user, data: months.map(function (m) { return SA.months[m] || 0; }),
               borderColor: COL_A, backgroundColor: COL_A, tension: .3 },
             { label: B.user, data: months.map(function (m) { return SB.months[m] || 0; }),
               borderColor: COL_B, backgroundColor: COL_B, tension: .3 }] }, options: opts() });

// סיכום במילים — מה באמת שונה, לא רק גרפים יפים.
// "כמה כתב" חייב להיחשב מסך הפוסטים בפורום ולא ממה שנסרק: ההגבלה חותכת את שני
// המשתמשים לאותו מספר, וכך המשפט היה יוצא "בערך אותה כמות" בדיוק כשההפרש גדול,
// או אפילו מצביע על ההפוך. אם אין postcount אמין — אומרים במפורש על מה מדובר.
const out = [];
const capped = A.meta.limited || B.meta.limited;
const totA = A.meta.postcount || 0, totB = B.meta.postcount || 0;
const useTotals = totA > 0 && totB > 0;
const mA = useTotals ? totA : SA.posts, mB = useTotals ? totB : SB.posts;
const more = mA >= mB ? A : B, less = mA >= mB ? B : A;
const hi = Math.max(mA, mB), lo = Math.max(1, Math.min(mA, mB));
const rat = (hi / lo).toFixed(1);
const basis = useTotals ? " (לפי סך הפוסטים בפורום)"
                        : (capped ? " (מתוך מה שנסרק בלבד)" : "");
out.push("• <b>" + esc(more.user) + "</b> כתב " +
  (rat > 1.15 ? "פי " + rat + " יותר" : "בערך אותה כמות") +
  " פוסטים מ־<b>" + esc(less.user) + "</b>" + basis + ".");
if (capped) out.push("• שאר ההשוואה מבוססת על " + Math.min(SA.posts, SB.posts) +
  "–" + Math.max(SA.posts, SB.posts) + " הפוסטים האחרונים של כל אחד, לפי ההגבלה שהגדרת.");
if (Math.abs(SA.avg_likes - SB.avg_likes) > 0.2)
  out.push("• פוסט של <b>" + esc(SA.avg_likes > SB.avg_likes ? A.user : B.user) +
    "</b> מקבל בממוצע יותר לייקים (" + Math.max(SA.avg_likes, SB.avg_likes) + " מול " +
    Math.min(SA.avg_likes, SB.avg_likes) + ").");
if (Math.abs(SA.avg_words - SB.avg_words) > 10)
  out.push("• <b>" + esc(SA.avg_words > SB.avg_words ? A.user : B.user) + "</b> כותב ארוך יותר (" +
    Math.max(SA.avg_words, SB.avg_words) + " מילים לפוסט מול " +
    Math.min(SA.avg_words, SB.avg_words) + ").");
out.push(SA.top_hour !== SB.top_hour
  ? "• שעות השיא שונות: " + esc(A.user) + " ב־" + SA.top_hour + ":00, " + esc(B.user) + " ב־" + SB.top_hour + ":00."
  : "• שניהם פעילים בעיקר סביב " + SA.top_hour + ":00.");
if (SA.top_day === SB.top_day) out.push("• שניהם פעילים במיוחד ביום " + esc(SA.top_day) + ".");
const shared = SA.top_topics.map(function (t) { return t[0]; }).filter(function (t) {
  return SB.top_topics.some(function (x) { return x[0] === t; });
});
if (shared.length) out.push("• נושאים משותפים בין הבולטים: " +
  shared.slice(0, 3).map(esc).join(" · ") + ".");
document.getElementById("sum").innerHTML = out.join("<br>");
</script></body></html>"""
