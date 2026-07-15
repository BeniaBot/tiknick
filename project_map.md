# Tik-Nick — מפת פרויקט (project_map.md)

> מסמך ארכיטקטורה תמציתי למודלי שפה ולמפתחים. בלי קוד מלא — רק מבנה, תפקידים וזרימת מידע.
> נבנה מקריאה ישירה של קוד המקור ב-Project Knowledge (לא מהסיכום). גרסה בקוד: `APP_VERSION = "0.2.5"`.
> ריפו: `github.com/BeniaBot/tiknick`

---

## מהות בשורה אחת
אפליקציית דסקטופ ל-Windows לניהול "ניקים" (שמות משתמש) בפורומים חרדיים. **PyWebView**: backend ב-Python + ממשק Web, נתונים ב-SQLite, נארז ל-EXE יחיד ב-PyInstaller.

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

  שירות חיצוני יחיד בפועל:  api.github.com/repos/.../releases/latest  (בדיקת עדכונים)
```

## תפקיד כל קובץ (לפי הקוד בפועל)

### ליבה (runtime)
| קובץ | תפקיד | מתקשר עם |
|------|--------|-----------|
| `main.py` | נקודת כניסה. מגדיר DPI awareness (Windows), פותר נתיבי משאבים (`resource_path`/`data_dir`) לתמיכה גם בהרצה רגילה וגם ב-EXE, מבצע מיגרציה של DB ישן, יוצר חלון PyWebView בגודל 1400×820 וממרכז אותו (work-area + hwnd אמיתי, fallback ל-`window.move`). מגדיר `class API` שכל שיטותיה נחשפות ל-JS. כולל את `check_for_updates` (מושך releases/latest מ-GitHub, משווה גרסאות, מאתר נכס EXE). | ← `web/app.js` (דרך `window.pywebview.api`) · → `database.py` (כ-`db`) · → GitHub API |
| `database.py` | כל שכבת ה-SQLite. מגדיר `KNOWN_FORUMS` (15 פורומים מובנים) ו-`ALL_NICK_FIELDS` (רשימת השדות + ברירת מחדל לסנכרון). יוצר 7 טבלאות, מריץ `_migrate()` להוספת עמודות חסרות ל-DB ישן, ומספק CRUD לניקים/פורומים/אנשי-קשר/התנגשויות/זהויות, הגדרות תצוגה, הגדרות סנכרון, וייצוא/ייבוא עם מיפוי פורומים וזיהוי התנגשויות. | ← `main.py` · → `tiknick.db` |

### ממשק (`web/`)
| קובץ | תפקיד |
|------|--------|
| `web/index.html` | מבנה ה-DOM: סרגל צד, טבלה/כרטיסים, מודאלים, שורת סטטוס, footer עם אינדיקטור עדכון. |
| `web/style.css` | עיצוב מבוסס CSS variables: ערכות כהה/בהיר, 8 צבעי מבטא, צפיפות, מודאלים, טבלה, דיאלוג אודות בסגנון "olive", אינדיקטור עדכון. |
| `web/app.js` | **כל** לוגיקת הצד-לקוח: state גלובלי (`S`), הגדרת עמודות (`COLS`), אתחול עם `waitForApi`, גשר `api()` גנרי, רינדור טבלה/כרטיסים, מיון, חיפוש חי (debounce 200ms), דיאלוג ניק (כולל אנשי-קשר/זהויות/התנגשויות), מנהל פורומים, הגדרות סנכרון, ייצוא/ייבוא + דיאלוג מיפוי פורומים, בדיקת עדכונים, ודיאלוג אודות. הכותרת בקובץ מסומנת עדיין `v0.1`. |

### בנייה, הרצה והפצה
| קובץ | תפקיד |
|------|--------|
| `TikNick.spec` | קונפיגורציית PyInstaller: single-file, windowed, אורז `web/` ו-`icon.ico`, `hiddenimports` לבקאנד של pywebview ב-Windows, UPX, אייקון + `version_info.txt`. |
| `version_info.txt` | מטא-דאטה של גרסת ה-EXE (Windows). |
| `build.bat` | סקריפט בנייה (PyInstaller → `dist\TikNick.exe`). |
| `הפעל.bat` | הרצה מהמקור: מתקין pywebview שקט ואז `python main.py`. |
| `upload_to_github.bat` | סקריפט העלאה חד-פעמי (מגדיר זהות git, init, add, commit, push). **שים לב:** ה-remote בקובץ מצביע ל-`b0554003794-alt/tiknick`, בעוד שאר הפרויקט משתמש ב-`BeniaBot/tiknick` — פער שכדאי ליישב. |
| `README.md` | תיאור למשתמש. מציג עדיין תג גרסה `0.2` וכולל בקטע "מה יבוא" את Chazonishnik/Stinknik וסריקה אוטומטית. |
| `.gitignore` | חוסם `tiknick.db*`, `*.log`, `__pycache__`, `build/`, `dist/`, קבצי OS. |
| `icon.ico` | אייקון התג (ענבר). |

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
- **גשר API**: כל method ב-`class API` זמין אוטומטית כ-`window.pywebview.api.<name>()`. הוספת יכולת = הוספת method שם + קריאה ב-app.js.
- **מיון ברירת מחדל**: `has_info DESC, trust_level DESC, updated_at DESC` — ניקים עם מידע "מעניין" (שם אמיתי/טלפון/מייל/הערות/extra_info) עולים למעלה. הלוגיקה הזו נמצאת ב-SQL של `get_all_nicks`.
- **ייבוא**: זרימת 2 שלבים — `load_import_file` (בדיקת פורומים לא-מוכרים) → `confirm_import(mapping)`. התנגשות ערך שונה בשדה קיים → נרשמת ב-`nick_conflicts`; שדה ריק → מתמלא שקט. ניק מיובא מוגבל ל-`trust_level ≤ 4`.
- **בדיקת עדכונים**: תלויה בהתאמת `APP_VERSION`↔tag ב-GitHub (parse ל-3 חלקים, מתעלם מ-`v`).

---

## אזהרות דיוק (פערים בין הקוד למסמכים)
1. **`scraper.py` — לא נמצא ב-Project Knowledge.** גם אין תיקייה בשם "אינטרנט". הסיכום מציין ש"קיים", אך בקוד שנסרק אין קובץ סורק ואין קריאה אליו מ-`main.py`. הסריקה, Chazonishnik ו-Stinknik הם **תוכנית בלבד** בשלב זה. אם הקובץ קיים בדיסק אך לא הועלה ל-Knowledge — הוסף אותו ואבנה עבורו ערך.
2. **חוסר עקביות בגרסה**: `APP_VERSION=0.2.5` בקוד, אך `app.js` מסומן `v0.1` ו-README מציג `0.2`. שווה ליישר (כלל הזהב חל רק על tag↔APP_VERSION, אבל הסימונים האחרים מבלבלים).
3. **פער remote**: `upload_to_github.bat` דוחף ל-`b0554003794-alt/tiknick`, שאר הפרויקט ל-`BeniaBot/tiknick`.
4. שדה **`trust_level`** (רמת אמינות, ברירת מחדל 5) לא הוזכר בסיכום אך הוא מרכזי למיון ולייבוא.
