"""
database.py - ניהול מסד נתונים SQLite לניקטרקר
"""
import sqlite3
import json
import os
import threading
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "tiknick.db")

# רשימת הפורומים המוכרים — מוצגת בניהול פורומים להוספה מהירה.
# אין הוספה אוטומטית — המשתמש בוחר מה להוסיף.
# platform: 'nodebb' (ברירת מחדל) | 'discourse' — נתמכים לסריקה אוטומטית.
#           'xenforo'/'phpbb'/'custom' — אין API ציבורי לרשימת משתמשים, אין סריקה אוטומטית
#           (עדיין שימושי לארגון ניקים ולפתיחת פרופילים ידנית).
# profile_pattern: תבנית לבניית קישור פרופיל, עם {user}. אם חסר — נגזר לפי הפלטפורמה.
KNOWN_FORUMS = [
    {"name": "מתמחים טופ",       "color": "#5865f2", "url": "https://mitmachim.top"},
    {"name": "פורום בינה טופ",   "color": "#1abc9c", "url": "https://bina.top/"},
    {"name": "פורום בני ברק",    "color": "#9b59b6", "url": "https://bnebrak.com"},
    {"name": "פורום נודביבי",    "color": "#3498db", "url": "https://community.nodebb.org/"},
    {"name": "פורום אוצריא",     "color": "#e74c3c", "url": "https://otzaria.org/forum"},
    {"name": "פורום המוזיקאי",   "color": "#e67e22", "url": "https://hamusicay.com/"},
    {"name": "פורום המטבח",      "color": "#e91e8c", "url": "https://hamitbach.me/", "needs_login": True},
    {"name": "פורום מקצב",       "color": "#00bcd4", "url": "https://miktzav.com/"},
    {"name": "פורום בנקל",       "color": "#8bc34a", "url": "https://forum.benakel.org/"},
    {"name": "פורום סייפר",      "color": "#ff5722", "url": "https://forum.safera.co.il/"},
    {"name": "פורום ידיים טובות", "color": "#795548", "url": "https://diy-il.forum/"},
    {"name": "פורום תחומים",     "color": "#607d8b", "url": "https://tchumim.com/"},
    {"name": "פורום המכלול",     "color": "#f39c12", "url": "https://forum.hamichlol.org.il"},
    {"name": "פורום ארבע אמות",  "color": "#673ab7", "url": "https://arba-amot.ovh/"},
    {"name": "פורום גבאים",      "color": "#c0392b", "url": "https://forum-gabai.onrender.com/"},
    # ── נוספו ב-0.8.2 ──
    {"name": "פורום ימות המשיח", "color": "#16a085", "url": "https://f2.freeivr.co.il/"},
    {"name": "פורום נטפרי",      "color": "#2980b9", "url": "https://forum.netfree.link/"},
    {"name": "חרדים נעייס",      "color": "#455a64", "url": "https://charedim-neyes.onrender.com/"},
    # פלטפורמות ללא API ציבורי לרשימת משתמשים — לארגון ולפתיחת פרופילים בלבד
    {"name": "פורום לתורה",      "color": "#2ecc71", "url": "https://tora-forum.co.il/",
     "platform": "xenforo"},
    {"name": "פורום פרוג",       "color": "#d35400", "url": "https://www.prog.co.il/",
     "platform": "xenforo"},
    {"name": "פורום אוצר התורה", "color": "#7f8c8d", "url": "https://forum-otzar-hatorah.co.il/",
     "platform": "xenforo"},
    {"name": "פורום אוצר החכמה", "color": "#a04000", "url": "https://forum.otzar.org/",
     "platform": "phpbb", "profile_pattern": "/memberlist.php?mode=viewprofile&un={user}"},
    {"name": "פורום אייוועלט",   "color": "#1f618d", "url": "https://www.ivelt.com/forum/",
     "platform": "phpbb", "profile_pattern": "/memberlist.php?mode=viewprofile&un={user}"},
    {"name": "פורום בחדרי חרדים", "color": "#616a6b", "url": "https://forums.bhol.co.il/forums/",
     "platform": "custom"},
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

_local = threading.local()

def get_connection():
    """
    מחזיר חיבור SQLite לשימוש חוזר לכל thread.
    פתיחת חיבור חדש בכל קריאה (כולל 2 PRAGMA) עלתה ~7ms — מה שהצטבר לשניות
    בכל פעולה שעושה הרבה קריאות קטנות. חיבור אחד per-thread מוריד זאת כמעט לאפס.
    sqlite3 אינו בטוח לשיתוף בין threads, ולכן thread-local (הסריקה רצה ב-thread נפרד).
    אם DB_PATH השתנה (בדיקות / אתחול) — נסגר הישן ונפתח חדש.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == DB_PATH:
        return conn
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _local.conn = conn
    _local.path = DB_PATH
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
                platform TEXT DEFAULT 'nodebb',
                sort_order INTEGER DEFAULT 99
            );

            -- עוגיות התחברות שמורות, מסווגות לפי דומיין (origin) של הפורום.
            -- כך אותה עוגייה משמשת סריקה, Chazonishnik ו-Stinknik של אותו אתר.
            CREATE TABLE IF NOT EXISTS forum_cookies (
                origin TEXT PRIMARY KEY,
                cookie TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now'))
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
            CREATE INDEX IF NOT EXISTS idx_fv_nick_field     ON field_values(nick_id, field_name);
            -- קריטי: בלי אינדקס דו-עמודתי המתכנן בוחר את idx_fv_source, ומכיוון
            -- שמקור הסריקה מחזיק כמעט את כל השורות — כל שליפה סורקת את כל הטבלה.
            CREATE INDEX IF NOT EXISTS idx_fv_nick_source    ON field_values(nick_id, source_id);
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
    _backfill_sources()
    # בלי סטטיסטיקות (sqlite_stat1) המתכנן בוחר אינדקסים לפי ניחוש ברירת מחדל,
    # ועלול לבחור אינדקס גרוע בטבלאות גדולות. PRAGMA optimize מייצר/מרענן אותן בזול.
    try:
        with get_connection() as conn:
            conn.execute("PRAGMA optimize")
    except Exception:
        pass

FTS_AVAILABLE = False

# העמודות שנסרקות בחיפוש המהיר (FTS + נפילת ה-LIKE) — מקור אמת יחיד
_SEARCH_COLS = ["username", "full_name", "real_name", "phone", "email", "address",
                "notes", "groups", "forum", "extra_info", "private_notes"]

def _init_fts():
    """
    מגדיר טבלת FTS5 (Full-Text Search) לחיפוש מהיר על עשרות אלפי ניקים.
    LIKE '%...%' על הרבה עמודות דורש סריקה מלאה של הטבלה בכל חיפוש; FTS5 משתמש
    באינדקס מילים וממשיך להיות מהיר גם עם הרבה נתונים.
    אם סכימת ה-FTS הקיימת ישנה (חסרות full_name/address) — נבנית מחדש אוטומטית.
    אם הגרסה המקומית של SQLite לא כוללת FTS5 (נדיר), נופלים בחזרה לחיפוש LIKE.
    """
    global FTS_AVAILABLE
    fts_cols = ", ".join(_SEARCH_COLS)
    new_vals = ", ".join(f"new.{c}" for c in _SEARCH_COLS)
    old_vals = ", ".join(f"old.{c}" for c in _SEARCH_COLS)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='nicks_fts'"
        ).fetchone()
        if row and all(c in (row[0] or "") for c in _SEARCH_COLS):
            FTS_AVAILABLE = True
            return
        if row:
            # סכימה ישנה — מחק ובנה מחדש עם העמודות המלאות
            conn.executescript("""
                DROP TRIGGER IF EXISTS nicks_fts_ai;
                DROP TRIGGER IF EXISTS nicks_fts_ad;
                DROP TRIGGER IF EXISTS nicks_fts_au;
                DROP TABLE IF EXISTS nicks_fts;
            """)
        try:
            conn.executescript(f"""
                CREATE VIRTUAL TABLE nicks_fts USING fts5(
                    {fts_cols},
                    content='nicks', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TRIGGER nicks_fts_ai AFTER INSERT ON nicks BEGIN
                  INSERT INTO nicks_fts(rowid, {fts_cols})
                  VALUES (new.id, {new_vals});
                END;
                CREATE TRIGGER nicks_fts_ad AFTER DELETE ON nicks BEGIN
                  INSERT INTO nicks_fts(nicks_fts, rowid, {fts_cols})
                  VALUES ('delete', old.id, {old_vals});
                END;
                CREATE TRIGGER nicks_fts_au AFTER UPDATE ON nicks BEGIN
                  INSERT INTO nicks_fts(nicks_fts, rowid, {fts_cols})
                  VALUES ('delete', old.id, {old_vals});
                  INSERT INTO nicks_fts(rowid, {fts_cols})
                  VALUES (new.id, {new_vals});
                END;
            """)
            # מילוי חד-פעמי מהנתונים הקיימים בטבלה
            conn.execute("INSERT INTO nicks_fts(nicks_fts) VALUES('rebuild')")
            FTS_AVAILABLE = True
        except sqlite3.OperationalError:
            FTS_AVAILABLE = False

def _backfill_sources():
    """
    מיגרציה חד-פעמית: משייכת את כל ערכי הניקים הקיימים למקור "אני" (id=1),
    כדי שנתונים מלפני v0.5.0 ישתתפו בהכרעת המקורות ויציגו את סימן ⚠️.
    מוגן בדגל כדי לרוץ פעם אחת בלבד.
    """
    with get_connection() as conn:
        done = conn.execute(
            "SELECT value FROM settings WHERE key='backfill_sources_done'").fetchone()
        if done:
            return
        # ודא שקיים מקור "אני"
        conn.execute("INSERT OR IGNORE INTO sources (id,kind,name,trust,absolute) "
                     "VALUES (1,'me','אני',10,0)")
        sourced = [f for f in _NICK_FIELDS if f not in _NON_SOURCED]
        rows = conn.execute("SELECT id, " + ", ".join(sourced) + " FROM nicks").fetchall()
        for r in rows:
            d = dict(r)
            nid = d["id"]
            for f in sourced:
                v = d.get(f, "")
                if v not in (None, ""):
                    conn.execute("""INSERT OR IGNORE INTO field_values
                        (nick_id, field_name, value, source_id) VALUES (?,?,?,1)""",
                        (nid, f, str(v)))
        conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('backfill_sources_done','1')")

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
        if "platform" not in fcols:
            conn.execute("ALTER TABLE forums ADD COLUMN platform TEXT DEFAULT 'nodebb'")
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
            "platform": known.get("platform", "nodebb"),
            "profile_pattern": known.get("profile_pattern", ""),
        }
    return {
        "name":  name,
        "color": color or "#8b90a0",
        "url":   url or "",
        "platform": "nodebb",
        "profile_pattern": "",
    }

def get_forums():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM forums ORDER BY sort_order, name").fetchall()
        return [dict(r) for r in rows]

def get_forum_colors():
    return {f["name"]: f["color"] for f in get_forums()}

def get_forum_names():
    return [f["name"] for f in get_forums()]

def add_forum(name, color="#8b90a0", url="", platform=None):
    """מוסיף פורום — משלים צבע/URL/פלטפורמה/תבנית-פרופיל מ-KNOWN_FORUMS אם חסרים"""
    resolved = resolve_forum_data(name, color, url)
    plat = platform or resolved.get("platform", "nodebb")
    pattern = resolved.get("profile_pattern", "")
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO forums (name, color, url, platform, profile_pattern) "
            "VALUES (?,?,?,?,?)",
            (resolved["name"], resolved["color"], resolved["url"], plat, pattern))

def update_forum(forum_id, name, color, url="", platform=None):
    with get_connection() as conn:
        old_row = conn.execute("SELECT name FROM forums WHERE id=?", (forum_id,)).fetchone()
        old_name = old_row[0] if old_row else None
        if platform is not None:
            conn.execute("UPDATE forums SET name=?, color=?, url=?, platform=? WHERE id=?",
                         (name, color, url, platform, forum_id))
        else:
            conn.execute("UPDATE forums SET name=?, color=?, url=? WHERE id=?",
                         (name, color, url, forum_id))
        if old_name and old_name != name:
            conn.execute("UPDATE nicks SET forum=? WHERE forum=?", (name, old_name))

def get_forum_platform(name):
    """מחזיר את פלטפורמת הפורום (nodebb/discourse/...) לפי שם, ברירת מחדל nodebb."""
    with get_connection() as conn:
        row = conn.execute("SELECT platform FROM forums WHERE name=?", (name,)).fetchone()
        if row and row[0]:
            return row[0]
    known = get_known_forum_by_name(name)
    return (known or {}).get("platform", "nodebb")

def set_forum_platform_by_url(url, platform):
    """שומר פלטפורמה שזוהתה (בעת 'בדוק פורום') חזרה אל הפורום לפי כתובתו."""
    if not url or not platform:
        return
    with get_connection() as conn:
        conn.execute("UPDATE forums SET platform=? WHERE url=?", (platform, url))

# ── עוגיות התחברות שמורות (לפי דומיין) ───────────────────────────────
def _origin(url):
    """מחזיר את ה-origin (scheme://host[:port]) של כתובת, לשיוך עוגייה."""
    from urllib.parse import urlsplit
    u = (url or "").strip()
    if u and not u.startswith("http"):
        u = "https://" + u
    parts = urlsplit(u)
    if not parts.netloc:
        return ""
    return f"{parts.scheme or 'https'}://{parts.netloc}".lower()

def get_cookie_for_url(url):
    """מחזיר עוגייה שמורה לדומיין של הכתובת (או '' אם אין)."""
    origin = _origin(url)
    if not origin:
        return ""
    with get_connection() as conn:
        row = conn.execute("SELECT cookie FROM forum_cookies WHERE origin=?", (origin,)).fetchone()
        return (row[0] if row else "") or ""

def save_cookie_for_url(url, cookie):
    """שומר/מעדכן עוגייה לדומיין. עוגייה ריקה מוחקת את השמורה."""
    origin = _origin(url)
    if not origin:
        return
    with get_connection() as conn:
        if (cookie or "").strip():
            conn.execute(
                "INSERT INTO forum_cookies (origin, cookie, updated_at) VALUES (?,?,datetime('now')) "
                "ON CONFLICT(origin) DO UPDATE SET cookie=excluded.cookie, updated_at=datetime('now')",
                (origin, cookie.strip()))
        else:
            conn.execute("DELETE FROM forum_cookies WHERE origin=?", (origin,))

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
def _chunks(seq, size):
    """חותך רשימה למנות — SQLite מגביל את מספר הפרמטרים בשאילתה."""
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]

def _list_cols_sql():
    """
    עמודות לרשימות (טבלה/כרטיסים/סינון) — במכוון **בלי** avatar_image.
    התמונה נשמרת כ-data URL בבסיס64 ומשקלה עשרות KB; שליחתה לכל השורות ניפחה את
    המטען שעובר לגשר ה-JS לעשרות MB. במקומה מוחזר דגל has_avatar, והתמונה עצמה
    נטענת לפי דרישה (get_avatars) רק עבור השורות שמוצגות בפועל.
    """
    # extra_info הוא בלוב סרוק (מיקום/אתר/אודות/חתימה) שיכול להיות ארוך מאוד;
    # ברשימה ממילא מוצג רק תקציר, ולכן נחתך כאן. הערך המלא זמין ב-get_nick.
    cols = ", ".join(
        "substr(n.extra_info,1,300) as extra_info" if f == "extra_info" else "n." + f
        for f in _NICK_FIELDS if f != "avatar_image")
    return (f"n.id, {cols}, n.created_at, n.updated_at, "
            f"(n.avatar_image != '') as has_avatar")

def get_avatars(nick_ids):
    """מחזיר {nick_id: avatar_image} רק לניקים המבוקשים שיש להם תמונה."""
    ids = [int(i) for i in (nick_ids or [])][:500]   # תקרה, למניעת מטען ענק
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, avatar_image FROM nicks WHERE id IN ({ph}) AND avatar_image != ''",
            ids).fetchall()
        return {str(r["id"]): r["avatar_image"] for r in rows}

def get_all_nicks(search="", limit=None, offset=0):
    """
    מחזיר dict: {"rows": [...], "total": N}.
    limit=None (ברירת מחדל) מחזיר הכל, לתאימות אחורה עם קריאות ישנות.
    """
    with get_connection() as conn:
        base_select = f"""
            SELECT {_list_cols_sql()},
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
                (SELECT COUNT(*) FROM nick_contacts ct WHERE ct.nick_id=n.id) as extra_contacts,
                (SELECT GROUP_CONCAT(field_name) FROM (
                    SELECT field_name FROM field_values fv WHERE fv.nick_id = n.id
                    GROUP BY field_name HAVING COUNT(DISTINCT value) > 1
                 )) as conflict_fields
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
            like_parts = " OR ".join(f"n.{c} LIKE ?" for c in _SEARCH_COLS)
            where = f"WHERE {like_parts}"
            n_cols = len(_SEARCH_COLS)
            total = conn.execute(
                f"SELECT COUNT(*) FROM nicks n {where}", (s,) * n_cols
            ).fetchone()[0]
            rows = conn.execute(
                base_select + where + f" {order_clause} {limit_clause}",
                (s,) * n_cols + tuple(params_extra)
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) FROM nicks").fetchone()[0]
            rows = conn.execute(
                base_select + f"{order_clause} {limit_clause}", params_extra
            ).fetchall()

        return {"rows": [dict(r) for r in rows], "total": total}

# שדות שמותר לסנן/לערוך לפיהם
FILTERABLE_FIELDS = [
    ("forum","פורום"),("username","שם משתמש"),("real_name","שם אמיתי"),
    ("full_name","שם מלא"),("phone","טלפון"),("email","מייל"),("address","כתובת"),
    ("groups","קבוצות"),("status","סטטוס"),("notes","הערות"),("private_notes","הערות אישיות"),
    ("extra_info","פרטים נוספים"),("reputation","מוניטין"),("join_date","תאריך הצטרפות"),
]
_FILTERABLE_KEYS = {k for k, _ in FILTERABLE_FIELDS}

def filter_nicks(field, op="contains", value=""):
    """
    מסנן ניקים לפי שדה בודד.
    op: 'contains' | 'equals' | 'empty' | 'not_empty' | 'starts'
    מחזיר רשימת שורות (עם אותם דגלים מחושבים כמו הרשימה הראשית).
    """
    if field not in _FILTERABLE_KEYS:
        return []
    computed = """
        , (SELECT COUNT(*) FROM nick_conflicts c WHERE c.nick_id = n.id) as conflict_count,
        (SELECT COUNT(*) FROM nick_identities i WHERE i.nick_id_a=n.id OR i.nick_id_b=n.id) as has_identity,
        (SELECT COUNT(*) FROM nick_contacts ct WHERE ct.nick_id=n.id) as extra_contacts,
        (SELECT GROUP_CONCAT(field_name) FROM (
            SELECT field_name FROM field_values fv WHERE fv.nick_id = n.id
            GROUP BY field_name HAVING COUNT(DISTINCT value) > 1)) as conflict_fields
    """
    with get_connection() as conn:
        if op == "empty":
            where = f"WHERE (n.{field} IS NULL OR n.{field}='')"; params = []
        elif op == "not_empty":
            where = f"WHERE n.{field} IS NOT NULL AND n.{field}!=''"; params = []
        elif op == "equals":
            where = f"WHERE n.{field}=?"; params = [value]
        elif op == "starts":
            where = f"WHERE n.{field} LIKE ?"; params = [f"{value}%"]
        else:  # contains
            where = f"WHERE n.{field} LIKE ?"; params = [f"%{value}%"]
        rows = conn.execute(
            f"SELECT {_list_cols_sql()} {computed} FROM nicks n {where} "
            f"ORDER BY n.{field}", params).fetchall()
        return [dict(r) for r in rows]

def filter_nicks_multi(conditions):
    """
    מסנן ניקים לפי כמה תנאים במקביל (כולם חייבים להתקיים — AND).
    conditions: [{field, op, value}, ...]
    """
    conds = [c for c in (conditions or []) if c.get("field") in _FILTERABLE_KEYS]
    if not conds:
        return []
    computed = """
        , (SELECT COUNT(*) FROM nick_conflicts c WHERE c.nick_id = n.id) as conflict_count,
        (SELECT COUNT(*) FROM nick_identities i WHERE i.nick_id_a=n.id OR i.nick_id_b=n.id) as has_identity,
        (SELECT COUNT(*) FROM nick_contacts ct WHERE ct.nick_id=n.id) as extra_contacts,
        (SELECT GROUP_CONCAT(field_name) FROM (
            SELECT field_name FROM field_values fv WHERE fv.nick_id = n.id
            GROUP BY field_name HAVING COUNT(DISTINCT value) > 1)) as conflict_fields
    """
    clauses, params = [], []
    for c in conds:
        f, op, val = c["field"], c.get("op", "contains"), c.get("value", "")
        if op == "empty":
            clauses.append(f"(n.{f} IS NULL OR n.{f}='')")
        elif op == "not_empty":
            clauses.append(f"(n.{f} IS NOT NULL AND n.{f}!='')")
        elif op == "equals":
            clauses.append(f"n.{f}=?"); params.append(val)
        elif op == "starts":
            clauses.append(f"n.{f} LIKE ?"); params.append(f"{val}%")
        else:
            clauses.append(f"n.{f} LIKE ?"); params.append(f"%{val}%")
    where = "WHERE " + " AND ".join(clauses)
    order = conds[0]["field"]
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {_list_cols_sql()} {computed} FROM nicks n {where} "
            f"ORDER BY n.{order}", params).fetchall()
        return [dict(r) for r in rows]

def bulk_update_field(nick_ids, field, value):
    """עדכון מרובה מהיר של שדה בודד (דרך מקור 'אני'), בטרנזקציה אחת."""
    if field not in _FILTERABLE_KEYS or field in ("forum","username"):
        return 0
    ids = [int(i) for i in (nick_ids or [])]
    if not ids:
        return 0
    with get_connection() as conn:
        # עדכון ה-cache בטבלת nicks
        conn.executemany(
            f"UPDATE nicks SET {field}=?, updated_at=datetime('now') WHERE id=?",
            [(value, nid) for nid in ids])
        if field not in _NON_SOURCED:
            if value in (None, ""):
                # ריקון → הסר את תרומת "אני" לשדה זה
                conn.executemany(
                    "DELETE FROM field_values WHERE nick_id=? AND field_name=? AND source_id=1",
                    [(nid, field) for nid in ids])
            else:
                # רשום/עדכן ערך תחת מקור "אני"
                conn.executemany(
                    """INSERT INTO field_values (nick_id, field_name, value, source_id)
                       VALUES (?,?,?,1)
                       ON CONFLICT(nick_id, field_name, source_id)
                       DO UPDATE SET value=excluded.value, created_at=datetime('now')""",
                    [(nid, field, value) for nid in ids])
    # הכרעה מחדש (כדי לכבד מקורות אבסולוטיים/אמינים יותר) — רק אם יש ריבוי מקורות
    if field not in _NON_SOURCED:
        with get_connection() as conn:
            multi = set()
            for chunk in _chunks(ids, 400):
                ph = ",".join("?" * len(chunk))
                multi.update(r[0] for r in conn.execute(
                    f"""SELECT nick_id FROM field_values WHERE field_name=? AND nick_id IN
                        ({ph}) GROUP BY nick_id HAVING COUNT(*)>1""",
                    [field] + list(chunk)).fetchall())
            for nid in multi:
                _resolve_fields_conn(conn, nid, [field])
    return len(ids)

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

def find_nick_by_username(username):
    """מאתר ניק לפי שם משתמש בלבד (הראשון שנמצא) — לתיוג @"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, forum FROM nicks WHERE username=? LIMIT 1",
            (username,)).fetchone()
        return dict(row) if row else None

