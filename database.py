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
    ("last_seen",     "נראה לאחרונה",    True),
    ("avatar_url",    "כתובת תמונה",     True),
    ("nick_color",    "צבע ניק",         True),
    ("avatar_image",  "תמונת פרופיל",    False),  # כבד — ברירת מחדל לא מסונכרן
]

EXPORT_FORMAT_VERSION = 3

# מקטעים בקובץ שאינם עמודות של הניק. דגל הסנכרון שלהם יושב באותה טבלת
# sync_settings, אבל הם *לא* ב-ALL_NICK_FIELDS: כל מי שקורא את ALL_NICK_FIELDS
# מניח "שם עמודה בטבלת nicks" (ייצוא, ייבוא, CSV, איפוס עמודות).
EXTRA_SYNC_KEYS = [
    ("contacts",   "אנשי קשר נוספים (טלפונים/מיילים)",     True),
    ("identities", "קישורי זהות (אותו אדם בכמה פורומים)",  True),
]

CONTACT_TYPES = {"phone", "email"}      # מה שהממשק יודע להציג ולפעול עליו
MAX_CONTACTS_PER_NICK = 50              # תקרת שפיות מול קובץ פגום/עוין
MAX_IMPORT_IDENTITY_GROUPS = 5000

_local = threading.local()

# ── בריכת חיבורים ─────────────────────────────────────────────────────
# pywebview מריץ כל קריאת גשר מ-JS ב-thread חדש (js_bridge_call -> Thread(target=_call)),
# ולכן חיבור thread-local לבדו נפתח מחדש בכל קריאה — ~7ms של connect+PRAGMA פר קריאה,
# מאות פעמים בהפעלה. ה-thread מחזיק את החיבור כל עוד הוא חי, וכשהוא מת ה-holder
# משוחרר ומחזיר את החיבור לבריכה במקום לזרוק אותו.
_pool = []                      # [(conn, path)] — חיבורים פנויים
_pool_lock = threading.Lock()
_POOL_MAX = 8

class _ConnHolder:
    __slots__ = ("conn", "path")

    def __init__(self, conn, path):
        self.conn, self.path = conn, path

    def __del__(self):
        conn, path = self.conn, self.path
        try:
            conn.rollback()     # אל תחזיר לבריכה חיבור באמצע טרנזקציה
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return
        try:
            if _pool_lock is None:      # כיבוי המפרש
                return
            with _pool_lock:
                if path == DB_PATH and len(_pool) < _POOL_MAX:
                    _pool.append((conn, path))
                    return
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

def get_connection():
    """
    מחזיר חיבור SQLite לשימוש חוזר לכל thread.
    פתיחת חיבור חדש בכל קריאה (כולל 2 PRAGMA) עלתה ~7ms — מה שהצטבר לשניות
    בכל פעולה שעושה הרבה קריאות קטנות. חיבור אחד per-thread מוריד זאת כמעט לאפס.
    sqlite3 אינו בטוח לשיתוף בין threads, ולכן thread-local (הסריקה רצה ב-thread נפרד).
    אם DB_PATH השתנה (בדיקות / אתחול) — נסגר הישן ונפתח חדש.
    """
    h = getattr(_local, "holder", None)
    if h is not None and h.path == DB_PATH:
        return h.conn
    if h is not None:
        _local.holder = None      # ה-__del__ מחזיר את הישן לבריכה/סוגר אותו
    conn = None
    with _pool_lock:
        while _pool:
            cand, cpath = _pool.pop()
            if cpath == DB_PATH:
                conn = cand
                break
            try:
                cand.close()
            except Exception:
                pass
    if conn is None:
        conn = _new_connection()
    _local.holder = _ConnHolder(conn, DB_PATH)
    return conn

def _new_connection():
    # check_same_thread=False: החיבור נוצר ב-thread אחד וייתכן שיישאל שוב מאחר
    # דרך הבריכה. השימוש עצמו נשאר חד-threadי (thread אחד מחזיק אותו בכל רגע).
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # בלי זה, כתיבה בזמן שסריקה/ייבוא מחזיקים את המאגר נכשלת מיד ב-
    # "database is locked": update_nick היה מספיק לעדכן את ה-cache ואז נופל
    # לפני רישום המקורות — כלומר שמירה שנראתה מוצלחת והשאירה נתונים חצויים.
    conn.execute("PRAGMA busy_timeout=15000")
    # בלי גבול, קובץ ה--wal לא מתכווץ אחרי סריקה/ייבוא גדולים
    conn.execute("PRAGMA journal_size_limit=67108864")
    return conn

def close_pool():
    """סוגר את כל החיבורים הפנויים (בדיקות / החלפת DB_PATH / יציאה)."""
    with _pool_lock:
        while _pool:
            c, _ = _pool.pop()
            try:
                c.close()
            except Exception:
                pass

def checkpoint():
    """מקפל את ה-WAL לקובץ הראשי (לסגירה נקייה / אחרי פעולה גדולה)."""
    try:
        conn = get_connection()
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass

def db_health():
    """מצב המאגר לדיאלוג 'בריאות המאגר': גודל, WAL, בדיקת תקינות מהירה, ספירות."""
    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    wal = os.path.getsize(DB_PATH + "-wal") if os.path.exists(DB_PATH + "-wal") else 0
    with get_connection() as conn:
        qc = conn.execute("PRAGMA quick_check").fetchone()[0]
        counts = {}
        for t in ("nicks", "field_values", "nick_contacts", "nick_identities",
                  "sources", "forums", "trash_nicks"):
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return {"path": DB_PATH, "size": size, "wal": wal, "quick_check": qc,
            "counts": counts, "fts": FTS_AVAILABLE}

def vacuum():
    """כיווץ הקובץ (אחרי מחיקות גדולות). מחזיר את הגודל החדש."""
    conn = get_connection()
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    return os.path.getsize(DB_PATH)

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
                last_seen TEXT DEFAULT '',
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

            -- היסטוריית שינויים לשדות "מעניינים" (field_values שומר רק את הערך
            -- האחרון לכל מקור, ולכן בלי זה אין ציר זמן)
            CREATE TABLE IF NOT EXISTS field_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nick_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT DEFAULT '',
                new_value TEXT DEFAULT '',
                changed_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (nick_id) REFERENCES nicks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_hist_nick ON field_history(nick_id, changed_at);

            -- ניקים שנצפו לאחרונה. טבלה ולא JSON בהגדרות: CASCADE מנקה לבד
            -- ניק שנמחק, ואין מרוץ בין שני כותבים על אותה מחרוזת.
            CREATE TABLE IF NOT EXISTS recent_views (
                nick_id INTEGER PRIMARY KEY,
                seq INTEGER NOT NULL DEFAULT 0,
                viewed_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
                FOREIGN KEY (nick_id) REFERENCES nicks(id) ON DELETE CASCADE
            );
            -- הסדר לפי מונה עולה ולא לפי חותמת זמן: גם ברזולוציית מילישנייה
            -- שתי צפיות רצופות מקבלות את אותו ערך, והגיזום היה שרירותי.
            CREATE INDEX IF NOT EXISTS idx_recent_seq ON recent_views(seq DESC);

            -- יומן סריקות + מה השתנה בכל אחת
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                forum TEXT DEFAULT '',
                started_at TEXT DEFAULT (datetime('now')),
                finished_at TEXT DEFAULT '',
                added INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
                unchanged INTEGER DEFAULT 0, failed_pages INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS scan_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                nick_id INTEGER, forum TEXT DEFAULT '', username TEXT DEFAULT '',
                kind TEXT DEFAULT 'changed',      -- 'new' | 'changed'
                field_name TEXT DEFAULT '', old_value TEXT DEFAULT '', new_value TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_scan_changes_run ON scan_changes(run_id);

            -- הצעות זהות שהמשתמש דחה (לא להציע שוב)
            CREATE TABLE IF NOT EXISTS identity_dismissed (
                nick_id_a INTEGER NOT NULL, nick_id_b INTEGER NOT NULL,
                PRIMARY KEY (nick_id_a, nick_id_b)
            );

            -- סל מחזור: צילום מלא של ניק שנמחק (כולל אנשי קשר, זהויות, מקורות)
            -- כדי ש"בטל" ישחזר הכול. נשמר 30 יום.
            CREATE TABLE IF NOT EXISTS trash_nicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                nick_id INTEGER NOT NULL,
                forum TEXT DEFAULT '',
                username TEXT DEFAULT '',
                deleted_at TEXT DEFAULT (datetime('now')),
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trash_batch      ON trash_nicks(batch_id);
            CREATE INDEX IF NOT EXISTS idx_trash_deleted    ON trash_nicks(deleted_at);

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
            CREATE INDEX IF NOT EXISTS idx_nicks_forum_username ON nicks(forum, username);
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
        # מקטעים שאינם עמודות (אנשי קשר / זהויות) — אותה טבלה, מפתחות נפרדים
        for key, _, default_sync in EXTRA_SYNC_KEYS:
            conn.execute(
                "INSERT OR IGNORE INTO sync_settings (field_key, synced) VALUES (?,?)",
                (key, 1 if default_sync else 0))

    # Migrations for existing DBs
    _migrate()
    _init_fts()
    _backfill_sources()
    # סל המחזור נשמר 30 יום; היסטוריה ויומן סריקות — שנה (אחרת גדלים בלי גבול)
    try:
        empty_trash(30)
        with get_connection() as conn:
            conn.execute("DELETE FROM field_history WHERE changed_at < datetime('now','-365 days')")
            old_runs = [r[0] for r in conn.execute(
                "SELECT id FROM scan_runs WHERE started_at < datetime('now','-365 days')")]
            for chunk in _chunks(old_runs, 400):
                ph = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM scan_changes WHERE run_id IN ({ph})", chunk)
                conn.execute(f"DELETE FROM scan_runs WHERE id IN ({ph})", chunk)
    except Exception:
        pass
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

