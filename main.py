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
import csv_import
import profile_sheet
import i18n
import net


# ── מצב סריקה פעילה (למעקב התקדמות מהממשק) ─────────────────────────
_scrape_state = {
    "running": False, "done": False, "error": None,
    "page": 0, "total_pages": 0,
    "added": 0, "updated": 0, "unchanged": 0, "failed_pages": 0,
    "forum": None, "cancelled": False, "run_id": None, "auto": False,
    "all_mode": False, "selected_mode": False,
    "forum_index": 0, "forum_total": 0, "skipped": [],
}
_scrape_cancel = threading.Event()
_scrape_skip = threading.Event()

# ── מצב Chazonishnik (ניתוח פעילות ברקע) ──
_chz_state = {"running": False, "done": False, "error": None,
              "phase": "", "count": 0, "total": 0, "html": None, "path": None,
              "cancelled": False}
_chz_cancel = threading.Event()

# מצב הורדת עדכון
_update_state = {"downloaded": 0, "total": 0, "target_version": ""}

# מצב ייבוא ברקע (ייבוא גדול נמשך שניות-דקות — לא חוסמים את הממשק)
# הטיק רק *מחליט*; הסריקה עצמה עוברת במסלול הקיים עם ההשהיות שלו.
SCHED_TICK_SEC = 60
SCHED_STARTUP_GRACE_SEC = 300     # פתיחת התוכנה לא מפעילה סריקה מיידית
_sched_hold = threading.Event()   # מוחזק סביב תחזוקה (vacuum/restore/reset)
_sched_stop = threading.Event()

_import_state = {"running": False, "done": False, "error": None,
                 "processed": 0, "total": 0, "result": None}

# מצב פעולת מקור ברקע (שינוי אמינות / מחיקת מקור = הכרעה מחדש לכל הערכים שלו)
_source_state = {"running": False, "done": False, "error": None,
                 "processed": 0, "total": 0, "op": ""}

# מצב Stinknik (ניתוח דיסלייקים ברקע)
_stink_state = {"running": False, "done": False, "error": None,
                "checked": 0, "page": 0, "disliked": 0, "html": None,
                "cancelled": False}
_stink_cancel = threading.Event()

class _ChzCancelled(Exception):
    """נזרק כדי לבטל ניתוח Chazonishnik שרץ."""
    pass


# ── גרסה נוכחית (לבדיקת עדכונים) ────────────────────────────────────
APP_VERSION = "0.8.23"
GITHUB_REPO = "BeniaBot/tiknick"

