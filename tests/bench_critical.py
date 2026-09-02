# -*- coding: utf-8 -*-
"""Benchmark the three paths the deep audit flagged as critical, at realistic scale."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
import database as db

N = 40000                     # nicks
tmp = tempfile.mkdtemp(prefix="tiknick_b2_")
db.DB_PATH = os.path.join(tmp, "b.db")
db.init_db()
FORUM = "פורום ימות המשיח"
db.add_forum(FORUM, "#16a085", "https://f2.freeivr.co.il/")

t0 = time.perf_counter()
scrape_sid = db.get_scrape_source()["id"]
FIELDS = ["full_name", "groups", "reputation", "status", "join_date", "post_count"]
with db.get_connection() as conn:
    conn.executemany(
        "INSERT INTO nicks (forum, username, source, trust_level) VALUES (?,?,'NodeBB',4)",
        [(FORUM, f"user{i}") for i in range(N)])
    ids = [r[0] for r in conn.execute("SELECT id FROM nicks").fetchall()]
    conn.executemany(
        "INSERT OR IGNORE INTO field_values (nick_id, field_name, value, source_id) VALUES (?,?,?,?)",
        [(nid, f, f"v{nid}", scrape_sid) for nid in ids for f in FIELDS])
    conn.execute("ANALYZE")
n_fv = db.get_connection().execute("SELECT COUNT(*) FROM field_values").fetchone()[0]
print(f"seed {time.perf_counter()-t0:.0f}s  nicks={N}  field_values={n_fv}  "
      f"size={os.path.getsize(db.DB_PATH)/1e6:.0f}MB")

def bench(label, fn):
    t = time.perf_counter(); out = fn(); el = time.perf_counter() - t
    print(f"  {label:<44} {el*1000:8.0f} ms   {out if out is not None else ''}")
    return el

print("\n── critical paths (audit-flagged) ──")

# 1. Re-scrape a page of 500 existing users with NO changes (the common case)
page = [(f"user{i}", {f: f"v{i+1}" for f in FIELDS}) for i in range(500)]
# values won't match (v{nid} vs v{i+1}) so this is a worst case: all 500 update
bench("merge_scraped_users: 500 users (changed)",
      lambda: db.merge_scraped_users(FORUM, page, "NodeBB:test"))
bench("merge_scraped_users: same 500 again (no-op)",
      lambda: db.merge_scraped_users(FORUM, page, "NodeBB:test"))

# 2. Import 2000 nicks (half new, half existing)
imp = {"version": 2, "exported_fields": ["forum", "username", "real_name", "phone", "notes"],
       "nicks": [{"forum": FORUM, "username": f"user{i}", "real_name": f"שם {i}",
                  "phone": f"05{i:08d}", "notes": "הערה"} for i in range(1000)]
              + [{"forum": FORUM, "username": f"new{i}", "real_name": f"חדש {i}",
                  "phone": f"05{i:08d}", "notes": "הערה"} for i in range(1000)]}
bench("import_data: 2000 nicks x 3 fields",
      lambda: db.import_data(imp, "bench", {}, import_name="bench", import_trust=6))

# 3. Trust slider on the scrape source (re-resolves every field it ever wrote)
bench("update_source: trust change on scrape source",
      lambda: db.update_source(scrape_sid, trust=8))

# 4. Select-all delete (SQLite variable limit)
all_ids = [r[0] for r in db.get_connection().execute("SELECT id FROM nicks").fetchall()]
bench(f"delete_nicks: all {len(all_ids)} (param limit)",
      lambda: db.delete_nicks(all_ids))
print()
