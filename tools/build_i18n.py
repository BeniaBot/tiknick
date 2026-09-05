# -*- coding: utf-8 -*-
"""
בונה את web/i18n.js מתוך קטלוג התרגום.

הקטלוג (_catalog.json) הוא רשימת {he, en, kind}. "static" הוא טקסט קבוע,
"pattern" הוא טקסט שמכיל ערכים מוטמעים בזמן ריצה ומסומנים {1}, {2}...

למה קטלוג ולא t() בכל אתר קריאה: הממשק בנוי כמחרוזות HTML שמורכבות בזמן ריצה
בכ-1200 מקומות. מעבר ל-t() בכל אחד מהם הוא שכתוב של כל הקובץ. במקום זה
i18n.js מתרגם את ה-DOM אחרי שהוא נבנה — אותה תוצאה, בלי לגעת בקוד שמייצר אותו.
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def js_str(s):
    """מחרוזת JS בטוחה — json.dumps מברֵח כבר את כל מה שצריך."""
    return json.dumps(s, ensure_ascii=False)


def to_regex(he):
    """'📊 {1} ניקים' -> '^📊\\ (.+?)\\ ניקים$' עם בריחה מלאה של השאר."""
    parts = re.split(r"\{(\d+)\}", he)
    out, order = [], []
    for i, part in enumerate(parts):
        if i % 2 == 1:            # מספר הסוגר
            order.append(int(part))
            out.append("([\\s\\S]*?)")
        else:
            out.append(re.escape(part))
    return "^" + "".join(out) + "$", order


def build(catalog):
    static = {}
    patterns = []
    for e in catalog:
        he, en = (e.get("he") or "").strip(), (e.get("en") or "").strip()
        if not he or not en or he == en:
            continue
        if e.get("kind") == "pattern" and "{" in he:
            rx, order = to_regex(he)
            # ההחלפה באנגלית ממופה לפי מספר הסוגר, לא לפי מיקום — הסדר
            # באנגלית שונה לעיתים קרובות מהעברית, וזה תקין.
            def sub(m):
                return "$" + str(order.index(int(m.group(1))) + 1)
            rep = re.sub(r"\{(\d+)\}", sub, en)
            if all(int(n) in order for n in re.findall(r"\{(\d+)\}", en)):
                patterns.append((rx, rep, len(he)))
        else:
            static[he] = en

    # תבניות ארוכות קודם: "נשמרו {1} ניקים מתוך {2}" חייבת להיבדק לפני
    # תבנית קצרה יותר שהיא תת-קבוצה שלה.
    patterns.sort(key=lambda p: -p[2])

    lines = []
    lines.append("// ═══ נוצר אוטומטית ע\"י tools/build_i18n.py — אין לערוך ביד ═══")
    lines.append("// %d מחרוזות קבועות, %d תבניות." % (len(static), len(patterns)))
    lines.append("const I18N_EN = {")
    for he in sorted(static, key=lambda k: (-len(k), k)):
        lines.append("  %s: %s," % (js_str(he), js_str(static[he])))
    lines.append("};")
    lines.append("")
    # מפתח שני לפי רווחים מנורמלים: אותה פסקה ב-HTML מגיעה עם שבירות שורה
    # והזחה, ולכן ההשוואה המדויקת מחמיצה אותה.
    lines.append("const I18N_EN_NORM = {")
    seen = set()
    for he in sorted(static, key=lambda k: (-len(k), k)):
        n = " ".join(he.split())
        if n != he and n not in seen:
            seen.add(n)
            lines.append("  %s: %s," % (js_str(n), js_str(static[he])))
    lines.append("};")
    lines.append("")
    lines.append("const I18N_EN_PAT = [")
    for rx, rep, _ in patterns:
        lines.append("  [%s, %s]," % (js_str(rx), js_str(rep)))
    lines.append("];")
    return "\n".join(lines), len(static), len(patterns)


RUNTIME = r"""

// ── המנוע ────────────────────────────────────────────────────────────────
// התרגום נעשה על ה-DOM אחרי הבנייה ולא במקור, כי הממשק מורכב כמחרוזות HTML
// בכ-1200 מקומות. כשהשפה עברית שום דבר כאן לא רץ — אפילו לא ה-observer.
let I18N_LANG = 'he';
let _i18nObserver = null;
const _i18nRx = I18N_EN_PAT.map(p => [new RegExp(p[0]), p[1]]);

// אזורים שמכילים נתונים של המשתמש ושל הפורומים ולא ממשק. ניק ששמו במקרה
// "ייצוא" לא אמור להפוך ל-"Export".
const I18N_SKIP = 'INPUT,TEXTAREA,SCRIPT,STYLE,IFRAME,CODE';

function i18nText(s) {
  const t = s.trim();
  if (t.length < 2) return null;
  const hit = I18N_EN[t];
  if (hit !== undefined) return s.replace(t, hit);
  const n = t.replace(/\s+/g, ' ');
  const hit2 = I18N_EN[n] !== undefined ? I18N_EN[n] : I18N_EN_NORM[n];
  if (hit2 !== undefined) return s.replace(t, hit2);
  // בדיקת תבניות רק אם יש כאן בכלל אות עברית — חוסך מעבר על מספרים ותאריכים
  if (!/[֐-׿]/.test(t)) return null;
  for (let i = 0; i < _i18nRx.length; i++) {
    const m = t.match(_i18nRx[i][0]);
    if (m) return s.replace(t, t.replace(_i18nRx[i][0], _i18nRx[i][1]));
  }
  return null;
}

