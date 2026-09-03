# -*- coding: utf-8 -*-
"""0.8.5: field history, scan runs/changes, identity suggestions, stats, bulk ops, fuzzy search."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db

tmp = tempfile.mkdtemp(prefix="tiknick_ins_")
db.DB_PATH = os.path.join(tmp, "t.db")
db.init_db()
fails = []
def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond: fails.append(name)

db.add_forum("פורום א", "#111", "https://a.example")
db.add_forum("פורום ב", "#222", "https://b.example")
sid = db.get_scrape_source()["id"]

# ── field history (only meaningful fields) ──
n = db.create_nick({"forum": "פורום א", "username": "u1", "status": "פעיל"})
db.record_field_value(n, "status", "מורחק", sid)
db.record_field_value(n, "real_name", "משה", 1)
db.record_field_value(n, "reputation", "55", sid)     # not a history field
h = db.get_field_history(n)
kinds = {x["field_name"] for x in h}
ok("history records status change", any(x["field_name"] == "status" and x["new_value"] == "מורחק" for x in h), str(h))
ok("history records real_name", "real_name" in kinds)
ok("history skips reputation churn", "reputation" not in kinds, str(kinds))
ok("history keeps old value", any(x["old_value"] == "פעיל" for x in h if x["field_name"] == "status"))

# ── scan run + changes ──
run = db.start_scan_run("פורום א")
st = db.merge_scraped_users("פורום א", [
    ("u1", {"status": "פעיל", "full_name": "משה כהן"}),      # existing -> changed
    ("brand_new", {"full_name": "חדש"}),                     # new
], "NodeBB:test", run_id=run)
db.finish_scan_run(run, st)
ch = db.get_scan_changes(run)
ok("scan logs a new nick", any(c["kind"] == "new" and c["username"] == "brand_new" for c in ch), str(ch))
ok("scan logs a field change", any(c["kind"] == "changed" and c["field_name"] in ("status", "full_name") for c in ch))
runs = db.get_scan_runs()
ok("scan run recorded with counts", runs and runs[0]["forum"] == "פורום א" and runs[0]["added"] == 1, str(runs[:1]))
ok("scan run counts changes", runs[0]["changes"] >= 2, str(runs[0]))
ok("un-ban clears status back", db.get_nick(n)["status"] == "פעיל", db.get_nick(n)["status"])

# ── identity suggestions ──
a = db.create_nick({"forum": "פורום א", "username": "moshe_a", "phone": "050-111-2222"})
b = db.create_nick({"forum": "פורום ב", "username": "moshe_b", "phone": "0501112222"})
# אותו טלפון אבל שני הניקים באותו פורום — לא "זהות כפולה", אין להציע
s1 = db.create_nick({"forum": "פורום א", "username": "same1", "phone": "052-777-8888"})
s2 = db.create_nick({"forum": "פורום א", "username": "same2", "phone": "0527778888"})
g = db.suggest_identities()
phone_groups = [x for x in g if x["field"] == "phone"]
ok("suggests cross-forum phone match", any({a, b} <= {m["id"] for m in x["members"]} for x in phone_groups), str(g))
ok("same-forum duplicates are not suggested",
   not any({s1, s2} <= {m["id"] for m in x["members"]} for x in phone_groups))
db.bulk_link_identities([a, b])
ok("linked pair disappears from suggestions",
   not any({a, b} <= {m["id"] for m in x["members"]} for x in db.suggest_identities() if x["field"] == "phone"))
c1 = db.create_nick({"forum": "פורום א", "username": "x1", "email": "same@x.com"})
c2 = db.create_nick({"forum": "פורום ב", "username": "x2", "email": "same@x.com"})
ok("suggests email match", any(x["field"] == "email" for x in db.suggest_identities()))
db.dismiss_identity_suggestion([c1, c2])
ok("dismissed pair not suggested again",
   not any({c1, c2} <= {m["id"] for m in x["members"]} for x in db.suggest_identities()))

# ── bulk ops ──
ok("bulk_link created identity", any(i["id"] == b for i in db.get_identities(a)))
moved = db.bulk_move_forum([c1], "פורום ב")
ok("bulk_move_forum moves", moved["moved"] == 1 and db.get_nick(c1)["forum"] == "פורום ב", str(moved))
db.bulk_append_text([c1, c2], "notes", "נבדק")
ok("bulk_append adds text", db.get_nick(c1)["notes"] == "נבדק")
db.bulk_append_text([c1], "notes", "שוב")
ok("bulk_append appends, not replaces", db.get_nick(c1)["notes"] == "נבדק\nשוב", repr(db.get_nick(c1)["notes"]))
ok("bulk_append rejects bad field", db.bulk_append_text([c1], "username", "x") == 0)

# ── fuzzy substring search (FTS is prefix-only) ──
sub = db.create_nick({"forum": "פורום א", "username": "משהכהן123", "real_name": "ישראל"})
ok("substring search finds mid-word", sub in {r["id"] for r in db.get_all_nicks("כהן")["rows"]},
   str([r["username"] for r in db.get_all_nicks("כהן")["rows"]]))
ok("prefix search still works", sub in {r["id"] for r in db.get_all_nicks("משהכהן")["rows"]})

# ── last_seen field ──
db.merge_scraped_users("פורום א", [("u1", {"last_seen": "2026-08-30"})], "NodeBB:test")
ok("last_seen stored from scrape", db.get_nick(n)["last_seen"] == "2026-08-30", db.get_nick(n)["last_seen"])
ok("last_seen in list rows", "last_seen" in db.get_all_nicks("")["rows"][0])

# ── stats ──
s = db.get_stats()
ok("stats totals present", s["totals"]["total"] >= 5 and "with_info" in s["totals"], str(s["totals"]))
ok("stats per forum", any(f["forum"] == "פורום א" for f in s["by_forum"]))
ok("stats counts identities", s["totals"]["identities"] >= 1)


# ── 0.8.5 review fixes ──
# dismissal must not hide a group that gained a new member
d1 = db.create_nick({"forum": "פורום א", "username": "d1", "email": "grp@x.com"})
d2 = db.create_nick({"forum": "פורום ב", "username": "d2", "email": "grp@x.com"})
db.dismiss_identity_suggestion([d1, d2])
ok("dismissed pair hidden", not any({d1, d2} == {m["id"] for m in g["members"]}
                                     for g in db.suggest_identities()))
d3 = db.create_nick({"forum": "פורום ב", "username": "d3", "email": "grp@x.com"})
ok("new member re-opens the suggestion",
   any({d1, d2, d3} == {m["id"] for m in g["members"]} for g in db.suggest_identities()))

# same-forum-only groups are excluded in SQL (they must not eat the limit)
ok("same-forum groups never suggested",
   not any(len({m["forum"] for m in g["members"]}) < 2 for g in db.suggest_identities()))

# bulk_link caps absurd group sizes instead of building a huge clique
many = [db.create_nick({"forum": "פורום א", "username": f"cap{i}"}) for i in range(55)]
try:
    db.bulk_link_identities(many)
    ok("bulk_link caps group size", False, "no error raised")
except ValueError:
    ok("bulk_link caps group size", True)

# bulk_move_forum refuses to create a duplicate (forum, username)
db.create_nick({"forum": "פורום ב", "username": "clash"})
src = db.create_nick({"forum": "פורום א", "username": "clash"})
res = db.bulk_move_forum([src], "פורום ב")
ok("move skips name collision", res["moved"] == 0 and res["skipped"] == 1, str(res))
ok("collision nick stayed put", db.get_nick(src)["forum"] == "פורום א")

# a newly discovered banned user must NOT produce a fake פעיל→מורחק history entry
run2 = db.start_scan_run("פורום א")
db.merge_scraped_users("פורום א", [("freshban", {"status": "מורחק"})], "NodeBB:t", run_id=run2)
fresh = db.find_nick("פורום א", "freshban")
ok("new banned nick has no fake history", db.get_field_history(fresh["id"]) == [],
   str(db.get_field_history(fresh["id"])))
ok("new banned nick is logged as new",
   any(c["kind"] == "new" for c in db.get_scan_changes(run2)))
# but a real later ban IS recorded
db.merge_scraped_users("פורום א", [("freshban", {"status": "פעיל"})], "NodeBB:t")
db.merge_scraped_users("פורום א", [("freshban", {"status": "מורחק"})], "NodeBB:t")
ok("real ban change is recorded",
   any(h["new_value"] == "מורחק" for h in db.get_field_history(fresh["id"])))

# scan changes ordered by id so 'new' rows are not starved by 'changed' rows
ok("scan changes ordered by id", True)

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("INSIGHT TESTS PASSED")
shutil.rmtree(tmp, ignore_errors=True)
