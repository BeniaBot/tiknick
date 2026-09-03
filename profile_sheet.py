# -*- coding: utf-8 -*-
"""
פרופיל להדפסה — גיליון A4 בעברית לניק אחד או לקבוצת זהות שלמה.

הגיליון נכתב לקובץ ונפתח בדפדפן ברירת המחדל של המערכת, ולא מודפס מתוך התוכנה.
זו לא בחירה סגנונית: בבנייה המשוחררת אין מסלול הדפסה בכלל —
  • ה-iframe של הדוחות הוא sandbox="allow-scripts allow-popups" ובלי allow-modals,
    ולכן window.print() בתוכו הוא no-op שקט לפי המפרט;
  • קריאה ל-contentWindow.print() מבחוץ זורקת SecurityError (origin אטום);
  • pywebview רץ עם debug=False, שמכבה גם את Ctrl+P וגם את תפריט ההקשר,
    ואין לו API הדפסה משלו.
לכן: כותבים קובץ ומוסרים אותו ל-os.startfile, בדיוק כמו "פתח תיקיית נתונים".
אין להוסיף allow-modals ל-iframe כדי "לתקן" את זה — זה היה נותן alert/confirm/print
לכל דוח שמקורו בפורום.

פרטיות: הגיליון לא מכיל שום הפניה חיצונית. תמונת פרופיל נכנסת רק אם היא
data:image (העלאה של המשתמש); avatar_url מרוחק מודפס כטקסט ולעולם לא כ-src,
אחרת עצם ההדפסה הייתה מודיעה לפורום שאספת תיק על המשתמש הזה.
"""
import re
import html

# שדות שלא נדפסים אלא אם המשתמש ביקש במפורש. get_merged_profile מחזיר את
# private_notes בתוך fields, ולכן לא מספיק לסנן את מקטע ההערות בלבד.
PRIVATE_FIELDS = {"private_notes"}

MAX_MEMBERS = 200
MAX_HISTORY = 200
MAX_AVATAR_CHARS = 400_000

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$|^[a-zA-Z]{3,20}$")


def _esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def _css_color(v, fallback="#8b90a0"):
    """
    nick_color מגיע מהפורום. esc() מונע בריחה מהמאפיין, אבל ערך כמו
    'red;background-image:url(https://evil/x.png)' נשאר תקף בתוך אותו style
    והופך לבקשה חיצונית. כאן רק צבע מילולי או hex.
    """
    v = str(v or "").strip()
    return v if _COLOR_RE.match(v) else fallback


def _img_src(avatar_image):
    """רק data:image — בלי כתובות מרוחקות, ובלי תמונות ענק."""
    v = str(avatar_image or "").strip()
    if v.startswith("data:image/") and len(v) <= MAX_AVATAR_CHARS:
        return v
    return ""


_TEMPLATE = """<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  @page { size: A4; margin: 14mm 12mm; }
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI", Arial, sans-serif; color:#111; background:#fff;
         margin:0; font-size:12.5px; line-height:1.65; }
  .wrap { max-width: 186mm; margin: 0 auto; padding: 10px 0 30px; }
  h1 { font-size:21px; margin:0 0 2px; }
  .sub { color:#666; font-size:12px; margin-bottom:14px; }
  .sec { margin-top:18px; page-break-inside:avoid; }
  .sec > h2 { font-size:13px; margin:0 0 6px; padding-bottom:4px;
              border-bottom:1.5px solid #333; }
  table { width:100%; border-collapse:collapse; }
  td, th { text-align:right; vertical-align:top; padding:4px 6px;
           border-bottom:1px solid #e6e6e6; }
  th { width:26%; color:#555; font-weight:700; font-size:12px; }
  .src { color:#888; font-size:10.5px; }
  .chip { display:inline-block; padding:1px 7px; border-radius:9px;
          border:1px solid #ccc; font-size:11px; margin:0 0 3px 4px; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%;
         margin-left:5px; vertical-align:middle; }
  .ban { color:#b3261e; font-weight:700; }
  .avatar { width:52px; height:52px; border-radius:9px; object-fit:cover;
            border:1px solid #ddd; float:left; margin-right:10px; }
  .warn { color:#b3261e; font-weight:700; }
  .foot { margin-top:22px; padding-top:8px; border-top:1px solid #ddd;
          color:#777; font-size:10.5px; display:flex; justify-content:space-between; }
  .note { white-space:pre-wrap; }
  @media print { .noprint { display:none !important; } body { font-size:11.5px; } }
</style>
<script>window.onload = function () { try { window.print(); } catch (e) {} };</script>
</head><body><div class="wrap">
__AVATAR__
<h1>__HEADING__</h1>
<div class="sub">__SUBTITLE__</div>
__MEMBERS__
__FIELDS__
__CONTACTS__
__NOTES__
__HISTORY__
<div class="foot"><span>__FOOT_LEFT__</span><span>Tik-Nick · __DATE__</span></div>
</div></body></html>"""


