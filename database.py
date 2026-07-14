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
    ("full_name",     "שם מלא",          True),
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
                full_name TEXT DEFAULT '',
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
                forum_uid TEXT DEFAULT '',
                scraped_real_name TEXT DEFAULT '',
                scraped_email TEXT DEFAULT '',
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

            -- לוג ייבואים: כל ייבוא קובץ נרשם כאן עם שם, הערות, דרגת אמינות
            CREATE TABLE IF NOT EXISTS import_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                trust INTEGER DEFAULT 5,
                nick_count INTEGER DEFAULT 0,
                conflict_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- ערכים סותרים שנשמרו בצד (המנצח בטבלת nicks; המפסיד כאן, לריחוף)
            CREATE TABLE IF NOT EXISTS shelved_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nick_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                value TEXT NOT NULL,
                source_name TEXT DEFAULT '',
                source_trust INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (nick_id) REFERENCES nicks(id) ON DELETE CASCADE
            );

            -- מקורות מידע ("אבות"): אני, סריקת אינטרנט, וכל ייבוא קובץ
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,            -- 'me' | 'scrape' | 'import'
                name TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                trust INTEGER DEFAULT 5,       -- 1..10 (מתעלמים אם absolute=1)
                absolute INTEGER DEFAULT 0,    -- 1 = תמיד מנצח, בלי ערך מספרי
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- כל ערך שהגיע אי-פעם לכל שדה של כל ניק, עם המקור שלו.
            -- הערך המוצג ב-nicks נגזר מכאן (הכי אמין מנצח).
            CREATE TABLE IF NOT EXISTS field_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nick_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                value TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (nick_id) REFERENCES nicks(id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
                UNIQUE(nick_id, field_name, source_id)
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
            CREATE INDEX IF NOT EXISTS idx_shelved_nick_id   ON shelved_values(nick_id);
            CREATE INDEX IF NOT EXISTS idx_fv_nick           ON field_values(nick_id);
            CREATE INDEX IF NOT EXISTS idx_fv_source         ON field_values(source_id);
        """)
        # מקור ברירת מחדל: "אני" (id יציב דרך kind='me')
        conn.execute(
            "INSERT OR IGNORE INTO sources (id, kind, name, trust, absolute) "
            "VALUES (1, 'me', 'אני', 10, 0)")
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
        for col in ["extra_info", "private_notes", "nick_color", "avatar_image", "address",
                    "scraped_real_name", "scraped_email", "full_name", "forum_uid"]:
            if col not in existing:
                conn.execute(f"ALTER TABLE nicks ADD COLUMN {col} TEXT DEFAULT ''")
        ctcols = {row[1] for row in conn.execute("PRAGMA table_info(nick_contacts)")}
        if "is_private" not in ctcols:
            conn.execute("ALTER TABLE nick_contacts ADD COLUMN is_private INTEGER DEFAULT 0")
        # migration לפורומים
        fcols = {row[1] for row in conn.execute("PRAGMA table_info(forums)")}
        if "profile_pattern" not in fcols:
            conn.execute("ALTER TABLE forums ADD COLUMN profile_pattern TEXT DEFAULT ''")
        # ניקוי חד-פעמי: העברת 'uid:...' שנשמר בעבר ב-extra_info אל forum_uid
        try:
            rows = conn.execute(
                "SELECT id, extra_info FROM nicks WHERE extra_info LIKE 'uid:%'").fetchall()
            for rid, ei in rows:
                uid = str(ei).split("uid:", 1)[1].strip() if "uid:" in str(ei) else ""
                conn.execute(
                    "UPDATE nicks SET forum_uid=?, extra_info='' WHERE id=?", (uid, rid))
        except sqlite3.OperationalError:
            pass

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
                CASE WHEN (
                       n.phone != '' OR n.notes != '' OR n.private_notes != ''
                       OR n.real_name != ''
                       OR (n.email != '' AND n.email != n.scraped_email)
                       OR EXISTS (SELECT 1 FROM nick_contacts ct WHERE ct.nick_id = n.id)
                       OR EXISTS (SELECT 1 FROM nick_identities i
                                  WHERE i.nick_id_a = n.id OR i.nick_id_b = n.id)
                     ) THEN 1 ELSE 0 END as has_info,
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

def find_nick(forum, username):
    """מאתר ניק קיים לפי פורום+שם משתמש (למניעת כפילויות בסריקה חוזרת)"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM nicks WHERE forum=? AND username=? LIMIT 1",
            (forum, username)
        ).fetchone()
        return dict(row) if row else None

