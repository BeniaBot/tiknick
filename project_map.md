# Tik-Nick — מפת פרויקט (project_map.md)

> מסמך ארכיטקטורה תמציתי למודלי שפה ולמפתחים. בלי קוד מלא — רק מבנה, תפקידים וזרימת מידע.
> נבנה מקריאה ישירה של קוד המקור. גרסה בקוד: `APP_VERSION = "0.8.0"`.
> ריפו: `github.com/BeniaBot/tiknick`

---

## מהות בשורה אחת
אפליקציית דסקטופ ל-Windows לניהול ומעקב אחר "ניקים" (שמות משתמש) בפורומים חרדיים. **PyWebView**: backend ב-Python + ממשק Web, נתונים ב-SQLite, נארז ל-EXE יחיד ב-PyInstaller.

## סכמת שכבות
```
┌─────────────────────────────────────────────┐
│  שכבת ממשק  (web/)                            │
│  index.html · style.css · app.js            │
└───────────────┬─────────────────────────────┘
                │  window.pywebview.api  ← גשר JS↔Python (async, עם waitForApi)
┌───────────────┴─────────────────────────────┐
│  שכבת Backend / API  (main.py → class API)  │
│  יצירת חלון · מירכוז DPI · בדיקת עדכונים ·    │
│  כל שיטות ה-API שה-JS קורא להן                │
└───────────────┬─────────────────────────────┘
                │  import database as db  (קריאות פונקציה ישירות)
┌───────────────┴─────────────────────────────┐
│  שכבת נתונים  (database.py)                  │
│  SQLite: 7 טבלאות · CRUD · מיזוג/ייבוא ·      │
│  הגדרות תצוגה · הגדרות סנכרון                 │
└───────────────┬─────────────────────────────┘
                │
   DB_PATH  →  ליד ה-EXE / %APPDATA%\TikNick\tiknick.db  (WAL, FK on)

  שירותים חיצוניים:
  - api.github.com/repos/.../releases/latest  (בדיקת עדכונים)
  - פורומי NodeBB: /api/users, /api/user/{slug}, /api/user/{slug}/posts  (סריקה + חילוץ)
```

## תפקיד כל קובץ (לפי הקוד בפועל)

### ליבה (runtime)
| קובץ | תפקיד | מתקשר עם |
|------|--------|-----------||
| `main.py` | נקודת כניסה. DPI awareness, נתיבי משאבים, מיגרציית DB, חלון PyWebView 1400×820. `class API` חושף שיטות ל-JS. כולל בדיקת עדכונים, סריקה, Chazonishnik, Stinknik, Data Extractor. | ← `web/app.js` · → `database.py` · → GitHub API |
| `database.py` | כל שכבת ה-SQLite. 15 פורומים מובנים, 7 טבלאות, CRUD, מיזוג/ייבוא, הגדרות. מנגנון `field_values` לייחוס מקורות ופתרון התנגשויות. | ← `main.py` · → `tiknick.db` |
| `scraper.py` | סריקת רשימות משתמשים מפורומי NodeBB דרך ה-API הרשמי. מיפוי שדות, מיזוג למאגר, תמיכה בעוגיות. משתמש ב-SmartSession מ-`anti_detect.py` עם fallback ל-urllib. | ← `main.py` · → NodeBB API · → `anti_detect.py` |
| `anti_detect.py` | מודול אנטי-זיהוי. SmartSession עוטף urllib עם: רוטציית 15 User-Agents, headers מלאים של דפדפן, השהיות אנושיות (0.8-2.5s), exponential backoff עם jitter, rate limiter (20/דקה), ניהול עוגיות, זיהוי חסימת Cloudflare. | ← `scraper.py`, `chazonishnik.py`, `stinknik.py`, `data_extractor.py` |
| `data_extractor.py` | חילוץ מידע אישי מפוסטים: טלפונים ישראליים, מיילים, שמות, כתובות, טלגרם, WhatsApp. סורק את כל הפוסטים של משתמש, מחלץ regex, מייצר דוח HTML אינטראקטיבי עם ציוני ביטחון. | ← `main.py` · → NodeBB API · → `anti_detect.py` |
| `chazonishnik.py` | ניתוח פעילות משתמש בפורום: פוסטים, לייקים, שעות/ימי פעילות, מעריצים. דוח HTML אינטראקטיבי. 4 חוטים מקבילים. | ← `main.py` · → NodeBB API |
| `stinknik.py` | איתור פוסטים שקיבלו דיסלייקים (כולל מוסתרים). דוח HTML. | ← `main.py` · → NodeBB API |