def _digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _phone_norm_sql(col):
    """ביטוי SQL שמשאיר רק ספרות (בקירוב): מסיר מקפים, רווחים, סוגריים ו-+."""
    return (f"REPLACE(REPLACE(REPLACE(REPLACE(REPLACE({col},'-',''),' ',''),"
            f"'(',''),')',''),'+','')")

def _search_where(search, match_expr, fuzzy=False):
    """
    תנאי החיפוש המהיר המשולב — מחזיר (where_sql, params):
      • עמודות הניק דרך FTS (או LIKE כשאין FTS5),
      • טלפונים/מיילים נוספים (nick_contacts) — בעבר היו בלתי נראים לחיפוש,
      • התאמת טלפון מנורמל: '050-123-4567' נמצא גם כ-'0501234567' וגם כ-'972501234567'.
    """
    parts, params = [], []
    if match_expr and FTS_AVAILABLE:
        parts.append("n.id IN (SELECT rowid FROM nicks_fts WHERE nicks_fts MATCH ?)")
        params.append(match_expr)
    else:
        s = f"%{search}%"
        parts.append("(" + " OR ".join(f"n.{c} LIKE ?" for c in _SEARCH_COLS) + ")")
        params.extend([s] * len(_SEARCH_COLS))
    if fuzzy:
        # חיפוש תת-מחרוזת: FTS מוצא רק תחילת מילה, ולכן "כהן" לא מצא "משהכהן".
        # מופעל רק כשהחיפוש הרגיל כמעט לא החזיר תוצאות (סריקה מלאה — יקר).
        s = f"%{search.strip()}%"
        parts.append("(" + " OR ".join(f"n.{c} LIKE ?" for c in _SEARCH_COLS) + ")")
        params.extend([s] * len(_SEARCH_COLS))
    parts.append("n.id IN (SELECT nick_id FROM nick_contacts WHERE value LIKE ?)")
    params.append(f"%{search}%")
    digits = _digits(search)
    if len(digits) >= 5 and len(digits) >= len(search.strip()) - 4:
        variants = {digits}
        if digits.startswith("0"):
            variants.add("972" + digits[1:])
        elif digits.startswith("972"):
            variants.add("0" + digits[3:])
        for d in variants:
            parts.append(f"{_phone_norm_sql('n.phone')} LIKE ?")
            parts.append(f"n.id IN (SELECT nick_id FROM nick_contacts WHERE "
                         f"{_phone_norm_sql('value')} LIKE ?)")
            params.extend([f"%{d}%", f"%{d}%"])
    return "WHERE " + " OR ".join(parts), params

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
                    "scraped_real_name", "scraped_email", "full_name", "forum_uid",
                    "last_seen"]:
            if col not in existing:
                conn.execute(f"ALTER TABLE nicks ADD COLUMN {col} TEXT DEFAULT ''")
        ctcols = {row[1] for row in conn.execute("PRAGMA table_info(nick_contacts)")}
        if "is_private" not in ctcols:
            conn.execute("ALTER TABLE nick_contacts ADD COLUMN is_private INTEGER DEFAULT 0")
        # migration לפורומים
        rvcols = {row[1] for row in conn.execute("PRAGMA table_info(recent_views)")}
        if rvcols and "seq" not in rvcols:
            conn.execute("ALTER TABLE recent_views ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_recent_seq ON recent_views(seq DESC)")
        fcols = {row[1] for row in conn.execute("PRAGMA table_info(forums)")}
        if "profile_pattern" not in fcols:
            conn.execute("ALTER TABLE forums ADD COLUMN profile_pattern TEXT DEFAULT ''")
        if "platform" not in fcols:
            conn.execute("ALTER TABLE forums ADD COLUMN platform TEXT DEFAULT 'nodebb'")
        # ניקוי חד-פעמי: העברת 'uid:...' שנשמר בעבר ב-extra_info אל forum_uid
        try:
            done = conn.execute(
                "SELECT value FROM settings WHERE key='uid_cleanup_done'").fetchone()
            rows = [] if done else conn.execute(
                "SELECT id, extra_info FROM nicks WHERE extra_info LIKE 'uid:%'").fetchall()
            for rid, ei in rows:
                uid = str(ei).split("uid:", 1)[1].strip() if "uid:" in str(ei) else ""
                conn.execute(
                    "UPDATE nicks SET forum_uid=?, extra_info='' WHERE id=?", (uid, rid))
            # ניקוי חד-פעמי: בלי הדגל הוא סרק את כל הניקים בכל הפעלה
            # (LIKE 'uid:%' בלי אינדקס) רק כדי לגלות שאין מה לעשות.
            if not done:
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES "
                             "('uid_cleanup_done', '1')")
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
    for key, _, default in EXTRA_SYNC_KEYS:
        if key not in result:
            result[key] = default
    return result

def sync_enabled(key, default=True):
    """דגל סנכרון למקטע בקובץ שאינו עמודה (contacts / identities)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT synced FROM sync_settings WHERE field_key=?", (key,)).fetchone()
    return bool(row[0]) if row else default

def set_sync_setting(field_key, synced: bool):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sync_settings (field_key, synced) VALUES (?,?)",
            (field_key, 1 if synced else 0))

def set_sync_settings(mapping):
    """שמירה מרוכזת של כל דגלי הסנכרון בטרנזקציה אחת (במקום קריאת גשר לכל שדה)."""
    with get_connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO sync_settings (field_key, synced) VALUES (?,?)",
            [(k, 1 if v else 0) for k, v in (mapping or {}).items()])

def set_forum_io_flags(mapping):
    """שמירה מרוכזת של דגלי ייבוא/ייצוא לפורומים."""
    with get_connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
            [(f"forumio_{name}", "1" if inc else "0") for name, inc in (mapping or {}).items()])

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
    # בלי חיפוש: הסדר הקיים (has_info קודם) — מי שמדפדף רואה קודם את מה שכבר
    # העשיר. עם חיפוש זה הפוך: מי שהקליד "לומדעס" רוצה את הניק לומדעס ראשון,
    # ולא ניק אחר שרק מזכיר אותו בהערות. הרלוונטיות גוברת, ו-has_info נשאר
    # שובר שוויון בתוך אותה דרגת התאמה.
    term = (search or "").strip()
    rank_select, rank_params = "", []
    if term:
        rank_select = """,
                CASE
                  WHEN n.username = ?                      THEN 0
                  WHEN n.username LIKE ?                   THEN 1
                  WHEN n.username LIKE ?                   THEN 2
                  WHEN n.real_name = ? OR n.full_name = ?  THEN 3
                  WHEN n.real_name LIKE ? OR n.full_name LIKE ? THEN 4
                  ELSE 5
                END AS rank"""
        rank_params = [term, term + "%", "%" + term + "%",
                       term, term, term + "%", term + "%"]

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
            {rank_select}
            FROM nicks n
        """
        order_clause = ("ORDER BY rank ASC, has_info DESC, n.trust_level DESC, n.updated_at DESC"
                        if term else
                        "ORDER BY has_info DESC, n.trust_level DESC, n.updated_at DESC")
        limit_clause = ""
        params_extra = []
        if limit is not None:
            limit_clause = "LIMIT ? OFFSET ?"
            params_extra = [limit, offset]

        match_expr = _fts_match_query(search) if search else None

        if search:
            where, params = _search_where(search, match_expr)
            total = conn.execute(
                f"SELECT COUNT(*) FROM nicks n {where}", params).fetchone()[0]
            # כמעט בלי תוצאות? נסה תת-מחרוזת (סלחני יותר בעברית) — בדיוק המצב
            # שבו המשתמש זקוק לעזרה. זו סריקה מלאה, ולכן מוגבלת בכמות.
            if total < 5 and len(search.strip()) >= 2:
                where, params = _search_where(search, match_expr, fuzzy=True)
                total = conn.execute(
                    f"SELECT COUNT(*) FROM nicks n {where}", params).fetchone()[0]
                if limit is None:
                    limit_clause, params_extra = "LIMIT ? OFFSET 0", [500]
            rows = conn.execute(
                base_select + where + f" {order_clause} {limit_clause}",
                rank_params + params + params_extra).fetchall()
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
    ("last_seen","נראה לאחרונה"),("post_count","מספר הודעות"),("trust_level","רמת אמינות"),
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

