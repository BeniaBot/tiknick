// 0.8.21 — מתי "@" הוא תיוג ומתי הוא מייל.
// בנימין דיווח: "כל פעם שכותבים מייל של מישהו התוכנה חושבת שמנסים לתייג ניק
// בשם גימייל נקודה קום". הכלל היה `@` בכל מקום; עכשיו תיוג פותח מילה, ומה
// שנראה כמו דומיין לעולם אינו ניק. שתי נקודות חייבות להסכים — ההקלדה
// (ההשלמה האוטומטית) והתצוגה (הטקסט השמור) — ולכן שתיהן נבדקות מאותו מקור.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');

function grab(re, what) {
  const m = src.match(re);
  if (!m) throw new Error('not found in app.js: ' + what);
  return m[0];
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(
  grab(/\nfunction esc\(s\)[\s\S]*?\n\}/, 'esc') + '\n' +
  grab(/const TAG_OPEN = [^\n]*\n/, 'TAG_OPEN') +
  grab(/const TAG_DOMAIN_RX = [^\n]*\n/, 'TAG_DOMAIN_RX') +
  grab(/\nfunction tagCandidate\([\s\S]*?\n\}/, 'tagCandidate') + '\n' +
  grab(/\nfunction renderTaggedText\([\s\S]*?\n\}/, 'renderTaggedText') +
  // const בתוך vm אינו נחשף על אובייקט ההקשר — רק var ופונקציות
  '\nthis.TAG_OPEN = TAG_OPEN; this.tagCandidate = tagCandidate;' +
  '\nthis.renderTaggedText = renderTaggedText;',
  sandbox);

let fails = [];
function ok(name, cond, detail) {
  console.log((cond ? 'PASS  ' : 'FAIL  ') + name + (!cond && detail ? '  [' + detail + ']' : ''));
  if (!cond) fails.push(name);
}

// ── התצוגה: אילו קטעים הופכים לתג ──────────────────────────────────────
function tagsIn(text) {
  const html = sandbox.renderTaggedText(text);
  const out = [];
  const re = /data-tag="([^"]*)"/g;
  let m;
  // ערך המאפיין מוברח — משווים אחרי פענוח, כמו שהדפדפן נותן ב-dataset
  while ((m = re.exec(html)) !== null) {
    out.push(m[1].replace(/&quot;/g, '"').replace(/&#39;/g, "'")
                 .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&'));
  }
  return out;
}

ok('מייל אינו תיוג', tagsIn('שלח ל beni@gmail.com תודה').length === 0,
   JSON.stringify(tagsIn('שלח ל beni@gmail.com תודה')));
ok('מייל עם תת-דומיין אינו תיוג', tagsIn('david.cohen@walla.co.il').length === 0);
ok('מייל בתחילת שורה אינו תיוג', tagsIn('a@b.co הוא המייל').length === 0);
ok('תיוג רגיל עובד', tagsIn('דבר עם @בנימין בנוגע')[0] === 'בנימין');
ok('תיוג בתחילת טקסט', tagsIn('@דוד בבקשה')[0] === 'דוד');
ok('תיוג אחרי סוגר', tagsIn('(@דוד) אמר')[0] === 'דוד');
ok('פיסוק סוגר אינו חלק מהשם', tagsIn('שאל את @דוד.')[0] === 'דוד');
ok('גרשיים כן חלק מהשם', tagsIn('שאל את @ע"ה')[0] === 'ע"ה');
ok('מייל ותיוג באותה שורה', JSON.stringify(tagsIn('מייל a@b.co ותיוג @דוד')) ===
   JSON.stringify(['דוד']));
ok('שם עם קו תחתון מוצג עם רווח',
   sandbox.renderTaggedText('@משה_כהן').includes('>@<bdi>משה כהן</bdi>'));

// ── טקסט שאינו תג נשאר בדיוק כפי שהוא, ומוברח ─────────────────────────
ok('המייל נשאר קריא בטקסט',
   sandbox.renderTaggedText('שלח ל beni@gmail.com').includes('beni@gmail.com'));
ok('HTML מוברח', sandbox.renderTaggedText('<img src=x>').indexOf('&lt;img') === 0);
ok('גרשיים בשם התג מוברחות במאפיין',
   sandbox.renderTaggedText('@ע"ה').includes('data-tag="ע&quot;ה"'));

// ── ההקלדה: אותו כלל בדיוק ────────────────────────────────────────────
const typeRx = new RegExp(sandbox.TAG_OPEN + '@([^\\s@]{1,30})$');
function typed(s) {
  const m = s.match(typeRx);
  return (m && sandbox.tagCandidate(m[1])) ? m[1] : null;
}
ok('הקלדת מייל לא פותחת השלמה', typed('שלח ל beni@gmail') === null);
ok('הקלדת מייל שלם לא פותחת השלמה', typed('beni@gmail.com') === null);
ok('הקלדת תיוג כן פותחת השלמה', typed('דבר עם @בני') === 'בני');
ok('תיוג בתחילת שדה', typed('@דוד') === 'דוד');
ok('@ בודד לא פותח כלום', typed('שלום @') === null);

console.log('');
if (fails.length) { console.log('FAILED: ' + fails.join(', ')); process.exit(1); }
console.log('TAG TESTS PASSED');