def _looks_like_inno_setup(path):
    """
    האם הקובץ שהורד הוא מתקין Inno Setup — בדיקה לפי תוכן הקובץ, לא לפי שמו.
    כך גרסה ניידת לעולם לא תחליף את עצמה במתקין (ולהפך), גם אם נכס ב-Release
    נקרא בשם מטעה.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(4 * 1024 * 1024)
        return b"Inno Setup" in head or b"JR.Inno.Setup" in head
    except Exception:
        return False


def _install_type():
    """
    'installer' אם רצים מהתקנה (יש קובץ סימון install-type.txt ליד ה-EXE,
    שהאינסטולר מתקין), אחרת 'portable'. קובע לאיזה נכס לעדכן.
    """
    try:
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            if os.path.exists(os.path.join(exe_dir, "install-type.txt")):
                return "installer"
    except Exception:
        pass
    return "portable"

# ── נתיבים: תמיכה גם בהרצה רגילה וגם ב-EXE (PyInstaller) ────────────
def _sched_loop(api):
    """
    מתעורר כל דקה, ורוב הזמן לא עושה דבר. הבדיקות מסודרות מהזולה ליקרה, וכל
    יציאה מוקדמת היא "ננסה בטיק הבא" — לא כישלון.
    """
    import time as _t
    _sched_stop.wait(SCHED_STARTUP_GRACE_SEC)
    while not _sched_stop.is_set():
        try:
            if _sched_hold.is_set():
                pass                                  # תחזוקה רצה — לא נוגעים
            elif db.get_setting("sched_enabled", "0") == "1":
                due = db.sched_due_forums()
                if due and not _scrape_state["running"]:
                    logging.info("scheduled scrape: %s", ", ".join(due))
                    r = api._start_scheduled(due)
                    if not r.get("ok"):
                        logging.info("scheduled scrape not started: %s", r.get("error"))
        except Exception:
            logging.exception("scheduler tick failed")
        _sched_stop.wait(SCHED_TICK_SEC)

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

def _update_error_text(e):
    """
    הודעה שאומרת מה קרה. "לא ניתן לבדוק עדכונים כרגע" נכון תמיד וחסר תועלת
    תמיד — המשתמש לא יודע אם הוא מנותק, חסום, או שהשרת עמוס.
    """
    import urllib.error
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 403 and "rate limit" in str(getattr(e, "reason", "")).lower():
            return ("GitHub חוסם זמנית בדיקות מרובות מאותו חיבור (מגבלת קצב). "
                    "נסה שוב בעוד כשעה — או הורד ידנית מדף הגרסאות.")
        if e.code == 404:
            return "לא נמצאה גרסה משוחררת בכתובת המעודכנת."
        return "השרת החזיר שגיאה %s." % e.code
    if isinstance(e, urllib.error.URLError):
        return ("אין חיבור לאינטרנט, או שהגישה ל-GitHub חסומה ברשת שלך. "
                "אם הרשת דורשת פרוקסי — אפשר להגדיר אותו ב\"סנכרון לאינטרנט\".")
    return "לא ניתן לבדוק עדכונים כרגע: %s" % e


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

    def get_avatars(self, nick_ids):
        """תמונות פרופיל לפי דרישה — רק לשורות שמוצגות (הרשימה עצמה לא נושאת אותן)"""
        return db.get_avatars(nick_ids or [])

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
        try:
            r = db.delete_nicks([int(nick_id)])
            return {"ok": True, "count": r["deleted"], "batch_id": r["batch_id"]}
        except Exception as e:
            logging.exception("delete_nick failed")
            return {"ok": False, "error": str(e)}

    def delete_nicks(self, nick_ids):
        """מחיקה מרובה דרך סל המחזור — ניתנת לביטול (restore_trash)"""
        if len(nick_ids or []) > 50:
            busy = self._busy()      # מחיקה גדולה באמצע סריקה = התנגשות על אותן שורות
            if busy:
                return {"ok": False, "error": busy}
        try:
            r = db.delete_nicks(nick_ids or [])
            return {"ok": True, "count": r["deleted"], "batch_id": r["batch_id"]}
        except Exception as e:
            logging.exception("delete_nicks failed")
            return {"ok": False, "error": str(e)}

    # ── תובנות: ציר זמן, יומן סריקות, הצעות זהות, סטטיסטיקות ────────
    def get_field_history(self, nick_id, limit=100):
        return db.get_field_history(int(nick_id), int(limit))

    def get_scan_runs(self, limit=30):
        return db.get_scan_runs(int(limit))

    def get_scan_changes(self, run_id, limit=500):
        return db.get_scan_changes(int(run_id), int(limit))

    def suggest_identities(self, limit=60):
        try:
            return {"ok": True, "groups": db.suggest_identities(int(limit))}
        except Exception as e:
            logging.exception("suggest_identities failed")
            return {"ok": False, "error": str(e)}

    def dismiss_identity_suggestion(self, nick_ids):
        db.dismiss_identity_suggestion(nick_ids or [])
        return {"ok": True}

    def get_identity_map(self):
        try:
            return {"ok": True, **db.get_identity_map()}
        except Exception as e:
            logging.exception("get_identity_map failed")
            return {"ok": False, "error": str(e)}

    def repair_identity_groups(self):
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        try:
            return {"ok": True, "added": db.repair_identity_groups()}
        except Exception as e:
            logging.exception("repair_identity_groups failed")
            return {"ok": False, "error": str(e)}

    def touch_recent(self, nick_id):
        return {"ok": db.touch_recent(nick_id)}

    def get_recent_views(self, limit=12):
        try:
            return db.get_recent_views(int(limit))
        except Exception:
            logging.exception("get_recent_views failed")
            return []

    def clear_recent_views(self):
        db.clear_recent_views()
        return {"ok": True}

    def get_stats(self):
        try:
            return {"ok": True, **db.get_stats()}
        except Exception as e:
            logging.exception("get_stats failed")
            return {"ok": False, "error": str(e)}

    # ── פעולות מרובות ──────────────────────────────────────────────
    def bulk_link_identities(self, nick_ids):
        try:
            return {"ok": True, "count": db.bulk_link_identities(nick_ids or [])}
        except Exception as e:
            logging.exception("bulk_link_identities failed")
            return {"ok": False, "error": str(e)}

    def bulk_move_forum(self, nick_ids, forum):
        try:
            r = db.bulk_move_forum(nick_ids or [], forum)
            return {"ok": True, "count": r["moved"], "skipped": r["skipped"]}
        except Exception as e:
            logging.exception("bulk_move_forum failed")
            return {"ok": False, "error": str(e)}

    def bulk_append_text(self, nick_ids, field, text):
        try:
            return {"ok": True, "count": db.bulk_append_text(nick_ids or [], field, text)}
        except Exception as e:
            logging.exception("bulk_append_text failed")
            return {"ok": False, "error": str(e)}

    # ── סינונים שמורים ─────────────────────────────────────────────
    def get_saved_filters(self):
        try:
            return json.loads(db.get_setting("saved_filters", "[]")) or []
        except Exception:
            return []

    def save_filter(self, name, conditions):
        items = [f for f in self.get_saved_filters() if f.get("name") != name]
        items.append({"name": name, "conditions": conditions or []})
        # [-30:] ולא [:30] — התקרה צריכה להשליך את הישן, לא את מה שנשמר עכשיו
        db.set_setting("saved_filters", json.dumps(items[-30:], ensure_ascii=False))
        return {"ok": True}

    def delete_saved_filter(self, name):
        items = [f for f in self.get_saved_filters() if f.get("name") != name]
        db.set_setting("saved_filters", json.dumps(items, ensure_ascii=False))
        return {"ok": True}

    # ── סל מחזור ───────────────────────────────────────────────────
    def get_trash(self):
        return db.list_trash()

    def restore_trash(self, batch_id):
        try:
            return {"ok": True, **db.restore_trash(batch_id=batch_id)}
        except Exception as e:
            logging.exception("restore_trash failed")
            return {"ok": False, "error": str(e)}

    # ── פרופיל להדפסה ──────────────────────────────────────────────
    def _print_dir(self):
        d = os.path.join(_DATA_DIR, "print")
        os.makedirs(d, exist_ok=True)
        return d

    def _purge_print_dir(self, keep=40, max_age_h=24):
        """הגיליון עלול להכיל טלפונים והערות אישיות — לא משאירים אותו על הדיסק."""
        import time as _t
        try:
            d = self._print_dir()
            files = []
            for name in os.listdir(d):
                full = os.path.join(d, name)
                try:
                    files.append((os.path.getmtime(full), full))
                except OSError:
                    pass
            files.sort(reverse=True)
            now = _t.time()
            for i, (mt, full) in enumerate(files):
                if i >= keep or (now - mt) > max_age_h * 3600:
                    try:
                        os.remove(full)
                    except OSError:
                        pass
        except Exception:
            pass

    def _print_data(self, nick_id, whole_group=True, include_history=True):
        nid = int(nick_id)
        nick = db.get_nick(nid)
        if not nick:
            return None
        prof = db.get_merged_profile(nid) if whole_group else None
        members = (prof or {}).get("members") or [{
            "id": nick["id"], "forum": nick["forum"], "username": nick["username"],
            "nick_color": nick.get("nick_color", ""), "status": nick.get("status", ""),
        }]
        # הניק שביקשו תמיד ראשון, וגם אם הקבוצה נחתכת הוא נשאר בפנים
        members = sorted(members, key=lambda m: (m.get("id") != nid,))
        truncated_members = len(members) if len(members) > profile_sheet.MAX_MEMBERS else 0
        members = members[:profile_sheet.MAX_MEMBERS]
        for m in members:
            if not m.get("status"):
                row = db.get_nick(m.get("id"))
                m["status"] = (row or {}).get("status", "")
        hist = db.get_field_history(nid, profile_sheet.MAX_HISTORY + 1) if include_history else []
        truncated_history = len(hist) if len(hist) > profile_sheet.MAX_HISTORY else 0
        return {
            "nick": nick, "members": members,
            "fields": (prof or {}).get("fields") or [],
            "contacts": (prof or {}).get("contacts") or db.get_contacts(nid),
            "history": hist,
            "truncated_members": truncated_members,
            "truncated_history": truncated_history,
        }

    def preview_print_profile(self, nick_id, whole_group=True,
                              include_private=False, include_history=True):
        """מחזיר את ה-HTML לתצוגה מקדימה ב-iframe (בלי לכתוב קובץ)."""
        try:
            data = self._print_data(nick_id, whole_group, include_history)
            if not data:
                return {"ok": False, "error": "הניק לא נמצא"}
            import datetime as _dt
            html = profile_sheet.build_sheet(
                data, include_private=bool(include_private),
                include_history=bool(include_history),
                generated=f"{_dt.datetime.now():%d/%m/%Y %H:%M}")
            return {"ok": True, "html": html}
        except Exception as e:
            logging.exception("preview_print_profile failed")
            return {"ok": False, "error": str(e)}

    def open_print_profile(self, nick_id, whole_group=True,
                           include_private=False, include_history=True):
        """
        כותב את הגיליון לקובץ ומוסר אותו למערכת. אין הדפסה מתוך התוכנה: ה-iframe
        מוגן ב-sandbox בלי allow-modals, ו-pywebview רץ עם debug=False (בלי Ctrl+P
        ובלי תפריט הקשר). הדפדפן האמיתי מריץ את window.print() שבקובץ, ושם יש גם
        "Microsoft Print to PDF".
        שים לב: המתודה מקבלת מזהה בלבד — לא נתיב ולא HTML. שם הקובץ והתיקייה
        נבחרים כאן, ולכן JS לא יכול להשפיע על מה שנפתח (ו-open_url נשאר סגור).
        """
        try:
            r = self.preview_print_profile(nick_id, whole_group, include_private,
                                           include_history)
            if not r.get("ok"):
                return r
            import datetime as _dt
            # שם הקובץ לפי מזהה ולא לפי שם משתמש — הדפדפן מדפיס את הנתיב בכותרת
            name = f"tiknick-profile-{int(nick_id)}-{_dt.datetime.now():%H%M%S}.html"
            path = os.path.join(self._print_dir(), name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(r["html"])
            self._purge_print_dir()
            try:
                os.startfile(path)          # noqa: S606 — נתיב שנבחר בצד השרת
                return {"ok": True, "path": path}
            except Exception:
                try:
                    import pathlib
                    webbrowser.open(pathlib.Path(path).as_uri())
                    return {"ok": True, "path": path}
                except Exception as e2:
                    return {"ok": False, "path": path, "error": str(e2)}
        except Exception as e:
            logging.exception("open_print_profile failed")
            return {"ok": False, "error": str(e)}

    def get_backup_status(self):
        return db.backup_status()

    def run_auto_backup(self, reason="manual"):
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        return db.auto_backup(str(reason), force=True)

    def set_auto_backup(self, enabled):
        db.set_setting("auto_backup_enabled", "1" if enabled else "0")
        return {"ok": True, "enabled": bool(enabled)}

    def empty_trash(self):
        try:
            return {"ok": True, "count": db.empty_trash()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── לוח ─────────────────────────────────────────────────────────
    def copy_to_clipboard(self, text):
        """העתקה ללוח של Windows (CF_UNICODETEXT) — ה-WebView לא תמיד מאפשר navigator.clipboard"""
        try:
            import ctypes
            text = str(text or "")
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            k32.GlobalAlloc.restype = ctypes.c_void_p
            k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            u32.SetClipboardData.restype = ctypes.c_void_p
            u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            if not u32.OpenClipboard(None):
                return {"ok": False, "error": "הלוח תפוס על ידי תוכנה אחרת"}
            try:
                u32.EmptyClipboard()
                data = text.encode("utf-16-le") + b"\x00\x00"
                h = k32.GlobalAlloc(0x0002, len(data))          # GMEM_MOVEABLE
                p = k32.GlobalLock(h)
                ctypes.memmove(p, data, len(data))
                k32.GlobalUnlock(h)
                u32.SetClipboardData(13, h)                     # CF_UNICODETEXT
            finally:
                u32.CloseClipboard()
            return {"ok": True}
        except Exception as e:
            logging.exception("copy_to_clipboard failed")
            return {"ok": False, "error": str(e)}

    # ── בריאות המאגר ────────────────────────────────────────────────
    def get_db_health(self):
        try:
            h = db.db_health()
            h.update({"ok": True, "log_path": _LOG_PATH, "data_dir": _DATA_DIR,
                      "version": APP_VERSION, "install_type": _install_type()})
            return h
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _busy(self):
        """פעולה כבדה/הרסנית לא רצה בזמן שמשהו אחר עובד על המאגר.
        מחזיר הודעה בעברית או None. עד 0.8.5 רק גיבוי/שחזור/vacuum נשמרו כך,
        ואיפוס/מחיקה/שינוי מקור יכלו לרוץ באמצע סריקה ולהתנגש עליה."""
        for st, what in ((_scrape_state, "סריקה"), (_import_state, "ייבוא"),
                         (_source_state, "עדכון מקור"), (_chz_state, "ניתוח חזונישניק"),
                         (_stink_state, "ניתוח שטינקניק")):
            if st.get("running"):
                return f"{what} רצה כרגע ברקע — המתן לסיומה"
        return None

    def vacuum_db(self):
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        # vacuum/restore/reset לא מרימים דגל "running", ולכן _busy לא מכסה אותם
        # והטיק היה יכול להתחיל סריקה בדיוק לתוכם.
        _sched_hold.set()
        try:
            return {"ok": True, "size": db.vacuum()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            _sched_hold.clear()

    def open_data_folder(self):
        try:
            os.startfile(_DATA_DIR)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_log(self):
        try:
            os.startfile(_LOG_PATH)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_last_scrapes(self):
        """{שם פורום: זמן סריקה אחרון (ISO)} — למד 'נסרק לאחרונה' בדיאלוג הסנכרון"""
        out = {}
        for f in db.get_forums():
            ts = db.get_setting(f"last_scrape_{f['name']}", "")
            if ts:
                out[f["name"]] = ts
        return out

    # ── סנכרון לאינטרנט (סריקת פורומי NodeBB) ──────────────────────
    # ── סריקה מתוזמנת ──────────────────────────────────────────────
    def get_schedule(self):
        cfg = db.get_schedule()
        cfg["notify"] = db.sched_pop_notify()      # הודעה חד-פעמית
        cfg["due"] = db.sched_due_forums()
        return cfg

    def set_schedule(self, enabled=None, mode=None, at=None, every_hours=None,
                     forums=None):
        try:
            return {"ok": True, **db.set_schedule(enabled, mode, at, every_hours, forums)}
        except Exception as e:
            logging.exception("set_schedule failed")
            return {"ok": False, "error": str(e)}

    def run_schedule_now(self):
        """הרצה ידנית של מה שמתוזמן — לבדיקה, בלי להמתין לשעה."""
        due = db.sched_due_forums()
        if not due:
            return {"ok": False, "error": "אין כרגע פורום שמגיע לו להיסרק"}
        return self._start_scheduled(due)

    def _start_scheduled(self, due):
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        # cookie="" במכוון: start_scrape_all קורא עוגייה שמורה לכל פורום בנפרד
        # (כלל הפרטיות מ-0.8.3). אין כאן שום קוד עוגיות חדש.
        r = self.start_scrape_all(cookie="", only_forums=due)
        if r.get("ok"):
            _scrape_state["auto"] = True
        return r

    def get_scrapable_forums(self):
        """מחזיר את הפורומים המובנים עם כתובת, לבחירה בממשק הסנכרון"""
        forums = db.get_forums()
        return [f for f in forums if (f.get("url") or "").strip()]

    def check_forum(self, forum_url, cookie=""):
        """בדיקה מקדימה של הפורום — מזהה פלטפורמה (NodeBB/Discourse) ושומר עוגייה+פלטפורמה"""
        try:
            res = scraper.check_forum(forum_url, cookie=cookie or None)
            if res.get("platform") and res["platform"] != "unknown":
                db.set_forum_platform_by_url(forum_url, res["platform"])
            if (cookie or "").strip():
                db.save_cookie_for_url(forum_url, cookie)
            return res
        except Exception as e:
            return {"ok": False, "user_count": None, "title": None,
                    "platform": "unknown", "error": str(e)}

    def start_scrape(self, forum_name, forum_url, cookie="", max_pages=None):
        """מתחיל סריקה ברקע. הממשק יסקור התקדמות דרך get_scrape_progress."""
        if _scrape_state["running"]:
            return {"ok": False, "error": "סריקה כבר רצה"}

        # שמור עוגייה לדומיין (לשימוש חוזר), והשתמש בשמורה אם לא סופקה חדשה
        if (cookie or "").strip():
            db.save_cookie_for_url(forum_url, cookie)
        else:
            cookie = db.get_cookie_for_url(forum_url) or ""
        platform = db.get_forum_platform(forum_name)

        _scrape_cancel.clear()
        _scrape_state.update({
            "running": True, "done": False, "error": None,
            "page": 0, "total_pages": 0,
            "added": 0, "updated": 0, "unchanged": 0,
            "forum": forum_name, "cancelled": False, "run_id": None, "auto": False,
            "user_skipped": False, "aborted": False,
            # אפס מצב רב-פורומי שנותר מ'סרוק הכל'/'סנכרן נבחרים' קודמים
            "all_mode": False, "selected_mode": False,
            "forum_index": 0, "forum_total": 0, "skipped": [],
        })

        def _progress(p):
            _scrape_state.update({
                "page": p.get("page", 0),
                "total_pages": p.get("total_pages", 0),
                "added": p.get("added", 0),
                "updated": p.get("updated", 0),
                "unchanged": p.get("unchanged", 0),
                "failed_pages": p.get("failed_pages", 0),
            })

        def _run():
            try:
                mp = int(max_pages) if max_pages else None
                run_id = db.start_scan_run(forum_name)
                _scrape_state["run_id"] = run_id
                try:
                    stats = scraper.scrape_forum(
                        forum_name, forum_url, db,
                        cookie=cookie or None,
                        progress_cb=_progress,
                        cancel_flag=_scrape_cancel,
                        max_pages=mp,
                        platform=platform,
                        run_id=run_id,
                    )
                finally:
                    # תמיד סוגרים את רשומת הסריקה — גם בביטול או בשגיאה
                    db.finish_scan_run(run_id, {
                        "added": _scrape_state.get("added", 0),
                        "updated": _scrape_state.get("updated", 0),
                        "unchanged": _scrape_state.get("unchanged", 0),
                        "failed_pages": _scrape_state.get("failed_pages", 0)})
                _scrape_state["cancelled"] = _scrape_cancel.is_set()
                if not _scrape_state["cancelled"]:
                    import datetime as _dt
                    # UTC — הממשק מפרש את הערך הזה כ-UTC (כמו datetime('now') של SQLite)
                    db.set_setting(f"last_scrape_{forum_name}",
                                   _dt.datetime.utcnow().isoformat(timespec="minutes"))
            except Exception as e:
                _scrape_state["error"] = str(e)
            finally:
                _scrape_state["running"] = False
                _scrape_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def get_scrape_progress(self):
        return dict(_scrape_state)

    def start_scrape_all(self, cookie="", max_pages=None, only_forums=None):
        """סורק את כל הפורומים ברצף, עם דילוג אוטומטי על פורום שנכשל.
        cookie אינו בשימוש כאן במכוון — כל פורום משתמש רק בעוגייה השמורה שלו.
        only_forums — רשימת שמות לסריקה חוזרת של תת-קבוצה (למשל הפורומים שדולגו)."""
        if _scrape_state["running"]:
            return {"ok": False, "error": "סריקה כבר רצה"}

        wanted = set(only_forums or [])
        forums = [f for f in db.get_forums()
                  if (f.get("url") or "").strip() and (not wanted or f["name"] in wanted)]
        if not forums:
            return {"ok": False, "error": "אין פורומים עם כתובת לסריקה"}

        _scrape_cancel.clear()
        _scrape_state.update({
            "running": True, "done": False, "error": None,
            "page": 0, "total_pages": 0,
            "added": 0, "updated": 0, "unchanged": 0,
            "forum": None, "cancelled": False,
            "all_mode": True, "selected_mode": False, "run_id": None, "auto": False, "user_skipped": False, "aborted": False,   # אפס מצב מ'סנכרן נבחרים' קודם
            "forum_index": 0, "forum_total": len(forums),
            "skipped": [], "failed_pages": 0,
        })

        # מצטבר מהפורומים שהסתיימו; ההתקדמות מציגה מצטבר + הפורום הרץ כרגע
        base = {"added": 0, "updated": 0, "failed_pages": 0}

        def _progress(p):
            _scrape_state.update({
                "page": p.get("page", 0),
                "total_pages": p.get("total_pages", 0),
                "added":   base["added"]   + p.get("added", 0),
                "updated": base["updated"] + p.get("updated", 0),
                "failed_pages": base["failed_pages"] + p.get("failed_pages", 0),
            })

        def _run():
          try:
            for i, f in enumerate(forums):
                if _scrape_cancel.is_set():
                    _scrape_state["cancelled"] = True
                    break
                _scrape_state["forum"] = f["name"]
                _scrape_state["forum_index"] = i + 1
                _scrape_state["page"] = 0
                _scrape_state["total_pages"] = 0
                _scrape_skip.clear()
                try:
                    # פרטיות: משתמשים אך ורק בעוגייה השמורה של הפורום הזה.
                    # אין להעביר עוגיית התחברות של פורום אחד לכל שאר הפורומים.
                    fcookie = db.get_cookie_for_url(f["url"]) or None
                    mp = int(max_pages) if max_pages else None
                    run_id = db.start_scan_run(f["name"])
                    _scrape_state["run_id"] = run_id
                    try:
                        stats = scraper.scrape_forum(
                            f["name"], f["url"], db,
                            cookie=fcookie,
                            progress_cb=_progress,
                            cancel_flag=_scrape_cancel,
                            skip_flag=_scrape_skip,
                            max_pages=mp,
                            platform=f.get("platform") or "nodebb",
                            run_id=run_id,
                        )
                    except Exception:
                        db.finish_scan_run(run_id, {})   # פורום שנכשל — הרשומה נסגרת
                        raise
                    db.finish_scan_run(run_id, stats or {})
                    base["added"]   += stats.get("added", 0)
                    base["updated"] += stats.get("updated", 0)
                    base["failed_pages"] += stats.get("failed_pages", 0)
                    _scrape_state["failed_pages"] = base["failed_pages"]
                    if stats.get("aborted"):
                        _scrape_state["aborted"] = True
                    if not stats.get("cancelled") and not stats.get("skipped"):
                        import datetime as _dt
                        db.set_setting(f"last_scrape_{f['name']}",
                                       _dt.datetime.utcnow().isoformat(timespec="minutes"))
                    _scrape_state["added"]   = base["added"]
                    _scrape_state["updated"] = base["updated"]
                except Exception as e:
                    # דילוג אוטומטי על פורום שנכשל
                    _scrape_state["skipped"].append({"forum": f["name"], "error": str(e)})
                    continue
          except Exception as e:
            # בלי זה, חריגה כאן משאירה את התוכנה במצב "סורק" לצמיתות
            logging.exception("scrape_all worker crashed")
            _scrape_state["error"] = str(e)
          finally:
            if _scrape_state.get("auto"):
                if _scrape_state.get("cancelled") or _scrape_state.get("user_skipped"):
                    # המשתמש עצר או דילג. אלה לא כותבים last_scrape, ולכן הפורום
                    # נשאר "מגיע לו" והטיק הבא היה מפעיל אותו שוב בעוד דקה —
                    # לולאה שנוצרת דווקא מכפתורי השליטה. נודניק, ולא ספירת כישלון.
                    db.sched_snooze(6)
                else:
                    # הצלחה מאפסת את המונה; כישלון חוזר עוצר את התזמון אחרי 5,
                    # כדי לא לנדנד לפורום שנפל או שחסם אותנו.
                    err = _scrape_state.get("error") or ""
                    skipped = _scrape_state.get("skipped") or []
                    if not err and skipped:
                        err = "; ".join(f"{x.get('forum')}: {x.get('error')}" for x in skipped[:3])
                    if not err and _scrape_state.get("aborted"):
                        # נעצר אחרי 5 עמודים כושלים ברצף — זו לא סריקה שהצליחה,
                        # ולספור אותה כהצלחה היה מאפס את מונה הכישלונות לנצח.
                        err = "הסריקה נעצרה אחרי כשלים חוזרים בעמודים"
                    db.sched_note_result(not err, err)
            # חייב להתאפס: אחרת ביטול *ידני* מאוחר יותר היה מנמנם את התזמון
            _scrape_state["auto"] = False
            _scrape_state["running"] = False
            _scrape_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "forum_total": len(forums)}

    def cancel_scrape(self):
        # ביטול לא כותב last_scrape, ולכן הפורום נשאר "מגיע לו" והטיק הבא היה
        # מפעיל אותו שוב בעוד דקה — לולאה שנוצרת דווקא מכפתור העצירה.
        if _scrape_state.get("auto"):
            db.sched_snooze(6)
            _scrape_state["auto"] = False
        _scrape_cancel.set()
        return {"ok": True}

    def skip_current_forum(self):
        _scrape_state["user_skipped"] = True
        """דילוג לפורום הבא (במצב 'סרוק הכל')."""
        _scrape_skip.set()
        return {"ok": True}

    def sync_selected_online(self, nick_ids, cookie=""):
        """
        מסנכרן ניקים נבחרים מהאינטרנט — הערך הסרוק תמיד מנצח (המשתמש בחר במפורש).
        רץ ברקע; התקדמות דרך _scrape_state.
        """
        if _scrape_state["running"]:
            return {"ok": False, "error": "סריקה כבר רצה"}
        ids = [int(i) for i in (nick_ids or [])]
        if not ids:
            return {"ok": False, "error": "לא נבחרו ניקים"}

        _scrape_cancel.clear()
        _scrape_state.update({
            "running": True, "done": False, "error": None,
            "page": 0, "total_pages": len(ids),
            "added": 0, "updated": 0, "unchanged": 0,
            "forum": None, "cancelled": False,
            "all_mode": False, "selected_mode": True, "run_id": None, "auto": False, "user_skipped": False, "aborted": False,
            "forum_index": 0, "forum_total": 0, "skipped": [], "failed_pages": 0,
        })

        # מפת URL ופלטפורמה לכל פורום (קריאת get_forums אחת)
        _forums = db.get_forums()
        forum_urls = {f["name"]: (f.get("url") or "").strip() for f in _forums}
        forum_plats = {f["name"]: (f.get("platform") or "nodebb") for f in _forums}
        _cookie_cache = {}   # origin/url → cookie, כדי לא לפתוח חיבור DB לכל ניק
        def _cookie_for(u):
            if u not in _cookie_cache:
                _cookie_cache[u] = db.get_cookie_for_url(u) or cookie or None
            return _cookie_cache[u]

        def _run():
          updated = 0
          try:
            for i, nid in enumerate(ids):
                if _scrape_cancel.is_set():
                    _scrape_state["cancelled"] = True
                    break
                _scrape_state["page"] = i + 1
                try:
                    nick = db.get_nick(nid)
                    if not nick:
                        continue
                    url = forum_urls.get(nick["forum"], "")
                    if not url:
                        _scrape_state["skipped"].append({"forum": nick.get("username",""), "error": "אין URL לפורום"})
                        continue
                    plat = forum_plats.get(nick["forum"], "nodebb")
                    fcookie = _cookie_for(url)
                except Exception as e:
                    _scrape_state["skipped"].append({"forum": str(nid), "error": str(e)})
                    continue
                try:
                    mapped = scraper.scrape_single_user(url, nick["username"],
                                                        cookie=fcookie, platform=plat)
                    if not mapped:
                        _scrape_state["skipped"].append({"forum": nick["username"], "error": "לא נמצא"})
                        continue
                    # בחירה מפורשת → ערך הסריקה מנצח בתצוגה (הכול בחיבור DB אחד)
                    db.force_scraped_values(nid, mapped)
                    updated += 1
                    _scrape_state["updated"] = updated
                except Exception as e:
                    _scrape_state["skipped"].append({"forum": nick.get("username",""), "error": str(e)})
                    continue
          except Exception as e:
            # בלי זה, חריגה כאן משאירה את התוכנה במצב "סורק" לצמיתות
            logging.exception("sync_selected worker crashed")
            _scrape_state["error"] = str(e)
          finally:
            _scrape_state["running"] = False
            _scrape_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "count": len(ids)}

    def reset_all(self, force=False):
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        # auto_backup לעולם לא מרימה חריגה (דיסק מלא לא אמור לחסום עבודה),
        # ולכן התעלמות מהתוצאה הפכה את הגיבוי-לפני-איפוס למראית עין: דווקא
        # כשהוא נכשל, האיפוס הבלתי הפיך היה מתבצע בלי רשת ביטחון.
        if not force:
            r = db.auto_backup("reset")
            if not r.get("ok"):
                return {"ok": False, "needs_confirm": True,
                        "error": "הגיבוי לפני האיפוס נכשל: " + str(r.get("error", ""))}
        _sched_hold.set()
        try:
            db.reset_all()
        finally:
            _sched_hold.clear()
        return {"ok": True}

    def reset_columns(self, columns, force=False):
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        if not force:
            r = db.auto_backup("reset-cols")
            if not r.get("ok"):
                return {"ok": False, "needs_confirm": True,
                        "error": "הגיבוי לפני האיפוס נכשל: " + str(r.get("error", ""))}
        _sched_hold.set()      # איפוס עמודות נוגע בכל 90 אלף השורות
        try:
            n = db.reset_columns(columns or [])
        finally:
            _sched_hold.clear()
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
        # הדוחות והגיליון להדפסה נוצרים בפייתון ולא עוברים דרך ה-DOM,
        # ולכן צד השרת חייב לדעת מה השפה הנבחרת.
        if key == "lang":
            i18n.set_lang(value)
        return {"ok": True}

    def reset_display_settings(self):
        db.reset_display_settings()
        i18n.set_lang("he")
        return {"ok": True}

    def open_url(self, url):
        """פתח URL בדפדפן ברירת המחדל של המערכת"""
        if not url:
            return {"ok": False, "error": "אין קישור"}
        # רק סכימות מוכרות — webbrowser.open ב-Windows מגיע ל-ShellExecute,
        # שיפעיל גם קובץ מקומי או ms-*: אם ערך מהפורום יגיע לכאן
        from urllib.parse import urlsplit
        if urlsplit(url).scheme.lower() not in ("http", "https", "mailto", "tel"):
            logging.warning("Blocked open_url scheme: %s", url[:120])
            return {"ok": False, "error": "סוג קישור לא נתמך"}
        try:
            webbrowser.open(url)
            return {"ok": True}
        except Exception as e:
            logging.exception("open_url failed for %s", url)
            return {"ok": False, "error": str(e)}

    def run_chazonishnik_compare(self, user_a, user_b, cookie="",
                                 base_url="https://mitmachim.top", max_posts=None):
        """
        השוואת שני משתמשים. משתמש באותו מצב רקע ובאותו ביטול כמו הניתוח הרגיל,
        כדי שהבאנר, ההתקדמות וכפתור הביטול הקיימים ימשיכו לעבוד בלי שינוי.
        """
        if _chz_state["running"]:
            return {"ok": False, "error": "ניתוח כבר רץ"}
        a, b = (user_a or "").strip(), (user_b or "").strip()
        if not a or not b:
            return {"ok": False, "error": "הזן שני שמות משתמש"}
        if a.lower() == b.lower():
            return {"ok": False, "error": "אלה אותו משתמש"}
        base_url = base_url or "https://mitmachim.top"
        cookie = (cookie or "").strip()
        if cookie:
            db.save_cookie_for_url(base_url, cookie)
        else:
            cookie = db.get_cookie_for_url(base_url) or ""
        try:
            max_posts = int(max_posts) if max_posts else None
        except (ValueError, TypeError):
            max_posts = None

        _chz_cancel.clear()
        _chz_state.update({"running": True, "done": False, "error": None,
                           "phase": "scan", "count": 0, "total": 0, "which": 1, "of": 2,
                           "user": a, "compare": True,
                           "html": None, "path": None, "cancelled": False})

        def _progress(p):
            _chz_state["phase"] = p.get("phase", "")
            _chz_state["which"] = p.get("which", 1)
            _chz_state["user"] = p.get("user", "")
            if p.get("phase") == "scan":
                _chz_state["count"] = p.get("count", 0)
            else:
                _chz_state["count"] = p.get("done", 0)
                _chz_state["total"] = p.get("total", 0)

        def _run():
            try:
                import chazonishnik
                out_dir = os.path.dirname(db.DB_PATH)
                safe = "".join(c for c in (a + "-" + b) if c.isalnum() or c in "-_") or "pair"
                save_path = os.path.join(out_dir, f"chazonishnik_compare_{safe}.html")
                result = chazonishnik.analyze_pair(
                    a, b, cookie, base_url=base_url, progress=_progress,
                    save_path=save_path, cancel_flag=_chz_cancel, max_posts=max_posts)
                if result.get("cancelled"):
                    _chz_state["cancelled"] = True
                elif result.get("ok"):
                    _chz_state["html"] = result.get("html")
                    _chz_state["path"] = result.get("path")
                    _chz_state["count"] = result.get("posts", 0)
                    _chz_state["pair"] = {"a": result.get("a"), "b": result.get("b")}
                else:
                    _chz_state["error"] = result.get("error")
            except Exception as e:
                logging.exception("chazonishnik compare failed")
                _chz_state["error"] = str(e)
            finally:
                _chz_state["running"] = False
                _chz_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "started": True}

    def run_chazonishnik(self, username, cookie="", base_url="https://mitmachim.top",
                         max_posts=None):
        """מתחיל ניתוח פעילות ברקע. התקדמות דרך get_chazonishnik_progress.
        עוגייה אופציונלית — פורומים ציבוריים חושפים היסטוריית פוסטים גם בלעדיה.
        max_posts — הגבלת מספר הפוסטים הנסרקים (None = הכל)."""
        if _chz_state["running"]:
            return {"ok": False, "error": "ניתוח כבר רץ"}
        if not username or not username.strip():
            return {"ok": False, "error": "הזן שם משתמש"}
        base_url = base_url or "https://mitmachim.top"
        cookie = (cookie or "").strip()
        if cookie:
            db.save_cookie_for_url(base_url, cookie)
        else:
            cookie = db.get_cookie_for_url(base_url) or ""
        try:
            max_posts = int(max_posts) if max_posts else None
        except (ValueError, TypeError):
            max_posts = None

        _chz_cancel.clear()
        _chz_state.update({"running": True, "done": False, "error": None,
                           "phase": "scan", "count": 0, "total": 0, "compare": False,
                           "html": None, "path": None, "cancelled": False})

        def _progress(p):
            _chz_state["phase"] = p.get("phase", "")
            if p.get("phase") == "scan":
                _chz_state["count"] = p.get("count", 0)
            else:
                _chz_state["count"] = p.get("done", 0)
                _chz_state["total"] = p.get("total", 0)

        def _run():
            try:
                import chazonishnik
                out_dir = os.path.dirname(db.DB_PATH)
                safe = "".join(c for c in username if c.isalnum() or c in "-_") or "user"
                save_path = os.path.join(out_dir, f"chazonishnik_{safe}.html")
                result = chazonishnik.analyze_user(
                    username, cookie, base_url=base_url,
                    progress=_progress, save_path=save_path, cancel_flag=_chz_cancel,
                    max_posts=max_posts)
                if result.get("cancelled"):
                    _chz_state["cancelled"] = True
                elif result.get("ok"):
                    _chz_state["html"] = result.get("html")
                    _chz_state["path"] = result.get("path")
                    _chz_state["count"] = result.get("posts", 0)
                    _chz_state["postcount"] = result.get("postcount", 0)
                    _chz_state["partial"] = result.get("partial", False)
                    _chz_state["stopped_early"] = result.get("stopped_early", False)
                    _chz_state["limited"] = result.get("limited", False)
                else:
                    _chz_state["error"] = result.get("error")
            except Exception as e:
                logging.exception("chazonishnik failed")
                _chz_state["error"] = str(e)
            finally:
                _chz_state["running"] = False
                _chz_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def get_chazonishnik_progress(self):
        return dict(_chz_state)

    # ── Stinknik — ניתוח דיסלייקים ─────────────────────────────────
    def run_stinknik(self, user_input, cookie="", base_url="https://mitmachim.top",
                     max_posts=None):
        """מתחיל ניתוח דיסלייקים ברקע. התקדמות דרך get_stinknik_progress.
        max_posts — הגבלת מספר הפוסטים הנסרקים (None = הכל)."""
        if _stink_state["running"]:
            return {"ok": False, "error": "ניתוח כבר רץ"}
        if not user_input or not user_input.strip():
            return {"ok": False, "error": "הזן שם משתמש או קישור לפרופיל"}
        base_url = base_url or "https://mitmachim.top"
        cookie = (cookie or "").strip()
        if cookie:
            db.save_cookie_for_url(base_url, cookie)
        else:
            cookie = db.get_cookie_for_url(base_url) or ""
        try:
            max_posts = int(max_posts) if max_posts else None
        except (ValueError, TypeError):
            max_posts = None
        _stink_cancel.clear()
        _stink_state.update({"running": True, "done": False, "error": None,
                             "checked": 0, "page": 0, "disliked": 0,
                             "html": None, "cancelled": False})

        def _progress(p):
            _stink_state["checked"] = p.get("checked", 0)
            _stink_state["page"] = p.get("page", 0)
            _stink_state["disliked"] = p.get("disliked", 0)

        def _run():
            try:
                import stinknik
                result = stinknik.analyze_dislikes(
                    user_input, base_url=base_url,
                    cookie=(cookie or None), progress=_progress, cancel_flag=_stink_cancel,
                    max_posts=max_posts)
                if result.get("cancelled"):
                    _stink_state["cancelled"] = True
                elif result.get("ok"):
                    _stink_state["html"] = result.get("html")
                    _stink_state["disliked"] = result.get("disliked", 0)
                    _stink_state["checked"] = result.get("checked", 0)
                    _stink_state["postcount"] = result.get("postcount", 0)
                    _stink_state["partial"] = result.get("partial", False)
                    _stink_state["stopped_early"] = result.get("stopped_early", False)
                    _stink_state["limited"] = result.get("limited", False)
                else:
                    _stink_state["error"] = result.get("error")
            except Exception as e:
                logging.exception("stinknik failed")
                _stink_state["error"] = str(e)
            finally:
                _stink_state["running"] = False
                _stink_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def get_stinknik_progress(self):
        return dict(_stink_state)

    def cancel_stinknik(self):
        _stink_cancel.set()
        return {"ok": True}

    def save_stinknik_report(self, html=None):
        content = html or _stink_state.get("html")
        if not content:
            return {"ok": False, "error": "אין דוח לשמירה"}
        try:
            import webview
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG, save_filename="stinknik_report.html",
                file_types=("HTML Files (*.html)",))
            if not result:
                return {"ok": False, "error": "בוטל"}
            path = result if isinstance(result, str) else result[0]
            if not path.lower().endswith(".html"):
                path += ".html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "path": path}
        except Exception as e:
            logging.exception("save_stinknik_report failed")
            return {"ok": False, "error": str(e)}

    def cancel_chazonishnik(self):
        _chz_cancel.set()
        return {"ok": True}

    def save_chazonishnik_report(self, html=None):
        """שמירת הדוח כקובץ HTML במיקום לבחירת המשתמש (דיאלוג שמירה)."""
        content = html or _chz_state.get("html")
        if not content:
            return {"ok": False, "error": "אין דוח לשמירה"}
        try:
            import webview
            windows = webview.windows
            result = windows[0].create_file_dialog(
                webview.SAVE_DIALOG, save_filename="chazonishnik_report.html",
                file_types=("HTML Files (*.html)",))
            if not result:
                return {"ok": False, "error": "בוטל"}
            path = result if isinstance(result, str) else result[0]
            if not path.lower().endswith(".html"):
                path += ".html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "path": path}
        except Exception as e:
            logging.exception("save_chazonishnik_report failed")
            return {"ok": False, "error": str(e)}

    # ── בדיקת עדכונים מ-GitHub ──────────────────────────────────────
    def get_app_version(self):
        return {"version": APP_VERSION, "repo": GITHUB_REPO,
                "install_type": _install_type()}

    def download_update(self, download_url):
        """מוריד את קובץ העדכון (EXE נייד או Setup) לפי סוג ההתקנה. מחזיר את הנתיב."""
        import urllib.request, sys as _sys, tempfile
        from urllib.parse import urlsplit
        if not download_url:
            return {"ok": False, "error": "אין קישור הורדה"}
        # רק מארחים של GitHub, ורק https — כדי שקריאה זו לא תוכל לשמש להורדת
        # קובץ שרירותי (למשל מקוד שהוזרק לדוח) והרצתו דרך apply_update.
        _parts = urlsplit(download_url)
        _host = (_parts.hostname or "").lower()
        if _parts.scheme != "https" or not (
                _host == "github.com" or _host.endswith(".github.com")
                or _host == "objects.githubusercontent.com"
                or _host.endswith(".githubusercontent.com")):
            logging.error("Blocked update download from untrusted host: %s", download_url)
            return {"ok": False, "error": "מקור ההורדה אינו מזוהה — העדכון בוטל"}
        # רק כשרצים כ-EXE (frozen)
        if not getattr(_sys, "frozen", False):
            return {"ok": False, "error": "עדכון מתוך התוכנה זמין רק בגרסת ה-EXE"}
        try:
            cur_exe = _sys.executable
            if _install_type() == "installer":
                # אינסטולר: מורידים לתיקייה זמנית (תיקיית ההתקנה לרוב אינה כתיבה)
                new_path = os.path.join(tempfile.gettempdir(), "TikNick-Setup-new.exe")
            else:
                new_path = os.path.join(os.path.dirname(cur_exe), "TikNick_new.exe")
            req = urllib.request.Request(download_url, headers={"User-Agent": "TikNick-Updater"})
            with net.urlopen(req, timeout=60) as resp, open(new_path, "wb") as out:
                total = int(resp.headers.get("Content-Length", 0))
                got = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
                    _update_state["downloaded"] = got
                    _update_state["total"] = total

            # שער בטיחות: ודא שהקובץ שהורד תואם לסוג ההתקנה (לפי תוכן, לא לפי שם)
            is_setup = _looks_like_inno_setup(new_path)
            want_setup = _install_type() == "installer"
            if is_setup != want_setup:
                try:
                    os.remove(new_path)
                except Exception:
                    pass
                logging.error("Update asset mismatch: is_setup=%s want_setup=%s url=%s",
                              is_setup, want_setup, download_url)
                return {"ok": False, "error": (
                    "קובץ העדכון שהורד אינו מתאים לסוג ההתקנה שלך "
                    f"({'מותקנת' if want_setup else 'ניידת'}). "
                    "העדכון בוטל — אפשר להוריד ידנית מדף ההורדות.")}
            return {"ok": True, "path": new_path}
        except Exception as e:
            logging.exception("download_update failed")
            return {"ok": False, "error": str(e)}

    def get_update_download_progress(self):
        return dict(_update_state)

    def _settle_pending_update(self):
        """
        סימון שנכתב לפני ניסיון עדכון. אם התוכנה עלתה שוב *באותה גרסה* —
        העדכון נכשל, וצריך לומר את זה במקום להעמיד פנים שלא קרה כלום.
        """
        marker = os.path.join(_DATA_DIR, "update-pending.txt")
        if not os.path.exists(marker):
            return None
        try:
            with open(marker, "r", encoding="utf-8") as f:
                target = (f.read() or "").strip()
        except OSError:
            target = ""
        try:
            os.remove(marker)
        except OSError:
            pass
        if target and target != APP_VERSION:
            inno_log = os.path.join(_DATA_DIR, "update-inno.log")
            logging.warning("update to %s did not take effect (still %s)", target, APP_VERSION)
            return {"target": target, "current": APP_VERSION,
                    "log": inno_log if os.path.exists(inno_log) else ""}
        return None

    def settle_pending_update(self):
        try:
            return self._settle_pending_update()
        except Exception:
            logging.exception("settle_pending_update failed")
            return None

    def open_update_log(self):
        for name in ("update-inno.log", "update.log"):
            path = os.path.join(_DATA_DIR, name)
            if os.path.exists(path):
                try:
                    os.startfile(path)      # noqa: S606 — נתיב שנבחר בצד השרת
                    return {"ok": True, "path": path}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "אין יומן התקנה"}

    def consume_update_failure(self):
        """האם עדכון קודם נכשל בהחלפת הקובץ? (סימון שכותב סקריפט העדכון) — חד-פעמי."""
        try:
            if not getattr(sys, "frozen", False):
                return {"failed": False}
            marker = os.path.join(os.path.dirname(sys.executable), "update-failed.txt")
            if os.path.exists(marker):
                os.remove(marker)
                return {"failed": True}
        except Exception:
            pass
        return {"failed": False}

    def apply_update(self, new_exe_path):
        """
        מחליף את ה-EXE הישן בחדש: כותב סקריפט batch שממתין לסגירת התוכנה,
        מחליף את הקובץ, ומריץ מחדש. ואז סוגר את התוכנה.
        """
        import sys as _sys, subprocess, tempfile
        if not getattr(_sys, "frozen", False):
            return {"ok": False, "error": "זמין רק בגרסת ה-EXE"}
        if not new_exe_path or not os.path.exists(new_exe_path):
            return {"ok": False, "error": "קובץ העדכון לא נמצא"}

        # גרסת אינסטולר: מריצים את ה-Setup בשקט (הוא מחליף את הקבצים,
        # סוגר את התהליך הישן אם נשאר, ומפעיל מחדש דרך סעיף [Run])
        if _install_type() == "installer":
            # מה שהיה כאן קודם נכשל בשקט מוחלט: בלי /LOG אין שום עקבה, בלי ניקוי
            # סביבה ה-Setup יורש את משתני ה-_MEI של PyInstaller, ובלי סימון —
            # התוכנה חוזרת בגרסה הישנה בלי מילה, וזה נראה למשתמש כ"העדכון נפל".
            inno_log = os.path.join(_DATA_DIR, "update-inno.log")
            marker = os.path.join(_DATA_DIR, "update-pending.txt")
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(str(_update_state.get("target_version") or ""))
            except OSError:
                pass
            try:
                # ה-Setup חייב לרוץ *אחרי* שהתוכנה נסגרה. הרצה מקבילה נכשלת:
                # RestartManager מזהה את התהליך החי, לא מצליח לסגור אותו
                # ("Some applications could not be shut down"), ומבטל את
                # ההתקנה. לכן batch שממתין ל-PID ורק אז מריץ — בדיוק כמו
                # במסלול הנייד.
                pid = os.getpid()
                exe_name = os.path.basename(_sys.executable)
                proc_name = os.path.splitext(exe_name)[0]
                log_file = os.path.join(_DATA_DIR, "update.log")
                bat = os.path.join(tempfile.gettempdir(), "tiknick_setup.bat")
                script = f"""@echo off
