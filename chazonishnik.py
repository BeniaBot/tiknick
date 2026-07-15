# -*- coding: utf-8 -*-
"""
Chazonishnik — ניתוח פעילות משתמש בפורום NodeBB.
מבוסס על הסקריפט המקורי, מותאם לשימוש בתוך Tik-Nick:
פונקציה אחת analyze_user(...) שמחזירה HTML (ואופציונלית שומרת קובץ).
משתמש ב-urllib בלבד (ללא תלות ב-requests) כדי לא להוסיף תלויות.
"""
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures
from datetime import datetime

DEFAULT_BASE = "https://mitmachim.top"
CONCURRENCY = 12
MAX_PAGES = 1500
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _get_json(url, cookie=None, timeout=15):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    req.add_header("Accept", "application/json")
    if cookie:
        val = cookie if cookie.startswith("express.sid=") else f"express.sid={cookie}"
        req.add_header("Cookie", val)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _fetch_user(base, slug, cookie):
    data = _get_json(f"{base}/api/user/{urllib.parse.quote(slug)}", cookie=cookie)
    return data.get("uid"), data


def _scan_posts(base, slug, cookie, progress=None):
    all_posts = []
    page = 1
    while page <= MAX_PAGES:
        url = f"{base}/api/user/{urllib.parse.quote(slug)}/posts?page={page}"
        try:
            data = _get_json(url, cookie=cookie)
        except Exception:
            break
        posts = data.get("posts", []) if isinstance(data, dict) else []
        if not posts:
            break
        all_posts.extend(posts)
        if progress:
            progress({"phase": "scan", "page": page, "count": len(all_posts)})
        page += 1
    uniq = {p.get("pid"): p for p in all_posts if p.get("pid")}
    return list(uniq.values())


_DAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def _fetch_detail(base, cookie, post):
    try:
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


def analyze_user(username, cookie, base_url=DEFAULT_BASE, progress=None, save_path=None):
    """
    מריץ ניתוח מלא ומחזיר dict: {ok, html, path, posts, error}
    progress(dict) — קריאה אופציונלית לעדכוני התקדמות.
    """
    base = (base_url or DEFAULT_BASE).rstrip("/")
    slug = username.strip()
    try:
        my_uid, _ = _fetch_user(base, slug, cookie)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "error": "נדרשת עוגייה תקינה (שגיאת הרשאה)"}
        return {"ok": False, "error": f"שגיאת רשת: {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"לא ניתן למצוא משתמש: {e}"}

    raw_posts = _scan_posts(base, slug, cookie, progress=progress)
    if not raw_posts:
        return {"ok": False, "error": "לא נמצאו פוסטים (או שהמשתמש לא פעיל / העוגייה לא תקינה)"}

    processed = []
    total = len(raw_posts)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(_fetch_detail, base, cookie, p): p for p in raw_posts}
        for fut in concurrent.futures.as_completed(futs):
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

    return {"ok": True, "html": html, "path": path, "posts": len(processed)}


def _build_html(user_slug, base_url, my_uid, posts_data):
    json_data = json.dumps(posts_data, ensure_ascii=False)
    my_uid_json = json.dumps(my_uid)
    base_url_json = json.dumps(base_url)
    return HTML_TEMPLATE.replace("__USER__", user_slug) \
        .replace("__JSON_DATA__", json_data) \
        .replace("__MY_UID__", my_uid_json) \
        .replace("__BASE_URL__", base_url_json)


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ניתוח פעילות: __USER__</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
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
Object.entries(fans).sort((a,b)=>b[1]-a[1]).slice(0,10).forEach(([name,count])=>{document.getElementById('list-fans').innerHTML+=`<div class="list-item"><a href="${baseUrl}/user/${name}" target="_blank">${name}</a><span class="badge">${count}</span></div>`;});
const dayOrder=["ראשון","שני","שלישי","רביעי","חמישי","שישי","שבת"];
const dayCounts=dayOrder.map(day=>data.filter(d=>d.day===day).length);
new Chart(document.getElementById('chart-weekly'),{type:'radar',data:{labels:dayOrder,datasets:[{label:'פוסטים',data:dayCounts,borderColor:'#f59e0b',backgroundColor:'rgba(245,158,11,.2)'}]},options:{responsive:true,maintainAspectRatio:false,scales:{r:{grid:{color:'#334155'}}}}});
const lens={'קצר':0,'בינוני':0,'ארוך':0};data.forEach(d=>{if(d.words<20)lens['קצר']++;else if(d.words<100)lens['בינוני']++;else lens['ארוך']++;});
new Chart(document.getElementById('chart-length'),{type:'doughnut',data:{labels:Object.keys(lens),datasets:[{data:Object.values(lens),backgroundColor:['#ef4444','#3b82f6','#10b981'],borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'70%'}});
[...data].sort((a,b)=>b.likes-a.likes).slice(0,10).forEach(p=>{document.getElementById('list-best').innerHTML+=`<div class="list-item"><a href="${baseUrl}/post/${p.pid}" target="_blank" style="max-width:80%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.title}</a><span class="badge">+${p.likes}</span></div>`;});
new Chart(document.getElementById('chart-scatter'),{type:'scatter',data:{datasets:[{label:'פוסטים',data:data.map(d=>({x:d.words,y:d.likes})),backgroundColor:'#38bdf888'}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{type:'logarithmic',title:{display:true,text:'כמות מילים'}},y:{title:{display:true,text:'לייקים'}}}}});
</script>
</body>
</html>"""