def _existing_ids(conn, ids):
    """מסנן מזהים שכבר נמחקו — אחרת FK מפיל את כל הפעולה על בחירה ישנה."""
    live = set()
    for chunk in _chunks(list(ids), 400):
        ph = ",".join("?" * len(chunk))
        live.update(r[0] for r in conn.execute(
            f"SELECT id FROM nicks WHERE id IN ({ph})", list(chunk)))
    return live

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
    # הכרעה מחדש. פעם היה כאן COUNT(*)>1, ואז ריקון ערך אצל ניק שיש לו מקור
    # אחד בלבד (הסריקה) לא הכריע מחדש: ה-cache נשאר ריק בזמן ש-field_values
    # עדיין החזיק את הערך — הניק "איבד" סטטוס/שם והפסיק להיספר בסטטיסטיקות.
    if field not in _NON_SOURCED:
        with get_connection() as conn:
            remaining = set()
            for chunk in _chunks(ids, 400):
                ph = ",".join("?" * len(chunk))
                remaining.update(r[0] for r in conn.execute(
                    f"""SELECT DISTINCT nick_id FROM field_values
                        WHERE field_name=? AND nick_id IN ({ph})""",
                    [field] + list(chunk)).fetchall())
            for nid in remaining:
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
    digits = _digits(q)
    phone_sql, phone_params = "", []
    if len(digits) >= 5:
        variants = {digits} | ({"972" + digits[1:]} if digits.startswith("0") else set())
        for d in variants:
            phone_sql += (f" OR {_phone_norm_sql('phone')} LIKE ?"
                          f" OR id IN (SELECT nick_id FROM nick_contacts WHERE {_phone_norm_sql('value')} LIKE ?)")
            phone_params += [f"%{d}%", f"%{d}%"]
    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT id, username, forum, real_name, full_name FROM nicks
            WHERE username LIKE ? OR real_name LIKE ? OR full_name LIKE ?
               OR id IN (SELECT nick_id FROM nick_contacts WHERE value LIKE ?){phone_sql}
            ORDER BY
              CASE WHEN username = ? THEN 0
                   WHEN username LIKE ? THEN 1
                   ELSE 2 END,
              username
            LIMIT ?
        """, [like, like, like, like] + phone_params + [q, q + "%", limit]).fetchall()
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
                        "status", "join_date", "post_count", "avatar_url", "last_seen",
                        "nick_color", "avatar_image", "extra_info", "forum_uid"]

def merge_scraped_users(forum, users, source_label="סריקה", run_id=None):
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
                    # ניק חדש — אין "היסטוריה" (הוא נרשם ממילא כ-new ביומן הסריקה),
                    # ובלעדי זה נוצר אירוע שקרי "פעיל → מורחק" לכל מורחק שנתגלה
                    _resolve_fields_conn(conn, nid, list(new_vals), history=False)
                if run_id:
                    conn.execute(
                        "INSERT INTO scan_changes (run_id, nick_id, forum, username, kind) "
                        "VALUES (?,?,?,?,'new')", (run_id, nid, forum, username))
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
            if run_id:
                notable = [(run_id, nid, forum, username, "changed", f,
                            str(old.get(f, "") or ""), str(v))
                           for f, v in changed.items() if f in _HISTORY_FIELDS]
                if notable:
                    conn.executemany(
                        "INSERT INTO scan_changes (run_id, nick_id, forum, username, kind, "
                        "field_name, old_value, new_value) VALUES (?,?,?,?,?,?,?,?)", notable)
            stats["updated"] += 1
    return stats

_NICK_FIELDS = ["forum","username","groups","reputation","real_name","full_name","phone","email",
                "notes","private_notes","extra_info","address","status","join_date","post_count",
                "last_seen","avatar_url","nick_color","avatar_image","source","forum_uid",
                "scraped_real_name","scraped_email","trust_level"]

# שדות שמתועדים בציר הזמן (השאר — מוניטין/ספירת הודעות — משתנים כל הזמן)
_HISTORY_FIELDS = {"status", "real_name", "full_name", "phone", "email", "address", "groups"}

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
    """
    מתעדכנות רק העמודות שנשלחו ב-data. בעבר נכתבו כל העמודות עם data.get(f,''),
    וטופס העריכה לא שולח את scraped_email/scraped_real_name — כך שכל שמירה של
    ניק מחקה אותם בשקט, ומאז email != scraped_email הפך כל ניק שנערך ל"ניק עם
    מידע". מפתח שקיים עם ערך ריק עדיין מנקה — זה הריקון הידני.
    """
    upd_fields = [f for f in _NICK_FIELDS if f != "source" and f in data]
    if not upd_fields:
        return
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
    return delete_nicks([nick_id])

def delete_nicks(nick_ids):
    """
    מחיקה מרובה דרך סל המחזור: לכל ניק נשמר צילום מלא (השורה, אנשי קשר, זהויות,
    ערכי מקורות, מדף, התנגשויות) ב-trash_nicks, ורק אז נמחק. "בטל" משחזר הכול.
    מחזיר {"deleted": n, "batch_id": id}.
    """
    import uuid
    ids = [int(i) for i in (nick_ids or [])]
    if not ids:
        return {"deleted": 0, "batch_id": None}
    batch = uuid.uuid4().hex
    deleted = 0
    with get_connection() as conn:
        for chunk in _chunks(ids, 400):
            ph = ",".join("?" * len(chunk))
            snap = {}
            for r in conn.execute(f"SELECT * FROM nicks WHERE id IN ({ph})", chunk):
                snap[r["id"]] = {"nick": dict(r), "contacts": [], "identities": [],
                                 "field_values": [], "shelved": [], "conflicts": [],
                                 "history": []}
            if not snap:
                continue
            for r in conn.execute(f"SELECT * FROM nick_contacts WHERE nick_id IN ({ph})", chunk):
                snap[r["nick_id"]]["contacts"].append(dict(r))
            for r in conn.execute(
                    f"SELECT nick_id_a, nick_id_b FROM nick_identities "
                    f"WHERE nick_id_a IN ({ph}) OR nick_id_b IN ({ph})", chunk + chunk):
                for nid in (r[0], r[1]):
                    if nid in snap:
                        snap[nid]["identities"].append([r[0], r[1]])
            for r in conn.execute(
                    f"SELECT nick_id, field_name, value, source_id, created_at "
                    f"FROM field_values WHERE nick_id IN ({ph})", chunk):
                snap[r["nick_id"]]["field_values"].append(dict(r))
            for r in conn.execute(f"SELECT * FROM shelved_values WHERE nick_id IN ({ph})", chunk):
                snap[r["nick_id"]]["shelved"].append(dict(r))
            for r in conn.execute(f"SELECT * FROM nick_conflicts WHERE nick_id IN ({ph})", chunk):
                snap[r["nick_id"]]["conflicts"].append(dict(r))
            # field_history מוגדר ON DELETE CASCADE — בלי צילום, ציר הזמן של הניק
            # נמחק לתמיד גם אחרי "בטל" או שחזור מסל המחזור.
            for r in conn.execute(
                    f"SELECT nick_id, field_name, old_value, new_value, changed_at "
                    f"FROM field_history WHERE nick_id IN ({ph})", chunk):
                snap[r["nick_id"]]["history"].append(dict(r))
            conn.executemany(
                "INSERT INTO trash_nicks (batch_id, nick_id, forum, username, payload) "
                "VALUES (?,?,?,?,?)",
                [(batch, nid, s["nick"]["forum"], s["nick"]["username"],
                  json.dumps(s, ensure_ascii=False)) for nid, s in snap.items()])
            cur = conn.execute(f"DELETE FROM nicks WHERE id IN ({ph})", chunk)
            deleted += cur.rowcount
    return {"deleted": deleted, "batch_id": batch}

def restore_trash(batch_id=None, trash_ids=None):
    """
    משחזר ניקים מסל המחזור (לפי batch או לפי רשומות). ניק שבינתיים נוצר מחדש
    (אותו פורום+שם) מדולג. מחזיר {"restored": n, "skipped": n}.
    """
    restored = skipped = 0
    with get_connection() as conn:
        if trash_ids:
            ph = ",".join("?" * len(trash_ids))
            rows = conn.execute(f"SELECT * FROM trash_nicks WHERE id IN ({ph})",
                                [int(i) for i in trash_ids]).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trash_nicks WHERE batch_id=?", (batch_id,)).fetchall()
        forums = {r[0] for r in conn.execute("SELECT name FROM forums")}
        handled = []
        payloads = []
        for r in rows:
            s = json.loads(r["payload"])
            payloads.append(s)
            n = s["nick"]
            if conn.execute("SELECT 1 FROM nicks WHERE forum=? AND username=?",
                            (n["forum"], n["username"])).fetchone():
                skipped += 1
                handled.append(r["id"])
                continue
            if n["forum"] not in forums:
                conn.execute("INSERT OR IGNORE INTO forums (name, color, url) VALUES (?,?,'')",
                             (n["forum"], "#8b90a0"))
                forums.add(n["forum"])
            # שמות עמודות מהסכימה החיה בלבד (payload הוא JSON — לא מקור לזיהוי SQL)
            valid = {r[1] for r in conn.execute("PRAGMA table_info(nicks)")}
            cols = [c for c in n if c in valid]
            conn.execute(
                f"INSERT OR IGNORE INTO nicks ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [n[c] for c in cols])
            nid = n["id"]
            for c in s.get("contacts", []):
                conn.execute(
                    "INSERT INTO nick_contacts (nick_id, type, value, label, is_private) VALUES (?,?,?,?,?)",
                    (nid, c["type"], c["value"], c.get("label", ""), c.get("is_private", 0)))
            for fv in s.get("field_values", []):
                # רק אם המקור עדיין קיים
                conn.execute(
                    "INSERT OR IGNORE INTO field_values (nick_id, field_name, value, source_id, created_at) "
                    "SELECT ?,?,?,?,? WHERE EXISTS (SELECT 1 FROM sources WHERE id=?)",
                    (nid, fv["field_name"], fv["value"], fv["source_id"], fv["created_at"], fv["source_id"]))
            for sh in s.get("shelved", []):
                conn.execute(
                    "INSERT INTO shelved_values (nick_id, field_name, value, source_name, source_trust) "
                    "VALUES (?,?,?,?,?)",
                    (nid, sh["field_name"], sh["value"], sh.get("source_name", ""), sh.get("source_trust", 0)))
            for hh in s.get("history", []):
                conn.execute(
                    "INSERT INTO field_history (nick_id, field_name, old_value, new_value, "
                    "changed_at) VALUES (?,?,?,?,?)",
                    (nid, hh["field_name"], hh.get("old_value", ""), hh.get("new_value", ""),
                     hh.get("changed_at")))
            for cf in s.get("conflicts", []):
                conn.execute(
                    "INSERT INTO nick_conflicts (nick_id, field_name, conflicting_value, source_info) "
                    "VALUES (?,?,?,?)",
                    (nid, cf["field_name"], cf["conflicting_value"], cf.get("source_info", "")))
            restored += 1
            handled.append(r["id"])
        # הכרעה מחדש לכל ניק ששוחזר: ערכים שמקורם נמחק בינתיים לא חוזרים
        # (ה-INSERT מותנה בקיום המקור), ובלי הכרעה ה-cache היה ממשיך להציג אותם.
        for s in payloads:
            n = s["nick"]
            fields = {fv["field_name"] for fv in s.get("field_values", [])}
            if fields and conn.execute("SELECT 1 FROM nicks WHERE id=?", (n["id"],)).fetchone():
                _resolve_fields_conn(conn, n["id"], sorted(fields), history=False)
        # זהויות — אחרי שכל הניקים של האצווה חזרו (שני הצדדים חייבים להתקיים)
        for s in payloads:
            for a, b in s.get("identities", []):
                if (conn.execute("SELECT 1 FROM nicks WHERE id=?", (a,)).fetchone()
                        and conn.execute("SELECT 1 FROM nicks WHERE id=?", (b,)).fetchone()):
                    conn.execute("INSERT OR IGNORE INTO nick_identities (nick_id_a, nick_id_b) VALUES (?,?)",
                                 (min(a, b), max(a, b)))
        for chunk in _chunks(handled, 400):
            conn.execute(f"DELETE FROM trash_nicks WHERE id IN ({','.join('?' * len(chunk))})", chunk)
    return {"restored": restored, "skipped": skipped}

def list_trash(limit=200):
    """אצוות מחיקה בסל, מהחדשה לישנה: batch_id, deleted_at, count, names (דוגמית)."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT batch_id, MIN(deleted_at) AS deleted_at, COUNT(*) AS count,
                   substr(GROUP_CONCAT(username, ' · '), 1, 160) AS names
            FROM trash_nicks GROUP BY batch_id
            ORDER BY deleted_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]