chcp 65001 >nul
set "_MEIPASS2="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="

rem — המתנה דרך PowerShell ולא tasklist: /FI "IMAGENAME eq ..." החזיר "לא נמצא"
rem על תהליך חי (Get-Process כן מצא אותו), וזה בדיוק המנגנון שההמתנה נשענה עליו
rem מאז 0.8.3 — כלומר ההמתנה יכלה להסתיים מיד וההתקנה לרוץ אל תוך תוכנה פתוחה.
rem הסקריפט ממתין לתהליך שלנו, ואז לכל עותק אחר, ורק אז סוגר בכוח מה שנשאר.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='SilentlyContinue';" ^
 "for($i=0;$i -lt 60 -and (Get-Process -Id {pid});$i++){{Start-Sleep -Milliseconds 500}};" ^
 "for($i=0;$i -lt 20 -and (Get-Process -Name '{proc_name}');$i++){{Start-Sleep -Milliseconds 500}};" ^
 "$left=Get-Process -Name '{proc_name}';" ^
 "if($left){{Add-Content -LiteralPath '{log_file}' -Value ('[' + (Get-Date -Format HH:mm:ss) + '] leftover {proc_name} still up - forcing close');" ^
 "$left | Stop-Process -Force; Start-Sleep -Milliseconds 800}}"