def search_usernames(prefix, limit=8):
    """שמות משתמש שמתחילים ב-prefix, להשלמה אוטומטית בתיוג"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT username, forum FROM nicks WHERE username LIKE ? "
            "ORDER BY username LIMIT ?",
            (prefix + "%", limit)).fetchall()
        return [dict(r) for r in rows]

def search_nicks_for_lookup(query, limit=12):
    """
    חיפוש ניקים לתצוגת המשתמש המאוחדת — לפי שם משתמש או שם אמיתי,
    מדורג: התאמה מדויקת → מתחיל ב- → מכיל. מחזיר [{id,username,forum,real_name}].
    """
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, username, forum, real_name, full_name FROM nicks
            WHERE username LIKE ? OR real_name LIKE ? OR full_name LIKE ?
            ORDER BY
              CASE WHEN username = ? THEN 0
                   WHEN username LIKE ? THEN 1
                   ELSE 2 END,
              username
            LIMIT ?
        """, (like, like, like, q, q + "%", limit)).fetchall()
        return [dict(r) for r in rows]

# שדות המוצגים בתצוגת המשתמש המאוחדת (label, key)
_MERGE_DISPLAY = [
    ("real_name", "שם אמיתי"), ("full_name", "שם מלא"),
    ("phone", "טלפון"), ("email", "מייל"), ("address", "כתובת"),
    ("groups", "קבוצות"), ("reputation", "מוניטין"), ("status", "סטטוס"),
    ("join_date", "תאריך הצטרפות"), ("post_count", "מספר הודעות"),
    ("notes", "הערות"), ("extra_info", "פרטים נוספים"), ("private_notes", "הערות אישיות"),
]