def empty_trash(older_than_days=None):
    with get_connection() as conn:
        if older_than_days is None:
            cur = conn.execute("DELETE FROM trash_nicks")
        else:
            cur = conn.execute("DELETE FROM trash_nicks WHERE deleted_at < datetime('now', ?)",
                               (f"-{int(older_than_days)} days",))
        return cur.rowcount

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
        conn.execute("DELETE FROM trash_nicks")   # "מחיקה לגמרי" חייבת לרוקן גם את הסל
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
        # nicks הוא cache בלבד. בלי מחיקת field_values הערך "המנוקה" חוזר בהכרעה
        # הבאה (סריקה, עריכה, שינוי אמינות של מקור) — והמשתמש שביקש למחוק
        # טלפונים מהמאגר נשאר איתם בפועל.
        sourced = [c for c in cols if c not in _NON_SOURCED]
        if sourced:
            ph = ",".join("?" * len(sourced))
            conn.execute(f"DELETE FROM field_values WHERE field_name IN ({ph})", sourced)
            conn.execute(f"DELETE FROM shelved_values WHERE field_name IN ({ph})", sourced)
            conn.execute(f"DELETE FROM field_history WHERE field_name IN ({ph})", sourced)
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

def _contact_key(ctype, value):
    """'050-123-4567', '0501234567' ו-'+972501234567' הם אותו איש קשר."""
    v = str(value or "").strip()
    if ctype == "phone":
        d = _digits(v)
        if d.startswith("00972"):
            d = "0" + d[5:]
        elif d.startswith("972"):
            d = "0" + d[3:]
        return ("phone", d)
    return (str(ctype or ""), v.lower())

def _import_contacts_conn(conn, pairs):
    """
    pairs: [(nick_id, [{type,value,label}, …]), …] על חיבור קיים.
    מוסיף רק מה שאינו קיים (לפי _contact_key) — שליפה אחת למנה של 400 ניקים
    וכתיבה אחת, כדי שייבוא חוזר של אותו קובץ לא יכפיל דבר. מחזיר כמה נוספו.
    """
    ids = sorted({nid for nid, cts in pairs if cts})
    if not ids:
        return 0
    seen = set()
    for chunk in _chunks(ids, 400):
        ph = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT nick_id, type, value FROM nick_contacts WHERE nick_id IN ({ph})",
                list(chunk)):
            seen.add((r["nick_id"],) + _contact_key(r["type"], r["value"]))
    to_add = []
    for nid, cts in pairs:
        for c in (cts or [])[:MAX_CONTACTS_PER_NICK]:
            if not isinstance(c, dict):
                continue
            ctype = str(c.get("type", "")).strip().lower()
            value = str(c.get("value", "")).strip()[:200]
            if ctype not in CONTACT_TYPES or not value:
                continue
            key = (nid,) + _contact_key(ctype, value)
            if key in seen:
                continue
            seen.add(key)
            # אנשי קשר מיובאים תמיד גלויים: "סודי" הוא סימון אישי של מי שקלט,
            # ולא משהו שקובץ מבחוץ יכול לקבוע.
            to_add.append((nid, ctype, value, str(c.get("label", "") or "")[:60], 0))
    if to_add:
        conn.executemany(
            "INSERT INTO nick_contacts (nick_id, type, value, label, is_private) "
            "VALUES (?,?,?,?,?)", to_add)
    return len(to_add)

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