ping -n 3 127.0.0.1 >nul

"{new_exe_path}" /SILENT /SUPPRESSMSGBOXES /NOCANCEL /CLOSEAPPLICATIONS /LOG="{inno_log}"
del "%~f0"
"""
                with open(bat, "w", encoding="utf-8") as f:
                    f.write(script)
                clean_env = {k: v for k, v in os.environ.items()
                             if not k.startswith("_MEI") and not k.startswith("_PYI")}
                subprocess.Popen(["cmd", "/c", bat], env=clean_env,
                                 cwd=tempfile.gettempdir(),
                                 creationflags=0x08000000)   # CREATE_NO_WINDOW
                logging.info("installer update scheduled after pid %s (log: %s)",
                             pid, inno_log)
                try:
                    webview.windows[0].destroy()
                except Exception:
                    pass
                os._exit(0)
            except Exception as e:
                logging.exception("apply_update (installer) failed")
                return {"ok": False, "error": str(e)}

        try:
            cur_exe = _sys.executable
            exe_name = os.path.basename(cur_exe)
            proc_name = os.path.splitext(exe_name)[0]
            pid = os.getpid()
            fail_marker = os.path.join(os.path.dirname(cur_exe), "update-failed.txt")
            old_exe = cur_exe + ".old"
            # יומן של ה-batch עצמו: בלעדיו כישלון החלפה נראה בדיוק כמו הצלחה —
            # התוכנה פשוט חוזרת בגרסה הישנה בלי מילה.
            log_file = os.path.join(_DATA_DIR, "update.log")
            bat = os.path.join(tempfile.gettempdir(), "tiknick_update.bat")
            # ממתין לסגירה מלאה, נותן ל-PyInstaller לנקות את _MEI, מחליף עם ניסיונות
            # חוזרים, ומריץ מחדש בסביבה נקייה (מנקה _MEIPASS2 כדי למנוע שגיאת DLL).
            script = f"""@echo off
