# Tik-Nick — מסמך הקשרים (מקור אמת יחיד)

> נכתב מקריאה מלאה של כל הקוד; עודכן לגרסה **0.8.2** (2026-09).
> **`context_compress.md` ו-`project_map.md` מיושנים** (מתארים 0.2.5) — אל תסתמך עליהם.
> מדיניות גרסאות: להישאר ב-0.8.x — לבנימין יש עוד שיפורים מתוכננים לפני 0.9.

## מהות

תוכנת דסקטופ Windows בעברית (RTL) לניהול ומעקב ניקים בפורומים חרדיים.
PyWebView: backend פייתון + ממשק HTML/CSS/JS בחלון, SQLite מקומי, PyInstaller → EXE יחיד.
ריפו: `BeniaBot/tiknick` · רישיון שימוש אישי · המשתמשים הם דוברי עברית לא-טכניים.

## קבצים (heב-runtime)

| קובץ | שורות | תפקיד |
|---|---|---|
| `main.py` | ~890 | כניסה, DPI, נתיבים, לוגים, `class API` (כל method → `window.pywebview.api.*`), מנגנון עדכון עצמי, threads לסריקה/ניתוחים |
| `database.py` | ~1270 | כל שכבת SQLite: 11 טבלאות + FTS5, מנוע מקורות, ייבוא/ייצוא, CRUD |
| `scraper.py` | ~430 | סריקת **NodeBB + Discourse** (זיהוי פלטפורמה, עימוד, ריטריי, 429, cookie); `detect_platform`, `_scrape_nodebb`/`_scrape_discourse`, מיפוי לכל פלטפורמה, מיזוג עמוד-שלם דרך `db.merge_scraped_users`. פלטפורמות ללא API (XenForo/phpBB/custom) מרימות שגיאה ידידותית |
| `chazonishnik.py` | ~255 | ניתוח פעילות משתמש (פוסטים/לייקים/שעות) → דוח HTML; Chart.js מוטמע מ-`web/chart.umd.min.js` (עובד אופליין, fallback ל-CDN). עוגיית `express.sid` אופציונלית; כל פורום NodeBB דרך בורר בממשק |
| `stinknik.py` | ~197 | כל הפוסטים עם דיסלייקים → דוח HTML. לרוב בלי עוגייה |
| `web/index.html` | ~233 | שלד: sidebar, topbar, טבלה+כרטיסים, באנרים צפים, statusbar |
| `web/app.js` | ~3080 | כל לוגיקת הצד-לקוח (פירוט למטה) |
| `web/style.css` | ~1177 | ערכות dark/light + 8 מבטאים דרך `data-theme`/`data-accent`, צפיפות דרך `data-density` |

בנייה: `TikNick.spec` (onefile, windowed, אורז `web/`+`icon.ico`, hiddenimports ל-edgechromium) · `build.bat` · `version_info.txt` (0.8.0.0) · `הפעל.bat` להרצה מהמקור.

## נתיבים ולוגים

- `resource_path(rel)` — משאבים ארוזים (`sys._MEIPASS` ב-EXE).
- `data_dir()` — ב-EXE: `%APPDATA%\TikNick` (עם מיגרציה אוטומטית של DB ישן מליד ה-EXE); בפיתוח: ליד הסקריפט.
- לוגים: `tiknick.log` בתיקיית הנתונים, כולל excepthook גלובלי.

## מסד נתונים (11 טבלאות + FTS)

```
forums(name UNIQUE, color, url, profile_pattern, sort_order)     "כללי" מוגן ממחיקה
nicks(~26 עמודות)   ← זהו cache! הערך המוצג. מקור האמת ב-field_values
nick_contacts(nick_id, type, value, label, is_private)           CASCADE
nick_conflicts(nick_id, field_name, conflicting_value, ...)      CASCADE — כמעט vestigial, ר' למטה
nick_identities(a, b, UNIQUE)                                    קבוצות טרנזיטיביות מלאות (כל זוג נשמר)
settings(key, value)          display_* / forumio_* / conflict_policy / my_trust / import_manual_conflicts
sync_settings(field_key, synced)                                 אילו שדות מיוצאים בקובץ
import_sources(...)           לוג ייבואים ישן (לתאימות; גם import_log.txt ליד ה-DB)
shelved_values(...)           ערכים "על המדף" + promote_shelved (החלפה הפיכה)
sources(kind: me|scrape|import, trust 1-10, absolute)            id=1 = "אני" (trust 10), scrape=9
field_values(nick_id, field_name, value, source_id, UNIQUE שלישייה)  כל ערך שהגיע אי-פעם
nicks_fts(FTS5, unicode61 remove_diacritics 2) + 3 טריגרים       חיפוש; fallback ל-LIKE אם אין FTS5
```

