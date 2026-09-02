# -*- coding: utf-8 -*-
"""0.8.4: recycle bin (snapshot + restore), contacts/phone-normalized search, partial export, health."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
import database as db

tmp = tempfile.mkdtemp(prefix="tiknick_ts_")
db.DB_PATH = os.path.join(tmp, "t.db")
db.init_db()
fails = []
def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond: fails.append(name)

db.add_forum("פורום א", "#111", "https://a.example")
db.add_forum("פורום ב", "#222", "https://b.example")

# ── search: contacts + phone normalization ──
n1 = db.create_nick({"forum": "פורום א", "username": "moshe", "phone": "050-123-4567"})
n2 = db.create_nick({"forum": "פורום ב", "username": "dovid"})
db.add_contact(n2, "email", "dovid@example.com", "עבודה", 0)
db.add_contact(n2, "phone", "+972 52 999 8888", "נייד", 0)
ok("digits-only finds hyphenated phone", n1 in {r["id"] for r in db.get_all_nicks("0501234567")["rows"]})
ok("972 prefix finds local phone", n1 in {r["id"] for r in db.get_all_nicks("972501234567")["rows"]})
ok("search finds extra email (contacts)", n2 in {r["id"] for r in db.get_all_nicks("dovid@example")["rows"]})
ok("search finds extra phone normalized", n2 in {r["id"] for r in db.get_all_nicks("0529998888")["rows"]})
ok("lookup finds by contact", any(r["id"] == n2 for r in db.search_nicks_for_lookup("0529998888")))
ok("plain username search still works", n1 in {r["id"] for r in db.get_all_nicks("moshe")["rows"]})

# ── partial export by ids ──
exp = db.export_data("all", ids=[n1])
ok("export ids filters to one", [r["username"] for r in exp["nicks"]] == ["moshe"], str([r["username"] for r in exp["nicks"]]))

# ── trash: snapshot + restore everything ──
db.add_identity(n1, n2)
scrape_sid = db.get_scrape_source()["id"]
db.record_field_value(n2, "full_name", "דוד לוי", scrape_sid)
before_total = db.get_all_nicks("")["total"]
r = db.delete_nicks([n2])
ok("delete returns batch", r["deleted"] == 1 and r["batch_id"])
ok("nick gone", db.get_nick(n2) is None)
ok("trash lists one batch", len(db.list_trash()) == 1 and db.list_trash()[0]["count"] == 1)
ok("identity link gone with nick", db.get_identities(n1) == [])
res = db.restore_trash(batch_id=r["batch_id"])
ok("restore ok", res["restored"] == 1 and res["skipped"] == 0, str(res))
back = db.get_nick(n2)
ok("nick restored with same id", back is not None and back["id"] == n2)
ok("contacts restored", len(db.get_contacts(n2)) == 2, str(len(db.get_contacts(n2))))
ok("identity restored", any(i["id"] == n2 for i in db.get_identities(n1)))
ok("field_values restored", any(s["value"] == "דוד לוי" for s in db.get_field_sources(n2, "full_name")))
ok("trash empty after restore", db.list_trash() == [])
ok("total back to before", db.get_all_nicks("")["total"] == before_total)
ok("restored nick searchable (FTS trigger)", n2 in {x["id"] for x in db.get_all_nicks("dovid")["rows"]})

# restore skips if same forum+username was re-created meanwhile
r2 = db.delete_nicks([n1])
db.create_nick({"forum": "פורום א", "username": "moshe"})
res2 = db.restore_trash(batch_id=r2["batch_id"])
ok("restore skips re-created nick", res2["restored"] == 0 and res2["skipped"] == 1, str(res2))

# bulk delete of many (chunking) + empty_trash
ids = [db.create_nick({"forum": "פורום א", "username": f"bulk{i}"}) for i in range(900)]
rb = db.delete_nicks(ids)
ok("bulk delete 900", rb["deleted"] == 900)
ok("empty_trash removes all", db.empty_trash() >= 900 and db.list_trash() == [])

# ── health / vacuum / checkpoint ──
h = db.db_health()
ok("health quick_check ok", h["quick_check"] == "ok" and h["counts"]["nicks"] >= 1)
db.checkpoint()
ok("vacuum returns size", db.vacuum() > 0)

print()
if fails: print("FAILED:", fails); sys.exit(1)
print("TRASH/SEARCH TESTS PASSED")
shutil.rmtree(tmp, ignore_errors=True)