def _identity_group_many(conn, nick_ids):
    """
    הסגור הטרנזיטיבי של קבוצת ניקים ב-BFS אחד. ה-frontier נחתך למנות של 400
    (=800 פרמטרים) — מגבלת SQLite היא 999, וקבוצה גדולה הייתה מפילה את השאילתה.
    """
    group = {int(n) for n in nick_ids}
    frontier = set(group)
    while frontier:
        new = set()
        for chunk in _chunks(sorted(frontier), 400):
            ph = ",".join(["?"] * len(chunk))
            for a, b in conn.execute(f"""
                SELECT nick_id_a, nick_id_b FROM nick_identities
                WHERE nick_id_a IN ({ph}) OR nick_id_b IN ({ph})
            """, list(chunk) * 2):
                for x in (a, b):
                    if x not in group:
                        group.add(x); new.add(x)
        frontier = new
    return group

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
    מוציא מקבוצת הזהות את הניק שלחצת ליד ה-✕ שלו (other_nick_id): מנתק אותו
    מכל חברי הקבוצה, ושאר החברים נשארים מקושרים ביניהם.
    לדוגמה: פתחת את "בני" ולחצת ✕ ליד "בני1" → "בני1" יוצא, "בני" נשאר מקושר לשאר.
    (עד 0.8.5 יצא דווקא הניק הפתוח, והרשימה נראתה כאילו נמחקה כולה.)
    הקבוצה שמורה כסגור טרנזיטיבי מלא, ולכן מחיקת זוג בודד לא הייתה מנתקת דבר.
    """
    with get_connection() as conn:
        group = _identity_group(conn, other_nick_id)
        group.discard(other_nick_id)
        for other in group:
            a, b = min(other_nick_id, other), max(other_nick_id, other)
            conn.execute(
                "DELETE FROM nick_identities WHERE nick_id_a=? AND nick_id_b=?", (a, b))

# ── נצפו לאחרונה ─────────────────────────────────────────────────────
RECENT_VIEWS_KEEP = 30

def touch_recent(nick_id):
    """רושם צפייה בניק. PRIMARY KEY על nick_id = צפייה חוזרת מקדמת, לא מכפילה."""
    try:
        with get_connection() as conn:
            if not conn.execute("SELECT 1 FROM nicks WHERE id=?", (int(nick_id),)).fetchone():
                return False
            conn.execute(
                "INSERT INTO recent_views (nick_id, seq, viewed_at) VALUES "
                "(?, (SELECT IFNULL(MAX(seq),0)+1 FROM recent_views), "
                " strftime('%Y-%m-%d %H:%M:%f','now')) "
                "ON CONFLICT(nick_id) DO UPDATE SET "
                "seq=(SELECT IFNULL(MAX(seq),0)+1 FROM recent_views), "
                "viewed_at=strftime('%Y-%m-%d %H:%M:%f','now')", (int(nick_id),))
            conn.execute(
                "DELETE FROM recent_views WHERE nick_id NOT IN "
                "(SELECT nick_id FROM recent_views ORDER BY seq DESC LIMIT ?)",
                (RECENT_VIEWS_KEEP,))
        return True
    except (ValueError, TypeError, sqlite3.Error):
        return False

def get_recent_views(limit=12):
    """הניקים שנצפו לאחרונה. ניק שנמחק נעלם לבד דרך CASCADE."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT n.id, n.username, n.forum, n.status, n.real_name, n.nick_color,
                   r.viewed_at
            FROM recent_views r JOIN nicks n ON n.id = r.nick_id
            ORDER BY r.seq DESC LIMIT ?""", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

def clear_recent_views():
    with get_connection() as conn:
        conn.execute("DELETE FROM recent_views")

# ── מפת זהויות ───────────────────────────────────────────────────────
IDENTITY_MAP_LIMIT = 3000
# שדות שסתירה ביניהם בתוך קבוצה היא מידע אמיתי (או קישור שגוי, או ידיעה חדשה).
_IDENTITY_CONFLICT_FIELDS = [("real_name", "שם אמיתי"), ("phone", "טלפון"),
                             ("email", "מייל"), ("full_name", "שם מלא")]

def get_identity_map(limit=IDENTITY_MAP_LIMIT):
    """
    כל קבוצות הזהות, בשתי שאילתות: אחת על nick_identities ואחת על הניקים
    שמופיעים בהן. **לא** סורק את טבלת הניקים כולה, ולא מחזיר avatar_image
    (כלל מטען הרשימות מ-0.8.3) — רק has_avatar.

    הקיבוץ הוא union-find ולא הנחת קליקה: קבוצה יכולה להיות לא-סגורה אחרי
    שחזור חלקי מסל המחזור, ואיחוד לפי צמתים נכון לכל צורת גרף.
    """
    with get_connection() as conn:
        edges = conn.execute(
            "SELECT nick_id_a, nick_id_b FROM nick_identities").fetchall()
        if not edges:
            return {"groups": [], "total_groups": 0, "linked_nicks": 0, "truncated": False}

        parent = {}
        def find(x):
            root = x
            while parent.get(root, root) != root:
                root = parent[root]
            while parent.get(x, x) != x:      # path compression
                parent[x], x = root, parent[x]
            return root
        for a, b in edges:
            parent.setdefault(a, a); parent.setdefault(b, b)
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        buckets = {}
        for nid in parent:
            buckets.setdefault(find(nid), []).append(nid)
        groups_ids = [m for m in buckets.values() if len(m) > 1]
        total_groups = len(groups_ids)
        linked = sum(len(m) for m in groups_ids)
        groups_ids.sort(key=len, reverse=True)
        truncated = len(groups_ids) > limit
        groups_ids = groups_ids[:limit]

        wanted = sorted({n for m in groups_ids for n in m})
        rows = {}
        cols = ("id, forum, username, status, real_name, full_name, phone, email, "
                "nick_color, updated_at, (avatar_image IS NOT NULL AND avatar_image != '') "
                "AS has_avatar")
        for chunk in _chunks(wanted, 400):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(f"SELECT {cols} FROM nicks WHERE id IN ({ph})", list(chunk)):
                rows[r["id"]] = dict(r)

    out = []
    for members in groups_ids:
        ms = [rows[i] for i in members if i in rows]
        if len(ms) < 2:
            continue                       # ניק שנמחק והשאיר קישור יתום
        ms.sort(key=lambda r: (r["forum"] or "", r["username"] or ""))
        conflicts = []
        for key, label in _IDENTITY_CONFLICT_FIELDS:
            vals = {str(r.get(key) or "").strip() for r in ms}
            vals.discard("")
            if len(vals) > 1:
                conflicts.append(label)
        out.append({
            "members": ms,
            "size": len(ms),
            "forums": sorted({r["forum"] for r in ms if r["forum"]}),
            "forum_count": len({r["forum"] for r in ms if r["forum"]}),
            "banned": sum(1 for r in ms if (r.get("status") or "") == "מורחק"),
            "conflicts": conflicts,
            "updated_at": max((r.get("updated_at") or "") for r in ms),
        })
    out.sort(key=lambda g: (g["size"], g["forum_count"], g["updated_at"]), reverse=True)
    return {"groups": out, "total_groups": total_groups, "linked_nicks": linked,
            "truncated": truncated}

def repair_identity_groups():
    """
    משלים קישורים חסרים כך שכל קבוצה תהיה סגורה (כל זוג שמור), כפי ששאר הקוד
    מניח. קבוצה לא-סגורה יכולה להיווצר משחזור חלקי מסל המחזור.
    מחזיר כמה קישורים נוספו.
    """
    added = 0
    with get_connection() as conn:
        edges = conn.execute("SELECT nick_id_a, nick_id_b FROM nick_identities").fetchall()
        if not edges:
            return 0
        parent = {}
        def find(x):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
            return x
        have = set()
        for a, b in edges:
            parent.setdefault(a, a); parent.setdefault(b, b)
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
            have.add((min(a, b), max(a, b)))
        buckets = {}
        for nid in parent:
            buckets.setdefault(find(nid), []).append(nid)
        missing = []
        for members in buckets.values():
            if len(members) < 3 or len(members) > MAX_IDENTITY_GROUP:
                continue
            members.sort()
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    pair = (members[i], members[j])
                    if pair not in have:
                        missing.append(pair)
        if missing:
            conn.executemany(
                "INSERT OR IGNORE INTO nick_identities (nick_id_a, nick_id_b) VALUES (?,?)",
                missing)
            added = len(missing)
    return added

# ── הגדרות תצוגה ─────────────────────────────────────────────────────
DEFAULT_DISPLAY = {
    "theme":        "dark",     # dark | light | system
    "accent":       "amber",     # teal|indigo|emerald|sky|violet|amber|rose|slate
    "view":         "table",    # table | cards
    "density":      "normal",   # compact | normal | cozy
    "hidden_cols":  "",         # comma-separated column keys
    "col_layout":   "",         # JSON: {"order":[keys],"w":{key:px}} — רוחב וסדר עמודות
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

def _contacts_for_export(conn):
    """
    אנשי הקשר הניתנים לשיתוף, מקובצים לפי nick_id, בשאילתה אחת.
    is_private=1 לא יוצא לעולם: הממשק מבטיח "🔒 סודי (לא יסונכרן בייצוא)",
    וזו הבטחה מוחלטת שאינה תלויה בשום מתג.
    """
    out = {}
    for r in conn.execute(
            "SELECT nick_id, type, value, label FROM nick_contacts "
            "WHERE is_private=0 AND value != '' ORDER BY nick_id, type, id"):
        rec = {"type": r["type"], "value": r["value"]}
        if r["label"]:
            rec["label"] = r["label"]
        out.setdefault(r["nick_id"], []).append(rec)
    return out

def _identity_groups_for_export(conn, id_key):
    """
    קבוצות זהות כרשימות של {forum, username} — id-ים חסרי משמעות במאגר אחר.
    id_key: {nick_id: (forum, username)} של הניקים שיוצאו בפועל.
    קישור נכלל רק אם *שני* צדדיו יוצאו; אחרת הקובץ היה חושף פורום+שם משתמש
    של ניק שהוחרג במכוון (פורום מכובה, מצב ייצוא, בחירה) — דליפת פרטיות.
    parent/union-find בסריקה אחת, בלי self-join.
    """
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for a, b in conn.execute("SELECT nick_id_a, nick_id_b FROM nick_identities"):
        if a in id_key and b in id_key:
            parent.setdefault(a, a); parent.setdefault(b, b); union(a, b)
    groups = {}
    for nid in parent:
        groups.setdefault(find(nid), []).append(nid)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        out.append([{"forum": id_key[n][0], "username": id_key[n][1]}
                    for n in sorted(members)])
    return out

def export_data(mode="all", ids=None):
    """
    mode: 'all' | 'has_info' (רק ניקים עם מידע מעניין) | 'my_info' (רק ניקים עם מידע שהוספתי בעצמי)
          | 'selected' (רק ה-ids שסופקו — ייצוא חלקי של בחירה/תצוגה).
    """
    exportable = get_exportable_fields()
    io_flags = get_forum_io_flags()   # forum_name -> included?
    id_set = {int(i) for i in ids} if ids is not None else None
    keep = {}       # nick_id -> the record already in `records` (לצירוף אנשי קשר)
    id_key = {}     # nick_id -> (forum, username)  — לזהויות
    with get_connection() as conn:
        rows = conn.execute(_EXPORT_QUERY).fetchall()
    records = []
    for r in rows:
        d = dict(r)
        if id_set is not None and d["id"] not in id_set:
            continue
        # דלג על פורומים שהוחרגו בהגדרות (סעיף 2)
        if io_flags.get(d.get("forum", ""), True) is False:
            continue
        if mode == "has_info" and not d.get("_has_info"):
            continue
        if mode == "my_info" and not d.get("_my_info"):
            continue
        rec = {f: d.get(f, '') for f in exportable}
        records.append(rec)
        keep[d["id"]] = rec
        id_key[d["id"]] = (d.get("forum", ""), d.get("username", ""))

    contacts_n = groups_out = 0
    with get_connection() as conn:
        if sync_enabled("contacts"):
            by_nick = _contacts_for_export(conn)
            for nid, rec in keep.items():
                cts = by_nick.get(nid)
                if cts:
                    rec["contacts"] = cts[:MAX_CONTACTS_PER_NICK]
                    contacts_n += len(rec["contacts"])
        identity_groups = (_identity_groups_for_export(conn, id_key)
                           if sync_enabled("identities") else [])
        groups_out = len(identity_groups)
    return {
        # exported_fields מכיל שמות עמודות בלבד — זו ההבטחה שמחזיקה תאימות
        # לאחור: גרסה ישנה קוראת nicks[] ו-exported_fields ומתעלמת מהשאר.
        "version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "exported_fields": exportable,
        "export_mode": mode,
        "nicks": records,
        "identity_groups": identity_groups,
        "counts": {"nicks": len(records), "contacts": contacts_n, "identity_groups": groups_out},
    }

def get_unknown_forums_in_data(data):
    """מחזיר שמות פורומים בקובץ הייבוא שאינם קיימים במסד.
    במכוון סורק רק nicks[]: פורומים שמוזכרים ב-identity_groups הם תמיד תת-קבוצה
    שלהם (קישור מיוצא רק כששני צדדיו ברשימת הניקים), ולכן אין מה למפות בנפרד."""
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

def update_source(source_id, name=None, notes=None, trust=None, absolute=None, progress_cb=None):
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
        _resolve_fields_bulk(conn, by_nick, progress_cb)

def delete_source(source_id, progress_cb=None):
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
        _resolve_fields_bulk(conn, by_nick, progress_cb)
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

def _winner_row_for(field_name, frows):
    """כמו _winner_for אבל מחזיר את השורה המנצחת — כדי שפאנל "מקורות" יסמן
    בדיוק את הערך שמוצג, ולא ינחש לפי מיון אמינות (שמתעלם מכללי status/מוניטין)."""
    if not frows:
        return None
    if field_name == "reputation":
        scr = [r for r in frows if r["kind"] == "scrape"]
        pool = scr if scr else frows
        return max(pool, key=lambda r: r["created_at"])
    def score(r):
        eff = 10**6 if r["absolute"] else int(r["trust"])
        if field_name == "status" and r["kind"] == "scrape":
            eff = 10**6
        return (eff, r["created_at"])
    return max(frows, key=score)

def _resolve_fields_conn(conn, nick_id, field_names, history=True):
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
    # ציר זמן — רק לשדות משמעותיים (ראה _HISTORY_FIELDS)
    if history:
        # מילוי ראשוני של שדה כן נרשם ("(ריק) → 050…" הוא מידע אמיתי);
        # רעש היצירה של ניק חדש נמנע בכך שהקורא מעביר history=False
        hist = [(nick_id, f, str(cur_row[f] or ""), str(winners[f] or ""))
                for f in changed if f in _HISTORY_FIELDS]
        if hist:
            conn.executemany(
                "INSERT INTO field_history (nick_id, field_name, old_value, new_value) "
                "VALUES (?,?,?,?)", hist)
    sets = ", ".join(f"{f}=?" for f in changed)
    conn.execute(
        f"UPDATE nicks SET {sets}, updated_at=datetime('now') WHERE id=?",
        [winners[f] for f in changed] + [nick_id])

def _resolve_fields_bulk(conn, by_nick, progress_cb=None):
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
    done = 0
    for chunk in _chunks(nids, 400):
        if progress_cb:
            progress_cb(done, len(nids))
        done += len(chunk)
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

# ── יומן סריקות ─────────────────────────────────────────────────────
def start_scan_run(forum):
    with get_connection() as conn:
        return conn.execute("INSERT INTO scan_runs (forum) VALUES (?)", (forum,)).lastrowid

def finish_scan_run(run_id, stats):
    if not run_id:
        return
    with get_connection() as conn:
        conn.execute(
            "UPDATE scan_runs SET finished_at=datetime('now'), added=?, updated=?, "
            "unchanged=?, failed_pages=? WHERE id=?",
            (stats.get("added", 0), stats.get("updated", 0), stats.get("unchanged", 0),
             stats.get("failed_pages", 0), run_id))

def get_scan_runs(limit=30):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT r.*, (SELECT COUNT(*) FROM scan_changes c WHERE c.run_id=r.id) AS changes
            FROM scan_runs r ORDER BY r.id DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]

def get_scan_changes(run_id, limit=500):
    with get_connection() as conn:
        # ORDER BY id ולא kind — מיון לפי kind דחף את כל ה-'changed' לפני ה-'new',
        # וברשימה ארוכה הניקים החדשים נחתכו לגמרי
        rows = conn.execute(
            "SELECT * FROM scan_changes WHERE run_id=? ORDER BY id LIMIT ?",
            (run_id, limit)).fetchall()
        return [dict(r) for r in rows]

def get_field_history(nick_id, limit=100):
    """ציר זמן לניק: מה השתנה, ממה למה ומתי."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT field_name, old_value, new_value, changed_at FROM field_history "
            "WHERE nick_id=? ORDER BY id DESC LIMIT ?", (int(nick_id), limit)).fetchall()
        return [dict(r) for r in rows]