chcp 65001 >nul
title Tik-Nick Updater
echo מעדכן את Tik-Nick, נא להמתין...

rem — נקה משתני PyInstaller שירשנו מהתהליך הישן (מונע שגיאת python DLL) —
set "_MEIPASS2="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="

rem — המתנה דרך PowerShell ולא tasklist: /FI "IMAGENAME eq ..." החזיר "לא נמצא"
rem על תהליך חי (Get-Process כן מצא אותו), וזה בדיוק המנגנון שההמתנה נשענה עליו
rem מאז 0.8.3 — כלומר ההמתנה יכלה להסתיים מיד וההתקנה לרוץ אל תוך תוכנה פתוחה.
rem הסקריפט ממתין לתהליך שלנו, ואז לכל עותק אחר, ורק אז סוגר בכוח מה שנשאר.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='SilentlyContinue';" ^
 "for($i=0;$i -lt 60 -and (Get-Process -Id {pid});$i++){{Start-Sleep -Milliseconds 500}};" ^
 "for($i=0;$i -lt 20 -and (Get-Process -Name '{proc_name}');$i++){{Start-Sleep -Milliseconds 500}};" ^
 "$left=Get-Process -Name '{proc_name}';" ^
 "if($left){{Add-Content -LiteralPath '{log_file}' -Value ('[' + (Get-Date -Format HH:mm:ss) + '] leftover {proc_name} still up - forcing close');" ^
 "$left | Stop-Process -Force; Start-Sleep -Milliseconds 800}}"

