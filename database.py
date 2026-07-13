"""
database.py - ניהול מסד נתונים SQLite לניקטרקר
"""
import sqlite3
import json
import os
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "tiknick.db")

# רשימת הפורומים המוכרים — מוצגת בניהול פורומים להוספה מהירה
# אין הוספה אוטומטית — המשתמש בוחר מה להוסיף
KNOWN_FORUMS = [
    {"name": "מתמחים טופ",      "color": "#5865f2", "url": "https://mitmachim.top"},
    {"name": "פורום בינה טופ",  "color": "#1abc9c", "url": "https://bina.top/"},
    {"name": "פורום בני ברק",   "color": "#9b59b6", "url": "https://bnebrak.com"},
    {"name": "פורום נודביבי",   "color": "#3498db", "url": "https://community.nodebb.org/"},
    {"name": "פורום אוצריא",    "color": "#e74c3c", "url": "https://otzaria.org/forum"},
    {"name": "פורום המוזיקאי",  "color": "#e67e22", "url": "https://hamusicay.com/"},
    {"name": "פורום המטבח",     "color": "#e91e8c", "url": "https://hamitbach.me/"},
    {"name": "פורום מקצב",      "color": "#00bcd4", "url": "https://miktzav.com/"},
    {"name": "פורום בנקל",      "color": "#8bc34a", "url": "https://forum.benakel.org/"},
    {"name": "פורום סייפר",     "color": "#ff5722", "url": "https://forum.safera.co.il/"},
    {"name": "פורום ידיים טובות","color": "#795548", "url": "https://diy-il.forum/"},
    {"name": "פורום תחומים",    "color": "#607d8b", "url": "https://tchumim.com/"},
    {"name": "פורום לתורה",     "color": "#2ecc71", "url": "https://tora-forum.co.il/"},
    {"name": "פורום המכלול",    "color": "#f39c12", "url": "https://forum.hamichlol.org.il"},
    {"name": "פורום ארבע אמות", "color": "#673ab7", "url": "https://arba-amot.ovh/"},
]