### ממשק (`web/`)
| קובץ | תפקיד |
|------|--------|
| `web/index.html` | מבנה ה-DOM: סרגל צד (ניקים, קובץ, הגדרות, כלים, מתקדם), טבלה/כרטיסים, באנרים צפים (סריקה, Chazonishnik, Stinknik, Data Extractor), שורת סטטוס. |
| `web/style.css` | עיצוב CSS variables: ערכות כהה/בהיר, 8 צבעי מבטא, צפיפות, מודאלים. |
| `web/app.js` | כל לוגיקת צד-הלקוח: state, עמודות, גשר API, רינדור, מיון, חיפוש, דיאלוגים, Chazonishnik, Stinknik, Data Extractor, הגדרות תצוגה. |

### בנייה, הרצה והפצה
| קובץ | תפקיד |
|------|--------|
| `TikNick.spec` | PyInstaller: single-file, windowed, אורז web/ ו-icon.ico. |
| `version_info.txt` | מטא-דאטה של גרסת EXE (Windows). |
| `build.bat` | סקריפט בנייה (PyInstaller → `dist\TikNick.exe`). |
| `הפעל.bat` | הרצה מהמקור: מתקין pywebview ואז `python main.py`. |
| `upload_to_github.bat` | סקריפט העלאה. Remote: `BeniaBot/tiknick`. |
| `.gitignore` | חוסם `tiknick.db*`, `*.log`, `__pycache__`, `build/`, `dist/`. |

## מודל הנתונים (7 טבלאות ב-SQLite)
```
forums(id, name UNIQUE, color, url, profile_pattern, sort_order)
nicks(id, forum, username, groups, reputation, real_name, phone, email,
      address, notes, private_notes, extra_info, status, join_date,
      post_count, avatar_url, nick_color, avatar_image, source,
      trust_level, created_at, updated_at)
nick_contacts(id, nick_id→nicks, type, value, label, is_private)          [CASCADE]
nick_conflicts(id, nick_id→nicks, field_name, conflicting_value, source_info, created_at) [CASCADE]
nick_identities(id, nick_id_a→nicks, nick_id_b→nicks, created_at, UNIQUE(a,b))            [CASCADE]
settings(key PRIMARY, value)              ← כולל display_* ו-export_version/user_identity/trust_own_data
sync_settings(field_key PRIMARY, synced)  ← איזה שדה מיוצא
```

## זרימת מידע טיפוסית (הוספת ניק)
```
משתמש בדיאלוג  →  app.js אוסף שדות (fields[])  →  api('create_nick', data)
   →  window.pywebview.api.create_nick  →  API.create_nick (ממיר reputation ל-int)
   →  db.create_nick  →  INSERT ל-nicks ב-SQLite  →  מחזיר lastrowid
   →  חזרה ל-app.js  →  loadNicks()  →  get_all_nicks  →  רינדור מחדש
```

## נקודות אינטגרציה מרכזיות
- **גשר API**: כל method ב-`class API` זמין אוטומטית כ-`window.pywebview.api.<name>()`.
- **מיון ברירת מחדל**: `has_info DESC, trust_level DESC, updated_at DESC` — ניקים עם מידע "מעניין" עולים למעלה.
- **ייבוא**: 2 שלבים — `load_import_file` → `confirm_import(mapping)`. התנגשות → `nick_conflicts`. שדה ריק → מתמלא שקט. ניק מיובא מוגבל ל-`trust_level ≤ 4`.
- **אנטי-זיהוי**: כל בקשות הרשת עוברות דרך `anti_detect.SmartSession` עם fallback ל-urllib רגיל.
- **בדיקת עדכונים**: תלויה בהתאמת `APP_VERSION`↔tag ב-GitHub.
