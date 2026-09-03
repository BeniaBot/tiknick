// 0.8.9 — פריסת עמודות: טעינה סלחנית, הזזה, וגיאומטריית RTL.
// אין תשתית בדיקות ל-JS, ולכן הבדיקה שולפת את הפונקציות הטהורות מ-app.js
// ומריצה אותן בארגז חול. שגיאת סימן ב-RTL היא בדיוק סוג הבאג שקריאה מפספסת:
// עמודה שמצטמצמת כשגוררים אותה רחבה יותר נראית "כמעט נכון".
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');

function grab(name) {
  const re = new RegExp('\\nfunction ' + name + '\\s*\\([\\s\\S]*?\\n\\}', 'm');
  const m = src.match(re);
  if (!m) throw new Error('function not found in app.js: ' + name);
  return m[0];
}

const COLS = [
  { key: 'forum', label: 'פורום', width: 110 },
  { key: 'username', label: 'שם משתמש', width: 145 },
  { key: 'phone', label: 'טלפון', width: 115 },
  { key: 'notes', label: 'הערות', width: 180 },
];

const sandbox = {
  COLS,
  MIN_COL_W: 46,
  MAX_COL_W: 640,
  COL_LAYOUT: { order: null, w: {} },
  DISPLAY: { hidden_cols: '' },
  console,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(
  [grab('loadColLayout'), grab('orderedCols'), grab('visibleCols'),
   grab('hiddenColsSet'), grab('applyColMove'), grab('dropIndexAt'),
   grab('colWidth')].join('\n'),
  sandbox);

let fails = [];
function ok(name, cond, detail) {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (!cond && detail ? '  [' + detail + ']' : ''));
  if (!cond) fails.push(name);
}
const keys = () => sandbox.orderedCols().map(c => c.key);

// ── טעינה סלחנית ──────────────────────────────────────────────────────
sandbox.loadColLayout('');
ok('קלט ריק → ברירת מחדל', sandbox.COL_LAYOUT.order === null &&
   JSON.stringify(keys()) === JSON.stringify(COLS.map(c => c.key)));

for (const bad of ['{not json', 'null', '[]', '"str"', '17']) {
  sandbox.loadColLayout(bad);
  ok('קלט פגום לא מפיל: ' + bad, sandbox.COL_LAYOUT.order === null && keys().length === 4);
}

sandbox.loadColLayout(JSON.stringify({ order: ['notes', 'forum'] }));
ok('עמודות חסרות מתווספות בסוף, פעם אחת',
   JSON.stringify(keys()) === JSON.stringify(['notes', 'forum', 'username', 'phone']), keys().join(','));

sandbox.loadColLayout(JSON.stringify({ order: ['ghost', 'phone', 'phone', 'forum'] }));
ok('שם לא מוכר וכפילות נזרקים',
   JSON.stringify(keys()) === JSON.stringify(['phone', 'forum', 'username', 'notes']), keys().join(','));
ok('אין ערך undefined בסדר', sandbox.orderedCols().every(Boolean));

sandbox.loadColLayout(JSON.stringify({ w: { username: 5, phone: 99999, ghost: 100 } }));
ok('רוחב נצמד לטווח',
   sandbox.COL_LAYOUT.w.username === 46 && sandbox.COL_LAYOUT.w.phone === 640,
   JSON.stringify(sandbox.COL_LAYOUT.w));
ok('רוחב לעמודה לא מוכרת נזרק', !('ghost' in sandbox.COL_LAYOUT.w));

// ── הזזה ──────────────────────────────────────────────────────────────
sandbox.loadColLayout('');
sandbox.COL_LAYOUT.order = COLS.map(c => c.key);
sandbox.applyColMove('phone', 0);
ok('הזזה לתחילת הסדר',
   JSON.stringify(keys()) === JSON.stringify(['phone', 'forum', 'username', 'notes']), keys().join(','));

sandbox.COL_LAYOUT.order = COLS.map(c => c.key);
const before = keys().join(',');
sandbox.applyColMove('username', 1);
ok('הזזה למקום הנוכחי לא משנה כלום (from)', keys().join(',') === before, keys().join(','));
sandbox.applyColMove('username', 2);
ok('הזזה למקום הנוכחי לא משנה כלום (from+1)', keys().join(',') === before, keys().join(','));

sandbox.COL_LAYOUT.order = COLS.map(c => c.key);
sandbox.applyColMove('forum', 4);
ok('הזזה לסוף', keys()[3] === 'forum', keys().join(','));
ok('אף עמודה לא אבדה בהזזות', new Set(keys()).size === 4 && keys().length === 4);

// עמודה מוסתרת שומרת על מקומה היחסי
sandbox.COL_LAYOUT.order = COLS.map(c => c.key);
sandbox.DISPLAY.hidden_cols = 'notes';
ok('מוסתרת לא מופיעה בנראות', sandbox.visibleCols().map(c => c.key).join(',') === 'forum,username,phone');
sandbox.applyColMove('phone', 0);
sandbox.DISPLAY.hidden_cols = '';
ok('הסתרה והחזרה שומרות על הסדר המלא',
   new Set(keys()).size === 4 && keys().includes('notes'), keys().join(','));

// ── גיאומטריית RTL ────────────────────────────────────────────────────
// ths[0] הוא הימני ביותר. מלבנים: [700..800], [600..700], [500..600]
const ths = [
  { getBoundingClientRect: () => ({ left: 700, right: 800, width: 100, top: 0, height: 20 }) },
  { getBoundingClientRect: () => ({ left: 600, right: 700, width: 100, top: 0, height: 20 }) },
  { getBoundingClientRect: () => ({ left: 500, right: 600, width: 100, top: 0, height: 20 }) },
];
ok('מצביע מימין לכולן → 0', sandbox.dropIndexAt(ths, 790) === 0, String(sandbox.dropIndexAt(ths, 790)));
ok('בין המרכזים של 1 ו-2 → 2', sandbox.dropIndexAt(ths, 620) === 2, String(sandbox.dropIndexAt(ths, 620)));
ok('משמאל לכולן → הסוף', sandbox.dropIndexAt(ths, 400) === 3, String(sandbox.dropIndexAt(ths, 400)));

// סימן שינוי הרוחב: הידית על הקצה השמאלי, גרירה שמאלה = רחב יותר
const resize = (startX, startW, clientX) =>
  Math.max(46, Math.min(640, Math.round(startW + (startX - clientX))));
ok('גרירה שמאלה מרחיבה', resize(800, 140, 760) === 180, String(resize(800, 140, 760)));
ok('גרירה ימינה מצרה', resize(800, 140, 840) === 100, String(resize(800, 140, 840)));
ok('לא יורד מתחת למינימום', resize(800, 140, 2000) === 46);
ok('לא עולה מעל המקסימום', resize(800, 140, -2000) === 640);

// ── רוחב אפקטיבי ──────────────────────────────────────────────────────
sandbox.loadColLayout(JSON.stringify({ w: { phone: 200 } }));
ok('רוחב שנקבע גובר', sandbox.colWidth({ key: 'phone', width: 115 }) === 200);
ok('אחרת ברירת המחדל', sandbox.colWidth({ key: 'forum', width: 110 }) === 110);

console.log('');
if (fails.length) { console.log('FAILED: ' + fails.join(', ')); process.exit(1); }
console.log('COLUMN TESTS PASSED');