def get_merged_profile(nick_id):
    """
    תצוגת משתמש מאוחדת: מאחד ניק וכל הזהויות המקושרות אליו (סגור טרנזיטיבי).
    מחזיר:
      {members: [{id,forum,username,avatar_image,avatar_url,nick_color,trust_level}],
       fields:  [{key,label, values:[{value,forum,username,nick_id}]}],
       contacts:[{type,value,label,is_private,forum,username}]}
    ערך לכל שדה נאסף מכל חברי הקבוצה (ערכים שונים מוצגים כולם, מיוחסים למקורם).
    """
    nid = int(nick_id)
    with get_connection() as conn:
        exists = conn.execute("SELECT id FROM nicks WHERE id=?", (nid,)).fetchone()
        if not exists:
            return None
        group = sorted(_identity_group(conn, nid))
        ph = ",".join("?" * len(group))
        rows = conn.execute(
            f"SELECT * FROM nicks WHERE id IN ({ph}) ORDER BY trust_level DESC, id", group
        ).fetchall()
        members = [dict(r) for r in rows]

        member_meta = [{
            "id": m["id"], "forum": m["forum"], "username": m["username"],
            "avatar_image": m.get("avatar_image", ""), "avatar_url": m.get("avatar_url", ""),
            "nick_color": m.get("nick_color", ""), "trust_level": m.get("trust_level", 5),
        } for m in members]

        fields = []
        for key, label in _MERGE_DISPLAY:
            seen_vals, values = set(), []
            for m in members:
                v = str(m.get(key, "") or "").strip()
                if not v or v in seen_vals:
                    continue
                seen_vals.add(v)
                values.append({"value": v, "forum": m["forum"],
                               "username": m["username"], "nick_id": m["id"]})
            if values:
                fields.append({"key": key, "label": label, "values": values})

        contacts = []
        ct_rows = conn.execute(
            f"SELECT c.*, n.forum, n.username FROM nick_contacts c "
            f"JOIN nicks n ON n.id = c.nick_id WHERE c.nick_id IN ({ph}) "
            f"ORDER BY c.type, c.id", group).fetchall()
        for c in ct_rows:
            contacts.append(dict(c))

    return {"members": member_meta, "fields": fields, "contacts": contacts}

