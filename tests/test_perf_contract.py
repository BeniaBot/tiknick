# -*- coding: utf-8 -*-
"""Contracts introduced by the 0.8.3 perf work: lean list payload + lazy avatars."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
import database as db

tmp = tempfile.mkdtemp(prefix="tiknick_perf_")
db.DB_PATH = os.path.join(tmp, "t.db")
db.init_db()

fails = []
def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond: fails.append(name)

db.add_forum("פורום א", "#111", "https://a.example")
AV = "data:image/jpeg;base64," + ("A" * 5000)
LONG = "חתימה ארוכה " * 100          # > 300 chars
id1 = db.create_nick({"forum": "פורום א", "username": "withpic",
                      "avatar_image": AV, "extra_info": LONG, "real_name": "משה"})
id2 = db.create_nick({"forum": "פורום א", "username": "nopic"})

rows = {r["username"]: r for r in db.get_all_nicks("")["rows"]}
ok("list omits avatar_image", "avatar_image" not in rows["withpic"], str(list(rows["withpic"])[:5]))
ok("list has has_avatar=1 for pic", rows["withpic"]["has_avatar"] == 1)
ok("list has has_avatar=0 for none", rows["nopic"]["has_avatar"] == 0)
ok("list truncates extra_info to 300", len(rows["withpic"]["extra_info"]) == 300,
   str(len(rows["withpic"]["extra_info"])))
ok("get_nick keeps FULL extra_info", len(db.get_nick(id1)["extra_info"]) == len(LONG))
ok("get_nick keeps avatar_image", db.get_nick(id1)["avatar_image"] == AV)

av = db.get_avatars([id1, id2])
ok("get_avatars returns pic for id1", av.get(str(id1)) == AV)
ok("get_avatars omits id without pic", str(id2) not in av, str(list(av)))
ok("get_avatars empty input safe", db.get_avatars([]) == {})

# filter path must expose the same shape
frows = db.filter_nicks_multi([{"field": "forum", "op": "contains", "value": "א"}])
ok("filter omits avatar_image", frows and "avatar_image" not in frows[0])
ok("filter has has_avatar", frows and "has_avatar" in frows[0])

# counts must agree with the actual exports after the SQL rewrite
counts = db.count_export_modes()
ok("count all == export all", counts["all"] == len(db.export_data("all")["nicks"]), str(counts))
ok("count has_info == export has_info",
   counts["has_info"] == len(db.export_data("has_info")["nicks"]), str(counts))
ok("count my_info == export my_info",
   counts["my_info"] == len(db.export_data("my_info")["nicks"]), str(counts))

# excluded forum must drop out of both count and export
db.add_forum("פורום ב", "#222", "https://b.example")
db.create_nick({"forum": "פורום ב", "username": "excluded_one", "real_name": "דוד"})
before = db.count_export_modes()["all"]
db.set_forum_io_flag("פורום ב", False)
after = db.count_export_modes()["all"]
ok("excluding a forum lowers the count", after == before - 1, f"{before}->{after}")
ok("excluded forum absent from export",
   "excluded_one" not in {n["username"] for n in db.export_data("all")["nicks"]})

# thread-local connection must survive a DB_PATH switch (tests/app startup rely on it)
other = os.path.join(tmp, "other.db")
old_path = db.DB_PATH
db.DB_PATH = other
db.init_db()
ok("switching DB_PATH uses the new DB", db.get_all_nicks("")["total"] == 0)
db.DB_PATH = old_path
ok("switching back sees original data", db.get_all_nicks("")["total"] >= 2)

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("PERF CONTRACT TESTS PASSED")
shutil.rmtree(tmp, ignore_errors=True)
