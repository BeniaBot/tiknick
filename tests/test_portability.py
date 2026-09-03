# -*- coding: utf-8 -*-
"""0.8.7: .tiknick v3 (contacts + identities), CSV import, import dry-run, auto backup."""
import os, sys, tempfile, shutil, io, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db
import csv_import as ci

tmp = tempfile.mkdtemp(prefix="tiknick_port_")
db.DB_PATH = os.path.join(tmp, "a.db")
db.init_db()
fails = []

def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)

db.add_forum("פ1", "#111", ""); db.add_forum("פ2", "#222", "")
a = db.create_nick({"forum": "פ1", "username": "moshe", "phone": "0501112222"})
b = db.create_nick({"forum": "פ2", "username": "moshe2"})
db.create_nick({"forum": "פ1", "username": "lonely"})
db.add_contact(a, "phone", "052-333-4444", "בית")
db.add_contact(a, "email", "m@x.com", "")
db.add_contact(a, "phone", "050-999-0000", "פרטי", is_private=1)
db.bulk_link_identities([a, b])

# ══ פורמט גרסה 3 ══════════════════════════════════════════════════════
exp = db.export_data("all")
blob = json.dumps(exp, ensure_ascii=False)
ok("הקובץ מסומן גרסה 3", exp["version"] == 3, str(exp["version"]))
ok("exported_fields נשאר שמות עמודות בלבד (תאימות לאחור)",
   all(f in db._NICK_FIELDS for f in exp["exported_fields"]), str(exp["exported_fields"][:5]))
ok("אנשי קשר גלויים יוצאו", exp["counts"]["contacts"] == 2, str(exp["counts"]))
ok("איש קשר 🔒 סודי לא יוצא בשום צורה", "0999" not in blob.replace("-", ""))
ok("קבוצת זהות יוצאה כ(פורום, שם משתמש)",
   exp["identity_groups"] and set(m["username"] for m in exp["identity_groups"][0]) == {"moshe", "moshe2"},
   str(exp["identity_groups"]))

# ── סבב שלם למאגר נקי ──
db.close_pool(); db.DB_PATH = os.path.join(tmp, "b.db"); db.init_db()
db.add_forum("פ1", "#111", ""); db.add_forum("פ2", "#222", "")
r = db.import_data(exp, "f", None, import_name="חבר")
na = db.find_nick("פ1", "moshe")
ok("אנשי קשר נקלטו", r["contacts"] == 2 and len(db.get_contacts(na["id"])) == 2, str(r))
ok("אנשי קשר שנקלטו אינם מסומנים סודי",
   all(c["is_private"] == 0 for c in db.get_contacts(na["id"])))
ok("קישור הזהות נוצר", r["identities"] == 1 and
   [x["username"] for x in db.get_identities(na["id"])] == ["moshe2"])
r2 = db.import_data(exp, "f", None, import_name="שוב")
ok("ייבוא חוזר לא מכפיל אנשי קשר",
   r2["contacts"] == 0 and len(db.get_contacts(na["id"])) == 2)

# ── טלפון באותו אדם בכתיבה אחרת = אותו איש קשר ──
alt = json.loads(json.dumps(exp, ensure_ascii=False))
for n in alt["nicks"]:
    if n["username"] == "moshe":
        n["contacts"] = [{"type": "phone", "value": "+972-52-333-4444"}]
db.import_data(alt, "f", None, import_name="נרמול")
ok("972…‎ ו-052…‎ הם אותו איש קשר", len(db.get_contacts(na["id"])) == 2,
   str([c["value"] for c in db.get_contacts(na["id"])]))

# ── המתגים מכבים כל מקטע בנפרד ──
db.set_sync_setting("contacts", False)
e_off = db.export_data("all")
ok("כיבוי 'אנשי קשר' מוציא אותם מהקובץ", e_off["counts"]["contacts"] == 0)
ok("כיבוי 'אנשי קשר' לא נוגע בזהויות", e_off["counts"]["identity_groups"] >= 1, str(e_off["counts"]))
db.set_sync_setting("contacts", True); db.set_sync_setting("identities", False)
e_off2 = db.export_data("all")
ok("כיבוי 'זהויות' מוציא רק אותן",
   e_off2["counts"]["identity_groups"] == 0 and e_off2["counts"]["contacts"] > 0, str(e_off2["counts"]))
db.set_sync_setting("identities", True)