# שדות שממוזגים מסריקה (לא נוגעים ב-private_notes/real_name של המשתמש)
_SCRAPE_MERGE_FIELDS = ["groups", "reputation", "full_name", "email", "address",
                        "status", "join_date", "post_count", "avatar_url",
                        "nick_color", "avatar_image", "extra_info", "forum_uid"]

def merge_scraped_users(forum, users, source_label="סריקה"):
    """
    ממזג עמוד שלם של משתמשים סרוקים — חיבור וטרנזקציה אחת לכל העמוד,
    במקום שני חיבורים לכל שדה של כל משתמש (עשרות אלפי חיבורים בסריקה מלאה).
    users: רשימת (username, mapped) כפי שמחזיר scraper._map_user.
    רק ערכים שהשתנו מאז הסריקה הקודמת נרשמים ומוכרעים מחדש, כך שסריקה
    חוזרת על פורום שלא השתנה כמעט לא כותבת ל-DB.
    מחזיר: {"added": n, "updated": n, "unchanged": n}
    """
    stats = {"added": 0, "updated": 0, "unchanged": 0}
    with get_connection() as conn:
        scrape_sid = get_scrape_source(conn)["id"]

        # ── שתי שאילתות לכל העמוד, במקום שתיים לכל משתמש ──────────────
        # (השליפה הפר-משתמשית של ערכי הסריקה הקיימים הייתה סורקת את כל
        #  field_values בכל קריאה במאגר גדול — צוואר הבקבוק החמור ביותר.)
        names = [u for u, _ in users]
        existing_rows = {}
        for chunk in _chunks(names, 400):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT id, username, scraped_email FROM nicks "
                    f"WHERE forum=? AND username IN ({ph})", [forum] + list(chunk)):
                existing_rows[r["username"]] = r

        old_by_nick = {}
        for chunk in _chunks([r["id"] for r in existing_rows.values()], 400):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT nick_id, field_name, value FROM field_values "
                    f"WHERE source_id=? AND nick_id IN ({ph})", [scrape_sid] + list(chunk)):
                old_by_nick.setdefault(r["nick_id"], {})[r["field_name"]] = r["value"]

        for username, scraped in users:
            new_vals = {}
            for f in _SCRAPE_MERGE_FIELDS:
                v = scraped.get(f, "")
                if v not in (None, ""):
                    new_vals[f] = v
            row = existing_rows.get(username)

            if row is None:
                cur = conn.execute(
                    "INSERT INTO nicks (forum, username, source, trust_level, scraped_email) "
                    "VALUES (?,?,?,4,?)",
                    (forum, username, source_label, scraped.get("email", "") or ""))
                nid = cur.lastrowid
                for f, v in new_vals.items():
                    _upsert_field_value(conn, nid, f, v, scrape_sid)
                if new_vals:
                    _resolve_fields_conn(conn, nid, list(new_vals))
                stats["added"] += 1
                continue

            nid = row["id"]
            # scraped_email משמש את חישוב has_info (מייל מסריקה אינו "מידע מעניין")
            if scraped.get("email") and scraped["email"] != row["scraped_email"]:
                conn.execute("UPDATE nicks SET scraped_email=? WHERE id=?",
                             (scraped["email"], nid))
            old = old_by_nick.get(nid, {})
            # הרחקה שבוטלה: הסורק לא מדווח "לא מורחק" (מחזיר סטטוס ריק), ולכן
            # "מורחק" שנרשם בסריקה קודמת היה נשאר לנצח. אם עכשיו אין סטטוס
            # והסריקה הקודמת רשמה הרחקה — מנקים ל"פעיל".
            if "status" not in new_vals and old.get("status") == "מורחק":
                new_vals["status"] = "פעיל"
            changed = {f: v for f, v in new_vals.items() if str(v) != old.get(f)}
            if not changed:
                stats["unchanged"] += 1
                continue
            for f, v in changed.items():
                _upsert_field_value(conn, nid, f, v, scrape_sid)
            _resolve_fields_conn(conn, nid, list(changed))
            stats["updated"] += 1
    return stats

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
    # מנות של 400 — SQLite מגביל את מספר הפרמטרים, ו"בחר הכל" יכול להיות עשרות אלפים
    deleted = 0
    with get_connection() as conn:
        for chunk in _chunks(ids, 400):
            ph = ",".join(["?"] * len(chunk))
            cur = conn.execute(f"DELETE FROM nicks WHERE id IN ({ph})", list(chunk))
            deleted += cur.rowcount
    return deleted

