/* Tik-Nick — app.js (הגרסה נקבעת ב-main.py בלבד: APP_VERSION) */
'use strict';

// ══ STATE ═══════════════════════════════════════════════════════════
const S = {
  nicks:       [],
  forums:      [],
  forumColors: {},
  selectedId:  null,
  searchTimer: null,
  sortCol:     'has_info',
  sortDir:     -1,
  total:       0,
  currentSearch: '',
  // הגנה מפני תשובות חיפוש שמגיעות מאוחר מדי (race condition)
  loadToken:   0,
  // בחירה מרובה למחיקה בפועל
  multiSelected: new Set(),
  // Virtual scrolling — טבלה: רק השורות שבתצוגה נבנות ב-DOM, לא הכל.
  rowHeight:   36,
  vRange:      { start: 0, end: 0 },
  // כרטיסים: גדילה הדרגתית תוך גלילה (ללא כפתור), ללא הסרה כדי לשמור על פשטות
  cardsRendered: 0,
  cardsChunk:  120,
  // תמונות פרופיל נטענות לפי דרישה (הרשימה מחזירה רק דגל has_avatar)
  avatarCache: new Map(),
};

// ══ COLUMNS ══════════════════════════════════════════════════════════
const COLS = [
  { key: 'forum',         label: 'פורום',          width: 110, render: renderForum },
  { key: 'username',      label: 'שם משתמש',       width: 145, render: renderUsername },
  { key: '_open',         label: 'פרופיל',         width: 60,  render: renderOpenBtn },
  { key: 'full_name',     label: 'שם מלא',         width: 130 },
  { key: 'real_name',     label: 'שם אמיתי',       width: 130 },
  { key: 'groups',        label: 'קבוצות',          width: 105 },
  { key: 'reputation',    label: 'מוניטין',         width: 65,  render: renderRep },
  { key: 'phone',         label: 'טלפון',           width: 115, render: renderPhone },
  { key: 'email',         label: 'מייל',            width: 155, render: renderEmail },
  { key: 'address',       label: 'כתובת',           width: 150 },
  { key: 'status',        label: 'סטטוס',           width: 85,  render: renderStatus },
  { key: 'last_seen',     label: 'נראה לאחרונה',    width: 110 },
  { key: 'join_date',     label: 'תאריך הצטרפות',   width: 110 },
  { key: 'post_count',    label: 'הודעות',          width: 70,  render: renderNum },
  { key: 'trust_level',   label: 'אמינות',          width: 65,  render: renderNum },
  { key: 'updated_at',    label: 'עודכן',           width: 130, render: renderUpdated },
  { key: 'extra_info',    label: 'פרטים נוספים',    width: 170 },
  { key: 'notes',         label: 'הערות',           width: 180, render: renderNotes },
  { key: 'private_notes', label: 'הערות אישיות',    width: 175, render: renderPrivate },
  { key: 'identity',      label: 'זהות כפולה',      width: 90,  render: renderIdentity },
];

// ══ רוחב וסדר עמודות ══════════════════════════════════════════════════
// נשמר כ-JSON יחיד ב-display settings. שמות עמודות לא מוכרים נזרקים, וחסרות
// מתווספות בסוף — כך שהוספת עמודה בגרסה חדשה לא שוברת פריסה שמורה.
const MIN_COL_W = 46, MAX_COL_W = 640;
let COL_LAYOUT = { order: null, w: {} };

function loadColLayout(raw) {
  COL_LAYOUT = { order: null, w: {} };
  let parsed = null;
  try { parsed = JSON.parse(raw || 'null'); } catch (e) { parsed = null; }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return;
  const known = new Set(COLS.map(c => c.key));
  if (Array.isArray(parsed.order)) {
    const seen = new Set();
    const ord = parsed.order.filter(k => known.has(k) && !seen.has(k) && seen.add(k));
    COLS.forEach(c => { if (!seen.has(c.key)) ord.push(c.key); });   // עמודה חדשה בסוף
    COL_LAYOUT.order = ord;
  }
  if (parsed.w && typeof parsed.w === 'object') {
    for (const [k, v] of Object.entries(parsed.w)) {
      const n = parseInt(v);
      if (known.has(k) && Number.isFinite(n))
        COL_LAYOUT.w[k] = Math.max(MIN_COL_W, Math.min(MAX_COL_W, n));
    }
  }
}

function orderedCols() {
  if (!COL_LAYOUT.order) return COLS.slice();
  const byKey = new Map(COLS.map(c => [c.key, c]));
  return COL_LAYOUT.order.map(k => byKey.get(k)).filter(Boolean);
}

function visibleCols() {
  const hidden = hiddenColsSet();
  return orderedCols().filter(c => !hidden.has(c.key));
}

function colWidth(col) { return COL_LAYOUT.w[col.key] || col.width; }

let _colSaveTimer = null;
function saveColLayout() {
  clearTimeout(_colSaveTimer);
  _colSaveTimer = setTimeout(() => {
    // נשמרים רק רוחבים שהמשתמש שינה בפועל — לא צילום של ברירות המחדל
    const w = {};
    for (const [k, v] of Object.entries(COL_LAYOUT.w)) {
      const def = COLS.find(c => c.key === k);
      if (def && v !== def.width) w[k] = v;
    }
    const payload = JSON.stringify({ order: COL_LAYOUT.order, w });
    DISPLAY.col_layout = payload;
    api('set_display_setting', 'col_layout', payload);
  }, 250);
}

async function resetColLayout() {
  COL_LAYOUT = { order: null, w: {} };
  DISPLAY.col_layout = '';
  await api('set_display_setting', 'col_layout', '');
  buildTableHeader();
  renderTable();
  toast('רוחב וסדר העמודות אופסו', 'success');
}

function applyColMove(key, toIndex) {
  const order = (COL_LAYOUT.order || COLS.map(c => c.key)).slice();
  const from = order.indexOf(key);
  if (from < 0) return;
  order.splice(from, 1);
  order.splice(from < toIndex ? toIndex - 1 : toIndex, 0, key);
  COL_LAYOUT.order = order;
}

// איזה אינדקס-שחרור מתאים למיקום המצביע. ths[0] הוא הימני ביותר ב-RTL, ולכן
// עוברים לפי סדר ה-DOM ומחפשים את הראשון שמרכזו שמאלה מהמצביע.
function dropIndexAt(ths, clientX) {
  for (let i = 0; i < ths.length; i++) {
    const r = ths[i].getBoundingClientRect();
    if (clientX > r.left + r.width / 2) return i;
  }
  return ths.length;
}

function showDropLine(ths, idx) {
  let line = document.getElementById('col-drop-line');
  if (!line) {
    line = document.createElement('div');
    line.id = 'col-drop-line';
    document.body.appendChild(line);
  }
  const ref = ths[Math.min(idx, ths.length - 1)];
  if (!ref) return;
  const r = ref.getBoundingClientRect();
  // הוספה "לפני" עמודה ב-RTL = הקצה הימני שלה; הוספה בסוף = הקצה השמאלי של האחרונה
  line.style.left = (idx >= ths.length ? r.left : r.right) + 'px';
  line.style.top = r.top + 'px';
  line.style.height = (document.getElementById('table-wrap')?.clientHeight || r.height) + 'px';
}

function hideDropLine() {
  document.getElementById('col-drop-line')?.remove();
}

// מדידה לפי מה שנבנה בפועל ב-DOM (עשרות שורות בחלון הווירטואלי) — לעולם לא
// לעבור על S.nicks, שהוא 90 אלף.
function autoFitColumn(key) {
  const cells = document.querySelectorAll(`#tbody td[data-col="${CSS.escape(key)}"]`);
  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;font-size:13.5px';
  document.body.appendChild(probe);
  let max = 0;
  const th = document.querySelector(`#thead-row th[data-col="${CSS.escape(key)}"]`);
  if (th) { probe.textContent = th.textContent; max = probe.offsetWidth + 30; }
  cells.forEach(td => {
    probe.textContent = td.textContent || '';
    max = Math.max(max, probe.offsetWidth);
  });
  probe.remove();
  COL_LAYOUT.w[key] = Math.max(MIN_COL_W, Math.min(MAX_COL_W, max + 34));
  buildTableHeader();
  renderTableWindow();
  saveColLayout();
}

let _colDrag = null;

function startColResize(e, key) {
  e.preventDefault(); e.stopPropagation();
  const th = e.target.closest('th');
  _colDrag = { kind: 'resize', key, startX: e.clientX, startW: th.getBoundingClientRect().width };
  document.body.classList.add('col-resizing');
  e.target.setPointerCapture?.(e.pointerId);
}

function startColMove(e, key) {
  if (e.button !== 0) return;
  const th = e.target.closest('th');
  _colDrag = { kind: 'maybe-move', key, startX: e.clientX, th, moved: false };
  e.target.setPointerCapture?.(e.pointerId);
}

function onColPointerMove(e) {
  if (!_colDrag) return;
  if (_colDrag.kind === 'resize') {
    // RTL: הידית על הקצה השמאלי, ולכן גרירה שמאלה (clientX יורד) = רחב יותר
    const dx = _colDrag.startX - e.clientX;
    const w = Math.max(MIN_COL_W, Math.min(MAX_COL_W, Math.round(_colDrag.startW + dx)));
    COL_LAYOUT.w[_colDrag.key] = w;
    const cg = document.getElementById('nick-colgroup');
    const idx = visibleCols().findIndex(c => c.key === _colDrag.key);
    if (cg && idx >= 0 && cg.children[idx + 1]) cg.children[idx + 1].style.width = w + 'px';
    return;
  }
  if (Math.abs(e.clientX - _colDrag.startX) > 5) {
    if (!_colDrag.moved) {
      _colDrag.moved = true;
      _colDrag.kind = 'move';
      _colDrag.th.classList.add('col-dragging');
      document.body.classList.add('col-dragging');
    }
  }
  if (_colDrag.kind === 'move') {
    const ths = [...document.querySelectorAll('#thead-row th[data-col]')];
    showDropLine(ths, dropIndexAt(ths, e.clientX));
  }
}

function endColDrag(e) {
  if (!_colDrag) return;
  const d = _colDrag;
  _colDrag = null;
  document.body.classList.remove('col-resizing', 'col-dragging');
  d.th?.classList.remove('col-dragging');
  hideDropLine();
  if (d.kind === 'resize') { buildTableHeader(); renderTableWindow(); saveColLayout(); return; }
  if (d.kind === 'move' && e) {
    const ths = [...document.querySelectorAll('#thead-row th[data-col]')];
    const visKeys = ths.map(t => t.dataset.col);
    const at = dropIndexAt(ths, e.clientX);
    const fullOrder = COL_LAYOUT.order || COLS.map(c => c.key);
    // אינדקס מתוך העמודות הנראות → אינדקס בסדר המלא, כדי שעמודות מוסתרות
    // ישמרו על מקומן היחסי ולא יזחלו לסוף
    const targetKey = visKeys[at];
    const toIndex = targetKey ? fullOrder.indexOf(targetKey) : fullOrder.length;
    applyColMove(d.key, toIndex);
    buildTableHeader();
    renderTable();
    saveColLayout();
    _suppressSortClick = true;      // ה-click שאחרי הגרירה לא ימיין
    setTimeout(() => { _suppressSortClick = false; }, 0);
  }
}

let _suppressSortClick = false;
document.addEventListener('pointermove', onColPointerMove);
document.addEventListener('pointerup', endColDrag);
document.addEventListener('pointercancel', () => endColDrag(null));

// ══ INIT ══════════════════════════════════════════════════════════════
// המתן עד ש-pywebview.api מכיל מתודות ממשיות (לא רק אובייקט ריק)
function apiReady() {
  return !!(window.pywebview &&
            window.pywebview.api &&
            typeof window.pywebview.api.get_forums === 'function');
}

function waitForApi(timeoutMs = 10000) {
  return new Promise((resolve) => {
    if (apiReady()) return resolve(true);
    const started = Date.now();
    const poll = setInterval(() => {
      if (apiReady()) {
        clearInterval(poll);
        resolve(true);
      } else if (Date.now() - started > timeoutMs) {
        clearInterval(poll);
        console.error('[Tik-Nick] pywebview.api לא נטען בזמן');
        resolve(false);
      }
    }, 50);
  });
}

window.addEventListener('load', async () => {
  if (window._initDone) return;
  window._initDone = true;
  const ok = await waitForApi();
  if (!ok) {
    document.getElementById('status-msg').textContent =
      'שגיאה: לא ניתן להתחבר ל-Python API';
    return;
  }
  await _origInit();
});

async function _origInit() {
  // גרסה ב-footer מיד מההפעלה (לא תלוי בבדיקת עדכונים / אינטרנט)
  api('get_app_version').then(v => {
    const el = document.getElementById('footer-version');
    if (el && v?.version) el.textContent = `v${v.version} | Tik-Nick`;
  });
  await applyDisplaySettings();
  // זיכרון סשן: מיון וחיפוש אחרונים
  const savedSort = String(DISPLAY.sort || '');
  if (savedSort.includes(':')) {
    const [c, d] = savedSort.split(':');
    if (COLS.some(x => x.key === c) || c === 'has_info') { S.sortCol = c; S.sortDir = d === '-1' ? -1 : 1; }
  }
  const lastSearch = String(DISPLAY.last_search || '');
  const si = document.getElementById('search-input');
  if (si && lastSearch) si.value = lastSearch;
  buildTableHeader();
  updateSortIcons();
  await loadForums();
  await loadNicks(lastSearch);
  const tableWrap = document.getElementById('table-wrap');
  if (tableWrap) tableWrap.addEventListener('scroll', onTableScroll);
  const cardsWrap = document.getElementById('cards-wrap');
  if (cardsWrap) cardsWrap.addEventListener('scroll', onCardsScroll);
  // אם סריקה כבר רצה ברקע — חדש את מד ההתקדמות
  try {
    const p = await api('get_scrape_progress');
    if (p && p.running) startScrapeMonitor();
  } catch (e) {}
  try {
    const cp = await api('get_chazonishnik_progress');
    if (cp && cp.running) startChazonishnikMonitor();
  } catch (e) {}
  try {
    const sp = await api('get_stinknik_progress');
    if (sp && sp.running) startStinknikMonitor();
  } catch (e) {}
  setInterval(() => {
    const el = document.getElementById('status-time');
    if (el) el.textContent = new Date().toLocaleTimeString('he-IL');
  }, 1000);
  // אם עדכון קודם ירד אך לא הצליח להחליף את הקובץ — אמור זאת (אחרת נראה כאילו כלום לא קרה)
  api('consume_update_failure').then(r => {
    if (r?.failed) toast('העדכון הקודם ירד אך לא הוחל (הקובץ היה נעול). נסה שוב דרך "אודות".', 'error');
  });
  // עדכון שהתחיל ולא תפס: התוכנה עולה שוב באותה גרסה. עד עכשיו זה נראה כאילו
  // פשוט לא קרה כלום — וזה בדיוק מה שהמשתמש חווה כ"העדכון נפל".
  api('settle_pending_update').then(r => {
    if (!r || !r.target) return;
    openModal('⚠️ העדכון לא הושלם', `
      <div style="font-size:13.5px;line-height:1.9">
        ניסינו לעדכן ל-<b>v${esc(r.target)}</b>, אבל התוכנה עלתה שוב ב-<b>v${esc(r.current)}</b>.
        <div style="margin-top:10px;color:var(--subtext);font-size:12.5px">
          זה קורה כשההתקנה חסומה — אנטי-וירוס, הרשאות, או עותק אחר של התוכנה שרץ.
          ${r.log ? 'פרטי הכישלון נשמרו ביומן ההתקנה.' : ''}
        </div>
        <div style="margin-top:12px;font-size:12.5px">
          הדרך הבטוחה: להוריד את הגרסה מדף הגרסאות ולהתקין ידנית.
        </div>
      </div>`, [
      { label: '🌐 פתח את דף הגרסאות', cls: 'btn-primary', action: () => {
        api('open_url', 'https://github.com/BeniaBot/tiknick/releases/latest'); closeModal();
      }},
      ...(r.log ? [{ label: '📄 פתח יומן התקנה', cls: 'btn-ghost',
                     action: () => api('open_update_log') }] : []),
      { label: 'סגור', cls: 'btn-ghost', action: closeModal },
    ], 'modal-sm', { id: 'update-failed' });
  });
  // בדיקת עדכונים שקטה ברקע (לא חוסמת)
  setTimeout(silentUpdateCheck, 2500);
}

// ══ UPDATE CHECK ══════════════════════════════════════════════════════
async function silentUpdateCheck() {
  const res = await api('check_for_updates');
  const verEl = document.getElementById('footer-version');
  if (res?.ok) {
    if (verEl) verEl.textContent = `v${res.current} | Tik-Nick`;
    if (res.update_available) {
      const dot = document.getElementById('update-dot');
      if (dot) dot.style.display = 'inline-block';
      const adot = document.getElementById('about-update-dot');
      if (adot) adot.style.display = 'inline-block';
      const foot = document.getElementById('app-footer');
      if (foot) foot.title = `גרסה ${res.latest} זמינה! לחץ לאודות`;
      toast(`🎉 גרסה חדשה זמינה: v${res.latest}`, 'info');
    }
  }
}

async function checkUpdates() {
  toast('בודק עדכונים...', 'info');
  const res = await api('check_for_updates');
  if (!res?.ok) {
    toast(res?.error || 'לא ניתן לבדוק עדכונים', 'error');
    return;
  }

  if (!res.update_available) {
    openModal('✓ אתה מעודכן', `
      <div style="text-align:center;padding:24px 20px">
        <div style="font-size:48px;margin-bottom:14px">✅</div>
        <h3 style="font-size:17px;margin-bottom:8px">הגרסה שלך עדכנית</h3>
        <p style="color:var(--subtext);font-size:14px">
          גרסה נוכחית: <b>v${esc(res.current)}</b><br>
          זו הגרסה האחרונה שפורסמה.
        </p>
      </div>`, [
      { label: 'סגור', cls: 'btn-ghost', action: closeModal },
    ], 'modal-sm');
    return;
  }

  // תקציר שמתקצר ככל שהקפיצה גדולה: מי שדילג על תשע גרסאות לא יקרא קיר טקסט,
  // ומי שמעדכן גרסה אחת דווקא רוצה את הפירוט.
  const sum = await api('get_update_summary', res.current, res.latest);
  let notesHtml = '';
  if (sum?.ok && (sum.groups || []).length) {
    notesHtml = `
      <div style="margin-top:14px;padding:12px 14px;background:var(--card2);border-radius:8px;
                  max-height:44vh;overflow-y:auto">
        <div style="font-size:12.5px;font-weight:800;margin-bottom:8px">${esc(sum.headline)}</div>
        ${sum.groups.map(g => `
          <div style="margin-bottom:9px">
            <div style="font-size:11px;font-weight:800;color:var(--subtext);margin-bottom:3px">
              ${esc(g.title)}</div>
            ${g.items.map(it => `
              <div style="font-size:12.5px;line-height:1.75;padding-inline-start:4px">• ${esc(it)}</div>`).join('')}
          </div>`).join('')}
        ${sum.jump > 1 ? `<div style="font-size:11px;color:var(--subtext);margin-top:6px">
          הרשימה המלאה לכל גרסה נמצאת בדף הגרסאות.</div>` : ''}
      </div>`;
  } else if (res.notes) {
    notesHtml = `<div style="margin-top:14px;padding:12px 14px;background:var(--card2);
             border-radius:8px;font-size:12.5px;color:var(--text-dim);
             max-height:180px;overflow-y:auto;white-space:pre-wrap;line-height:1.6">${esc(res.notes)}</div>`;
  }

  openModal('🎉 גרסה חדשה זמינה!', `
    <div style="text-align:center;padding:10px 0 6px">
      <div style="font-size:44px;margin-bottom:10px">🚀</div>
      <div style="font-size:15px;color:var(--subtext)">
        גרסה נוכחית: <b style="color:var(--text)">v${esc(res.current)}</b>
        &nbsp;→&nbsp;
        גרסה חדשה: <b style="color:var(--accent)">v${esc(res.latest)}</b>
      </div>
    </div>
    ${notesHtml}
    <div id="update-progress" style="display:none;margin-top:16px">
      <div style="font-size:12.5px;color:var(--subtext);margin-bottom:6px" id="update-progress-text">מוריד…</div>
      <div style="height:8px;background:var(--card2);border-radius:99px;overflow:hidden">
        <div id="update-bar" style="height:100%;width:0%;background:linear-gradient(90deg,var(--accent),var(--accent-2));transition:width .3s"></div>
      </div>
    </div>
    <p style="font-size:12px;color:var(--subtext);margin-top:14px;text-align:center">
      הנתונים שלך נשמרים בנפרד ולא יושפעו מהעדכון.
    </p>`, [
    res.download_url
      ? { label: '⬇️ עדכן עכשיו', cls: 'btn-primary', action: () => startInAppUpdate(res.download_url, res.release_url) }
      : { label: '🌐 פתח דף ההורדה', cls: 'btn-primary', action: () => { api('open_url', res.release_url); closeModal(); } },
    { label: '📥 הורד ידנית', cls: 'btn-ghost', action: () => { api('open_url', res.download_url || res.release_url); closeModal(); } },
    { label: 'אחר כך', cls: 'btn-ghost', action: closeModal },
  ]);
}

async function startInAppUpdate(downloadUrl, releaseUrl) {
  // בדוק אם רצים כ-EXE (עדכון פנימי) או לא (fallback לדפדפן)
  const prog = document.getElementById('update-progress');
  const btnBar = document.querySelector('.modal-buttons') || document.querySelector('.modal-footer');
  if (prog) prog.style.display = 'block';
  const txt = document.getElementById('update-progress-text');
  const bar = document.getElementById('update-bar');
  if (txt) txt.textContent = 'מוריד את הגרסה החדשה…';

  // התחל הורדה
  const dlPromise = api('download_update', downloadUrl);
  // עדכון פס התקדמות
  const poll = setInterval(async () => {
    const p = await api('get_update_download_progress');
    if (p && p.total && bar) {
      const pct = Math.round((p.downloaded / p.total) * 100);
      bar.style.width = pct + '%';
      if (txt) txt.textContent = `מוריד… ${pct}%`;
    }
  }, 400);

  const dl = await dlPromise;
  clearInterval(poll);

  if (!dl?.ok) {
    // fallback — פתח בדפדפן
    if (dl?.error && dl.error.includes('EXE')) {
      if (txt) txt.textContent = '';
      toast('עדכון פנימי זמין רק בגרסת ה-EXE. פותח הורדה בדפדפן…', 'info');
      api('open_url', downloadUrl || releaseUrl);
      closeModal();
      return;
    }
    toast('שגיאה בהורדה: ' + (dl?.error || ''), 'error');
    return;
  }

  if (bar) bar.style.width = '100%';
  if (txt) txt.textContent = 'ההורדה הושלמה. מחיל עדכון ומפעיל מחדש…';
  if (!confirm('ההורדה הושלמה. התוכנה תיסגר, תתעדכן, ותיפתח מחדש. להמשיך?')) {
    toast('העדכון בוטל. הקובץ הורד וממתין.', 'info');
    return;
  }
  const ap = await api('apply_update', dl.path);
  if (!ap?.ok) {
    toast('שגיאה בהחלת העדכון: ' + (ap?.error || ''), 'error');
  }
  // אם הצליח — התוכנה נסגרת אוטומטית
}