WAL + foreign_keys ON. אינדקסים על username/forum/updated_at/trust_level/fk-ים.
מיגרציות: `_migrate()` מוסיף עמודות חסרות; `_backfill_sources()` חד-פעמי (דגל `backfill_sources_done`);
`_init_fts()` בונה מחדש אוטומטית סכימת FTS ישנה (מ-0.8.1 החיפוש כולל גם full_name ו-address —
`_SEARCH_COLS` הוא מקור האמת לעמודות החיפוש, גם ל-FTS וגם לנפילת ה-LIKE).

## מנוע המקורות — הלוגיקה המרכזית

- כל כתיבת ערך: `record_field_value(nick, field, value, source_id)` → upsert ל-`field_values` → הכרעה → עדכון ה-cache ב-`nicks`.
- **פנימיות (מ-0.8.1)**: `_upsert_field_value(conn,...)` + `_winner_for(field, rows)` + `_resolve_fields_conn(conn, nick, fields)` — כולן עובדות על חיבור קיים; ההכרעה המרובה מעדכנת כמה שדות ב-UPDATE אחד (חוסך גם שכתובי FTS, כי הטריגרים משכתבים את כל שורת ה-FTS בכל UPDATE). כתיבה חדשה בתפזורת? לעבוד דרכן על חיבור אחד, לא לפתוח חיבור פר-שדה.
- ניצחון: `absolute=1` → אינסוף; אחרת trust; שובר שוויון — `created_at` חדש יותר.
- **כללים מיוחדים ב-`resolve_field`:**
  - `reputation` — רק ערכי סריקה נחשבים, החדש ביותר מנצח.
  - `status` — מקור סריקה מקבל אמינות אבסולוטית (הרחקה בפורום גוברת על עריכה ידנית — **מכוון**; המשתמש לא יכול לדרוס סטטוס סרוק דרך הדיאלוג).
- `_NON_SOURCED` (לא במנוע): forum, username, source, trust_level, scraped_real_name, scraped_email, created_at, updated_at.
- ריקון שדה ידני = מחיקת התרומה של "אני" + הכרעה מחדש (הערך הבא באמינות עולה).
- עקיפות מפורשות: `force_field_value` (כתיבה ישירה ל-cache) — משמשת ב"סנכרן נבחרים" וב-`apply_import_conflict`.
- `update_source`/`delete_source` מריצים resolve מחדש לכל השדות המושפעים. absolute מותר רק ל"אני".

## סריקה (סנכרון לאינטרנט)

- **המסלול המהיר (מ-0.8.1)**: `db.merge_scraped_users(forum, pairs, label)` — עמוד שלם בחיבור וטרנזקציה אחת, עם זיהוי שינויים מול הערכים הקודמים של מקור הסריקה (סריקה חוזרת ללא שינוי כמעט לא כותבת; נמדד פי ~400 מהמסלול שדה-שדה). scraper.handle_users ממפה עמוד ואז קורא לזה.
- `_SCRAPE_MERGE_FIELDS`: groups, reputation, full_name, email, address, status, join_date, post_count, avatar_url, nick_color, avatar_image, extra_info, forum_uid. **בכוונה לא**: phone, real_name, notes, private_notes (פרטיות המשתמש).
- ניק חדש מסריקה: trust_level=4, source="NodeBB:<פורום>"; scraped_email מתעדכן גם במיזוג. מיובא מקובץ: trust_level=3.
- שלושה מצבים ב-main.py: `start_scrape` (פורום אחד), `start_scrape_all` (הכול ברצף, דילוג על כשל + skip ידני, התקדמות חיה מצטברת), `sync_selected_online` (נבחרים; הסרוק תמיד מנצח דרך `db.force_scraped_values` — חיבור אחד לניק).
- שגיאות הרשאה: `scraper.AuthRequired` (תת-מחלקה של ScrapeError) על 401/403 — `check_forum` מזהה דרכה דרישת התחברות ומציע עוגייה.
- מצב משותף ב-module globals: `_scrape_state` + `threading.Event` לביטול/דילוג. ה-UI סוקר ב-polling (`get_scrape_progress`, כל 700ms).
- KNOWN_FORUMS ב-database.py: 16 פורומים עם דגלים `needs_login` (המטבח) ו-`scrapable:False` (לתורה — לא NodeBB).
- נימוס: UA מזוהה, 0.6s בין עמודים, כיבוד Retry-After, עמוד שנכשל מדולג.