def reset_all():
    """איפוס נתונים מלא — מוחק ניקים וכל המידע הנלווה כולל מקורות וייבואים."""
    with get_connection() as conn:
        conn.execute("DELETE FROM nicks")
        conn.execute("DELETE FROM nick_conflicts")
        conn.execute("DELETE FROM nick_contacts")
        conn.execute("DELETE FROM nick_identities")
        conn.execute("DELETE FROM field_values")
        conn.execute("DELETE FROM shelved_values")
        conn.execute("DELETE FROM import_sources")
        # מחק את כל המקורות פרט ל"אני", ואפס את "אני" לברירת מחדל
        conn.execute("DELETE FROM sources WHERE id != 1")
        conn.execute("UPDATE sources SET trust=10, absolute=0, notes='' WHERE id=1")
        # אפס דגל ה-backfill כדי שהתחלה חדשה תהיה נקייה
        conn.execute("DELETE FROM settings WHERE key='backfill_sources_done'")
        # אפס טבלת ה-FTS אם קיימת
        try:
            conn.execute("INSERT INTO nicks_fts(nicks_fts) VALUES('rebuild')")
        except Exception:
            pass

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
    """מאפס את כל ההגדרות (תצוגה, סנכרון, מדיניות התנגשות, ייבוא) — לא נתונים"""
    _PRESERVE = {"export_version", "backfill_sources_done"}
    with get_connection() as conn:
        rows = conn.execute("SELECT key FROM settings").fetchall()
        for (k,) in rows:
            if k not in _PRESERVE:
                conn.execute("DELETE FROM settings WHERE key=?", (k,))
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