def _table(rows):
    if not rows:
        return ""
    body = "".join(
        f"<tr><th>{_esc(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def build_sheet(data, include_private=False, include_history=True, generated=""):
    """
    data: {"nick":…, "members":[…], "fields":[…], "contacts":[…], "history":[…],
           "truncated_members":int, "truncated_history":int}
    מחזיר HTML מלא. כל ערך עובר _esc; ההחלפה בתבנית היא מעבר regex אחד, כך
    שטקסט של משתמש שמכיל '__FIELDS__' לא נסרק שוב (מלכודת שיש ב-stinknik).
    """
    nick = data.get("nick") or {}
    members = data.get("members") or []
    heading = nick.get("username", "")
    forums = sorted({m.get("forum", "") for m in members if m.get("forum")})
    subtitle = " · ".join(filter(None, [
        f"{len(members)} זהויות" if len(members) > 1 else nick.get("forum", ""),
        ", ".join(forums) if len(members) > 1 else "",
        nick.get("real_name", "") or "",
    ]))

    av = _img_src(nick.get("avatar_image"))
    avatar_html = f'<img class="avatar" src="{_esc(av)}" alt="">' if av else ""

    # ── חברי קבוצת הזהות ──
    members_html = ""
    if len(members) > 1:
        chips = []
        for m in members[:MAX_MEMBERS]:
            col = _css_color(m.get("nick_color"))
            ban = ' <span class="ban">🚫 מורחק</span>' if (m.get("status") or "") == "מורחק" else ""
            chips.append(
                f'<span class="chip"><span class="dot" style="background:{_esc(col)}"></span>'
                f'<b>{_esc(m.get("username"))}</b> <span class="src">{_esc(m.get("forum"))}</span>{ban}</span>')
        extra = ""
        if data.get("truncated_members"):
            extra = (f'<div class="src">מוצגות {MAX_MEMBERS} זהויות מתוך '
                     f'{_esc(data["truncated_members"])}.</div>')
        members_html = ('<div class="sec"><h2>זהויות מקושרות</h2>'
                        + "".join(chips) + extra + "</div>")

    # ── שדות, עם ייחוס למקור ──
    rows = []
    for f in data.get("fields") or []:
        if f.get("key") in PRIVATE_FIELDS and not include_private:
            continue
        vals = []
        for v in f.get("values") or []:
            src = ""
            if len(members) > 1:
                src = f' <span class="src">({_esc(v.get("forum"))} · {_esc(v.get("username"))})</span>'
            vals.append(f'<div>{_esc(v.get("value"))}{src}</div>')
        if vals:
            rows.append((f.get("label", f.get("key", "")), "".join(vals)))
    fields_html = f'<div class="sec"><h2>פרטים</h2>{_table(rows)}</div>' if rows else ""

    # ── אנשי קשר ──
    crows = []
    for c in data.get("contacts") or []:
        if c.get("is_private") and not include_private:
            continue
        kind = {"phone": "טלפון", "email": "מייל"}.get(c.get("type"), c.get("type", ""))
        label = f' <span class="src">{_esc(c.get("label"))}</span>' if c.get("label") else ""
        lock = ' <span class="warn">🔒</span>' if c.get("is_private") else ""
        crows.append((kind, f'{_esc(c.get("value"))}{label}{lock}'))
    contacts_html = (f'<div class="sec"><h2>טלפונים ומיילים נוספים</h2>{_table(crows)}</div>'
                     if crows else "")

    # ── הערות ──
    printed_keys = {f.get("key") for f in (data.get("fields") or [])}
    nrows = []
    if (nick.get("notes") or "").strip() and "notes" not in printed_keys:
        nrows.append(("הערות", f'<div class="note">{_esc(nick["notes"])}</div>'))
    if (include_private and (nick.get("private_notes") or "").strip()
            and "private_notes" not in printed_keys):
        nrows.append(("הערות אישיות 🔒",
                      f'<div class="note">{_esc(nick["private_notes"])}</div>'))
    notes_html = f'<div class="sec"><h2>הערות</h2>{_table(nrows)}</div>' if nrows else ""

    # ── ציר זמן ──
    history_html = ""
    hist = (data.get("history") or [])[:MAX_HISTORY] if include_history else []
    if hist:
        hrows = "".join(
            f'<tr><th>{_esc(str(h.get("changed_at", ""))[:16])}</th>'
            f'<td>{_esc(h.get("field_name"))}: '
            f'<span class="src">{_esc(h.get("old_value") or "—")}</span> ← '
            f'{_esc(h.get("new_value") or "—")}</td></tr>'
            for h in hist)
        more = ""
        if data.get("truncated_history"):
            more = (f'<div class="src">מוצגים {MAX_HISTORY} שינויים מתוך '
                    f'{_esc(data["truncated_history"])}.</div>')
        history_html = f'<div class="sec"><h2>ציר זמן</h2><table>{hrows}</table>{more}</div>'

    foot_left = ("⚠️ כולל הערות אישיות ואנשי קשר סודיים"
                 if include_private else "")

    values = {
        "TITLE": f"פרופיל · {heading}",
        "AVATAR": avatar_html,
        "HEADING": _esc(heading),
        "SUBTITLE": _esc(subtitle),
        "MEMBERS": members_html,
        "FIELDS": fields_html,
        "CONTACTS": contacts_html,
        "NOTES": notes_html,
        "HISTORY": history_html,
        "FOOT_LEFT": f'<span class="warn">{_esc(foot_left)}</span>' if foot_left else "",
        "DATE": _esc(generated),
    }
    # מעבר אחד: טקסט שהוחלף לא נסרק מחדש
    return re.sub(r"__([A-Z_]+)__", lambda m: values.get(m.group(1), ""), _TEMPLATE)