## ייבוא/ייצוא

- פורמט `.tiknick` (JSON): `{version:2, exported_at, exported_fields, nicks[]}`. רק שדות מסונכרנים (`sync_settings`) ורק פורומים שלא הוחרגו (`forumio_*`).
- זרימת ייבוא דו-שלבית: `load_import_file` (בדיקת פורומים זרים, נשמר ב-`self._pending_import`) → דיאלוג פרטי מקור (שם/הערות/trust) → מיפוי פורומים → `confirm_import`.
- התנגשות = ערך שונה בשדה מלא: אוטומטי לפי אמינות, או ידני אחד-אחד (`import_manual_conflicts=1`, עם "החל על הכול").

## עדכון עצמי

- `check_for_updates`: GitHub `releases/latest`, השוואת 3 מספרים, איתור נכס `.exe`.
- **כלל זהב: `APP_VERSION` (main.py:59) == tag בלי v** (0.8.0 == v0.8.0), אחרת הבדיקה נשברת.
- `download_update` → `TikNick_new.exe` ליד ה-EXE → `apply_update` כותב batch (ממתין לסגירה, מנקה משתני `_MEI*`/`_PYI*`, עד 15 ניסיונות move, מפעיל מחדש) → `os._exit(0)`.
- שחרור גרסה: עדכן APP_VERSION + version_info.txt → commit+push → `build.bat` → Release עם tag תואם + `dist\TikNick.exe` מצורף.

## app.js — מפה מהירה

- State גלובלי `S` (nicks, forums, multiSelected:Set, sortCol, loadToken נגד race), `COLS` (16 עמודות עם renderers), `DISPLAY`.
- גשר: `api(method, ...args)` גנרי + `waitForApi` (עד 10s).
- **טבלה = virtual scrolling** (רק השורות הנראות + spacers, `rowHeight` נמדד); **כרטיסים = טעינה הדרגתית** במנות של 120 בגלילה.
- דיאלוגים דרך `openModal(title, html, buttons, size)` — HTML נבנה כמחרוזות עם inline handlers; פונקציות מחוברות ל-`window.*` כשנדרש. `esc()` לכל ערך משתמש.
- תיוג `@ניק` בשדות `.tag-field`: רווחים→קו תחתון, השלמה אוטומטית, ריחוף, קליק פותח את הניק.
- מיון: `has_info` תמיד ראשון (גם במיון ידני). SQL ממיין `has_info DESC, trust_level DESC, updated_at DESC`.
- ניתוחים (סריקה/Chazonishnik/Stinknik) רצים ברקע עם באנר צף; חידוש polling אוטומטי אם רצים בעת טעינת הדף.
- דוחות מוצגים ב-iframe דרך `srcdoc`; שמירה דרך דיאלוג קובץ של pywebview.

## תשתית UI/עיצוב

- ערכות: dark (ברירת מחדל, פחם חם) / light (קרם) / system; 8 מבטאים (ברירת מחדל amber); צפיפות compact/normal/cozy — הכול CSS variables על `data-*` attributes, נשמר ב-settings.
- `user-select:none` גלובלי, film-grain overlay, אנימציות spring.

## מה נוסף ב-0.8.5 (2026-09-03) — ההצעות מניתוח הפערים

**ליבת המוצר — "מי זה מי":**
- **הצעות זהות אוטומטיות** (`suggest_identities`): GROUP BY על טלפון מנורמל / מייל / real_name / full_name (לא self-join — O(n) ולא O(n²)); מדלג על קבוצות שכולן כבר מקושרות (union-find דרך `_identity_groups_map`), על קבוצות באותו פורום בלבד, ועל זוגות שנדחו (`identity_dismissed`). UI: "🔗 הצעות זהות" עם קישור/דחייה בלחיצה.
- **פעולות מרובות**: `bulk_link_identities`, `bulk_move_forum` (bulk_update_field חוסם forum במכוון), `bulk_append_text` (מוסיף שורה להערות במקום לדרוס, ורושם תחת מקור "אני").