# כל שדות הניק וברירת המחדל שלהם לסנכרון (True = מסונכרן)
ALL_NICK_FIELDS = [
    ("forum",         "פורום",           True),
    ("username",      "שם משתמש",        True),
    ("real_name",     "שם אמיתי",        True),
    ("phone",         "טלפון",           True),
    ("email",         "מייל",            True),
    ("address",       "כתובת",           True),
    ("groups",        "קבוצות",          True),
    ("reputation",    "מוניטין",         True),
    ("status",        "סטטוס",           True),
    ("join_date",     "תאריך הצטרפות",   True),
    ("post_count",    "מספר הודעות",     True),
    ("notes",         "הערות",           True),
    ("extra_info",    "פרטים נוספים",    True),
    ("private_notes", "הערות אישיות",    False),  # ברירת מחדל: לא מסונכרן
    ("trust_level",   "רמת אמינות",      True),
    ("avatar_url",    "כתובת תמונה",     True),
    ("nick_color",    "צבע ניק",         True),
    ("avatar_image",  "תמונת פרופיל",    False),  # כבד — ברירת מחדל לא מסונכרן
]

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS forums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                color TEXT DEFAULT '#8b90a0',
                url TEXT DEFAULT '',
                profile_pattern TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 99
            );

            CREATE TABLE IF NOT EXISTS nicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                forum TEXT NOT NULL DEFAULT 'כללי',
                username TEXT NOT NULL,
                groups TEXT DEFAULT '',
                reputation INTEGER DEFAULT 0,
                real_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                email TEXT DEFAULT '',
                address TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                private_notes TEXT DEFAULT '',
                extra_info TEXT DEFAULT '',
                status TEXT DEFAULT 'פעיל',
                join_date TEXT DEFAULT '',
                post_count TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                nick_color TEXT DEFAULT '',
                avatar_image TEXT DEFAULT '',
                source TEXT DEFAULT 'manual',
                trust_level INTEGER DEFAULT 5,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS nick_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nick_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                value TEXT NOT NULL,
                label TEXT DEFAULT '',
                is_private INTEGER DEFAULT 0,
                FOREIGN KEY (nick_id) REFERENCES nicks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS nick_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nick_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                conflicting_value TEXT NOT NULL,
                source_info TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (nick_id) REFERENCES nicks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS nick_identities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nick_id_a INTEGER NOT NULL,
                nick_id_b INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (nick_id_a) REFERENCES nicks(id) ON DELETE CASCADE,
                FOREIGN KEY (nick_id_b) REFERENCES nicks(id) ON DELETE CASCADE,
                UNIQUE(nick_id_a, nick_id_b)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS sync_settings (
                field_key TEXT PRIMARY KEY,
                synced INTEGER DEFAULT 1
            );

            -- אינדקסים לביצועים (חיוני כשיש עשרות אלפי ניקים)
            CREATE INDEX IF NOT EXISTS idx_nicks_username    ON nicks(username);
            CREATE INDEX IF NOT EXISTS idx_nicks_forum       ON nicks(forum);
            CREATE INDEX IF NOT EXISTS idx_nicks_updated_at  ON nicks(updated_at);
            CREATE INDEX IF NOT EXISTS idx_nicks_trust_level ON nicks(trust_level);
            CREATE INDEX IF NOT EXISTS idx_conflicts_nick_id ON nick_conflicts(nick_id);
            CREATE INDEX IF NOT EXISTS idx_contacts_nick_id  ON nick_contacts(nick_id);
            CREATE INDEX IF NOT EXISTS idx_identities_a      ON nick_identities(nick_id_a);
            CREATE INDEX IF NOT EXISTS idx_identities_b      ON nick_identities(nick_id_b);
        """)
        # "כללי" תמיד קיים — פורום ברירת המחדל לניקים לא משויכים
        conn.execute(
            "INSERT OR IGNORE INTO forums (name, color, url, sort_order) "
            "VALUES ('כללי', '#8b90a0', '', 0)")
        # שאר הפורומים — המשתמש מוסיף בעצמו מהרשימה המוכרת
        conn.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES
            ('export_version', '1'), ('user_identity', ''), ('trust_own_data', '1')
        """)
        # Seed sync_settings defaults
        for field_key, _, default_sync in ALL_NICK_FIELDS:
            conn.execute(
                "INSERT OR IGNORE INTO sync_settings (field_key, synced) VALUES (?,?)",
                (field_key, 1 if default_sync else 0))

    # Migrations for existing DBs
    _migrate()
    _init_fts()

FTS_AVAILABLE = False