# הערה: טבלת nick_conflicts נשארת לצפייה/סגירה של התנגשויות מגרסאות ישנות
# (get_conflicts / delete_conflict). זרימות חדשות עוברות דרך מנוע המקורות.

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

def _identity_group(conn, nick_id):
    """מחזיר את כל ה-IDs בקבוצת הזהות של ניק (כולל עצמו), דרך סגור טרנזיטיבי."""
    group = {nick_id}
    frontier = {nick_id}
    while frontier:
        placeholders = ",".join(["?"] * len(frontier))
        rows = conn.execute(f"""
            SELECT nick_id_a, nick_id_b FROM nick_identities
            WHERE nick_id_a IN ({placeholders}) OR nick_id_b IN ({placeholders})
        """, list(frontier) * 2).fetchall()
        new = set()
        for a, b in rows:
            for x in (a, b):
                if x not in group:
                    new.add(x); group.add(x)
        frontier = new
    return group

def add_identity(nick_id_a, nick_id_b):
    """
    מקשר שני ניקים כזהות כפולה — באופן טרנזיטיבי.
    אם A שייך לקבוצה {A, A1} ו-B לקבוצה {B, B1}, לאחר הקישור כל החמישה
    מקושרים הדדית זה לזה (קבוצת זהות אחת מלאה).
    """
    if nick_id_a == nick_id_b:
        return
    with get_connection() as conn:
        # אחד את שתי הקבוצות של A ושל B
        members = _identity_group(conn, nick_id_a) | _identity_group(conn, nick_id_b)
        members = sorted(members)
        # צור קישור בין כל זוג בקבוצה המאוחדת
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                conn.execute(
                    "INSERT OR IGNORE INTO nick_identities (nick_id_a, nick_id_b) VALUES (?,?)",
                    (a, b))

def remove_identity(current_nick_id, other_nick_id):
    """
    מוציא את הניק שממנו פעלת (current_nick_id — זה שפתחת את ההגדרות שלו)
    מקבוצת הזהות לחלוטין: מנתק אותו מכל חברי הקבוצה. שאר החברים נשארים
    מקושרים ביניהם.
    לדוגמה: פתחת את "בני" ולחצת להסיר את "בני1" → "בני" יוצא מהקבוצה,
    ו"בני1" ושאר החברים נשארים מקושרים.
    """
    with get_connection() as conn:
        group = _identity_group(conn, current_nick_id)
        group.discard(current_nick_id)
        for other in group:
            a, b = min(current_nick_id, other), max(current_nick_id, other)
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
# תנאי has_info / my_info — מקור אמת יחיד, משותף לייצוא ולספירה
_HAS_INFO_SQL = """(
   n.phone != '' OR n.notes != '' OR n.private_notes != '' OR n.real_name != ''
   OR (n.email != '' AND n.email != n.scraped_email)
   OR EXISTS (SELECT 1 FROM nick_contacts ct WHERE ct.nick_id = n.id)
   OR EXISTS (SELECT 1 FROM nick_identities i WHERE i.nick_id_a=n.id OR i.nick_id_b=n.id)
)"""
_MY_INFO_SQL = """(
   EXISTS (SELECT 1 FROM field_values fv WHERE fv.nick_id=n.id AND fv.source_id=1)
   OR EXISTS (SELECT 1 FROM nick_contacts ct WHERE ct.nick_id=n.id)
   OR n.private_notes != ''
)"""

_EXPORT_QUERY = f"""
    SELECT n.*,
      CASE WHEN {_HAS_INFO_SQL} THEN 1 ELSE 0 END as _has_info,
      CASE WHEN {_MY_INFO_SQL} THEN 1 ELSE 0 END as _my_info
    FROM nicks n
"""

def _excluded_forums_clause():
    """(where_sql, params) המחריג פורומים שכובו בהגדרות הייבוא/ייצוא."""
    excluded = [name for name, inc in get_forum_io_flags().items() if not inc]
    if not excluded:
        return "", []
    return "WHERE n.forum NOT IN (%s)" % ",".join("?" * len(excluded)), excluded

def count_export_modes():
    """כמה ניקים ייכללו בכל מצב ייצוא — ספירה ב-SQL (בלי למשוך את כל השורות)."""
    where, params = _excluded_forums_clause()
    with get_connection() as conn:
        row = conn.execute(f"""
            SELECT COUNT(*) AS all_c,
                   SUM(CASE WHEN {_HAS_INFO_SQL} THEN 1 ELSE 0 END) AS info_c,
                   SUM(CASE WHEN {_MY_INFO_SQL} THEN 1 ELSE 0 END) AS mine_c
            FROM nicks n {where}
        """, params).fetchone()
    return {"all": row["all_c"] or 0,
            "has_info": row["info_c"] or 0,
            "my_info": row["mine_c"] or 0}