# ── הצעות זהות: אותו אדם בכמה פורומים ────────────────────────────────
def _identity_groups_map(conn):
    """{nick_id: group_key} לכל ניק שכבר מקושר — כדי לא להציע קישור קיים."""
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    for a, b in conn.execute("SELECT nick_id_a, nick_id_b FROM nick_identities"):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    return find

def suggest_identities(limit=60):
    """
    מציע ניקים שנראים כאותו אדם: אותו טלפון / מייל / שם אמיתי / שם מלא,
    בשני ניקים שונים שאינם מקושרים כבר ולא נדחו. מקובץ לפי הערך המשותף.
    """
    out = []
    with get_connection() as conn:
        find = _identity_groups_map(conn)
        dismissed = {(a, b) for a, b in conn.execute(
            "SELECT nick_id_a, nick_id_b FROM identity_dismissed")}
        checks = [
            ("phone", "טלפון זהה", _phone_norm_sql("phone")),
            ("email", "מייל זהה", "lower(trim(email))"),
            ("real_name", "שם אמיתי זהה", "trim(real_name)"),
            ("full_name", "שם מלא זהה", "trim(full_name)"),
        ]
        for field, reason, expr in checks:
            # הסינון "יותר מפורום אחד" נעשה ב-SQL: אחרת קבוצות לא-רלוונטיות היו
            # אוכלות את ה-LIMIT, והדיאלוג היה נראה ריק אף שיש התאמות אמיתיות.
            # אין LIMIT בשאילתה — עוצרים בפייתון כשנאספו מספיק הצעות (השאילתה זורמת).
            cur = conn.execute(f"""
                SELECT {expr} AS k, GROUP_CONCAT(id) AS ids, COUNT(*) AS c
                FROM nicks
                WHERE {field} IS NOT NULL AND trim({field}) != '' AND length(trim({field})) >= 3
                GROUP BY k HAVING c > 1 AND c <= 12 AND COUNT(DISTINCT forum) > 1""")
            for r in cur:
                ids = sorted(int(i) for i in str(r["ids"]).split(","))
                # דלג אם כולם כבר באותה קבוצת זהות
                if len({find(i) for i in ids}) < 2:
                    continue
                # דלג רק אם כל הזוגות בקבוצה נדחו (חבר חדש = הצעה חדשה)
                pairs = {(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))}
                if pairs <= dismissed:
                    continue
                members = [dict(m) for m in conn.execute(
                    f"SELECT id, username, forum, real_name, full_name, phone, email FROM nicks "
                    f"WHERE id IN ({','.join('?' * len(ids))})", ids)]
                out.append({"reason": reason, "field": field,
                            "value": str(r["k"]), "members": members})
                if len(out) >= limit:
                    return out
    return out

def dismiss_identity_suggestion(nick_ids):
    """דוחה קבוצה — נשמרים כל הזוגות שבה, כדי שחבר חדש יפתח הצעה חדשה."""
    ids = sorted(int(i) for i in (nick_ids or []))
    if len(ids) < 2:
        return
    pairs = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
    with get_connection() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO identity_dismissed (nick_id_a, nick_id_b) VALUES (?,?)", pairs)

# ── פעולות מרובות ────────────────────────────────────────────────────
MAX_IDENTITY_GROUP = 50

def bulk_link_identities(nick_ids):
    """
    מקשר את כל הניקים שנבחרו לקבוצת זהות אחת — במעבר אחד.
    (קריאה ל-add_identity לכל חבר בנתה מחדש את כל הקליקה בכל פעם — O(n³);
    בחירה של מאות ניקים הייתה תוקעת את התוכנה לדקות.)
    """
    with get_connection() as conn:
        return _link_identity_group_conn(conn, nick_ids)

def _link_identity_group_conn(conn, nick_ids, cap=None):
    """
    מאחד קבוצת ניקים לקבוצת זהות אחת על חיבור קיים (כולל מיזוג עם קבוצות
    קיימות). הייבוא לא יכול לקרוא ל-add_identity פר-זוג: היא פותחת with משלה
    ומחשבת מחדש את הסגור לכל זוג.
    """
    ids = sorted({int(i) for i in (nick_ids or [])})
    if len(ids) < 2:
        return 0
    members = sorted(_identity_group_many(conn, ids))
    limit = MAX_IDENTITY_GROUP if cap is None else cap
    if len(members) > limit:
        raise ValueError(
            f"קבוצת זהות של {len(members)} ניקים נראית כטעות — "
            f"המקסימום הוא {limit}. בחר פחות ניקים.")
    pairs = [(members[i], members[j])
             for i in range(len(members)) for j in range(i + 1, len(members))]
    conn.executemany(
        "INSERT OR IGNORE INTO nick_identities (nick_id_a, nick_id_b) VALUES (?,?)", pairs)
    return len(members)

def bulk_move_forum(nick_ids, forum):
    """מעביר ניקים לפורום אחר (bulk_update_field חוסם forum במכוון)."""
    ids = [int(i) for i in (nick_ids or [])]
    forum = (forum or "").strip()
    if not ids or not forum:
        return 0
    moved, skipped = 0, 0
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM forums WHERE name=?", (forum,)).fetchone():
            conn.execute("INSERT OR IGNORE INTO forums (name,color,url) VALUES (?,?,'')",
                         (forum, "#8b90a0"))
        # התנגשות שם בפורום היעד תיצור כפילות ש(forum,username) — סריקה עתידית
        # תתאים רק לאחת מהן והשנייה תיוותר "יתומה". מדלגים ומדווחים.
        taken = {r[0] for r in conn.execute(
            "SELECT username FROM nicks WHERE forum=?", (forum,))}
        movable = []
        for chunk in _chunks(ids, 400):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT id, username, forum FROM nicks WHERE id IN ({ph})", list(chunk)):
                if r["forum"] == forum:
                    continue
                if r["username"] in taken:
                    skipped += 1
                else:
                    movable.append(r["id"])
                    taken.add(r["username"])
        for chunk in _chunks(movable, 400):
            ph = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"UPDATE nicks SET forum=?, updated_at=datetime('now') WHERE id IN ({ph})",
                [forum] + list(chunk))
            moved += cur.rowcount
    return {"moved": moved, "skipped": skipped}

def bulk_append_text(nick_ids, field, text):
    """מוסיף טקסט לסוף שדה טקסט (הערות/הערות אישיות) בלי למחוק את הקיים."""
    ids = [int(i) for i in (nick_ids or [])]
    text = (text or "").strip()
    if not ids or not text or field not in ("notes", "private_notes", "extra_info"):
        return 0
    n = 0
    with get_connection() as conn:
        ids = sorted(_existing_ids(conn, ids))
        if not ids:
            return 0
        for chunk in _chunks(ids, 400):
            ph = ",".join("?" * len(chunk))
            cur = conn.execute(
                f"UPDATE nicks SET {field} = CASE WHEN {field} IS NULL OR {field}='' THEN ? "
                f"ELSE {field} || char(10) || ? END, updated_at=datetime('now') "
                f"WHERE id IN ({ph})", [text, text] + list(chunk))
            n += cur.rowcount
        # רישום תחת מקור "אני" ואז הכרעה — אחרת ה-cache והמנוע נפרדים,
        # והפעולה הבאה שמכריעה את השדה מוחקת את ההערה שנוספה.
        for chunk in _chunks(ids, 400):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(f"SELECT id, {field} FROM nicks WHERE id IN ({ph})", list(chunk)):
                _upsert_field_value(conn, r["id"], field, r[field], 1)
                _resolve_fields_conn(conn, r["id"], [field])
    return n