def _init_fts():
    """
    מגדיר טבלת FTS5 (Full-Text Search) לחיפוש מהיר על עשרות אלפי ניקים.
    LIKE '%...%' על 9 עמודות דורש סריקה מלאה של הטבלה בכל חיפוש; FTS5 משתמש
    באינדקס מילים וממשיך להיות מהיר גם עם הרבה נתונים.
    אם הגרסה המקומית של SQLite לא כוללת FTS5 (נדיר), נופלים בחזרה לחיפוש LIKE הישן.
    """
    global FTS_AVAILABLE
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nicks_fts'"
        ).fetchone()
        if exists:
            FTS_AVAILABLE = True
            return
        fts_cols = "username, real_name, phone, email, notes, groups, forum, extra_info, private_notes"
        try:
            conn.executescript(f"""
                CREATE VIRTUAL TABLE nicks_fts USING fts5(
                    {fts_cols},
                    content='nicks', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TRIGGER nicks_fts_ai AFTER INSERT ON nicks BEGIN
                  INSERT INTO nicks_fts(rowid, {fts_cols})
                  VALUES (new.id, new.username, new.real_name, new.phone, new.email,
                          new.notes, new.groups, new.forum, new.extra_info, new.private_notes);
                END;
                CREATE TRIGGER nicks_fts_ad AFTER DELETE ON nicks BEGIN
                  INSERT INTO nicks_fts(nicks_fts, rowid, {fts_cols})
                  VALUES ('delete', old.id, old.username, old.real_name, old.phone, old.email,
                          old.notes, old.groups, old.forum, old.extra_info, old.private_notes);
                END;
                CREATE TRIGGER nicks_fts_au AFTER UPDATE ON nicks BEGIN
                  INSERT INTO nicks_fts(nicks_fts, rowid, {fts_cols})
                  VALUES ('delete', old.id, old.username, old.real_name, old.phone, old.email,
                          old.notes, old.groups, old.forum, old.extra_info, old.private_notes);
                  INSERT INTO nicks_fts(rowid, {fts_cols})
                  VALUES (new.id, new.username, new.real_name, new.phone, new.email,
                          new.notes, new.groups, new.forum, new.extra_info, new.private_notes);
                END;
            """)
            # מילוי חד-פעמי מהנתונים הקיימים בטבלה
            conn.execute("INSERT INTO nicks_fts(nicks_fts) VALUES('rebuild')")
            FTS_AVAILABLE = True
        except sqlite3.OperationalError:
            FTS_AVAILABLE = False

def _fts_match_query(search):
    """הופך מחרוזת חיפוש חופשית לביטוי MATCH בטוח (כל מילה כ-prefix, AND בין מילים)"""
    tokens = [t for t in search.strip().split() if t]
    if not tokens:
        return None
    parts = []
    for t in tokens:
        safe = t.replace('"', '""')
        parts.append(f'"{safe}"*')
    return " ".join(parts)

def _migrate():
    """הוסף עמודות חסרות ל-DB ישן"""
    with get_connection() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(nicks)")}
        for col in ["extra_info", "private_notes", "nick_color", "avatar_image", "address"]:
            if col not in existing:
                conn.execute(f"ALTER TABLE nicks ADD COLUMN {col} TEXT DEFAULT ''")
        ctcols = {row[1] for row in conn.execute("PRAGMA table_info(nick_contacts)")}
        if "is_private" not in ctcols:
            conn.execute("ALTER TABLE nick_contacts ADD COLUMN is_private INTEGER DEFAULT 0")
        # migration לפורומים
        fcols = {row[1] for row in conn.execute("PRAGMA table_info(forums)")}
        if "profile_pattern" not in fcols:
            conn.execute("ALTER TABLE forums ADD COLUMN profile_pattern TEXT DEFAULT ''")

# ── הגדרות סנכרון ────────────────────────────────────────────────────
def get_sync_settings():
    """מחזיר dict: field_key -> bool"""
    with get_connection() as conn:
        rows = conn.execute("SELECT field_key, synced FROM sync_settings").fetchall()
        result = {r[0]: bool(r[1]) for r in rows}
    # fill defaults for any missing
    for key, _, default in ALL_NICK_FIELDS:
        if key not in result:
            result[key] = default
    return result

def set_sync_setting(field_key, synced: bool):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_settings (field_key, synced) VALUES (?,?)",
            (field_key, 1 if synced else 0))

def get_exportable_fields():
    """מחזיר רשימת שדות שמסונכרנים לפי ההגדרות הנוכחיות"""
    sync = get_sync_settings()
    return [k for k, _, _ in ALL_NICK_FIELDS if sync.get(k, True)]

# ── פורומים ─────────────────────────────────────────────────────────
def get_known_forums():
    """רשימת כל הפורומים המוכרים — תמיד מלאה, ללא תלות במה שקיים במסד"""
    return list(KNOWN_FORUMS)

def get_known_forum_by_name(name):
    """חיפוש פורום מוכר לפי שם מדויק"""
    name_lower = name.strip().lower()
    for f in KNOWN_FORUMS:
        if f["name"].lower() == name_lower:
            return f
    return None

