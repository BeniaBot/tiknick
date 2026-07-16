# Tik-Nick — הקשר מכווץ (context_compress.md)

> תקציר לוגיקה ומצב נוכחי, מיועד להזרקה כהקשר למודל שפה לפני עבודה על הקוד.
> מבוסס על קריאת קוד המקור בפועל. **`APP_VERSION="0.8.0"`** · PyWebView (Python + web) · SQLite · PyInstaller → EXE יחיד.

## מה זה
מנהל "ניקים" (שמות משתמש) בפורומים חרדיים. לכל ניק: פורום, שם משתמש, שם אמיתי, טלפון, מייל, כתובת, קבוצות, מוניטין, סטטוס, הערות, הערות אישיות, פרטים נוספים, תאריך הצטרפות, מספר הודעות, אווטאר/צבע, ורמת אמינות. **הכל מקומי** ב-SQLite (`tiknick.db`, ליד ה-EXE / `%APPDATA%\TikNick`).

## סטאק וזרימה
`app.js` → `window.pywebview.api.<method>()` → `class API` ב-`main.py` → `database.py` → SQLite.
כל method ב-`class API` נחשף אוטומטית ל-JS. app.js משתמש ב-`api(method, ...args)` גנרי עם `waitForApi` (עד 10ש').

## מודל נתונים (7 טבלאות)
- **nicks** — הישות המרכזית (~22 עמודות). כולל `trust_level` (ברירת מחדל 5) ו-`source` ('manual'/מקור ייבוא).
- **nick_contacts** — פרטי קשר מרובים לכל ניק: `type,value,label,is_private`. (CASCADE)
- **nick_conflicts** — התנגשויות מייבוא: `field_name,conflicting_value,source_info`. (CASCADE)
- **nick_identities** — זהויות כפולות: זוג `(a,b)` ממוין+UNIQUE. (CASCADE)
- **forums** — `name UNIQUE,color,url,profile_pattern,sort_order`. "כללי" תמיד קיים ומוגן ממחיקה.
- **settings** — key/value, כולל `display_*` והגדרות export.
- **sync_settings** — לכל שדה: האם מיוצא.
מנוע DB: `PRAGMA journal_mode=WAL`, `foreign_keys=ON`. `init_db()` יוצר טבלאות + seed; `_migrate()` מוסיף עמודות חסרות ל-DB ישן.

## קבועים חשובים ב-database.py
- **KNOWN_FORUMS** — 15 פורומים חרדיים מובנים (שם+צבע+URL). לא מתווספים אוטומטית; המשתמש בוחר. `resolve_forum_data` משלים צבע/URL מהרשימה לפי שם.
- **ALL_NICK_FIELDS** — רשימת `(key, label, default_sync)`. ברירת מחדל **לא-מסונכרן**: `private_notes` ו-`avatar_image` (כבד). זה למעשה מנגנון "כספת הפרטיות".

## אלגוריתמים/לוגיקה מרכזית
1. **מיון "מידע מעניין"** — `get_all_nicks` ממיין: `has_info DESC, trust_level DESC, updated_at DESC`. `has_info=1` אם יש real_name/phone/email/notes/extra_info. חיפוש חי סורק 9 שדות עם LIKE.
2. **ייבוא (2 שלבים)** — `load_import_file` בודק פורומים לא-מוכרים ושומר `_pending_import` בזיכרון → `confirm_import(forum_mapping)`. מיזוג: ניק חדש נוסף; שדה ריק בניק קיים מתמלא שקט; ערך שונה בשדה קיים ומלא → נרשם ב-`nick_conflicts`. ניק מיובא: `trust_level` מוגבל ל-≤4.
3. **ייצוא** — רק שדות ש-`get_exportable_fields()` מחזיר (לפי sync_settings). פורמט `{version:2, exported_at, exported_fields, nicks[]}`.
4. **בדיקת עדכונים** — `check_for_updates` מושך `releases/latest` מ-GitHub, parse גרסה ל-3 מספרים (מתעלם מ-`v`), משווה, מאתר נכס `.exe`. שקטה בהפעלה (2.5ש' אחרי טעינה) + ידנית. תלויה ב-`APP_VERSION`↔tag.
5. **מירכוז חלון (main.py)** — DPI awareness מראש; מוצא hwnd אמיתי, מודד work-area, ממרכז ב-`SetWindowPos`; fallback ל-`window.move`.
6. **נתיבים** — `resource_path` (משאבים ארוזים, `sys._MEIPASS` ב-EXE) ו-`data_dir` (%APPDATA% כשקפוא, ליד הסקריפט בפיתוח) + מיגרציית DB ישן.

## מודולי רשת (סריקה ואינטרנט)
7. **scraper.py** — סורק רשימות משתמשים מפורומי NodeBB דרך `/api/users`. מיפוי שדות ומיזוג למאגר. השהיות אנושיות (0.8-2.5s), תמיכה בעוגיות, זיהוי Cloudflare. משתמש ב-SmartSession מ-anti_detect.py עם fallback ל-urllib.
8. **anti_detect.py** — מודול אנטי-זיהוי מרכזי. SmartSession עם: רוטציית 15 User-Agents (Chrome/Firefox/Edge), headers מלאים של דפדפן, השהיות אנושיות אקראיות, exponential backoff עם jitter, rate limiter (20/דקה), ניהול עוגיות, זיהוי חסימת Cloudflare. אפס תלויות חיצוניות.
9. **data_extractor.py** — חילוץ מידע אישי מפוסטים: טלפונים ישראליים (05X, +972), מיילים, שמות (לפי הקדמות עבריות), כתובות, טלגרם, WhatsApp. סורק את כל הפוסטים של משתמש, מחלץ regex, מייצר דוח HTML אינטראקטיבי עם ציוני ביטחון (high/medium/low) וכפתור "החל על הניק".
10. **chazonishnik.py** — ניתוח פעילות משתמש: פוסטים, לייקים, שעות/ימי פעילות, מעריצים. 4 חוטים מקבילים. דוח HTML.
11. **stinknik.py** — איתור פוסטים שקיבלו דיסלייקים. דוח HTML. השהיות אקראיות (0.6-2.0s).

## מצב v0.8.0 — עובד
ניהול ניקים מלא (CRUD, חיפוש חי, מיון, טבלה/כרטיסים) · אנשי-קשר מרובים (פרטי/גלוי) · זהויות כפולות · צבע/אווטאר לניק · מנהל פורומים (15 מובנים + "כללי" מוגן, בורר צבע, קישור) · פתיחת פרופיל בדפדפן · ייצוא/ייבוא + מיפוי פורומים + התנגשויות · הגדרות סנכרון/כספת פרטיות · הגדרות תצוגה (theme dark/light/system, 8 accents, density, בורר עמודות) · סריקת NodeBB עם אנטי-זיהוי · חילוץ מידע מפוסטים · Chazonishnik · Stinknik · בדיקת עדכונים + עדכון אוטומטי · דיאלוג אודות.

## מוסכמות עבודה
- **git**: תיקייה אחת עם `.git`. עדכון = `git add . && git commit -m "..." && git push`.
- **מהדורה**: עדכן `APP_VERSION` → push → `build.bat` → Release עם tag תואם + EXE מצורף.
- **כלל זהב**: `APP_VERSION` == tag (`0.8.0`==`v0.8.0`), אחרת בדיקת העדכונים נשברת.