**תובנות:**
- **`field_history`** — טבלה חדשה; הרישום נעשה ב-`_resolve_fields_conn` (choke point יחיד לכל שינוי ערך מנצח), רק ל-`_HISTORY_FIELDS` (status/real_name/full_name/phone/email/address/groups — לא מוניטין/post_count שמשתנים כל הזמן). `_resolve_fields_bulk` **לא** רושם היסטוריה (פעולות מקור נוגעות במאות אלפי שורות). מוצג כציר זמן בדיאלוג הניק.
- **`scan_runs` + `scan_changes`** — `merge_scraped_users(..., run_id)` רושם ניקים חדשים ושינויים משמעותיים; `start_scan_run`/`finish_scan_run` ב-main. UI: "🕒 יומן סריקות" + toast עם "📋 מה השתנה" אחרי סריקה, כולל הדגשת הרחקות.
- **`get_stats`** — סה"כ/לפי פורום/מורחקים/עם מידע/זהויות/7 ימים אחרונים + קבוצות נפוצות. UI: "📊 סטטיסטיקות".

**חיפוש ושדות:**
- **חיפוש סלחני**: FTS הוא prefix-only ולכן "כהן" לא מצא "משהכהן". `_search_where(..., fuzzy=True)` מוסיף LIKE %term% — **רק** כשהחיפוש הרגיל החזיר פחות מ-5 תוצאות (סריקה מלאה יקרה).
- **`last_seen`** כשדה אמיתי (עמודה, סינון, ייצוא) — ממופה מ-`lastonline` ב-NodeBB ומ-`last_seen_at` ב-Discourse; קודם היה קבור כטקסט בתוך extra_info.
- **סינונים שמורים** (`saved_filters` ב-settings כ-JSON) — שמירה בשם והחלה בלחיצה מסרגל הסינון.

## שני באגים שבנימין דיווח (0.8.4) — שורש וסטטוס

1. **"שני תהליכים במקביל — Chazonishnik נעלם כשהפעלתי Stinknik"**: שלושת הבאנרים הצפים היו ממוקמים בדיוק באותו מקום (`bottom:16px;right:16px`), כך שהשני צייר על הראשון. **תוקן**: כולם בתוך `#bg-tasks` (flex column) ונערמים. שים לב שהמוניטורים עצמם (`_chzPoll`/`_stinkPoll`/`_scrapePoll`) תמיד היו עצמאיים — זו הייתה בעיה ויזואלית בלבד, והניתוח כן רץ ברקע.
2. **"Stinknik סרק רק אחוז מזערי מהפוסטים של לומדעס"**: נבדק מול השרת החי — הקוד **כן** עובר את כל העמודים (3,177 פוסטים מתוך 3,476 postcount, ~128 שניות, ללא עוגייה). שתי סיבות אמיתיות לפער שהמשתמש ראה: (א) בגרסה המשוחררת `_get_json` היה **בלי ריטריי**, וכל תקלת רשת/429 באמצע גרמה ל-`break` שקט שדווח כ"הושלם ✓" (תוקן ב-0.8.4 עם ריטריי + כיבוד Retry-After); (ב) ~300 פוסטים הם בקטגוריות שדורשות התחברות. **תוקן**: הסריקה מדווחת כעת בכנות — `postcount`, `partial`, `stopped_early`, `limited` חוזרים מ-`analyze_dislikes`/`analyze_user`, ה-toast אומר "נסרקו X מתוך Y" ומבחין בין "נעצר בגלל תקלת רשת" ל"השאר דורש התחברות", והדוח עצמו מציג "פוסטים שנסרקו מתוך Y". **לקח: אל תסמוך על `pagination.pageCount` של NodeBB בנתיב `/api/user/{slug}/posts` — הוא מחזיר 1 גם כשיש 170 עמודים; יש לעמוד עד עמוד ריק.**

## מה נוסף ב-0.8.4 (2026-09-02) — "חסרים הרבה דברים"

**מקור**: ניתוח פערי-מוצר (5 סוכנים, 38 הצעות; הרשימה המלאה ב-scratchpad של הסשן) + כל הפריטים שנותרו פתוחים מ-0.8.3.

**סל מחזור (`trash_nicks`)**: `delete_nicks` מצלם לכל ניק payload JSON מלא (השורה, contacts, identities, field_values, shelved, conflicts) ורק אז מוחק; מחזיר `{deleted, batch_id}`. `restore_trash(batch_id)` מחזיר עם **אותו id** (AUTOINCREMENT מבטיח שלא נוצל), מדלג על ניק שנוצר מחדש בינתיים, משחזר זהויות רק כששני הצדדים קיימים, וערכי מקורות רק אם המקור עדיין קיים. purge של 30 יום ב-`init_db`. ב-JS: `toast(msg,type,{actionLabel,onAction})` → "↩ בטל", ודיאלוג `openTrash()`.