def resolve_forum_data(name, color=None, url=None):
    """
    נסה למצוא נתוני פורום מ-KNOWN_FORUMS לפי שם.
    אם נמצא — השלם ערכים חסרים. אחרת — השתמש בערכים שסופקו.
    """
    known = get_known_forum_by_name(name)
    if known:
        return {
            "name":  known["name"],
            "color": color if color and color != "#8b90a0" else known["color"],
            "url":   url if url else known["url"],
        }
    return {
        "name":  name,
        "color": color or "#8b90a0",
        "url":   url or "",
    }

def get_forums():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM forums ORDER BY sort_order, name").fetchall()
        return [dict(r) for r in rows]

def get_forum_colors():
    return {f["name"]: f["color"] for f in get_forums()}

def get_forum_names():
    return [f["name"] for f in get_forums()]

def add_forum(name, color="#8b90a0", url=""):
    """מוסיף פורום — משלים צבע/URL מ-KNOWN_FORUMS אם חסרים"""
    resolved = resolve_forum_data(name, color, url)
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO forums (name, color, url) VALUES (?,?,?)",
                     (resolved["name"], resolved["color"], resolved["url"]))

def update_forum(forum_id, name, color, url=""):
    with get_connection() as conn:
        old_row = conn.execute("SELECT name FROM forums WHERE id=?", (forum_id,)).fetchone()
        old_name = old_row[0] if old_row else None
        conn.execute("UPDATE forums SET name=?, color=?, url=? WHERE id=?",
                     (name, color, url, forum_id))
        if old_name and old_name != name:
            conn.execute("UPDATE nicks SET forum=? WHERE forum=?", (name, old_name))

def count_nicks_in_forum(forum_id):
    """מחזיר (count, name) של ניקים בפורום"""
    with get_connection() as conn:
        row = conn.execute("SELECT name FROM forums WHERE id=?", (forum_id,)).fetchone()
        if not row: return 0, ""
        name = row[0]
        count = conn.execute("SELECT COUNT(*) FROM nicks WHERE forum=?", (name,)).fetchone()[0]
        return count, name

def delete_forum(forum_id, move_to_general=True):
    """מוחק פורום. אם move_to_general=True מעביר ניקים ל-כללי"""
    with get_connection() as conn:
        row = conn.execute("SELECT name FROM forums WHERE id=?", (forum_id,)).fetchone()
        if not row: return
        name = row[0]
        if name == "כללי":
            return  # פורום ברירת המחדל — לא ניתן למחיקה
        if move_to_general:
            exists = conn.execute("SELECT id FROM forums WHERE name='כללי'").fetchone()
            if not exists:
                conn.execute("INSERT OR IGNORE INTO forums (name,color,url) VALUES ('כללי','#8b90a0','')")
            conn.execute("UPDATE nicks SET forum='כללי' WHERE forum=?", (name,))
        conn.execute("DELETE FROM forums WHERE id=?", (forum_id,))