# שדות שממוזגים מסריקה (לא נוגעים ב-private_notes/real_name של המשתמש)
_SCRAPE_MERGE_FIELDS = ["groups", "reputation", "full_name", "email", "address",
                        "status", "join_date", "post_count", "avatar_url",
                        "nick_color", "avatar_image", "extra_info", "forum_uid"]

def merge_scraped_nick(forum, username, scraped, source_label="סריקה"):
    """
    ממזג ניק שנסרק — כל ערך נרשם תחת מקור 'סריקת אינטרנט' דרך מנוע המקורות.
    הערך המנצח בכל שדה נקבע אוטומטית לפי אמינות (כולל הכללים המיוחדים
    למוניטין ולסטטוס ב-resolve_field).
    מחזיר: ('created'|'updated'|'unchanged', nick_id, 0)  — אין עוד "התנגשויות" ידניות בסריקה.
    """
    existing = find_nick(forum, username)
    with get_connection() as conn:
        srow = conn.execute("SELECT * FROM sources WHERE kind='scrape' LIMIT 1").fetchone()
        if not srow:
            conn.execute("INSERT INTO sources (kind,name,trust,absolute) VALUES ('scrape','סריקת אינטרנט',9,0)")
            srow = conn.execute("SELECT * FROM sources WHERE kind='scrape' LIMIT 1").fetchone()
        scrape_sid = srow["id"]

    if not existing:
        data = {"forum": forum, "username": username, "source": source_label, "trust_level": 4}
        data["scraped_email"] = scraped.get("email", "") or ""
        nid = create_nick(data)
        action = "created"
    else:
        nid = existing["id"]
        action = "unchanged"

    changed = False
    for f in _SCRAPE_MERGE_FIELDS:
        new_val = scraped.get(f, "")
        if new_val in (None, ""):
            continue
        record_field_value(nid, f, new_val, scrape_sid)
        changed = True

    if action == "created":
        return ("created", nid, 0)
    return ("updated" if changed else "unchanged", nid, 0)

_NICK_FIELDS = ["forum","username","groups","reputation","real_name","full_name","phone","email",
                "notes","private_notes","extra_info","address","status","join_date","post_count",
                "avatar_url","nick_color","avatar_image","source","forum_uid","scraped_real_name",
                "scraped_email","trust_level"]

def create_nick(data):
    vals = [data.get(f, '') for f in _NICK_FIELDS]
    ph   = ",".join(["?"]*len(_NICK_FIELDS))
    with get_connection() as conn:
        cur = conn.execute(
            f"INSERT INTO nicks ({','.join(_NICK_FIELDS)}) VALUES ({ph})", vals)
        nid = cur.lastrowid
    # רשום ערכים ידניים תחת מקור "אני" (source_id=1)
    for f in _NICK_FIELDS:
        if f in _NON_SOURCED:
            continue
        v = data.get(f, "")
        if v not in (None, ""):
            record_field_value(nid, f, v, 1)
    return nid

