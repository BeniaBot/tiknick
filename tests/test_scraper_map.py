# -*- coding: utf-8 -*-
"""Scraper mapping + merge semantics fixed in 0.8.3 (zero values, un-ban, caps)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scraper, database as db

fails = []
def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond: fails.append(name)

# reputation / post_count 0 must survive (used to be dropped as "absent")
m = scraper._map_user({"username": "a", "reputation": 0, "postcount": 0})
ok("reputation 0 -> '0'", m["reputation"] == "0", m["reputation"])
ok("postcount 0 -> '0'", m["post_count"] == "0", m["post_count"])
m2 = scraper._map_user({"username": "a", "reputation": -12, "postcount": "77"})
ok("negative reputation kept", m2["reputation"] == "-12", m2["reputation"])
ok("string postcount parsed", m2["post_count"] == "77", m2["post_count"])
ok("missing reputation -> ''", scraper._map_user({"username": "a"})["reputation"] == "")

# extra_info capped
big = scraper._map_user({"username": "a", "signature": "x" * 5000, "aboutme": "y" * 5000})
ok("extra_info capped <= 2000", len(big["extra_info"]) <= 2000, str(len(big["extra_info"])))

# un-ban propagates through merge
tmp = tempfile.mkdtemp(prefix="tiknick_map_")
db.DB_PATH = os.path.join(tmp, "t.db"); db.init_db()
db.add_forum("פ", "#111", "https://x.example")
db.merge_scraped_users("פ", [("u1", scraper._map_user({"username": "u1", "banned": 1}))], "t")
ok("banned -> מורחק", db.find_nick("פ", "u1")["status"] == "מורחק")
st = db.merge_scraped_users("פ", [("u1", scraper._map_user({"username": "u1", "banned": 0}))], "t")
ok("un-ban -> פעיל", db.find_nick("פ", "u1")["status"] == "פעיל", db.find_nick("פ", "u1")["status"])
ok("un-ban counted as update", st["updated"] == 1, str(st))

# a manual status on a never-banned nick is NOT overridden by an empty scraped status
db.merge_scraped_users("פ", [("u2", scraper._map_user({"username": "u2"}))], "t")
nid = db.find_nick("פ", "u2")["id"]
db.record_field_value(nid, "status", "מושעה", 1)
db.merge_scraped_users("פ", [("u2", scraper._map_user({"username": "u2"}))], "t")
ok("manual status survives rescan", db.get_nick(nid)["status"] == "מושעה", db.get_nick(nid)["status"])

# reputation drop to 0 propagates
db.merge_scraped_users("פ", [("u3", scraper._map_user({"username": "u3", "reputation": 50}))], "t")
db.merge_scraped_users("פ", [("u3", scraper._map_user({"username": "u3", "reputation": 0}))], "t")
ok("reputation drop to 0 propagates", str(db.find_nick("פ", "u3")["reputation"]) == "0",
   str(db.find_nick("פ", "u3")["reputation"]))

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("SCRAPER MAP TESTS PASSED")