rem — המתן עוד רגע לשחרור קבצים וניקוי _MEI —
ping -n 4 127.0.0.1 >nul

rem ── ההחלפה עצמה ──────────────────────────────────────────────────
rem Windows מרשה *לשנות שם* לקובץ הרצה גם כשהוא נעול, אבל לא לדרוס אותו.
rem לכן: מזיזים את הישן הצידה, ורק אז מכניסים את החדש. ניסיון דריסה ישיר
rem (move /Y new cur) נכשל בשקט כשמשהו עדיין מחזיק את הקובץ — אנטי-וירוס
rem שסורק את ההורדה, ניקוי _MEI, או סייר קבצים פתוח על התיקייה.
set /a tries=0
:swaptry
del /F /Q "{old_exe}" >nul 2>&1
move /Y "{cur_exe}" "{old_exe}" >nul 2>&1
if exist "{cur_exe}" (
    set /a tries+=1
    echo [%%time%%] step1 rename-aside failed, try %%tries%%>> "{log_file}"
    if %tries% lss 20 (
        ping -n 2 127.0.0.1 >nul
        goto swaptry
    )
    echo [%%time%%] GIVING UP: could not move the running exe aside>> "{log_file}"
    echo rename-aside failed> "{fail_marker}"
    goto restart
)

move /Y "{new_exe_path}" "{cur_exe}" >nul 2>&1
if not exist "{cur_exe}" (
    rem — הכנסת החדש נכשלה: מחזירים את הישן כדי לא להשאיר את המשתמש בלי תוכנה
    echo [%%time%%] step2 install-new failed, rolling back>> "{log_file}"
    move /Y "{old_exe}" "{cur_exe}" >nul 2>&1
    echo install-new failed> "{fail_marker}"
    goto restart
)

echo [%%time%%] update applied successfully>> "{log_file}"
del /F /Q "{old_exe}" >nul 2>&1