def update_nick(nick_id, data):
    upd_fields = [f for f in _NICK_FIELDS if f != "source"]
    set_clause = ", ".join([f"{f}=?" for f in upd_fields]) + ", updated_at=datetime('now')"
    vals = [data.get(f, '') for f in upd_fields] + [nick_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE nicks SET {set_clause} WHERE id=?", vals)
    # רשום ערכים ידניים תחת מקור "אני" (source_id=1); ערך ריק מוחק את התרומה שלי
    for f in upd_fields:
        if f in _NON_SOURCED:
            continue
        v = data.get(f, "")
        if v not in (None, ""):
            record_field_value(nick_id, f, v, 1)
        else:
            # ריקון ידני → הסר את הערך שלי מהמקור, ואז הכרע מחדש
            with get_connection() as conn:
                conn.execute("DELETE FROM field_values WHERE nick_id=? AND field_name=? AND source_id=1",
                             (nick_id, f))
            resolve_field(nick_id, f)

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

def get_all_conflicts():
    """כל ההתנגשויות במאגר, עם שם הניק והערך הנוכחי בשדה — לפותר ההתנגשויות הגלובלי"""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT c.*, n.username, n.forum
            FROM nick_conflicts c JOIN nicks n ON n.id = c.nick_id
            ORDER BY c.created_at DESC
        """).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # הערך הנוכחי בשדה (הצד ה"קיים" של ההתנגשות)
            cur = conn.execute(
                f"SELECT {d['field_name']} AS v FROM nicks WHERE id=?", (d['nick_id'],)
            ).fetchone()
            d['current_value'] = cur['v'] if cur else ''
            out.append(d)
        return out

def apply_conflict(conflict_id):
    """מחיל את הערך החדש (conflicting_value) על הניק, ומוחק את ההתנגשות."""
    with get_connection() as conn:
        c = conn.execute("SELECT * FROM nick_conflicts WHERE id=?", (conflict_id,)).fetchone()
        if not c:
            return False
        c = dict(c)
        field = c['field_name']
        if field in _NICK_FIELDS and field not in ('id', 'forum', 'username'):
            conn.execute(
                f"UPDATE nicks SET {field}=?, updated_at=datetime('now') WHERE id=?",
                (c['conflicting_value'], c['nick_id'])
            )
        conn.execute("DELETE FROM nick_conflicts WHERE id=?", (conflict_id,))
        return True

def resolve_all_conflicts(prefer):
    """
    פותר את כל ההתנגשויות בבת אחת.
    prefer='new'      → מחיל את כל הערכים החדשים.
    prefer='existing' → שומר על הקיים (רק מוחק את ההתנגשויות).
    מחזיר כמה נפתרו.
    """
    with get_connection() as conn:
        ids = [r['id'] for r in conn.execute("SELECT id FROM nick_conflicts").fetchall()]
    n = 0
    for cid in ids:
        if prefer == 'new':
            apply_conflict(cid)
        else:
            delete_conflict(cid)
        n += 1
    return n

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

# ── הגדרה כללית (מפתח→ערך) ────────────────────────────────────────
def get_setting(key, default=""):
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

def set_setting(key, value):
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                     (key, str(value)))

# ── אילו פורומים ייכללו בייבוא/ייצוא בקובץ ─────────────────────────
# ברירת מחדל: כל הפורומים כלולים. נשמר רק מי שהוחרג (עם ערך '0').
def get_forum_io_flags():
    """מחזיר dict: forum_name -> bool (האם כלול בייבוא/ייצוא)"""
    forums = get_forums()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM settings WHERE key LIKE 'forumio_%'").fetchall()
    excluded = {k.replace("forumio_", ""): (v == "0") for k, v in rows}
    return {f["name"]: (not excluded.get(f["name"], False)) for f in forums}

def set_forum_io_flag(forum_name, included: bool):
    with get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                     (f"forumio_{forum_name}", "1" if included else "0"))

# ── ייצוא / ייבוא ────────────────────────────────────────────────────
def export_data():
    exportable = get_exportable_fields()
    io_flags = get_forum_io_flags()   # forum_name -> included?
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM nicks").fetchall()
    records = []
    for r in rows:
        d = dict(r)
        # דלג על פורומים שהוחרגו בהגדרות (סעיף 2)
        if io_flags.get(d.get("forum", ""), True) is False:
            continue
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

def get_my_trust():
    try:
        return int(get_setting("my_trust", "10"))
    except (ValueError, TypeError):
        return 10

def set_my_trust(val):
    v = max(1, min(10, int(val)))
    set_setting("my_trust", v)
    return v

# ══ מנוע מקורות (source attribution) ═══════════════════════════════════
# שדות שאינם מנוהלים דרך מקורות (מזהים/מבניים)
_NON_SOURCED = {"forum", "username", "source", "trust_level",
                "scraped_real_name", "scraped_email", "created_at", "updated_at"}
# שדות בעלי כלל מיוחד:
#   reputation → רק סריקה, והחדש תמיד מנצח
#   status     → סריקה מקבלת אמינות מלאה (absolute-כמו)

def _source_effective_trust(src):
    """מחזיר ערך השוואה: absolute → אינסוף, אחרת trust המספרי."""
    if src.get("absolute"):
        return 10**6
    return int(src.get("trust", 5))

def get_me_source_id():
    return 1  # מקור קבוע שנוצר ב-init

def get_scrape_source(conn=None):
    """מקור הסריקה — נוצר בפעם הראשונה. מחזיר dict."""
    own = conn is None
    if own: conn = get_connection().__enter__()
    try:
        row = conn.execute("SELECT * FROM sources WHERE kind='scrape' LIMIT 1").fetchone()
        if not row:
            conn.execute("INSERT INTO sources (kind,name,trust,absolute) VALUES ('scrape','סריקת אינטרנט',9,0)")
            row = conn.execute("SELECT * FROM sources WHERE kind='scrape' LIMIT 1").fetchone()
        return dict(row)
    finally:
        pass

def create_import_source(name, notes, trust, absolute=0):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO sources (kind,name,notes,trust,absolute) VALUES ('import',?,?,?,?)",
            (name or "ייבוא", notes or "", int(trust), 1 if absolute else 0))
        return cur.lastrowid

def get_sources():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
        return [dict(r) for r in rows]

def update_source(source_id, name=None, notes=None, trust=None, absolute=None):
    sets, vals = [], []
    if name is not None:     sets.append("name=?");     vals.append(name)
    if notes is not None:    sets.append("notes=?");    vals.append(notes)
    if trust is not None:    sets.append("trust=?");    vals.append(max(1, min(10, int(trust))))
    if absolute is not None: sets.append("absolute=?"); vals.append(1 if absolute else 0)
    if not sets:
        return
    vals.append(source_id)
    affected = set()
    with get_connection() as conn:
        conn.execute(f"UPDATE sources SET {', '.join(sets)} WHERE id=?", vals)
        rows = conn.execute(
            "SELECT DISTINCT nick_id, field_name FROM field_values WHERE source_id=?",
            (source_id,)).fetchall()
        affected = {(r[0], r[1]) for r in rows}
    for nid, fld in affected:
        resolve_field(nid, fld)

def delete_source(source_id):
    """מוחק מקור וכל הערכים שלו; מריץ הכרעה מחדש לשדות המושפעים."""
    if source_id == 1:
        return False  # לא מוחקים את "אני"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT nick_id, field_name FROM field_values WHERE source_id=?",
            (source_id,)).fetchall()
        affected = {(r[0], r[1]) for r in rows}
        conn.execute("DELETE FROM field_values WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    for nid, fld in affected:
        resolve_field(nid, fld)
    return True

def record_field_value(nick_id, field_name, value, source_id):
    """רושם/מעדכן ערך של שדה ממקור מסוים, ואז מכריע מחדש מי מנצח."""
    if field_name in _NON_SOURCED or value in (None, ""):
        return
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO field_values (nick_id, field_name, value, source_id)
            VALUES (?,?,?,?)
            ON CONFLICT(nick_id, field_name, source_id)
            DO UPDATE SET value=excluded.value, created_at=datetime('now')
        """, (nick_id, field_name, str(value), source_id))
    resolve_field(nick_id, field_name)

