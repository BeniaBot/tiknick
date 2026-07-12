<div align="right" dir="rtl">

# 📋 Tik-Nick

**תוכנת דסקטופ לניהול ומעקב אחר ניקים (שמות משתמש) בפורומים חרדיים.**

[![Version](https://img.shields.io/badge/גרסה-0.2-f59e0b?style=flat-square)](https://github.com)
[![Platform](https://img.shields.io/badge/פלטפורמה-Windows%2010%2F11-blue?style=flat-square)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)

---

## ✨ יכולות עיקריות

- 🔍 **ניהול ניקים** — פורום, שם משתמש, שם אמיתי, טלפון, מייל, כתובת, קבוצות, מוניטין, סטטוס
- 📞 **פרטי קשר מרובים** — טלפונים ומיילים נוספים, עם סימון סודי/גלוי ועריכה מלאה
- 👤 **זהויות כפולות** — קישור ניקים שהם אותו אדם
- 🎨 **מראה ניק** — צבע מותאם אישית או תמונת פרופיל
- 🏛️ **ניהול פורומים** — 15 פורומים חרדיים מוכרים מובנים עם קישורים
- 🔗 **פתיחת פרופיל** — לחיצה אחת פותחת את פרופיל הניק בדפדפן
- 📤 **ייצוא / ייבוא** — עם מיפוי פורומים חכם וזיהוי התנגשויות
- 🎨 **הגדרות תצוגה** — כהה / בהיר / מערכת, 8 צבעי מבטא, טבלה / כרטיסים, צפיפות
- 🔒 **כספת פרטיות** — שליטה מלאה על אילו שדות מסונכרנים בייצוא

---

## 🚀 הפעלה מהירה

### הרצה מהמקור
```bash
pip install pywebview
python main.py
```

### קימפול ל-EXE עצמאי
```bash
# Windows — לחץ פעמיים על:
build.bat
```
הקובץ `dist\TikNick.exe` ירוץ על כל Windows 10/11 **ללא התקנת Python**.

---

## 📁 מבנה הפרויקט

```
tiknick/
├── main.py              # Backend + PyWebView
├── database.py          # SQLite logic
├── web/
│   ├── index.html       # UI structure
│   ├── style.css        # Modern dark/light theme
│   └── app.js           # Frontend logic
├── TikNick.spec         # PyInstaller build config
├── icon.ico             # App icon (multi-resolution)
├── version_info.txt     # Windows EXE metadata
├── build.bat            # One-click build script
└── הפעל.bat            # Run from source (Windows)
```

---

## 🛠️ דרישות

| כלי | גרסה |
|-----|-------|
| Python | 3.8+ |
| pywebview | 4.4+ |
| PyInstaller | (לקימפול בלבד) |

---

## 📸 צילומי מסך

*בקרוב*

---

## 🔮 מה הולך לבוא (v0.2)

- 📖 **Chazonishnik** — *בפיתוח*
- 🦨 **Stinknik** — *בפיתוח*
- 🤖 סריקת פורום אוטומטית

---

## 📄 רישיון

שימוש אישי בלבד.

</div>