:restart
rem — הפעל מחדש בסביבה נקייה (cmd חדש בלי משתני PyInstaller) —
ping -n 3 127.0.0.1 >nul
start "" /D "{os.path.dirname(cur_exe)}" "{cur_exe}"
del "%~f0"
"""
            with open(bat, "w", encoding="utf-8") as f:
                f.write(script)
            # הרץ את ה-batch בסביבה נקייה: TEMP אמיתי, בלי משתני _MEI של PyInstaller
            clean_env = {k: v for k, v in os.environ.items()
                         if not k.startswith("_MEI") and not k.startswith("_PYI")}
            real_temp = os.environ.get("SYSTEMROOT", r"C:\Windows")
            # השתמש ב-TEMP של המשתמש (מחוץ ל-_MEI)
            user_temp = os.path.join(os.environ.get("LOCALAPPDATA", real_temp), "Temp")
            if os.path.isdir(user_temp):
                clean_env["TEMP"] = user_temp
                clean_env["TMP"] = user_temp
            subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000, env=clean_env)
            # סגור את התוכנה כדי לאפשר את ההחלפה
            try:
                webview.windows[0].destroy()
            except Exception:
                pass
            os._exit(0)
        except Exception as e:
            logging.exception("apply_update failed")
            return {"ok": False, "error": str(e)}

    def _fallback_latest(self):
        """
        גרסה אחרונה בלי ה-API: קוראים את changelog.json מ-raw (אותו קובץ
        שהתקציר כבר נשען עליו) ובונים את כתובות ההורדה לפי המוסכמה הקבועה
        של השחרורים. raw.githubusercontent.com אינו תחת אותה תקרת בקשות.
        """
        import urllib.request
        import json as _json
        url = (f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/changelog.json")
        req = urllib.request.Request(url, headers={"User-Agent": "TikNick-UpdateCheck"})
        with net.urlopen(req, timeout=8) as resp:
            log = _json.loads(resp.read().decode("utf-8"))
        ver = ((log.get("versions") or [{}])[0].get("v") or "").strip()
        if not ver:
            raise ValueError("changelog.json without a version")
        base = f"https://github.com/{GITHUB_REPO}/releases/download/v{ver}"
        return {
            "tag_name": "v" + ver,
            "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/v{ver}",
            "body": "",
            "assets": [{"name": "TikNick-Setup.exe",
                        "browser_download_url": base + "/TikNick-Setup.exe"},
                       {"name": "TikNick.exe",
                        "browser_download_url": base + "/TikNick.exe"}],
        }

    def check_for_updates(self):
        """בודק אם קיימת גרסה חדשה יותר ב-GitHub Releases."""
        import urllib.request
        import json as _json
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        why = ""
        try:
            req = urllib.request.Request(
                api_url, headers={"User-Agent": "TikNick-UpdateCheck"})
            with net.urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            # ה-API נפל — עדיין אפשר לדעת מה הגרסה האחרונה בלעדיו.
            logging.info("Update check via API failed: %s", e)
            why = _update_error_text(e)
            try:
                data = self._fallback_latest()
                logging.info("Update check fell back to raw changelog.json")
                why = ""
            except Exception as e2:
                logging.info("Update fallback failed too: %s", e2)
                return {"ok": False, "error": why or _update_error_text(e2)}

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

        # בחר את הנכס המתאים לסוג ההתקנה:
        #   installer → קובץ Setup (שם מכיל setup/install)
        #   portable  → ה-EXE הרגיל
        install_type = _install_type()
        portable_url = setup_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if not name.endswith(".exe"):
                continue
            url = asset.get("browser_download_url", "")
            if "setup" in name or "install" in name:
                if not setup_url:
                    setup_url = url
            elif not portable_url:
                portable_url = url

        # התאמה קפדנית: ניידת מקבלת רק EXE נייד, מותקנת רק Setup.
        # אם הנכס המתאים חסר — נשארים בלי קישור הורדה ישיר (הממשק יפתח את דף ה-Release),
        # כדי לא להריץ בטעות מתקין על גרסה ניידת או להפך.
        download_url = setup_url if install_type == "installer" else portable_url

        _update_state["target_version"] = latest
        return {
            "ok": True,
            "current": current,
            "latest": latest,
            "update_available": is_newer,
            "install_type": install_type,
            "release_url": data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
            "download_url": download_url,
            "notes": (data.get("body") or "")[:800],
        }

    # ── תקציר שינויים מותאם לגודל הקפיצה ───────────────────────────
    def get_update_summary(self, from_version=None, to_version=None):
        """
        מה השתנה בין הגרסה שרצה לגרסה החדשה. הניסוח *משתנה לפי גודל הקפיצה*:
        קפיצה של גרסה אחת מקבלת את הפירוט המלא, קפיצה של שמונה מקבלת רק את
        הכותרות — אחרת מי שמדלג על חצי שנה מקבל קיר טקסט ולא קורא כלום.
        נכשל בשקט: אם היומן לא נטען, הדיאלוג פשוט לא יציג תקציר.
        """
        import urllib.request
        import json as _json
        cur = (from_version or APP_VERSION).strip()
        try:
            url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/changelog.json"
            req = urllib.request.Request(url, headers={"User-Agent": "TikNick-Updater"})
            with net.urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logging.info("changelog fetch failed: %s", e)
            return {"ok": False, "error": "לא ניתן לטעון את יומן השינויים"}

        def parse(v):
            out = []
            for part in str(v).split("."):
                digits = "".join(c for c in part if c.isdigit())
                out.append(int(digits) if digits else 0)
            while len(out) < 3:
                out.append(0)
            return tuple(out[:3])

        cur_t = parse(cur)
        top_t = parse(to_version) if to_version else None
        newer = []
        for entry in data.get("versions", []):
            vt = parse(entry.get("v", "0"))
            if vt > cur_t and (top_t is None or vt <= top_t):
                newer.append(entry)
        newer.sort(key=lambda e: parse(e["v"]), reverse=True)
        if not newer:
            return {"ok": True, "jump": 0, "versions": [], "groups": [], "headline": ""}

        jump = len(newer)
        all_items = [(e["v"], it) for e in newer for it in (e.get("items") or [])]
        majors = [(v, it) for v, it in all_items if it.get("t") == "major"]
        feats = [(v, it) for v, it in all_items if it.get("t") == "feature"]
        fixes = [(v, it) for v, it in all_items if it.get("t") == "fix"]

        if jump == 1:
            # גרסה אחת: הכול, מקובץ לפי סוג
            mode = "full"
            groups = [g for g in (
                {"title": "חשוב לדעת", "items": [it["s"] for _, it in majors]},
                {"title": "חדש", "items": [it["s"] for _, it in feats]},
                {"title": "תיקונים", "items": [it["s"] for _, it in fixes]},
            ) if g["items"]]
        elif jump <= 3:
            # קפיצה קטנה: חשוב + חדש במלואם, תיקונים רק כמספר
            mode = "grouped"
            groups = [g for g in (
                {"title": "חשוב לדעת", "items": [it["s"] for _, it in majors]},
                {"title": "מה חדש", "items": [it["s"] for _, it in feats]},
            ) if g["items"]]
            if fixes:
                groups.append({"title": "ובנוסף",
                               "items": ["%d תיקונים ושיפורים" % len(fixes)]})
        else:
            # קפיצה גדולה: רק הכותרות, והשאר כמספרים. והתקרה מתהדקת ככל שהקפיצה
            # גדלה — מי שדילג על תשע גרסאות צריך *פחות* טקסט, לא יותר.
            mode = "headlines"
            n_major, n_feat = (3, 4) if jump <= 6 else (2, 3)
            top_feats = [it["s"] for _, it in feats][:n_feat]
            groups = [g for g in (
                {"title": "חשוב לדעת", "items": [it["s"] for _, it in majors][:n_major]},
                {"title": "העיקר שנוסף", "items": top_feats},
            ) if g["items"]]
            rest = max(0, len(feats) - len(top_feats))
            tail = []
            if rest:
                tail.append("ועוד %d תוספות" % rest)
            if fixes:
                tail.append("%d תיקונים" % len(fixes))
            if tail:
                groups.append({"title": "ובנוסף", "items": [" · ".join(tail)]})

        newest = newer[0]["v"]
        if jump == 1:
            headline = "מה השתנה בגרסה %s" % newest
        else:
            oldest = newer[-1]["v"]
            headline = "דילגת על %d גרסאות (%s → %s) — הנה העיקר" % (jump, oldest, newest)
        return {"ok": True, "jump": jump, "mode": mode, "headline": headline,
                "from": cur, "to": newest,
                "versions": [e["v"] for e in newer], "groups": groups,
                "counts": {"major": len(majors), "feature": len(feats), "fix": len(fixes)}}

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

    # ── התנגשויות (תצוגת legacy בדיאלוג הניק בלבד) ──────────────────
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

    def set_sync_settings(self, mapping):
        """שמירה מרוכזת: {field_key: bool} בקריאה אחת"""
        db.set_sync_settings({k: bool(v) for k, v in (mapping or {}).items()})
        return {"ok": True}

    def set_forum_io_flags(self, mapping):
        """שמירה מרוכזת: {forum_name: bool} בקריאה אחת"""
        db.set_forum_io_flags({k: bool(v) for k, v in (mapping or {}).items()})
        return {"ok": True}

    # section 2: אילו פורומים ייכללו בייבוא/ייצוא
    def get_forum_io_flags(self):
        return db.get_forum_io_flags()

    def set_forum_io_flag(self, forum_name, included):
        db.set_forum_io_flag(forum_name, bool(included))
        return {"ok": True}

    def get_setting(self, key, default=""):
        return db.get_setting(key, default)

    def set_setting(self, key, value):
        db.set_setting(key, value)
        return {"ok": True}

    # ── ייצוא / ייבוא ──────────────────────────────────────────────
    def get_export_counts(self):
        """כמה ניקים ייכללו בכל מצב ייצוא (הכל / עם מידע / עם מידע שלי)."""
        return db.count_export_modes()

    def export_csv(self, mode="all", ids=None):
        """ייצוא לאקסל: CSV עם BOM (עברית תקינה); מספרים עם 0 מוביל נשמרים כטקסט."""
        import csv
        try:
            from webview import FileDialog
            save_dialog = FileDialog.SAVE
        except ImportError:
            save_dialog = webview.SAVE_DIALOG
        if mode not in ("all", "has_info", "my_info", "selected"):
            mode = "all"
        result = webview.windows[0].create_file_dialog(
            save_dialog, save_filename="tiknick_export.csv",
            file_types=("CSV לאקסל (*.csv)", "All files (*.*)"))
        if not result:
            return {"ok": False, "error": "בוטל"}
        dest = result[0] if isinstance(result, (list, tuple)) else result
        if not dest:
            return {"ok": False, "error": "בוטל"}
        try:
            data = db.export_data("all" if mode == "selected" else mode,
                                  ids if mode == "selected" else None)
            labels = {k: lbl for k, lbl, _ in db.ALL_NICK_FIELDS}
            fields = [f for f in data["exported_fields"] if f != "avatar_image"]

            def cell(v):
                s = "" if v is None else str(v)
                # אקסל מוחק 0 מוביל ממספרים — נוסחת טקסט שומרת אותו (עובד גם ב-Google Sheets)
                if s.isdigit() and s.startswith("0") and len(s) >= 6:
                    return f'="{s}"'
                # ערכים מהפורום אינם בטוחים: תא שמתחיל ב-= + - @ מורץ כנוסחה באקסל
                if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
                    return "'" + s
                return s
            with open(dest, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow([labels.get(k, k) for k in fields])
                for r in data["nicks"]:
                    w.writerow([cell(r.get(k, "")) for k in fields])
            return {"ok": True, "path": dest, "count": len(data["nicks"])}
        except Exception as e:
            logging.exception("export_csv failed")
            return {"ok": False, "error": str(e)}

    def export_data(self, mode="all", ids=None):
        try:
            from webview import FileDialog
            save_dialog = FileDialog.SAVE
        except ImportError:
            save_dialog = webview.SAVE_DIALOG  # older pywebview

        if mode not in ("all", "has_info", "my_info", "selected"):
            mode = "all"
        suffix = {"all": "", "has_info": "_מידע", "my_info": "_שלי", "selected": "_נבחרים"}[mode]

        result = webview.windows[0].create_file_dialog(
            save_dialog,
            directory=_HERE,
            save_filename=f"tiknick_export{suffix}.tiknick",
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

        data = db.export_data("all" if mode == "selected" else mode,
                              ids if mode == "selected" else None)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        counts = data.get("counts") or {}
        return {"ok": True, "path": dest, "count": len(data["nicks"]),
                "contacts": counts.get("contacts", 0),
                "identity_groups": counts.get("identity_groups", 0)}

    def load_import_file(self):
        """שלב 1: פתח קובץ ובדוק פורומים לא מוכרים"""
        try:
            from webview import FileDialog
            open_dialog = FileDialog.OPEN
        except ImportError:
            open_dialog = webview.OPEN_DIALOG

        result = webview.windows[0].create_file_dialog(
            open_dialog,
            file_types=("קובץ Tik-Nick (*.tiknick;*.json)", "טבלה (*.csv;*.tsv;*.txt)",
                        "All files (*.*)")
        )
        if not result:
            return {"ok": False, "error": "בוטל"}
        path = result[0] if isinstance(result, (list, tuple)) else result
        if not path:
            return {"ok": False, "error": "בוטל"}
        if os.path.splitext(path)[1].lower() in (".csv", ".tsv", ".txt"):
            return self._load_csv_file(path)
        try:
            # utf-8-sig: קובץ שנשמר מעורך שמוסיף BOM נכשל אחרת עם שגיאת
            # מפענח באנגלית שלא אומרת למשתמש כלום. ל-UTF-8 רגיל זה זהה.
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            unknown = db.get_unknown_forums_in_data(data)
            # שמור data זמנית בזיכרון לשלב 2
            self._pending_import = {"data": data, "path": path}
            groups = data.get("identity_groups") or []
            contacts = sum(len(n.get("contacts") or [])
                           for n in data.get("nicks", []) if isinstance(n, dict))
            try:
                fver = int(data.get("version", 2))
            except (TypeError, ValueError):
                fver = 2
            return {"ok": True, "unknown_forums": unknown,
                    "nick_count": len(data.get("nicks", [])),
                    "file_version": fver,
                    "newer_format": fver > db.EXPORT_FORMAT_VERSION,
                    "contacts": contacts,
                    "identity_groups": len(groups) if isinstance(groups, list) else 0}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _load_csv_file(self, path):
        """
        שלב 1 לקובץ טבלה: מפענח, מנחש מפריד, ומציע מיפוי עמודות. עדיין לא נכתב
        דבר — המשתמש מאשר את המיפוי, ומשם ממשיכים באותה זרימה של .tiknick.
        """
        try:
            parsed = csv_import.parse_file(path)
        except Exception as e:
            logging.exception("csv parse failed")
            return {"ok": False, "error": str(e)}
        self._pending_csv = {"parsed": parsed, "path": path}
        return {"ok": True, "kind": "csv", "path": os.path.basename(path),
                "encoding": parsed["encoding"], "delimiter": parsed["delimiter"],
                "headers": parsed["headers"], "sample": parsed["sample"],
                "mapping": parsed["mapping"], "row_count": parsed["row_count"],
                "fields": csv_import.mappable_fields(),
                "forums": [f["name"] for f in db.get_forums()]}

    def confirm_csv_mapping(self, mapping=None, default_forum="כללי", fix_phone=True):
        """שלב 1.5 לקובץ טבלה: הופך את השורות למבנה של .tiknick וממשיך רגיל."""
        pending = getattr(self, "_pending_csv", None)
        if not pending:
            return {"ok": False, "error": "אין קובץ ממתין"}
        parsed = pending["parsed"]
        try:
            data = csv_import.normalize_rows(
                parsed["headers"], parsed["rows"], mapping or parsed["mapping"],
                default_forum=default_forum or "כללי", fix_phone=bool(fix_phone))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logging.exception("csv normalize failed")
            return {"ok": False, "error": str(e)}
        self._pending_csv = None
        self._pending_import = {"data": data, "path": pending["path"]}
        return {"ok": True, "unknown_forums": db.get_unknown_forums_in_data(data),
                "nick_count": len(data["nicks"]),
                "skipped_no_username": data["skipped_no_username"],
                "merged_dupes": data["merged_dupes"],
                "contacts": 0, "identity_groups": 0,
                "file_version": 2, "newer_format": False}

    def import_data(self):
        """לא בשימוש ישיר — השתמש ב-load_import_file + confirm_import"""
        pass

    def preview_import(self, forum_mapping=None, include_contacts=True,
                       include_identities=True):
        """מעבר קריאה-בלבד לפני הייבוא — רץ ב-thread כמו הייבוא עצמו."""
        pending = getattr(self, "_pending_import", None)
        if not pending:
            return {"ok": False, "error": "אין קובץ ממתין"}
        if _import_state["running"]:
            return {"ok": False, "error": "ייבוא כבר רץ"}
        data = pending["data"]
        total = len(data.get("nicks", []))
        _import_state.update({"running": True, "done": False, "error": None,
                              "processed": 0, "total": total, "result": None,
                              "preview": True})

        def _run():
            try:
                _import_state["result"] = db.preview_import(
                    data, forum_mapping or {}, bool(include_contacts),
                    bool(include_identities),
                    progress_cb=lambda n: _import_state.update({"processed": n}))
            except Exception as e:
                logging.exception("preview_import failed")
                _import_state["error"] = str(e)
            finally:
                _import_state["processed"] = total
                _import_state["running"] = False
                _import_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "started": True, "total": total}

    def confirm_import(self, forum_mapping=None, import_name=None,
                       import_notes="", import_trust=None,
                       include_contacts=True, include_identities=True):
        """שלב 2: בצע ייבוא עם מיפוי פורומים ודרגת אמינות"""
        pending = getattr(self, '_pending_import', None)
        if not pending:
            return {"ok": False, "error": "אין קובץ ממתין"}
        if _import_state["running"]:
            return {"ok": False, "error": "ייבוא כבר רץ"}
        data     = pending["data"]
        path     = pending["path"]
        mapping  = forum_mapping or {}
        name     = import_name or os.path.basename(path)
        manual   = db.get_setting("import_manual_conflicts", "0") == "1"
        total    = len(data.get("nicks", []))
        self._pending_import = None
        _import_state.update({"running": True, "done": False, "error": None,
                              "processed": 0, "total": total, "result": None})

        def _progress(n):
            _import_state["processed"] = n

        def _run():
            try:
                result = db.import_data(
                    data, os.path.basename(path), mapping,
                    import_name=name, import_notes=import_notes, import_trust=import_trust,
                    manual_conflicts=manual, progress_cb=_progress,
                    include_contacts=include_contacts, include_identities=include_identities)
                # db.import_data מחזיר תמיד dict מ-0.8.7
                _import_state["result"] = {
                    "imported": result["imported"],
                    "conflicts": result["conflicts"] if manual else result["recorded"],
                    "manual": bool(manual),
                    "contacts": result.get("contacts", 0),
                    "identities": result.get("identities", 0),
                    "identities_skipped": result.get("identities_skipped", 0)}
            except Exception as e:
                logging.exception("import failed")
                _import_state["error"] = str(e)
            finally:
                _import_state["processed"] = total
                _import_state["running"] = False
                _import_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "started": True, "total": total}

    def get_import_progress(self):
        return dict(_import_state)

    def apply_import_conflicts(self, items, accept):
        """'החל על כל השאר' — כל ההחלטות בקריאת גשר אחת"""
        try:
            return {"ok": True, "count": db.apply_import_conflicts(items or [], bool(accept))}
        except Exception as e:
            logging.exception("apply_import_conflicts failed")
            return {"ok": False, "error": str(e)}

    # ── גיבוי ושחזור מלאים ─────────────────────────────────────────
    def backup_db(self):
        """שומר עותק מלא של ה-DB (כל הטבלאות, כולל עוגיות והגדרות) לקובץ לבחירת המשתמש."""
        try:
            from webview import FileDialog
            save_dialog = FileDialog.SAVE
        except ImportError:
            save_dialog = webview.SAVE_DIALOG
        import datetime as _dt
        default = f"tiknick_backup_{_dt.datetime.now():%Y-%m-%d_%H-%M}.db"
        result = webview.windows[0].create_file_dialog(
            save_dialog, save_filename=default,
            file_types=("Tik-Nick backup (*.db)", "All files (*.*)"))
        if not result:
            return {"ok": False, "error": "בוטל"}
        dest = result[0] if isinstance(result, (list, tuple)) else result
        if not dest:
            return {"ok": False, "error": "בוטל"}
        try:
            n = db.backup_to(dest)
            return {"ok": True, "path": dest, "nicks": n}
        except Exception as e:
            logging.exception("backup_db failed")
            return {"ok": False, "error": str(e)}

    def restore_db(self):
        """מחליף את המאגר כולו בגיבוי שנבחר (אחרי אימות ועותק בטיחות של הנוכחי)."""
        if (_scrape_state["running"] or _import_state["running"] or _source_state["running"]
                or _chz_state["running"] or _stink_state["running"]):
            return {"ok": False, "error": "יש פעולה שרצה ברקע — המתן לסיומה לפני שחזור"}
        # ה-hold עוטף גם את דיאלוג הקובץ: אם המשתמש מבטל אותו, hold שנשאר דלוק
        # משתיק את התזמון עד סוף הריצה בלי שום סימן.
        _sched_hold.set()
        try:
            try:
                from webview import FileDialog
                open_dialog = FileDialog.OPEN
            except ImportError:
                open_dialog = webview.OPEN_DIALOG
            result = webview.windows[0].create_file_dialog(
                open_dialog, file_types=("Tik-Nick backup (*.db)", "All files (*.*)"))
            if not result:
                return {"ok": False, "error": "בוטל"}
            path = result[0] if isinstance(result, (list, tuple)) else result
            if not path:
                return {"ok": False, "error": "בוטל"}
            try:
                info = db.restore_from(path)
                logging.info("DB restored from %s (safety copy: %s)", path, info["safety_backup"])
                return {"ok": True, **info}
            except Exception as e:
                logging.exception("restore_db failed")
                return {"ok": False, "error": str(e)}
        finally:
            _sched_hold.clear()

    def apply_import_conflict(self, nick_id, field, value, source_id, accept):
        db.apply_import_conflict(nick_id, field, value, source_id, bool(accept))
        return {"ok": True}

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

    def _run_source_op(self, op, fn):
        """מריץ פעולת מקור ב-thread רקע עם מעקב התקדמות (get_source_progress)."""
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        _source_state.update({"running": True, "done": False, "error": None,
                              "processed": 0, "total": 0, "op": op})

        def _progress(done, total):
            _source_state["processed"] = done
            _source_state["total"] = total

        def _run():
            try:
                fn(_progress)
            except Exception as e:
                logging.exception("source op %s failed", op)
                _source_state["error"] = str(e)
            finally:
                _source_state["processed"] = _source_state["total"]
                _source_state["running"] = False
                _source_state["done"] = True

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "started": True}

    def update_source(self, source_id, name=None, notes=None, trust=None, absolute=None):
        sid = int(source_id)
        return self._run_source_op("update", lambda cb: db.update_source(
            sid, name=name, notes=notes, trust=trust, absolute=absolute, progress_cb=cb))

    def delete_source(self, source_id):
        sid = int(source_id)
        if sid == 1:
            return {"ok": False, "error": "לא מוחקים את המקור 'אני'"}
        return self._run_source_op("delete", lambda cb: db.delete_source(sid, progress_cb=cb))

    def get_source_progress(self):
        return dict(_source_state)

    def pick_field_value(self, nick_id, field_name, value):
        try:
            return db.pick_field_value(int(nick_id), field_name, value)
        except Exception as e:
            logging.exception("pick_field_value failed")
            return {"ok": False, "error": str(e)}

    def get_shelved_for_nick(self, nick_id):
        try:
            return db.get_shelved_values(int(nick_id))
        except Exception:
            logging.exception("get_shelved_for_nick failed")
            return []

    def promote_shelved_value(self, shelved_id):
        try:
            return {"ok": bool(db.promote_shelved(int(shelved_id)))}
        except Exception as e:
            logging.exception("promote_shelved_value failed")
            return {"ok": False, "error": str(e)}

    def get_import_log(self, limit=50):
        try:
            return db.get_import_sources()[:int(limit)]
        except Exception:
            logging.exception("get_import_log failed")
            return []

    def get_field_sources(self, nick_id, field_name):
        return db.get_field_sources(int(nick_id), field_name)

    # ── תיוג ניקים בטקסט חופשי (@username) ─────────────────────────
    # ── רשת ופרוקסי ────────────────────────────────────────────────
    def get_net_settings(self):
        """מה חל *עכשיו* על היציאה לאינטרנט — לא רק מה ששמור במאגר."""
        return dict(net.current(), forums=self._net_test_targets())

    def _net_test_targets(self):
        """כתובות אמיתיות לבדיקה — הפורומים שהמשתמש עצמו הגדיר."""
        out = []
        for f in db.get_forums():
            url = (f.get("url") or "").strip()
            if url:
                out.append({"name": f["name"], "url": url})
        return out[:12]

    def set_net_settings(self, mode="system", url=""):
        """מחיל ושומר. הגדרה פסולה נדחית — הקיימת ממשיכה לעבוד."""
        try:
            state = net.apply(mode, url)
        except net.ProxyError as e:
            return {"ok": False, "error": str(e)}
        db.set_setting(net.SETTING_MODE, state["mode"])
        db.set_setting(net.SETTING_URL, state["url"])
        logging.info("Network: %s", state["description"])
        return dict(state, ok=True)

    def test_net_settings(self, mode="system", url="", target=""):
        """בודק בלי להחיל, כדי שסריקה שרצה ברקע לא תיפגע מכתובת שגויה."""
        if not target:
            t = self._net_test_targets()
            target = t[0]["url"] if t else ""
        return net.test_connection(mode, url, target)

    def count_encoded_names(self):
        """כמה ערכים נשמרו מקודדים ל-HTML — לתצוגה לפני שמציעים לתקן."""
        return db.count_encoded_values()

    def fix_encoded_names(self):
        """מפענח אותם. פעולה על נתונים — ולכן גיבוי לפניה, כמו כל פעולה כזו."""
        busy = self._busy()
        if busy:
            return {"ok": False, "error": busy}
        bk = db.auto_backup("fix-encoded")
        r = db.fix_encoded_values()
        return dict(r, ok=True, backed_up=bool(bk and bk.get("ok")))

    def resolve_tag(self, username):
        """מאתר ניק לפי שם משתמש מדויק (ללא תלות בפורום) — ללחיצה על תיוג"""
        return db.find_nick_by_username(username)

    def search_usernames(self, prefix, limit=8):
        """חיפוש שמות משתמש להשלמה אוטומטית בעת תיוג"""
        return db.search_usernames(prefix, int(limit))

    # ── תצוגת משתמש מאוחדת (איחוד זהויות) ──────────────────────────
    def lookup_nicks(self, query, limit=12):
        """חיפוש ניקים לתצוגת המשתמש המאוחדת (לפי שם משתמש/שם אמיתי)"""
        return db.search_nicks_for_lookup(query, int(limit))

    def get_merged_profile(self, nick_id):
        """מחזיר תצוגה מאוחדת של ניק וכל הזהויות המקושרות אליו"""
        return db.get_merged_profile(int(nick_id))

    # ── עוגיות התחברות שמורות (לפי דומיין) ─────────────────────────
    def get_saved_cookie(self, url):
        return db.get_cookie_for_url(url or "")

    def save_cookie(self, url, cookie):
        db.save_cookie_for_url(url or "", cookie or "")
        return {"ok": True}

    # ── חיפוש/סינון/פעולות מרובות מתקדם ────────────────────────────
    def get_filterable_fields(self):
        return [{"key": k, "label": l} for k, l in db.FILTERABLE_FIELDS]

    def filter_nicks(self, field, op="contains", value=""):
        return db.filter_nicks(field, op, value)

    def filter_nicks_multi(self, conditions):
        return db.filter_nicks_multi(conditions or [])

    def bulk_update_field(self, nick_ids, field, value):
        try:
            n = db.bulk_update_field(nick_ids or [], field, value)
            return {"ok": True, "count": n}
        except Exception as e:
            logging.exception("bulk_update_field failed")
            return {"ok": False, "error": str(e)}


def _msgbox(text, title="Tik-Nick", icon=0x10):
    """הודעה למשתמש (בעברית) גם כשאין עדיין חלון — ה-EXE רץ בלי קונסולה."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, icon | 0x0)
    except Exception:
        pass

