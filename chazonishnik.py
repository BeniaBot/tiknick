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