**חיפוש**: `_search_where()` — FTS/LIKE על עמודות הניק **וגם** `nick_contacts.value`, **וגם** התאמת טלפון מנורמל (`_phone_norm_sql`, ווריאנטים 0…/972…). `search_nicks_for_lookup` באותה רוח.

**ממשק**: קישורי קשר (`contactMenu` — wa.me/tel:/mailto:/העתקה; `.contact-link[data-cval]` בהאצלה); `copy_to_clipboard` (ctypes, CF_UNICODETEXT — `navigator.clipboard` לא אמין ב-WebView); העתקת נבחרים כ-TSV ופרופיל מאוחד; `export_csv(mode, ids)` (utf-8-sig, `="0501…"` לאפסים מובילים) + `export_data(mode, ids)` עם מצבי `selected`/תצוגה; מקלדת (Ctrl+F, "/", Enter, חיצים, Delete, Esc); זיכרון `sort`/`last_search` ב-display settings; `updateSortIcons()`.

**תשתית**: ייבוא ב-thread (`_import_state`, `get_import_progress`, `runImport()`); פעולות מקור ב-thread (`_source_state`, `_run_source_op`, `waitSourceOp()`); `set_sync_settings`/`set_forum_io_flags`/`apply_import_conflicts` מרוכזים; `start_scrape_all(..., only_forums)` + `showSkippedForums()`; `last_scrape_<forum>` ב-settings + `get_last_scrapes`; `checkpoint()` בסגירת החלון + `journal_size_limit`; `db_health()`/`vacuum()`/`open_data_folder`/`open_log`; `backup_to`/`validate_backup`/`restore_from` (עותק בטיחות `.before-restore-*`); `_single_instance_or_exit` (mutex) ו-`_msgbox` בעברית ב-init_db כושל; עדכון עצמי ממתין לפי PID וכותב `update-failed.txt` (`consume_update_failure`); ריטריי ב-`_get_json` של Chazonishnik/Stinknik; חלון וירטואלי לכרטיסים (`measureCardsLayout`, `cardsSpacer`); אונבורדינג כשאין פורומים.

**מהניתוח — עדיין לא מומש (לפי ערך)**: הצעות זהות אוטומטיות (real_name/phone זהים בין פורומים); חיפוש תת-מחרוזת/סלחני בעברית; ציר זמן/היסטוריה לניק (field_values דורס created_at); דוח "מה השתנה בסריקה" + התראה על הרחקות; לוח סטטיסטיקות; ייבוא CSV; אנשי קשר וזהויות בפורמט .tiknick (גרסה 3); תצוגה מקדימה לייבוא; פעולות מרובות (קישור זהויות/העברת פורום/תיוג); סינונים שמורים; סריקה מתוזמנת; גיבוי אוטומטי יומי + לפני פעולות הרסניות; רוחב/סדר עמודות; פרופיל להדפסה; מפת זהויות.

## מה נוסף ב-0.8.3 (2026-09-02) — סריקת עומק

**מקור**: ביקורת רב-ממדית (6 סוכני קריאה-בלבד, 79 ממצאים) + מדידות על מאגר סינתטי של 20-40 אלף ניקים ועל ה-DB האמיתי של בנימין (88MB, 90k ניקים).