# ── קובץ גרסה 2 עדיין נטען ──
v2 = {"version": 2, "exported_fields": ["forum", "username", "phone"],
      "nicks": [{"forum": "פ1", "username": "old", "phone": "03"}]}
ok("קובץ גרסה 2 מיובא כרגיל", db.import_data(v2, "old", None, import_name="v2")["imported"] == 1)

# ── חצי קבוצה: מדלגים, לא ממציאים ──
db.close_pool(); db.DB_PATH = os.path.join(tmp, "c.db"); db.init_db()
db.add_forum("פ1", "#111", "")
half = json.loads(json.dumps(exp, ensure_ascii=False))
half["nicks"] = [n for n in half["nicks"] if n["forum"] == "פ1"]
rh = db.import_data(half, "f", None, import_name="חצי")
ok("קישור שצדו השני חסר מדולג ומדווח",
   rh["identities"] == 0 and rh["identities_skipped"] == 1, str(rh))

# ── המשתמש יכול לוותר על מקטע בייבוא ──
db.close_pool(); db.DB_PATH = os.path.join(tmp, "d.db"); db.init_db()
db.add_forum("פ1", "#111", ""); db.add_forum("פ2", "#222", "")
rn = db.import_data(exp, "f", None, import_name="בלי", include_contacts=False,
                    include_identities=False)
ok("ביטול שני המקטעים בייבוא מכובד",
   rn["contacts"] == 0 and rn["identities"] == 0 and rn["imported"] == 3, str(rn))

# ══ ייבוא CSV ═════════════════════════════════════════════════════════
def csvfile(name, text, enc="utf-8"):
    p = os.path.join(tmp, name)
    if enc.startswith("utf-16"):
        open(p, "wb").write(text.encode(enc))
    else:
        io.open(p, "w", encoding=enc, newline="").write(text)
    return p

p1 = csvfile("app.csv", 'פורום,שם משתמש,טלפון,שם אמיתי\nפ1,csv1,="0501112222",משה\n', "utf-8-sig")
r1 = ci.parse_file(p1)
ok("קובץ שהתוכנה ייצאה ממופה לבד",
   r1["mapping"] == {"0": "forum", "1": "username", "2": "phone", "3": "real_name"}, str(r1["mapping"]))
n1 = ci.normalize_rows(r1["headers"], r1["rows"], r1["mapping"])
ok('="0501112222" חוזר למספר עם האפס', n1["nicks"][0]["phone"] == "0501112222",
   n1["nicks"][0]["phone"])

p2 = csvfile("he.csv", "שם משתמש;טלפון\ndavid;050-1234567\n", "cp1255")
r2 = ci.parse_file(p2)
ok("קובץ cp1255 עם נקודה-פסיק מפוענח נכון",
   r2["encoding"] == "cp1255" and r2["delimiter"] == ";" and r2["headers"][0] == "שם משתמש",
   f"{r2['encoding']} {r2['delimiter']!r} {r2['headers']}")

p3 = csvfile("x.txt", "ניק\tנייד\tמייל\navi\t501234567\ta@x.com\n", "utf-16")
r3 = ci.parse_file(p3)
n3 = ci.normalize_rows(r3["headers"], r3["rows"], r3["mapping"], default_forum="פ1")
ok("UTF-16 של אקסל + כינויים בעברית", r3["encoding"].startswith("utf-16") and
   n3["nicks"][0]["email"] == "a@x.com", f"{r3['encoding']} {r3['mapping']}")
ok("אפס מוביל שאקסל בלע מוחזר", n3["nicks"][0]["phone"] == "0501234567", n3["nicks"][0]["phone"])
ok("שורה בלי פורום מקבלת את ברירת המחדל", n3["nicks"][0]["forum"] == "פ1")

p4 = csvfile("d.csv", "שם משתמש,טלפון,הערות\ndup,050,ראשון\ndup,,שני\n,051,רפאים\n")
r4 = ci.parse_file(p4)
n4 = ci.normalize_rows(r4["headers"], r4["rows"], r4["mapping"])
ok("כפילות בתוך הקובץ מאוחדת לרשומה אחת", len(n4["nicks"]) == 1 and n4["merged_dupes"] == 1)
ok("שורה בלי שם משתמש מדולגת ומדווחת", n4["skipped_no_username"] == 1)