def resolve_field(nick_id, field_name):
    """
    מחשב מחדש את הערך המנצח לשדה ומעדכן את טבלת nicks (ה-cache).
    כללים מיוחדים:
      • reputation: רק ערך ממקור סריקה, והחדש ביותר מנצח.
      • status: מקור סריקה מקבל אמינות אבסולוטית.
    """
    if field_name in _NON_SOURCED:
        return
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT fv.value, fv.created_at, s.id AS sid, s.kind, s.trust, s.absolute
            FROM field_values fv JOIN sources s ON s.id = fv.source_id
            WHERE fv.nick_id=? AND fv.field_name=?
        """, (nick_id, field_name)).fetchall()
        rows = [dict(r) for r in rows]

        if not rows:
            winner = ""
        elif field_name == "reputation":
            scr = [r for r in rows if r["kind"] == "scrape"]
            pool = scr if scr else rows
            pool.sort(key=lambda r: r["created_at"], reverse=True)
            winner = pool[0]["value"]
        else:
            def score(r):
                eff = 10**6 if r["absolute"] else int(r["trust"])
                if field_name == "status" and r["kind"] == "scrape":
                    eff = 10**6  # סריקה = אמינות מלאה לסטטוס
                return (eff, r["created_at"])
            rows.sort(key=score, reverse=True)
            winner = rows[0]["value"]

        if field_name in _NICK_FIELDS:
            conn.execute(
                f"UPDATE nicks SET {field_name}=?, updated_at=datetime('now') WHERE id=?",
                (winner, nick_id))

def get_field_sources(nick_id, field_name):
    """כל הערכים שהגיעו לשדה, עם המקור והאמינות — לתצוגת 'אבות' בחלון הניק."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT fv.value, fv.created_at, s.id AS source_id, s.kind, s.name, s.trust, s.absolute
            FROM field_values fv JOIN sources s ON s.id = fv.source_id
            WHERE fv.nick_id=? AND fv.field_name=?
            ORDER BY s.absolute DESC, s.trust DESC
        """, (nick_id, field_name)).fetchall()
        return [dict(r) for r in rows]


def log_import_source(name, notes, trust, nick_count, conflict_count):
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO import_sources (name, notes, trust, nick_count, conflict_count)
               VALUES (?,?,?,?,?)""",
            (name or "ייבוא", notes or "", int(trust), nick_count, conflict_count))
        rid = cur.lastrowid
    # לוג טקסט שקט ליד ה-DB (המשתמש לא רואה אותו בממשק)
    try:
        from datetime import datetime as _dt
        logpath = os.path.join(os.path.dirname(DB_PATH), "import_log.txt")
        with open(logpath, "a", encoding="utf-8") as fh:
            fh.write(f"[{_dt.now().isoformat(timespec='seconds')}] "
                     f"מקור='{name}' אמינות={trust} ניקים={nick_count} "
                     f"ערכים={conflict_count} הערות='{notes}'\n")
    except Exception:
        pass
    return rid

