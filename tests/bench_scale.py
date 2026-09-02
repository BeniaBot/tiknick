# -*- coding: utf-8 -*-
"""Realistic-scale benchmark for Tik-Nick: build a big DB and time the hot paths."""
import os, sys, time, json, base64, tempfile, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # קונסולה בעברית/CP1255 לא תפיל הדפסות
import database as db

N = int(os.environ.get("BENCH_N", "20000"))
tmp = tempfile.mkdtemp(prefix="tiknick_bench_")
db.DB_PATH = os.path.join(tmp, "bench.db")
print(f"DB: {db.DB_PATH}  N={N}")
db.init_db()

FORUMS = ["מתמחים טופ", "פורום ימות המשיח", "פורום נטפרי", "חרדים נעייס", "פורום תחומים"]
for i, f in enumerate(FORUMS):
    db.add_forum(f, "#%06x" % (0x3366aa + i * 0x112233 % 0xffffff), f"https://f{i}.example")

random.seed(7)
# fake avatar ~24KB base64 data URL (what an uploaded avatar looks like)
AVATAR = "data:image/jpeg;base64," + base64.b64encode(os.urandom(18000)).decode()

t0 = time.perf_counter()
scrape_sid = db.get_scrape_source()["id"]
with db.get_connection() as conn:
    conn.execute("BEGIN")
    rows = []
    for i in range(N):
        forum = FORUMS[i % len(FORUMS)]
        rows.append((forum, f"user{i}", "חברים", str(i % 500),
                     f"שם מלא {i}", "פעיל", "2024-05-01", str(i % 3000),
                     f"מיקום: עיר {i%40}", str(i), "NodeBB", 4,
                     AVATAR if i % 50 == 0 else ""))
    conn.executemany(
        "INSERT INTO nicks (forum, username, groups, reputation, full_name, status,"
        " join_date, post_count, extra_info, forum_uid, source, trust_level, avatar_image)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    # field_values: 6 scraped fields per nick + a manual value for 10%
    ids = [r[0] for r in conn.execute("SELECT id FROM nicks").fetchall()]
    fv = []
    for nid in ids:
        for fld in ("full_name", "groups", "reputation", "status", "join_date", "post_count"):
            fv.append((nid, fld, f"v{nid}", scrape_sid))
    conn.executemany("INSERT OR IGNORE INTO field_values (nick_id, field_name, value, source_id)"
                     " VALUES (?,?,?,?)", fv)
    # 10% also have a conflicting manual value -> makes the GROUP_CONCAT subquery do work
    conn.executemany("INSERT OR IGNORE INTO field_values (nick_id, field_name, value, source_id)"
                     " VALUES (?,?,?,1)",
                     [(nid, "full_name", f"ידני{nid}") for nid in ids[::10]])
    # contacts + identities for a slice
    conn.executemany("INSERT INTO nick_contacts (nick_id, type, value, label) VALUES (?,?,?,?)",
                     [(nid, "phone", "0500000000", "נייד") for nid in ids[::20]])
    conn.executemany("INSERT OR IGNORE INTO nick_identities (nick_id_a, nick_id_b) VALUES (?,?)",
                     [(ids[i], ids[i + 1]) for i in range(0, min(len(ids) - 1, 2000), 2)])
    conn.execute("INSERT INTO nicks_fts(nicks_fts) VALUES('rebuild')")
print(f"seed: {time.perf_counter()-t0:.1f}s   size={os.path.getsize(db.DB_PATH)/1e6:.0f}MB")

def bench(label, fn, reps=3):
    times = []
    for _ in range(reps):
        t = time.perf_counter(); out = fn(); times.append(time.perf_counter() - t)
    best = min(times)
    extra = ""
    if isinstance(out, dict) and "rows" in out:
        payload = json.dumps(out, ensure_ascii=False)
        extra = f"  rows={len(out['rows'])} payload={len(payload)/1e6:.1f}MB"
    elif isinstance(out, list):
        extra = f"  rows={len(out)}"
    print(f"  {label:<38} {best*1000:8.0f} ms{extra}")
    return best

print("\n── hot paths ──")
bench("get_all_nicks() full list", lambda: db.get_all_nicks(""))
bench("get_all_nicks(search='user123')", lambda: db.get_all_nicks("user123"))
bench("get_all_nicks(limit=200)", lambda: db.get_all_nicks("", limit=200))
bench("filter_nicks_multi(forum contains)", lambda: db.filter_nicks_multi(
    [{"field": "forum", "op": "contains", "value": "טופ"}]))
bench("get_nick(single)", lambda: db.get_nick(1), reps=20)
bench("count_export_modes()", lambda: db.count_export_modes())
bench("export_data('has_info')", lambda: db.export_data("has_info"))

# connection overhead: 500 trivial calls (what CRUD-heavy code does)
def many_conns():
    for i in range(500):
        db.get_setting("display_theme", "dark")
bench("500x get_setting (conn overhead)", many_conns, reps=3)

print("\nDB path kept for inspection:", db.DB_PATH)
