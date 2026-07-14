"""
main.py - Tik-Nick — PyWebView backend
"""
import os
import sys

# חייב לקרות לפני אתחול ה-GUI — מגדיר מודעות ל-DPI כדי שמיקום החלון יהיה מדויק
if os.name == "nt":
    try:
        import ctypes
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import webview
import json
import logging
import webbrowser
import threading
import database as db
import scraper


# ── מצב סריקה פעילה (למעקב התקדמות מהממשק) ─────────────────────────
_scrape_state = {
    "running": False, "done": False, "error": None,
    "page": 0, "total_pages": 0,
    "added": 0, "updated": 0, "unchanged": 0, "conflicts": 0,
    "forum": None, "cancelled": False, "auto_resolved": 0,
}
_scrape_cancel = threading.Event()


# ── גרסה נוכחית (לבדיקת עדכונים) ────────────────────────────────────
APP_VERSION = "0.6.2"
GITHUB_REPO = "BeniaBot/tiknick"

# ── נתיבים: תמיכה גם בהרצה רגילה וגם ב-EXE (PyInstaller) ────────────
def resource_path(rel):
    """נתיב למשאבים ארוזים (web/). ב-EXE הם ב-sys._MEIPASS."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def data_dir():
    """
    תיקיית נתונים תקנית (DB, לוגים):
    - Windows: %APPDATA%\\TikNick  (למשל C:\\Users\\<user>\\AppData\\Roaming\\TikNick)
    - אחר: ~/.tiknick
    כך הנתונים מופרדים מה-EXE, שורדים שדרוגים, ולא נחסמים ע"י הרשאות.
    בהרצה מהמקור (לא frozen) — נשאר ליד הסקריפט לנוחות פיתוח.
    """
    if getattr(sys, "frozen", False):
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            d = os.path.join(base, "TikNick")
        else:
            d = os.path.join(os.path.expanduser("~"), ".tiknick")
    else:
        d = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(d, exist_ok=True)
    return d

def _migrate_old_data(new_dir):
    """אם קיים DB ישן ליד ה-EXE (מגרסאות קודמות) — העבר אותו לתיקייה החדשה."""
    if not getattr(sys, "frozen", False):
        return
    old_dir = os.path.dirname(sys.executable)
    if os.path.abspath(old_dir) == os.path.abspath(new_dir):
        return
    old_db = os.path.join(old_dir, "tiknick.db")
    new_db = os.path.join(new_dir, "tiknick.db")
    if os.path.exists(old_db) and not os.path.exists(new_db):
        try:
            import shutil
            for suffix in ("", "-wal", "-shm"):
                src = old_db + suffix
                if os.path.exists(src):
                    shutil.copy2(src, new_db + suffix)
            logging.info("Migrated old DB from %s to %s", old_dir, new_dir)
        except Exception:
            logging.exception("Failed migrating old DB")

_HERE     = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = data_dir()
_migrate_old_data(_DATA_DIR)

# ── לוגים ל-tiknick.log בתיקיית הנתונים ─────────────────────────────
_LOG_PATH = os.path.join(_DATA_DIR, "tiknick.log")
logging.basicConfig(
    filename=_LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
# תפוס גם שגיאות לא-מטופלות
def _excepthook(exc_type, exc_value, exc_tb):
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
sys.excepthook = _excepthook

logging.info("Tik-Nick %s starting | data_dir=%s | frozen=%s",
             APP_VERSION, _DATA_DIR, getattr(sys, "frozen", False))

class API:
    """כל method כאן זמינה ב-JS כ: window.pywebview.api.method_name()"""

    # ── ניקים ──────────────────────────────────────────────────────
    def get_nicks(self, search="", offset=0, limit=None):
        """
        מחזיר {"rows":[...], "total": N}. ברירת מחדל: טוען את כל הניקים
        התואמים בבת אחת (ללא הגבלת עמוד) — לפי בקשת המשתמש. אם בעתיד
        המאגר יגדל משמעותית ותהיה שוב תקיעות, אפשר להעביר limit ממשי.
        """
        lim = int(limit) if limit else None
        return db.get_all_nicks(search or "", limit=lim, offset=int(offset or 0))

    def get_nick(self, nick_id):
        nick = db.get_nick(int(nick_id))
        if not nick:
            return None
        nick["contacts"]   = db.get_contacts(int(nick_id))
        nick["conflicts"]  = db.get_conflicts(int(nick_id))
        nick["identities"] = db.get_identities(int(nick_id))
        nick["shelved"]    = db.get_shelved_values(int(nick_id))
        # שדות שיש להם ערכים שונים ממקורות שונים (התנגשות אמיתית)
        multi = {}
        for f in ["real_name","full_name","phone","email","address","groups",
                  "status","join_date","post_count","notes","extra_info"]:
            srcs = db.get_field_sources(int(nick_id), f)
            distinct_vals = {str(s.get("value","")).strip() for s in srcs}
            if len(distinct_vals) > 1:
                multi[f] = srcs
        nick["field_sources"] = multi
        return nick

    def create_nick(self, data):
        try:
            data["reputation"] = int(data.get("reputation") or 0)
            nick_id = db.create_nick(data)
            return {"ok": True, "id": nick_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def update_nick(self, nick_id, data):
        try:
            data["reputation"] = int(data.get("reputation") or 0)
            db.update_nick(int(nick_id), data)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def delete_nick(self, nick_id):
        db.delete_nick(int(nick_id))
        return {"ok": True}

    def delete_nicks(self, nick_ids):
        """מחיקה מרובה בפועל — מוחקת את הניקים הנבחרים (לא מרוקנת עמודות בלבד)"""
        n = db.delete_nicks(nick_ids or [])
        return {"ok": True, "count": n}

    # ── סנכרון לאינטרנט (סריקת פורומי NodeBB) ──────────────────────
    def get_scrapable_forums(self):
        """מחזיר את הפורומים המובנים עם כתובת, לבחירה בממשק הסנכרון"""
        forums = db.get_forums()
        return [f for f in forums if (f.get("url") or "").strip()]

    def check_forum(self, forum_url, cookie=""):
        """בדיקה מקדימה שהכתובת היא פורום NodeBB עם API פעיל"""
        try:
            return scraper.check_forum(forum_url, cookie=cookie or None)
        except Exception as e:
            return {"ok": False, "user_count": None, "title": None, "error": str(e)}

    def start_scrape(self, forum_name, forum_url, cookie="", max_pages=None):
        """מתחיל סריקה ברקע. הממשק יסקור התקדמות דרך get_scrape_progress."""
        if _scrape_state["running"]:
            return {"ok": False, "error": "סריקה כבר רצה"}

        _scrape_cancel.clear()
        _scrape_state.update({
            "running": True, "done": False, "error": None,
            "page": 0, "total_pages": 0,
            "added": 0, "updated": 0, "unchanged": 0, "conflicts": 0,
            "forum": forum_name, "cancelled": False,
        })

        def _progress(p):
            _scrape_state.update({
                "page": p.get("page", 0),
                "total_pages": p.get("total_pages", 0),
                "added": p.get("added", 0),
                "updated": p.get("updated", 0),
                "unchanged": p.get("unchanged", 0),
                "conflicts": p.get("conflicts", 0),
            })

        def _run():
            try:
                mp = int(max_pages) if max_pages else None
                scraper.scrape_forum(
                    forum_name, forum_url, db,
                    cookie=cookie or None,
                    progress_cb=_progress,
                    cancel_flag=_scrape_cancel,
                    max_pages=mp,
                )
                _scrape_state["cancelled"] = _scrape_cancel.is_set()
                # החלת מדיניות התנגשות אוטומטית (אם הוגדרה)
                policy = db.get_setting("conflict_policy", "ask")
                if policy in ("new", "existing") and _scrape_state["conflicts"] > 0:
                    resolved = db.resolve_all_conflicts(policy)
                    _scrape_state["auto_resolved"] = resolved
                    _scrape_state["conflicts"] = 0
            except Exception as e:
                _scrape_state["error"] = str(e)
            finally:
                _scrape_state["running"] = False
                _scrape_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def get_scrape_progress(self):
        return dict(_scrape_state)

    def cancel_scrape(self):
        _scrape_cancel.set()
        return {"ok": True}

    def reset_all(self):
        db.reset_all()
        return {"ok": True}

    def reset_columns(self, columns):
        n = db.reset_columns(columns or [])
        return {"ok": True, "count": n}

    def reset_settings_only(self):
        db.reset_settings_only()
        return {"ok": True}

    def get_resettable_columns(self):
        # עמודות שניתן לאפס (ללא username)
        return [{"key": k, "label": l}
                for k, l, _ in db.ALL_NICK_FIELDS if k != "username"]

    # ── הגדרות תצוגה ───────────────────────────────────────────────
    def get_display_settings(self):
        return db.get_display_settings()

    def set_display_setting(self, key, value):
        db.set_display_setting(key, value)
        return {"ok": True}

    def reset_display_settings(self):
        db.reset_display_settings()
        return {"ok": True}

    def open_url(self, url):
        """פתח URL בדפדפן ברירת המחדל של המערכת"""
        if not url:
            return {"ok": False, "error": "אין קישור"}
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as e:
            logging.exception("open_url failed for %s", url)
            return {"ok": False, "error": str(e)}

    # ── בדיקת עדכונים מ-GitHub ──────────────────────────────────────
    def get_app_version(self):
        return {"version": APP_VERSION, "repo": GITHUB_REPO}

    def check_for_updates(self):
        """בודק אם קיימת גרסה חדשה יותר ב-GitHub Releases."""
        import urllib.request
        import json as _json
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        try:
            req = urllib.request.Request(
                api_url, headers={"User-Agent": "TikNick-UpdateCheck"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logging.info("Update check failed: %s", e)
            return {"ok": False, "error": "לא ניתן לבדוק עדכונים כרגע"}

        tag = (data.get("tag_name") or "").lstrip("vV").strip()
        latest = tag or "0.0.0"
        current = APP_VERSION

        def parse(v):
            parts = []
            for p in str(v).split("."):
                num = "".join(ch for ch in p if ch.isdigit())
                parts.append(int(num) if num else 0)
            while len(parts) < 3:
                parts.append(0)
            return tuple(parts[:3])

        cur_t, lat_t = parse(current), parse(latest)
        is_newer = lat_t > cur_t
        logging.info("Update check: current=%s%s latest=%s%s newer=%s",
                     current, cur_t, latest, lat_t, is_newer)

        # מצא את קובץ ה-EXE להורדה
        exe_url = ""
        for asset in data.get("assets", []):
            if asset.get("name", "").lower().endswith(".exe"):
                exe_url = asset.get("browser_download_url", "")
                break

        return {
            "ok": True,
            "current": current,
            "latest": latest,
            "update_available": is_newer,
            "release_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
            "download_url": exe_url,
            "notes": (data.get("body") or "")[:800],
        }

    # ── פורומים ────────────────────────────────────────────────────
    def get_forums(self):
        return db.get_forums()

    def add_forum(self, name, color, url=""):
        db.add_forum(name, color, url)
        return {"ok": True}

    def update_forum(self, forum_id, name, color, url=""):
        db.update_forum(int(forum_id), name, color, url)
        return {"ok": True}

    def get_known_forums(self):
        """מחזיר כל הפורומים המוכרים + סימון אם כבר קיים"""
        known   = db.get_known_forums()
        active  = set(db.get_forum_names())
        for f in known:
            f["active"] = f["name"] in active
        return known

    def resolve_forum_data(self, name, color=None, url=None):
        return db.resolve_forum_data(name, color or "#8b90a0", url or "")

    def delete_forum(self, forum_id, move_to_general=True):
        db.delete_forum(int(forum_id), bool(move_to_general))
        return {"ok": True}

    def count_nicks_in_forum(self, forum_id):
        count, name = db.count_nicks_in_forum(int(forum_id))
        return {"count": count, "name": name}

    def get_unknown_forums_in_data(self, data):
        return db.get_unknown_forums_in_data(data)

    # ── זהויות ─────────────────────────────────────────────────────
    def add_identity(self, nick_id_a, nick_id_b):
        db.add_identity(int(nick_id_a), int(nick_id_b))
        return {"ok": True}

    def remove_identity(self, nick_id_a, nick_id_b):
        db.remove_identity(int(nick_id_a), int(nick_id_b))
        return {"ok": True}

    # ── אנשי קשר ───────────────────────────────────────────────────
    def add_contact(self, nick_id, ctype, value, label="", is_private=False):
        db.add_contact(int(nick_id), ctype, value, label, 1 if is_private else 0)
        return {"ok": True}

    def update_contact(self, contact_id, ctype, value, label="", is_private=False):
        db.update_contact(int(contact_id), ctype, value, label, 1 if is_private else 0)
        return {"ok": True}

    def delete_contact(self, contact_id):
        db.delete_contact(int(contact_id))
        return {"ok": True}

    # ── התנגשויות ──────────────────────────────────────────────────
    def delete_conflict(self, conflict_id):
        db.delete_conflict(int(conflict_id))
        return {"ok": True}

    def get_all_conflicts(self):
        return db.get_all_conflicts()

    def apply_conflict(self, conflict_id):
        """מקבל את הערך החדש מההתנגשות ומחיל אותו על הניק"""
        ok = db.apply_conflict(int(conflict_id))
        return {"ok": ok}

    def resolve_all_conflicts(self, prefer):
        """prefer='new' מחיל את כל החדשים; prefer='existing' שומר קיים"""
        n = db.resolve_all_conflicts(prefer)
        return {"ok": True, "count": n}

    # ── הגדרות סנכרון ──────────────────────────────────────────────
    def get_sync_settings(self):
        return db.get_sync_settings()
    def get_all_nick_fields(self):
        return [{"key": k, "label": l, "default": d}
                for k, l, d in db.ALL_NICK_FIELDS]

    def set_sync_setting(self, field_key, synced):
        db.set_sync_setting(field_key, bool(synced))
        return {"ok": True}

    # section 2: אילו פורומים ייכללו בייבוא/ייצוא
    def get_forum_io_flags(self):
        return db.get_forum_io_flags()

    def set_forum_io_flag(self, forum_name, included):
        db.set_forum_io_flag(forum_name, bool(included))
        return {"ok": True}

    # section 3: מדיניות התנגשות בסנכרון מהאינטרנט
    # 'ask' = תמיד לשאול (ברירת מחדל), 'new' = תמיד להעדיף חדש, 'existing' = תמיד לשמור קיים
    def get_conflict_policy(self):
        return db.get_setting("conflict_policy", "ask")

    def set_conflict_policy(self, policy):
        if policy not in ("ask", "new", "existing"):
            policy = "ask"
        db.set_setting("conflict_policy", policy)
        return {"ok": True}

    # ── ייצוא / ייבוא ──────────────────────────────────────────────
    def export_data(self):
        import shutil
        try:
            from webview import FileDialog
            save_dialog = FileDialog.SAVE
        except ImportError:
            save_dialog = webview.SAVE_DIALOG  # older pywebview

        result = webview.windows[0].create_file_dialog(
            save_dialog,
            directory=_HERE,
            save_filename="tiknick_export.tiknick",
            file_types=("TikNick (*.tiknick)", "JSON (*.json)", "All files (*.*)")
        )
        if not result:
            return {"ok": False, "error": "בוטל"}

        # result יכול להיות string או tuple — מנרמל
        if isinstance(result, (list, tuple)):
            dest = result[0]
        else:
            dest = result

        if not dest:
            return {"ok": False, "error": "בוטל"}

        data = db.export_data()
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"ok": True, "path": dest, "count": len(data["nicks"])}

    def load_import_file(self):
        """שלב 1: פתח קובץ ובדוק פורומים לא מוכרים"""
        try:
            from webview import FileDialog
            open_dialog = FileDialog.OPEN
        except ImportError:
            open_dialog = webview.OPEN_DIALOG

        result = webview.windows[0].create_file_dialog(
            open_dialog,
            file_types=("TikNick (*.tiknick)", "JSON (*.json)", "All files (*.*)")
        )
        if not result:
            return {"ok": False, "error": "בוטל"}
        path = result[0] if isinstance(result, (list, tuple)) else result
        if not path:
            return {"ok": False, "error": "בוטל"}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            unknown = db.get_unknown_forums_in_data(data)
            # שמור data זמנית בזיכרון לשלב 2
            self._pending_import = {"data": data, "path": path}
            return {"ok": True, "unknown_forums": unknown,
                    "nick_count": len(data.get("nicks", []))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def import_data(self):
        """לא בשימוש ישיר — השתמש ב-load_import_file + confirm_import"""
        pass

    def confirm_import(self, forum_mapping=None, import_name=None,
                       import_notes="", import_trust=None):
        """שלב 2: בצע ייבוא עם מיפוי פורומים ודרגת אמינות"""
        pending = getattr(self, '_pending_import', None)
        if not pending:
            return {"ok": False, "error": "אין קובץ ממתין"}
        try:
            data     = pending["data"]
            path     = pending["path"]
            mapping  = forum_mapping or {}
            name     = import_name or os.path.basename(path)
            imp, conf = db.import_data(
                data, os.path.basename(path), mapping,
                import_name=name, import_notes=import_notes, import_trust=import_trust)
            self._pending_import = None
            return {"ok": True, "imported": imp, "conflicts": conf}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── אמינות ולוג ייבואים ────────────────────────────────────────
    def get_my_trust(self):
        return db.get_my_trust()

    def set_my_trust(self, val):
        return {"ok": True, "value": db.set_my_trust(val)}

    def get_import_sources(self):
        return db.get_import_sources()

    def get_shelved_values(self, nick_id):
        return db.get_shelved_values(int(nick_id))

    def promote_shelved(self, shelved_id):
        return {"ok": db.promote_shelved(int(shelved_id))}

    # ── ניהול מקורות ("אבות") ──────────────────────────────────────
    def get_sources(self):
        return db.get_sources()

    def update_source(self, source_id, name=None, notes=None, trust=None, absolute=None):
        db.update_source(int(source_id), name=name, notes=notes,
                         trust=trust, absolute=absolute)
        return {"ok": True}

    def delete_source(self, source_id):
        return {"ok": db.delete_source(int(source_id))}

    def get_field_sources(self, nick_id, field_name):
        return db.get_field_sources(int(nick_id), field_name)

    # ── תיוג ניקים בטקסט חופשי (@username) ─────────────────────────
    def resolve_tag(self, username):
        """מאתר ניק לפי שם משתמש מדויק (ללא תלות בפורום) — ללחיצה על תיוג"""
        return db.find_nick_by_username(username)

    def search_usernames(self, prefix, limit=8):
        """חיפוש שמות משתמש להשלמה אוטומטית בעת תיוג"""
        return db.search_usernames(prefix, int(limit))


if __name__ == "__main__":
    try:
        # מסד הנתונים נשמר בתיקייה הניתנת לכתיבה (ליד ה-EXE)
        db.DB_PATH = os.path.join(_DATA_DIR, "tiknick.db")
        db.init_db()
        logging.info("Database ready at %s", db.DB_PATH)

        api = API()

        # קבצי ה-web ארוזים בתוך ה-EXE — נטענים דרך resource_path
        index_path = resource_path(os.path.join("web", "index.html"))
        if os.name == "nt":
            index_url = "file:///" + index_path.replace("\\", "/")
        else:
            index_url = "file://" + index_path
        logging.info("Loading UI from %s", index_url)

        win_w, win_h = 1400, 820

        window = webview.create_window(
            title="Tik-Nick",
            url=index_url,
            js_api=api,
            width=win_w, height=win_h,
            min_size=(1000, 600),
            background_color="#0d1117",
        )

        # מירכוז אמין שמתחשב ב-DPI scaling ובשורת המשימות.
        def center_window():
            try:
                if os.name != "nt":
                    return
                import ctypes
                from ctypes import wintypes
                import time

                user32 = ctypes.windll.user32

                # נסה למצוא את החלון (עד ~1 שנייה, כי לפעמים עוד לא מוכן)
                hwnd = 0
                for _ in range(20):
                    hwnd = user32.FindWindowW(None, "Tik-Nick")
                    if hwnd:
                        break
                    time.sleep(0.05)

                rect = wintypes.RECT()
                user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
                work_w = rect.right - rect.left
                work_h = rect.bottom - rect.top

                if hwnd:
                    wr = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(wr))
                    actual_w = wr.right - wr.left
                    actual_h = wr.bottom - wr.top
                    # אם הגודל נראה סביר השתמש בו, אחרת בגודל המבוקש
                    if actual_w < 200 or actual_w > work_w + 400:
                        actual_w, actual_h = win_w, win_h
                    x = rect.left + max(0, (work_w - actual_w) // 2)
                    y = rect.top  + max(0, (work_h - actual_h) // 2)
                    user32.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0, 0x0001 | 0x0004)
                    logging.info("Centered hwnd at %s,%s (work %sx%s, win %sx%s)",
                                 x, y, work_w, work_h, actual_w, actual_h)
                else:
                    # fallback: מירכוז דרך move של pywebview
                    x = rect.left + max(0, (work_w - win_w) // 2)
                    y = rect.top  + max(0, (work_h - win_h) // 2)
                    window.move(x, y)
                    logging.info("Centered via move at %s,%s (no hwnd)", x, y)
            except Exception:
                logging.exception("Centering failed")

        window.events.shown += center_window
        webview.start(debug=False)   # ללא כלי מפתחים למשתמש הסופי
        logging.info("Tik-Nick closed normally")
    except Exception:
        logging.exception("Fatal error during startup")
        raise
