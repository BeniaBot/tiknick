# -*- coding: utf-8 -*-
"""0.8.4: full DB backup/restore, batched settings/conflict APIs, import progress callback."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
import database as db

tmp = tempfile.mkdtemp(prefix="tiknick_bb_")
db.DB_PATH = os.path.join(tmp, "main.db")
db.init_db()
fails = []
def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond: fails.append(name)

db.add_forum("פורום א", "#111", "https://a.example")

# ── batched settings ──
db.set_sync_settings({"phone": False, "email": True, "private_notes": True})
ss = db.get_sync_settings()
ok("set_sync_settings phone off", ss["phone"] is False)
ok("set_sync_settings private_notes on", ss["private_notes"] is True)
db.set_forum_io_flags({"פורום א": False})
ok("set_forum_io_flags excludes", db.get_forum_io_flags()["פורום א"] is False)
db.set_forum_io_flags({"פורום א": True})
ok("set_forum_io_flags re-includes", db.get_forum_io_flags()["פורום א"] is True)

# ── apply_import_conflicts ──
nid = db.create_nick({"forum": "פורום א", "username": "u1", "real_name": "אלף"})
sid = db.create_import_source("קובץ", "", 6)
items = [{"nick_id": nid, "field": "real_name", "new_value": "בית", "source_id": sid},
         {"nick_id": nid, "field": "phone", "new_value": "050", "source_id": sid},
         {"nick_id": nid, "field": "username", "new_value": "hack", "source_id": sid}]  # non-sourced: ignored
ok("reject keeps existing", db.apply_import_conflicts(items, False) == 0 and db.get_nick(nid)["real_name"] == "אלף")
n = db.apply_import_conflicts(items, True)
ok("accept applies 2 (username skipped)", n == 2, str(n))
ok("accepted value shown", db.get_nick(nid)["real_name"] == "בית", db.get_nick(nid)["real_name"])
ok("accepted phone shown", db.get_nick(nid)["phone"] == "050")
ok("username untouched", db.get_nick(nid)["username"] == "u1")

# ── import progress callback ──
calls = []
imp = {"version": 2, "exported_fields": ["forum", "username", "real_name"],
       "nicks": [{"forum": "פורום א", "username": f"imp{i}", "real_name": f"שם {i}"} for i in range(60)]}
db.import_data(imp, "x", {}, import_name="x", import_trust=5, progress_cb=lambda n: calls.append(n))
ok("progress_cb called at 25 and 50", calls == [25, 50], str(calls))

# ── backup / restore ──
before = db.get_all_nicks("")["total"]
bak = os.path.join(tmp, "backup.db")
n_bak = db.backup_to(bak)
ok("backup_to returns nick count", n_bak == before, f"{n_bak} vs {before}")
ok("backup file exists", os.path.getsize(bak) > 0)
ok("validate_backup ok", db.validate_backup(bak) == before)
bad = os.path.join(tmp, "bad.db"); open(bad, "wb").write(b"not a database at all")
try:
    db.validate_backup(bad); ok("validate rejects garbage", False)
except Exception:
    ok("validate rejects garbage", True)
db.create_nick({"forum": "פורום א", "username": "after_backup"})
ok("nick added after backup", db.get_all_nicks("")["total"] == before + 1)
info = db.restore_from(bak)
ok("restore returns nick count", info["nicks"] == before, str(info))
ok("restore reverted the extra nick", db.get_all_nicks("")["total"] == before,
   str(db.get_all_nicks("")["total"]))
ok("safety copy created", os.path.exists(info["safety_backup"]))
ok("restored DB still searchable (FTS rebuilt)", db.get_all_nicks("imp1")["total"] >= 1)
ok("restored DB usable for writes", db.create_nick({"forum": "פורום א", "username": "post_restore"}) > 0)

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("BACKUP/BATCH TESTS PASSED")
shutil.rmtree(tmp, ignore_errors=True)