# ── סטטיסטיקות ───────────────────────────────────────────────────────
def get_stats():
    """מבט-על: סה"כ, לפי פורום, מורחקים, עם מידע, ופעילות אחרונה."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM nicks").fetchone()[0]
        by_forum = [dict(r) for r in conn.execute(f"""
            SELECT n.forum,
                   COUNT(*) AS total,
                   SUM(CASE WHEN n.status='מורחק' THEN 1 ELSE 0 END) AS banned,
                   SUM(CASE WHEN {_HAS_INFO_SQL} THEN 1 ELSE 0 END) AS with_info
            FROM nicks n GROUP BY n.forum ORDER BY total DESC""")]
        totals = {
            "total": total,
            "banned": conn.execute("SELECT COUNT(*) FROM nicks WHERE status='מורחק'").fetchone()[0],
            "with_info": conn.execute(
                f"SELECT COUNT(*) FROM nicks n WHERE {_HAS_INFO_SQL}").fetchone()[0],
            "identities": conn.execute("SELECT COUNT(*) FROM nick_identities").fetchone()[0],
            "contacts": conn.execute("SELECT COUNT(*) FROM nick_contacts").fetchone()[0],
            "added_7d": conn.execute(
                "SELECT COUNT(*) FROM nicks WHERE created_at >= datetime('now','-7 days')").fetchone()[0],
            "updated_7d": conn.execute(
                "SELECT COUNT(*) FROM nicks WHERE updated_at >= datetime('now','-7 days')").fetchone()[0],
        }
        top_groups = [dict(r) for r in conn.execute("""
            SELECT groups AS name, COUNT(*) AS c FROM nicks
            WHERE groups IS NOT NULL AND groups != '' GROUP BY groups
            ORDER BY c DESC LIMIT 8""")]
    return {"totals": totals, "by_forum": by_forum, "top_groups": top_groups}

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
            ORDER BY s.absolute DESC, s.trust DESC, fv.created_at DESC
        """, (nick_id, field_name)).fetchall()
        out = [dict(r) for r in rows]
    # מי באמת מנצח נקבע ב-_winner_for (לסטטוס ולמוניטין יש כללים משלהם), ולכן
    # אי אפשר להסיק זאת ממיון האמינות — הפאנל היה מציג את ההפך מהערך המוצג.
    win = _winner_row_for(field_name, rows)
    for d, r in zip(out, rows):
        d["is_winner"] = bool(win is not None and r is win)
    return out


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
        # דרך מנוע המקורות ולא ישירות ל-cache: כתיבה ל-nicks בלי רישום תחת מקור
        # מתאדה בהכרעה הבאה (אותה משפחת באגים שתוקנה ב-0.8.6).
        _upsert_field_value(conn, s["nick_id"], field, s["value"], 1)
        _resolve_fields_conn(conn, s["nick_id"], [field])
        # הסר את הרשומה מהמדף
        conn.execute("DELETE FROM shelved_values WHERE id=?", (shelved_id,))
        # הורד את הערך הפעיל הקודם למדף (אם היה)
        if old_active not in (None, ""):
            conn.execute("""INSERT INTO shelved_values
                (nick_id, field_name, value, source_name, source_trust)
                VALUES (?,?,?,?,?)""",
                (s["nick_id"], field, str(old_active), "הערך הקודם שלי", get_my_trust()))
        return True

def pick_field_value(nick_id, field_name, value):
    """
    "השתמש בערך הזה": רושם את הערך שנבחר תחת מקור "אני" ומכריע מחדש, כך שהוא
    יוצג — בלי לגעת בערכים של המקורות האחרים, שנשארים ב-field_values ויוצגו
    בפאנל. הפיך: מחיקת הערך בטופס מחזירה את המנצח הקודם.
    שדות שהמנוע מכריע בהם לפי כלל משלו (סטטוס מסריקה הוא אבסולוטי) יסרבו,
    ומחזירים הסבר במקום להיכשל בשקט.
    """
    field = str(field_name)
    if field in _NON_SOURCED or field not in _NICK_FIELDS:
        return {"ok": False, "error": "לא ניתן לבחור ערך לשדה הזה"}
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM nicks WHERE id=?", (int(nick_id),)).fetchone():
            return {"ok": False, "error": "הניק לא נמצא"}
        _upsert_field_value(conn, int(nick_id), field, str(value), 1)
        _resolve_fields_conn(conn, int(nick_id), [field])
        row = conn.execute(f"SELECT {field} AS v FROM nicks WHERE id=?",
                           (int(nick_id),)).fetchone()
    shown = (row["v"] if row else "") or ""
    if str(shown).strip() != str(value).strip():
        # למשל סטטוס: מקור סריקה אבסולוטי וגובר גם על "אני" — במכוון.
        return {"ok": False, "shown": shown,
                "error": f"הערך המוצג נשאר \"{shown}\" — לשדה הזה יש מקור בעל "
                         f"עדיפות מוחלטת (סטטוס נקבע לפי הסריקה)."}
    return {"ok": True, "shown": shown}

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

def apply_import_conflicts(items, accept):
    """
    "החל על כל השאר" בפותר ההתנגשויות — כל ההחלטות בחיבור אחד.
    accept=False → לא נרשם כלום (הקיים נשאר). מחזיר כמה ערכים הוחלו.
    """
    if not accept:
        return 0
    n = 0
    with get_connection() as conn:
        for it in (items or []):
            field = it.get("field")
            val = it.get("new_value")
            if field in _NON_SOURCED or val in (None, ""):
                continue
            nid = int(it.get("nick_id"))
            _upsert_field_value(conn, nid, field, val, int(it.get("source_id")))
            if field in _NICK_FIELDS and field not in ("forum", "username"):
                conn.execute(
                    f"UPDATE nicks SET {field}=?, updated_at=datetime('now') WHERE id=?",
                    (val, nid))
            n += 1
    return n

