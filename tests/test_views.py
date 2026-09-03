# -*- coding: utf-8 -*-
"""0.8.8: identity map, printable profile sheet, recently viewed, search ranking."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database as db
import profile_sheet as ps

tmp = tempfile.mkdtemp(prefix="tiknick_views_")
db.DB_PATH = os.path.join(tmp, "t.db")
db.init_db()
fails = []

def ok(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{detail}]" if not cond and detail else ""))
    if not cond:
        fails.append(name)

for f in ("פ1", "פ2", "פ3"):
    db.add_forum(f, "#111", "")

# ══ מפת זהויות ════════════════════════════════════════════════════════
a = db.create_nick({"forum": "פ1", "username": "A", "real_name": "משה"})
b = db.create_nick({"forum": "פ2", "username": "B", "real_name": "יוסי"})
c = db.create_nick({"forum": "פ3", "username": "C", "status": "מורחק"})
d = db.create_nick({"forum": "פ1", "username": "D"})
e = db.create_nick({"forum": "פ2", "username": "E"})
db.create_nick({"forum": "פ1", "username": "solo"})
db.bulk_link_identities([a, b, c])
db.bulk_link_identities([d, e])

m = db.get_identity_map()
ok("רק ניקים מקושרים נכנסים למפה", m["total_groups"] == 2 and m["linked_nicks"] == 5, str(m["total_groups"]))
big = m["groups"][0]
ok("הקבוצה הגדולה ראשונה", big["size"] == 3 and big["forum_count"] == 3, str(big["size"]))
ok("מורחקים נספרים", big["banned"] == 1)
ok("סתירה בשדה מזוהה", big["conflicts"] == ["שם אמיתי"], str(big["conflicts"]))
ok("קבוצה בלי סתירה לא מסומנת", m["groups"][1]["conflicts"] == [])
ok("המפה לא מחזירה avatar_image (כלל מטען הרשימות)",
   not any("avatar_image" in mem for g in m["groups"] for mem in g["members"]))
ok("ניק בודד לא מופיע כקבוצה",
   not any("solo" in [x["username"] for x in g["members"]] for g in m["groups"]))

# קבוצה שאיבדה קישור (שחזור חלקי) עדיין מזוהה כקבוצה אחת
with db.get_connection() as conn:
    conn.execute("DELETE FROM nick_identities WHERE nick_id_a=? AND nick_id_b=?",
                 (min(a, c), max(a, c)))
ok("קבוצה לא-סגורה עדיין מקובצת נכון (union-find, לא הנחת קליקה)",
   any(g["size"] == 3 for g in db.get_identity_map()["groups"]))
ok("תיקון משלים את הקישור החסר", db.repair_identity_groups() == 1)
ok("תיקון חוזר לא מוסיף כלום", db.repair_identity_groups() == 0)

# קישור יתום אחרי מחיקת ניק לא מפיל את המפה
db.delete_nicks([e])
mm = db.get_identity_map()
ok("ניק שנמחק לא משאיר קבוצה שבורה",
   all(len(g["members"]) >= 2 for g in mm["groups"]), str([g["size"] for g in mm["groups"]]))

# ══ דירוג רלוונטיות בחיפוש ════════════════════════════════════════════
db.close_pool(); db.DB_PATH = os.path.join(tmp, "r.db"); db.init_db()
db.add_forum("פ1", "#111", "")
db.create_nick({"forum": "פ1", "username": "אחר", "notes": "מכיר את לומדעס", "phone": "050"})
db.create_nick({"forum": "פ1", "username": "לומדעס2"})
db.create_nick({"forum": "פ1", "username": "לומדעס"})
db.create_nick({"forum": "פ1", "username": "zz", "real_name": "לומדעס"})
names = [r["username"] for r in db.get_all_nicks("לומדעס")["rows"]]
ok("התאמה מדויקת בשם המשתמש ראשונה", names[0] == "לומדעס", str(names))
ok("תחילית לפני התאמה בשדה אחר", names.index("לומדעס2") < names.index("zz"), str(names))
ok("ניק שרק מזכיר את המילה בהערות אחרון", names[-1] == "אחר", str(names))
plain = [r["username"] for r in db.get_all_nicks("")["rows"]]
ok("בלי חיפוש — has_info עדיין ראשון", plain[0] == "אחר", str(plain))

# ══ נצפו לאחרונה ══════════════════════════════════════════════════════
db.close_pool(); db.DB_PATH = os.path.join(tmp, "v.db"); db.init_db()
db.add_forum("פ1", "#111", "")
ids = [db.create_nick({"forum": "פ1", "username": "u%d" % i}) for i in range(40)]
for i in ids:
    db.touch_recent(i)
rows = db.get_recent_views(50)
ok("נשמרים %d אחרונים" % db.RECENT_VIEWS_KEEP, len(rows) == db.RECENT_VIEWS_KEEP, str(len(rows)))
ok("האחרון שנצפה ראשון", rows[0]["username"] == "u39", rows[0]["username"])
ok("הישנים ביותר נזרקו", rows[-1]["username"] == "u10", rows[-1]["username"])
db.touch_recent(ids[0])
again = db.get_recent_views(50)
ok("צפייה חוזרת מקדמת ולא מכפילה",
   again[0]["username"] == "u0" and sum(1 for x in again if x["username"] == "u0") == 1)
db.delete_nicks([ids[0]])
ok("ניק שנמחק נעלם מהרשימה (CASCADE)",
   not any(x["username"] == "u0" for x in db.get_recent_views(50)))
ok("מזהה לא קיים לא מתרסק", db.touch_recent(999999) is False)
db.clear_recent_views()
ok("ניקוי מרוקן", db.get_recent_views() == [])

# ══ גיליון להדפסה ═════════════════════════════════════════════════════
db.close_pool(); db.DB_PATH = os.path.join(tmp, "p.db"); db.init_db()
db.add_forum("פ1", "#111", ""); db.add_forum("פ2", "#222", "")
x = db.create_nick({"forum": "פ1", "username": "__FIELDS__", "real_name": "משה",
                    "notes": "פומבי", "private_notes": "סוד",
                    "nick_color": "red;background-image:url(https://evil/x.png)",
                    "avatar_url": "https://forum/avatar.png"})
y = db.create_nick({"forum": "פ2", "username": "B", "status": "מורחק"})
db.bulk_link_identities([x, y])
db.add_contact(x, "phone", "0501112222", "בית")
db.add_contact(x, "email", "secret@x.com", "", is_private=1)
prof = db.get_merged_profile(x)
data = {"nick": db.get_nick(x), "members": prof["members"], "fields": prof["fields"],
        "contacts": prof["contacts"], "history": db.get_field_history(x),
        "truncated_members": 0, "truncated_history": 0}

sheet = ps.build_sheet(data, include_private=False, generated="03/09/2026")
ok("אין שום הפניה חיצונית בגיליון",
   "http://" not in sheet and "https://" not in sheet)
ok("הזרקת CSS דרך צבע הניק מנוטרלת", "evil/x.png" not in sheet)
ok("שם משתמש שנראה כמצייָן בתבנית שורד", "__FIELDS__" in sheet)
ok("הערה אישית לא נדפסת כברירת מחדל", "סוד" not in sheet)
ok("איש קשר סודי לא נדפס", "secret@x.com" not in sheet)
ok("הערה פומבית כן נדפסת", "פומבי" in sheet)
ok("חבר מורחק מסומן", "מורחק" in sheet)
ok("הגיליון מדפיס את עצמו בדפדפן", "window.print()" in sheet)

full = ps.build_sheet(data, include_private=True, generated="x")
ok("בבחירה מפורשת המידע הפרטי נכלל", "סוד" in full and "secret@x.com" in full)
ok("ומופיעה אזהרה בתחתית", "כולל הערות אישיות" in full)
ok("הערה פומבית לא מודפסת פעמיים", full.count("פומבי") == 1, str(full.count("פומבי")))

ok("צבע חוקי עובר", ps._css_color("#a1b2c3") == "#a1b2c3")
ok("צבע לא חוקי מוחלף", ps._css_color("red;url(x)") == "#8b90a0")
ok("תמונה מרוחקת נפסלת", ps._img_src("https://x/y.png") == "")
ok("data:image עובר", ps._img_src("data:image/png;base64,AAA") != "")

no_hist = ps.build_sheet(data, include_history=False, generated="x")
ok("אפשר לוותר על ציר הזמן", "ציר זמן" not in no_hist)

print()
if fails:
    print("FAILED:", fails); sys.exit(1)
print("VIEWS TESTS PASSED")
db.close_pool()
shutil.rmtree(tmp, ignore_errors=True)
