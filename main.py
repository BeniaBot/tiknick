"""
main.py - Tik-Nick v0.1 — PyWebView backend
"""
import webview
import json
import os
import sys
import logging
import webbrowser
import database as db


# ── נתיבים: תמיכה גם בהרצה רגילה וגם ב-EXE (PyInstaller) ────────────
def resource_path(rel):
    """נתיב למשאבים ארוזים (web/). ב-EXE הם ב-sys._MEIPASS."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def data_dir():
    """תיקייה לכתיבה (DB, לוגים). ליד ה-EXE, או ליד הסקריפט."""
    if getattr(sys, "frozen", False):
        # רץ כ-EXE — שמור ליד קובץ ה-EXE
        d = os.path.dirname(sys.executable)
    else:
        d = os.path.dirname(os.path.abspath(__file__))
    return d

_HERE     = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = data_dir()

# ── לוגים ל-tiknick.log ליד התוכנה ──────────────────────────────────
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

logging.info("Tik-Nick starting | data_dir=%s | frozen=%s",
             _DATA_DIR, getattr(sys, "frozen", False))

class API:
    """כל method כאן זמינה ב-JS כ: window.pywebview.api.method_name()"""

    # ── ניקים ──────────────────────────────────────────────────────
    def get_nicks(self, search=""):
        return db.get_all_nicks(search)

    def get_nick(self, nick_id):
        nick = db.get_nick(int(nick_id))
        if not nick:
            return None
        nick["contacts"]   = db.get_contacts(int(nick_id))
        nick["conflicts"]  = db.get_conflicts(int(nick_id))
        nick["identities"] = db.get_identities(int(nick_id))
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
            return {"ok": False, "error": str(e)}

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

    # ── הגדרות סנכרון ──────────────────────────────────────────────
    def get_sync_settings(self):
        return db.get_sync_settings()

    def get_all_nick_fields(self):
        return [{"key": k, "label": l, "default": d}
                for k, l, d in db.ALL_NICK_FIELDS]

    def set_sync_setting(self, field_key, synced):
        db.set_sync_setting(field_key, bool(synced))
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

    def confirm_import(self, forum_mapping=None):
        """שלב 2: בצע ייבוא עם מיפוי פורומים"""
        pending = getattr(self, '_pending_import', None)
        if not pending:
            return {"ok": False, "error": "אין קובץ ממתין"}
        try:
            data     = pending["data"]
            path     = pending["path"]
            mapping  = forum_mapping or {}
            imp, conf = db.import_data(data, os.path.basename(path), mapping)
            self._pending_import = None
            return {"ok": True, "imported": imp, "conflicts": conf}
        except Exception as e:
            return {"ok": False, "error": str(e)}


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

        window = webview.create_window(
            title="Tik-Nick",
            url=index_url,
            js_api=api,
            width=1400, height=820,
            min_size=(1000, 600),
            background_color="#0d1117",
        )
        webview.start(debug=False)   # ללא כלי מפתחים למשתמש הסופי
        logging.info("Tik-Nick closed normally")
    except Exception:
        logging.exception("Fatal error during startup")
        raise