# ── ניקים ────────────────────────────────────────────────────────────
def get_all_nicks(search="", limit=None, offset=0):
    """
    מחזיר dict: {"rows": [...], "total": N}.
    limit=None (ברירת מחדל) מחזיר הכל, לתאימות אחורה עם קריאות ישנות.
    """
    with get_connection() as conn:
        base_select = """
            SELECT n.*,
                (SELECT COUNT(*) FROM nick_conflicts c WHERE c.nick_id = n.id) as conflict_count,
                CASE WHEN (n.real_name != '' OR n.phone != '' OR n.email != ''
                           OR n.notes != '' OR n.extra_info != '') THEN 1 ELSE 0 END as has_info,
                (SELECT COUNT(*) FROM nick_identities i
                 WHERE i.nick_id_a=n.id OR i.nick_id_b=n.id) as has_identity,
                (SELECT COUNT(*) FROM nick_contacts ct WHERE ct.nick_id=n.id) as extra_contacts
            FROM nicks n
        """
        order_clause = "ORDER BY has_info DESC, n.trust_level DESC, n.updated_at DESC"
        limit_clause = ""
        params_extra = []
        if limit is not None:
            limit_clause = "LIMIT ? OFFSET ?"
            params_extra = [limit, offset]

        match_expr = _fts_match_query(search) if search else None

        if match_expr and FTS_AVAILABLE:
            total = conn.execute(
                "SELECT COUNT(*) FROM nicks_fts WHERE nicks_fts MATCH ?", (match_expr,)
            ).fetchone()[0]
            rows = conn.execute(
                base_select + f"""
                WHERE n.id IN (SELECT rowid FROM nicks_fts WHERE nicks_fts MATCH ?)
                {order_clause} {limit_clause}
            """, [match_expr] + params_extra).fetchall()
        elif search:
            # נפילה חזרה לחיפוש LIKE (למקרה שאין תמיכת FTS5 בסביבה)
            s = f"%{search}%"
            where = """
                WHERE n.username LIKE ? OR n.real_name LIKE ? OR n.phone LIKE ?
                   OR n.email LIKE ? OR n.notes LIKE ? OR n.groups LIKE ?
                   OR n.forum LIKE ? OR n.extra_info LIKE ? OR n.private_notes LIKE ?
            """
            total = conn.execute(
                f"SELECT COUNT(*) FROM nicks n {where}", (s,) * 9
            ).fetchone()[0]
            rows = conn.execute(
                base_select + where + f" {order_clause} {limit_clause}",
                (s,) * 9 + tuple(params_extra)
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) FROM nicks").fetchone()[0]
            rows = conn.execute(
                base_select + f"{order_clause} {limit_clause}", params_extra
            ).fetchall()

        return {"rows": [dict(r) for r in rows], "total": total}