# ── גיבוי ושחזור מלאים של קובץ ה-DB ──────────────────────────────────
def backup_to(dest_path):
    """
    גיבוי מלא ועקבי (כולל תוכן ה-WAL) לקובץ יעד דרך ה-backup API של SQLite.
    מחזיר את מספר הניקים שגובו.
    """
    src = get_connection()
    src.commit()
    dst = sqlite3.connect(dest_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
    return src.execute("SELECT COUNT(*) FROM nicks").fetchone()[0]

def _close_thread_connection():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
        _local.path = None

def validate_backup(src_path):
    """מאמת שקובץ הוא DB תקין של Tik-Nick; מחזיר מספר ניקים או מרים ValueError."""
    chk = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        ok = chk.execute("PRAGMA integrity_check").fetchone()[0]
        has = chk.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nicks'").fetchone()
        n = chk.execute("SELECT COUNT(*) FROM nicks").fetchone()[0] if has else 0
    finally:
        chk.close()
    if ok != "ok" or not has:
        raise ValueError("הקובץ אינו גיבוי תקין של Tik-Nick")
    return n

# ── גיבוי אוטומטי ─────────────────────────────────────────────────────
# המאגר האמיתי הוא 88MB, והתיקייה יושבת על C: שצפוף. לכן: מעט עותקים,
# תקרת נפח קשיחה, וספירה שהמשתמש רואה — ולא "נשמור הכל ליתר ביטחון".
AUTO_BACKUP_KEEP = 3
AUTO_BACKUP_MAX_BYTES = 1024 * 1024 * 1024      # 1GB לכל התיקייה
AUTO_BACKUP_MIN_HOURS = 20                      # "יומי" בלי להיתקע על הפעלה כפולה

def backup_dir():
    d = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
    os.makedirs(d, exist_ok=True)
    return d

def list_backups():
    """הגיבויים האוטומטיים, החדש ראשון."""
    out = []
    try:
        d = backup_dir()
        for name in os.listdir(d):
            if not name.startswith("tiknick-") or not name.endswith(".db"):
                continue
            full = os.path.join(d, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append({"path": full, "name": name, "bytes": st.st_size,
                        "_ts": st.st_mtime,
                        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    except Exception:
        return []
    # מיון לפי הזמן המדויק (float) ואז לפי שם — שני גיבויים באותה שנייה חייבים
    # סדר יציב, אחרת הגיזום מוחק אחד מהם באקראי במקום את הישן.
    out.sort(key=lambda x: (x["_ts"], x["name"]), reverse=True)
    return out

def _prune_backups(keep=AUTO_BACKUP_KEEP):
    files = list_backups()
    total = 0
    for i, f in enumerate(files):
        total += f["bytes"]
        if i >= keep or total > AUTO_BACKUP_MAX_BYTES:
            try:
                os.remove(f["path"])
            except OSError:
                pass

def auto_backup(reason="daily", force=False):
    """
    עותק מלא דרך ה-backup API של SQLite (לא העתקת קובץ — WAL).
    reason נכנס לשם הקובץ כדי שאפשר יהיה לראות למה הוא נוצר.
    מחזיר {"ok", "path"|"skipped", "bytes"} — לעולם לא מרים חריגה: גיבוי
    שנכשל (דיסק מלא, נתיב חסום) לא אמור למנוע מהמשתמש לעבוד.
    """
    try:
        if not force and reason == "daily":
            last = get_setting("last_auto_backup", "")
            if last:
                try:
                    delta = datetime.now() - datetime.fromisoformat(last)
                    if delta.total_seconds() < AUTO_BACKUP_MIN_HOURS * 3600:
                        return {"ok": True, "skipped": "טרי", "path": ""}
                except ValueError:
                    pass
        safe = "".join(c for c in str(reason) if c.isalnum() or c in "-_")[:24] or "auto"
        dest = os.path.join(backup_dir(),
                            f"tiknick-{safe}-{datetime.now():%Y%m%d-%H%M%S}.db")
        backup_to(dest)
        size = os.path.getsize(dest)
        if size <= 0:
            os.remove(dest)
            return {"ok": False, "error": "הגיבוי יצא ריק"}
        if reason == "daily":
            set_setting("last_auto_backup", datetime.now().isoformat(timespec="seconds"))
        _prune_backups()
        return {"ok": True, "path": dest, "bytes": size}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def backup_status():
    files = list_backups()
    return {"enabled": get_setting("auto_backup_enabled", "1") != "0",
            "last": get_setting("last_auto_backup", ""),
            "count": len(files),
            "bytes": sum(f["bytes"] for f in files),
            "dir": backup_dir(),
            "files": files}

def restore_from(src_path):
    """
    שחזור מגיבוי דרך ה-backup API של SQLite — כותב לתוך המאגר החי במקום להחליף
    קובץ פתוח (ב-Windows אי אפשר, וגם עותק-קובץ פשוט מפספס את תוכן ה-WAL).
    עותק בטיחות של המצב הנוכחי נשמר לצדו לפני הכתיבה.
    """
    n = validate_backup(src_path)
    safety = DB_PATH + f".before-restore-{datetime.now():%Y%m%d-%H%M%S}"
    backup_to(safety)                     # כולל את תוכן ה-WAL
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        src.backup(get_connection())      # אטומי תחת הנעילה של SQLite
    finally:
        src.close()
    init_db()                             # מיגרציות/אינדקסים/FTS על התוכן החדש
    _prune_safety_backups()
    return {"nicks": n, "safety_backup": safety}

_SAFETY_KEEP = 3

def _prune_safety_backups(keep=_SAFETY_KEEP):
    """
    משאיר רק את N עותקי הבטיחות האחרונים. כל שחזור הוריד עותק מלא של המאגר
    (88MB אצל בנימין) לתיקיית הנתונים ב-C:, ושום דבר לא מחק אותם — שלושה
    שחזורים = רבע ג'יגה שנשכח שם.
    """
    import glob as _glob
    try:
        files = sorted(_glob.glob(DB_PATH + ".before-restore-*"))
        for f in files[:-keep] if keep > 0 else files:
            try:
                os.remove(f)
            except OSError:
                pass
        return len(files)
    except Exception:
        return 0

def preview_import(data, forum_mapping=None, include_contacts=True,
                   include_identities=True, sample_limit=12, progress_cb=None):
    """
    מעבר קריאה-בלבד על קובץ הייבוא: כמה ניקים חדשים מול קיימים, כמה ערכים
    ייכתבו, כמה מהם ידרסו ערך קיים שונה (עם דוגמאות), ומה יידלג ולמה.
    שום דבר לא נכתב.

    עלות: מעבר אחד על רשומות הקובץ + שליפת הניקים הקיימים במנות של 400 —
    אותה עבודה שהייבוא עושה ממילא בשלב הטעינה שלו, לא מעבר שני על המאגר.
    """
    mapping = forum_mapping or {}
    exported_fields = data.get("exported_fields", get_exportable_fields())
    sourced_fields = [f for f in exported_fields
                      if f not in _NON_SOURCED and f in _NICK_FIELDS]
    io_flags = get_forum_io_flags()

    entries, skipped_no_username, skipped_forum = [], 0, 0
    excluded_forums = set()
    for nick in data.get("nicks", []):
        if not isinstance(nick, dict):
            continue
        username = str(nick.get("username", "")).strip()
        forum_raw = str(nick.get("forum", "")).strip()
        forum = mapping.get(forum_raw, "") or forum_raw
        if not username:
            skipped_no_username += 1
            continue
        if io_flags.get(forum, True) is False:
            skipped_forum += 1
            excluded_forums.add(forum)
            continue
        entries.append((forum, username, nick))

    new_nicks = existing_nicks = values = conflicts = 0
    samples = []
    with get_connection() as conn:
        by_forum = {}
        for forum, username, _ in entries:
            by_forum.setdefault(forum, set()).add(username)
        existing = {}
        for forum, unames in by_forum.items():
            for chunk in _chunks(sorted(unames), 400):
                ph = ",".join("?" * len(chunk))
                for r in conn.execute(
                        f"SELECT * FROM nicks WHERE forum=? AND username IN ({ph})",
                        [forum] + list(chunk)):
                    existing[(forum, r["username"])] = r

        seen_pairs = set()
        for i, (forum, username, nick) in enumerate(entries):
            if progress_cb and i % 200 == 0:
                progress_cb(i)
            row = existing.get((forum, username))
            key = (forum, username)
            if row is None and key not in seen_pairs:
                new_nicks += 1
            elif row is not None and key not in seen_pairs:
                existing_nicks += 1
            seen_pairs.add(key)
            for field in sourced_fields:
                val = nick.get(field, "")
                if val in (None, ""):
                    continue
                values += 1
                if row is None:
                    continue
                old = str((row[field] if field in row.keys() else "") or "").strip()
                if old and old != str(val).strip():
                    conflicts += 1
                    if len(samples) < sample_limit:
                        samples.append({"forum": forum, "username": username,
                                        "field": field, "old": old[:120],
                                        "new": str(val)[:120]})

    contacts = 0
    if include_contacts:
        for _, _, nick in entries:
            cts = nick.get("contacts")
            if isinstance(cts, list):
                contacts += len([c for c in cts if isinstance(c, dict)])
    groups = data.get("identity_groups") if include_identities else None
    return {
        "rows": len(data.get("nicks", [])),
        "new_nicks": new_nicks, "existing_nicks": existing_nicks,
        "values": values, "conflicts": conflicts, "samples": samples,
        "skipped_no_username": skipped_no_username,
        "skipped_forum": skipped_forum,
        "excluded_forums": sorted(excluded_forums),
        "unknown_forums": get_unknown_forums_in_data(data),
        "contacts": contacts,
        "identity_groups": len(groups) if isinstance(groups, list) else 0,
        "fields": sourced_fields,
    }

def _resolve_pairs_conn(conn, pairs, known=None):
    """
    (פורום, שם משתמש) → nick_id עבור חברי קבוצות הזהות שבקובץ.
    קודם ממה שהייבוא כבר נגע בו (בחינם), והשאר במנות של 400 מקובצות לפי פורום —
    אותה תבנית שבה import_data טוען את הניקים הקיימים. שאילתה לזוג הייתה N+1
    על אלפי קישורים.
    """
    out = dict(known or {})
    missing = [pr for pr in pairs if pr not in out]
    by_forum = {}
    for forum, username in missing:
        by_forum.setdefault(forum, set()).add(username)
    for forum, unames in by_forum.items():
        for chunk in _chunks(sorted(unames), 400):
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT id, username FROM nicks WHERE forum=? AND username IN ({ph})",
                    [forum] + list(chunk)):
                out[(forum, r["username"])] = r["id"]
    return out

def import_data(data, source_info="ייבוא חיצוני", forum_mapping=None,
                import_name=None, import_notes="", import_trust=None, import_absolute=0,
                manual_conflicts=False, progress_cb=None,
                include_contacts=True, include_identities=True):
    """
    ייבוא מבוסס-מקורות: נוצר מקור ייבוא אחד (שם/הערות/אמינות/אבסולוטי),
    וכל ערך מיובא נרשם תחתיו במנוע המקורות. הערך המנצח בכל שדה נקבע אוטומטית.
    manual_conflicts=True → התנגשויות (ערך שונה בשדה קיים) לא נרשמות אלא מוחזרות
    לפתרון ידני; מחזיר dict עם רשימת ההתנגשויות.
    מחזיר: (imported_new, values_recorded) או dict במצב ידני.
    """
    imported = 0; recorded = 0
    contacts_added = identities_linked = identities_skipped = 0
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

    # exported_fields מגיע מהקובץ. בלי הצלבה מול הרשימה הלבנה, קובץ ערוך ידנית
    # מזריק שורות field_values בשמות שדות שלא קיימים — הן לא ישפיעו על שום ניק
    # (ההכרעה מסננת ל-_NICK_FIELDS) אבל ינפחו את המאגר בלי שאפשר לראות אותן.
    sourced_fields = [f for f in exported_fields
                      if f not in _NON_SOURCED and f in _NICK_FIELDS]

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

        done_n = 0
        local_ids = {}       # (forum, username) -> nick_id — לפתרון קבוצות הזהות
        file_contacts = []   # [(nick_id, [{type,value,label}, …]), …]
        for forum, username, nick in entries:
            done_n += 1
            if progress_cb and done_n % 25 == 0:
                progress_cb(done_n)
            row = existing.get((forum, username))
            if row is not None:
                nid = row["id"]
            else:
                cur_ins = conn.execute(
                    "INSERT INTO nicks (forum, username, source, trust_level) VALUES (?,?,?,3)",
                    (forum, username, src_name))
                nid = cur_ins.lastrowid
                imported += 1
                # בלי זה, קובץ שמכיל את אותו (פורום, שם משתמש) פעמיים יצר שני
                # ניקים — וסריקה עתידית מתאימה רק לאחד מהם. השני נשאר יתום.
                existing[(forum, username)] = {"id": nid}

            local_ids[(forum, username)] = nid
            if include_contacts:
                cts = nick.get("contacts")
                if isinstance(cts, list) and cts:
                    file_contacts.append((nid, cts))

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
                _resolve_fields_conn(conn, nid, changed_fields, history=(row is not None))

        # ── מקטעי גרסה 3 — באותו חיבור ובאותה טרנזקציה ──
        if include_contacts and file_contacts:
            contacts_added = _import_contacts_conn(conn, file_contacts)

        raw_groups = data.get("identity_groups") if include_identities else None
        if isinstance(raw_groups, list) and raw_groups:
            wanted = []
            for grp in raw_groups[:MAX_IMPORT_IDENTITY_GROUPS]:
                if not isinstance(grp, list) or len(grp) < 2:
                    continue
                members = []
                for m in grp:
                    if not isinstance(m, dict):
                        continue
                    f_raw = str(m.get("forum", "")).strip()
                    f_map = mapping.get(f_raw, "") or f_raw
                    u = str(m.get("username", "")).strip()
                    if u:
                        members.append((f_map, u))
                if len(members) >= 2:
                    wanted.append(members)
            flat = {pr for grp in wanted for pr in grp}
            resolved = _resolve_pairs_conn(conn, sorted(flat), local_ids)
            for members in wanted:
                local = [resolved[pr] for pr in members if pr in resolved]
                if len(set(local)) < 2:
                    # קישור מדולג כששני הצדדים אינם קיימים אצלי — מדווח, לא מומצא
                    identities_skipped += 1
                    continue
                try:
                    _link_identity_group_conn(conn, local, cap=MAX_IDENTITY_GROUP)
                    identities_linked += 1
                except ValueError:
                    identities_skipped += 1

    # עדכן ספירות בלוג הייבוא (import_sources הישן, לתאימות)
    log_import_source(src_name, import_notes, trust, imported, recorded)
    # מחזיר תמיד dict (עד 0.8.6 היה tuple במצב הרגיל ו-dict במצב הידני)
    return {"imported": imported, "recorded": recorded,
            "conflicts": pending_conflicts if manual_conflicts else [],
            "manual": bool(manual_conflicts), "source_id": import_sid,
            "contacts": contacts_added,
            "identities": identities_linked, "identities_skipped": identities_skipped}