**ביצועים (הכי חשוב לזכור):**
- `get_connection()` הוא **thread-local ונשמר** (`_local`); מתחלף אוטומטית כש-`DB_PATH` משתנה. `with get_connection() as conn:` עדיין מבצע commit בסוף הבלוק — אבל עכשיו על חיבור משותף, כך שבלוקים מקוננים באותו thread חולקים טרנזקציה. פתיחת חיבור חדש לכל קריאה עלתה ~7ms.
- **רשימות (`get_all_nicks`/`filter_*`) לא מחזירות `avatar_image`** — רק `has_avatar`; התמונה נטענת ב-`get_avatars(ids)` רק לשורות המוצגות (`hydrateAvatars()` ב-JS, cache ב-`S.avatarCache`). `extra_info` נחתך ל-300 ברשימות בלבד (`_list_cols_sql`). זה הוריד את המטען לגשר מ-22.7MB ל-13MB על 20k.
- **אינדקס `idx_fv_nick_source(nick_id, source_id)` הוא קריטי**: בלעדיו המתכנן בחר ב-`idx_fv_source` ומקור הסריקה מחזיק כמעט את כל השורות → סריקה מלאה לכל משתמש (464ms/משתמש על ה-DB האמיתי). `PRAGMA optimize` רץ ב-`init_db`.
- `merge_scraped_users` שולף את הניקים הקיימים ואת ערכי הסריקה שלהם ב-**2 שאילתות לעמוד** (`_chunks` של 400), לא לכל משתמש.
- `_resolve_fields_conn` **מדלג על UPDATE כשהמנצח לא השתנה** (כל UPDATE על nicks משכתב את שורת ה-FTS). `_resolve_fields_bulk(conn, {nick:[fields]})` — 2 שאילתות ל-400 ניקים, משמש את `update_source`/`delete_source`.
- `import_data` כולו בחיבור אחד: טעינת קיימים במנות, `_upsert_field_value` + `_resolve_fields_conn` פעם אחת לניק.
- `delete_nicks`/`bulk_update_field` במנות של 400 (מגבלת פרמטרים של SQLite).
- `count_export_modes` סופר ב-SQL (`_HAS_INFO_SQL`/`_MY_INFO_SQL` — מקור אמת יחיד לתנאים).
- JS: `renderCards()` רק כש-`DISPLAY.view==='cards'`; `HE_COLLATOR` במקום `localeCompare` וללא מיון כש-`sortCol==='has_info'`; debounce+token ל-`applyFieldFilter` (מחזיר Promise), לתיוג `@` ולחיפוש זהויות; טולטיפים עם `ttBegin/ttValid`.

**אבטחה (RCE chain שנסגר):**
- דוחות Chazonishnik/Stinknik: iframe עם `sandbox="allow-scripts allow-popups"` (בלי allow-same-origin → אין גישה ל-`window.parent.pywebview.api`) + בריחה מלאה בתבניות (`_esc`, `_json_for_script` שמנטרל `</script>`).
- `openModal` מבצע `esc(title)`; `esc()` מנטרל גם `'`; `safeUrl()` לכל href/src ממקור פורום (רק http(s)/data:image); `applyAvatar` מאמת URL.
- handlers מוטבעים שנבנו משמות פורומים הוחלפו ב-`data-*` + האזנה מואצלת (`.known-add`, `.fmap-select`) — בריחת HTML לא מגינה על מחרוזת JS בתוך מאפיין.
- `download_update` מקבל רק https מ-github.com / githubusercontent.com; `_looks_like_inno_setup` מאמת התאמת סוג לפני `apply_update`.

**נכונות/יציבות:** `delete_nick`/`delete_nicks`/`bulk_update_field` מחזירים `{ok,error}`; ה-JS בודק ולא מדווח הצלחה על כישלון. `start_scrape_all`/`sync_selected_online` עם try/finally (אחרת `running` נתקע לנצח). הסורק סופר `failed_pages` ועוצר אחרי 5 כישלונות רצופים; ה-UI מציג "הסתיימה חלקית". `_map_user`: `_num_str` שומר 0 (ירידת מוניטין ל-0 מתעדכנת), תקרות ל-extra_info; במיזוג — הרחקה שבוטלה מנוקה ל"פעיל" רק אם הסריקה הקודמת רשמה "מורחק".

**UX:** מודאלים עם `opts.id`/`dismissable`; `_currentModalId` — מוניטורי הרקע סוגרים רק את החלון שלהם ושומרים `_lastReport` ("📄 הדוח האחרון"); דיאלוג הניק לא נסגר מרקע; `renderEmptyState` לפי חיפוש; `relativeTime` בעברית תקינה; `dir="ltr"` לשדות URL/מייל/מוניטין; `user-select:text` למשטחי ערכים; שם עוגייה לפי פלטפורמה (`#sync-cookie-name`); "סרוק הכל" משתמש **רק** בעוגיות שמורות פר-פורום (פרטיות).

**עדיין פתוח (מהביקורת, לא טופל):** כרטיסים גדלים בלי גבול בגלילה; ייבוא עדיין חוסם את ה-UI (מהיר, אבל בלי פס התקדמות); `update_source` ~10s על 40k ניקים (עם משוב, לא ברקע); עוגיות בטקסט גלוי ב-SQLite (DPAPI אפשרי); אין אימות חתימה על קובץ עדכון (רק allow-list של מארח + בדיקת סוג); רשימת הפורומים שדולגו ב"סרוק הכל" לא מוצגת בפירוט; הגדרות סנכרון מערבבות שמירה-מיידית ושמירה-בכפתור.

