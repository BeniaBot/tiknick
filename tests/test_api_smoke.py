# -*- coding: utf-8 -*-
"""Smoke test: import main (full API surface loads) and exercise new API methods."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main   # runs top-level (DPI/logging/imports) — must not raise
sys.excepthook = sys.__excepthook__   # main.py routes tracebacks to a log; restore printing
import database as db

tmp = tempfile.mkdtemp(prefix="tiknick_api_")
db.DB_PATH = os.path.join(tmp, "t.db")
db.init_db()
main.db.DB_PATH = db.DB_PATH   # main holds its own ref

api = main.API()
fails = []
def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond: fails.append(name)

v = api.get_app_version()
ok("get_app_version has install_type", v.get("install_type") in ("portable", "installer"), str(v))

api.add_forum("פורום ימות המשיח", "#16a085", "https://f2.freeivr.co.il/")
ok("get_saved_cookie empty", api.get_saved_cookie("https://f2.freeivr.co.il") == "")
api.save_cookie("https://f2.freeivr.co.il/x", "express.sid=zzz")
ok("save/get cookie roundtrip", api.get_saved_cookie("https://f2.freeivr.co.il") == "express.sid=zzz")

r = api.create_nick({"forum": "פורום ימות המשיח", "username": "tester", "real_name": "בודק"})
nid = r["id"]
ok("create_nick ok", r.get("ok"))
ok("lookup_nicks finds", any(x["id"] == nid for x in api.lookup_nicks("tester")))
prof = api.get_merged_profile(nid)
ok("merged profile members", prof and len(prof["members"]) == 1)

counts = api.get_export_counts()
ok("export counts keys", set(counts) == {"all", "has_info", "my_info"}, str(counts))

kf = api.get_known_forums()
plats = {f["name"]: f.get("platform", "nodebb") for f in kf}
ok("known has ימות המשיח nodebb", plats.get("פורום ימות המשיח") == "nodebb")
ok("known has לתורה xenforo", plats.get("פורום לתורה") == "xenforo", str(plats.get("פורום לתורה")))
ok("known count >= 24", len(kf) >= 24, str(len(kf)))

# check_forum returns a platform field even on failure (no network here → unknown/err)
cf = api.check_forum("https://definitely-not-a-forum.invalid")
ok("check_forum has platform key", "platform" in cf, str(cf))

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("API SMOKE OK")