function i18nNode(node) {
  const p = node.parentElement;
  if (!p || p.closest(I18N_SKIP) || p.closest('[data-no-i18n]')) return;
  const out = i18nText(node.nodeValue || '');
  if (out !== null) node.nodeValue = out;
}

function i18nAttrs(el) {
  if (el.closest('[data-no-i18n]')) return;
  for (const a of ['placeholder', 'title', 'aria-label']) {
    const v = el.getAttribute && el.getAttribute(a);
    if (!v) continue;
    const out = i18nText(v);
    if (out !== null) el.setAttribute(a, out);
  }
}

function i18nTree(root) {
  if (I18N_LANG !== 'en' || !root) return;
  if (root.nodeType === 3) { i18nNode(root); return; }
  if (root.nodeType !== 1 && root.nodeType !== 9) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  texts.forEach(i18nNode);
  i18nBlocks(root);
  if (root.nodeType === 1) i18nAttrs(root);
  root.querySelectorAll('[placeholder],[title],[aria-label]').forEach(i18nAttrs);
}

// פסקה שיש בתוכה <b> או <code> מפוצלת לכמה צמתי טקסט, וכל אחד מהם לבדו אינו
// מפתח בקטלוג. כאן משווים את הטקסט של האלמנט כולו — אבל רק כשאין בתוכו שום
// דבר אינטראקטיבי, כדי לא למחוק onclick או id.
const I18N_BLOCKS = 'p,li,label,summary,div,span,b,small';

function i18nBlocks(root) {
  if (root.nodeType !== 1 && root.nodeType !== 9) return;
  const list = root.querySelectorAll ? root.querySelectorAll(I18N_BLOCKS) : [];
  for (const el of list) {
    if (el.dataset && el.dataset.i18nDone) continue;
    if (el.closest('[data-no-i18n]') || el.closest(I18N_SKIP)) continue;
    if (el.querySelector('[onclick],[id],a,button,input,select,textarea,iframe')) continue;
    const txt = (el.textContent || '').trim().replace(/\s+/g, ' ');
    if (txt.length < 4 || !/[֐-׿]/.test(txt)) continue;
    const hit = I18N_EN[txt] !== undefined ? I18N_EN[txt] : I18N_EN_NORM[txt];
    if (hit === undefined) continue;
    el.textContent = hit;          // ההדגשות הפנימיות נמסרות תמורת תרגום שלם
    if (el.dataset) el.dataset.i18nDone = '1';
  }
}

function i18nStart() {
  if (_i18nObserver) return;
  i18nTree(document.body);
  // כל הדיאלוגים, הטבלה והטוסטים נבנים אחרי הטעינה, ולכן צריך מעקב מתמשך
  // ולא מעבר חד-פעמי. ה-observer קיים רק במצב אנגלית.
  _i18nObserver = new MutationObserver(muts => {
    for (const m of muts) {
      if (m.type === 'attributes' && m.target) i18nAttrs(m.target);
      m.addedNodes && m.addedNodes.forEach(n => i18nTree(n));
    }
  });
  _i18nObserver.observe(document.body, {
    childList: true, subtree: true, characterData: false,
    attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label'],
  });
}

function i18nStop() {
  if (_i18nObserver) { _i18nObserver.disconnect(); _i18nObserver = null; }
}

// החלפת שפה דורשת בנייה מחדש של המסך — אי אפשר "לתרגם חזרה" טקסט שכבר הוחלף.
function applyLang(lang) {
  I18N_LANG = (lang === 'en') ? 'en' : 'he';
  document.documentElement.setAttribute('data-lang', I18N_LANG);
  document.documentElement.setAttribute('dir', I18N_LANG === 'en' ? 'ltr' : 'rtl');
  if (I18N_LANG === 'en') i18nStart(); else i18nStop();
}

// תרגום מחרוזת בודדת מקוד — לשימוש במקומות שלא עוברים דרך ה-DOM
function tt(s) {
  if (I18N_LANG !== 'en') return s;
  const out = i18nText(s);
  return out === null ? s : out;
}
"""


def main():
    cat_path = os.path.join(ROOT, "i18n_catalog.json")
    if not os.path.exists(cat_path):
        print("missing i18n_catalog.json", file=sys.stderr)
        return 1
    catalog = json.load(io.open(cat_path, encoding="utf-8"))
    # תוספות שנכתבו אחרי מעבר החילוץ — הן גוברות על הקטלוג באותו מפתח
    extra_path = os.path.join(ROOT, "i18n_extra.json")
    if os.path.exists(extra_path):
        catalog += json.load(io.open(extra_path, encoding="utf-8"))
    body, n_static, n_pat = build(catalog)
    out = os.path.join(ROOT, "web", "i18n.js")
    io.open(out, "w", encoding="utf-8").write(body + "\n" + RUNTIME)
    print("wrote %s — %d static, %d patterns" % (out, n_static, n_pat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