def get_import_sources():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM import_sources ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

def get_shelved_values(nick_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM shelved_values WHERE nick_id=? ORDER BY source_trust DESC",
            (nick_id,)).fetchall()
        return [dict(r) for r in rows]

def promote_shelved(shelved_id):
    """מקדם ערך מהמדף לערך הפעיל; הערך הפעיל הקודם יורד למדף (הפיך)."""
    with get_connection() as conn:
        s = conn.execute("SELECT * FROM shelved_values WHERE id=?", (shelved_id,)).fetchone()
        if not s:
            return False
        s = dict(s)
        field = s["field_name"]
        if field not in _NICK_FIELDS or field in ("username", "forum"):
            return False
        cur = conn.execute(f"SELECT {field} AS v FROM nicks WHERE id=?", (s["nick_id"],)).fetchone()
        old_active = cur["v"] if cur else ""
        # כתוב את הערך מהמדף לפעיל
        conn.execute(f"UPDATE nicks SET {field}=?, updated_at=datetime('now') WHERE id=?",
                     (s["value"], s["nick_id"]))
        # הסר את הרשומה מהמדף
        conn.execute("DELETE FROM shelved_values WHERE id=?", (shelved_id,))
        # הורד את הערך הפעיל הקודם למדף (אם היה)
        if old_active not in (None, ""):
            conn.execute("""INSERT INTO shelved_values
                (nick_id, field_name, value, source_name, source_trust)
                VALUES (?,?,?,?,?)""",
                (s["nick_id"], field, str(old_active), "הערך הקודם שלי", get_my_trust()))
        return True

def import_data(data, source_info="ייבוא חיצוני", forum_mapping=None,
                import_name=None, import_notes="", import_trust=None, import_absolute=0):
    """
    ייבוא מבוסס-מקורות: נוצר מקור ייבוא אחד (שם/הערות/אמינות/אבסולוטי),
    וכל ערך מיובא נרשם תחתיו במנוע המקורות. הערך המנצח בכל שדה נקבע אוטומטית.
    מחזיר: (imported_new, values_recorded)
    """
    imported = 0; recorded = 0
    exported_fields = data.get("exported_fields", get_exportable_fields())
    mapping = forum_mapping or {}
    trust = get_my_trust() if import_trust is None else max(1, min(10, int(import_trust)))
    src_name = import_name or source_info
    import_sid = create_import_source(src_name, import_notes, trust, import_absolute)

    with get_connection() as conn:
        existing_forums = {row[0] for row in conn.execute("SELECT name FROM forums")}
        for nick in data.get("nicks", []):
            forum_raw = nick.get("forum","").strip()
            mapped    = mapping.get(forum_raw, "")
            forum     = mapped if mapped else forum_raw
            if forum and forum not in existing_forums:
                conn.execute("INSERT OR IGNORE INTO forums (name,color,url) VALUES (?,?,'')",
                             (forum, "#8b90a0"))
                existing_forums.add(forum)

    io_flags = get_forum_io_flags()
    for nick in data.get("nicks", []):
        username  = nick.get("username","").strip()
        forum_raw = nick.get("forum","").strip()
        mapped    = mapping.get(forum_raw, "")
        forum     = mapped if mapped else forum_raw
        if not username: continue
        if io_flags.get(forum, True) is False:
            continue
        existing = find_nick(forum, username)
        if existing:
            nid = existing["id"]
        else:
            nid = create_nick({"forum": forum, "username": username,
                               "source": src_name, "trust_level": 3})
            imported += 1
        # רשום כל שדה מיובא תחת מקור הייבוא
        for field in exported_fields:
            if field in _NON_SOURCED:
                continue
            val = nick.get(field, "")
            if val in (None, ""):
                continue
            record_field_value(nid, field, val, import_sid)
            recorded += 1

    # עדכן ספירות בלוג הייבוא (import_sources הישן, לתאימות)
    log_import_source(src_name, import_notes, trust, imported, recorded)
    return imported, recorded