def _single_instance_or_exit():
    """מופע כפול של התוכנה = שני תהליכים על אותו DB (ומסך 'סורק' שמתבלבל) — מונעים."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\TikNick-single-instance")
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            _msgbox("Tik-Nick כבר פתוח.\n\nחפש את החלון הקיים בשורת המשימות.", icon=0x40)
            os._exit(0)
    except Exception:
        pass

if __name__ == "__main__":
    try:
        _single_instance_or_exit()
        # מסד הנתונים נשמר בתיקייה הניתנת לכתיבה (ליד ה-EXE)
        db.DB_PATH = os.path.join(_DATA_DIR, "tiknick.db")
        try:
            db.init_db()
            i18n.set_lang(db.get_setting("display_lang", "he"))
            # חייב לחול לפני הבקשה היוצאת הראשונה — התזמון ובדיקת
            # העדכון יוצאים לדרך שניות אחרי העלייה.
            _net = net.apply_from_settings(db.get_setting)
            if not _net.get("ok"):
                logging.warning("Saved network settings ignored: %s", _net.get("error"))
            logging.info("Network: %s", _net.get("description"))
        except Exception as e:
            logging.exception("init_db failed")
            _msgbox("לא ניתן לפתוח את מאגר הנתונים.\n\n"
                    f"קובץ: {db.DB_PATH}\nשגיאה: {e}\n\n"
                    "אם הקובץ פגום — שחזר מגיבוי (קובץ .db) או העבר אותו הצידה כדי להתחיל מחדש.")
            raise
        logging.info("Database ready at %s", db.DB_PATH)

        # גיבוי יומי — ב-thread, כי 88MB דרך ה-backup API לוקחים כמה שניות
        # והמשתמש לא אמור להמתין לחלון. כישלון נרשם ללוג ולא עוצר את ההפעלה.
        def _daily_backup():
            try:
                if db.get_setting("auto_backup_enabled", "1") == "0":
                    return
                r = db.auto_backup("daily")
                if r.get("ok") and r.get("path"):
                    logging.info("auto backup: %s (%d bytes)", r["path"], r.get("bytes", 0))
                elif not r.get("ok"):
                    logging.warning("auto backup failed: %s", r.get("error"))
            except Exception:
                logging.exception("auto backup crashed")
        threading.Thread(target=_daily_backup, daemon=True).start()

        api = API()

        # התזמון: כבוי כברירת מחדל, ומתעורר רק אחרי חסד ההפעלה. הוא לא סורק —
        # רק מחליט, ומעביר למסלול הסריקה הקיים עם ההשהיות והנימוס שלו.
        threading.Thread(target=_sched_loop, args=(api,), daemon=True).start()

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
        # סגירה נקייה: קיפול ה-WAL לקובץ הראשי
        window.events.closing += lambda: (db.checkpoint(), True)[1]
        webview.start(debug=False)   # ללא כלי מפתחים למשתמש הסופי
        logging.info("Tik-Nick closed normally")
    except Exception:
        logging.exception("Fatal error during startup")
        raise