// ══ ABOUT ═════════════════════════════════════════════════════════════
async function openAbout() {
  const ver = await api('get_app_version');
  const version = ver?.version || '0.1.0';
  const repo    = ver?.repo || 'BeniaBot/tiknick';
  const ghUser  = repo.split('/')[0];

  const html = `
    <div class="about-wrap">
      <!-- סטטוס עדכון בראש -->
      <div class="about-update" id="about-update-box">
        <div class="about-update-inner" id="about-update-inner">
          <span class="au-spinner"></span>
          <span id="au-text">בודק עדכונים...</span>
        </div>
      </div>

      <!-- לוגו + כותרת -->
      <div class="about-hero">
        <div class="about-logo">
          <svg viewBox="0 0 100 100" width="72" height="72" xmlns="http://www.w3.org/2000/svg">
            <rect width="100" height="100" rx="23" fill="url(#aboutgrad)"/>
            <defs><linearGradient id="aboutgrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#fbbf24"/><stop offset="1" stop-color="#d97706"/>
            </linearGradient></defs>
            <g transform="rotate(-7 50 50)">
              <rect x="22" y="30" width="56" height="40" rx="7" fill="#fff"/>
              <circle cx="34" cy="47" r="8.5" fill="#d97706"/>
              <circle cx="34" cy="44.5" r="3" fill="#fff"/>
              <path d="M 28.5 52 A 5.5 5.5 0 0 1 39.5 52 Z" fill="#fff"/>
              <rect x="46" y="43" width="26" height="4.5" rx="2" fill="#d97706"/>
              <rect x="46" y="54" width="18" height="4" rx="2" fill="#f0c078"/>
            </g>
          </svg>
        </div>
        <h2 class="about-name">Tik-Nick</h2>
        <div class="about-version">גרסה ${esc(version)}</div>
        <a class="about-link" onclick="api('open_url','https://github.com/${esc(repo)}')">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:-2px">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/>
          </svg>
          בקר בעמוד ה-GitHub
        </a>
      </div>

      <!-- כפתורי ניווט -->
      <div class="about-tabs">
        <button class="about-tab active" onclick="switchAboutTab('about',this)">אודות</button>
        <button class="about-tab" onclick="switchAboutTab('credits',this)">קרדיטים</button>
        <button class="about-tab" onclick="switchAboutTab('license',this)">רישיון</button>
      </div>

      <!-- תוכן הלשוניות -->
      <div class="about-pane" id="about-pane-about">
        <p class="about-text">
          <b>Tik-Nick</b> היא תוכנה לניהול ומעקב אחר ניקים (שמות משתמש) בפורומים.
          מאפשרת לתעד פרטים, לקשר זהויות, לנהל פורומים ולסנכרן מידע — הכל מקומית במחשב שלך.
        </p>
        <div class="about-meta-grid">
          <div class="about-meta"><span class="am-k">גרסה</span><span class="am-v">${esc(version)}</span></div>
          <div class="about-meta"><span class="am-k">פלטפורמה</span><span class="am-v">Windows 10/11</span></div>
          <div class="about-meta"><span class="am-k">מנוע</span><span class="am-v">PyWebView</span></div>
          <div class="about-meta"><span class="am-k">אחסון</span><span class="am-v">מקומי (SQLite)</span></div>
        </div>
      </div>

      <div class="about-pane" id="about-pane-credits" style="display:none">
        <p class="about-text" style="text-align:center;margin-bottom:18px">
          תודה לכל מי שסייע, בדק, והציע רעיונות לאורך הפיתוח. 🙏
        </p>

        <div class="credit-card credit-hero">
          <div class="credit-avatar">🤖</div>
          <div class="credit-body">
            <div class="credit-role">מאחורי הקלעים</div>
            <div class="credit-name">Claude Opus 4.8</div>
            <div class="credit-desc">
              המתכנת של האפליקציה — מבית Anthropic<br>
              על פיתוח סבלני ומכיל חרף פרומפטים הפכפכים 💛
            </div>
          </div>
        </div>

        <div class="credit-card">
          <div class="credit-avatar" style="padding:0;overflow:hidden">
            <img src="cfopuser.png" alt="cfopuser" style="width:100%;height:100%;object-fit:cover">
          </div>
          <div class="credit-body">
            <div class="credit-role">רעיון ופיתוח Chazonishnik</div>
            <a class="credit-name-link" onclick="api('open_url','https://mitmachim.top/user/cfopuser')">cfopuser</a>
          </div>
        </div>

        <div class="credit-card">
          <div class="credit-avatar">🦨</div>
          <div class="credit-body">
            <div class="credit-role">רעיון ופיתוח Stinknik</div>
            <a class="credit-name-link" onclick="api('open_url','https://mitmachim.top/user/%D7%98%D7%95%D7%A4-%D7%A9%D7%91%D7%9E%D7%AA%D7%9E%D7%97%D7%99%D7%9D')">טופ שבמתמחים</a>
          </div>
        </div>

        <div class="credit-card">
          <div class="credit-avatar">🙏</div>
          <div class="credit-body">
            <div class="credit-role">תודה מיוחדת</div>
            <a class="credit-name-link" onclick="api('open_url','https://mitmachim.top/user/%D7%A6%D7%95%D7%9C-%D7%92%D7%90%D7%94')">צול גאה</a>
            <div class="credit-desc">
              על עידוד ותמיכה מורלית ;)<br>
              ובעיקר על ההשראה לשם Chazonishnik 😄
            </div>
          </div>
        </div>
      </div>

      <div class="about-pane" id="about-pane-license" style="display:none">
        <p class="about-text">
          תוכנה זו ניתנת <b>לשימוש אישי בלבד</b>.
        </p>
        <ul class="about-license-list">
          <li>✓ מותר להשתמש, להעתיק ולגבות לצורך אישי</li>
          <li>✓ הנתונים שלך שייכים לך ונשמרים מקומית בלבד</li>
          <li>✗ אין להפיץ מחדש למטרות מסחריות ללא רשות</li>
        </ul>
        <p class="about-license-fine">
          התוכנה מסופקת "כמות שהיא" (AS IS) ללא אחריות מכל סוג.
        </p>
      </div>

      <!-- "פותח על ידי" — תמיד מופיע למטה -->
      <div class="about-developer">
        <div class="ad-avatar">🤖</div>
        <div class="ad-info">
          <div class="ad-role">פותח על ידי</div>
          <a class="ad-name-link" onclick="api('open_url','https://github.com/${esc(ghUser)}')">
            בני הבוט
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:-1px;opacity:.75">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/>
            </svg>
          </a>
        </div>
        <button class="ad-contact-btn" onclick="api('open_url','https://mail.google.com/mail/?view=cm&fs=1&to=b0554003794@gmail.com&su=Tik-Nick%20-%20\u05e6\u05d5\u05e8%20\u05e7\u05e9\u05e8')" title="שלח מייל למפתח">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="5" width="18" height="14" rx="2"/>
            <path d="m3 7 9 6 9-6"/>
          </svg>
          צור קשר
        </button>
      </div>
    </div>`;

  openModal('אודות', html, [
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');

  refreshAboutUpdate();
}

function switchAboutTab(tab, btn) {
  document.querySelectorAll('.about-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  ['about','credits','license'].forEach(t => {
    const pane = document.getElementById('about-pane-' + t);
    if (pane) pane.style.display = t === tab ? 'block' : 'none';
  });
}

async function refreshAboutUpdate() {
  const box   = document.getElementById('about-update-box');
  const inner = document.getElementById('about-update-inner');
  if (!inner) return;
  const res = await api('check_for_updates');
  if (!res?.ok) {
    box.className = 'about-update neutral';
    inner.innerHTML = `<span>ℹ️</span><span>לא ניתן לבדוק עדכונים כרגע</span>
      <a onclick="refreshAboutUpdate()" class="au-action">נסה שוב</a>`;
    return;
  }
  if (res.update_available) {
    box.className = 'about-update available';
    inner.innerHTML = `
      <span>🎉</span>
      <span>גרסה <b>${esc(res.latest)}</b> זמינה!</span>
      <a onclick="closeModal();checkUpdates()" class="au-action">עדכן עכשיו</a>`;
  } else {
    box.className = 'about-update ok';
    inner.innerHTML = `
      <span class="au-check">✓</span>
      <span>האפליקציה מעודכנת לגרסה האחרונה</span>
      <a onclick="refreshAboutUpdate()" class="au-action">בדוק שוב</a>`;
  }
}

// ══ FORUMS ════════════════════════════════════════════════════════════
async function refreshFromLogo() {
  const logo = document.querySelector('.sidebar-logo .logo-mark');
  if (logo) { logo.style.transition = 'transform .5s'; logo.style.transform = 'rotate(360deg)'; }
  await loadForums();
  await loadNicks(document.getElementById('search-input').value);
  toast('רוענן ✓', 'success');
  setTimeout(() => { if (logo) { logo.style.transition=''; logo.style.transform=''; } }, 500);
}

async function loadForums() {
  const res = await api('get_forums');
  S.forums = Array.isArray(res) ? res : [];
  S.forumColors = {};
  S.forums.forEach(f => { S.forumColors[f.name] = f.color; });
}

// ══ TABLE ═════════════════════════════════════════════════════════════
function buildTableHeader() {
  const tr = document.getElementById('thead-row');
  tr.innerHTML = '';

  const thSel = document.createElement('th');
  thSel.style.width = '34px';
  thSel.innerHTML = `<input type="checkbox" id="select-all-cb" title="בחר הכל">`;
  tr.appendChild(thSel);
  thSel.querySelector('input').onclick = e => {
    e.stopPropagation();
    toggleSelectAll(e.target.checked);
  };

  const cols = visibleCols();
  const cg = document.getElementById('nick-colgroup');
  if (cg) {
    cg.innerHTML = '<col style="width:34px">' +
      cols.map(c => `<col style="width:${colWidth(c)}px">`).join('') + '<col>';
  }
  cols.forEach(col => {
    const th = document.createElement('th');
    th.style.width = colWidth(col) + 'px';
    th.innerHTML = `<span class="th-label">${col.label}</span> <span class="sort-icon">↕</span>` +
                   `<span class="col-resize" title="גרור לשינוי רוחב · לחיצה כפולה = התאמה אוטומטית"></span>`;
    th.dataset.col = col.key;
    th.onclick = () => { if (!_suppressSortClick) sortBy(col.key); };
    th.querySelector('.col-resize').addEventListener('pointerdown', e => startColResize(e, col.key));
    th.querySelector('.col-resize').addEventListener('dblclick', e => {
      e.stopPropagation(); autoFitColumn(col.key);
    });
    th.querySelector('.th-label').addEventListener('pointerdown', e => startColMove(e, col.key));
    tr.appendChild(th);
  });
  // עמודת מילוי: בלעדיה טבלה צרה מהמסך נמתחת ומבטלת את הרוחבים שנקבעו
  const filler = document.createElement('th');
  filler.className = 'th-filler';
  filler.style.cursor = 'default';
  tr.appendChild(filler);
}

async function loadNicks(search = '') {
  // טוקן ייחודי לבקשה הזו — אם עד שהיא חוזרת כבר יצאה בקשה חדשה יותר
  // (חיפוש נוסף, מחיקה, וכו'), מתעלמים מהתוצאה המיושנת. זה מונע מצב
  // שבו ניק שכבר נמחק "קופץ בחזרה" רגע לפני שנעלם, בעיקר בתצוגת כרטיסים.
  const myToken = ++S.loadToken;
  S.currentSearch = search;
  S.multiSelected.clear();
  S.selectedId = null;      // אחרת "ערוך"/"מחק" פעלו על ניק שכבר לא ברשימה
  setStatus('טוען…');   // משוב מיידי — במאגר גדול הטעינה נמשכת שניות
  // תמונות פרופיל עלולות להשתנות אחרי סריקה/ייבוא — מטמון טרי לכל טעינה
  S.avatarCache.clear();
  // חיפוש חופשי וסינון מתקדם אינם חיים יחד — הצגת סינון ישן עם תוצאות חיפוש מבלבלת,
  // ותשובת סינון שעוד בדרך לא תדרוס את הטעינה החדשה
  clearTimeout(_filterTimer); _filterSeq++;
  if (_fieldFilterActive) {
    _fieldFilterActive = false;
    const fc = document.getElementById('flt-count');
    if (fc) fc.textContent = '';
  }

  const res = await api('get_nicks', search);

  if (myToken !== S.loadToken) return; // תשובה מיושנת — מתעלמים

  const rows  = res && Array.isArray(res.rows) ? res.rows : (Array.isArray(res) ? res : []);
  const total = res && typeof res.total === 'number' ? res.total : rows.length;

  S.nicks = rows;
  S.total = total;
  S.cardsRendered = Math.min(S.cardsChunk, S.nicks.length);
  // רשימה חדשה — חוזרים לראש הגלילה (גם בכרטיסים) כדי שהחלון הווירטואלי יהיה בטווח
  const cw = document.getElementById('cards-wrap');
  if (cw) cw.scrollTop = 0;
  const tw2 = document.getElementById('table-wrap');
  if (tw2) tw2.scrollTop = 0;

  sortNicks();
  renderTable();
  updateBulkBar();
}

function sortBy(col) {
  if (S.sortCol === col) S.sortDir *= -1;
  else { S.sortCol = col; S.sortDir = 1; }
  api('set_display_setting', 'sort', `${S.sortCol}:${S.sortDir}`);   // זיכרון בין הפעלות
  sortNicks();
  // גלילה חזרה למעלה — אחרת החלון הווירטואלי מציג את השורות של מיקום הגלילה הישן
  const tw = document.getElementById('table-wrap');
  if (tw) tw.scrollTop = 0;
  const cw = document.getElementById('cards-wrap');
  if (cw) cw.scrollTop = 0;
  S.cardsRendered = Math.min(S.cardsChunk, S.nicks.length);
  renderTable();
  updateSortIcons();
}

function updateSortIcons() {
  document.querySelectorAll('thead th').forEach(th => {
    const active = th.dataset.col === S.sortCol;
    th.classList.toggle('sorted', active);
    const icon = th.querySelector('.sort-icon');
    if (icon) icon.textContent = active ? (S.sortDir === 1 ? '↑' : '↓') : '↕';
  });
}

// Collator אחד קבוע — localeCompare(...,'he') בכל השוואה היה פי ~2.4 יקר יותר
const HE_COLLATOR = new Intl.Collator('he', { numeric: true });

function sortNicks() {
  // ברירת המחדל כבר ממוינת ב-SQL (has_info, trust_level, updated_at) — אין טעם למיין שוב
  if (S.sortCol === 'has_info') return;
  S.nicks.sort((a, b) => {
    // has_info always first
    if (a.has_info !== b.has_info) return b.has_info - a.has_info;
    const va = a[S.sortCol] ?? '';
    const vb = b[S.sortCol] ?? '';
    const n = typeof va === 'number';
    return n ? (va - vb) * S.sortDir
             : HE_COLLATOR.compare(String(va), String(vb)) * S.sortDir;
  });
}

function buildNickRow(n) {
  const tr = document.createElement('tr');
  tr.dataset.id = n.id;
  if (n.id === S.selectedId) tr.classList.add('selected');

  const tdSel = document.createElement('td');
  tdSel.innerHTML = `<input type="checkbox" class="row-select-cb">`;
  const cb = tdSel.querySelector('input');
  cb.checked = S.multiSelected.has(n.id);
  cb.onclick = e => {
    e.stopPropagation();
    toggleRowSelected(n.id, e.target.checked);
  };
  tr.appendChild(tdSel);

  const conflictFields = n.conflict_fields ? String(n.conflict_fields).split(',') : [];
  (_visibleColsCache || visibleCols()).forEach(col => {
    const td = document.createElement('td');
    td.dataset.col = col.key;      // גם ל-renderers גנריים וגם לשינוי רוחב עמודה
    td.title = String(n[col.key] ?? '');
    if (col.render) {
      col.render(td, n);
    } else {
      const val = n[col.key] ?? '';
      td.textContent = String(val).slice(0, 80);
    }
    // סימן התנגשות על השדה הספציפי
    if (conflictFields.includes(col.key)) {
      const mark = document.createElement('span');
      mark.className = 'field-conflict-mark';
      mark.textContent = ' ❗';
      mark.style.cursor = 'help';
      mark.onmouseenter = e => showFieldSourcesTooltip(e, n.id, col.key);
      mark.onmouseleave = hideTooltip;
      td.appendChild(mark);
    }
    tr.appendChild(td);
  });
  // תא מילוי מול עמודת המילוי בכותרת — אחרת מספר התאים לא תואם ו-colspan
  // של ה-spacer בגלילה הווירטואלית שובר את יישור העמודות.
  tr.appendChild(document.createElement('td'));

  tr.onclick    = e => selectRow(n.id, e);
  tr.ondblclick = () => openNickDialog(n.id);
  return tr;
}

function visibleColCount() {
  return 2 + visibleCols().length;   // תיבת סימון + עמודות + עמודת מילוי
}

// אחרי חיפוש/סינון/מיון התוצאות שונות לגמרי — גלילה שנשארה עמוק בפנים
// מציגה טבלה ריקה (החלון הווירטואלי מחשב שורות שכבר לא קיימות).
function resetScroll() {
  const wrap = document.getElementById('table-wrap');
  if (wrap) wrap.scrollTop = 0;
  const cw = document.getElementById('cards-wrap');
  if (cw) cw.scrollTop = 0;
  S.cardsRendered = Math.min(S.cardsChunk, S.nicks.length);
}

function renderTable() {
  const empty = document.getElementById('empty-state');

  if (!S.nicks.length) {
    document.getElementById('tbody').innerHTML = '';
    empty.style.display = '';
    renderEmptyState();
    updateStats();
    setStatus(`עודכן ${new Date().toLocaleTimeString('he-IL')} · אין תוצאות`);
    if (DISPLAY.view === 'cards') renderCards();
    return;
  }
  empty.style.display = 'none';

  renderTableWindow();  // בונה רק את השורות שבתצוגה (virtual scrolling)

  updateStats();
  setStatus(`עודכן ${new Date().toLocaleTimeString('he-IL')}`);
  // כרטיסים נבנים רק כשהתצוגה פעילה — אחרת נבנו 120 כרטיסים נסתרים בכל רענון
  if (DISPLAY.view === 'cards') renderCards();
}

// מצב ריק מותאם: אחרי חיפוש/סינון זו לא "התחלה", אלא "אין תוצאות"
function renderEmptyState() {
  const box = document.getElementById('empty-state');
  if (!box) return;
  const q = (S.currentSearch || '').trim();
  if (q || _fieldFilterActive) {
    box.innerHTML = `<div class="empty-icon">🔍</div>
      <h3>לא נמצאו תוצאות${q ? ` עבור "${esc(q)}"` : ''}</h3>
      <p>נסו לחפש אחרת, או <b style="color:var(--accent);cursor:pointer"
         onclick="clearAllFilters()">נקו את החיפוש</b></p>`;
  } else {
    // הפעלה ראשונה: הצע את שתי הדרכים להתחיל — ידנית, או סריקה של פורום
    const hasForums = S.forums.some(f => (f.url || '').trim());
    box.innerHTML = `<div class="empty-icon">📭</div>
      <h3>אין ניקים להצגה</h3>
      <p>לחץ "ניק חדש" כדי להוסיף ידנית, או
         <b style="color:var(--accent);cursor:pointer" onclick="${hasForums ? 'openInternetSync()' : 'openForumMgr()'}">
           ${hasForums ? 'סרוק פורום מהאינטרנט' : 'הוסף פורום וסרוק אותו'}</b></p>`;
  }
}

async function clearAllFilters() {
  const inp = document.getElementById('search-input');
  if (inp) inp.value = '';
  if (_fieldFilterActive) await clearFieldFilter();
  else await loadNicks('');
}

// ── Virtual scrolling: בונה רק את השורות בטווח הנראה + מרווח בטחון ──────
function renderTableWindow() {
  const wrap  = document.getElementById('table-wrap');
  const tbody = document.getElementById('tbody');
  if (!wrap || !tbody) return;
  const total = S.nicks.length;
  if (!total) { tbody.innerHTML = ''; return; }

  const buffer = 8;
  const viewportH = wrap.clientHeight || 600;
  const scrollTop = wrap.scrollTop || 0;
  const rh = S.rowHeight || 36;

  let start = Math.max(0, Math.floor(scrollTop / rh) - buffer);
  let end   = Math.min(total, Math.ceil((scrollTop + viewportH) / rh) + buffer);
  if (end <= start) end = Math.min(total, start + 30);

  S.vRange = { start, end };
  const cols = visibleColCount();
  _visibleColsCache = visibleCols();    // פעם אחת לחלון, לא פעם לכל שורה

  tbody.innerHTML = '';

  if (start > 0) {
    const spTop = document.createElement('tr');
    spTop.className = 'v-spacer';
    spTop.innerHTML = `<td colspan="${cols}" style="padding:0;border:none;height:${start * rh}px"></td>`;
    tbody.appendChild(spTop);
  }

  for (let i = start; i < end; i++) {
    tbody.appendChild(buildNickRow(S.nicks[i]));
  }

  if (end < total) {
    const spBot = document.createElement('tr');
    spBot.className = 'v-spacer';
    spBot.innerHTML = `<td colspan="${cols}" style="padding:0;border:none;height:${(total - end) * rh}px"></td>`;
    tbody.appendChild(spBot);
  }

  // מדידת גובה שורה אמיתית פעם אחת (לפי הצפיפות הנוכחית), לחישוב מדויק יותר בהמשך
  const sample = tbody.querySelector('tr:not(.v-spacer)');
  if (sample) {
    const h = sample.getBoundingClientRect().height;
    if (h && Math.abs(h - S.rowHeight) > 1 && !_rhRerender) {
      // הגובה האמיתי שונה מההנחה (למשל אחרי שינוי צפיפות) — בנה שוב פעם אחת
      // עם הגובה המדויק, אחרת המרווחים והחלון הנראה לא תואמים עד הגלילה הבאה
      S.rowHeight = h;
      _rhRerender = true;
      try { renderTableWindow(); } finally { _rhRerender = false; }
      return;
    }
  }

  hydrateAvatars();   // רק לשורות שנבנו כרגע
}
let _rhRerender = false;

let _tableScrollRaf = null;
function onTableScroll() {
  if (_tableScrollRaf) return;
  _tableScrollRaf = requestAnimationFrame(() => {
    _tableScrollRaf = null;
    renderTableWindow();
  });
}

// ── טעינת תמונות פרופיל לפי דרישה ────────────────────────────────────
// הרשימה מגיעה בלי תמונות (רק has_avatar) כדי לא להעביר עשרות MB בגשר.
// אחרי כל רינדור מושכים רק את התמונות של השורות שבאמת מוצגות, ומטמינים.
function applyAvatar(el, dataUrl) {
  el.dataset.avatarDone = '1';
  const safe = safeUrl(dataUrl);            // רק data:image או http(s)
  if (!safe || /["'()\\]/.test(safe.slice(0, 32))) return;
  if (el.tagName === 'IMG') el.src = safe;
  else el.style.backgroundImage = `url("${safe.replace(/["\\]/g, '')}")`;
}

async function hydrateAvatars() {
  const pending = [];
  document.querySelectorAll('[data-avatar-id]:not([data-avatar-done])').forEach(el => {
    const id = el.dataset.avatarId;
    if (S.avatarCache.has(id)) applyAvatar(el, S.avatarCache.get(id));
    else pending.push(id);
  });
  if (!pending.length) return;
  const ids = [...new Set(pending)].slice(0, 200);
  const map = await api('get_avatars', ids);
  if (!map) return;   // כשל גשר — אל "תזכור" שאין תמונה; ננסה שוב ברינדור הבא
  ids.forEach(id => S.avatarCache.set(id, map[id] || null));
  document.querySelectorAll('[data-avatar-id]:not([data-avatar-done])').forEach(el => {
    const id = el.dataset.avatarId;
    if (S.avatarCache.has(id)) applyAvatar(el, S.avatarCache.get(id));
  });
}

// ── cell renderers ──────────────────────────────────────────────────
function renderForum(td, n) {
  const color = S.forumColors[n.forum] || '#8b90a0';
  const span  = document.createElement('span');
  span.className = 'cell-forum';
  // הצבע נשאר כרקע (הוא סימן הזיהוי), אבל לא כצבע הטקסט: צבע פורום בהיר
  // על אותו צבע ב-13% נתן ~2:1 בערכה הבהירה, בכל שורה בטבלה.
  span.style.background = color + '22';
  span.style.color      = 'var(--text)';
  span.style.boxShadow  = 'inset 0 0 0 1px ' + color + '55';
  span.textContent = n.forum || '';
  td.appendChild(span);
}

function renderUsername(td, n) {
  // מיני אווטאר/נקודת צבע לפני השם
  if (n.has_avatar || n.nick_color) {
    const dot = document.createElement('span');
    dot.className = 'uname-dot';
    if (n.has_avatar) {
      dot.classList.add('has-img');
      dot.style.background = safeColor(n.nick_color, 'var(--card2)');
      dot.dataset.avatarId = n.id;   // התמונה נטענת לפי דרישה
    } else {
      dot.style.background = safeColor(n.nick_color, 'var(--card2)');
    }
    td.appendChild(dot);
  }
  const txt = document.createElement('span');
  txt.textContent = n.username || '';
  td.appendChild(txt);
  if (n.conflict_count > 0) {
    const warn = document.createElement('span');
    warn.title   = `${n.conflict_count} התנגשויות מידע`;
    warn.textContent = ' ⚠️';
    warn.style.cursor = 'help';
    td.appendChild(warn);
  }
}

async function showFieldSourcesTooltip(e, nickId, fieldKey) {
  // שמור קואורדינטות מיד — לפני ה-await (אחרת האירוע עלול להתאפס)
  const cx = e.clientX, cy = e.clientY;
  const tok = ttBegin();
  const srcs = await api('get_field_sources', nickId, fieldKey);
  if (!ttValid(tok)) return;      // העכבר כבר עזב
  if (!srcs || srcs.length < 2) return;
  const srcKind = s => s.kind==='me' ? 'אני' : s.kind==='scrape' ? 'סריקה' : s.name;
  const rows = srcs.map((s, i) =>
    `<div style="padding-right:8px">${i===0?'▸':'◦'} ${esc(String(s.value))} <span style="opacity:.65">— ${esc(srcKind(s))}</span></div>`
  ).join('');
  showTooltipAt(cx, cy, `<b>גרסאות לפי מקור:</b>${rows}`);
}

// מונה ריחוף: תשובה שחוזרת אחרי שהעכבר כבר עזב לא תציג טולטיפ יתום
let _ttSeq = 0;
function ttBegin() { return ++_ttSeq; }
function ttValid(token) { return token === _ttSeq; }

function showTooltipAt(cx, cy, html) {
  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.style.display = '';
  tt.style.left = Math.min(cx + 12, window.innerWidth  - 300) + 'px';
  tt.style.top  = Math.min(cy + 12, window.innerHeight - 150) + 'px';
}

// מספרים: LTR ומיושרים, אחרת הם נשברים בתוך טבלה בעברית
function renderNum(td, n) {
  const v = n[td.dataset.col || ''] ?? '';
  td.textContent = v === '' || v === null ? '' : String(v);
  td.dir = 'ltr';
  td.style.textAlign = 'center';
}

function renderRep(td, n) {
  if (!n.reputation) return;
  td.textContent = Number(n.reputation).toLocaleString();
  td.dir = 'ltr';   // אחרת מוניטין שלילי מוצג הפוך ("12-" במקום "-12")
  td.style.textAlign = 'right';
  td.style.color = n.reputation > 100 ? 'var(--success)' : 'inherit';
}

// ── פעולות על טלפון/מייל: וואטסאפ / חיוג / מייל / העתקה ─────────────────
function waLink(phone) {
  let d = String(phone || '').replace(/\D/g, '');
  if (!d) return '';
  if (d.startsWith('0')) d = '972' + d.slice(1);       // ישראל
  return 'https://wa.me/' + d;
}

// חלון משנה עצמאי — לא עובר דרך openModal, שסוגר את החלון הפתוח.
// (לחיצה על טלפון בתוך דיאלוג עריכת ניק הייתה מוחקת את הדיאלוג ואת מה שהוקלד בו.)
function contactMenu(type, value) {
  const v = String(value || '').trim();
  if (!v) return;
  document.getElementById('contact-pop')?.remove();
  const ov = document.createElement('div');
  ov.className = 'modal-overlay';
  ov.id = 'contact-pop';
  ov.style.zIndex = '200';
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  ov.innerHTML = `
    <div class="modal modal-sm">
      <div class="modal-header">
        <div class="modal-title">${type === 'phone' ? '📞 טלפון' : '📧 מייל'}</div>
        <button class="modal-close" id="cp-close">✕</button>
      </div>
      <div class="modal-body">
        <div style="text-align:center;font-size:20px;font-weight:800;padding:14px 0" dir="ltr">${esc(v)}</div>
      </div>
      <div class="modal-footer" id="cp-foot"></div>
    </div>`;
  document.body.appendChild(ov);
  const foot = ov.querySelector('#cp-foot');
  const add = (label, cls, fn) => {
    const b = document.createElement('button');
    b.className = 'btn ' + cls;
    b.textContent = label;
    b.onclick = () => { ov.remove(); if (fn) fn(); };
    foot.appendChild(b);
  };
  if (type === 'phone') {
    add('💬 וואטסאפ', 'btn-primary', () => api('open_url', waLink(v)));
    add('📞 חיוג', 'btn-ghost', () => api('open_url', 'tel:' + v.replace(/[^\d+]/g, '')));
  } else {
    add('📧 שלח מייל', 'btn-primary', () => api('open_url', 'mailto:' + v));
  }
  add('📋 העתק', 'btn-ghost', async () => {
    const r = await api('copy_to_clipboard', v);
    toast(r?.ok ? 'הועתק ✓' : 'ההעתקה נכשלה', r?.ok ? 'success' : 'error');
  });
  add('סגור', 'btn-ghost', null);
  ov.querySelector('#cp-close').onclick = () => ov.remove();
}

function contactSpan(type, value) {
  const s = document.createElement('span');
  s.className = 'contact-link';
  s.textContent = value;
  s.dir = 'ltr';
  s.title = type === 'phone' ? 'וואטסאפ / חיוג / העתקה' : 'שליחת מייל / העתקה';
  s.onclick = e => { e.stopPropagation(); contactMenu(type, value); };
  return s;
}

function renderPhone(td, n) {
  if (n.phone) td.appendChild(contactSpan('phone', n.phone));
  if (n.extra_contacts > 0) {
    const ex = document.createElement('span');
    ex.className = 'cell-extra';
    ex.textContent = '❕';
    ex.title = 'יש פרטי קשר נוספים';
    ex.onmouseenter = e => showContactsTooltip(e, n.id);
    ex.onmouseleave = hideTooltip;
    td.appendChild(ex);
  }
}

function renderEmail(td, n) {
  if (n.email) td.appendChild(contactSpan('email', n.email));
  if (n.extra_contacts > 0 && !n.phone) {
    const ex = document.createElement('span');
    ex.className = 'cell-extra';
    ex.textContent = '❕';
    ex.title = 'יש פרטי קשר נוספים';
    td.appendChild(ex);
  }
}

function renderStatus(td, n) {
  const map = {
    'פעיל':   ['status-active',    '●'],
    'מורחק':  ['status-banned',    '●'],
    'מושעה':  ['status-suspended', '●'],
  };
  const [cls, dot] = map[n.status] || ['', ''];
  if (cls) {
    const span = document.createElement('span');
    span.className = `cell-status ${cls}`;
    span.textContent = `${dot} ${n.status}`;
    td.appendChild(span);
  } else {
    td.textContent = n.status || '';
  }
}

function renderNotes(td, n) {
  if (n.notes) {
    if (n.notes.includes('@')) {
      td.innerHTML = renderTaggedText(n.notes.slice(0, 120));
    } else {
      td.textContent = n.notes.slice(0, 80);
    }
  }
}

function renderPrivate(td, n) {
  if (n.private_notes) {
    td.className = 'cell-private';
    if (n.private_notes.includes('@')) {
      td.innerHTML = renderTaggedText(n.private_notes.slice(0, 90));
    } else {
      td.textContent = n.private_notes.slice(0, 60);
    }
  }
}

function renderIdentity(td, n) {
  if (n.has_identity) {
    const span = document.createElement('span');
    span.className = 'cell-identity';
    span.textContent = '👤 כן';
    span.onmouseenter = e => showIdentityTooltip(e, n.id);
    span.onmouseleave = hideTooltip;
    span.onclick = e => { e.stopPropagation(); openIdentityDialog(n.id); };
    td.appendChild(span);
  }
}

function renderUpdated(td, n) {
  const raw = n.updated_at;
  if (!raw) return;
  td.textContent = relativeTime(raw);
  td.title = raw;
  td.style.color = 'var(--subtext)';
  td.style.fontSize = '12px';
}

function relativeTime(dateStr) {
  // SQLite datetime is UTC "YYYY-MM-DD HH:MM:SS"
  const d = new Date(dateStr.replace(' ', 'T') + 'Z');
  const now = new Date();
  const diff = Math.floor((now - d) / 1000);
  if (isNaN(diff)) return dateStr;
  if (diff < 60) return 'עכשיו';
  // עברית: יחיד/זוגי/רבים ("לפני דקה", "לפני שעתיים", "אתמול")
  const m = Math.floor(diff / 60), h = Math.floor(diff / 3600), dd = Math.floor(diff / 86400);
  if (diff < 3600)   return m === 1 ? 'לפני דקה'  : m === 2 ? 'לפני שתי דקות' : `לפני ${m} דקות`;
  if (diff < 86400)  return h === 1 ? 'לפני שעה'  : h === 2 ? 'לפני שעתיים'  : `לפני ${h} שעות`;
  if (diff < 604800) return dd === 1 ? 'אתמול'    : dd === 2 ? 'לפני יומיים'  : `לפני ${dd} ימים`;
  return d.toLocaleDateString('he-IL');
}

function renderOpenBtn(td, n) {
  // כפתור פתיחת פרופיל היוזר בפורום
  const btn = document.createElement('span');
  btn.textContent = '👤🔗';
  btn.title = `פתח את פרופיל "${n.username}" בפורום`;
  btn.style.cssText = 'font-size:13px;cursor:pointer;user-select:none;white-space:nowrap';
  td.style.textAlign = 'center';

  btn.onclick = (e) => {
    e.stopPropagation();
    openNickProfile(n);
  };
  td.appendChild(btn);
}

function buildProfileUrl(forum, username) {
  const base = (forum.url || '').replace(/\/+$/, '');
  const uname = (username || '').trim();
  // תבנית מפורשת (למשל phpBB: /memberlist.php?...&un={user})
  if (forum.profile_pattern) {
    return base + forum.profile_pattern.replace('{user}', encodeURIComponent(uname));
  }
  const plat = forum.platform || 'nodebb';
  if (plat === 'discourse') return `${base}/u/${encodeURIComponent(uname)}`;
  if (plat === 'nodebb') {
    const slug = uname.replace(/\s+/g, '-');   // NodeBB: /user/שם-משתמש
    return `${base}/user/${encodeURIComponent(slug)}`;
  }
  // פלטפורמה ללא תבנית ידועה — פתח את הפורום עצמו
  return base || '#';
}

function openNickProfile(n) {
  const forum = S.forums.find(f => f.name === n.forum);

  if (!n.forum || n.forum === 'כללי') {
    toast('הניק בפורום "כללי" — אין פורום לפתיחת פרופיל', 'info');
    return;
  }
  if (!forum) {
    toast(`הפורום "${n.forum}" לא נמצא ברשימה`, 'error');
    return;
  }
  if (!forum.url) {
    toast(`לא הוגדר קישור לפורום "${n.forum}" — ניתן להוסיפו בניהול פורומים`, 'info');
    return;
  }
  const profileUrl = buildProfileUrl(forum, n.username);
  api('open_url', profileUrl);
}

// ══ SELECT ════════════════════════════════════════════════════════════
function selectRow(id, e) {
  S.selectedId = id;
  document.querySelectorAll('tbody tr').forEach(tr => {
    tr.classList.toggle('selected', parseInt(tr.dataset.id) === id);
  });
  // גם בתצוגת כרטיסים — אחרת הסימון והבחירה בפועל לא תואמים
  document.querySelectorAll('.nick-card').forEach(c => {
    c.classList.toggle('selected', parseInt(c.dataset.id) === id);
  });
  document.getElementById('btn-edit').disabled   = false;
  document.getElementById('btn-delete').disabled = false;
  if(document.getElementById('stat-sel'))document.getElementById('stat-sel').textContent='1';
}

function editSelected() {
  if (S.selectedId) openNickDialog(S.selectedId);
}

async function deleteSelected() {
  if (!S.selectedId) return;
  const nick = S.nicks.find(n => n.id === S.selectedId);
  if (!nick) return;
  if (!confirm(`להעביר את "${nick.username}" (${nick.forum}) לסל המחזור?\n\n` +
               'אפשר לבטל מיד, או לשחזר מסל המחזור במשך 30 יום.')) return;
  const r = await api('delete_nick', S.selectedId);
  if (!r?.ok) { toast('המחיקה נכשלה: ' + (r?.error || ''), 'error'); return; }
  S.selectedId = null;
  document.getElementById('btn-edit').disabled   = true;
  document.getElementById('btn-delete').disabled = true;
  if(document.getElementById('stat-sel'))document.getElementById('stat-sel').textContent='0';
  await loadNicks(document.getElementById('search-input').value);
  toast(`"${nick.username}" הועבר לסל המחזור`, 'success',
        { actionLabel: '↩ בטל', onAction: () => restoreBatch(r.batch_id) });
}

// שחזור אצוות מחיקה (מה-toast או מדיאלוג סל המחזור)
async function restoreBatch(batchId) {
  if (!batchId) return;
  const r = await api('restore_trash', batchId);
  if (!r?.ok) { toast('השחזור נכשל: ' + (r?.error || ''), 'error'); return; }
  await loadNicks(document.getElementById('search-input').value);
  const extra = r.skipped ? ` (${r.skipped} דולגו — כבר קיימים)` : '';
  toast(`שוחזרו ${r.restored} ניקים ✓${extra}`, 'success');
}

async function openTrash(back) {
  const batches = await api('get_trash') || [];
  const rows = batches.length ? batches.map(b => `
    <div style="display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--border-soft);font-size:13px">
      <div style="flex:1;min-width:0">
        <div><b>${b.count}</b> ניקים · <span style="color:var(--subtext)">${esc(relativeTime(b.deleted_at))}</span></div>
        <div style="color:var(--subtext);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(b.names || '')}</div>
      </div>
      <button class="btn btn-sm btn-primary" data-batch="${esc(b.batch_id)}" onclick="restoreBatch(this.dataset.batch);closeModal()">↩ שחזר</button>
    </div>`).join('')
    : '<div style="padding:24px;text-align:center;color:var(--subtext)">סל המחזור ריק</div>';
  openModal('🗑️ סל מחזור', `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:10px">
      ניקים שנמחקו נשמרים כאן 30 יום, עם אנשי הקשר, הזהויות והיסטוריית המקורות שלהם.
    </p>${rows}`, [
    ...(batches.length ? [{ label: 'רוקן סל', cls: 'btn-danger', action: async () => {
      if (!confirm('לרוקן את סל המחזור לצמיתות?')) return;
      await api('empty_trash'); closeModal(); toast('סל המחזור רוקן', 'info');
    }}] : []),
    ...(typeof back === 'function'
        ? [{ label: '↩ חזרה', cls: 'btn-ghost', action: () => { closeModal(); back(); } }]
        : []),
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
}

// "🩺 המאגר" — החלון הזה מרכז עכשיו את כל מה שנוגע לקובץ עצמו: תקינות, גיבוי
// ושחזור, סל המחזור, התחזוקה והאיפוס. שלושה מהם היו כפתורים נפרדים בתפריט.
//
// והתיקון החשוב: שבעת הכפתורים שישבו כאן ב-footer דרשו 915 פיקסל ברוחב פנוי
// של 426, ומכיוון של-.modal-footer אין flex-wrap — ארבעה מהם צוירו *מחוץ*
// לחלון ונחתכו, בלי פס גלילה ובלי שום רמז שהם קיימים. כלומר "יומן ייבואים",
// "תקן קבוצות זהות" ו"גבה עכשיו" לא היו נגישים בשום דרך. הפעולות ירדו לגוף
// החלון בשורות שנשברות, וב-footer נשאר "סגור" בלבד.
async function openDbHealth() {
  const h = await api('get_db_health');
  const bk = await api('get_backup_status') || {};
  if (!h?.ok) { toast('לא ניתן לקרוא את מצב המאגר: ' + (h?.error || ''), 'error'); return; }
  // בידוד דו-כיווני: בלעדיו "12.4 MB" בתוך משפט עברי מוצג כ-"MB 12.4"
  const mb = b => '⁦' + (b / 1048576).toFixed(1) + ' MB⁩';
  const c = h.counts || {};
  const okQC = h.quick_check === 'ok';
  const row = (k, v) => `<div style="display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid var(--border-soft);font-size:13px">
      <span style="color:var(--subtext)">${k}</span><b dir="ltr">${v}</b></div>`;
  const trashN = c.trash_nicks || 0;

  openModal('🩺 המאגר', `
    <div style="padding:10px 12px;border-radius:8px;margin-bottom:14px;font-size:13px;
         background:var(--card);border-inline-start:3px solid var(${okQC ? '--success' : '--danger'});
         color:var(${okQC ? '--success' : '--danger'})">
      ${okQC ? '✅ בדיקת תקינות עברה' : '⚠️ בדיקת התקינות מצאה בעיה: ' + esc(h.quick_check)}
    </div>

    <div class="section-hdr">📊 מצב</div>
    ${row('גרסה', esc(h.version) + ' · ' + (h.install_type === 'installer' ? 'מותקנת' : 'ניידת'))}
    ${row('גודל הקובץ', mb(h.size))}
    ${row('יומן WAL', mb(h.wal))}
    ${row('ניקים', (c.nicks || 0).toLocaleString())}
    ${row('ערכי מקורות', (c.field_values || 0).toLocaleString())}
    ${row('אנשי קשר / זהויות', `${(c.nick_contacts || 0).toLocaleString()} / ${(c.nick_identities || 0).toLocaleString()}`)}
    ${row('חיפוש מהיר (FTS5)', h.fts ? 'פעיל' : 'לא זמין — LIKE')}
    <div style="font-size:11.5px;color:var(--subtext);margin-top:10px;word-break:break-all" dir="ltr">${esc(h.path)}</div>

    <div class="section-hdr">💾 גיבוי ושחזור</div>
    <label style="display:flex;gap:8px;align-items:center;font-size:12.5px;cursor:pointer;margin-bottom:8px">
      <input type="checkbox" id="bk-on" ${bk.enabled !== false ? 'checked' : ''}
             onchange="api('set_auto_backup', this.checked)">
      גיבוי יומי אוטומטי בהפעלת התוכנה, וגיבוי לפני כל פעולת איפוס
    </label>
    ${row('גיבויים שמורים', `${bk.count || 0} · ${mb(bk.bytes || 0)}`)}
    ${row('גיבוי אחרון', bk.last ? esc(String(bk.last).replace('T', ' ')) : 'עדיין לא')}
    ${(bk.files || []).length ? `
      <div style="max-height:14vh;overflow:auto;margin-top:6px">
        ${(bk.files || []).map(f => `
          <div style="display:flex;justify-content:space-between;gap:8px;font-size:11px;
                      color:var(--subtext);padding:3px 0" dir="ltr">
            <span style="overflow:hidden;text-overflow:ellipsis;min-width:0">${esc(f.name)}</span>
            <span style="flex-shrink:0">${mb(f.bytes)}</span>
          </div>`).join('')}
      </div>` : ''}
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
      <button class="btn btn-sm btn-ghost" onclick="dbhBackupNow()">💾 גבה עכשיו</button>
      <button class="btn btn-sm btn-ghost" onclick="dbhBackupToFile()"
              title="עותק מלא של כל המאגר לקובץ שתבחר">🗄️ גיבוי מלא לקובץ</button>
      <button class="btn btn-sm btn-ghost" onclick="dbhRestore()"
              title="החלפת המאגר בגיבוי שנשמר">♻️ שחזור מגיבוי</button>
    </div>
    <div style="font-size:11px;color:var(--subtext);margin-top:6px;line-height:1.6">
      מהגיבוי האוטומטי נשמרים 3 האחרונים בלבד — עותק מלא שוקל כמו המאגר עצמו.
    </div>

    <div class="section-hdr">🧰 תחזוקה</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn btn-sm btn-ghost" onclick="dbhTrash()"
              title="ניקים שנמחקו — לשחזור עד 30 יום">🗑️ סל מחזור${trashN ? ` (${trashN.toLocaleString()})` : ''}</button>
      <button class="btn btn-sm btn-ghost" onclick="dbhImportLog()">📥 יומן ייבואים</button>
      <button class="btn btn-sm btn-ghost" onclick="dbhRepair()">🔧 תקן קבוצות זהות</button>
      <button class="btn btn-sm btn-ghost" onclick="dbhVacuum()">🧹 כווץ קובץ</button>
      <button class="btn btn-sm btn-ghost" onclick="api('open_data_folder')">📂 תיקיית נתונים</button>
      <button class="btn btn-sm btn-ghost" onclick="api('open_log')">📄 פתח יומן</button>
    </div>

    <div class="section-hdr" style="color:var(--danger);border-bottom-color:var(--danger)">⚠️ אזור מסוכן</div>
    <p style="font-size:12px;color:var(--subtext);line-height:1.6;margin-bottom:8px">
      מחיקת נתונים מהמאגר. גיבוי אוטומטי נוצר לפני הפעולה כשהאפשרות למעלה דלוקה.
    </p>
    <button class="btn btn-sm btn-danger" onclick="dbhReset()">🔴 איפוס נתונים</button>
  `, [{ label: 'סגור', cls: 'btn-ghost', action: closeModal }], '', { id: 'db-health' });
}

// הפעולות יושבות בגוף החלון, ולכן הן צריכות להיות גלובליות (inline onclick).
async function dbhBackupNow() {
  setStatus('מגבה…');
  const r = await api('run_auto_backup', 'manual');
  setStatus('');
  if (r?.ok) { toast(`הגיבוי נשמר ✓ (${(r.bytes / 1048576).toFixed(1)} MB)`, 'success'); closeModal(); openDbHealth(); }
  else toast(r?.error || 'הגיבוי נכשל', 'error');
}
async function dbhBackupToFile() { await backupDb(); }
async function dbhRestore() { await restoreDb(); }
async function dbhVacuum() {
  setStatus('מכווץ את המאגר…');
  const r = await api('vacuum_db');
  setStatus('');
  if (r?.ok) { toast(`המאגר כווץ ✓ (${(r.size / 1048576).toFixed(1)} MB)`, 'success'); closeModal(); openDbHealth(); }
  else toast(r?.error || 'הכיווץ נכשל', 'error');
}
async function dbhRepair() {
  const r = await api('repair_identity_groups');
  if (!r?.ok) { toast(r?.error || 'התיקון נכשל', 'error'); return; }
  toast(r.added ? `${r.added} קישורים חסרים הושלמו ✓` : 'כל קבוצות הזהות תקינות ✓', 'success');
}
function dbhTrash() { closeModal(); openTrash(openDbHealth); }
function dbhImportLog() { closeModal(); openImportLog(openDbHealth); }
function dbhReset() { closeModal(); confirmReset(); }

// ══ בחירה מרובה + מחיקה בפועל ═══════════════════════════════════════════
function toggleRowSelected(id, checked) {
  if (checked) S.multiSelected.add(id);
  else S.multiSelected.delete(id);
  updateBulkBar();
  // עדכן גם את הכרטיס המתאים אם קיים
  const card = document.querySelector(`.nick-card[data-id="${id}"] .card-select-cb`);
  if (card) card.checked = checked;
  const row = document.querySelector(`tr[data-id="${id}"] .row-select-cb`);
  if (row) row.checked = checked;
}

function toggleSelectAll(checked) {
  if (checked) S.nicks.forEach(n => S.multiSelected.add(n.id));
  else S.multiSelected.clear();
  renderTable();
  updateBulkBar();
}

function clearBulkSelection() {
  S.multiSelected.clear();
  renderTable();
  updateBulkBar();
}

function updateBulkBar() {
  const n = S.multiSelected.size;
  const lowerBar = document.getElementById('bulk-bar');
  const cnt2 = document.getElementById('bulk-count2');
  if (lowerBar) lowerBar.style.display = n > 0 ? 'flex' : 'none';
  if (cnt2) cnt2.textContent = n;
  const selAllCb = document.getElementById('select-all-cb');
  if (selAllCb) selAllCb.checked = S.nicks.length > 0 && S.nicks.every(n2 => S.multiSelected.has(n2.id));
}

async function deleteBulkSelected() {
  const ids = [...S.multiSelected];
  if (!ids.length) return;
  if (!confirm(`להעביר ${ids.length} ניקים שנבחרו לסל המחזור?\n\nאפשר לשחזר אותם מסל המחזור (30 יום).`)) return;
  const res = await api('delete_nicks', ids);
  if (!res?.ok) { toast('המחיקה נכשלה: ' + (res?.error || ''), 'error'); return; }
  S.multiSelected.clear();
  S.selectedId = null;
  await loadNicks(document.getElementById('search-input').value);
  toast(`${res.count} ניקים הועברו לסל המחזור`, 'success',
        { actionLabel: '↩ בטל', onAction: () => restoreBatch(res.batch_id) });
}

// ══ SEARCH ════════════════════════════════════════════════════════════
function onSearch(val) {
  clearTimeout(S.searchTimer);
  S.searchTimer = setTimeout(() => {
    loadNicks(val);
    api('set_display_setting', 'last_search', val);   // זיכרון בין הפעלות
  }, 200);
}

// ── מקלדת ─────────────────────────────────────────────────────────────
// Ctrl+F או "/" → חיפוש · Enter בחיפוש → פתח תוצאה ראשונה · חיצים → ניווט בשורות
// Enter → פתח נבחר · Delete → מחק נבחר (עם אישור)
document.addEventListener('keydown', (e) => {
  const inInput = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || '');
  const search = document.getElementById('search-input');
  const modalOpen = !!document.getElementById('modal-overlay') || !!document.getElementById('contact-pop');
  // e.code ולא e.key — בפריסת מקלדת עברית e.key של Ctrl+F הוא 'כ'
  if (!modalOpen && ((e.ctrlKey && e.code === 'KeyF') || (!inInput && e.key === '/'))) {
    e.preventDefault(); search?.focus(); search?.select(); return;
  }
  if (modalOpen) return;
  if (e.target === search) {
    if (e.key === 'Enter' && S.nicks.length) { e.preventDefault(); openNickDialog(S.nicks[0].id); }
    if (e.key === 'ArrowDown' && S.nicks.length) { e.preventDefault(); search.blur(); selectRow(S.nicks[0].id); }
    return;
  }
  if (inInput) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    if (!S.nicks.length) return;
    e.preventDefault();
    const idx = S.nicks.findIndex(n => n.id === S.selectedId);
    const next = Math.min(S.nicks.length - 1, Math.max(0, idx + (e.key === 'ArrowDown' ? 1 : -1)));
    selectRow(S.nicks[next].id);
    document.querySelector(`tr[data-id="${S.nicks[next].id}"], .nick-card[data-id="${S.nicks[next].id}"]`)
      ?.scrollIntoView({ block: 'nearest' });
  } else if (e.key === 'Enter' && S.selectedId) {
    e.preventDefault(); openNickDialog(S.selectedId);
  } else if (e.key === 'Delete' && S.selectedId) {
    e.preventDefault(); deleteSelected();
  }
});

// ── העתקה ללוח ────────────────────────────────────────────────────────
function nickRowText(n, sep = '\t') {
  const hidden = hiddenColsSet();
  return COLS.filter(c => c.key !== '_open' && c.key !== 'identity' && !hidden.has(c.key))
             .map(c => {
               const s = String(n[c.key] ?? '').replace(/[\t\r\n]+/g, ' ');
               // ערך מהפורום שמתחיל ב-= + - @ מורץ כנוסחה כשמדביקים באקסל
               return /^[=+\-@]/.test(s) ? "'" + s : s;
             }).join(sep);
}
async function copySelectedRows() {
  const rows = S.nicks.filter(n => S.multiSelected.has(n.id));
  if (!rows.length) { toast('לא נבחרו ניקים', 'error'); return; }
  const hidden = hiddenColsSet();
  const header = COLS.filter(c => c.key !== '_open' && c.key !== 'identity' && !hidden.has(c.key))
                     .map(c => c.label).join('\t');
  const text = [header, ...rows.map(n => nickRowText(n))].join('\r\n');
  const r = await api('copy_to_clipboard', text);
  toast(r?.ok ? `${rows.length} שורות הועתקו — אפשר להדביק באקסל ✓` : 'ההעתקה נכשלה', r?.ok ? 'success' : 'error');
}
async function copyMergedProfile(p) {
  const lines = [];
  (p.members || []).forEach(m => lines.push(`${m.username} [${m.forum}]`));
  lines.push('');
  (p.fields || []).forEach(f => f.values.forEach(v =>
    lines.push(`${f.label}: ${v.value}` + ((p.members || []).length > 1 ? ` (${v.username})` : ''))));
  (p.contacts || []).forEach(c => lines.push(`${c.type === 'phone' ? 'טלפון' : 'מייל'}: ${c.value}${c.label ? ' (' + c.label + ')' : ''}`));
  const r = await api('copy_to_clipboard', lines.join('\r\n'));
  toast(r?.ok ? 'הפרופיל הועתק ✓' : 'ההעתקה נכשלה', r?.ok ? 'success' : 'error');
}

// ══ STATS ═════════════════════════════════════════════════════════════
function updateStats() {
  document.getElementById('stat-total').textContent = S.total || S.nicks.length;
  // has_info מגיע רק ממסלול get_nicks. filter_nicks_multi לא מחשב אותו, ואז
  // כל השורות נראו "בלי מידע" והמונה הראה 0 על סינון שהחזיר מאות תוצאות.
  const el = document.getElementById('stat-info');
  const known = S.nicks.some(n => n.has_info !== undefined);
  el.textContent = known ? S.nicks.filter(n => n.has_info).length : '—';
  el.title = known ? '' : 'לא מחושב בסינון מתקדם';
}

// ══ NICK DIALOG ═══════════════════════════════════════════════════════
async function openNickDialog(nickId = null) {
  let nick = null;
  if (nickId) {
    nick = await api('get_nick', nickId);
    if (!nick) {   // נמחק בינתיים / שגיאת גשר — אחרת נופל בשקט
      toast('הניק לא נמצא — ייתכן שנמחק', 'error');
      await loadNicks(document.getElementById('search-input').value);
      return;
    }
  }
  const forums = S.forums.map(f =>
    `<option value="${esc(f.name)}" ${nick?.forum===f.name?'selected':''}>${esc(f.name)}</option>`
  ).join('');

  const isNew = !nickId;
  const title = isNew ? '➕ ניק חדש' : `✏️ עריכה: ${nick.username}`;

  // contacts HTML
  const contactsHtml = nick ? renderContactsSection(nick) : '';
  // identities HTML
  const identitiesHtml = nick ? renderIdentitiesSection(nick) : '';
  // conflicts HTML
  const conflictsHtml = nick?.conflicts?.length ? renderConflictsSection(nick.conflicts) : '';
  const shelvedHtml =
    `<div id="field-sources-host">${(nick?.field_sources && Object.keys(nick.field_sources).length)
        ? renderFieldSourcesSection(nick.field_sources, nick.id) : ''}</div>`
    + renderShelvedSection(nick);

  const html = `
    <div class="form-grid">
      <div class="form-group">
        <label class="form-label">פורום</label>
        <div style="display:flex;gap:6px;align-items:center">
          <select class="form-select" id="f-forum" style="flex:1"
                  onchange="updateForumLink(this.value)">${forums}</select>
          <a id="forum-link-btn"
             href="${nick ? (S.forums.find(f=>f.name===nick.forum)?.url||'#') : '#'}"
             target="_blank"
             title="פתח פורום בדפדפן"
             style="display:${nick && S.forums.find(f=>f.name===nick?.forum)?.url ? 'flex' : 'none'};
                    align-items:center;padding:8px 10px;
                    background:var(--card2);border-radius:5px;
                    color:var(--accent);text-decoration:none;font-size:15px;
                    border:1px solid var(--border)"
             onclick="if(this.href==='#'){event.preventDefault()}">🌐</a>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">שם משתמש *</label>
        <input class="form-input" id="f-username" value="${esc(nick?.username||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">שם מלא <span style="font-size:10px;opacity:.6">(מהפורום)</span></label>
        <input class="form-input" id="f-full_name" value="${esc(nick?.full_name||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">שם אמיתי</label>
        <input class="form-input" id="f-real_name" value="${esc(nick?.real_name||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">טלפון ראשי</label>
        <input class="form-input" id="f-phone" value="${esc(nick?.phone||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">מייל ראשי</label>
        <input class="form-input" id="f-email" dir="ltr"
               value="${esc(nick?.email||'')}">
      </div>
      <div class="form-group full">
        <label class="form-label">כתובת</label>
        <input class="form-input tag-field" id="f-address" value="${esc(nick?.address||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">קבוצות</label>
        <input class="form-input" id="f-groups" value="${esc(nick?.groups||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">מוניטין</label>
        <input class="form-input" id="f-reputation" type="number" dir="ltr"
               value="${esc(nick?.reputation ?? 0)}">
      </div>
      <div class="form-group">
        <label class="form-label">סטטוס</label>
        <select class="form-select" id="f-status">
          ${['פעיל','מורחק','מושעה','לא ידוע'].map(s =>
            `<option ${nick?.status===s?'selected':''}>${s}</option>`).join('')}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">תאריך הצטרפות</label>
        <input class="form-input" id="f-join_date" value="${esc(nick?.join_date||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">מספר הודעות</label>
        <input class="form-input" id="f-post_count" value="${esc(nick?.post_count||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">רמת אמינות (1-10)</label>
        <input class="form-input" id="f-trust_level" type="number" min="1" max="10"
               value="${nick?.trust_level||5}">
      </div>
      <div class="form-group full">
        <label class="form-label">קישור לפרופיל (URL)</label>
        <div style="display:flex;gap:6px">
          <input class="form-input" id="f-avatar_url" placeholder="https://..." dir="ltr"
                 value="${esc(nick?.avatar_url||'')}" style="flex:1">
          <a id="profile-link-btn"
             href="${esc(safeUrl(nick?.avatar_url) || '#')}" target="_blank"
             title="פתח פרופיל"
             style="display:${nick?.avatar_url ? 'flex' : 'none'};
                    align-items:center;padding:8px 10px;
                    background:var(--card2);border-radius:5px;
                    color:var(--accent);text-decoration:none;font-size:15px;
                    border:1px solid var(--border)">🌐</a>
        </div>
      </div>
    </div>

    <div class="section-hdr">🎨 מראה הניק</div>
    <div class="appearance-row">
      <div class="avatar-upload" id="avatar-upload-box">
        <div class="avatar-preview" id="avatar-preview">
          ${nick?.avatar_image
            ? `<img src="${esc(nick.avatar_image)}" alt="">`
            : `<span class="avatar-initial" style="background:${esc(safeColor(nick?.nick_color))}">${esc((nick?.username||'?').charAt(0).toUpperCase())}</span>`}
        </div>
        <div class="avatar-controls">
          <input type="file" id="avatar-file" accept="image/*" style="display:none"
                 onchange="handleAvatarUpload(event)">
          <button type="button" class="btn btn-ghost btn-sm"
                  onclick="document.getElementById('avatar-file').click()">📷 העלה תמונה</button>
          <button type="button" class="btn btn-ghost btn-sm" id="avatar-remove"
                  onclick="removeAvatar()"
                  style="display:${nick?.avatar_image?'inline-flex':'none'}">🗑️ הסר</button>
        </div>
        <input type="hidden" id="f-avatar_image" value="${nick?.avatar_image||''}">
      </div>

      <div class="color-picker-box">
        <label class="form-label">צבע הניק</label>
        <div class="nick-color-swatches" id="nick-color-swatches">
          ${nickColorSwatches(nick?.nick_color||'')}
        </div>
        <input type="hidden" id="f-nick_color" value="${esc(nick?.nick_color||'')}">
      </div>
    </div>


    ${contactsHtml}
    ${identitiesHtml}

    <div class="section-hdr">📝 תוכן</div>
    <div class="form-group" style="margin-bottom:12px">
      <label class="form-label accent">פרטים נוספים <span style="font-size:10px;opacity:.6">(@ לתיוג ניק)</span></label>
      <textarea class="form-textarea tag-field" id="f-extra_info">${esc(nick?.extra_info||'')}</textarea>
    </div>
    <div class="form-group" style="margin-bottom:12px">
      <label class="form-label">הערות (מסונכרנות) <span style="font-size:10px;opacity:.6">(@ לתיוג ניק)</span></label>
      <textarea class="form-textarea tag-field" id="f-notes">${esc(nick?.notes||'')}</textarea>
    </div>
    <div class="form-group" style="margin-bottom:12px">
      <label class="form-label warn">🔒 הערות אישיות (לא מיוצאות בברירת מחדל) <span style="font-size:10px;opacity:.6">(@ לתיוג)</span></label>
      <textarea class="form-textarea private tag-field" id="f-private_notes">${esc(nick?.private_notes||'')}</textarea>
    </div>
    <div id="tag-autocomplete" style="display:none;position:absolute;z-index:1000;background:var(--card);
         border:1px solid var(--border-soft);border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,.3);
         max-height:180px;overflow-y:auto;min-width:180px"></div>

    ${conflictsHtml}
    ${shelvedHtml}
    ${nickId ? '<div id="nick-history"></div>' : ''}
  `;

  openModal(title, html, [
    { label: '💾 שמור', cls: 'btn-primary', action: () => saveNick(nickId) },
    // openModal סוגר את החלון הנוכחי כשלב ראשון ואין לו מחסנית — כפתור שפותח
    // חלון נוסף מכאן היה מוחק טופס עריכה פתוח. לכן מדפיסים ישירות.
    ...(nickId ? [{ label: '🖨️ הדפס (ברירות מחדל)', cls: 'btn-ghost', action: () => printProfileNow(nickId) }] : []),
    { label: 'ביטול',   cls: 'btn-ghost',   action: closeModal },
  ], 'modal-lg', { id: 'nick-dialog', dismissable: false });
  if (nickId) api('touch_recent', nickId);

  // wire up contacts
  if (nick) wireContactsSection(nick);
  if (nick) wireIdentitiesSection(nick);
  if (nickId) loadNickHistory(nickId);
}

// ציר זמן: מה השתנה בניק הזה, ממה למה ומתי
async function loadNickHistory(nickId) {
  const box = document.getElementById('nick-history');
  if (!box) return;
  const hist = await api('get_field_history', nickId, 60) || [];
  if (!hist.length) return;
  const label = k => (COLS.find(c => c.key === k)?.label) || k;
  box.innerHTML = `
    <div class="section-hdr">🕒 היסטוריית שינויים</div>
    ${hist.map(h => `
      <div style="display:flex;gap:8px;font-size:12.5px;padding:5px 0;border-bottom:1px solid var(--border-soft)">
        <span style="color:var(--subtext);min-width:92px">${esc(relativeTime(h.changed_at))}</span>
        <b style="min-width:80px">${esc(label(h.field_name))}</b>
        <span style="flex:1"><bdi style="color:var(--subtext)">${esc(h.old_value || '(ריק)')}</bdi>
          ← <bdi><b>${esc(h.new_value || '(ריק)')}</b></bdi></span>
      </div>`).join('')}`;
}

function contactItemHtml(ct, nickId) {
  const icon = ct.type === 'phone' ? '📞' : '📧';
  const priv = ct.is_private
    ? '<span class="ct-priv" title="סודי — לא מסונכרן">🔒</span>'
    : '<span class="ct-priv ct-public" title="גלוי — מסונכרן">🌐</span>';
  const lbl = ct.label ? `<span class="ct-lbl">${esc(ct.label)}</span>` : '';
  return `
    <div class="contact-item" data-cid="${ct.id}">
      <span class="ct-icon">${icon}</span>
      <span class="ct-val contact-link" dir="ltr" data-ctype="${esc(ct.type)}" data-cval="${esc(ct.value)}"
            title="${ct.type === 'phone' ? 'וואטסאפ / חיוג / העתקה' : 'שליחת מייל / העתקה'}">${esc(ct.value)}</span>
      ${lbl}
      ${priv}
      <button class="btn btn-sm btn-ghost btn-icon" title="ערוך"
              onclick="startEditContact(${ct.id},${nickId})">✏️</button>
      <button class="btn btn-sm btn-danger btn-icon" title="מחק"
              onclick="delContact(${ct.id},${nickId})">✕</button>
    </div>`;
}

function contactEditHtml(ct, nickId) {
  return `
    <div class="contact-item contact-edit" data-cid="${ct.id}">
      <select class="form-select" id="edit-type-${ct.id}" style="width:100px">
        <option value="phone" ${ct.type==='phone'?'selected':''}>📞 טלפון</option>
        <option value="email" ${ct.type==='email'?'selected':''}>📧 מייל</option>
      </select>
      <input class="form-input" id="edit-val-${ct.id}" value="${esc(ct.value)}" style="flex:1">
      <input class="form-input" id="edit-lbl-${ct.id}" value="${esc(ct.label||'')}"
             placeholder="כינוי" style="width:110px">
      <label class="ct-priv-toggle" style="white-space:nowrap">
        <input type="checkbox" id="edit-priv-${ct.id}" ${ct.is_private?'checked':''}>
        <span>🔒</span>
      </label>
      <button class="btn btn-sm btn-primary btn-icon" title="שמור"
              onclick="saveEditContact(${ct.id},${nickId})">✓</button>
      <button class="btn btn-sm btn-ghost btn-icon" title="ביטול"
              onclick="refreshContacts(${nickId})">✕</button>
    </div>`;
}

async function startEditContact(contactId, nickId) {
  const nick = await api('get_nick', nickId);
  const ct = (nick.contacts||[]).find(x => x.id === contactId);
  if (!ct) return;
  const row = document.querySelector(`.contact-item[data-cid="${contactId}"]`);
  if (row) row.outerHTML = contactEditHtml(ct, nickId);
}

async function saveEditContact(contactId, nickId) {
  const type  = document.getElementById(`edit-type-${contactId}`)?.value;
  const val   = document.getElementById(`edit-val-${contactId}`)?.value?.trim();
  const label = document.getElementById(`edit-lbl-${contactId}`)?.value?.trim();
  const priv  = document.getElementById(`edit-priv-${contactId}`)?.checked || false;
  if (!val) { toast('הזן ערך', 'error'); return; }
  await api('update_contact', contactId, type, val, label, priv);
  await refreshContacts(nickId);
  toast('פרט קשר עודכן', 'success');
}

async function refreshContacts(nickId) {
  const updated = await api('get_nick', nickId);
  const list = document.getElementById('contact-list');
  if (list) {
    list.innerHTML = (updated.contacts||[]).map(ct => contactItemHtml(ct, nickId)).join('')
      || '<p style="color:var(--subtext);font-size:13px;padding:4px 0">אין פרטים נוספים</p>';
  }
}

function renderContactsSection(nick) {
  const items = (nick.contacts||[]).map(ct => contactItemHtml(ct, nick.id)).join('');
  return `
    <div class="section-hdr">📞 טלפונים ומיילים נוספים</div>
    <div class="contact-list" id="contact-list">${items || '<p style="color:var(--subtext);font-size:13px;padding:4px 0">אין פרטים נוספים</p>'}</div>
    <div class="contact-add-wrap">
      <div class="contact-add-row">
        <select class="form-select" id="ct-type" style="width:110px">
          <option value="phone">📞 טלפון</option>
          <option value="email">📧 מייל</option>
        </select>
        <input class="form-input" id="ct-val" placeholder="מספר / כתובת" style="flex:1">
        <input class="form-input" id="ct-lbl" placeholder="כינוי: נייד / עבודה..." style="width:150px">
      </div>
      <div class="contact-add-row2">
        <label class="ct-priv-toggle">
          <input type="checkbox" id="ct-private">
          <span>🔒 סודי (לא יסונכרן בייצוא)</span>
        </label>
        <button class="btn btn-primary btn-sm" onclick="addContact(${nick.id})">➕ הוסף</button>
      </div>
    </div>`;
}

function wireContactsSection(nick) {}

async function addContact(nickId) {
  const val     = document.getElementById('ct-val')?.value?.trim();
  const type    = document.getElementById('ct-type')?.value;
  const label   = document.getElementById('ct-lbl')?.value?.trim();
  const isPriv  = document.getElementById('ct-private')?.checked || false;
  if (!val) { toast('הזן ערך', 'error'); return; }
  await api('add_contact', nickId, type, val, label, isPriv);
  await refreshContacts(nickId);
  document.getElementById('ct-val').value = '';
  document.getElementById('ct-lbl').value = '';
  document.getElementById('ct-private').checked = false;
}

async function delContact(contactId, nickId) {
  await api('delete_contact', contactId);
  await refreshContacts(nickId);
}

function renderIdentitiesSection(nick) {
  const items = (nick.identities||[]).map(id => `
    <div class="identity-item">
      <span class="id-forum" style="color:${S.forumColors[id.forum]||'#8b90a0'}">[${esc(id.forum)}]</span>
      <span class="id-name">${esc(id.username)}</span>
      <button class="btn btn-sm btn-danger btn-icon"
              onclick="removeIdentity(${nick.id},${id.id})">✕</button>
    </div>`).join('');
  return `
    <div class="section-hdr">👤 זהויות כפולות</div>
    <div class="identity-list" id="identity-list">${items || '<p style="color:var(--subtext);font-size:13px;padding:4px 0">אין</p>'}</div>
    <div style="margin-top:8px">
      <input class="form-input" id="id-search" placeholder="🔍 חפש ניק להוסיף..."
             oninput="searchForIdentity(this.value, ${nick.id})" style="width:100%">
      <div class="search-results" id="id-results" style="display:none"></div>
    </div>`;
}

function wireIdentitiesSection() {}

// ══ תיוג ניקים בטקסט חופשי (@username) ═══════════════════════════════════
let _tagField = null;

// האזנה גלובלית — תופסת כל שדה עם class="tag-field" גם אם נוצר דינמית
let _tagTimer = null, _tagSeq = 0;
document.addEventListener('input', (e) => {
  if (e.target && e.target.classList && e.target.classList.contains('tag-field')) {
    // debounce — בלי זה כל הקשה שלחה בקשה לגשר, והתוצאות חזרו לא לפי הסדר
    clearTimeout(_tagTimer);
    _tagTimer = setTimeout(() => onTagInput(e), 180);
  }
});

document.addEventListener('click', (e) => {
  const pv = e.target.closest('.pick-val');
  if (pv) { pickFieldValue(parseInt(pv.dataset.nid), pv.dataset.field, pv.dataset.value); return; }
  const sr = e.target.closest('.shelf-restore');
  if (sr) { restoreShelved(parseInt(sr.dataset.sid), parseInt(sr.dataset.nid)); return; }
  const prof = e.target.closest('.idm-prof');
  if (prof) { idmProfile(parseInt(prof.dataset.gi)); return; }
  const un = e.target.closest('.idm-unlink');
  if (un) { idmUnlink(parseInt(un.dataset.nid), parseInt(un.dataset.gi)); return; }
  const op = e.target.closest('.idm-open');
  if (op) { closeModal(); openNickDialog(parseInt(op.dataset.nid)); }
});

// ── חיווט מטפלים דרך data-* במקום onclick מוטבע ────────────────────────
// שמות פורומים מיובאים אינם בטוחים: בריחת HTML אינה מגינה על מחרוזת JS בתוך
// מאפיין (הדפדפן מפענח את הישות לפני ש-JS מנתח), ולכן אין לבנות handler מטקסט.
document.addEventListener('click', (e) => {
  const btn = e.target.closest && e.target.closest('.known-add');
  if (btn && typeof window.fmAddKnown === 'function') {
    window.fmAddKnown(btn.dataset.name, btn.dataset.color, btn.dataset.url);
  }
});
document.addEventListener('change', (e) => {
  const sel = e.target.closest && e.target.closest('.fmap-select');
  if (sel && typeof window.fmapOnChange === 'function') {
    window.fmapOnChange(sel, sel.dataset.fname);
  }
});
// קישורי קשר שנבנו ב-innerHTML (דיאלוג הניק, תצוגה מאוחדת) — האצלה לפי data-*
document.addEventListener('click', (e) => {
  const el = e.target.closest && e.target.closest('.contact-link[data-cval]');
  if (el) { e.stopPropagation(); contactMenu(el.dataset.ctype, el.dataset.cval); }
});
// תיוג @: בחירה מההשלמה (mousedown, לפני שה-textarea מאבד פוקוס) ולחיצה/ריחוף על תג
document.addEventListener('mousedown', (e) => {
  const opt = e.target.closest && e.target.closest('.tag-opt');
  if (opt && opt.dataset.username != null) pickTag(e, opt.dataset.username);
});
// capture: רץ לפני onclick של השורה, ו-goToTag עוצר את ההתפשטות כמו קודם
document.addEventListener('click', (e) => {
  const tag = e.target.closest && e.target.closest('.nick-tag');
  if (tag && tag.dataset.tag != null) goToTag(e, tag.dataset.tag);
}, true);
document.addEventListener('mouseover', (e) => {
  const tag = e.target.closest && e.target.closest('.nick-tag');
  if (tag && tag.dataset.tag != null && !(e.relatedTarget && tag.contains(e.relatedTarget))) {
    tagHover(e, tag.dataset.tag);
  }
});
document.addEventListener('mouseout', (e) => {
  const tag = e.target.closest && e.target.closest('.nick-tag');
  if (tag && !(e.relatedTarget && tag.contains(e.relatedTarget))) hideTooltip();
});

async function onTagInput(e) {
  const ta = e.target;
  _tagField = ta;
  const pos = ta.selectionStart;
  const upto = ta.value.slice(0, pos);
  const m = upto.match(/@([^\s@]{1,30})$/);   // @ ואז מילה, עד הסמן
  let box = document.getElementById('tag-autocomplete');
  // ודא שה-dropdown תלוי ישירות ב-body (לא נחתך/מוסתר ע"י המודאל)
  if (box && box.parentElement !== document.body) {
    document.body.appendChild(box);
  }
  if (!box) return;
  box.style.zIndex = '99999';
  if (!m) { box.style.display = 'none'; return; }
  const prefix = m[1];
  const seq = ++_tagSeq;
  const results = await api('search_usernames', prefix, 8) || [];
  if (seq !== _tagSeq) return;   // הגיעה בקשה חדשה יותר — התוצאה הזו מיושנת
  if (!results.length) { box.style.display = 'none'; return; }
  // השם עובר ב-data-username (לא במחרוזת JS מוטבעת) — גרש בשם היה שובר את ה-handler
  box.innerHTML = results.map(r => `
    <div class="tag-opt" style="padding:7px 12px;cursor:pointer;font-size:13px;direction:rtl"
         data-username="${esc(r.username)}">
      <span style="color:${S.forumColors[r.forum]||'#8b90a0'}">[${esc(r.forum)}]</span>
      ${esc(r.username)}
    </div>`).join('');
  const rect = ta.getBoundingClientRect();
  // ב-RTL הסמן יושב בקצה הימני של השדה; עיגון לשמאל פתח את הרשימה
  // מרחק של כמעט רוחב חלון מהמקום שבו מקלידים.
  box.style.left = '';
  box.style.right = (window.innerWidth - rect.right) + 'px';
  box.style.top  = (rect.bottom + 4) + 'px';
  box.style.display = '';
}

function pickTag(e, username) {
  e.preventDefault();
  const ta = _tagField;
  if (!ta) return;
  const pos = ta.selectionStart;
  // רווחים → קו תחתון, כדי שהתיוג יישאר מילה אחת ולא יישבר על רווח
  const tagText = '@' + username.replace(/\s+/g, '_') + ' ';
  const before = ta.value.slice(0, pos).replace(/@[^\s@]*$/, tagText);
  const after = ta.value.slice(pos);
  ta.value = before + after;
  ta.focus();
  const newPos = before.length;
  ta.setSelectionRange(newPos, newPos);
  document.getElementById('tag-autocomplete').style.display = 'none';
}

document.addEventListener('click', (e) => {
  const box = document.getElementById('tag-autocomplete');
  if (box && !e.target.closest('.tag-field') && !e.target.closest('#tag-autocomplete')) {
    box.style.display = 'none';
  }
});

function renderTaggedText(text) {
  if (!text) return '';
  // מפצל טקסט ל-@תיוגים לחיצים ושאר טקסט (בטוח מפני HTML)
  const parts = String(text).split(/(@[^\s@]{1,40})/g);
  return parts.map(p => {
    const m = p.match(/^@([^\s@]{1,40})$/);
    if (m) {
      const raw = m[1];                      // עם קווים תחתונים
      const display = raw.replace(/_/g, ' '); // תצוגה עם רווחים
      // ה-handlers מחוברים בהאצלה לפי data-tag — לא מחרוזת JS מוטבעת (גרש/לוכסן שוברים אותה)
      return `<span class="nick-tag" style="color:var(--accent);cursor:pointer;font-weight:600"
                data-tag="${esc(raw)}">@${esc(display)}</span>`;
    }
    return esc(p);
  }).join('');
}

async function goToTag(e, username) {
  e.stopPropagation();
  const real = username.replace(/_/g, ' ');
  const n = await api('resolve_tag', real);
  if (n && n.id) {
    closeModal();
    openNickDialog(n.id);
  } else {
    toast(`לא נמצא ניק בשם @${real}`, 'error');
  }
}

async function tagHover(e, username) {
  const real = username.replace(/_/g, ' ');
  const n = await api('resolve_tag', real);
  if (n && n.id) {
    const full = await api('get_nick', n.id);
    const bits = [];
    if (full.real_name) bits.push('שם: ' + esc(full.real_name));
    if (full.phone)     bits.push('טלפון: ' + esc(full.phone));
    showTooltip(e, `<b>@${esc(real)}</b> <span style="opacity:.6">[${esc(n.forum)}]</span>` +
      (bits.length ? '<br>' + bits.join('<br>') : ''));
  } else {
    showTooltip(e, `<span style="opacity:.7">@${esc(real)} — לא נמצא</span>`);
  }
}

// חשיפה גלובלית מפורשת — כדי ש-inline handlers ב-HTML שנוצר דינמית תמיד ימצאו אותן
window.onTagInput = onTagInput;
window.pickTag = pickTag;
window.goToTag = goToTag;
window.tagHover = tagHover;
window.renderTaggedText = renderTaggedText;

let _idSearchTimer = null, _idSearchSeq = 0;
function searchForIdentity(q, nickId) {
  clearTimeout(_idSearchTimer);
  _idSearchTimer = setTimeout(() => _searchForIdentityNow(q, nickId), 200);
}

async function _searchForIdentityNow(q, nickId) {
  const box = document.getElementById('id-results');
  if (!box) return;
  if (!q.trim()) { box.style.display = 'none'; return; }
  const seq = ++_idSearchSeq;
  const res   = await api('get_nicks', q, 0, 50);
  const nicks = res && Array.isArray(res.rows) ? res.rows : (Array.isArray(res) ? res : []);
  const nick  = await api('get_nick', nickId);
  if (seq !== _idSearchSeq || !nick) return;   // תשובה מיושנת / הניק נעלם
  const linked = new Set((nick.identities||[]).map(i => i.id));
  linked.add(nickId);
  const results = nicks.filter(n => !linked.has(n.id)).slice(0, 20);
  if (!results.length) { box.style.display = 'none'; return; }
  box.style.display = '';
  box.innerHTML = results.map(n => `
    <div class="search-result-item" onclick="addIdentity(${nickId},${n.id})">
      <span style="color:${S.forumColors[n.forum]||'#8b90a0'}">[${esc(n.forum)}]</span>
      <span style="font-weight:600;margin-right:6px">${esc(n.username)}</span>
    </div>`).join('');
}

async function addIdentity(nickIdA, nickIdB) {
  await api('add_identity', nickIdA, nickIdB);
  document.getElementById('id-search').value = '';
  document.getElementById('id-results').style.display = 'none';
  const updated = await api('get_nick', nickIdA);
  refreshIdentityList(updated, nickIdA);
}

async function removeIdentity(nickIdA, nickIdB) {
  await api('remove_identity', nickIdA, nickIdB);
  const updated = await api('get_nick', nickIdA);
  refreshIdentityList(updated, nickIdA);
}

function refreshIdentityList(nick, nickId) {
  const list = document.getElementById('identity-list');
  if (!list) return;
  list.innerHTML = (nick.identities||[]).map(id => `
    <div class="identity-item">
      <span class="id-forum" style="color:${S.forumColors[id.forum]||'#8b90a0'}">[${esc(id.forum)}]</span>
      <span class="id-name">${esc(id.username)}</span>
      <button class="btn btn-sm btn-danger btn-icon"
              onclick="removeIdentity(${nickId},${id.id})">✕</button>
    </div>`).join('') || '<p style="color:var(--subtext);font-size:13px;padding:4px 0">אין</p>';
}

function renderConflictsSection(conflicts) {
  return `
    <div class="section-hdr" style="color:var(--warn)">⚠️ התנגשויות מידע</div>
    ${conflicts.map(c => `
      <div class="conflict-item">
        <button class="btn btn-sm btn-ghost" onclick="resolveConflict(${c.id})">✕ סגור</button>
        <div>
          <div><span class="conflict-field">${esc(c.field_name)}: </span>
               <span class="conflict-val">${esc(c.conflicting_value)}</span></div>
          <div class="conflict-src">מקור: ${esc(c.source_info)}</div>
        </div>
      </div>`).join('')}`;
}

async function resolveConflict(conflictId) {
  await api('delete_conflict', conflictId);
  const el = document.querySelector(`.conflict-item button[onclick="resolveConflict(${conflictId})"]`)
               ?.closest('.conflict-item');
  if (el) el.remove();
  await loadNicks(document.getElementById('search-input').value);
}

function renderFieldSourcesSection(fieldSources, nickId) {
  const fieldLabel = k => (COLS.find(c => c.key===k)?.label) || k;
  const srcKind = s => s.kind==='me' ? '👤 אני' : s.kind==='scrape' ? '🌐 סריקה' : `📥 ${esc(s.name)}`;
  const blocks = Object.entries(fieldSources).map(([field, srcs]) => {
    // המנצח מסומן בצד השרת (is_winner). אי אפשר להסיק אותו ממיון האמינות:
    // לסטטוס ולמוניטין יש כללים משלהם, והפאנל היה מציג את ההפך מהמוצג בפועל.
    // ערכים זהים ממקורות שונים מקובצים לשורה אחת.
    const byValue = new Map();
    for (const sr of srcs) {
      const k = String(sr.value ?? '').trim();
      if (!byValue.has(k)) byValue.set(k, { value: sr.value, srcs: [], win: false });
      const e = byValue.get(k);
      e.srcs.push(sr);
      if (sr.is_winner) e.win = true;
    }
    const entries = [...byValue.values()];
    if (!entries.some(e => e.win) && entries.length) entries[0].win = true;   // גיבוי
    entries.sort((a, b) => (b.win ? 1 : 0) - (a.win ? 1 : 0));
    return `
      <div class="conflict-item" style="display:block">
        <div style="font-weight:700;font-size:12.5px;margin-bottom:4px">
          ${esc(fieldLabel(field))}
          <span title="מידע סותר מכמה מקורות" style="cursor:help">⚠️</span>
        </div>
        ${entries.map(e => {
          const tags = e.srcs.map(x => `${srcKind(x)}${x.absolute ? ', אבסולוטי' : `, אמינות ${x.trust}`}`).join(' · ');
          return e.win
            ? `<div style="font-size:12.5px;margin-bottom:3px">
                 <span style="color:var(--success)">▸ מוצג:</span> ${esc(e.value)}
                 <span style="color:var(--subtext);font-size:11px"> (${tags})</span></div>`
            : `<div style="font-size:12px;color:var(--subtext);padding-right:14px;
                      display:flex;gap:6px;align-items:center">
                 <span style="flex:1">◦ ${esc(e.value)}
                   <span style="font-size:11px">(${tags})</span></span>
                 <button class="btn btn-sm btn-ghost pick-val" data-nid="${nickId}"
                         data-field="${esc(field)}" data-value="${esc(e.value)}"
                         style="font-size:10.5px;padding:1px 7px">השתמש בזה</button>
               </div>`;
        }).join('')}
      </div>`;
  }).join('');
  return `
    <div class="section-hdr" style="color:var(--subtext)">⚠️ מידע לפי מקור (אבות)</div>
    <p style="font-size:11.5px;color:var(--subtext);margin-bottom:8px">
      שדות עם יותר ממקור אחד. המוצג נבחר לפי האמינות הגבוהה — "השתמש בזה" רושם את
      הערך על שמך כדי שהוא ינצח, בלי למחוק את השאר.
    </p>
    ${blocks}`;
}

async function pickFieldValue(nickId, field, value) {
  const r = await api('pick_field_value', nickId, field, value);
  if (!r?.ok) { toast(r?.error || 'לא ניתן לבחור את הערך', 'error', { ms: 7000 }); return; }
  toast('הערך נבחר ✓', 'success');
  const fresh = await api('get_nick', nickId);
  if (!fresh) return;
  const el = document.getElementById(`f-${field}`);
  if (el) el.value = fresh[field] ?? '';
  const host = document.getElementById('field-sources-host');
  if (host) host.innerHTML = (fresh.field_sources && Object.keys(fresh.field_sources).length)
    ? renderFieldSourcesSection(fresh.field_sources, nickId) : '';
}

// ── ערכים "על המדף" — נשמרו בהחלפה הפיכה, ועד עכשיו לא הוצגו בשום מקום ──
function renderShelvedSection(nick) {
  const rows = nick?.shelved || [];
  if (!rows.length) return '';
  const fieldLabel = k => (COLS.find(c => c.key === k)?.label) || k;
  return `
    <div class="section-hdr" style="color:var(--subtext)">📥 ערכים על המדף</div>
    <p style="font-size:11.5px;color:var(--subtext);margin-bottom:8px">
      ערכים שהוחלפו בעבר ונשמרו בצד. "החזר" מציב את הערך הזה כמוצג, והנוכחי יורד למדף.
    </p>
    ${rows.map(r => `
      <div class="conflict-item" style="display:flex;gap:6px;align-items:center">
        <span style="flex:1;font-size:12.5px">
          <b>${esc(fieldLabel(r.field_name))}:</b> ${esc(r.value)}
          <span style="color:var(--subtext);font-size:11px">
            (${esc(r.source_name || 'לא ידוע')}${r.source_trust ? `, אמינות ${esc(r.source_trust)}` : ''})</span>
        </span>
        <button class="btn btn-sm btn-ghost shelf-restore" data-sid="${r.id}" data-nid="${nick.id}"
                style="font-size:10.5px;padding:1px 7px">↩ החזר</button>
      </div>`).join('')}`;
}

async function restoreShelved(shelvedId, nickId) {
  const r = await api('promote_shelved_value', shelvedId);
  if (!r?.ok) { toast(r?.error || 'ההחזרה נכשלה', 'error'); return; }
  toast('הערך הוחזר ✓', 'success');
  closeModal();
  openNickDialog(nickId);
}

async function saveNick(nickId) {
  // update profile link button live
  const profileInput = document.getElementById('f-avatar_url');
  const profileBtn   = document.getElementById('profile-link-btn');
  if (profileInput && profileBtn) {
    const url = profileInput.value.trim();
    profileBtn.href         = url || '#';
    profileBtn.style.display= url ? 'flex' : 'none';
  }

  const fields = ['forum','username','real_name','full_name','phone','email','groups',
                  'reputation','address','status','join_date','post_count','trust_level',
                  'extra_info','notes','private_notes','avatar_url','nick_color','avatar_image'];
  const data = {};
  for (const f of fields) {
    const el = document.getElementById('f-' + f);
    if (el) data[f] = el.value;
  }
  if (!data.username?.trim()) { toast('שם משתמש הוא שדה חובה', 'error'); return; }

  if (nickId) {
    const r = await api('update_nick', nickId, data);
    if (!r?.ok) {   // אל תסגור ואל תדווח הצלחה כשהשמירה נכשלה
      toast('השמירה נכשלה: ' + (r?.error || 'שגיאה לא ידועה'), 'error');
      return;
    }
    S.avatarCache.delete(String(nickId));   // ייתכן שהתמונה הוחלפה
    toast('ניק עודכן ✓', 'success');
  } else {
    const res = await api('create_nick', data);
    if (!res?.ok) {
      toast('ההוספה נכשלה: ' + (res?.error || 'שגיאה לא ידועה'), 'error');
      return;
    }
    toast('ניק נוסף ✓', 'success');
  }
  closeModal();
  await loadNicks(document.getElementById('search-input').value);
}

// ══ IDENTITY DIALOG ═══════════════════════════════════════════════════
function openIdentityDialog(nickId) {
  openNickDialog(nickId); // opens full dialog, identity section is there
}

// ══ USER LOOKUP — תצוגת משתמש מאוחדת (כל הזהויות המקושרות) ═══════════════
let _lookupTimer = null;

function openUserLookup() {
  openModal('🔎 תצוגת משתמש', `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:10px">
      הקלד שם משתמש או שם אמיתי — התצוגה תרכז את כל המידע על אותו אדם, כולל מכל הזהויות המקושרות אליו בפורומים השונים.
    </p>
    <div class="search-wrap" style="max-width:none;margin-bottom:10px">
      <span class="search-icon">🔍</span>
      <input type="text" id="lookup-input" placeholder="שם משתמש / שם אמיתי..." autocomplete="off"
             oninput="onLookupInput(this.value)">
    </div>
    <div id="lookup-results" style="max-height:150px;overflow-y:auto;margin-bottom:6px"></div>
    <div id="lookup-profile"></div>
  `, [
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
  setTimeout(() => {
    document.getElementById('lookup-input')?.focus();
    const box = document.getElementById('lookup-results');
    if (box) renderRecentInto(box);
  }, 60);
}

function onLookupInput(val) {
  clearTimeout(_lookupTimer);
  _lookupTimer = setTimeout(() => lookupSearch(val), 200);
}

async function lookupSearch(query) {
  const box = document.getElementById('lookup-results');
  if (!box) return;
  if (!query.trim()) { renderRecentInto(box); return; }
  const rows = await api('lookup_nicks', query, 12) || [];
  if (!rows.length) {
    box.innerHTML = '<div style="padding:10px;color:var(--subtext);font-size:13px">לא נמצאו ניקים</div>';
    return;
  }
  box.innerHTML = rows.map(n => `
    <div class="search-result-item" onclick="showMergedProfile(${n.id})">
      <span style="color:${S.forumColors[n.forum] || '#8b90a0'}">[${esc(n.forum)}]</span>
      <span style="font-weight:600;margin-right:6px">${esc(n.username)}</span>
      ${n.real_name ? `<span style="color:var(--subtext);font-size:12px;margin-right:6px">· ${esc(n.real_name)}</span>` : ''}
    </div>`).join('');
}

// הרשימה שהייתה חלון נפרד ("🕘 נצפו לאחרונה"): עכשיו זו המצב הריק של החיפוש.
async function renderRecentInto(box) {
  const rows = await api('get_recent_views', 12) || [];
  if (!box.isConnected) return;
  if (!rows.length) {
    box.innerHTML = '<div style="padding:10px;color:var(--subtext);font-size:12.5px">' +
                    'עדיין לא נפתח אף ניק.</div>';
    return;
  }
  box.innerHTML = `<div style="font-size:11px;color:var(--subtext);padding:4px 2px 6px;
        display:flex;justify-content:space-between;align-items:center">
      <span>🕘 נצפו לאחרונה</span>
      <button class="btn btn-ghost btn-sm" style="padding:2px 8px;font-size:11px"
              onclick="clearRecentFromLookup()">🧹 נקה</button>
    </div>` + rows.map(n => `
    <div class="search-result-item" onclick="showMergedProfile(${n.id})">
      <span style="color:${esc(safeColor(S.forumColors[n.forum], '#8b90a0'))}">[${esc(n.forum)}]</span>
      <span style="font-weight:600;margin-right:6px">${esc(n.username)}</span>
      ${n.real_name ? `<span style="color:var(--subtext);font-size:12px;margin-right:6px">· ${esc(n.real_name)}</span>` : ''}
      <span style="margin-inline-start:auto;color:var(--subtext);font-size:11px">
        ${esc(relativeTime(String(n.viewed_at).replace(' ', 'T')))}</span>
    </div>`).join('');
}

async function clearRecentFromLookup() {
  await api('clear_recent_views');
  const box = document.getElementById('lookup-results');
  if (box) renderRecentInto(box);
}

async function showMergedProfile(nickId) {
  const box = document.getElementById('lookup-profile');
  const results = document.getElementById('lookup-results');
  if (results) results.innerHTML = '';
  if (box) box.innerHTML = '<div style="padding:14px;color:var(--subtext)">טוען…</div>';
  const p = await api('get_merged_profile', nickId);
  if (!p) { if (box) box.innerHTML = '<div style="padding:14px;color:var(--danger)">לא נמצא</div>'; return; }
  if (box) box.innerHTML =
    `<div style="text-align:left;margin-bottom:6px">
       <button class="btn btn-sm btn-ghost" onclick="openPrintDialog(${nickId})">🖨️ פרופיל להדפסה</button>
     </div>` + renderMergedProfile(p);
  S.lastMergedProfile = p;
  api('touch_recent', nickId);
}

function renderMergedProfile(p) {
  const members = p.members || [];
  const primary = members[0] || {};
  const initial = esc((primary.username || '?').charAt(0).toUpperCase());
  // nick_color/avatar_image מגיעים מהפורום (לא בטוחים) — חובה esc בתוך innerHTML
  const avatarBg = esc(safeColor(primary.nick_color,
                       S.forumColors[primary.forum] || 'var(--accent)'));
  const avatarHtml = primary.avatar_image
    ? `<img src="${esc(primary.avatar_image)}" style="width:100%;height:100%;object-fit:cover">`
    : `<span style="width:100%;height:100%;display:grid;place-items:center;font-size:22px;font-weight:800;color:${fgOn(avatarBg)};background:${avatarBg}">${initial}</span>`;

  // צ'יפים לכל זהות (עם פתיחת פרופיל)
  const memberChips = members.map(m => `
    <span class="lookup-chip" onclick='openMergedMember(${m.id})' title="פתח לעריכה"
          style="display:inline-flex;align-items:center;gap:5px;background:var(--card2);
                 border:1px solid var(--border-soft);border-radius:999px;padding:4px 11px;
                 font-size:12px;cursor:pointer;margin:0 0 6px 6px">
      <span style="width:8px;height:8px;border-radius:50%;background:${S.forumColors[m.forum] || '#8b90a0'}"></span>
      <b>${esc(m.username)}</b>
      <span style="color:var(--subtext)">${esc(m.forum)}</span>
    </span>`).join('');

  // שדות מאוחדים
  const fieldRows = (p.fields || []).map(f => {
    const vals = f.values.map(v => {
      const attribution = members.length > 1
        ? `<span style="color:var(--subtext);font-size:11px"> — ${esc(v.username)} [${esc(v.forum)}]</span>` : '';
      const disp = String(v.value).includes('@') ? renderTaggedText(v.value) : esc(v.value);
      return `<div style="padding:2px 0">${disp}${attribution}</div>`;
    }).join('');
    return `
      <div style="display:flex;gap:12px;padding:9px 0;border-bottom:1px solid var(--border-soft)">
        <div style="min-width:110px;color:var(--subtext);font-size:12px;font-weight:700">${esc(f.label)}</div>
        <div style="flex:1;font-size:13.5px">${vals}</div>
      </div>`;
  }).join('');

  const contactsHtml = (p.contacts || []).length ? `
    <div class="section-hdr" style="margin-top:16px">📞 אנשי קשר</div>
    ${p.contacts.map(c => `
      <div style="display:flex;gap:8px;align-items:center;font-size:13px;padding:4px 0">
        <span>${c.type === 'phone' ? '📞' : '📧'}</span>
        <b class="contact-link" dir="ltr" data-ctype="${esc(c.type)}" data-cval="${esc(c.value)}">${esc(c.value)}</b>
        ${c.label ? `<span style="color:var(--subtext);font-size:11px">${esc(c.label)}</span>` : ''}
        ${c.is_private ? '<span title="סודי">🔒</span>' : ''}
        <span style="color:var(--subtext);font-size:11px;margin-right:auto">${esc(c.username)} [${esc(c.forum)}]</span>
      </div>`).join('')}` : '';

  return `
    <div style="border:1px solid var(--border-soft);border-radius:14px;padding:16px;background:var(--card)">
      <div style="display:flex;align-items:center;gap:14px;margin-bottom:12px">
        <div style="width:56px;height:56px;border-radius:16px;overflow:hidden;box-shadow:var(--shadow-sm);flex-shrink:0">${avatarHtml}</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:18px;font-weight:800">${esc(primary.username || '')}</div>
          <div style="font-size:12px;color:var(--subtext)">
            ${members.length > 1 ? `${members.length} זהויות מקושרות` : 'זהות אחת'}
          </div>
        </div>
      </div>
      <div style="margin-bottom:6px;display:flex;flex-wrap:wrap;align-items:center">${memberChips}
        <button class="btn btn-ghost btn-sm" style="margin-right:auto" onclick="copyMergedProfile(S.lastMergedProfile)">📋 העתק פרופיל</button>
      </div>
      ${fieldRows ? `<div style="margin-top:6px">${fieldRows}</div>`
                  : '<div style="color:var(--subtext);font-size:13px;padding:8px 0">אין פרטים מלאים לניק זה</div>'}
      ${contactsHtml}
    </div>`;
}

function openMergedMember(nickId) {
  closeModal();
  openNickDialog(nickId);
}

// ══ FORUM MANAGER ════════════════════════════════════════════════════
async function openForumMgr() {
  await loadForums();
  let selectedForum = null;

  const renderList = () => {
    if (!S.forums.length) return '<p style="color:var(--subtext);padding:8px 0">אין פורומים. הוסף מהרשימה למטה.</p>';
    return S.forums.map(f => `
      <div class="forum-item ${selectedForum?.id===f.id?'selected':''}"
           onclick="fmSelect(${f.id})" data-fid="${f.id}">
        <span class="forum-dot" style="background:${f.color};color:${f.color}"></span>
        <span class="forum-name">${esc(f.name)}</span>
        <span style="flex:1"></span>
        ${f.url
          ? `<a href="${esc(f.url)}" target="_blank" title="פתח: ${esc(f.url)}"
                style="color:var(--accent);font-size:14px;text-decoration:none;padding:2px 6px"
                onclick="event.stopPropagation()">🔗</a>`
          : `<span style="font-size:11px;color:var(--subtext);padding:2px 6px"
                   title="אין קישור — בחר פורום ועדכן">🔗</span>`}
        <input type="color" value="${f.color}" title="שנה צבע"
               style="width:26px;height:26px;border:none;background:none;cursor:pointer;padding:0"
               onclick="event.stopPropagation()"
               onchange="fmColor(${f.id}, this.value)">
        <button class="btn btn-sm btn-danger btn-icon" title="מחק פורום"
                onclick="event.stopPropagation();fmDeleteById(${f.id})">✕</button>
      </div>`).join('');
  };

  const renderKnown = (known) => {
    if (!known.length) return '<p style="color:var(--subtext);font-size:12px">הרשימה ריקה</p>';
    return known.map(f => {
      const isActive = f.active;
      return `
        <div class="forum-item" style="cursor:default;${isActive ? 'opacity:.6' : ''}">
          <span class="forum-dot" style="background:${f.color};color:${f.color}"></span>
          <span class="forum-name" style="font-size:13px">${esc(f.name)}</span>
          ${f.url ? `<a href="${esc(f.url)}" target="_blank"
             style="color:var(--subtext);font-size:11px;margin-right:auto;text-decoration:none;
                    flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px">
            ${esc(f.url.replace(/https?:\/\//,'').slice(0,30))}
          </a>` : '<span style="flex:1"></span>'}
          ${isActive
            ? `<span style="font-size:11px;color:var(--success);padding:3px 8px;
                            background:rgba(63,185,80,.12);border-radius:10px">✓ קיים</span>`
            : `<button class="btn btn-sm btn-primary btn-icon known-add"
                       data-name="${esc(f.name)}" data-color="${esc(f.color)}"
                       data-url="${esc(f.url||'')}">➕</button>`
          }
        </div>`;
    }).join('');
  };

  let knownForums = await api('get_known_forums') || [];

  const buildHtml = () => `
    <div style="font-size:12px;font-weight:700;color:var(--subtext);margin-bottom:6px">פורומים פעילים</div>
    <div class="forum-list" id="forum-list">${renderList()}</div>

    <div style="margin-top:12px;display:flex;gap:6px;align-items:center">
      <input class="form-input" id="rename-val" placeholder="שם חדש לפורום שנבחר" style="flex:1">
      <input class="form-input" id="rename-url" placeholder="קישור (URL)" dir="ltr" style="flex:1">
      <button class="btn btn-ghost btn-sm" onclick="fmRename()">✏️ שמור</button>
    </div>

    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:14px">
      <div style="font-size:12px;font-weight:700;color:var(--subtext);margin-bottom:8px">
        ➕ הוסף פורום חדש
      </div>
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
        <input class="form-input" id="new-forum-name" placeholder="שם"
               style="flex:1" oninput="fmAutoFill(this.value)">
        <input class="form-input" id="new-forum-url" placeholder="קישור (אופציונלי)" dir="ltr" style="flex:1">
        <input type="color" id="new-forum-color" value="#58a6ff"
               style="width:34px;height:34px;border:none;background:none;cursor:pointer;padding:0">
        <button class="btn btn-primary btn-sm" onclick="fmAdd()">הוסף</button>
      </div>
      <div id="fmAutofillMsg" style="font-size:11px;color:var(--success);
           min-height:16px;padding-bottom:4px"></div>
    </div>

    <div style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px">
      <div style="font-size:12px;font-weight:700;color:var(--subtext);margin-bottom:8px">
        📋 פורומים מוכרים — לחץ ➕ להוספה מהירה
      </div>
      <div class="forum-list" id="known-list">${renderKnown(knownForums)}</div>
    </div>`;

  const refreshLists = async () => {
    await loadForums();
    knownForums = await api('get_known_forums') || [];
    const fl = document.getElementById('forum-list');
    const kl = document.getElementById('known-list');
    if (fl) fl.innerHTML = renderList();
    if (kl) kl.innerHTML = renderKnown(knownForums);
  };

  window.fmSelect = (id) => {
    selectedForum = S.forums.find(f => f.id === id);
    document.querySelectorAll('#forum-list .forum-item').forEach(el => {
      el.classList.toggle('selected', parseInt(el.dataset.fid) === id);
    });
    if (selectedForum) {
      const rv = document.getElementById('rename-val');
      const ru = document.getElementById('rename-url');
      if (rv) rv.value = selectedForum.name;
      if (ru) ru.value = selectedForum.url || '';
    }
  };

  window.fmColor = async (id, color) => {
    const f = S.forums.find(f => f.id === id);
    if (!f) return;
    await api('update_forum', id, f.name, color, f.url||'');
    await refreshLists();
    // צביעה מחדש מקומית — שינוי צבע לא מצדיק טעינה מחדש של כל המאגר
    S.forumColors[f.name] = color;
    renderTable();
  };

  window.fmAutoFill = async (val) => {
    if (!val.trim()) {
      document.getElementById('fmAutofillMsg').textContent = '';
      return;
    }
    const resolved = await api('resolve_forum_data', val.trim());
    const msg = document.getElementById('fmAutofillMsg');
    if (resolved && (resolved.url || resolved.color !== '#8b90a0')) {
      // מילוי אוטומטי
      const urlEl   = document.getElementById('new-forum-url');
      const colorEl = document.getElementById('new-forum-color');
      if (urlEl   && !urlEl.value   && resolved.url)   urlEl.value   = resolved.url;
      if (colorEl && resolved.color !== '#8b90a0') colorEl.value = resolved.color;
      if (msg) msg.textContent = resolved.url
        ? `✓ נמצא ברשימה המוכרת — קישור וצבע הוזנו אוטומטית`
        : '';
    } else {
      if (msg) msg.textContent = '';
    }
  };

  window.fmAdd = async () => {
    const name  = document.getElementById('new-forum-name')?.value.trim();
    const url   = document.getElementById('new-forum-url')?.value.trim();
    const color = document.getElementById('new-forum-color')?.value || '#58a6ff';
    if (!name) { toast('נדרש שם פורום', 'error'); return; }
    await api('add_forum', name, color, url);
    document.getElementById('new-forum-name').value = '';
    document.getElementById('new-forum-url').value  = '';
    document.getElementById('new-forum-color').value = '#58a6ff';
    const msg = document.getElementById('fmAutofillMsg');
    if (msg) msg.textContent = '';
    await refreshLists();
    await loadNicks(document.getElementById('search-input').value);
    toast('פורום נוסף ✓', 'success');
  };

  window.fmAddKnown = async (name, color, url) => {
    await api('add_forum', name, color, url);
    await refreshLists();
    await loadNicks(document.getElementById('search-input').value);
    toast(`"${name}" נוסף ✓`, 'success');
  };

  window.fmRename = async () => {
    if (!selectedForum) { toast('בחר פורום מהרשימה', 'error'); return; }
    const name = document.getElementById('rename-val')?.value.trim();
    const url  = document.getElementById('rename-url')?.value.trim() || selectedForum.url || '';
    if (!name) { toast('נדרש שם', 'error'); return; }
    await api('update_forum', selectedForum.id, name, selectedForum.color, url);
    selectedForum = null;
    await refreshLists();
    await loadNicks(document.getElementById('search-input').value);
    toast('פורום עודכן ✓', 'success');
  };

  window.fmDeleteById = async (id) => {
    const f = S.forums.find(f => f.id === id);
    if (!f) return;
    const countRes = await api('count_nicks_in_forum', id);
    const count = countRes?.count || 0;
    let msg = `למחוק את "${f.name}"?`;
    if (count > 0) {
      msg = `⚠️ לפורום "${f.name}" יש ${count} ניקים פעילים.
אם תמחק — הם יועברו אוטומטית לפורום "כללי".

להמשיך?`;
    }
    if (!confirm(msg)) return;
    await api('delete_forum', id, true);
    if (selectedForum?.id === id) selectedForum = null;
    await refreshLists();
    await loadNicks(document.getElementById('search-input').value);
    toast(count > 0 ? `פורום נמחק, ${count} ניקים הועברו ל"כללי"` : 'פורום נמחק', 'info');
  };

  openModal('🏛️ ניהול פורומים', buildHtml(), [
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
}

// ══ SYNC MANAGER ══════════════════════════════════════════════════════
// ══ חיפוש / סינון מתקדם — על הממשק הראשי ═══════════════════════════════
let _fieldFilterActive = false;
let _filterFields = [];

async function toggleFilterBar() {
  const bar = document.getElementById('filter-bar');
  const showing = bar.style.display === 'flex';
  if (showing) {
    bar.style.display = 'none';
    if (_fieldFilterActive) clearFieldFilter();
    return;
  }
  if (!_filterFields.length) {
    _filterFields = await api('get_filterable_fields') || [];
  }
  bar.style.display = 'flex';
  const rows = document.getElementById('filter-rows');
  if (rows && !rows.children.length) addFilterRow();
  refreshSavedFilters();
}

// ── סינונים שמורים ────────────────────────────────────────────────────
async function refreshSavedFilters() {
  const box = document.getElementById('saved-filters');
  if (!box) return;
  const items = await api('get_saved_filters') || [];
  box.innerHTML = items.map((f, i) => `
    <span class="saved-filter" style="background:var(--card2);border-radius:999px;padding:3px 10px;font-size:12px;cursor:pointer"
          onclick="applySavedFilter(${i})" title="החל סינון">${esc(f.name)}
      <b style="color:var(--subtext);margin-right:4px" onclick="event.stopPropagation();removeSavedFilter(${i})">✕</b>
    </span>`).join('');
  _savedFilters = items;
}
let _savedFilters = [];

async function applySavedFilter(i) {
  const f = _savedFilters[i];
  if (!f) return;
  const rows = document.getElementById('filter-rows');
  rows.innerHTML = '';
  for (const c of f.conditions) {
    addFilterRow();
    const row = rows.lastElementChild;
    row.querySelector('.flt-field').value = c.field;
    row.querySelector('.flt-op').value = c.op;
    row.querySelector('.flt-value').value = c.value || '';
    onFilterOpChange(row.querySelector('.flt-op'));
  }
  await applyFieldFilter();
}

async function saveCurrentFilter() {
  const conditions = [...document.querySelectorAll('#filter-rows .filter-row')].map(r => ({
    field: r.querySelector('.flt-field').value,
    op: r.querySelector('.flt-op').value,
    value: r.querySelector('.flt-value').value.trim(),
  })).filter(c => c.op === 'empty' || c.op === 'not_empty' || c.value);
  if (!conditions.length) { toast('אין תנאים לשמור', 'error'); return; }
  // דיאלוג משלנו ולא prompt() — הנייטיב מציג כפתורים באנגלית ואינו אמין ב-WebView2
  openModal('💾 שמירת סינון', `
    <label class="form-label">שם לסינון</label>
    <input id="flt-name" class="form-input" style="width:100%" placeholder="למשל: בני ברק בלי טלפון">
  `, [
    { label: 'שמור', cls: 'btn-primary', action: async () => {
      const name = document.getElementById('flt-name').value.trim();
      if (!name) { toast('הזן שם', 'error'); return; }
      closeModal();
      await api('save_filter', name, conditions);
      await refreshSavedFilters();
      toast('הסינון נשמר ✓', 'success');
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
  setTimeout(() => document.getElementById('flt-name')?.focus(), 60);
}

async function removeSavedFilter(i) {
  const f = _savedFilters[i];
  if (!f) return;
  await api('delete_saved_filter', f.name);
  await refreshSavedFilters();
}

function _fieldOptions() {
  return _filterFields.map(f => `<option value="${f.key}">${esc(f.label)}</option>`).join('');
}

function addFilterRow() {
  const rows = document.getElementById('filter-rows');
  if (!rows) return;
  const idx = rows.children.length;
  const row = document.createElement('div');
  row.className = 'filter-row';
  row.style.cssText = 'display:flex;align-items:center;gap:8px;flex-wrap:wrap';
  row.innerHTML = `
    <span style="font-size:12px;color:var(--subtext);min-width:48px">${idx === 0 ? 'סנן לפי:' : 'וגם:'}</span>
    <select class="form-select flt-field" style="width:auto;min-width:120px">${_fieldOptions()}</select>
    <select class="form-select flt-op" style="width:auto" onchange="onFilterOpChange(this);applyFieldFilter()">
      <option value="contains">מכיל</option>
      <option value="equals">שווה בדיוק</option>
      <option value="starts">מתחיל ב-</option>
      <option value="not_empty">לא ריק</option>
      <option value="empty">ריק</option>
    </select>
    <input class="form-input flt-value" style="width:auto;flex:1;min-width:120px"
           placeholder="ערך (לדוגמה: בני ברק)" oninput="applyFieldFilter()">
    ${idx === 0 ? '' : '<button class="btn btn-ghost btn-sm" onclick="this.closest(\'.filter-row\').remove();applyFieldFilter()">✕</button>'}
  `;
  rows.appendChild(row);
  row.querySelector('.flt-field').onchange = applyFieldFilter;
}

function onFilterOpChange(opSel) {
  const row = opSel.closest('.filter-row');
  const valInput = row.querySelector('.flt-value');
  const noValue = (opSel.value === 'empty' || opSel.value === 'not_empty');
  valInput.disabled = noValue;
  valInput.style.opacity = noValue ? '.4' : '1';
}

// debounce + token: בלי זה כל הקשה בשדה הסינון הריצה שאילתה מלאה על כל המאגר,
// ותשובות שחזרו לא לפי הסדר הציגו תוצאות של קידומת ישנה
let _filterTimer = null, _filterSeq = 0;
function applyFieldFilter() {
  clearTimeout(_filterTimer);
  return new Promise(resolve => {
    _filterTimer = setTimeout(() => _applyFieldFilterNow().then(resolve, resolve), 200);
  });
}

async function _applyFieldFilterNow() {
  const rows = [...document.querySelectorAll('#filter-rows .filter-row')];
  const conditions = [];
  for (const r of rows) {
    const field = r.querySelector('.flt-field').value;
    const op    = r.querySelector('.flt-op').value;
    const value = r.querySelector('.flt-value').value.trim();
    const needsValue = (op !== 'empty' && op !== 'not_empty');
    if (needsValue && !value) continue;  // דלג על תנאי ריק
    conditions.push({ field, op, value });
  }
  if (!conditions.length) {
    if (_fieldFilterActive) { _fieldFilterActive = false; await loadNicks(''); }
    document.getElementById('flt-count').textContent = '';
    return;
  }
  const seq = ++_filterSeq;
  const results = await api('filter_nicks_multi', conditions) || [];
  if (seq !== _filterSeq) return;   // סינון חדש יותר כבר יצא
  _fieldFilterActive = true;
  S.nicks = results;
  S.total = results.length;
  S.multiSelected.clear();
  S.selectedId = null;
  sortNicks();
  resetScroll();
  renderTable();
  updateBulkBar();
  document.getElementById('flt-count').textContent = `${results.length} תוצאות`;
}

async function clearFieldFilter() {
  _fieldFilterActive = false;
  clearTimeout(_filterTimer); _filterSeq++;   // בטל סינון שעוד בדרך
  const rows = document.getElementById('filter-rows');
  if (rows) rows.innerHTML = '';
  addFilterRow();
  document.getElementById('flt-count').textContent = '';
  await loadNicks(document.getElementById('search-input').value);
}

// עריכת שדה במרובים — משתמש בבחירה הקיימת (S.multiSelected)
async function bulkEditSelected() {
  const ids = [...S.multiSelected];
  if (!ids.length) { toast('לא נבחרו ניקים', 'error'); return; }
  const fields = await api('get_filterable_fields') || [];
  const opts = fields.filter(f => f.key!=='username' && f.key!=='forum')
                     .map(f => `<option value="${f.key}">${esc(f.label)}</option>`).join('');
  openModal('✏️ עריכת שדה במרובים', `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:12px">
      עדכון שדה אחד ל-${ids.length} הניקים שנבחרו (נרשם תחת מקור "אני").
    </p>
    <div class="form-group"><label class="form-label">שדה</label>
      <select id="bulk-field" class="form-select">${opts}</select></div>
    <div class="form-group"><label class="form-label">ערך חדש</label>
      <input id="bulk-value" class="form-input" placeholder="הערך שיוחל על כולם — או השאר ריק לניקוי השדה">
      <div style="font-size:11px;color:var(--subtext);margin-top:4px">💡 השארת השדה ריק תנקה את הערך אצל כל הנבחרים</div>
    </div>
  `, [
    { label: 'עדכן', cls: 'btn-primary', action: async () => {
      const field = document.getElementById('bulk-field').value;
      const value = document.getElementById('bulk-value').value;
      const r = await api('bulk_update_field', ids, field, value);
      if (!r?.ok) { toast('העדכון נכשל: ' + (r?.error || ''), 'error'); return; }
      closeModal();
      toast(`${r.count} ניקים עודכנו ✓`, 'success');
      if (_fieldFilterActive) await applyFieldFilter();
      else await loadNicks(document.getElementById('search-input').value);
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
}

// ── פעולות מרובות נוספות ─────────────────────────────────────────────
async function bulkLinkSelected() {
  const ids = [...S.multiSelected];
  if (ids.length < 2) { toast('בחר לפחות שני ניקים', 'error'); return; }
  if (ids.length > 50) { toast('יותר מדי ניקים לקישור כאדם אחד (מקסימום 50)', 'error'); return; }
  if (!confirm(`לקשר ${ids.length} ניקים כזהות אחת (אותו אדם)?`)) return;
  const r = await api('bulk_link_identities', ids);
  if (!r?.ok) { toast('הקישור נכשל: ' + (r?.error || ''), 'error'); return; }
  await loadNicks(document.getElementById('search-input').value);
  toast(`${r.count} ניקים קושרו כזהות אחת ✓`, 'success');
}

async function bulkMoveForum() {
  const ids = [...S.multiSelected];
  if (!ids.length) { toast('לא נבחרו ניקים', 'error'); return; }
  const opts = S.forums.map(f => `<option value="${esc(f.name)}">${esc(f.name)}</option>`).join('');
  openModal('🏛️ העברה לפורום אחר', `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:10px">
      ${ids.length} ניקים יועברו לפורום שתבחר.
    </p>
    <select id="bulk-forum" class="form-select" style="width:100%">${opts}</select>
  `, [
    { label: 'העבר', cls: 'btn-primary', action: async () => {
      const forum = document.getElementById('bulk-forum').value;
      const r = await api('bulk_move_forum', ids, forum);
      closeModal();
      if (!r?.ok) { toast('ההעברה נכשלה: ' + (r?.error || ''), 'error'); return; }
      await loadNicks(document.getElementById('search-input').value);
      const skip = r.skipped ? ` · ${r.skipped} דולגו (כבר קיים שם כזה בפורום)` : '';
      toast(`${r.count} ניקים הועברו ל"${forum}" ✓${skip}`, r.skipped ? 'info' : 'success');
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
}

async function bulkAddNote() {
  const ids = [...S.multiSelected];
  if (!ids.length) { toast('לא נבחרו ניקים', 'error'); return; }
  openModal('📝 הוספת הערה למרובים', `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:10px">
      הטקסט <b>יתווסף</b> בשורה חדשה להערות של ${ids.length} הניקים — בלי למחוק את הקיים.
    </p>
    <select id="bulk-note-field" class="form-select" style="width:100%;margin-bottom:8px">
      <option value="notes">הערות (מסונכרנות)</option>
      <option value="private_notes">🔒 הערות אישיות</option>
    </select>
    <textarea id="bulk-note-text" class="form-textarea" style="width:100%" placeholder="למשל: נבדק ✓"></textarea>
  `, [
    { label: 'הוסף', cls: 'btn-primary', action: async () => {
      const field = document.getElementById('bulk-note-field').value;
      const text = document.getElementById('bulk-note-text').value.trim();
      if (!text) { toast('הזן טקסט', 'error'); return; }
      const r = await api('bulk_append_text', ids, field, text);
      closeModal();
      if (!r?.ok) { toast('ההוספה נכשלה: ' + (r?.error || ''), 'error'); return; }
      await loadNicks(document.getElementById('search-input').value);
      toast(`נוסף ל-${r.count} ניקים ✓`, 'success');
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
}

async function syncSelectedOnline() {
  const ids = [...S.multiSelected];
  if (!ids.length) { toast('לא נבחרו ניקים', 'error'); return; }
  if (!confirm(`לסנכרן ${ids.length} ניקים מהאינטרנט? הערך מהאינטרנט יגבר.`)) return;
  const start = await api('sync_selected_online', ids, '');
  if (!start || !start.ok) { toast(start?.error || 'לא ניתן להתחיל', 'error'); return; }
  startScrapeMonitor();
}

// פעולות על מקור רצות ברקע (הכרעה מחדש לכל הערכים של המקור); כאן ממתינים עם משוב חי
async function waitSourceOp(labelPrefix) {
  return new Promise(resolve => {
    let busy = false;
    const poll = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const p = await api('get_source_progress');
        if (!p) return;
        if (p.total) setStatus(`${labelPrefix} ${p.processed.toLocaleString()} / ${p.total.toLocaleString()} ניקים…`);
        if (p.done || !p.running) { clearInterval(poll); resolve(p); }
      } finally { busy = false; }
    }, 300);
  });
}

async function onSrcTrust(sid, val) {
  setStatus('מעדכן ערכים לפי דרגת האמינות החדשה…');
  const r = await api('update_source', sid, null, null, parseInt(val), null);
  if (!r?.ok) { toast(r?.error || 'לא ניתן לעדכן כרגע', 'error'); return; }
  const p = await waitSourceOp('מכריע מחדש');
  if (p.error) { toast('העדכון נכשל: ' + p.error, 'error'); return; }
  await loadNicks(document.getElementById('search-input').value);
  toast('דרגת האמינות עודכנה והנתונים הוכרעו מחדש ✓', 'success');
}
async function onSrcAbsolute(sid, checked) {
  const r = await api('update_source', sid, null, null, null, checked);
  if (!r?.ok) { toast(r?.error || 'לא ניתן לעדכן כרגע', 'error'); return; }
  const row = document.querySelector(`.sync-item[data-sid="${sid}"]`);
  if (row) {
    const slider = row.querySelector('.src-trust');
    const wrap = row.querySelector('.src-trust-wrap');
    if (slider) slider.disabled = checked;
    if (wrap) wrap.style.opacity = checked ? '.4' : '1';
  }
  const p = await waitSourceOp('מכריע מחדש');
  if (p.error) { toast('העדכון נכשל: ' + p.error, 'error'); return; }
  await loadNicks(document.getElementById('search-input').value);
}
async function onSrcDelete(sid) {
  if (!confirm('למחוק את המקור הזה? כל הערכים שהגיעו ממנו יימחקו, והנתונים ייפלו לערך הבא לפי אמינות.')) return;
  setStatus('מוחק מקור ומכריע מחדש…');
  const r = await api('delete_source', sid);
  if (!r?.ok) { toast(r?.error || 'לא ניתן למחוק כרגע', 'error'); return; }
  document.querySelector(`.sync-item[data-sid="${sid}"]`)?.remove();
  const p = await waitSourceOp('מוחק מקור, מכריע מחדש');
  if (p.error) { toast('המחיקה נכשלה: ' + p.error, 'error'); return; }
  await loadNicks(document.getElementById('search-input').value);
  toast('המקור נמחק, הנתונים עודכנו ✓', 'success');
}

// מקטעים בקובץ שאינם עמודות של הניק (database.EXTRA_SYNC_KEYS)
const EXTRA_SYNC = [
  { key: 'contacts',   label: 'אנשי קשר נוספים (טלפונים/מיילים)' },
  { key: 'identities', label: 'קישורי זהות (אותו אדם בכמה פורומים)' },
];

async function openSyncMgr() {
  const fields   = await api('get_all_nick_fields');
  const sync     = await api('get_sync_settings');
  const forumIo  = await api('get_forum_io_flags') || {};
  const importManual = (await api('get_setting', 'import_manual_conflicts', '0')) === '1';
  const myTrust  = await api('get_my_trust') ?? 10;
  const sources  = await api('get_sources') || [];

  // ── סעיף 1: עמודות לייבוא/ייצוא בקובץ ──
  const sec1 = `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:12px">
      אילו עמודות ייכללו כשמייצאים או מייבאים קובץ נתונים.
    </p>
    <div class="sync-list" id="sync-list">
      ${fields.map(f => `
        <div class="sync-item">
          <span class="sync-label ${(f.key==='private_notes'||f.key==='avatar_image')?'warn':''}">
            ${esc(f.label)}${f.key==='avatar_image'?' <span style="font-size:10px;opacity:.7">(מכביד על הקובץ)</span>':''}
          </span>
          <span class="sync-badge ${sync[f.key]?'sync-on':'sync-off'}" id="sb-${f.key}">
            ${sync[f.key] ? '✓ מסונכרן' : '🔒 פרטי'}
          </span>
          <label class="toggle">
            <input type="checkbox" id="st-${f.key}" ${sync[f.key]?'checked':''}
                   onchange="updateSyncBadge('${f.key}',this.checked)">
            <span class="toggle-slider"></span>
          </label>
        </div>`).join('')}
    </div>
    <div style="font-size:11px;font-weight:800;color:var(--subtext);margin:14px 0 6px">
      מקטעים נוספים בקובץ</div>
    <div class="sync-list" id="sync-extra-list">
      ${EXTRA_SYNC.map(x => `
        <div class="sync-item">
          <span class="sync-label">${esc(x.label)}</span>
          <span class="sync-badge ${sync[x.key]?'sync-on':'sync-off'}" id="sb-${x.key}">
            ${sync[x.key] ? '✓ מסונכרן' : '🔒 פרטי'}
          </span>
          <label class="toggle">
            <input type="checkbox" id="st-${x.key}" ${sync[x.key]?'checked':''}
                   onchange="updateSyncBadge('${x.key}',this.checked)">
            <span class="toggle-slider"></span>
          </label>
        </div>`).join('')}
    </div>
    <p style="font-size:11px;color:var(--subtext);margin-top:6px;line-height:1.6">
      אנשי קשר המסומנים 🔒 סודי לעולם לא ייכללו בקובץ — גם כשהמתג דלוק.
      קישור זהות נכלל רק כששני הניקים שלו יוצאו.
    </p>`;

  // ── סעיף 2: אילו פורומים לייבא/לייצא ──
  const forumNames = Object.keys(forumIo);
  const sec2 = `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:12px">
      אילו פורומים ייכללו בייבוא/ייצוא קובץ. פורום שכבוי — הניקים שלו יידלגו.
    </p>
    <div class="sync-list" id="forumio-list">
      ${forumNames.length ? forumNames.map((name, i) => `
        <div class="sync-item">
          <span class="sync-label">${esc(name)}</span>
          <label class="toggle">
            <input type="checkbox" id="fio-${i}" data-forum="${esc(name)}" ${forumIo[name]?'checked':''}>
            <span class="toggle-slider"></span>
          </label>
        </div>`).join('') : '<div style="color:var(--subtext);padding:14px">אין פורומים מוגדרים</div>'}
    </div>`;

  // ── סעיף 3: התנגשויות בייבוא קובץ ──
  // (התנגשויות בסריקה מהאינטרנט נפתרות אוטומטית ע"י מנוע המקורות לפי אמינות —
  //  אין עוד מדיניות נפרדת לסריקה.)
  const sec3 = `
    <div style="display:flex;flex-direction:column;border:1px solid var(--border-soft);
         border-radius:12px;overflow:hidden;margin-bottom:14px">
      <div style="background:var(--card2);padding:12px 16px;font-weight:800;font-size:14px;
           border-bottom:2px solid var(--accent);display:flex;align-items:center;gap:8px">
        <span>👤</span> האמינות שלי
      </div>
      <div style="padding:16px">
        <p style="color:var(--subtext);font-size:12.5px;margin-bottom:12px">
          כמה משקל יש לערך שאתה מזין בעצמך, מול ערך שהגיע מסריקה או מקובץ.
          10 = תמיד גובר. דיאלוג הייבוא מציג את המספר הזה לשם השוואה.
        </p>
        <label class="form-label">אמינות: <b id="my-trust-val">${myTrust}</b> / 10</label>
        <input type="range" min="1" max="10" value="${myTrust}" id="my-trust" style="width:100%"
               oninput="document.getElementById('my-trust-val').textContent=this.value">
        <div style="font-size:11px;color:var(--subtext);margin-top:6px">
          שינוי כאן מכריע מחדש את כל השדות שיש להם יותר ממקור אחד — פעולה שעשויה
          לקחת כמה שניות במאגר גדול.
        </div>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;border:1px solid var(--border-soft);border-radius:12px;overflow:hidden">
      <div style="background:var(--card2);padding:12px 16px;font-weight:800;font-size:14px;
           border-bottom:2px solid var(--accent);display:flex;align-items:center;gap:8px">
        <span>📥</span> התנגשויות בייבוא קובץ
      </div>
      <div style="padding:16px">
        <p style="color:var(--subtext);font-size:12.5px;margin-bottom:14px">
          כשייבוא קובץ מכניס ערך שונה לשדה קיים, איך להכריע?
        </p>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <label class="toggle">
            <input type="checkbox" id="import-manual" ${importManual?'checked':''}>
            <span class="toggle-slider"></span>
          </label>
          <span style="font-size:13px;font-weight:600">פתרון ידני — שאל אותי לכל התנגשות</span>
        </div>
        <div style="font-size:11.5px;color:var(--subtext);line-height:1.6">
          כבוי (ברירת מחדל) = הכרעה אוטומטית לפי דרגת אמינות.<br>
          דלוק = ייפתח חלון לבחירה ידנית בכל התנגשות.
        </div>
        <div style="font-size:12px;color:var(--subtext);padding:12px;margin-top:14px;
             background:var(--card2);border-radius:8px;line-height:1.6">
          💡 כך גם עובדת הסריקה מהאינטרנט: ערך סותר נשמר לצד הקיים ומסומן ב-❗,
          והמנצח נקבע לפי דרגות האמינות שקובעים בלשונית
          <b style="color:var(--accent-2);cursor:pointer;white-space:nowrap" onclick="switchSyncTab('s4')">🎖️&nbsp;מקורות</b>.
        </div>
      </div>
    </div>`;

  // ── סעיף 4: ניהול מקורות ("אבות") ──
  const kindLabel = k => k==='me' ? '👤 אני' : k==='scrape' ? '🌐 סריקת אינטרנט' : '📥 ייבוא';
  const srcRows = sources.map(s => `
    <div class="sync-item" data-sid="${s.id}" style="flex-wrap:wrap;gap:8px">
      <span class="sync-label" style="min-width:150px">
        ${kindLabel(s.kind)} ${s.kind==='import'||s.kind==='scrape'?`— ${esc(s.name)}`:''}
        ${s.notes?`<span style="font-size:10px;opacity:.6">(${esc(s.notes)})</span>`:''}
      </span>
      ${s.kind==='me' ? `
        <label class="toggle" title="תמיד מנצח, ללא תלות באמינות">
          <input type="checkbox" class="src-abs" ${s.absolute?'checked':''}
                 onchange="onSrcAbsolute(${s.id}, this.checked)">
          <span class="toggle-slider"></span>
        </label>
        <span style="font-size:12px">אבסולוטי</span>` : ''}
      <span class="src-trust-wrap"
            style="display:flex;align-items:center;gap:6px;${s.kind==='me' && s.absolute?'opacity:.4':''}">
        אמינות <b class="src-tval" id="stv-${s.id}">${s.trust}</b>
        <input type="range" min="1" max="10" value="${s.trust}" class="src-trust" style="width:90px"
               ${s.kind==='me' && s.absolute?'disabled':''}
               oninput="document.getElementById('stv-${s.id}').textContent=this.value"
               onchange="onSrcTrust(${s.id}, this.value)">
      </span>
      ${s.id!==1 ? `<button class="btn btn-sm btn-ghost" onclick="onSrcDelete(${s.id})" title="מחק מקור">🗑️</button>` : ''}
    </div>`).join('');
  const sec4 = `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:12px">
      כל מידע משויך למקור ("אב"). בכל שדה — הערך מהמקור בעל האמינות הגבוהה מוצג.
      שינוי אמינות או מחיקת מקור משפיעים על הנתונים מיד.
      "אבסולוטי" (רק ל"אני") = תמיד מנצח. את התנהגות הסריקה מנהלים בלשונית "התנגשויות".
    </p>
    <div class="sync-list">${srcRows}</div>`;

  const html = `
    <div class="tab-bar" style="display:flex;gap:6px;margin-bottom:16px;border-bottom:1px solid var(--border-soft);flex-wrap:wrap">
      <button class="tab-btn active" data-tab="s1" onclick="switchSyncTab('s1')">📄 עמודות בקובץ</button>
      <button class="tab-btn" data-tab="s2" onclick="switchSyncTab('s2')">🏛️ פורומים</button>
      <button class="tab-btn" data-tab="s3" onclick="switchSyncTab('s3')">⚠️ התנגשויות</button>
      <button class="tab-btn" data-tab="s4" onclick="switchSyncTab('s4')">🎖️ מקורות</button>
    </div>
    <div id="tab-s1" class="sync-tab">${sec1}</div>
    <div id="tab-s2" class="sync-tab" style="display:none">${sec2}</div>
    <div id="tab-s3" class="sync-tab" style="display:none">${sec3}</div>
    <div id="tab-s4" class="sync-tab" style="display:none">${sec4}</div>`;

  window.switchSyncTab = (tab) => {
    ['s1','s2','s3','s4'].forEach(t => {
      document.getElementById('tab-'+t).style.display = (t===tab)?'':'none';
    });
    document.querySelectorAll('.tab-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.tab===tab));
  };
  window.updateSyncBadge = (key, checked) => {
    const badge = document.getElementById(`sb-${key}`);
    if (!badge) return;
    badge.className = `sync-badge ${checked ? 'sync-on' : 'sync-off'}`;
    badge.textContent = checked ? '✓ מסונכרן' : '🔒 פרטי';
  };

  openModal('⚙️ הגדרות סנכרון', html, [
    { label: '💾 שמור', cls: 'btn-primary', action: async () => {
      // סעיף 1+2 — קריאת גשר אחת לכל סעיף (במקום ~40 קריאות סדרתיות)
      const syncMap = {};
      for (const f of fields) {
        const el = document.getElementById(`st-${f.key}`);
        if (el) syncMap[f.key] = el.checked;
      }
      for (const x of EXTRA_SYNC) {
        const el = document.getElementById(`st-${x.key}`);
        if (el) syncMap[x.key] = el.checked;
      }
      await api('set_sync_settings', syncMap);
      const ioMap = {};
      for (let i = 0; i < forumNames.length; i++) {
        const el = document.getElementById(`fio-${i}`);
        if (el) ioMap[el.dataset.forum] = el.checked;
      }
      await api('set_forum_io_flags', ioMap);
      const mt = document.getElementById('my-trust');
      if (mt && parseInt(mt.value) !== myTrust) {
        await api('set_my_trust', parseInt(mt.value));
        // "אני" הוא מקור ככל מקור אחר — שינוי האמינות שלו מחייב הכרעה מחדש,
        // אחרת המספר משתנה והתצוגה נשארת על ההכרעה הישנה.
        await api('update_source', 1, null, null, parseInt(mt.value), null);
        await waitSourceOp('מעדכן אמינות');
        await loadNicks(document.getElementById('search-input').value);
      }
      // סעיף 3
      const im = document.getElementById('import-manual');
      if (im) await api('set_setting', 'import_manual_conflicts', im.checked ? '1' : '0');
      toast('הגדרות סנכרון נשמרו ✓', 'success');
      closeModal();   // כמו בכל "שמור" אחר בתוכנה
    }},
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
}

// ══ הצעות זהות: "מי זה אותו אדם" ══════════════════════════════════════
// נשארת ככניסה חוקית (קיצור/קוד ישן) — ומובילה ללשונית שבתוך חלון הזהויות.
async function openIdentitySuggestions() {
  await openIdentityMap('sug');
}

// נטענות פעם אחת לכל פתיחה של החלון, ורק כשעוברים ללשונית — החיפוש עצמו יקר.
async function loadIdentitySuggestions() {
  const pane = document.getElementById('idsug-pane');
  if (!pane || pane.dataset.loaded === '1') return;
  pane.dataset.loaded = '1';
  pane.innerHTML = '<div style="padding:24px;text-align:center;color:var(--subtext)">מחפש התאמות…</div>';
  const r = await api('suggest_identities', 60);
  if (_currentModalId !== 'identity-map') return;
  const box = document.getElementById('idsug-pane');
  if (!box) return;
  if (!r?.ok) {
    box.innerHTML = `<div style="padding:20px;color:var(--danger)">${esc(r?.error || 'שגיאה')}</div>`;
    return;
  }
  _idSuggestions = r.groups || [];
  renderIdentitySuggestions();
}

function switchIdentityTab(tab) {
  const map = document.getElementById('idm-pane');
  const sug = document.getElementById('idsug-pane');
  if (!map || !sug) return;
  const isSug = tab === 'sug';
  map.style.display = isSug ? 'none' : '';
  sug.style.display = isSug ? '' : 'none';
  document.getElementById('idtab-map')?.classList.toggle('active', !isSug);
  document.getElementById('idtab-sug')?.classList.toggle('active', isSug);
  if (isSug) loadIdentitySuggestions();
}

let _idSuggestions = [];

function renderIdentitySuggestions() {
  if (_currentModalId !== 'identity-map') return;
  const body = document.getElementById('idsug-pane');
  if (!body) return;
  if (!_idSuggestions.length) {
    body.innerHTML = `<div style="text-align:center;padding:30px;color:var(--subtext)">
      <div style="font-size:44px;margin-bottom:10px">✓</div>
      אין הצעות חדשות — כל ההתאמות שנמצאו כבר מקושרות או נדחו</div>`;
    return;
  }
  body.innerHTML = `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:12px">
      ניקים בפורומים שונים שנראים כאותו אדם (אותו טלפון / מייל / שם). קישור יאחד אותם לזהות אחת.
    </p>` + _idSuggestions.map((g, i) => `
    <div class="suggest-item" data-sug="${i}">
      <div style="font-size:12px;color:var(--subtext);margin-bottom:6px">
        ${esc(g.reason)}: <b dir="auto" style="color:var(--accent-2)">${esc(g.value)}</b>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">
        ${g.members.map(m => `
          <span style="background:var(--card2);border-radius:999px;padding:4px 11px;font-size:12px">
            <b>${esc(m.username)}</b>
            <span style="color:${S.forumColors[m.forum] || '#8b90a0'}"> ${esc(m.forum)}</span>
            ${m.real_name ? `<span style="color:var(--subtext)"> · ${esc(m.real_name)}</span>` : ''}
          </span>`).join('')}
      </div>
      <div style="display:flex;gap:6px">
        <button class="btn btn-sm btn-primary" onclick="linkSuggestion(${i})">🔗 קשר כזהות אחת</button>
        <button class="btn btn-sm btn-ghost" onclick="dismissSuggestion(${i})">✕ לא אותו אדם</button>
      </div>
    </div>`).join('');
}

// הסרה לפי זהות האובייקט ולא לפי אינדקס — לחיצות מהירות ברצף הסיטו אינדקסים
function _dropSuggestion(g) {
  const idx = _idSuggestions.indexOf(g);
  if (idx >= 0) _idSuggestions.splice(idx, 1);
  renderIdentitySuggestions();
}

async function linkSuggestion(i) {
  const g = _idSuggestions[i];
  if (!g || g._busy) return;
  g._busy = true;
  const r = await api('bulk_link_identities', g.members.map(m => m.id));
  g._busy = false;
  if (!r?.ok) { toast('הקישור נכשל: ' + (r?.error || ''), 'error'); return; }
  _dropSuggestion(g);
  await loadNicks(document.getElementById('search-input').value);
  toast(`${r.count} ניקים קושרו כזהות אחת ✓`, 'success');
}

async function dismissSuggestion(i) {
  const g = _idSuggestions[i];
  if (!g || g._busy) return;
  g._busy = true;
  await api('dismiss_identity_suggestion', g.members.map(m => m.id));
  _dropSuggestion(g);
}

// ══ סריקה מתוזמנת ════════════════════════════════════════════════════
// כבוי כברירת מחדל, ומרגע שמדליקים — עדיין לא סורק כלום עד שמסמנים פורומים.
// זו לא זהירות יתר: אלה פורומים קטנים שמתנדבים מתחזקים, וסריקה לא מפוקחת
// מכתובת ביתית היא עומס אמיתי עליהם.
async function openScheduler(back) {
  const cfg = await api('get_schedule') || {};
  // רק פלטפורמות שהסורק באמת יודע לסרוק. XenForo/phpBB נכשלים מיד, וכל טיק
  // היה סופר עוד כישלון עד שהתזמון כולו נכבה בגלל פורום אחד שלא ניתן לסרוק.
  const forums = (await api('get_scrapable_forums') || [])
    .filter(f => (f.url || '').trim() && SCRAPABLE_PLATFORMS.has(f.platform || 'nodebb'));
  const on = !!cfg.enabled;
  const picked = new Set(cfg.forums || []);
  openModal('⏰ סריקה מתוזמנת', `
    ${cfg.fail_count ? `<div style="background:var(--card2);border-inline-start:3px solid var(--danger,#e5484d);
        padding:8px 10px;border-radius:6px;font-size:12px;margin-bottom:10px">
        ⚠️ ${esc(cfg.fail_count)} ניסיונות כושלים ברצף${cfg.last_error ? ` — ${esc(cfg.last_error)}` : ''}
      </div>` : ''}
    <label style="display:flex;gap:8px;align-items:center;font-size:13px;cursor:pointer;margin-bottom:12px">
      <input type="checkbox" id="sch-on" ${on ? 'checked' : ''}>
      <b>הפעל סריקה אוטומטית</b>
    </label>
    <div class="form-group">
      <label class="form-label">מתי</label>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <label style="display:flex;gap:5px;align-items:center;font-size:12.5px;cursor:pointer">
          <input type="radio" name="sch-mode" value="daily" ${cfg.mode !== 'interval' ? 'checked' : ''}>
          כל יום בשעה</label>
        <input type="time" class="form-input" id="sch-at" value="${esc(cfg.at || '03:00')}"
               style="width:auto" dir="ltr">
        <label style="display:flex;gap:5px;align-items:center;font-size:12.5px;cursor:pointer;margin-inline-start:10px">
          <input type="radio" name="sch-mode" value="interval" ${cfg.mode === 'interval' ? 'checked' : ''}>
          כל</label>
        <input type="number" class="form-input" id="sch-hours" min="${esc(cfg.min_hours || 12)}" max="720"
               value="${esc(cfg.every_hours || 24)}" style="width:80px" dir="ltr">
        <span style="font-size:12.5px">שעות</span>
      </div>
      <div style="font-size:11px;color:var(--subtext);margin-top:5px">
        המינימום הוא ${esc(cfg.min_hours || 12)} שעות בין סריקות לאותו פורום — גם אם תגדיר פחות.
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">אילו פורומים</label>
      ${forums.length ? `<div class="sync-list" style="max-height:30vh;overflow:auto">
        ${forums.map((f, i) => `
          <div class="sync-item">
            <span class="sync-label">${esc(f.name)}</span>
            <label class="toggle">
              <input type="checkbox" class="sch-forum" data-forum="${esc(f.name)}"
                     ${picked.has(f.name) ? 'checked' : ''}>
              <span class="toggle-slider"></span>
            </label>
          </div>`).join('')}
      </div>` : '<div style="font-size:12.5px;color:var(--subtext)">אין פורומים עם כתובת לסריקה.</div>'}
      <div style="font-size:11px;color:var(--subtext);margin-top:5px">
        סריקה משתמשת רק בעוגייה השמורה של כל פורום בנפרד. פורום שדורש התחברות
        ושהעוגייה שלו פגה — פשוט ידולג.
      </div>
    </div>
    <div style="font-size:11.5px;color:var(--subtext);line-height:1.8;margin-top:6px">
      ${cfg.last_run ? `סריקה אוטומטית אחרונה: <span dir="ltr">${esc(String(cfg.last_run).replace('T', ' ').slice(0, 16))}</span><br>` : ''}
      ${(cfg.due || []).length ? `מגיע להיסרק כעת: ${esc((cfg.due || []).join(', '))}` : 'כרגע אין פורום שמגיע לו להיסרק.'}
    </div>
  `, [
    { label: '💾 שמור', cls: 'btn-primary', action: async () => {
      const chosen = [...document.querySelectorAll('.sch-forum')]
        .filter(c => c.checked).map(c => c.dataset.forum);
      const mode = document.querySelector('input[name="sch-mode"]:checked')?.value || 'daily';
      const r = await api('set_schedule',
        document.getElementById('sch-on').checked, mode,
        document.getElementById('sch-at').value,
        parseInt(document.getElementById('sch-hours').value) || 24, chosen);
      if (!r?.ok) { toast(r?.error || 'השמירה נכשלה', 'error'); return; }
      closeModal();
      toast(r.enabled
        ? (r.forums.length ? `התזמון פעיל · ${r.forums.length} פורומים` : 'התזמון פעיל, אך לא נבחר אף פורום')
        : 'התזמון כבוי', r.enabled && !r.forums.length ? 'error' : 'success');
    }},
    { label: '▶ הרץ עכשיו', cls: 'btn-ghost', action: async () => {
      const r = await api('run_schedule_now');
      // "אין כרגע פורום שמגיע לו" היא התשובה הרגילה, לא שגיאה — טוסט אדום
      // על מצב תקין נראה כמו באג.
      if (!r?.ok) { toast(r?.error || 'לא ניתן להריץ', r?.error ? 'info' : 'error'); return; }
      closeModal(); startScrapeMonitor();
    }},
    ...(typeof back === 'function'
        ? [{ label: '↩ חזרה', cls: 'btn-ghost', action: () => { closeModal(); back(); } }]
        : []),
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm', { id: 'scheduler' });
}

// ══ יומן ייבואים ═════════════════════════════════════════════════════
// כל ייבוא נרשם ב-import_sources מאז הגרסאות הראשונות, ומעולם לא הוצג.
async function openImportLog(back) {
  const rows = await api('get_import_log', 50) || [];
  openModal('📥 יומן ייבואים', rows.length ? `
    <div style="max-height:56vh;overflow:auto">
      <table style="width:100%;border-collapse:collapse">
        <thead><tr style="position:sticky;top:0;background:var(--card2)">
          <th style="padding:6px;text-align:right;font-size:11px">מקור</th>
          <th style="padding:6px;text-align:right;font-size:11px">מתי</th>
          <th style="padding:6px;text-align:right;font-size:11px">ניקים</th>
          <th style="padding:6px;text-align:right;font-size:11px">ערכים</th>
          <th style="padding:6px;text-align:right;font-size:11px">אמינות</th>
        </tr></thead>
        <tbody>${rows.map(r => `
          <tr style="border-bottom:1px solid var(--border-soft)">
            <td style="padding:5px 6px;font-size:12px">
              <b>${esc(r.name)}</b>
              ${r.notes ? `<div style="color:var(--subtext);font-size:11px">${esc(r.notes)}</div>` : ''}
            </td>
            <td style="padding:5px 6px;font-size:11.5px;color:var(--subtext)" dir="ltr">
              ${esc(String(r.created_at || '').replace('T', ' ').slice(0, 16))}</td>
            <td style="padding:5px 6px;font-size:12px">${esc(r.nick_count ?? 0)}</td>
            <td style="padding:5px 6px;font-size:12px">${esc(r.conflict_count ?? 0)}</td>
            <td style="padding:5px 6px;font-size:12px">${esc(r.trust ?? '')}</td>
          </tr>`).join('')}</tbody>
      </table>
    </div>` : `<div style="text-align:center;padding:26px;color:var(--subtext);font-size:13px">
      עדיין לא בוצע ייבוא.</div>`,
    [...(typeof back === 'function'
         ? [{ label: '↩ חזרה', cls: 'btn-ghost', action: () => { closeModal(); back(); } }]
         : []),
     { label: 'סגור', cls: 'btn-ghost', action: closeModal }], 'modal-lg',
    { id: 'import-log' });
}

// ══ פרופיל להדפסה ════════════════════════════════════════════════════
// אין הדפסה מתוך התוכנה: ה-iframe מוגן ב-sandbox בלי allow-modals, ו-pywebview
// רץ עם debug=False (בלי Ctrl+P ובלי תפריט הקשר). לכן פייתון כותב קובץ
// ומוסר אותו למערכת, והדפדפן האמיתי מדפיס אותו.
async function printProfileNow(nickId, opts = {}) {
  setStatus('מכין גיליון…');
  const r = await api('open_print_profile', nickId, opts.group !== false,
                      !!opts.priv, opts.history !== false);
  setStatus('');
  if (r?.ok) toast('הגיליון נפתח בדפדפן — משם אפשר להדפיס או לשמור כ-PDF', 'success');
  else toast('לא ניתן לפתוח את הגיליון' + (r?.path ? ` — הקובץ נשמר ב: ${r.path}` : ''), 'error');
}

async function openPrintDialog(nickId) {
  openModal('🖨️ פרופיל להדפסה', `
    <div style="display:flex;flex-direction:column;gap:7px;margin-bottom:10px">
      <label style="display:flex;gap:8px;align-items:center;font-size:12.5px;cursor:pointer">
        <input type="checkbox" id="pr-group" checked> לכלול את כל הזהויות המקושרות</label>
      <label style="display:flex;gap:8px;align-items:center;font-size:12.5px;cursor:pointer">
        <input type="checkbox" id="pr-hist" checked> לכלול ציר זמן</label>
      <label style="display:flex;gap:8px;align-items:center;font-size:12.5px;cursor:pointer">
        <input type="checkbox" id="pr-priv"> 🔒 לכלול הערות אישיות ואנשי קשר סודיים</label>
    </div>
    <div style="font-size:11px;color:var(--subtext);margin-bottom:8px">
      הגיליון נשמר בתיקיית הנתונים ונמחק אוטומטית אחרי יממה.
    </div>
    <iframe id="pr-frame" sandbox="allow-scripts" style="width:100%;height:44vh;border:1px solid var(--border-soft);border-radius:8px;background:#fff"></iframe>
  `, [
    { label: '🖨️ פתח להדפסה', cls: 'btn-primary', action: () => {
      printProfileNow(nickId, {
        group: document.getElementById('pr-group').checked,
        priv:  document.getElementById('pr-priv').checked,
        history: document.getElementById('pr-hist').checked });
    }},
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg', { id: 'print-profile' });
  ['pr-group', 'pr-hist', 'pr-priv'].forEach(id =>
    document.getElementById(id).addEventListener('change', () => refreshPrintPreview(nickId)));
  refreshPrintPreview(nickId);
}

async function refreshPrintPreview(nickId) {
  const r = await api('preview_print_profile', nickId,
                      document.getElementById('pr-group')?.checked !== false,
                      !!document.getElementById('pr-priv')?.checked,
                      document.getElementById('pr-hist')?.checked !== false);
  if (_currentModalId !== 'print-profile') return;   // תשובה מאוחרת לחלון שכבר הוחלף
  const f = document.getElementById('pr-frame');
  if (f && r?.ok) f.srcdoc = r.html;
}

// ══ נצפו לאחרונה ═════════════════════════════════════════════════════
// ══ מפת זהויות ═══════════════════════════════════════════════════════
let _idMap = null;

async function openIdentityMap(tab) {
  setStatus('טוען מפת זהויות…');
  const m = await api('get_identity_map');
  setStatus('');
  if (!m?.ok) { toast('שגיאה: ' + (m?.error || ''), 'error'); return; }
  _idMap = m;
  const forums = [...new Set(m.groups.flatMap(g => g.forums))].sort(HE_COLLATOR.compare);
  openModal('🗺️ זהויות', `
    <div class="tab-bar" style="display:flex;gap:6px;margin-bottom:14px;
         border-bottom:1px solid var(--border-soft)">
      <button class="tab-btn active" id="idtab-map" onclick="switchIdentityTab('map')">🗺️ מפת זהויות</button>
      <button class="tab-btn" id="idtab-sug" onclick="switchIdentityTab('sug')">🔗 הצעות לקישור</button>
    </div>
    <div id="idsug-pane" style="display:none"></div>
    <div id="idm-pane">
    <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--subtext);
                margin-bottom:10px">
      <span><b style="color:var(--accent-2)">${m.total_groups}</b> קבוצות</span>
      <span><b>${m.linked_nicks}</b> ניקים מקושרים</span>
      <span><b>${m.groups.length ? m.groups[0].size : 0}</b> הקבוצה הגדולה</span>
      <span><b>${m.groups.filter(g => g.forum_count > 1).length}</b> חוצות פורומים</span>
      <span><b>${m.groups.filter(g => g.conflicts.length).length}</b> עם סתירה</span>
    </div>
    ${m.truncated ? `<div style="font-size:11.5px;color:var(--subtext);margin-bottom:8px">
      מוצגות ${m.groups.length} הקבוצות הגדולות בלבד.</div>` : ''}
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
      <input class="form-input" id="idm-q" placeholder="🔍 ניק / שם / פורום…"
             oninput="renderIdentityMap()" style="flex:1;min-width:150px;font-size:12px">
      <select class="form-input" id="idm-size" onchange="renderIdentityMap()" style="width:auto;font-size:12px">
        <option value="0">כל הקבוצות</option><option value="3">3 ומעלה</option>
        <option value="4">4 ומעלה</option><option value="6">6 ומעלה</option>
      </select>
      <select class="form-input" id="idm-span" onchange="renderIdentityMap()" style="width:auto;font-size:12px">
        <option value="0">כל פריסה</option><option value="2">חוצות 2 פורומים+</option>
        <option value="3">חוצות 3 פורומים+</option>
      </select>
      <select class="form-input" id="idm-forum" onchange="renderIdentityMap()" style="width:auto;font-size:12px">
        <option value="">כל פורום</option>
        ${forums.map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join('')}
      </select>
      <label style="display:flex;gap:5px;align-items:center;font-size:12px;cursor:pointer">
        <input type="checkbox" id="idm-conf" onchange="renderIdentityMap()"> רק עם סתירה</label>
    </div>
    <div id="idm-body"></div>
    </div>
  `, [{ label: 'סגור', cls: 'btn-ghost', action: closeModal }], 'modal-lg',
     { id: 'identity-map' });
  renderIdentityMap();
  if (tab === 'sug') switchIdentityTab('sug');
}

// גליף קטן: נקודה לכל חבר על מעגל + מיתרים. SVG בעבודת יד — אין ספרייה בחבילה.
function idGlyph(g) {
  const n = Math.min(g.size, 6), R = 15, C = 20;
  const pts = Array.from({ length: n }, (_, i) => {
    const t = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [C + R * Math.cos(t), C + R * Math.sin(t)];
  });
  const lines = [];
  for (let i = 0; i < n; i++)
    for (let j = i + 1; j < n; j++)
      lines.push(`<line x1="${pts[i][0].toFixed(1)}" y1="${pts[i][1].toFixed(1)}" x2="${pts[j][0].toFixed(1)}" y2="${pts[j][1].toFixed(1)}" stroke="currentColor" stroke-width="0.7" opacity=".35"/>`);
  const dots = pts.map((pt, i) => {
    const col = S.forumColors[(g.members[i] || {}).forum] || '#8b90a0';
    return `<circle cx="${pt[0].toFixed(1)}" cy="${pt[1].toFixed(1)}" r="3.6" fill="${esc(col)}"/>`;
  }).join('');
  const more = g.size > 6
    ? `<text x="20" y="24" text-anchor="middle" font-size="9" fill="currentColor">+${g.size - 6}</text>` : '';
  return `<svg width="40" height="40" viewBox="0 0 40 40" style="flex:none;color:var(--subtext)">${lines.join('')}${dots}${more}</svg>`;
}

function renderIdentityMap() {
  const box = document.getElementById('idm-body');
  if (!box || !_idMap) return;
  const q = (document.getElementById('idm-q')?.value || '').trim().toLowerCase();
  const minSize = parseInt(document.getElementById('idm-size')?.value || '0');
  const minSpan = parseInt(document.getElementById('idm-span')?.value || '0');
  const forum = document.getElementById('idm-forum')?.value || '';
  const onlyConf = document.getElementById('idm-conf')?.checked;

  const groups = _idMap.groups.filter(g => {
    if (minSize && g.size < minSize) return false;
    if (minSpan && g.forum_count < minSpan) return false;
    if (forum && !g.forums.includes(forum)) return false;
    if (onlyConf && !g.conflicts.length) return false;
    if (q && !g.members.some(mm =>
      (mm.username || '').toLowerCase().includes(q) ||
      (mm.real_name || '').toLowerCase().includes(q) ||
      (mm.forum || '').toLowerCase().includes(q))) return false;
    return true;
  });

  if (!groups.length) {
    box.innerHTML = `<div style="text-align:center;padding:28px;color:var(--subtext);font-size:13px">
      🗺️ אין קבוצות זהות שמתאימות לסינון.<br>
      <span style="font-size:12px">אפשר להתחיל מ"🔗 הצעות זהות".</span></div>`;
    return;
  }

  box.innerHTML = groups.map((g, gi) => `
    <div style="display:flex;gap:10px;padding:9px 4px;border-bottom:1px solid var(--border-soft)">
      ${idGlyph(g)}
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;font-weight:700;margin-bottom:4px">
          ${g.size} ניקים · ${g.forum_count} פורומים
          ${g.banned ? `<span style="color:var(--danger,#e5484d)"> · 🚫 ${g.banned} מורחקים</span>` : ''}
          ${g.conflicts.length ? `<span style="color:var(--warn,#e59b2b)"> · ⚠️ ${esc(g.conflicts.join(' · '))}</span>` : ''}
          <button class="btn btn-sm btn-ghost idm-prof" data-gi="${gi}" style="float:left;font-size:11px">🔎 פרופיל מאוחד</button>
        </div>
        <div>${g.members.map(mm => `
          <span class="chip" style="display:inline-block;padding:2px 7px;border:1px solid var(--border-soft);
                border-radius:9px;font-size:11.5px;margin:0 0 4px 4px">
            <span style="display:inline-block;width:7px;height:7px;border-radius:50%;
                  margin-left:5px;background:${esc(S.forumColors[mm.forum] || '#8b90a0')}"></span>
            <b class="idm-open" data-nid="${mm.id}" style="cursor:pointer">${esc(mm.username)}</b>
            <span style="color:var(--subtext)"> ${esc(mm.forum)}</span>
            ${(mm.status || '') === 'מורחק' ? ' 🚫' : ''}
            <span class="idm-unlink" data-nid="${mm.id}" data-gi="${gi}"
                  style="cursor:pointer;color:var(--danger,#e5484d);margin-right:4px">✕</span>
          </span>`).join('')}</div>
        <div id="idm-prof-${gi}"></div>
      </div>
    </div>`).join('');
  box._groups = groups;
}

async function idmUnlink(nid, gi) {
  const g = (document.getElementById('idm-body')?._groups || [])[gi];
  if (!g) return;
  const who = g.members.find(m => m.id === nid);
  if (!who) return;
  if (g.size === 2 && !confirm(`ניתוק "${who.username}" יפרק את הקבוצה כולה. להמשיך?`)) return;
  const other = g.members.find(m => m.id !== nid);
  await api('remove_identity', other.id, nid);
  toast(`${who.username} נותק מהקבוצה`, 'success', {
    actionLabel: '↩ בטל',
    onAction: async () => {
      await api('bulk_link_identities', g.members.map(m => m.id));
      await openIdentityMap();
    }, ms: 7000 });
  await openIdentityMap();
}

async function idmProfile(gi) {
  const g = (document.getElementById('idm-body')?._groups || [])[gi];
  const host = document.getElementById(`idm-prof-${gi}`);
  if (!g || !host) return;
  if (host.innerHTML) { host.innerHTML = ''; return; }
  const p = await api('get_merged_profile', g.members[0].id);
  if (_currentModalId !== 'identity-map') return;   // המשתמש כבר החליף חלון
  host.innerHTML = `<div style="margin-top:6px;padding:8px;background:var(--card2);
       border-radius:8px">${p ? renderMergedProfile(p) : 'לא נמצא'}</div>`;
}

// ══ סטטיסטיקות ════════════════════════════════════════════════════════
async function openStats() {
  const s = await api('get_stats');
  if (!s?.ok) { toast('לא ניתן לחשב סטטיסטיקות: ' + (s?.error || ''), 'error'); return; }
  const t = s.totals || {};
  const card = (label, val, color) => `
    <div style="background:var(--card);border:1px solid var(--border-soft);border-radius:12px;padding:12px 14px;flex:1;min-width:120px">
      <div style="font-size:22px;font-weight:800;color:${color || 'var(--text)'}">${(val || 0).toLocaleString()}</div>
      <div style="font-size:11.5px;color:var(--subtext)">${label}</div>
    </div>`;
  const maxF = Math.max(1, ...(s.by_forum || []).map(f => f.total));
  const bars = (s.by_forum || []).map(f => `
    <div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:3px">
        <b>${esc(f.forum)}</b>
        <span style="color:var(--subtext)">${f.total.toLocaleString()} · עם מידע ${f.with_info || 0}${f.banned ? ` · מורחקים ${f.banned}` : ''}</span>
      </div>
      <div style="height:7px;background:var(--card2);border-radius:99px;overflow:hidden">
        <div style="height:100%;width:${Math.round(f.total / maxF * 100)}%;background:${S.forumColors[f.forum] || 'var(--accent)'}"></div>
      </div>
    </div>`).join('');
  openModal('📊 סטטיסטיקות', `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      ${card('סה"כ ניקים', t.total)}
      ${card('עם מידע', t.with_info, 'var(--success)')}
      ${card('מורחקים', t.banned, 'var(--danger)')}
      ${card('קישורי זהות', t.identities, 'var(--violet)')}
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
      ${card('אנשי קשר', t.contacts)}
      ${card('נוספו בשבוע', t.added_7d)}
      ${card('עודכנו בשבוע', t.updated_7d)}
    </div>
    <div class="section-hdr">לפי פורום</div>
    ${bars || '<div style="color:var(--subtext);font-size:13px">אין נתונים</div>'}
    ${(s.top_groups || []).length ? `<div class="section-hdr">קבוצות נפוצות</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">${s.top_groups.map(g =>
        `<span style="background:var(--card2);border-radius:999px;padding:4px 11px;font-size:12px">${esc(g.name)} <b>${g.c}</b></span>`).join('')}</div>` : ''}
  `, [{ label: 'סגור', cls: 'btn-ghost', action: closeModal }], 'modal-lg');
}

// ══ מה השתנה בסריקה ═══════════════════════════════════════════════════
async function openScanRuns(back) {
  const runs = await api('get_scan_runs', 30) || [];
  const rows = runs.length ? runs.map(r => `
    <div style="display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border-soft);font-size:13px">
      <div style="flex:1;min-width:0">
        <b>${esc(r.forum)}</b>
        <span style="color:var(--subtext)"> · ${esc(relativeTime(r.started_at))}</span>
        <div style="color:var(--subtext);font-size:12px">
          נוספו ${r.added} · עודכנו ${r.updated}${r.failed_pages ? ` · ${r.failed_pages} עמודים נכשלו` : ''}
        </div>
      </div>
      ${r.changes ? `<button class="btn btn-sm btn-ghost" onclick="openScanChanges(${r.id})">${r.changes} שינויים</button>`
                  : '<span style="color:var(--subtext);font-size:12px">ללא שינוי</span>'}
    </div>`).join('')
    : '<div style="padding:24px;text-align:center;color:var(--subtext)">עדיין לא בוצעו סריקות</div>';
  openModal('🕒 יומן סריקות', rows, [
    ...(typeof back === 'function'
        ? [{ label: '↩ חזרה', cls: 'btn-ghost', action: () => { closeModal(); back(); } }]
        : []),
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
}

async function openScanChanges(runId) {
  const LIMIT = 500;
  const ch = await api('get_scan_changes', runId, LIMIT) || [];
  const truncated = ch.length >= LIMIT;
  const label = k => (COLS.find(c => c.key === k)?.label) || k;
  const isNew = c => c.kind === 'new';
  const news = ch.filter(isNew), changes = ch.filter(c => !isNew(c));
  const bans = changes.filter(c => c.field_name === 'status' && c.new_value === 'מורחק');
  const html = `
    ${truncated ? `<div style="padding:8px 12px;background:var(--card2);border-radius:8px;margin-bottom:10px;font-size:12.5px;color:var(--subtext)">
      מוצגים ${LIMIT} השינויים הראשונים בלבד</div>` : ''}
    ${bans.length ? `<div style="padding:10px 12px;background:rgba(244,84,76,.10);border-radius:8px;margin-bottom:12px;font-size:13px">
      🚫 <b>${bans.length}</b> ניקים סומנו כמורחקים בסריקה זו</div>` : ''}
    ${news.length ? `<div class="section-hdr">ניקים חדשים (${news.length})</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">${news.slice(0, 200).map(c =>
        `<span style="background:var(--card2);border-radius:999px;padding:3px 10px;font-size:12px">${esc(c.username)}</span>`).join('')}</div>` : ''}
    ${changes.length ? `<div class="section-hdr">שינויים (${changes.length})</div>
      ${changes.slice(0, 300).map(c => `
        <div style="display:flex;gap:8px;font-size:12.5px;padding:5px 0;border-bottom:1px solid var(--border-soft)">
          <b style="min-width:110px">${esc(c.username)}</b>
          <span style="color:var(--subtext);min-width:80px">${esc(label(c.field_name))}</span>
          <span style="flex:1"><bdi style="color:var(--subtext)">${esc(c.old_value || '(ריק)')}</bdi>
            ← <bdi><b>${esc(c.new_value || '(ריק)')}</b></bdi></span>
        </div>`).join('')}` : ''}
    ${!ch.length ? '<div style="padding:24px;text-align:center;color:var(--subtext)">לא נמצאו שינויים</div>' : ''}`;
  openModal('📋 מה השתנה בסריקה', html, [{ label: 'סגור', cls: 'btn-ghost', action: closeModal }], 'modal-lg');
}

// ══ BACKUP / RESTORE (קובץ DB שלם) ═══════════════════════════════════
async function backupDb() {
  const r = await api('backup_db');
  if (r?.ok) toast(`גיבוי מלא נשמר ✓ (${r.nicks} ניקים)`, 'success');
  else if (r?.error !== 'בוטל') toast('הגיבוי נכשל: ' + (r?.error || ''), 'error');
}

async function restoreDb() {
  if (!confirm('לשחזר מגיבוי?\n\n' +
               'המאגר הנוכחי כולו יוחלף בתוכן הגיבוי — ניקים, פורומים, הגדרות ועוגיות.\n' +
               'עותק בטיחות של המאגר הנוכחי יישמר לצדו לפני ההחלפה.')) return;
  const r = await api('restore_db');
  if (!r?.ok) {
    if (r?.error !== 'בוטל') toast('השחזור נכשל: ' + (r?.error || ''), 'error');
    return;
  }
  S.avatarCache.clear();
  await applyDisplaySettings();
  buildTableHeader();
  await loadForums();
  const inp = document.getElementById('search-input');
  if (inp) inp.value = '';
  await loadNicks('');
  toast(`המאגר שוחזר ✓ (${r.nicks} ניקים)`, 'success');
}

// ══ EXPORT / IMPORT ════════════════════════════════════════════════════
async function exportData() {
  const counts = await api('get_export_counts') || { all: 0, has_info: 0, my_info: 0 };
  const selN = S.multiSelected.size;
  const viewN = S.nicks.length;
  const opt = (mode, icon, title, desc, count, checked) => `
    <label class="policy-opt" style="display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border:1px solid var(--border-soft);border-radius:10px;margin-bottom:8px;cursor:pointer">
      <input type="radio" name="expmode" value="${mode}" ${checked ? 'checked' : ''} style="margin-top:3px">
      <div style="flex:1">
        <div style="font-weight:700;font-size:13.5px">${icon} ${title}
          <span style="float:left;color:var(--accent-2);font-weight:800">${count}</span></div>
        <div style="font-size:12px;color:var(--subtext);margin-top:2px">${desc}</div>
      </div>
    </label>`;
  openModal('📤 ייצוא נתונים', `
    <div style="display:flex;gap:6px;margin-bottom:12px;background:var(--card2);padding:4px;border-radius:8px">
      <label style="flex:1;text-align:center;padding:7px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:700">
        <input type="radio" name="expfmt" value="tiknick" checked> קובץ Tik-Nick (.tiknick)</label>
      <label style="flex:1;text-align:center;padding:7px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:700">
        <input type="radio" name="expfmt" value="csv"> CSV לאקסל</label>
    </div>
    <p style="color:var(--subtext);font-size:12px;margin-bottom:10px">
      בחר אילו ניקים לייצא. חלים גם כללי הסנכרון (אילו שדות ופורומים כלולים).
    </p>
    <p id="exp-extra" style="color:var(--subtext);font-size:11.5px;margin:-4px 0 10px;line-height:1.6">
      בקובץ <b>.tiknick</b> נשמרים גם אנשי הקשר הנוספים (למעט 🔒 סודיים) וקישורי הזהות.
      ב-<b>CSV</b> נשמרות עמודות בלבד.
    </p>
    ${selN ? opt('selected', '☑️', 'הניקים שנבחרו', 'רק השורות המסומנות בטבלה', selN, true) : ''}
    ${opt('view', '🔍', 'התצוגה הנוכחית', 'מה שמוצג עכשיו אחרי חיפוש/סינון', viewN, !selN)}
    ${opt('all', '📦', 'כל הניקים', 'ייצוא מלא של כל המאגר', counts.all, false)}
    ${opt('has_info', '✓', 'רק ניקים עם מידע', 'שם אמיתי / טלפון / מייל / הערות / אנשי קשר / זהות', counts.has_info, false)}
    ${opt('my_info', '👤', 'רק מידע שהוספתי בעצמי', 'ערך שאני הזנתי (מקור "אני") או אנשי קשר / הערות אישיות', counts.my_info, false)}
  `, [
    { label: '📤 ייצא', cls: 'btn-primary', action: async () => {
      let mode = document.querySelector('input[name="expmode"]:checked')?.value || 'all';
      const fmt = document.querySelector('input[name="expfmt"]:checked')?.value || 'tiknick';
      let ids = null;
      if (mode === 'selected') ids = [...S.multiSelected];
      if (mode === 'view') { ids = S.nicks.map(n => n.id); mode = 'selected'; }
      closeModal();
      const res = await api(fmt === 'csv' ? 'export_csv' : 'export_data', mode, ids);
      if (res?.ok) {
        let extra = '';
        if (res.contacts) extra += ` · ${res.contacts} אנשי קשר`;
        if (res.identity_groups) extra += ` · ${res.identity_groups} קבוצות זהות`;
        toast(`יוצאו ${res.count} ניקים ✓${extra}`, 'success');
      }
      else if (res?.error !== 'בוטל') toast('שגיאה בייצוא: ' + (res?.error || ''), 'error');
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
}

let _pendingImportMeta = { name: '', notes: '', trust: 10 };

async function importData() {
  // שלב 1: טען קובץ ובדוק פורומים
  const res = await api('load_import_file');
  if (!res) return;
  if (!res.ok) {
    if (res.error !== 'בוטל') toast('שגיאה בייבוא: ' + res.error, 'error');
    return;
  }
  // קובץ טבלה — קודם התאמת עמודות, ורק אז אותה זרימה כמו .tiknick
  if (res.kind === 'csv') { showCsvMappingDialog(res); return; }
  // שלב 1.5: פרטי הייבוא (שם, הערות, דרגת אמינות)
  showImportDetailsDialog(res);
}

// ── ייבוא CSV: התאמת עמודות ──────────────────────────────────────────
// קובץ שהתוכנה עצמה ייצאה נפתר לבד (הכותרות הן בדיוק התוויות שלנו) והמשתמש
// רק לוחץ "המשך".
const DELIM_HE = { ',': 'פסיק', '\t': 'טאב', ';': 'נקודה-פסיק', '|': 'קו אנכי' };

async function showCsvMappingDialog(res) {
  const fields = res.fields || [];
  const forums = res.forums || [];
  const opts = (sel) => '<option value="">— לא לייבא —</option>' +
    fields.map(f => `<option value="${esc(f.key)}" ${sel === f.key ? 'selected' : ''}>${esc(f.label)}</option>`).join('');
  const rows = (res.headers || []).map((h, i) => `
    <tr>
      <td style="padding:4px 6px;font-weight:700;font-size:12.5px;max-width:150px;overflow:hidden;text-overflow:ellipsis">${esc(h || '(ללא כותרת)')}</td>
      <td style="padding:4px 6px;font-size:11.5px;color:var(--subtext);max-width:150px;overflow:hidden;text-overflow:ellipsis" dir="auto">${esc((res.sample || {})[String(i)] || '')}</td>
      <td style="padding:4px 6px">
        <select class="form-input csv-map" data-idx="${i}" style="font-size:12px;padding:4px 6px">
          ${opts((res.mapping || {})[String(i)])}
        </select>
        <div class="csv-note" data-note="${i}" style="font-size:10.5px;color:var(--subtext);margin-top:2px"></div>
      </td>
    </tr>`).join('');

  openModal('📥 ייבוא CSV — התאמת עמודות', `
    <p style="color:var(--subtext);font-size:12px;margin-bottom:10px;line-height:1.7">
      <b dir="auto">${esc(res.path)}</b> · נמצאו <b>${esc(res.row_count)}</b> שורות ·
      קידוד: <span dir="ltr">${esc(res.encoding)}</span> ·
      מפריד: ${esc(DELIM_HE[res.delimiter] || res.delimiter)}
    </p>
    <div style="max-height:46vh;overflow:auto;border:1px solid var(--border-soft);border-radius:8px">
      <table style="width:100%;border-collapse:collapse">
        <thead><tr style="position:sticky;top:0;background:var(--card2)">
          <th style="padding:6px;text-align:right;font-size:11px">עמודה בקובץ</th>
          <th style="padding:6px;text-align:right;font-size:11px">דוגמה</th>
          <th style="padding:6px;text-align:right;font-size:11px">ייובא לשדה</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="form-group" style="margin-top:12px">
      <label class="form-label">פורום ברירת מחדל (לשורות בלי פורום)</label>
      <select class="form-input" id="csv-forum">
        ${forums.map(f => `<option value="${esc(f)}" ${f === 'כללי' ? 'selected' : ''}>${esc(f)}</option>`).join('')}
      </select>
    </div>
    <label style="display:flex;gap:8px;align-items:center;font-size:12.5px;cursor:pointer">
      <input type="checkbox" id="csv-phone" checked>
      החזר 0 מוביל למספרי טלפון שאקסל קיצץ
    </label>
    <div id="csv-warn" style="color:var(--danger,#e5484d);font-size:12px;margin-top:8px"></div>
  `, [
    { label: 'המשך', cls: 'btn-primary', action: async () => {
      const mapping = {};
      document.querySelectorAll('.csv-map').forEach(sel => {
        if (sel.value) mapping[sel.dataset.idx] = sel.value;
      });
      if (!Object.values(mapping).includes('username')) {
        document.getElementById('csv-warn').textContent = "חובה למפות עמודה ל'שם משתמש'";
        return;
      }
      const r = await api('confirm_csv_mapping', mapping,
                          document.getElementById('csv-forum').value,
                          document.getElementById('csv-phone').checked);
      if (!r?.ok) {
        document.getElementById('csv-warn').textContent = r?.error || 'שגיאה';
        return;
      }
      closeModal();
      let note = `${r.nick_count} שורות לייבוא`;
      if (r.merged_dupes) note += ` · אוחדו כפולים ${r.merged_dupes}`;
      if (r.skipped_no_username) note += ` · דולגו ${r.skipped_no_username} בלי שם משתמש`;
      if (r.merged_dupes || r.skipped_no_username) toast(note, 'info');
      showImportDetailsDialog(r);
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg', { id: 'csv-mapping' });

  // הערות פר-שדה (סטטוס/מוניטין נקבעים בסריקה) — מוצגות מתחת לבורר שנבחר
  const notes = {};
  fields.forEach(f => { if (f.note) notes[f.key] = f.note; });
  const refreshNotes = () => document.querySelectorAll('.csv-map').forEach(sel => {
    const el = document.querySelector(`[data-note="${sel.dataset.idx}"]`);
    if (el) el.textContent = notes[sel.value] || '';
  });
  document.querySelectorAll('.csv-map').forEach(sel => sel.addEventListener('change', refreshNotes));
  refreshNotes();
}

async function showImportDetailsDialog(res) {
  const myTrust = await api('get_my_trust') ?? 10;
  const nContacts = res.contacts || 0, nGroups = res.identity_groups || 0;
  const sectionRow = (id, icon, text) => `
    <label style="display:flex;gap:8px;align-items:flex-start;font-size:12.5px;
                  padding:7px 9px;border:1px solid var(--border-soft);border-radius:8px;
                  margin-bottom:6px;cursor:pointer">
      <input type="checkbox" id="${id}" checked style="margin-top:2px">
      <span>${icon} ${text}</span>
    </label>`;
  const extras = (nContacts || nGroups) ? `
    <div style="margin-bottom:14px">
      <div style="font-size:11px;font-weight:800;color:var(--subtext);margin-bottom:6px">
        מקטעים נוספים בקובץ</div>
      ${nContacts ? sectionRow('imp-contacts', '📞',
        `לקלוט <b>${nContacts}</b> אנשי קשר נוספים (טלפונים/מיילים)`) : ''}
      ${nGroups ? sectionRow('imp-identities', '🔗',
        `לקלוט <b>${nGroups}</b> קבוצות זהות — הקישור יתבצע רק כששני הצדדים קיימים אצלך`) : ''}
    </div>` : '';
  const newer = res.newer_format ? `
    <div style="background:var(--card2);border-inline-start:3px solid var(--warn,#e59b2b);
                padding:8px 10px;border-radius:6px;font-size:12px;margin-bottom:12px">
      ⚠️ הקובץ נוצר בגרסה חדשה יותר של Tik-Nick. מה שהגרסה הזו לא מכירה יידלג.
    </div>` : '';
  openModal('📥 פרטי הייבוא', newer + extras + `
    <p style="color:var(--subtext);font-size:13px;margin-bottom:14px">
      תן שם למקור הייבוא ודרגת אמינות. בהתנגשות עם מידע קיים — הערך מהמקור בעל
      האמינות הגבוהה יותר ינצח, והאחר יישמר בצד (יסומן ב-⚠️).
    </p>
    <div class="form-group">
      <label class="form-label">שם המקור</label>
      <input class="form-input" id="imp-name" placeholder="למשל: קובץ מיוסי">
    </div>
    <div class="form-group">
      <label class="form-label">הערות (אופציונלי)</label>
      <input class="form-input" id="imp-notes" placeholder="למשל: נתונים מ-2024">
    </div>
    <div class="form-group">
      <label class="form-label">דרגת אמינות: <b id="imp-trust-val">7</b> / 10</label>
      <input type="range" min="1" max="10" value="7" id="imp-trust" style="width:100%"
             oninput="document.getElementById('imp-trust-val').textContent=this.value">
      <div style="font-size:11px;color:var(--subtext);margin-top:4px">
        לשם השוואה — האמינות שלך מוגדרת כ-${myTrust}/10 (ניתן לשינוי בהגדרות סנכרון)
      </div>
    </div>
  `, [
    { label: 'המשך', cls: 'btn-primary', action: () => {
      const cbC = document.getElementById('imp-contacts');
      const cbI = document.getElementById('imp-identities');
      _pendingImportMeta = {
        name: document.getElementById('imp-name').value.trim() || 'ייבוא',
        notes: document.getElementById('imp-notes').value.trim(),
        trust: parseInt(document.getElementById('imp-trust').value) || 7,
        contacts: cbC ? cbC.checked : true,
        identities: cbI ? cbI.checked : true,
      };
      closeModal();
      proceedImport(res);
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
}

async function proceedImport(res) {
  const unknown = res.unknown_forums || [];
  if (unknown.length === 0) { await showImportPreview({}); return; }
  showForumMappingDialog(unknown, res.nick_count);
}

// ── תצוגה מקדימה: מה הייבוא באמת יעשה, לפני שהוא עושה משהו ────────────
// הייבוא אינו הפיך (רק מחיקת ניקים יש לה סל מחזור), ולכן הוא נעצר כאן.
async function showImportPreview(mapping) {
  const start = await api('preview_import', mapping || {},
                          _pendingImportMeta.contacts !== false,
                          _pendingImportMeta.identities !== false);
  if (!start?.ok) { toast('שגיאה בתצוגה המקדימה: ' + (start?.error || ''), 'error'); return; }

  openModal('🔎 בודק…', `
    <div style="text-align:center;padding:22px 16px">
      <div style="font-size:34px;margin-bottom:12px">🔎</div>
      <div id="prev-text" style="font-size:14px">בודק ${esc(start.total)} שורות…</div>
    </div>`, [], 'modal-lg', { id: 'import-preview-wait', dismissable: false });

  const st = await new Promise(resolve => {
    let busy = false;
    const poll = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const p = await api('get_import_progress');
        if (!p) return;
        const t = document.getElementById('prev-text');
        if (t && p.total) t.textContent = `בודק ${p.processed} מתוך ${p.total}…`;
        if (p.done || !p.running) { clearInterval(poll); resolve(p); }
      } finally { busy = false; }
    }, 300);
  });

  if (_currentModalId === 'import-preview-wait') closeModal();
  if (st.error) { toast('שגיאה בתצוגה המקדימה: ' + st.error, 'error'); return; }
  const r = st.result || {};

  const line = (icon, label, value, strong) => `
    <div style="display:flex;justify-content:space-between;padding:6px 2px;
                border-bottom:1px solid var(--border-soft);font-size:13px">
      <span>${icon} ${label}</span>
      <b style="${strong ? 'color:var(--accent-2)' : ''}">${esc(value)}</b>
    </div>`;

  const conflictRows = (r.samples || []).map(x => `
    <tr>
      <td style="padding:3px 6px;font-size:11.5px">${esc(x.username)}
        <span style="color:var(--subtext)">· ${esc(x.forum)}</span></td>
      <td style="padding:3px 6px;font-size:11.5px">${esc(x.field)}</td>
      <td style="padding:3px 6px;font-size:11.5px;color:var(--subtext)" dir="auto">${esc(x.old)}</td>
      <td style="padding:3px 6px;font-size:11.5px" dir="auto">${esc(x.new)}</td>
    </tr>`).join('');

  const conflictBlock = r.conflicts ? `
    <div style="margin-top:12px">
      <div style="font-size:12px;font-weight:800;margin-bottom:5px">
        ⚠️ ${esc(r.conflicts)} ערכים יתנגשו עם מידע קיים
        <span style="font-weight:500;color:var(--subtext)">— ההכרעה לפי אמינות המקור</span>
      </div>
      <div style="max-height:24vh;overflow:auto;border:1px solid var(--border-soft);border-radius:8px">
        <table style="width:100%;border-collapse:collapse">
          <thead><tr style="position:sticky;top:0;background:var(--card2)">
            <th style="padding:5px;text-align:right;font-size:10.5px">ניק</th>
            <th style="padding:5px;text-align:right;font-size:10.5px">שדה</th>
            <th style="padding:5px;text-align:right;font-size:10.5px">קיים</th>
            <th style="padding:5px;text-align:right;font-size:10.5px">מהקובץ</th>
          </tr></thead>
          <tbody>${conflictRows}</tbody>
        </table>
      </div>
      ${r.conflicts > (r.samples || []).length
        ? `<div style="font-size:11px;color:var(--subtext);margin-top:4px">מוצגות ${(r.samples||[]).length} דוגמאות ראשונות מתוך ${esc(r.conflicts)}.</div>` : ''}
    </div>` : '';

  const skipped = (r.skipped_no_username || 0) + (r.skipped_forum || 0);
  const skipBlock = skipped ? `
    <div style="margin-top:10px;font-size:12px;color:var(--subtext);line-height:1.7">
      ${r.skipped_no_username ? `· ${esc(r.skipped_no_username)} שורות בלי שם משתמש יידלגו<br>` : ''}
      ${r.skipped_forum ? `· ${esc(r.skipped_forum)} שורות מפורומים שכיבית בהגדרות (${esc((r.excluded_forums||[]).join(', '))}) יידלגו` : ''}
    </div>` : '';

  openModal('🔎 תצוגה מקדימה לייבוא', `
    <p style="color:var(--subtext);font-size:12px;margin-bottom:10px">
      עדיין לא נכתב דבר. כך ייראה המאגר אחרי הייבוא:
    </p>
    ${line('🆕', 'ניקים חדשים שייווצרו', r.new_nicks || 0, true)}
    ${line('🔁', 'ניקים קיימים שיתעדכנו', r.existing_nicks || 0)}
    ${line('📝', 'ערכים שייכתבו', r.values || 0)}
    ${r.contacts ? line('📞', 'אנשי קשר', r.contacts) : ''}
    ${r.identity_groups ? line('🔗', 'קבוצות זהות', r.identity_groups) : ''}
    ${conflictBlock}
    ${skipBlock}
  `, [
    { label: '📥 בצע ייבוא', cls: 'btn-primary', action: async () => {
      closeModal();
      await runImport(mapping || {});
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg', { id: 'import-preview' });
}

// הייבוא רץ ב-thread רקע בפייתון; כאן חלון התקדמות שנסגר בסיום (בעבר החלון קפא בלי משוב)
async function runImport(mapping) {
  const start = await api('confirm_import', mapping || {}, _pendingImportMeta.name,
                          _pendingImportMeta.notes, _pendingImportMeta.trust,
                          _pendingImportMeta.contacts !== false,
                          _pendingImportMeta.identities !== false);
  if (!start?.ok) { toast('שגיאה בייבוא: ' + (start?.error || ''), 'error'); return; }
  openModal('📥 מייבא…', `
    <div style="text-align:center;padding:24px 16px">
      <div style="font-size:40px;margin-bottom:14px">📥</div>
      <div id="import-progress-text" style="font-size:14px;margin-bottom:8px">מתחיל…</div>
      <div style="font-size:12px;color:var(--subtext)">מייבא ${esc(start.total)} ניקים — נא לא לסגור את התוכנה</div>
      <div style="height:8px;background:var(--card2);border-radius:99px;overflow:hidden;margin-top:16px">
        <div id="import-bar" style="height:100%;width:0%;background:linear-gradient(90deg,var(--accent),var(--accent-2));transition:width .3s"></div>
      </div>
    </div>`, [], 'modal-lg', { id: 'import-progress', dismissable: false });

  const p = await new Promise(resolve => {
    let busy = false;
    const poll = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const st = await api('get_import_progress');
        if (!st) return;
        const pct = st.total ? Math.round(st.processed / st.total * 100) : 0;
        const t = document.getElementById('import-progress-text');
        if (t) t.textContent = `${st.processed} מתוך ${st.total} (${pct}%)`;
        const b = document.getElementById('import-bar');
        if (b) b.style.width = pct + '%';
        if (st.done || !st.running) { clearInterval(poll); resolve(st); }
      } finally { busy = false; }
    }, 400);
  });

  if (_currentModalId === 'import-progress') closeModal();
  if (p.error) { toast('שגיאה בייבוא: ' + p.error, 'error'); return; }
  const r = p.result || {};
  await loadForums();
  await loadNicks(document.getElementById('search-input').value);
  if (r.manual && r.conflicts && r.conflicts.length) {
    startImportConflictResolver(r.conflicts);
  } else {
    let extra = '';
    if (r.contacts) extra += ` · אנשי קשר: ${r.contacts}`;
    if (r.identities) extra += ` · קישורי זהות: ${r.identities}`;
    if (r.identities_skipped) extra += ` · ${r.identities_skipped} קבוצות דולגו (הצד השני לא קיים אצלך)`;
    toast(`הייבוא הושלם ✓ · ניקים חדשים: ${r.imported} · ערכים שנקלטו: ${r.conflicts}${extra}`,
          'success', { ms: extra ? 8000 : 4000 });
  }
}

// פתרון ידני של התנגשויות ייבוא — אחד אחד
let _impConflicts = [];
let _impConflictIdx = 0;

function startImportConflictResolver(conflicts) {
  _impConflicts = conflicts;
  _impConflictIdx = 0;
  showNextImportConflict();
}

function showNextImportConflict() {
  if (_impConflictIdx >= _impConflicts.length) {
    closeModal();
    toast(`פתרון התנגשויות הושלם ✓`, 'success');
    loadNicks(document.getElementById('search-input').value);
    return;
  }
  const c = _impConflicts[_impConflictIdx];
  const fieldLabel = (COLS.find(x => x.key===c.field)?.label) || c.field;
  openModal(`⚠️ התנגשות ${_impConflictIdx+1}/${_impConflicts.length}`, `
    <p style="font-size:13px;margin-bottom:12px">
      <b>${esc(c.username)}</b> <span style="color:var(--subtext)">[${esc(c.forum)}]</span> ·
      שדה: <b>${esc(fieldLabel)}</b>
    </p>
    <div style="display:flex;flex-direction:column;gap:8px">
      <div style="padding:10px;border:1px solid var(--border-soft);border-radius:8px">
        <div style="font-size:11px;color:var(--subtext)">הערך הקיים</div>
        <div style="font-weight:600">${esc(c.old_value)}</div>
      </div>
      <div style="padding:10px;border:1px solid var(--accent);border-radius:8px">
        <div style="font-size:11px;color:var(--subtext)">הערך המיובא (${esc(c.source_name)})</div>
        <div style="font-weight:600">${esc(c.new_value)}</div>
      </div>
    </div>
    <label style="display:flex;align-items:center;gap:6px;margin-top:12px;font-size:12px;color:var(--subtext)">
      <input type="checkbox" id="imp-apply-all"> החל את הבחירה על כל שאר ההתנגשויות
    </label>
  `, [
    { label: 'קבל מיובא', cls: 'btn-primary', action: () => resolveImportConflict(true) },
    { label: 'שמור קיים', cls: 'btn-ghost',   action: () => resolveImportConflict(false) },
    { label: '⏸️ עצור כאן', cls: 'btn-ghost', action: stopImportConflicts },
  ], 'modal-sm', { id: 'import-conflict', dismissable: false });
}

async function resolveImportConflict(accept) {
  const all = document.getElementById('imp-apply-all')?.checked;
  const c = _impConflicts[_impConflictIdx];
  await api('apply_import_conflict', c.nick_id, c.field, c.new_value, c.source_id, accept);
  _impConflictIdx++;
  if (all && _impConflictIdx < _impConflicts.length) {
    // החל את אותה בחירה על כל השאר — בקריאה אחת (לא קריאת גשר לכל התנגשות)
    const rest = _impConflicts.slice(_impConflictIdx);
    toast(`מחיל על ${rest.length} התנגשויות…`, 'info');
    const r = await api('apply_import_conflicts', rest, accept);
    if (!r?.ok) { toast('ההחלה נכשלה: ' + (r?.error || ''), 'error'); return; }
    _impConflictIdx = _impConflicts.length;
  }
  showNextImportConflict();
}

function stopImportConflicts() {
  const done = _impConflictIdx, total = _impConflicts.length;
  _impConflictIdx = total;
  closeModal();
  toast(`הופסק אחרי ${done} מתוך ${total} — ${total - done} הערכים שנותרו לא הוחלו (הקיים נשמר)`, 'info');
  loadNicks(document.getElementById('search-input').value);
}

async function showForumMappingDialog(unknownForums, totalNicks) {
  const existingForums = S.forums.map(f => f.name);

  // בדוק אילו פורומים לא מוכרים מוכרים בכלל ב-KNOWN_FORUMS
  const knownAll = await api('get_known_forums') || [];
  const knownMap = {};
  knownAll.forEach(k => { knownMap[k.name.toLowerCase()] = k; });

  const rows = unknownForums.map(fname => {
    const knownMatch = knownMap[fname.toLowerCase()];
    const matchNote  = knownMatch
      ? `<div id="fmap-note-${esc(fname)}"
              style="font-size:11px;color:var(--success);margin-top:6px">
           ✓ נמצא ברשימה המוכרת — יוסף עם קישור וצבע אוטומטית
         </div>`
      : `<div id="fmap-note-${esc(fname)}" style="font-size:11px;color:var(--subtext);margin-top:6px"></div>`;
    return `
    <div style="background:var(--card2);border-radius:6px;padding:12px 14px;margin-bottom:8px">
      <div style="font-weight:700;color:var(--text);margin-bottom:8px">
        📁 <span style="color:var(--warn)">"${esc(fname)}"</span>
        <span style="font-size:12px;color:var(--subtext);font-weight:400"> — פורום לא מוכר</span>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <label style="font-size:12px;color:var(--subtext);white-space:nowrap">מזג לתוך:</label>
        <select class="form-select fmap-select" data-fname="${esc(fname)}" style="flex:1">
          <option value="">— הוסף כפורום חדש —</option>
          ${existingForums.map(ef =>
            `<option value="${esc(ef)}">${esc(ef)}</option>`
          ).join('')}
        </select>
      </div>
      ${matchNote}
    </div>`;
  }).join('');

  const html = `
    <div style="margin-bottom:14px;padding:10px 14px;background:rgba(88,166,255,.08);
                border:1px solid rgba(88,166,255,.2);border-radius:6px;font-size:13px">
      📥 הקובץ מכיל <b>${totalNicks}</b> ניקים.<br>
      נמצאו <b>${unknownForums.length}</b> פורומים שאינם קיימים אצלך.
      לכל אחד — בחר אם למזג לפורום קיים או להוסיף כחדש.
    </div>
    ${rows}`;

  // handler לשינוי בחירה — מעדכן הודעה
  window.fmapOnChange = (sel, fname) => {
    const noteEl = document.getElementById(`fmap-note-${fname}`);
    if (!noteEl) return;
    if (sel.value === '') {
      // "הוסף כפורום חדש" — בדוק אם מוכר
      const match = knownMap[fname.toLowerCase()];
      if (match) {
        noteEl.style.color = 'var(--success)';
        noteEl.textContent = '✓ נמצא ברשימה המוכרת — יוסף עם קישור וצבע אוטומטית';
      } else {
        noteEl.style.color = 'var(--subtext)';
        noteEl.textContent = 'יוסף כפורום חדש ללא קישור';
      }
    } else {
      noteEl.style.color = 'var(--accent)';
      noteEl.textContent = `→ יוזג לתוך "${sel.value}"`;
    }
  };

  openModal('📥 ייבוא — מיפוי פורומים', html, [
    { label: 'המשך לתצוגה מקדימה', cls: 'btn-primary', action: async () => {
      const mapping = {};
      // משתמש ב-data-fname במקום id כדי לתמוך בעברית ורווחים
      document.querySelectorAll('.fmap-select').forEach(sel => {
        const fname = sel.dataset.fname;
        if (sel.value && sel.value !== '') {
          mapping[fname] = sel.value;  // מיזוג לפורום קיים
        }
        // ערך ריק = הוסף כפורום חדש — Python יטפל
      });
      closeModal();
      await showImportPreview(mapping);   // תמיד תצוגה מקדימה לפני כתיבה
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ]);
}

// ══ RESET ══════════════════════════════════════════════════════════════
async function confirmReset() {
  const cols = await api('get_resettable_columns') || [];
  const colChecks = cols.map(col => `
    <div class="col-picker-item">
      <input type="checkbox" class="reset-col" value="${col.key}" id="rst-${col.key}">
      <label for="rst-${col.key}">${esc(col.label)}</label>
    </div>`).join('');

  const html = `
    <div class="reset-tabs">
      <button class="reset-tab active" onclick="switchResetTab('data',this)">🗑️ מאגר הניקים</button>
      <button class="reset-tab" onclick="switchResetTab('settings',this)">⚙️ הגדרות</button>
    </div>

    <div id="reset-data" class="reset-pane">
      <div style="padding:10px 14px;background:rgba(244,84,76,.08);border:1px solid rgba(244,84,76,.25);border-radius:8px;font-size:13px;margin-bottom:16px">
        ⚠️ פעולות אלו בלתי הפיכות
      </div>
      <div class="reset-choice">
        <button class="btn btn-danger" style="width:100%" onclick="doResetAll()">
          🗑️ מחק את כל הניקים לגמרי
        </button>
      </div>
      <div class="section-hdr" style="margin-top:20px">או — אפס עמודות ספציפיות</div>
      <p style="font-size:12px;color:var(--subtext);margin-bottom:10px">
        רוקן ערכים בעמודות נבחרות בכל הניקים, בלי למחוק את השורות עצמן
      </p>
      <div class="reset-col-actions" style="margin-bottom:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button class="btn btn-ghost btn-sm" onclick="toggleAllResetCols(true)">בחר הכל</button>
        <button class="btn btn-ghost btn-sm" onclick="toggleAllResetCols(false)">נקה בחירה</button>
        <button class="btn btn-warning btn-sm" style="margin-right:auto" onclick="doResetColumns()">
          🧹 אפס עמודות נבחרות
        </button>
      </div>
      <div class="col-picker" style="max-height:220px;overflow-y:auto">${colChecks}</div>
    </div>

    <div id="reset-settings" class="reset-pane" style="display:none">
      <div style="padding:10px 14px;background:var(--accent-soft);border-radius:8px;font-size:13px;margin-bottom:16px">
        ℹ️ מאפס הגדרות תצוגה וסנכרון לברירת המחדל. הניקים לא ייפגעו.
      </div>
      <button class="btn btn-primary" style="width:100%" onclick="doResetSettings()">
        ⚙️ אפס הגדרות לברירת מחדל
      </button>
    </div>`;

  openModal('🔴 איפוס נתונים', html, [
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ]);
}

function switchResetTab(tab, btn) {
  document.querySelectorAll('.reset-tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('reset-data').style.display     = tab==='data' ? 'block':'none';
  document.getElementById('reset-settings').style.display = tab==='settings' ? 'block':'none';
}

function toggleAllResetCols(val) {
  document.querySelectorAll('.reset-col').forEach(cb => cb.checked = val);
}

async function doResetAll() {
  if (!confirm('למחוק את כל הניקים לגמרי? פעולה בלתי הפיכה!')) return;
  if (!confirm('בטוח לחלוטין?')) return;
  await api('reset_all');
  S.selectedId = null;
  closeModal();
  await loadNicks();
  toast('כל הניקים נמחקו', 'info');
}

async function doResetColumns() {
  const selected = [...document.querySelectorAll('.reset-col:checked')].map(cb => cb.value);
  if (!selected.length) { toast('בחר לפחות עמודה אחת', 'error'); return; }
  if (!confirm(`לאפס ${selected.length} עמודות בכל הניקים?`)) return;
  const res = await api('reset_columns', selected);
  closeModal();
  await loadNicks();
  toast(`${res?.count||0} עמודות אופסו`, 'success');
}

async function doResetSettings() {
  if (!confirm('לאפס את כל ההגדרות לברירת מחדל?')) return;
  await api('reset_settings_only');
  closeModal();
  await applyDisplaySettings();
  buildTableHeader();
  await loadNicks();
  toast('ההגדרות אופסו', 'success');
}

// ══ TOOLTIP ════════════════════════════════════════════════════════════
async function showContactsTooltip(e, nickId) {
  const tok = ttBegin();
  const nick = await api('get_nick', nickId);
  if (!ttValid(tok)) return;
  const cts  = nick?.contacts || [];
  if (!cts.length) return;
  const html = cts.map(ct =>
    `<div>${ct.type==='phone'?'📞':'📧'} ${esc(ct.value)}${ct.label?' ['+esc(ct.label)+']':''}</div>`
  ).join('');
  showTooltip(e, `<b>פרטי קשר נוספים:</b><br>${html}`);
}

async function showIdentityTooltip(e, nickId) {
  const cx = e.clientX, cy = e.clientY;
  const tok = ttBegin();
  const nick = await api('get_nick', nickId);
  if (!ttValid(tok)) return;
  const list = nick?.identities || [];
  if (!list.length) return;
  const html = list.map(i =>
    `<div><span style="color:${S.forumColors[i.forum]||'#8b90a0'}">[${esc(i.forum)}]</span>
    <b style="margin-right:6px">${esc(i.username)}</b></div>`
  ).join('');
  showTooltipAt(cx, cy, `<b>זהויות נוספות:</b><br>${html}<br><small>לחץ לניהול</small>`);
}

function showTooltip(e, html) {
  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.style.display = '';
  const x = Math.min(e.clientX + 12, window.innerWidth  - 300);
  const y = Math.min(e.clientY + 12, window.innerHeight - 150);
  tt.style.left = x + 'px';
  tt.style.top  = y + 'px';
}

function hideTooltip() {
  _ttSeq++;   // מבטל תשובות שנמצאות בדרך
  document.getElementById('tooltip').style.display = 'none';
}

// ══ MODAL ═════════════════════════════════════════════════════════════
// מזהה החלון הפתוח כרגע — כדי שתהליך רקע שמסתיים לא ידרוס חלון אחר
let _currentModalId = '';

function openModal(title, bodyHtml, buttons = [], extraClass = '', opts = {}) {
  closeModal();
  _currentModalId = opts.id || '';
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'modal-overlay';
  overlay.dataset.dismissable = opts.dismissable === false ? '0' : '1';
  // דיאלוגים עם הזנת נתונים אינם נסגרים בלחיצה על הרקע (איבוד עבודה)
  if (opts.dismissable !== false) {
    overlay.onclick = e => { if (e.target === overlay) closeModal(); };
  }

  const btnsHtml = buttons.map((b, i) =>
    `<button class="btn ${b.cls}" id="mb-idx-${i}">${b.label}</button>`
  ).join('');

  overlay.innerHTML = `
    <div class="modal ${extraClass}">
      <div class="modal-header">
        <div class="modal-title">${esc(title)}</div>
        <button class="modal-close" onclick="requestCloseModal()">✕</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${buttons.length ? `<div class="modal-footer">${btnsHtml}</div>` : ''}
    </div>`;

  document.body.appendChild(overlay);

  buttons.forEach((b, i) => {
    const el = overlay.querySelector(`#mb-idx-${i}`);
    if (el) el.onclick = b.action;
  });
}

// ה-✕ הוא ה"סגור" הטבעי, ולכן הוא חייב לכבד את אותה הגנה כמו Esc ולחיצת רקע.
function requestCloseModal() {
  const ov = document.getElementById('modal-overlay');
  if (ov && ov.dataset.dismissable === '0' &&
      !confirm('לסגור את החלון? מה שהוזן כאן לא יישמר, ופעולה שכבר התחילה תמשיך לרוץ ברקע.')) return;
  closeModal();
}

function closeModal() {
  document.getElementById('modal-overlay')?.remove();
  _currentModalId = '';
}

// Esc סוגר חלון — רק חלונות שאינם הזנת-נתונים (בהם Esc בטעות = איבוד עבודה)
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const pop = document.getElementById('contact-pop');
  if (pop) { pop.remove(); return; }          // קודם חלון המשנה
  const ov = document.getElementById('modal-overlay');
  if (ov && ov.dataset.dismissable !== '0') closeModal();
});

// ══ TOAST ═════════════════════════════════════════════════════════════
function toast(msg, type = 'info', opts = {}) {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  // כפתור פעולה (למשל "↩ בטל" אחרי מחיקה)
  if (opts.actionLabel && typeof opts.onAction === 'function') {
    const btn = document.createElement('button');
    btn.className = 'toast-action';
    btn.textContent = opts.actionLabel;
    btn.onclick = (e) => { e.stopPropagation(); el.remove(); opts.onAction(); };
    el.appendChild(btn);
  }
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), opts.ms || (opts.actionLabel ? 7000 : 3500));
}

// ══ STATUS ════════════════════════════════════════════════════════════
function setStatus(msg) {
  document.getElementById('status-msg').textContent = msg;
}

// ══ API BRIDGE ════════════════════════════════════════════════════════
async function api(method, ...args) {
  // אם ה-API עדיין לא מוכן — המתן לו (עד 10 שניות)
  if (!apiReady()) {
    const ok = await waitForApi();
    if (!ok) {
      console.error(`[Tik-Nick] api.${method} — API לא זמין`);
      return null;
    }
  }
  try {
    const fn = window.pywebview.api[method];
    if (typeof fn !== 'function') {
      console.error(`[Tik-Nick] api.${method} — מתודה לא קיימת`);
      return null;
    }
    return await fn(...args);
  } catch (e) {
    console.error(`[Tik-Nick] api.${method} error:`, e);
    toast('שגיאת API: ' + method, 'error');
    return null;
  }
}

// ══ UTILS ═════════════════════════════════════════════════════════════
function updateForumLink(forumName) {
  const forum = S.forums.find(f => f.name === forumName);
  const btn   = document.getElementById('forum-link-btn');
  if (!btn) return;
  if (forum?.url) {
    btn.href = forum.url;
    btn.style.display = 'flex';
  } else {
    btn.href = '#';
    btn.style.display = 'none';
  }
}

// ══ DISPLAY SETTINGS ══════════════════════════════════════════════════
const DISPLAY = {
  theme: 'dark', accent: 'amber', view: 'table',
  density: 'normal', hidden_cols: '', col_layout: '',
};

const ACCENTS = [
  ['teal',    '#14b8a6', 'טורקיז'],
  ['indigo',  '#6366f1', 'אינדיגו'],
  ['emerald', '#10b981', 'ירוק'],
  ['sky',     '#0ea5e9', 'תכלת'],
  ['violet',  '#8b5cf6', 'סגול'],
  ['amber',   '#f59e0b', 'ענבר'],
  ['rose',    '#f43f5e', 'ורוד'],
  ['slate',   '#64748b', 'אפור'],
];

async function applyDisplaySettings() {
  const s = await api('get_display_settings');
  if (s) Object.assign(DISPLAY, s);
  loadColLayout(DISPLAY.col_layout);   // אחרי הטעינה, אחרת נקרא ערך ישן
  applyTheme();
  applyView();
  document.body.dataset.density  = DISPLAY.density;
  updateViewToggle();
  updateThemeToggleIcon();
}

function applyTheme() {
  let theme = DISPLAY.theme;
  if (theme === 'system') {
    theme = window.matchMedia &&
            window.matchMedia('(prefers-color-scheme: light)').matches
            ? 'light' : 'dark';
  }
  document.documentElement.dataset.theme  = theme;
  document.documentElement.dataset.accent = DISPLAY.accent || 'amber';
}

function applyView() {
  document.body.dataset.view = DISPLAY.view;
  updateViewToggle();
  // הכרטיסים נבנים רק כשהתצוגה פעילה — לכן יש לבנותם במעבר אליה
  if (DISPLAY.view === 'cards') renderCards();   // גם כשריק — מנקה כרטיסים ישנים
}

function updateViewToggle() {
  const t = document.getElementById('vt-table');
  const cc = document.getElementById('vt-cards');
  if (t)  t.classList.toggle('active',  DISPLAY.view === 'table');
  if (cc) cc.classList.toggle('active', DISPLAY.view === 'cards');
}

async function setView(view) {
  DISPLAY.view = view;
  applyView();
  await api('set_display_setting', 'view', view);
}

// חלון וירטואלי בונה ~30 שורות בכל פריים גלילה, וכל שורה בנתה מחדש את קבוצת
// העמודות המוסתרות מתוך מחרוזת ההגדרות. הקבוצה נבנית פעם אחת לחלון.
let _visibleColsCache = null;

function hiddenColsSet() {
  return new Set((DISPLAY.hidden_cols || '').split(',').filter(Boolean));
}

// ══ NICK APPEARANCE (color + avatar) ══════════════════════════════════
const NICK_COLORS = [
  '', '#f59e0b','#ef4444','#ec4899','#8b5cf6','#6366f1',
  '#0ea5e9','#14b8a6','#10b981','#84cc16','#f97316','#64748b',
];

function nickColorSwatches(selected) {
  return NICK_COLORS.map(col => {
    const isNone = col === '';
    const active = (selected || '') === col ? 'active' : '';
    const bg = isNone ? 'var(--card2)' : col;
    const inner = isNone ? '<span style="font-size:14px;color:var(--subtext)">∅</span>' : '';
    return `<div class="nick-swatch ${active}" style="background:${bg};color:${col||'var(--subtext)'}"
                 title="${isNone?'ללא':col}" onclick="pickNickColor('${col}',this)">${inner}</div>`;
  }).join('');
}

function pickNickColor(col, el) {
  document.getElementById('f-nick_color').value = col;
  document.querySelectorAll('#nick-color-swatches .nick-swatch')
    .forEach(s => s.classList.remove('active'));
  el.classList.add('active');
  // update avatar preview background if no image
  const prev = document.getElementById('avatar-preview');
  const initial = prev?.querySelector('.avatar-initial');
  if (initial) initial.style.background = col || 'var(--accent)';
}

function handleAvatarUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    toast('התמונה גדולה מדי (מקסימום 2MB)', 'error');
    return;
  }
  const reader = new FileReader();
  reader.onload = (e) => {
    // resize to max 200px to keep DB light
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      const max = 200;
      let { width, height } = img;
      if (width > height && width > max) { height = height * max / width; width = max; }
      else if (height > max) { width = width * max / height; height = max; }
      canvas.width = width; canvas.height = height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, width, height);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.82);
      document.getElementById('f-avatar_image').value = dataUrl;
      const prev = document.getElementById('avatar-preview');
      prev.innerHTML = `<img src="${dataUrl}" alt="">`;
      document.getElementById('avatar-remove').style.display = 'inline-flex';
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

function removeAvatar() {
  document.getElementById('f-avatar_image').value = '';
  const prev = document.getElementById('avatar-preview');
  const color = document.getElementById('f-nick_color')?.value || 'var(--accent)';
  const uname = document.getElementById('f-username')?.value || '?';
  // בלי innerHTML בכלל: הצבע נקבע כמאפיין סגנון, כמו ב-pickNickColor.
  // כאן זה המסמך הראשי (לא iframe מסונן), ולכן הזרקה כאן חמורה יותר.
  prev.textContent = '';
  const initial = document.createElement('span');
  initial.className = 'avatar-initial';
  initial.style.background = safeColor(color);
  initial.textContent = uname.charAt(0).toUpperCase();
  prev.appendChild(initial);
  document.getElementById('avatar-remove').style.display = 'none';
}

// ══ QUICK THEME TOGGLE ════════════════════════════════════════════════
async function quickToggleTheme() {
  // מחזוריות: כהה → בהיר → מערכת → כהה
  const cycle = ['dark', 'light', 'system'];
  const idx   = cycle.indexOf(DISPLAY.theme);
  const next  = cycle[(idx + 1) % cycle.length];
  DISPLAY.theme = next;
  applyTheme();
  updateThemeToggleIcon();
  // sync settings dialog if open
  document.querySelectorAll('.theme-card').forEach(el => {
    el.classList.toggle('active', el.dataset.theme === next);
  });
  await api('set_display_setting', 'theme', next);
  const names = {dark:'כהה', light:'בהיר', system:'מערכת'};
  toast(`מצב ${names[next]}`, 'info');
}

function resolvedTheme() {
  if (DISPLAY.theme === 'system') {
    return (window.matchMedia &&
            window.matchMedia('(prefers-color-scheme: light)').matches)
            ? 'light' : 'dark';
  }
  return DISPLAY.theme;
}

function updateThemeToggleIcon() {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const icon = btn.querySelector('.tt-icon');
  const map = {
    dark:   ['🌙', 'מצב כהה · לחץ לבהיר'],
    light:  ['☀️', 'מצב בהיר · לחץ למערכת'],
    system: ['💻', 'לפי המערכת · לחץ לכהה'],
  };
  const [ic, title] = map[DISPLAY.theme] || map.dark;
  if (icon) icon.textContent = ic;
  btn.title = title;
  btn.dataset.mode = DISPLAY.theme;
}

// ══ FEATURE BUTTONS (placeholders) ════════════════════════════════════
// ══ סנכרון לאינטרנט (סריקת פורומי NodeBB) ═══════════════════════════════
let _scrapePoll = null;

const PLATFORM_LABELS = { nodebb: 'NodeBB', discourse: 'Discourse',
  xenforo: 'XenForo', phpbb: 'phpBB', custom: 'מערכת ייחודית' };
const SCRAPABLE_PLATFORMS = new Set(['nodebb', 'discourse']);

async function openInternetSync() {
  const forums = await api('get_scrapable_forums') || [];
  const known = await api('get_known_forums') || [];
  const loginOf = {};
  known.forEach(k => { loginOf[k.name] = !!k.needs_login; });
  const opts = forums.map(f => {
    const plat = f.platform || 'nodebb';
    const needsLogin = loginOf[f.name];
    const scrapable = SCRAPABLE_PLATFORMS.has(plat);
    const tag = !scrapable ? ' ⛔' : (needsLogin ? ' 🔒' : '');
    return `<option value="${esc(f.name)}" data-url="${esc(f.url || '')}"
             data-platform="${esc(plat)}" data-login="${needsLogin?'1':'0'}">${esc(f.name)}${tag}</option>`;
  }).join('');

  // הפעלה ראשונה: אין עדיין פורומים עם כתובת — הסבר במקום דיאלוג ריק
  if (!forums.length) {
    openModal('🌐 סנכרון לאינטרנט', `
      <div style="text-align:center;padding:18px 10px">
        <div style="font-size:44px;margin-bottom:12px">🏛️</div>
        <h3 style="font-size:16px;margin-bottom:8px">עדיין אין פורומים לסריקה</h3>
        <p style="color:var(--subtext);font-size:13px;line-height:1.7">
          כדי לסרוק משתמשים מהאינטרנט, קודם מוסיפים פורום.<br>
          ב"ניהול פורומים" יש רשימה מוכנה של פורומים חרדיים — לחיצה על ➕ מוסיפה פורום עם כתובת וצבע.
        </p>
      </div>`, [
      { label: '🏛️ לניהול פורומים', cls: 'btn-primary', action: () => { closeModal(); openForumMgr(); } },
      { label: 'סגור', cls: 'btn-ghost', action: closeModal },
    ], 'modal-sm');
    return;
  }

  openModal('🌐 סנכרון לאינטרנט', `
    <p style="color:var(--subtext);font-size:13px;line-height:1.6;margin-bottom:16px">
      סורק את רשימת המשתמשים של פורום (NodeBB או Discourse) דרך ה-API הרשמי, ומוסיף/מעדכן
      ניקים אוטומטית. שדות ריקים מתמלאים; ערך סרוק סותר נשמר לצד הקיים ומוכרע לפי אמינות.
    </p>

    <div class="section-hdr">בחירת פורום</div>
    <label style="display:block;font-size:12px;margin-bottom:6px;color:var(--subtext)">פורום לסריקה</label>
    <select id="sync-forum" class="form-select" style="width:100%;margin-bottom:6px" onchange="onSyncForumChange()">${opts}</select>
    <div id="sync-forum-hint" style="font-size:12px;margin-bottom:12px;min-height:16px"></div>

    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;gap:8px">
      <label style="font-size:12px;color:var(--subtext)">
        עוגיית התחברות (<span id="sync-cookie-name" dir="ltr">express.sid</span>) — רק אם הפורום דורש התחברות לצפייה במשתמשים (לא חובה). נשמרת לפעם הבאה.
      </label>
      <button class="btn btn-ghost btn-sm" style="white-space:nowrap;flex-shrink:0"
              onclick="toggleCookieHelp('sync-cookie-help')" title="איך משיגים עוגיות?">🍪 איך משיגים?</button>
    </div>
    <input id="sync-cookie" class="form-input" style="width:100%;margin-bottom:12px" dir="ltr"
           placeholder="הדבק כאן את ערך העוגייה (השאר ריק אם הפורום ציבורי)">
    <div id="sync-cookie-help" style="display:none"></div>

    <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
      <label style="font-size:12px;color:var(--subtext);white-space:nowrap">הגבל עמודים (אופציונלי):</label>
      <input id="sync-maxpages" type="number" min="1" class="form-input" style="width:120px"
             placeholder="הכל" title="כמה עמודי משתמשים לסרוק לכל היותר (ריק = הכל)">
      <span style="font-size:11px;color:var(--subtext)">~50 משתמשים בעמוד</span>
    </div>

    <div class="section-hdr">אוטומציה ותיעוד</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
      <button class="btn btn-ghost btn-sm" onclick="openScheduler(openInternetSync)"
              title="סריקה אוטומטית לפי לוח זמנים — כבויה כברירת מחדל">⏰ סריקה מתוזמנת</button>
      <button class="btn btn-ghost btn-sm" onclick="openScanRuns(openInternetSync)"
              title="מה השתנה בסריקות האחרונות">🕒 יומן סריקות</button>
    </div>

    <div id="sync-check-result" style="font-size:13px;margin-bottom:12px;min-height:20px"></div>

    <div id="sync-progress-wrap" style="display:none;margin-top:8px">
      <div style="height:12px;background:var(--card2);border-radius:99px;overflow:hidden;margin-bottom:8px">
        <div id="sync-bar" style="height:100%;width:0%;background:linear-gradient(90deg,var(--accent),var(--accent-2));transition:width .3s"></div>
      </div>
      <div id="sync-progress-text" style="font-size:12px;color:var(--subtext);text-align:center"></div>
    </div>
  `, [
    { label: 'בדוק פורום', cls: 'btn-ghost',   action: doForumCheck },
    { label: 'התחל סריקה', cls: 'btn-primary', action: doStartScrape },
    { label: '🌍 סרוק הכל', cls: 'btn-ghost', action: doStartScrapeAll },
    { label: 'סגור',        cls: 'btn-ghost',   action: closeSyncModal },
  ], 'modal-lg');
  S.lastScrapes = await api('get_last_scrapes') || {};
  onSyncForumChange();
  // אם סריקה כבר רצה ברקע — הראה זאת במקום דיאלוג שנראה "רדום"
  api('get_scrape_progress').then(p => {
    if (!p || !p.running) return;
    const wrap = document.getElementById('sync-progress-wrap');
    if (wrap) wrap.style.display = '';
    const t = document.getElementById('sync-progress-text');
    if (t) t.textContent = `סריקה פעילה כרגע: ${p.forum || ''} · עמוד ${p.page}/${p.total_pages || '?'}`;
    if (!_scrapePoll) startScrapeMonitor();
  });
}

// טוען את העוגייה השמורה לפורום הנבחר לתוך שדה העוגייה
async function syncPrefillCookie() {
  const sel = document.getElementById('sync-forum');
  const url = sel?.selectedOptions[0]?.dataset.url || '';
  const input = document.getElementById('sync-cookie');
  if (!input || !url) return;
  const saved = await api('get_saved_cookie', url);
  input.value = saved || '';
}

async function doStartScrapeAll() {
  if (!confirm('לסרוק את כל הפורומים ברצף?\n\n' +
               'פורום שלא ניתן לסרוק יידלג אוטומטית.\n' +
               'לכל פורום תשמש רק העוגייה השמורה שלו — עוגייה של פורום אחד לא תישלח לאחרים.')) return;
  const maxPages = parseInt(document.getElementById('sync-maxpages')?.value) || null;
  const start = await api('start_scrape_all', '', maxPages);
  if (!start || !start.ok) { toast(start?.error || 'לא ניתן להתחיל', 'error'); return; }
  const wrap = document.getElementById('sync-progress-wrap');
  if (wrap) wrap.style.display = '';
  startScrapeMonitor();
}

function closeSyncModal() {
  closeModal();
}

async function doForumCheck() {
  const sel = document.getElementById('sync-forum');
  const url = sel.selectedOptions[0]?.dataset.url || '';
  const cookie = document.getElementById('sync-cookie').value.trim();
  const box = document.getElementById('sync-check-result');
  if (!url) { box.innerHTML = '<span style="color:var(--danger)">לפורום זה אין כתובת URL</span>'; return; }
  box.innerHTML = '<span style="color:var(--subtext)">בודק…</span>';
  const r = await api('check_forum', url, cookie);
  if (r && r.ok) {
    const platName = PLATFORM_LABELS[r.platform] || r.platform || 'פורום';
    const cnt = r.user_count != null ? `~${r.user_count} משתמשים` : 'זמין';
    box.innerHTML = `<span style="color:var(--success)">✓ ${esc(platName)} תקין (${esc(String(cnt))})</span>`;
    // עדכן את סימון הפלטפורמה באופציה הנבחרת (נשמר גם בצד השרת)
    if (sel.selectedOptions[0] && r.platform) sel.selectedOptions[0].dataset.platform = r.platform;
    updateSyncHint();   // רק הרמז — לא לדרוס את העוגייה שהוקלדה זה עתה
  } else {
    box.innerHTML = `<span style="color:var(--danger)">✕ ${esc(r?.error || 'בדיקה נכשלה')}</span>`;
  }
}

async function doStartScrape() {
  const sel = document.getElementById('sync-forum');
  const name = sel.value;
  const opt  = sel.selectedOptions[0];
  const url  = opt?.dataset.url || '';
  const plat = opt?.dataset.platform || 'nodebb';
  const cookie = document.getElementById('sync-cookie').value.trim();
  const maxPages = parseInt(document.getElementById('sync-maxpages')?.value) || null;
  if (!url) { toast('לפורום זה אין כתובת URL', 'error'); return; }
  if (!SCRAPABLE_PLATFORMS.has(plat)) {
    toast(`פלטפורמת ${PLATFORM_LABELS[plat] || plat} אינה נתמכת לסריקה אוטומטית`, 'error');
    return;
  }

  const start = await api('start_scrape', name, url, cookie, maxPages);
  if (!start || !start.ok) { toast(start?.error || 'לא ניתן להתחיל סריקה', 'error'); return; }

  const wrap = document.getElementById('sync-progress-wrap');
  if (wrap) wrap.style.display = '';
  const cr = document.getElementById('sync-check-result');
  if (cr) cr.innerHTML = '';
  startScrapeMonitor();
}

// משאיר את הדפדפן לצייר (מסתיר באנר וכו') לפני עבודה כבדה סינכרונית
function _yieldPaint() {
  return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
}

function startScrapeMonitor() {
  if (_scrapePoll) clearInterval(_scrapePoll);
  const banner = document.getElementById('scrape-banner');
  if (banner) banner.style.display = '';

  let busy = false;   // מונע הצטברות של polls איטיים חופפים
  _scrapePoll = setInterval(async () => {
    if (busy) return;
    busy = true;
    try {
    const p = await api('get_scrape_progress');
    if (!p) return;
    const pct = p.total_pages ? Math.round((p.page / p.total_pages) * 100) : 0;
    const forumPrefix = p.all_mode
      ? `[${p.forum_index}/${p.forum_total}] ${p.forum||''} · ` : '';
    // ב"סנכרן נבחרים" המונה הוא ניקים, לא עמודים
    const label = p.selected_mode
      ? `ניק ${p.page} מתוך ${p.total_pages} · עודכנו ${p.updated}`
      : `${forumPrefix}עמוד ${p.page}/${p.total_pages || '?'} · נוספו ${p.added} · עודכנו ${p.updated}`;

    // עדכן באנר צף (תמיד)
    const bBar = document.getElementById('scrape-banner-bar');
    const bTxt = document.getElementById('scrape-banner-text');
    if (bBar) bBar.style.width = pct + '%';
    if (bTxt) bTxt.textContent = p.running ? label : 'מסיים…';
    const skipBtn = document.getElementById('scrape-skip-btn');
    if (skipBtn) skipBtn.style.display = (p.all_mode && p.running) ? '' : 'none';

    // עדכן גם את המודאל אם פתוח
    const mBar = document.getElementById('sync-bar');
    const mTxt = document.getElementById('sync-progress-text');
    if (mBar) mBar.style.width = pct + '%';
    if (mTxt) mTxt.textContent = label;

    if (p.done || !p.running) {
      clearInterval(_scrapePoll); _scrapePoll = null;
      if (banner) banner.style.display = 'none';
      if (p.error) {
        toast('שגיאת סריקה: ' + p.error, 'error');
      } else {
        const partial = (p.failed_pages || 0) > 0;
        // "הוגבלה" = נעצרה בגלל מקסימום עמודים שהמשתמש הגדיר. עד 0.8.5 זה דווח
        // כ"הושלמה", והמשתמש חשב שסרק פורום שלם כשקיבל רק את העמודים הראשונים.
        const msg = p.cancelled ? 'הסריקה בוטלה'
                  : partial ? 'הסריקה הסתיימה חלקית'
                  : p.limited ? 'הסריקה נעצרה לפי ההגבלה שהגדרת' : 'הסריקה הושלמה';
        let extra = '';
        if (partial) extra += ` · ${p.failed_pages} עמודים נכשלו`;
        if (p.limited && !partial) extra += ` · ${p.pages} עמודים`;
        if (p.skipped && p.skipped.length) extra += ` · דולגו ${p.skipped.length} פורומים`;
        // בסריקת "הכל" יש רשומת סריקה לכל פורום — מפנים ליומן ולא לרשומה האחרונה
        const act = p.all_mode ? { actionLabel: '📋 מה השתנה', onAction: openScanRuns, ms: 8000 }
                  : (p.run_id ? { actionLabel: '📋 מה השתנה',
                                  onAction: () => openScanChanges(p.run_id), ms: 8000 } : {});
        if (p.auto) {
          // ריצה שהמשתמש לא התחיל: שקטה כשלא השתנה כלום, ולא טוענת מחדש את
          // הטבלה מתחת לידיים שלו כשחלון פתוח.
          if (p.added || p.updated || partial) {
            toast(`סריקה אוטומטית: נוספו ${p.added}, עודכנו ${p.updated}${extra}`,
                  partial ? 'error' : 'success', act);
          }
        } else {
          toast(`${msg} — נוספו ${p.added}, עודכנו ${p.updated}${extra}`,
                partial ? 'error' : 'success', act);
        }
        // אילו פורומים דולגו ולמה — רק בסריקת "הכל" (ב"סנכרן נבחרים" אלה שמות ניקים)
        if (p.all_mode && p.skipped && p.skipped.length && !p.cancelled && !isModalOpen()) {
          showSkippedForums(p.skipped);
        }
      }
      await _yieldPaint();   // תן לבאנר להיעלם לפני הטעינה הכבדה
      if (p.auto && isModalOpen()) {
        // סריקה שהמשתמש לא התחיל לא תמשוך לו את הרשימה מתחת לידיים באמצע
        // עבודה — מציעים לרענן במקום לעשות זאת בשבילו.
        if (p.added || p.updated) {
          toast('הסריקה האוטומטית עדכנה נתונים', 'info', {
            actionLabel: '🔄 רענן',
            onAction: () => loadNicks(document.getElementById('search-input').value),
            ms: 9000 });
        }
      } else {
        await loadNicks(document.getElementById('search-input').value);
      }
    }
    } finally { busy = false; }
  }, 700);
}

function cookieHelpHtml() {
  return `
      <div style="margin-bottom:14px;padding:14px;border:1px solid var(--accent-2);border-radius:10px">
        <b style="font-size:13px">✅ דרך מומלצת: תוסף Get cookies.txt</b>
        <ol style="margin:8px 0 0;padding-inline-start:20px;font-size:12px;line-height:1.9">
          <li>לחץ כאן להתקנת התוסף:
            <b style="color:var(--accent-2);cursor:pointer;text-decoration:underline"
               onclick="openExt('https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc')">Get cookies.txt LOCALLY</b>
            ← בחלון שנפתח לחץ "Add to Chrome" / "הוסף ל-Chrome" ואשר.</li>
          <li>היכנס לפורום <b>mitmachim.top</b> והתחבר לחשבון שלך (אם עדיין לא).</li>
          <li>לחץ על אייקון התוסף (בפינה הימנית-עליונה של הדפדפן, ליד סרגל הכתובת. אם לא רואים — לחץ על אייקון הפאזל 🧩 ואז על התוסף).</li>
          <li>בחלון שנפתח לחץ על הכפתור <b>"Export"</b> — ייווצר קובץ טקסט, או שהתוכן יועתק.</li>
          <li>בקובץ/טקסט חפש את השורה שכתוב בה <code>express.sid</code>, והעתק את <b>הערך שאחריה</b> (המחרוזת הארוכה שמתחילה ב-<code>s%3A</code>).</li>
          <li>הדבק אותו בשדה "עוגיית express.sid" למטה.</li>
        </ol>
      </div>

      <details style="margin-bottom:14px">
        <summary style="cursor:pointer;font-size:12.5px;font-weight:600">🔧 דרך חלופית: ידנית דרך כלי מפתחים (למתקדמים)</summary>
        <ol style="margin:8px 0 0;padding-inline-start:20px;font-size:12px;line-height:1.9;color:var(--subtext)">
          <li>היכנס לפורום mitmachim.top והתחבר.</li>
          <li>הקש <b>F12</b> לפתיחת כלי המפתחים.</li>
          <li>עבור ללשונית <b>Application</b> (או "אחסון"/Storage בדפדפנים מסוימים).</li>
          <li>בתפריט הצד: <b>Cookies</b> ← לחץ על הכתובת <code>https://mitmachim.top</code>.</li>
          <li>ברשימה שתופיע, מצא את השורה בשם <code>express.sid</code>.</li>
          <li>לחץ עליה, העתק את הערך שבעמודת <b>Value</b> (מתחיל ב-<code>s%3A</code>), והדבק למטה.</li>
        </ol>
      </details>

      <div style="font-size:11.5px;color:var(--subtext);margin-bottom:14px;padding:8px 10px;background:var(--card2);border-radius:6px">
        🔒 העוגייה היא אישית ומאפשרת גישה לחשבון שלך — אל תשתף אותה עם אחרים.
      </div>`;
}

// מציג/מסתיר את ההסבר בתוך החלון הפתוח, בלי לסגור אותו
function toggleCookieHelp(containerId) {
  const box = document.getElementById(containerId);
  if (!box) return;
  if (!box.dataset.filled) { box.innerHTML = cookieHelpHtml(); box.dataset.filled = '1'; }
  box.style.display = box.style.display === 'none' ? '' : 'none';
}

function updateSyncHint() {
  const sel = document.getElementById('sync-forum');
  const opt = sel?.selectedOptions[0];
  const hint = document.getElementById('sync-forum-hint');
  if (!opt || !hint) return;
  const plat = opt.dataset.platform || 'nodebb';
  // שם העוגייה תלוי בפלטפורמה: NodeBB → express.sid, Discourse → _t
  const cookieName = plat === 'discourse' ? '_t' : 'express.sid';
  const ckEl = document.getElementById('sync-cookie-name');
  if (ckEl) ckEl.textContent = cookieName;
  if (!SCRAPABLE_PLATFORMS.has(plat)) {
    hint.innerHTML = `⛔ פלטפורמת ${esc(PLATFORM_LABELS[plat] || plat)} — אין API ציבורי לרשימת משתמשים, ` +
                     `לכן אין סריקה אוטומטית. אפשר להוסיף ולנהל ניקים בפורום זה ידנית.`;
    hint.style.color = 'var(--danger)';
  } else if (opt.dataset.login === '1') {
    hint.innerHTML = `🔒 פורום זה דורש התחברות — הזן את עוגיית <span dir="ltr">${cookieName}</span> למטה (ראה "🍪 איך משיגים?").`;
    hint.style.color = 'var(--accent-2)';
  } else {
    hint.innerHTML = '';
  }
  // נסרק לאחרונה
  const last = (S.lastScrapes || {})[opt.value];
  if (last) {
    hint.innerHTML += (hint.innerHTML ? '<br>' : '') +
      `<span style="color:var(--subtext)">🕒 נסרק לאחרונה: ${esc(relativeTime(last.replace('T', ' ')))}</span>`;
  } else if (!hint.innerHTML) {
    hint.innerHTML = '<span style="color:var(--subtext)">🕒 טרם נסרק</span>';
  }
}

// מופעל בהחלפת פורום: עדכן רמז + טען עוגייה שמורה של הפורום החדש
function onSyncForumChange() {
  updateSyncHint();
  syncPrefillCookie();
}

function showSkippedForums(skipped) {
  const names = [...new Set(skipped.map(s => s.forum).filter(Boolean))];
  const rows = skipped.map(s => `
    <div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--border-soft);font-size:13px">
      <span>⛔</span><b style="min-width:120px">${esc(s.forum)}</b>
      <span style="color:var(--subtext);flex:1">${esc(s.error || '')}</span>
    </div>`).join('');
  openModal(`⛔ ${skipped.length} פורומים דולגו`, `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:10px">
      פורומים אלה לא נסרקו. סיבות נפוצות: הפורום דורש התחברות (הוסף עוגייה),
      הפורום במצב תחזוקה, או שהפלטפורמה אינה נתמכת לסריקה אוטומטית.
    </p>
    ${rows}`, [
    ...(names.length ? [{ label: '🔁 נסה שוב את אלה', cls: 'btn-primary', action: async () => {
      closeModal();
      const r = await api('start_scrape_all', '', null, names);
      if (!r?.ok) { toast(r?.error || 'לא ניתן להתחיל', 'error'); return; }
      startScrapeMonitor();
    }}] : []),
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
}

async function skipCurrentForum() {
  await api('skip_current_forum');
  const bTxt = document.getElementById('scrape-banner-text');
  if (bTxt) bTxt.textContent = 'מדלג לפורום הבא…';
  toast('מדלג לפורום הבא ⏭️', 'info');
}

async function stopScrape() {
  await api('cancel_scrape');
  const bTxt = document.getElementById('scrape-banner-text');
  if (bTxt) bTxt.textContent = 'עוצר…';
  toast('הסריקה תיעצר…', 'info');
}

// (הוסר: "פותר התנגשויות גלובלי" — הסריקה עברה למנוע המקורות ואינה מייצרת
//  עוד רשומות nick_conflicts; התנגשויות legacy עדיין נצפות ונסגרות בדיאלוג הניק.)

async function openChazonishnik() {
  const forums = await api('get_scrapable_forums') || [];
  // Chazonishnik מסתמך על נתיבי הפוסטים של NodeBB בלבד
  const opts = forums.filter(f => (f.url || '').trim() && (f.platform || 'nodebb') === 'nodebb')
    .map(f => `<option value="${esc(f.url)}" ${/mitmachim/.test(f.url) ? 'selected' : ''}>${esc(f.name)}</option>`)
    .join('');
  openModal('📖 Chazonishnik — ניתוח פעילות משתמש', `
    <div style="font-size:13.5px;line-height:1.7">
      <div style="padding:12px 14px;background:var(--card2);border-radius:10px;margin-bottom:14px">
        <b>מה זה עושה?</b> Chazonishnik שולף את היסטוריית הפוסטים של משתמש בפורום ומייצר
        דוח אינטראקטיבי: כמות פוסטים, לייקים, מילים, שעות וימי פעילות, מעריצים מובילים,
        והפוסטים המוצלחים ביותר.
      </div>

      <div class="form-group" style="margin-bottom:14px">
        <label class="form-label">פורום</label>
        <select id="chz-forum" class="form-select" onchange="chzPrefillCookie()">${opts || '<option value="https://mitmachim.top">מתמחים טופ</option>'}</select>
      </div>

      <div style="margin-bottom:14px">
        <b>🍪 עוגיית התחברות (express.sid)</b>
        <div style="color:var(--subtext);font-size:12.5px;margin-top:4px">
          בפורומים שמסתירים היסטוריית פוסטים מאורחים (למשל מתמחים טופ) נדרשת "עוגיית"
          התחברות אישית שלך — מחרוזת ארוכה שמתחילה ב-<code>s%3A</code>. בפורום ציבורי
          אפשר להשאיר ריק. כך משיגים אותה:
        </div>
      </div>

      ${cookieHelpHtml()}

      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">שם משתמש לניתוח</label>
        <input id="chz-user" class="form-input" placeholder="שם המשתמש בפורום (למשל: בנימין)">
      </div>
      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">משתמש שני
          <span style="font-size:10px;opacity:.6">(אופציונלי — מילוי יפיק דוח השוואה)</span></label>
        <input id="chz-user2" class="form-input" placeholder="השאר ריק לניתוח של משתמש אחד">
        <div style="font-size:11px;color:var(--subtext);margin-top:4px">
          שתי הסריקות רצות בזו אחר זו ולא במקביל — כדי לא להכפיל את העומס על הפורום.
        </div>
      </div>
      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">עוגיית express.sid <span style="font-size:10px;opacity:.6">(אופציונלי בפורום ציבורי · נשמרת לפעם הבאה)</span></label>
        <input id="chz-cookie" class="form-input" dir="ltr" placeholder="s%3A...  (השאר ריק אם הפורום ציבורי)">
      </div>
      <div class="form-group" style="margin-bottom:6px">
        <label class="form-label">הגבל מספר פוסטים <span style="font-size:10px;opacity:.6">(אופציונלי — למשתמשים ותיקים הניתוח עלול להיות ארוך)</span></label>
        <input id="chz-maxposts" type="number" min="1" class="form-input" placeholder="הכל (ריק)">
      </div>
    </div>
  `, [
    { label: '📊 נתח פעילות', cls: 'btn-primary', action: runChazonishnik },
    ...(_lastReport.chz ? [{ label: '📄 הדוח האחרון', cls: 'btn-ghost',
        action: () => showChazonishnikReport(_lastReport.chz.html, _lastReport.chz.count) }] : []),
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
  chzPrefillCookie();
}

async function chzPrefillCookie() {
  const url = document.getElementById('chz-forum')?.value || '';
  const input = document.getElementById('chz-cookie');
  if (!input || !url) return;
  const saved = await api('get_saved_cookie', url);
  if (saved) input.value = saved;
}

function openExt(url) {
  api('open_url', url);
}

let _chzPoll = null;
// הדוח האחרון נשמר כדי שאפשר יהיה לפתוח אותו שוב בלי להריץ ניתוח מחדש
const _lastReport = { chz: null, stink: null };

async function runChazonishnik() {
  const username = document.getElementById('chz-user')?.value.trim();
  const second   = document.getElementById('chz-user2')?.value.trim() || '';
  const cookie   = document.getElementById('chz-cookie')?.value.trim() || '';
  const baseUrl  = document.getElementById('chz-forum')?.value || 'https://mitmachim.top';
  const maxPosts = parseInt(document.getElementById('chz-maxposts')?.value) || null;
  if (!username) { toast('הזן שם משתמש', 'error'); return; }
  // שם שני מלא = השוואה. אותו מצב רקע ואותו ביטול, כדי שהבאנר וההתקדמות
  // הקיימים ימשיכו לעבוד בלי שינוי.
  const start = second
    ? await api('run_chazonishnik_compare', username, second, cookie, baseUrl, maxPosts)
    : await api('run_chazonishnik', username, cookie, baseUrl, maxPosts);
  if (!start?.ok) { toast('שגיאה: ' + (start?.error || ''), 'error'); return; }
  showChazonishnikProgress(second ? `${username} מול ${second}` : username);
}

function showChazonishnikProgress(username) {
  openModal('📊 מנתח פעילות…', `
    <div style="text-align:center;padding:24px 16px">
      <div style="font-size:40px;margin-bottom:14px">⏳</div>
      <div id="chz-progress-text" style="font-size:14px;margin-bottom:8px">מתחיל…</div>
      <div style="font-size:12px;color:var(--subtext)">מנתח את הפעילות של ${esc(username)} — רץ ברקע, אפשר לצאת ולחזור</div>
      <div id="chz-which" style="font-size:11.5px;color:var(--subtext);margin-top:6px"></div>
      <div style="height:8px;background:var(--card2);border-radius:99px;overflow:hidden;margin-top:16px">
        <div id="chz-bar" style="height:100%;width:20%;background:linear-gradient(90deg,var(--accent),var(--accent-2));transition:width .4s"></div>
      </div>
    </div>
  `, [
    { label: '✕ בטל', cls: 'btn-danger', action: cancelChazonishnik },
    { label: '🏠 המשך ברקע', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm', { id: 'chz-progress' });
  startChazonishnikMonitor();
}

function startChazonishnikMonitor() {
  if (_chzPoll) clearInterval(_chzPoll);
  const banner = document.getElementById('chz-banner');
  if (banner) banner.style.display = '';

  let busy = false;
  _chzPoll = setInterval(async () => {
    if (busy) return;
    busy = true;
    try {
    const p = await api('get_chazonishnik_progress');
    if (!p) return;
    let label = 'מתחיל…';
    if (p.phase === 'scan') label = `סורק פוסטים… נמצאו ${p.count}`;
    else if (p.phase === 'analyze') label = `מנתח… ${p.count}/${p.total}`;

    const which = document.getElementById('chz-which');
    if (which) which.textContent =
      (p.compare && p.user) ? `משתמש ${p.which || 1} מתוך 2: ${p.user}` : '';
    const txt = document.getElementById('chz-progress-text');
    const bar = document.getElementById('chz-bar');
    if (txt) txt.textContent = label;
    if (bar && p.total) bar.style.width = Math.min(90, 20 + (p.count / p.total) * 70) + '%';
    const bTxt = document.getElementById('chz-banner-text');
    if (bTxt) bTxt.textContent = p.running ? label : 'מסיים…';

    if (p.done || !p.running) {
      clearInterval(_chzPoll); _chzPoll = null;
      if (banner) banner.style.display = 'none';
      // סוגרים רק את חלון ההתקדמות שלנו — לא חלון אחר שהמשתמש פתח בינתיים
      const mine = _currentModalId === 'chz-progress';
      if (p.cancelled) { toast('הניתוח בוטל', 'info'); if (mine) closeModal(); return; }
      if (p.error) { toast('שגיאה: ' + p.error, 'error'); if (mine) closeModal(); return; }
      if (p.html) {
        _lastReport.chz = { html: p.html, count: p.count };
        const msg = scanSummary('נותחו', p.count, p.postcount, p.partial, p.stopped_early, p.limited);
        if (mine || !isModalOpen()) {
          showChazonishnikReport(p.html, p.count);
          toast(msg, p.partial ? 'error' : 'success', { ms: p.partial ? 9000 : 4000 });
        } else {
          // אל תגנוב את המסך מעבודה פתוחה — הדוח נשמר וזמין לפתיחה
          toast('📊 הדוח מוכן — פתח דרך Chazonishnik · ' + msg, p.partial ? 'error' : 'success');
        }
      } else if (mine) closeModal();
    }
    } finally { busy = false; }
  }, 600);
}

// דיווח כן על היקף הסריקה: כמה נסרק מתוך כמה, ולמה חסר
function scanSummary(verb, done, postcount, partial, stoppedEarly, limited) {
  const d = (done || 0).toLocaleString();
  if (!postcount) return `${verb} ${d} פוסטים ✓`;
  const base = `${verb} ${d} מתוך ${postcount.toLocaleString()} פוסטים`;
  if (limited) return base + ' (לפי ההגבלה שהגדרת)';
  if (stoppedEarly) return base + ' — נעצר בגלל תקלת רשת, הדוח חלקי';
  if (partial) return base + ' — השאר בפורומים שדורשים התחברות (הוסף עוגייה)';
  return base + ' ✓';
}

function isModalOpen() {
  const m = document.getElementById('modal-overlay');
  return m && m.style.display !== 'none' && m.innerHTML.trim() !== '';
}

async function cancelChazonishnik() {
  await api('cancel_chazonishnik');
  if (_chzPoll) { clearInterval(_chzPoll); _chzPoll = null; }
  const banner = document.getElementById('chz-banner');
  if (banner) banner.style.display = 'none';
  toast('מבטל…', 'info');
  // סגור רק את חלון ההתקדמות שלנו — לא דיאלוג אחר שהמשתמש עובד בו
  if (_currentModalId === 'chz-progress') closeModal();
}

// גובה קבוע ב-vh בתוך חלון שגם הוא מוגבל ב-vh = שני גוללים. הפיכת גוף
// החלון לעמודת flex נותנת למסגרת בדיוק את מה שנשאר.
function fillModalBody(frameId) {
  const body = document.querySelector('#modal-overlay .modal-body');
  const fr = document.getElementById(frameId);
  if (!body || !fr) return;
  body.style.display = 'flex';
  body.style.flexDirection = 'column';
  fr.style.height = 'auto';
  fr.style.flex = '1';
  fr.style.minHeight = '240px';
}

function showChazonishnikReport(html, postCount) {
  // sandbox ללא allow-same-origin: לדוח יש origin נפרד, ולכן סקריפט בתוכו
  // (למשל מכותרת נושא עוינת) לא יכול להגיע ל-window.parent.pywebview.api.
  openModal(`📊 דוח פעילות${postCount ? ` · ${postCount} פוסטים` : ''}`, `
    <iframe id="chz-frame" sandbox="allow-scripts allow-popups"
            style="width:100%;height:68vh;border:none;border-radius:8px;background:#0f172a"></iframe>
  `, [
    { label: '💾 שמור כ-HTML', cls: 'btn-primary', action: () => saveChazonishnikReport(html) },
    { label: '🔄 ניתוח נוסף', cls: 'btn-ghost', action: openChazonishnik },
    { label: '🏠 תפריט ראשי', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
  fillModalBody('chz-frame');
  setTimeout(() => {
    const frame = document.getElementById('chz-frame');
    if (frame) frame.srcdoc = html;
  }, 100);
}

async function saveChazonishnikReport(html) {
  const r = await api('save_chazonishnik_report', html);
  if (r?.ok) toast('הדוח נשמר ✓', 'success');
  else if (r?.error !== 'בוטל') toast('שגיאה בשמירה: ' + (r?.error || ''), 'error');
}

async function openStinknik() {
  const forums = await api('get_scrapable_forums') || [];
  // Stinknik מסתמך על נתיבי הפוסטים של NodeBB בלבד
  const opts = forums.filter(f => (f.url||'').trim() && (f.platform || 'nodebb') === 'nodebb')
    .map(f => `<option value="${esc(f.url)}">${esc(f.name)}</option>`).join('');
  openModal('🦨 Stinknik — כל הדיסלייקים של ניק', `
    <div style="font-size:13.5px;line-height:1.7">
      <div style="padding:12px 14px;background:var(--card2);border-radius:10px;margin-bottom:14px">
        <b>מה זה עושה?</b> Stinknik סורק את כל הפוסטים של משתמש ומציג את <b>כל</b> הפוסטים
        שקיבלו דיסלייקים — כולל אלה שהפורום לא מציג (בפורום רואים רק "שנוי במחלוקת",
        כלומר רק פוסטים עם יותר דיסים מלייקים).
      </div>
      <div style="font-size:12px;color:var(--subtext);margin-bottom:14px">
        💡 עובד על כל פורום NodeBB. ברוב המקרים <b>לא נדרשת עוגייה</b> (המידע ציבורי). אם מתקבלת
        שגיאת הרשאה, אפשר להוסיף עוגייה — <b style="color:var(--accent-text);cursor:pointer;text-decoration:underline" onclick="toggleCookieHelp('stink-cookie-help')">ראה הדרכה</b>.
      </div>
      <div id="stink-cookie-help" style="display:none;margin-bottom:14px"></div>
      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">פורום</label>
        <select id="stink-forum" class="form-select" onchange="stinkPrefillCookie()">${opts}</select>
      </div>
      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">שם משתמש או קישור לפרופיל</label>
        <input id="stink-user" class="form-input" dir="auto" placeholder="בנימין  או  קישור מלא לפרופיל">
      </div>
      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label" style="font-size:11px;color:var(--subtext)">עוגייה (אופציונלי · נשמרת לפעם הבאה)</label>
        <input id="stink-cookie" class="form-input" dir="ltr" placeholder="השאר ריק ברוב המקרים">
      </div>
      <div class="form-group" style="margin-bottom:6px">
        <label class="form-label" style="font-size:11px;color:var(--subtext)">הגבל מספר פוסטים (אופציונלי — לניקים ותיקים הסריקה עלולה להיות ארוכה)</label>
        <input id="stink-maxposts" type="number" min="1" class="form-input" placeholder="הכל (ריק)">
      </div>
    </div>
  `, [
    { label: '🦨 מצא דיסלייקים', cls: 'btn-primary', action: runStinknik },
    ...(_lastReport.stink ? [{ label: '📄 הדוח האחרון', cls: 'btn-ghost',
        action: () => showStinknikReport(_lastReport.stink.html, _lastReport.stink.count) }] : []),
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
  stinkPrefillCookie();
}

let _stinkPoll = null;

async function stinkPrefillCookie() {
  const url = document.getElementById('stink-forum')?.value || '';
  const input = document.getElementById('stink-cookie');
  if (!input || !url) return;
  const saved = await api('get_saved_cookie', url);
  if (saved) input.value = saved;
}

async function runStinknik() {
  const user = document.getElementById('stink-user')?.value.trim();
  const cookie = document.getElementById('stink-cookie')?.value.trim() || '';
  const maxPosts = parseInt(document.getElementById('stink-maxposts')?.value) || null;
  let baseUrl = document.getElementById('stink-forum')?.value || 'https://mitmachim.top';
  // אם הודבק קישור מלא — נחלץ ממנו את הדומיין
  if (user && /^https?:\/\//i.test(user)) {
    try { const u = new URL(user); baseUrl = u.origin; } catch (e) {}
  }
  if (!user) { toast('הזן שם משתמש או קישור', 'error'); return; }
  const start = await api('run_stinknik', user, cookie, baseUrl, maxPosts);
  if (!start?.ok) { toast('שגיאה: ' + (start?.error || ''), 'error'); return; }
  showStinknikProgress(user);
}

function showStinknikProgress(user) {
  openModal('🦨 סורק דיסלייקים…', `
    <div style="text-align:center;padding:24px 16px">
      <div style="font-size:40px;margin-bottom:14px">🔍</div>
      <div id="stink-progress-text" style="font-size:14px;margin-bottom:8px">מתחיל…</div>
      <div style="font-size:12px;color:var(--subtext)">סורק את הפוסטים של ${esc(user)} — רץ ברקע, אפשר לצאת ולחזור</div>
    </div>
  `, [
    { label: '✕ בטל', cls: 'btn-danger', action: cancelStinknik },
    { label: '🏠 המשך ברקע', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm', { id: 'stink-progress' });
  startStinknikMonitor();
}

function startStinknikMonitor() {
  if (_stinkPoll) clearInterval(_stinkPoll);
  const banner = document.getElementById('stink-banner');
  if (banner) banner.style.display = '';
  let busy = false;
  _stinkPoll = setInterval(async () => {
    if (busy) return;
    busy = true;
    try {
    const p = await api('get_stinknik_progress');
    if (!p) return;
    const label = `נסרקו ${p.checked} פוסטים · ${p.disliked} עם דיסים`;
    const txt = document.getElementById('stink-progress-text');
    if (txt) txt.textContent = label;
    const bTxt = document.getElementById('stink-banner-text');
    if (bTxt) bTxt.textContent = p.running ? label : 'מסיים…';
    if (p.done || !p.running) {
      clearInterval(_stinkPoll); _stinkPoll = null;
      if (banner) banner.style.display = 'none';
      const mine = _currentModalId === 'stink-progress';
      if (p.cancelled) { toast('הסריקה בוטלה', 'info'); if (mine) closeModal(); return; }
      if (p.error) { toast('שגיאה: ' + p.error, 'error'); if (mine) closeModal(); return; }
      if (p.html) {
        _lastReport.stink = { html: p.html, count: p.disliked };
        const msg = scanSummary('נסרקו', p.checked, p.postcount, p.partial, p.stopped_early, p.limited);
        if (mine || !isModalOpen()) {
          showStinknikReport(p.html, p.disliked);
          toast(msg, p.partial ? 'error' : 'success', { ms: p.partial ? 9000 : 4000 });
        } else {
          toast('🦨 הדוח מוכן — פתח דרך Stinknik · ' + msg, p.partial ? 'error' : 'success');
        }
      } else if (mine) closeModal();
    }
    } finally { busy = false; }
  }, 600);
}

async function cancelStinknik() {
  await api('cancel_stinknik');
  if (_stinkPoll) { clearInterval(_stinkPoll); _stinkPoll = null; }
  const banner = document.getElementById('stink-banner');
  if (banner) banner.style.display = 'none';
  toast('מבטל…', 'info');
  if (_currentModalId === 'stink-progress') closeModal();
}

function showStinknikReport(html, disCount) {
  openModal(`🦨 דוח דיסלייקים${disCount != null ? ` · ${disCount} פוסטים` : ''}`, `
    <iframe id="stink-frame" sandbox="allow-scripts allow-popups"
            style="width:100%;height:68vh;border:none;border-radius:8px;background:#0f172a"></iframe>
  `, [
    { label: '💾 שמור כ-HTML', cls: 'btn-primary', action: () => saveStinknikReport(html) },
    { label: '🔄 ניתוח נוסף', cls: 'btn-ghost', action: openStinknik },
    { label: '🏠 תפריט ראשי', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
  fillModalBody('stink-frame');
  setTimeout(() => {
    const frame = document.getElementById('stink-frame');
    if (frame) frame.srcdoc = html;
  }, 100);
}

async function saveStinknikReport(html) {
  const r = await api('save_stinknik_report', html);
  if (r?.ok) toast('הדוח נשמר ✓', 'success');
  else if (r?.error !== 'בוטל') toast('שגיאה בשמירה: ' + (r?.error || ''), 'error');
}

// ══ CARD RENDERING ════════════════════════════════════════════════════
function renderCards() {
  const grid  = document.getElementById('cards-grid');
  const empty = document.getElementById('cards-empty');
  if (!grid) return;

  if (!S.nicks.length) {
    grid.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  // חלון וירטואלי לפי שורות-גריד: נבנים רק הכרטיסים שבתצוגה (+ מרווח ביטחון),
  // עם spacers למעלה ולמטה. בעבר הכרטיסים רק נוספו ומעולם לא הוסרו —
  // גלילה ארוכה במאגר גדול הגיעה למאות אלפי צמתי DOM.
  const wrap = document.getElementById('cards-wrap');
  const cols = S.cardsCols || 3, rowH = S.cardsRowH || 280;
  const total = S.nicks.length, totalRows = Math.ceil(total / cols);
  const scrollTop = wrap ? wrap.scrollTop : 0, viewH = wrap ? (wrap.clientHeight || 800) : 800;
  const buffer = 2;
  // clamp — אחרת אחרי חיפוש שמקטין את הרשימה בזמן שגלולים למטה, החלון יוצא מהטווח והגריד נשאר ריק
  const startRow = Math.min(Math.max(0, Math.floor(scrollTop / rowH) - buffer),
                            Math.max(0, totalRows - 1));
  const endRow = Math.min(totalRows, Math.ceil((scrollTop + viewH) / rowH) + buffer);
  const start = startRow * cols, end = Math.min(total, endRow * cols);

  grid.innerHTML = '';
  if (startRow > 0) grid.appendChild(cardsSpacer(startRow * rowH));
  for (let i = start; i < end; i++) grid.appendChild(buildCardElement(S.nicks[i]));
  if (endRow < totalRows) grid.appendChild(cardsSpacer((totalRows - endRow) * rowH));
  S.cardsRange = { start, end };

  // מדידה אמיתית (עמודות וגובה שורה) — ואם היא שונה מההנחה, בנייה חוזרת אחת
  const m = measureCardsLayout();
  if (m && !_cardsRerender &&
      (m.cols !== cols || Math.abs(m.rowH - rowH) > rowH * 0.05)) {
    S.cardsCols = m.cols; S.cardsRowH = m.rowH;
    _cardsRerender = true;
    try { renderCards(); } finally { _cardsRerender = false; }
    return;
  }
  hydrateAvatars();
}
let _cardsRerender = false;

function cardsSpacer(h) {
  const d = document.createElement('div');
  d.className = 'cards-spacer';
  d.style.cssText = `grid-column:1/-1;height:${Math.max(0, Math.round(h))}px;padding:0;margin:0`;
  return d;
}

// מספר העמודות = כמה כרטיסים חולקים את ה-offsetTop של הראשון; גובה שורה = מרחק לשורה הבאה
function measureCardsLayout() {
  const cards = document.querySelectorAll('#cards-grid .nick-card');
  if (!cards.length) return null;
  const top0 = cards[0].offsetTop;
  let cols = 0;
  for (const c of cards) { if (c.offsetTop === top0) cols++; else break; }
  cols = Math.max(1, cols);
  let rowH = cards[0].offsetHeight + 18;
  if (cards.length > cols) rowH = cards[cols].offsetTop - top0;
  if (!(rowH > 40)) rowH = cards[0].offsetHeight + 18;
  return { cols, rowH };
}

let _cardsScrollRaf = null;
function onCardsScroll() {
  if (_cardsScrollRaf) return;
  _cardsScrollRaf = requestAnimationFrame(() => {
    _cardsScrollRaf = null;
    if (DISPLAY.view !== 'cards' || !S.nicks.length) return;
    const wrap = document.getElementById('cards-wrap');
    if (!wrap) return;
    // בנה מחדש רק אם החלון הנדרש השתנה
    const cols = S.cardsCols || 3, rowH = S.cardsRowH || 280;
    const startRow = Math.max(0, Math.floor(wrap.scrollTop / rowH) - 2);
    const endRow = Math.min(Math.ceil(S.nicks.length / cols),
                            Math.ceil((wrap.scrollTop + wrap.clientHeight) / rowH) + 2);
    const start = startRow * cols, end = Math.min(S.nicks.length, endRow * cols);
    if (!S.cardsRange || S.cardsRange.start !== start || S.cardsRange.end !== end) renderCards();
  });
}

function buildCardElement(n) {
    const color = S.forumColors[n.forum] || '#6b7280';
    const card = document.createElement('div');
    card.className = 'nick-card' + (n.id === S.selectedId ? ' selected' : '');
    card.style.setProperty('--card-accent', color);
    card.dataset.id = n.id;

    const st = n.status || 'פעיל';
    const stCls = {'פעיל':'status-active','מורחק':'status-banned','מושעה':'status-suspended'}[st] || '';
    const initial = (n.username || '?').trim().charAt(0).toUpperCase();
    // safeColor ולא רק esc: esc משאיר ; : ( ) על כנם, כך שערך מהפורום כמו
    // 'red;background-image:url(https://forum/track.png)' נשאר תקף בתוך אותו
    // style והופך לבקשה חיצונית בכל ציור של הכרטיס.
    const nickCol = safeColor(n.nick_color, color);
    const avatarHtml = n.has_avatar
      ? `<div class="card-avatar" style="padding:0;overflow:hidden;background:${esc(nickCol)}">
           <img data-avatar-id="${n.id}" alt="" style="width:100%;height:100%;object-fit:cover"></div>`
      : `<div class="card-avatar" style="color:${fgOn(nickCol)};background:linear-gradient(135deg,${esc(nickCol)},${esc(shade(nickCol,-25))})">${esc(initial)}</div>`;

    // rows — only fields that exist
    const cf = n.conflict_fields ? String(n.conflict_fields).split(',') : [];
    const has = k => cf.includes(k);
    const rows = [];
    if (n.real_name)  rows.push(cardRow('👤', n.real_name, false, has('real_name'), 'real_name'));
    if (n.full_name)  rows.push(cardRow('📛', n.full_name, false, has('full_name'), 'full_name'));
    if (n.phone)      rows.push(cardRow('📞', n.phone + (n.extra_contacts ? ' ❕' : ''), false, has('phone'), 'phone'));
    if (n.email)      rows.push(cardRow('📧', n.email, false, has('email'), 'email'));
    if (n.address)    rows.push(cardRow('📍', n.address, false, has('address'), 'address'));
    if (n.groups)     rows.push(cardRow('🏷️', n.groups, false, has('groups'), 'groups'));
    if (n.reputation) rows.push(cardRow('⭐', String(n.reputation)));
    if (n.status)     rows.push(cardRow('🔵', n.status, false, has('status'), 'status'));
    if (n.join_date)  rows.push(cardRow('📅', n.join_date, false, has('join_date'), 'join_date'));
    if (n.post_count) rows.push(cardRow('✍️', String(n.post_count)));
    if (n.notes)      rows.push(cardRow('📝', n.notes, false, has('notes'), 'notes'));
    if (n.extra_info) rows.push(cardRow('ℹ️', n.extra_info, false, has('extra_info'), 'extra_info'));
    if (n.private_notes) rows.push(cardRow('🔒', n.private_notes, true, false, 'private_notes'));

    const bodyHtml = rows.length
      ? `<div class="card-body">${rows.join('')}</div>`
      : `<div class="card-body"><div class="card-empty-body">אין פרטים נוספים</div></div>`;

    card.innerHTML = `
      <div class="card-head">
        <input type="checkbox" class="card-select-cb" style="margin-left:4px"
               ${S.multiSelected.has(n.id) ? 'checked' : ''}>
        ${avatarHtml}
        <div class="card-titles">
          <div class="card-username">${esc(n.username)}${n.conflict_count ? ' ⚠️' : ''}</div>
          <span class="card-forum" style="background:${color}22;color:${color}">${esc(n.forum)}</span>
        </div>
      </div>
      ${bodyHtml}
      <div class="card-footer">
        <span class="card-badge ${stCls}">● ${esc(st)}</span>
        ${n.has_identity ? '<span class="card-badge card-identity-badge" style="background:var(--accent-soft);color:var(--accent-2);cursor:help">👤 זהות</span>' : ''}
        <span style="flex:1"></span>
        <button class="card-action-btn" title="פתח פרופיל בפורום"
                data-act="profile" data-id="${n.id}">🔗</button>
        <button class="card-action-btn" title="ערוך"
                data-act="edit" data-id="${n.id}">✏️</button>
      </div>`;

    // wire buttons
    card.querySelector('[data-act="profile"]').onclick = e => {
      e.stopPropagation(); openNickProfile(n);
    };
    card.querySelector('[data-act="edit"]').onclick = e => {
      e.stopPropagation(); openNickDialog(n.id);
    };
    card.querySelector('.card-select-cb').onclick = e => {
      e.stopPropagation();
      toggleRowSelected(n.id, e.target.checked);
    };
    // wire identity badge hover
    const idBadge = card.querySelector('.card-identity-badge');
    if (idBadge) {
      idBadge.onmouseenter = e => showIdentityTooltip(e, n.id);
      idBadge.onmouseleave = hideTooltip;
      idBadge.onclick = e => { e.stopPropagation(); openNickDialog(n.id); };
    }
    // wire conflict marks (per field)
    card.querySelectorAll('.card-conflict-mark').forEach(mk => {
      const fld = mk.dataset.field;
      mk.onmouseenter = e => showFieldSourcesTooltip(e, n.id, fld);
      mk.onmouseleave = hideTooltip;
    });
    card.onclick    = e => selectRow(n.id, e);
    card.ondblclick = () => openNickDialog(n.id);
    return card;
}

function cardRow(icon, val, isPrivate, conflictMark, fieldKey) {
  const valHtml = String(val).includes('@') ? renderTaggedText(val) : esc(val);
  const markHtml = conflictMark
    ? ` <span class="card-conflict-mark" data-field="${esc(fieldKey||'')}" style="cursor:help">❗</span>`
    : '';
  return `<div class="card-row${isPrivate ? ' private' : ''}">
    <span class="ci">${icon}</span>
    <span class="cv">${valHtml}${markHtml}</span>
  </div>`;
}

// darken/lighten a hex color
function shade(hex, pct) {
  const h = hex.replace('#','');
  if (h.length !== 6) return hex;
  const num = parseInt(h, 16);
  const amt = Math.round(2.55 * pct);
  const r = Math.min(255, Math.max(0, (num >> 16) + amt));
  const g = Math.min(255, Math.max(0, ((num >> 8) & 0xff) + amt));
  const b = Math.min(255, Math.max(0, (num & 0xff) + amt));
  return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

// ══ DISPLAY SETTINGS DIALOG ═══════════════════════════════════════════
async function openDisplaySettings() {
  const s = DISPLAY;
  const seg = (key, current, options) => `
    <div class="segmented">
      ${options.map(([val,lbl]) =>
        `<button class="${current===val?'active':''}"
                 onclick="changeDisplaySetting('${key}','${val}',this)">${lbl}</button>`
      ).join('')}
    </div>`;

  const colItems = orderedCols().filter(cc => cc.key !== '_open').map(cc => {
    const hidden = hiddenColsSet().has(cc.key);
    return `<div class="col-picker-item">
      <input type="checkbox" id="col-${cc.key}" ${hidden?'':'checked'}
             onchange="toggleColumn('${cc.key}',this.checked)">
      <label for="col-${cc.key}">${esc(cc.label)}</label>
    </div>`;
  }).join('');

  const html = `
    <div class="settings-section">
      <div class="settings-section-title">סגנון ערכת נושא</div>
      <div class="theme-cards">
        ${[['dark','כהה','tp-dark'],['light','בהיר','tp-light'],['system','מערכת','tp-system']]
          .map(([val,lbl,cls]) => `
          <div class="theme-card ${s.theme===val?'active':''}" data-theme="${val}"
               onclick="pickTheme('${val}',this)">
            <span class="tc-radio"></span>
            <div class="theme-preview ${cls}">
              <div class="tp-side"></div>
              <div class="tp-main"><div class="tp-bar"></div><div class="tp-bar2"></div></div>
            </div>
            <span class="theme-card-label">${lbl}</span>
          </div>`).join('')}
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">צבע מבטא</div>
      <div class="accent-swatches">
        ${ACCENTS.map(([key,hex,label]) => `
          <div class="swatch-wrap ${s.accent===key?'active':''}"
               style="color:${hex}" onclick="pickAccent('${key}',this)">
            <div class="swatch" style="background:${hex}"></div>
            <span class="swatch-label">${label}</span>
          </div>`).join('')}
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">📐 תצוגה</div>
      <div class="settings-row">
        <div><div class="settings-label">מצב תצוגה</div>
             <div class="settings-desc">טבלה או כרטיסים</div></div>
        ${seg('view', s.view, [['table','▤ טבלה'],['cards','▦ כרטיסים']])}
      </div>
      <div class="settings-row">
        <div><div class="settings-label">צפיפות ומצב קומפקטי</div>
             <div class="settings-desc">קומפקטי = שורות צפופות וטקסט קטן · מרווח = אוורירי</div></div>
        ${seg('density', s.density, [['compact','🔻 קומפקטי'],['normal','רגיל'],['cozy','מרווח']])}
      </div>
    </div>

    <div class="settings-section">
      <div class="settings-section-title">📊 עמודות בטבלה</div>
      <div class="col-picker">${colItems}</div>
      <div style="margin-top:10px">
        <button class="btn btn-ghost btn-sm" onclick="resetColLayout()">↺ אפס רוחב וסדר עמודות</button>
        <div style="font-size:11px;color:var(--subtext);margin-top:4px">
          מחזיר את העמודות לרוחב ולסדר המקוריים · לא נוגע בנתונים
        </div>
      </div>
      <div style="font-size:11px;color:var(--subtext);margin-top:8px;line-height:1.6">
        💡 גרירת שם עמודה בכותרת הטבלה משנה את הסדר; גרירת הקצה השמאלי משנה רוחב,
        ולחיצה כפולה עליו מתאימה את הרוחב לתוכן.
      </div>
    </div>`;

  openModal('🎨 הגדרות תצוגה', html, [
    { label: '↺ אפס את כל הגדרות התצוגה', cls: 'btn-ghost', action: resetDisplay },
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ]);
}

async function pickTheme(val, el) {
  DISPLAY.theme = val;
  applyTheme();
  updateThemeToggleIcon();
  el.parentElement.querySelectorAll('.theme-card').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  await api('set_display_setting', 'theme', val);
}

async function pickAccent(val, el) {
  DISPLAY.accent = val;
  applyTheme();
  el.parentElement.querySelectorAll('.swatch-wrap').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  await api('set_display_setting', 'accent', val);
}

async function changeDisplaySetting(key, val, btn) {
  DISPLAY[key] = val;
  // update active button in same group
  if (btn) {
    btn.parentElement.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  }
  if (key === 'theme')    applyTheme();
  if (key === 'view')     applyView();
  if (key === 'density') {
    document.body.dataset.density = val;
    S.rowHeight = 0;     // גובה השורה השתנה — הגלילה הווירטואלית תמדוד מחדש
    renderTable();
  }
  await api('set_display_setting', key, val);
}

async function toggleColumn(colKey, visible) {
  const hidden = hiddenColsSet();
  if (visible) hidden.delete(colKey);
  else hidden.add(colKey);
  DISPLAY.hidden_cols = [...hidden].join(',');
  await api('set_display_setting', 'hidden_cols', DISPLAY.hidden_cols);
  buildTableHeader();
  renderTable();
}

async function resetDisplay() {
  await api('reset_display_settings');
  Object.assign(DISPLAY, {theme:'dark',accent:'amber',view:'table',density:'normal',
                          hidden_cols:'', col_layout:''});
  loadColLayout('');
  await applyDisplaySettings();
  buildTableHeader();
  renderTable();
  closeModal();
  toast('הגדרות התצוגה אופסו', 'info');
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                         .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
                         .replace(/'/g,'&#39;');
}

// צבע בטוח לתוך style=. esc() מונע בריחה מהמאפיין, אבל ערך כמו
// 'red;background-image:url(https://forum/track.png)' נשאר תקף בתוך אותו
// מאפיין והופך לבקשה חיצונית מה-WebView בכל צפייה בפרופיל — כלומר הפורום
// לומד שאתה מסתכל על המשתמש הזה. nick_color מגיע מהפורום, ולכן: רשימה לבנה.
// לבן על רקע בהיר נעלם. בוחרים שחור/לבן לפי בהירות הרקע בפועל.
function fgOn(bg) {
  const m = String(bg || '').trim().match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
  if (!m) return '#fff';
  let h = m[1];
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  const lin = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const L = 0.2126 * lin(parseInt(h.slice(0, 2), 16))
          + 0.7152 * lin(parseInt(h.slice(2, 4), 16))
          + 0.0722 * lin(parseInt(h.slice(4, 6), 16));
  return L > 0.42 ? '#1a1a1a' : '#fff';
}

function safeColor(v, fallback = 'var(--accent)') {
  const t = String(v ?? '').trim();
  return /^#[0-9a-fA-F]{3,8}$/.test(t) || /^[a-zA-Z]{3,20}$/.test(t) ? t : fallback;
}

// כתובת בטוחה ל-href/src: רק http(s) או data:image. אחרת — לא נפתח כלום.
// (avatar_url מגיע מהפורום; ערך כמו javascript:... אסור להגיע ל-DOM)
function safeUrl(u) {
  const s = String(u ?? '').trim();
  return /^(https?:\/\/|data:image\/)/i.test(s) ? s : '';
}