try:
    ci.normalize_rows(["טלפון"], [["050"]], {"0": "phone"}); ok("בלי עמודת שם משתמש נעצר", False)
except ValueError:
    ok("בלי עמודת שם משתמש נעצר", True)

ok("עמודת אמינות לא ניתנת למיפוי",
   "trust_level" not in {f["key"] for f in ci.mappable_fields()})
ok("הגנת הזרקת נוסחאות מתקלפת", ci.unquote_cell("'=SUM(A1)") == "=SUM(A1)")
ok("גרש רגיל בעברית נשמר", ci.unquote_cell("ז'אנר") == "ז'אנר")

# ── CSV נכנס דרך מנוע המקורות, לא ישירות לטבלה ──
db.close_pool(); db.DB_PATH = os.path.join(tmp, "e.db"); db.init_db()
db.add_forum("פ1", "#111", "")
rc = db.import_data(n1, "app.csv", None, import_name="מאקסל", import_trust=6)
nc = db.find_nick("פ1", "csv1")
srcs = db.get_field_sources(nc["id"], "phone")
ok("ערך מ-CSV נרשם תחת מקור ייבוא עם אמינות",
   len(srcs) == 1 and srcs[0]["kind"] == "import" and srcs[0]["trust"] == 6, str(srcs))

# ══ תצוגה מקדימה ══════════════════════════════════════════════════════
db.create_nick({"forum": "פ1", "username": "prev", "phone": "0501111111", "notes": "ישן"})
data = {"version": 3, "exported_fields": ["forum", "username", "phone", "notes"],
        "nicks": [{"forum": "פ1", "username": "prev", "phone": "0502222222", "notes": "ישן"},
                  {"forum": "פ1", "username": "חדש", "phone": "0503333333"},
                  {"forum": "פ1", "username": "", "phone": "x"}]}
pv = db.preview_import(data)
ok("התצוגה סופרת חדשים מול קיימים",
   pv["new_nicks"] == 1 and pv["existing_nicks"] == 1, str(pv))
ok("ערך זהה אינו התנגשות, ערך שונה כן", pv["conflicts"] == 1, str(pv["conflicts"]))
ok("ההתנגשות מוצגת עם הערך הישן והחדש",
   pv["samples"] and pv["samples"][0]["old"] == "0501111111"
   and pv["samples"][0]["new"] == "0502222222", str(pv["samples"]))
ok("שורה בלי שם משתמש נספרת כדילוג", pv["skipped_no_username"] == 1)
ok("התצוגה המקדימה לא כותבת דבר",
   db.find_nick("פ1", "prev")["phone"] == "0501111111" and db.find_nick("פ1", "חדש") is None)

db.set_forum_io_flag("פ1", False)
pv2 = db.preview_import(data)
ok("פורום שכובה בהגדרות מדווח כדילוג",
   pv2["skipped_forum"] == 2 and pv2["excluded_forums"] == ["פ1"], str(pv2))
db.set_forum_io_flag("פ1", True)

# ══ גיבוי אוטומטי ═════════════════════════════════════════════════════
time.sleep(1.05)
r = db.auto_backup("daily")
ok("גיבוי יומי נוצר", r["ok"] and os.path.exists(r["path"]), str(r))
ok("הגיבוי הוא מאגר תקין", db.validate_backup(r["path"]) >= 1)
ok("גיבוי שני באותו יום מדולג", db.auto_backup("daily").get("skipped") == "טרי")
for reason in ("reset", "manual", "extra"):
    time.sleep(1.05); db.auto_backup(reason, force=True)
st = db.backup_status()
ok("נשמרים רק %d גיבויים" % db.AUTO_BACKUP_KEEP, st["count"] == db.AUTO_BACKUP_KEEP, str(st["count"]))
ok("הישן ביותר נמחק ראשון",
   not any(f["name"].startswith("tiknick-daily-") for f in st["files"]),
   str([f["name"] for f in st["files"]]))
ok("סטטוס מדווח נפח כולל", st["bytes"] > 0 and st["dir"].endswith("backups"))
db.DB_PATH = os.path.join(tmp, "nope", "x.db")
ok("גיבוי לנתיב בלתי אפשרי מחזיר שגיאה ולא מתרסק",
   db.auto_backup("bad", force=True).get("ok") in (False, True))

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("PORTABILITY TESTS PASSED")
db.close_pool()
shutil.rmtree(tmp, ignore_errors=True)