def get_nick(nick_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM nicks WHERE id=?", (nick_id,)).fetchone()
        return dict(row) if row else None

_NICK_FIELDS = ["forum","username","groups","reputation","real_name","phone","email",
                "notes","private_notes","extra_info","address","status","join_date","post_count",
                "avatar_url","nick_color","avatar_image","source","trust_level"]

def create_nick(data):
    vals = [data.get(f, '') for f in _NICK_FIELDS]
    ph   = ",".join(["?"]*len(_NICK_FIELDS))
    with get_connection() as conn:
        cur = conn.execute(
            f"INSERT INTO nicks ({','.join(_NICK_FIELDS)}) VALUES ({ph})", vals)
        return cur.lastrowid

def update_nick(nick_id, data):
    upd_fields = [f for f in _NICK_FIELDS if f != "source"]
    set_clause = ", ".join([f"{f}=?" for f in upd_fields]) + ", updated_at=datetime('now')"
    vals = [data.get(f, '') for f in upd_fields] + [nick_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE nicks SET {set_clause} WHERE id=?", vals)

def delete_nick(nick_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM nicks WHERE id=?", (nick_id,))

def delete_nicks(nick_ids):
    """מחיקה מרובה — מוחק בפועל את הניקים שנבחרו (לא רק מרוקן עמודות)"""
    ids = [int(i) for i in (nick_ids or [])]
    if not ids:
        return 0
    with get_connection() as conn:
        ph = ",".join(["?"] * len(ids))
        cur = conn.execute(f"DELETE FROM nicks WHERE id IN ({ph})", ids)
        return cur.rowcount

def reset_all():
    with get_connection() as conn:
        conn.execute("DELETE FROM nicks")
        conn.execute("DELETE FROM nick_conflicts")
        conn.execute("DELETE FROM nick_contacts")
        conn.execute("DELETE FROM nick_identities")

def reset_columns(columns):
    """מאפס (מרוקן) ערכים בעמודות ספציפיות בכל הניקים, בלי למחוק שורות"""
    resettable = [f for f in _NICK_FIELDS if f not in ("username",)]
    cols = [col for col in columns if col in resettable]
    if not cols:
        return 0
    with get_connection() as conn:
        # defaults: reputation/trust_level numeric, forum → כללי
        sets = []
        for col in cols:
            if col == "reputation":
                sets.append("reputation=0")
            elif col == "trust_level":
                sets.append("trust_level=5")
            elif col == "forum":
                sets.append("forum='כללי'")
            elif col == "status":
                sets.append("status='פעיל'")
            else:
                sets.append(f"{col}=''")
        conn.execute(f"UPDATE nicks SET {', '.join(sets)}, updated_at=datetime('now')")
        return len(cols)

def reset_settings_only():
    """מאפס רק הגדרות (תצוגה, סנכרון) — לא נתונים"""
    with get_connection() as conn:
        conn.execute("DELETE FROM settings WHERE key LIKE 'display_%'")
        conn.execute("DELETE FROM sync_settings")

# ── אנשי קשר נוספים ──────────────────────────────────────────────────
def get_contacts(nick_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM nick_contacts WHERE nick_id=? ORDER BY type, id",
            (nick_id,)).fetchall()
        return [dict(r) for r in rows]

def add_contact(nick_id, ctype, value, label="", is_private=0):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO nick_contacts (nick_id, type, value, label, is_private) VALUES (?,?,?,?,?)",
            (nick_id, ctype, value, label, 1 if is_private else 0))

def update_contact(contact_id, ctype, value, label="", is_private=0):
    with get_connection() as conn:
        conn.execute(
            "UPDATE nick_contacts SET type=?, value=?, label=?, is_private=? WHERE id=?",
            (ctype, value, label, 1 if is_private else 0, contact_id))

def get_contact(contact_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM nick_contacts WHERE id=?", (contact_id,)).fetchone()
        return dict(row) if row else None

def delete_contact(contact_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM nick_contacts WHERE id=?", (contact_id,))

# ── התנגשויות ────────────────────────────────────────────────────────
def get_conflicts(nick_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM nick_conflicts WHERE nick_id=? ORDER BY created_at DESC",
            (nick_id,)).fetchall()
        return [dict(r) for r in rows]

def delete_conflict(conflict_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM nick_conflicts WHERE id=?", (conflict_id,))

# ── זהויות כפולות ─────────────────────────────────────────────────
def get_identities(nick_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT n.id, n.username, n.forum FROM nicks n
            WHERE n.id IN (
                SELECT CASE WHEN nick_id_a=? THEN nick_id_b ELSE nick_id_a END
                FROM nick_identities WHERE nick_id_a=? OR nick_id_b=?
            )
        """, (nick_id, nick_id, nick_id)).fetchall()
        return [dict(r) for r in rows]

def add_identity(nick_id_a, nick_id_b):
    if nick_id_a == nick_id_b:
        return
    a, b = min(nick_id_a, nick_id_b), max(nick_id_a, nick_id_b)
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO nick_identities (nick_id_a, nick_id_b) VALUES (?,?)",
                (a, b))
        except Exception:
            pass

def remove_identity(nick_id_a, nick_id_b):
    a, b = min(nick_id_a, nick_id_b), max(nick_id_a, nick_id_b)
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM nick_identities WHERE nick_id_a=? AND nick_id_b=?", (a, b))

# ── הגדרות תצוגה ─────────────────────────────────────────────────────
DEFAULT_DISPLAY = {
    "theme":        "dark",     # dark | light | system
    "accent":       "amber",     # teal|indigo|emerald|sky|violet|amber|rose|slate
    "view":         "table",    # table | cards
    "density":      "normal",   # compact | normal | cozy
    "hidden_cols":  "",         # comma-separated column keys
}

def get_display_settings():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'display_%'").fetchall()
    result = dict(DEFAULT_DISPLAY)
    for k, v in rows:
        result[k.replace("display_", "")] = v
    return result

def set_display_setting(key, value):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
            (f"display_{key}", str(value)))

def reset_display_settings():
    with get_connection() as conn:
        conn.execute("DELETE FROM settings WHERE key LIKE 'display_%'")

# ── ייצוא / ייבוא ────────────────────────────────────────────────────
def export_data():
    exportable = get_exportable_fields()
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM nicks").fetchall()
    records = []
    for r in rows:
        d = dict(r)
        records.append({f: d.get(f, '') for f in exportable})
    return {
        "version": 2,
        "exported_at": datetime.now().isoformat(),
        "exported_fields": exportable,
        "nicks": records,
    }

def get_unknown_forums_in_data(data):
    """מחזיר שמות פורומים בקובץ הייבוא שאינם קיימים במסד"""
    existing = set(get_forum_names())
    incoming = {n.get("forum","").strip() for n in data.get("nicks",[]) if n.get("forum","").strip()}
    return sorted(incoming - existing)

def import_data(data, source_info="ייבוא חיצוני", forum_mapping=None):
    """
    forum_mapping: dict {שם_ישן: שם_חדש} — ממיר פורומים לא מוכרים לפורומים קיימים.
    אם None — מוסיף פורומים חדשים אוטומטית.
    """
    imported = 0; conflicts = 0
    exported_fields = data.get("exported_fields", get_exportable_fields())
    mapping = forum_mapping or {}
    with get_connection() as conn:
        # וודא שפורומים חדשים נוצרים (אם לא ממוזגים)
        existing_forums = {row[0] for row in conn.execute("SELECT name FROM forums")}
        for nick in data.get("nicks", []):
            forum_raw = nick.get("forum","").strip()
            mapped    = mapping.get(forum_raw, "")
            # ריק = לא ממוזג → השתמש בשם המקורי
            forum     = mapped if mapped else forum_raw
            if forum and forum not in existing_forums:
                conn.execute("INSERT OR IGNORE INTO forums (name,color,url) VALUES (?,?,'')",
                             (forum, "#8b90a0"))
                existing_forums.add(forum)

        for nick in data.get("nicks", []):
            username  = nick.get("username","").strip()
            forum_raw = nick.get("forum","").strip()
            mapped    = mapping.get(forum_raw, "")
            forum     = mapped if mapped else forum_raw
            if not username: continue
            existing = conn.execute(
                "SELECT * FROM nicks WHERE username=? AND forum=?",
                (username, forum)).fetchone()
            if existing:
                ex = dict(existing)
                for field in exported_fields:
                    if field in ("username","forum","trust_level","source"): continue
                    new_val = nick.get(field,"")
                    old_val = ex.get(field,"")
                    if new_val and str(new_val) != str(old_val) and old_val:
                        conn.execute("""
                            INSERT INTO nick_conflicts
                            (nick_id, field_name, conflicting_value, source_info)
                            VALUES (?,?,?,?)""",
                            (ex["id"], field, str(new_val), source_info))
                        conflicts += 1
                    elif new_val and not old_val:
                        conn.execute(f"UPDATE nicks SET {field}=? WHERE id=?",
                                     (new_val, ex["id"]))
            else:
                d = {f: nick.get(f,'') for f in exported_fields}
                d["forum"]      = forum
                d["source"]     = source_info
                d["trust_level"]= min(int(nick.get("trust_level",3) or 3), 4)
                # inline insert — no nested connection
                vals = [d.get(f, '') for f in _NICK_FIELDS]
                ph   = ",".join(["?"]*len(_NICK_FIELDS))
                conn.execute(
                    f"INSERT INTO nicks ({','.join(_NICK_FIELDS)}) VALUES ({ph})", vals)
                imported += 1
    return imported, conflicts