## מה נוסף ב-0.8.2 (2026-09-01)

- **סריקת Discourse** לצד NodeBB: `scraper.detect_platform` + dispatch ב-`scrape_forum`. פלטפורמות ללא API ציבורי (XenForo/phpBB/custom) מרימות `ScrapeError` ידידותית ולא נסרקות. `check_forum` מחזיר `platform` ושומר אותו לפורום.
- **רשימת פורומים מורחבת** (KNOWN_FORUMS ~24): נוספו NodeBB — ימות המשיח (f2.freeivr.co.il), נטפרי (forum.netfree.link), חרדים נעייס; ופלטפורמות לא-סריקות עם `platform` + `profile_pattern` — לתורה/פרוג/אוצר התורה (xenforo), אוצר החכמה/אייוועלט (phpbb), בחדרי חרדים (custom). **מקור פלטפורמה**: מחקר אמת שנעשה ב-0.8.2 (ראו למטה).
- **עוגיות נשמרות לפי origin** (טבלה `forum_cookies`): `db.get/save_cookie_for_url`, `db._origin`. נשמרות אוטומטית בסריקה/Chazonishnik/Stinknik, משמשות שוב אוטומטית, ומוצגות מראש בדיאלוגים. `start_scrape_all`/`sync_selected` משתמשים בעוגייה השמורה לכל פורום.
- **תצוגת משתמש מאוחדת** (feature): `db.get_merged_profile(nick_id)` + `search_nicks_for_lookup` → כפתור "🔎 תצוגת משתמש", מרכז מידע מכל קבוצת הזהות.
- **מצבי ייצוא**: `export_data(mode)` + `count_export_modes` — all / has_info / my_info. דיאלוג בורר עם ספירות.
- **הגבלת כמות**: `max_posts` ל-Chazonishnik/Stinknik (זמן ריצה), `max_pages` בממשק הסנכרון.
- **גרסת אינסטולר** לצד ניידת: `installer.iss` (Inno Setup, per-user, ללא UAC) + `build_installer.bat` → `dist\TikNick-Setup.exe`. `_install_type()` מזהה לפי `install-type.txt` ליד ה-EXE (מותקן ע"י האינסטולר). עדכון עצמי בוחר נכס לפי סוג: ניידת→EXE, מותקנת→Setup (מריץ `/SILENT`). כלל שמות נכסי Release: שם המכיל "setup"/"install" = אינסטולר.
- **תיקון חלוניות צפות איטיות**: guard נגד polls חופפים + `_yieldPaint()` לפני `loadNicks` הכבד — הבאנר נעלם מיד.
- פלטפורמה+תבנית-פרופיל זורמות דרך `resolve_forum_data`/`add_forum`; `buildProfileUrl(forum,...)` ב-JS בונה לינק לפי פלטפורמה/תבנית.
- **אבטחה (ביקורת אדוורסרית)**: ערכים סרוקים (`nick_color`, `avatar_image`) הם קלט לא-בטוח מהפורום — כל הזרקה ל-innerHTML עוברת `esc()` (renderMergedProfile, דיאלוג הניק, כרטיסים). כלל: **לעולם לא לשרשר ערך שמקורו בפורום ל-innerHTML בלי esc**.
- תיקוני ביקורת: `stinknik._resolve_slug` מנסה וריאציות סלאג (שמות עם רווח נפתרים); `detect_platform` בודק Discourse לפני שמסיק NodeBB מ-401/403; עדכון עצמי בוחר נכס בהתאמה קפדנית (ניידת↔EXE, מותקנת↔Setup — בלי fallback חוצה-סוגים); `start_scrape` מאפס מצב רב-פורומי; `sync_selected` בחיבור DB אחד עם cache עוגיות.

## מחקר פלטפורמות הפורומים (2026-09-01, אימות חי)

| פורום | URL | פלטפורמה | סריקה? |
|---|---|---|---|
| מתמחים טופ / בינה / קהילה וכו' | (קיימים) | NodeBB | ✅ |
| ימות המשיח | f2.freeivr.co.il | NodeBB (13,576 משתמשים) | ✅ |
| נטפרי | forum.netfree.link | NodeBB (לעיתים במצב תחזוקה 503) | ✅ |
| חרדים נעייס | charedim-neyes.onrender.com | NodeBB (Render — נרדם, מתעורר לאט) | ✅ |
| לתורה / פרוג / אוצר התורה | tora-forum / prog.co.il / forum-otzar-hatorah | **XenForo** (REST דורש API key) | ❌ |
| אוצר החכמה / אייוועלט / אידטיש | forum.otzar.org / ivelt.com / yidtish | **phpBB** (memberlist HTML בלבד) | ❌ |
| בחדרי חרדים | forums.bhol.co.il | ASP ייחודי | ❌ |
| קדם (נשים) | kedemcenter.co.il | WordPress+BuddyBoss (יש `/wp-json/buddyboss/v1/members`) | לא נוסף |

**למה "לתורה" לא הסתנכרן**: הוא XenForo, וה-REST של XenForo דורש `XF-Api-Key`. אין דרך לספור/למשוך את כל המשתמשים בלי מפתח או session מאומת — לכן אין סריקה אוטומטית (מסומן במפורש בממשק).

## מה תוקן ב-0.8.1 (2026-09-01)

- **האצת סריקה פי ~400**: `merge_scraped_users` (עמוד = טרנזקציה אחת + זיהוי שינויים), `_resolve_fields_conn` (הכרעה מרובה ב-UPDATE אחד), `force_scraped_values` לסנכרון נבחרים. נבדק: 300 משתמשים × 9 שדות — ‎38.5s → ‎0.1s.
- **חיפוש**: full_name ו-address נוספו לחיפוש המהיר (FTS + LIKE); מיגרציית FTS אוטומטית ל-DB קיים.
- **זרימת ההתנגשויות המתה הוסרה**: אין עוד conflict_policy, פותר גלובלי, `apply_conflict`/`resolve_all_conflicts`. נשאר: `nick_conflicts` לצפייה/סגירה בדיאלוג הניק (legacy), ומדיניות ייבוא ידני (`import_manual_conflicts`).
- Chazonishnik: Chart.js מוטמע (אופליין), בורר פורום, עוגייה אופציונלית.
- `check_forum` מזהה דרישת התחברות דרך `AuthRequired` (הענף המת תוקן).
- ייבוא ידני: תוקן N+1 (‎snapshot אחד לניק).
- קוסמטיקה: footer מקבל גרסה מ-`get_app_version` בהפעלה (גם אופליין); הוסרו סימוני גרסה סטטיים מ-app.js/style.css/build.bat; `upload_to_github.bat` נמחק (remote ישן ומסוכן).

## פינות ידועות שנשארו

1. גיט: commit יחיד squashed; זהות `BeniaBot` / `b0554003794@gmail.com`.
2. `get_nicks` מחזיר את כל העמודות כולל `avatar_image` (base64) לכל הרשימה — כבד כשיש הרבה אווטארים; מועמד לעתיד (להחזיר בלי אווטאר ולהשלים lazy).
3. `import_data` עדיין פותח חיבור פר-ערך דרך `record_field_value` — עובד, אבל אפשר להעביר לאותו דפוס batching אם ייבואים גדולים יאטו.
4. הוראות העוגייה ב-Chazonishnik מזכירות את mitmachim כדוגמה קשיחה בטקסט ההדרכה.

## פקודות

```
python main.py        # הרצה מהמקור (או הפעל.bat)
build.bat             # EXE → dist\TikNick.exe
```

**בדיקות (מ-0.8.3):** `python tests/run_all.py` (או `run_tests.bat`) — 6 חבילות, ~80 בדיקות על database/scraper/API (DB זמני, בלי רשת, ~1 דקה). `tests/bench_scale.py` ו-`tests/bench_critical.py` הם בנצ'מרקים על מאגר סינתטי גדול (20-40k ניקים) — להריץ לפני/אחרי כל שינוי במסלולי ה-DB החמים. אין linter; `node --check web/app.js` + `python -m py_compile` לתחביר. **אין בדיקות UI** — ה-JS מאומת בקריאה ובביקורת בלבד.

## עקרונות עבודה

- כל הטקסט למשתמש בעברית; הקוד והלוגים באנגלית/מעורב כמו הקיים.
- הוספת יכולת = method ב-`class API` + קריאת `api('...')` ב-app.js. אין framework — vanilla הכול.
- פרטיות היא ערך מוצר: private_notes/avatar_image לא מסונכרנים בברירת מחדל, סריקה לא נוגעת בשדות אישיים, הכול מקומי.
- אל תשבור את פורמט `.tiknick` בלי bump ל-version בפורמט + תאימות לאחור.
- זהירות ב-SQL דינמי: שמות שדות רק מרשימות לבנות (`_NICK_FIELDS`, `_FILTERABLE_KEYS`) — לשמור על הדפוס.