def export_data(mode="all"):
    """
    mode: 'all' | 'has_info' (רק ניקים עם מידע מעניין) | 'my_info' (רק ניקים עם מידע שהוספתי בעצמי).
    """
    exportable = get_exportable_fields()
    io_flags = get_forum_io_flags()   # forum_name -> included?
    with get_connection() as conn:
        rows = conn.execute(_EXPORT_QUERY).fetchall()
    records = []
    for r in rows:
        d = dict(r)
        # דלג על פורומים שהוחרגו בהגדרות (סעיף 2)
        if io_flags.get(d.get("forum", ""), True) is False:
            continue
        if mode == "has_info" and not d.get("_has_info"):
            continue
        if mode == "my_info" and not d.get("_my_info"):
            continue
        records.append({f: d.get(f, '') for f in exportable})
    return {
        "version": 2,
        "exported_at": datetime.now().isoformat(),
        "exported_fields": exportable,
        "export_mode": mode,
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
    def _get(c):
        row = c.execute("SELECT * FROM sources WHERE kind='scrape' LIMIT 1").fetchone()
        if not row:
            c.execute("INSERT INTO sources (kind,name,trust,absolute) VALUES ('scrape','סריקת אינטרנט',9,0)")
            row = c.execute("SELECT * FROM sources WHERE kind='scrape' LIMIT 1").fetchone()
        return dict(row)
    if conn is not None:
        return _get(conn)
    with get_connection() as c:
        return _get(c)

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
    # אבסולוטי מותר רק על מקור "אני" (id=1)
    if absolute is not None and int(source_id) == 1:
        sets.append("absolute=?"); vals.append(1 if absolute else 0)
    if not sets:
        return
    vals.append(source_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE sources SET {', '.join(sets)} WHERE id=?", vals)
        rows = conn.execute(
            "SELECT DISTINCT nick_id, field_name FROM field_values WHERE source_id=?",
            (source_id,)).fetchall()
        # הכרעה מחדש מקובצת לפי ניק — UPDATE אחד לכל ניק (ולא לכל שדה),
        # על אותו חיבור. אחרת שינוי דרגת אמינות של מקור גדול תקע את התוכנה לשעות.
        by_nick = {}
        for r in rows:
            by_nick.setdefault(r[0], []).append(r[1])
        _resolve_fields_bulk(conn, by_nick)

def delete_source(source_id):
    """מוחק מקור וכל הערכים שלו; מריץ הכרעה מחדש לשדות המושפעים."""
    if source_id == 1:
        return False  # לא מוחקים את "אני"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT nick_id, field_name FROM field_values WHERE source_id=?",
            (source_id,)).fetchall()
        by_nick = {}
        for r in rows:
            by_nick.setdefault(r[0], []).append(r[1])
        conn.execute("DELETE FROM field_values WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
        # הכרעה מחדש מקובצת על אותו חיבור (ראה update_source)
        _resolve_fields_bulk(conn, by_nick)
    return True

def _upsert_field_value(conn, nick_id, field_name, value, source_id):
    """רישום/עדכון ערך ממקור, על חיבור קיים — ללא הכרעה (המכריע באחריות הקורא)."""
    conn.execute("""
        INSERT INTO field_values (nick_id, field_name, value, source_id)
        VALUES (?,?,?,?)
        ON CONFLICT(nick_id, field_name, source_id)
        DO UPDATE SET value=excluded.value, created_at=datetime('now')
    """, (nick_id, field_name, str(value), source_id))

def _winner_for(field_name, frows):
    """הערך המנצח לשדה מתוך רשומות (value, created_at, kind, trust, absolute).
    כללים מיוחדים:
      • reputation: רק ערך ממקור סריקה, והחדש ביותר מנצח.
      • status: מקור סריקה מקבל אמינות אבסולוטית.
    """
    if not frows:
        return ""
    if field_name == "reputation":
        scr = [r for r in frows if r["kind"] == "scrape"]
        pool = scr if scr else frows
        return max(pool, key=lambda r: r["created_at"])["value"]
    def score(r):
        eff = 10**6 if r["absolute"] else int(r["trust"])
        if field_name == "status" and r["kind"] == "scrape":
            eff = 10**6  # סריקה = אמינות מלאה לסטטוס
        return (eff, r["created_at"])
    return max(frows, key=score)["value"]

def _resolve_fields_conn(conn, nick_id, field_names):
    """
    מכריע כמה שדות של ניק אחד על חיבור קיים, ומעדכן את ה-cache ב-UPDATE יחיד.
    UPDATE אחד במקום אחד-לשדה חוסך גם את שכתובי ה-FTS החוזרים (הטריגרים
    משכתבים את כל שורת ה-FTS בכל UPDATE על nicks).
    """
    fields = [f for f in field_names if f not in _NON_SOURCED and f in _NICK_FIELDS]
    if not fields:
        return
    ph = ",".join("?" * len(fields))
    rows = conn.execute(f"""
        SELECT fv.field_name, fv.value, fv.created_at, s.kind, s.trust, s.absolute
        FROM field_values fv JOIN sources s ON s.id = fv.source_id
        WHERE fv.nick_id=? AND fv.field_name IN ({ph})
    """, [nick_id] + fields).fetchall()
    by_field = {}
    for r in rows:
        by_field.setdefault(r["field_name"], []).append(dict(r))
    winners = {f: _winner_for(f, by_field.get(f, [])) for f in fields}

    # כתוב רק אם משהו באמת השתנה: כל UPDATE על nicks מפעיל את טריגרי ה-FTS
    # ומשכתב את כל שורת האינדקס. דילוג על כתיבות-סרק הופך פעולות המוניות
    # (שינוי אמינות מקור, מיזוג סריקה חוזרת) לזולות.
    cur_row = conn.execute(
        f"SELECT {', '.join(fields)} FROM nicks WHERE id=?", (nick_id,)).fetchone()
    if cur_row is None:
        return
    changed = [f for f in fields if str(cur_row[f] or "") != str(winners[f] or "")]
    if not changed:
        return
    sets = ", ".join(f"{f}=?" for f in changed)
    conn.execute(
        f"UPDATE nicks SET {sets}, updated_at=datetime('now') WHERE id=?",
        [winners[f] for f in changed] + [nick_id])

def _resolve_fields_bulk(conn, by_nick):
    """
    הכרעה מחדש להרבה ניקים בבת אחת: שתי שאילתות לכל מנה של 400 ניקים,
    במקום שתיים לכל ניק. משמש פעולות המוניות (שינוי/מחיקת מקור), שבמאגר
    גדול נגעו במאות אלפי שורות ותקעו את התוכנה.
    by_nick: {nick_id: [field, ...]}
    """
    nids = [n for n in by_nick if by_nick[n]]
    all_fields = sorted({f for fl in by_nick.values() for f in fl
                         if f not in _NON_SOURCED and f in _NICK_FIELDS})
    if not nids or not all_fields:
        return 0
    fph = ",".join("?" * len(all_fields))
    updated = 0
    for chunk in _chunks(nids, 400):
        ph = ",".join("?" * len(chunk))
        grouped = {}
        for r in conn.execute(f"""
                SELECT fv.nick_id, fv.field_name, fv.value, fv.created_at,
                       s.kind, s.trust, s.absolute
                FROM field_values fv JOIN sources s ON s.id = fv.source_id
                WHERE fv.nick_id IN ({ph}) AND fv.field_name IN ({fph})
            """, list(chunk) + all_fields):
            grouped.setdefault(r["nick_id"], {}).setdefault(r["field_name"], []).append(dict(r))
        cur_rows = {r["id"]: r for r in conn.execute(
            f"SELECT id, {', '.join(all_fields)} FROM nicks WHERE id IN ({ph})", list(chunk))}
        for nid in chunk:
            cur = cur_rows.get(nid)
            if cur is None:
                continue
            flds = [f for f in by_nick[nid] if f in all_fields]
            winners = {f: _winner_for(f, grouped.get(nid, {}).get(f, [])) for f in flds}
            changed = [f for f in flds if str(cur[f] or "") != str(winners[f] or "")]
            if not changed:
                continue
            sets = ", ".join(f"{f}=?" for f in changed)
            conn.execute(f"UPDATE nicks SET {sets}, updated_at=datetime('now') WHERE id=?",
                         [winners[f] for f in changed] + [nid])
            updated += 1
    return updated

def record_field_value(nick_id, field_name, value, source_id):
    """רושם/מעדכן ערך של שדה ממקור מסוים, ואז מכריע מחדש מי מנצח."""
    if field_name in _NON_SOURCED or value in (None, ""):
        return
    with get_connection() as conn:
        _upsert_field_value(conn, nick_id, field_name, value, source_id)
        _resolve_fields_conn(conn, nick_id, [field_name])

def resolve_field(nick_id, field_name):
    """מחשב מחדש את הערך המנצח לשדה ומעדכן את טבלת nicks (ה-cache)."""
    if field_name in _NON_SOURCED:
        return
    with get_connection() as conn:
        _resolve_fields_conn(conn, nick_id, [field_name])

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

def force_field_value(nick_id, field_name, value):
    """כותב ערך ישירות ל-cache (nicks) — לבחירה מפורשת שגוברת על הכרעת אמינות."""
    if field_name in _NICK_FIELDS and field_name not in ("forum", "username"):
        with get_connection() as conn:
            conn.execute(
                f"UPDATE nicks SET {field_name}=?, updated_at=datetime('now') WHERE id=?",
                (value, int(nick_id)))

def force_scraped_values(nick_id, mapped):
    """
    "סנכרן נבחרים": רושם את כל הערכים הסרוקים תחת מקור הסריקה וכותב אותם
    ישירות ל-cache (המשתמש בחר במפורש → הסרוק מנצח, בלי הכרעת אמינות).
    הכול בחיבור אחד. מחזיר כמה שדות נכתבו.
    """
    nid = int(nick_id)
    with get_connection() as conn:
        sid = get_scrape_source(conn)["id"]
        sets, vals = [], []
        for field, val in (mapped or {}).items():
            if val in (None, ""):
                continue
            if field not in _NON_SOURCED:
                _upsert_field_value(conn, nid, field, val, sid)
            if field in _NICK_FIELDS and field not in ("forum", "username"):
                sets.append(f"{field}=?"); vals.append(val)
        if sets:
            conn.execute(
                f"UPDATE nicks SET {', '.join(sets)}, updated_at=datetime('now') WHERE id=?",
                vals + [nid])
        return len(sets)

def apply_import_conflict(nick_id, field, value, source_id, accept):
    """
    מחיל החלטה ידנית על התנגשות ייבוא.
    accept=True → הערך המיובא מנצח בפועל (נרשם למקור וגם מוצג מיד),
    כי בחירה ידנית גוברת על הכרעת האמינות האוטומטית.
    accept=False → נשאר הקיים (לא נרשם כלום מהייבוא לשדה זה).
    """
    if not accept:
        return True
    nid = int(nick_id)
    record_field_value(nid, field, value, int(source_id))
    # בחירה ידנית גוברת — כתוב ישירות ל-cache כדי שיוצג
    if field in _NICK_FIELDS and field not in ("forum", "username"):
        with get_connection() as conn:
            conn.execute(
                f"UPDATE nicks SET {field}=?, updated_at=datetime('now') WHERE id=?",
                (value, nid))
    return True

def import_data(data, source_info="ייבוא חיצוני", forum_mapping=None,
                import_name=None, import_notes="", import_trust=None, import_absolute=0,
                manual_conflicts=False):
    """
    ייבוא מבוסס-מקורות: נוצר מקור ייבוא אחד (שם/הערות/אמינות/אבסולוטי),
    וכל ערך מיובא נרשם תחתיו במנוע המקורות. הערך המנצח בכל שדה נקבע אוטומטית.
    manual_conflicts=True → התנגשויות (ערך שונה בשדה קיים) לא נרשמות אלא מוחזרות
    לפתרון ידני; מחזיר dict עם רשימת ההתנגשויות.
    מחזיר: (imported_new, values_recorded) או dict במצב ידני.
    """
    imported = 0; recorded = 0
    pending_conflicts = []
    exported_fields = data.get("exported_fields", get_exportable_fields())
    mapping = forum_mapping or {}
    trust = get_my_trust() if import_trust is None else max(1, min(10, int(import_trust)))
    src_name = import_name or source_info
    import_sid = create_import_source(src_name, import_notes, trust, 0)

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
    # נרמול הרשומות מהקובץ (מיפוי פורומים + סינון) לפני העבודה מול ה-DB
    entries = []
    for nick in data.get("nicks", []):
        username  = nick.get("username", "").strip()
        forum_raw = nick.get("forum", "").strip()
        mapped    = mapping.get(forum_raw, "")
        forum     = mapped if mapped else forum_raw
        if not username or io_flags.get(forum, True) is False:
            continue
        entries.append((forum, username, nick))

    sourced_fields = [f for f in exported_fields if f not in _NON_SOURCED]

    # הכל בחיבור וטרנזקציה אחת: קודם טוענים את הניקים הקיימים במנות,
    # ואז כותבים. (בעבר נפתח חיבור נפרד לכל ערך — ייבוא גדול נמשך עשרות דקות.)
    with get_connection() as conn:
        by_forum = {}
        for forum, username, _ in entries:
            by_forum.setdefault(forum, set()).add(username)
        existing = {}          # (forum, username) -> row
        for forum, unames in by_forum.items():
            for chunk in _chunks(sorted(unames), 400):
                ph = ",".join("?" * len(chunk))
                for r in conn.execute(
                        f"SELECT * FROM nicks WHERE forum=? AND username IN ({ph})",
                        [forum] + list(chunk)):
                    existing[(forum, r["username"])] = r

        for forum, username, nick in entries:
            row = existing.get((forum, username))
            if row is not None:
                nid = row["id"]
            else:
                cur_ins = conn.execute(
                    "INSERT INTO nicks (forum, username, source, trust_level) VALUES (?,?,?,3)",
                    (forum, username, src_name))
                nid = cur_ins.lastrowid
                imported += 1

            changed_fields = []
            for field in sourced_fields:
                val = nick.get(field, "")
                if val in (None, ""):
                    continue
                if manual_conflicts and row is not None:
                    old = str((row[field] if field in row.keys() else "") or "").strip()
                    if old and old != str(val).strip():
                        pending_conflicts.append({
                            "nick_id": nid, "username": username, "forum": forum,
                            "field": field, "old_value": old, "new_value": str(val),
                            "source_id": import_sid, "source_name": src_name,
                        })
                        continue  # אל תרשום עדיין — ימתין להכרעה ידנית
                _upsert_field_value(conn, nid, field, val, import_sid)
                changed_fields.append(field)
                recorded += 1
            # הכרעה אחת לכל הניק — UPDATE יחיד (ולא אחד לכל שדה)
            if changed_fields:
                _resolve_fields_conn(conn, nid, changed_fields)

    # עדכן ספירות בלוג הייבוא (import_sources הישן, לתאימות)
    log_import_source(src_name, import_notes, trust, imported, recorded)
    if manual_conflicts:
        return {"imported": imported, "recorded": recorded,
                "conflicts": pending_conflicts, "source_id": import_sid}
    return imported, recorded
