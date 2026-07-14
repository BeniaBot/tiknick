/* Tik-Nick v0.1 — app.js */
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
  { key: 'updated_at',    label: 'עודכן',           width: 130, render: renderUpdated },
  { key: 'extra_info',    label: 'פרטים נוספים',    width: 170 },
  { key: 'notes',         label: 'הערות',           width: 180 },
  { key: 'private_notes', label: 'הערות אישיות',    width: 175, render: renderPrivate },
  { key: 'identity',      label: 'זהות כפולה',      width: 90,  render: renderIdentity },
];

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
  await applyDisplaySettings();
  buildTableHeader();
  await loadForums();
  await loadNicks();
  const tableWrap = document.getElementById('table-wrap');
  if (tableWrap) tableWrap.addEventListener('scroll', onTableScroll);
  const cardsWrap = document.getElementById('cards-wrap');
  if (cardsWrap) cardsWrap.addEventListener('scroll', onCardsScroll);
  setInterval(() => {
    const el = document.getElementById('status-time');
    if (el) el.textContent = new Date().toLocaleTimeString('he-IL');
  }, 1000);
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
      { label: 'סגור', cls: 'btn-primary', action: closeModal },
    ], 'modal-sm');
    return;
  }

  const notesHtml = res.notes
    ? `<div style="margin-top:14px;padding:12px 14px;background:var(--card2);
             border-radius:8px;font-size:12.5px;color:var(--text-dim);
             max-height:180px;overflow-y:auto;white-space:pre-wrap;line-height:1.6">${esc(res.notes)}</div>`
    : '';

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
    <p style="font-size:12px;color:var(--subtext);margin-top:14px;text-align:center">
      ההורדה תיפתח בדפדפן. לאחר ההורדה, החלף את קובץ ה-EXE הישן בחדש.<br>
      הנתונים שלך נשמרים בנפרד ולא יושפעו.
    </p>`, [
    res.download_url
      ? { label: '⬇️ הורד עכשיו', cls: 'btn-primary', action: () => { api('open_url', res.download_url); closeModal(); } }
      : { label: '🌐 פתח דף ההורדה', cls: 'btn-primary', action: () => { api('open_url', res.release_url); closeModal(); } },
    { label: 'אחר כך', cls: 'btn-ghost', action: closeModal },
  ]);
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
        <p class="about-text">
          תודה לכל מי שסייע, בדק, והציע רעיונות לאורך הפיתוח. 🙏
        </p>
        <p class="about-text" style="color:var(--subtext);font-size:12.5px">
          (מקום להוספת קרדיטים מפורטים בהמשך)
        </p>
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
      <a onclick="${res.download_url
        ? `api('open_url','${esc(res.download_url)}')`
        : `api('open_url','${esc(res.release_url)}')`}" class="au-action">הורד</a>`;
  } else {
    box.className = 'about-update ok';
    inner.innerHTML = `
      <span class="au-check">✓</span>
      <span>האפליקציה מעודכנת לגרסה האחרונה</span>
      <a onclick="refreshAboutUpdate()" class="au-action">בדוק שוב</a>`;
  }
}

// ══ FORUMS ════════════════════════════════════════════════════════════
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

  const hidden = hiddenColsSet();
  COLS.forEach(col => {
    if (hidden.has(col.key)) return;
    const th = document.createElement('th');
    th.style.minWidth = col.width + 'px';
    th.innerHTML = `${col.label} <span class="sort-icon">↕</span>`;
    th.onclick = () => sortBy(col.key);
    th.dataset.col = col.key;
    tr.appendChild(th);
  });
}

async function loadNicks(search = '') {
  // טוקן ייחודי לבקשה הזו — אם עד שהיא חוזרת כבר יצאה בקשה חדשה יותר
  // (חיפוש נוסף, מחיקה, וכו'), מתעלמים מהתוצאה המיושנת. זה מונע מצב
  // שבו ניק שכבר נמחק "קופץ בחזרה" רגע לפני שנעלם, בעיקר בתצוגת כרטיסים.
  const myToken = ++S.loadToken;
  S.currentSearch = search;
  S.multiSelected.clear();

  const res = await api('get_nicks', search);

  if (myToken !== S.loadToken) return; // תשובה מיושנת — מתעלמים

  const rows  = res && Array.isArray(res.rows) ? res.rows : (Array.isArray(res) ? res : []);
  const total = res && typeof res.total === 'number' ? res.total : rows.length;

  S.nicks = rows;
  S.total = total;
  S.cardsRendered = Math.min(S.cardsChunk, S.nicks.length);

  sortNicks();
  renderTable();
  updateBulkBar();
}

function sortBy(col) {
  if (S.sortCol === col) S.sortDir *= -1;
  else { S.sortCol = col; S.sortDir = 1; }
  sortNicks();
  // גלילה חזרה למעלה — אחרת החלון הווירטואלי מציג את השורות של מיקום הגלילה הישן
  const tw = document.getElementById('table-wrap');
  if (tw) tw.scrollTop = 0;
  const cw = document.getElementById('cards-wrap');
  if (cw) cw.scrollTop = 0;
  S.cardsRendered = Math.min(S.cardsChunk, S.nicks.length);
  renderTable();
  // update header icons
  document.querySelectorAll('thead th').forEach(th => {
    th.classList.toggle('sorted', th.dataset.col === col);
    const icon = th.querySelector('.sort-icon');
    if (icon) icon.textContent = th.dataset.col === col ? (S.sortDir === 1 ? '↑' : '↓') : '↕';
  });
}

function sortNicks() {
  S.nicks.sort((a, b) => {
    // has_info always first
    if (a.has_info !== b.has_info) return b.has_info - a.has_info;
    const va = a[S.sortCol] ?? '';
    const vb = b[S.sortCol] ?? '';
    const n = typeof va === 'number';
    return n ? (va - vb) * S.sortDir
             : String(va).localeCompare(String(vb), 'he') * S.sortDir;
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

  const hiddenCols = hiddenColsSet();
  COLS.forEach(col => {
    if (hiddenCols.has(col.key)) return;
    const td = document.createElement('td');
    td.title = String(n[col.key] ?? '');
    if (col.render) {
      col.render(td, n);
    } else {
      const val = n[col.key] ?? '';
      td.textContent = String(val).slice(0, 80);
    }
    tr.appendChild(td);
  });

  tr.onclick    = e => selectRow(n.id, e);
  tr.ondblclick = () => openNickDialog(n.id);
  return tr;
}

function visibleColCount() {
  const hidden = hiddenColsSet();
  return 1 + COLS.filter(c => !hidden.has(c.key)).length; // +1 = checkbox column
}

function renderTable() {
  const empty = document.getElementById('empty-state');

  if (!S.nicks.length) {
    document.getElementById('tbody').innerHTML = '';
    empty.style.display = '';
    updateStats();
    renderCards();
    return;
  }
  empty.style.display = 'none';

  renderTableWindow();  // בונה רק את השורות שבתצוגה (virtual scrolling)

  updateStats();
  setStatus(`עודכן ${new Date().toLocaleTimeString('he-IL')}`);
  renderCards();  // תמיד מרנדר גם כרטיסים (מוסתר אם במצב טבלה)
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
    if (h && Math.abs(h - S.rowHeight) > 1) S.rowHeight = h;
  }
}

let _tableScrollRaf = null;
function onTableScroll() {
  if (_tableScrollRaf) return;
  _tableScrollRaf = requestAnimationFrame(() => {
    _tableScrollRaf = null;
    renderTableWindow();
  });
}

// ── cell renderers ──────────────────────────────────────────────────
function renderForum(td, n) {
  const color = S.forumColors[n.forum] || '#8b90a0';
  const span  = document.createElement('span');
  span.className = 'cell-forum';
  span.style.background = color + '22';
  span.style.color       = color;
  span.textContent = n.forum || '';
  td.appendChild(span);
}

function renderUsername(td, n) {
  // מיני אווטאר/נקודת צבע לפני השם
  if (n.avatar_image || n.nick_color) {
    const dot = document.createElement('span');
    dot.className = 'uname-dot';
    if (n.avatar_image) {
      dot.style.cssText = 'background-image:url('+n.avatar_image+')';
      dot.classList.add('has-img');
    } else {
      dot.style.background = n.nick_color;
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

function renderRep(td, n) {
  if (!n.reputation) return;
  td.textContent = Number(n.reputation).toLocaleString();
  td.style.color = n.reputation > 100 ? '#3fb950' : 'inherit';
}

function renderPhone(td, n) {
  td.textContent = n.phone || '';
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
  if (n.email) {
    td.textContent = n.email;
  }
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

function renderPrivate(td, n) {
  if (n.private_notes) {
    td.className = 'cell-private';
    td.textContent = n.private_notes.slice(0, 60);
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
  if (diff < 60)     return 'עכשיו';
  if (diff < 3600)   return `לפני ${Math.floor(diff/60)} דק'`;
  if (diff < 86400)  return `לפני ${Math.floor(diff/3600)} שע'`;
  if (diff < 604800) return `לפני ${Math.floor(diff/86400)} ימים`;
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

function buildProfileUrl(baseUrl, username) {
  // הסר / מסופי כתובת הבסיס
  let base = baseUrl.replace(/\/+$/, '');
  // המר רווחים למקפים (מבנה NodeBB: /user/שם-משתמש)
  const slug = username.trim().replace(/\s+/g, '-');
  return `${base}/user/${encodeURIComponent(slug)}`;
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
  const profileUrl = buildProfileUrl(forum.url, n.username);
  api('open_url', profileUrl);
}

// ══ SELECT ════════════════════════════════════════════════════════════
function selectRow(id, e) {
  S.selectedId = id;
  document.querySelectorAll('tbody tr').forEach(tr => {
    tr.classList.toggle('selected', parseInt(tr.dataset.id) === id);
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
  if (!confirm(`למחוק את "${nick.username}"?`)) return;
  await api('delete_nick', S.selectedId);
  S.selectedId = null;
  document.getElementById('btn-edit').disabled   = true;
  document.getElementById('btn-delete').disabled = true;
  if(document.getElementById('stat-sel'))document.getElementById('stat-sel').textContent='0';
  await loadNicks(document.getElementById('search-input').value);
  toast('ניק נמחק', 'success');
}

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
  const bar = document.getElementById('bulk-actions-bar');
  const cnt = document.getElementById('bulk-count');
  if (!bar) return;
  const n = S.multiSelected.size;
  bar.style.display = n > 0 ? '' : 'none';
  if (cnt) cnt.textContent = n;
  const selAllCb = document.getElementById('select-all-cb');
  if (selAllCb) selAllCb.checked = S.nicks.length > 0 && S.nicks.every(n2 => S.multiSelected.has(n2.id));
}

async function deleteBulkSelected() {
  const ids = [...S.multiSelected];
  if (!ids.length) return;
  if (!confirm(`למחוק ${ids.length} ניקים שנבחרו? פעולה בלתי הפיכה!`)) return;
  const res = await api('delete_nicks', ids);
  S.multiSelected.clear();
  S.selectedId = null;
  await loadNicks(document.getElementById('search-input').value);
  toast(`${res?.count ?? ids.length} ניקים נמחקו`, 'success');
}

// ══ SEARCH ════════════════════════════════════════════════════════════
function onSearch(val) {
  clearTimeout(S.searchTimer);
  S.searchTimer = setTimeout(() => loadNicks(val), 200);
}

// ══ STATS ═════════════════════════════════════════════════════════════
function updateStats() {
  document.getElementById('stat-total').textContent = S.total || S.nicks.length;
  document.getElementById('stat-info').textContent  =
    S.nicks.filter(n => n.has_info).length;
}

// ══ NICK DIALOG ═══════════════════════════════════════════════════════
async function openNickDialog(nickId = null) {
  let nick = null;
  if (nickId) nick = await api('get_nick', nickId);
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
  const shelvedHtml = nick?.shelved?.length ? renderShelvedSection(nick.shelved) : '';

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
        <input class="form-input" id="f-email" value="${esc(nick?.email||'')}">
      </div>
      <div class="form-group full">
        <label class="form-label">כתובת</label>
        <input class="form-input" id="f-address" value="${esc(nick?.address||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">קבוצות</label>
        <input class="form-input" id="f-groups" value="${esc(nick?.groups||'')}">
      </div>
      <div class="form-group">
        <label class="form-label">מוניטין</label>
        <input class="form-input" id="f-reputation" type="number" min="0"
               value="${nick?.reputation||0}">
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
          <input class="form-input" id="f-avatar_url" placeholder="https://..."
                 value="${esc(nick?.avatar_url||'')}" style="flex:1">
          <a id="profile-link-btn"
             href="${nick?.avatar_url||'#'}" target="_blank"
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
            ? `<img src="${nick.avatar_image}" alt="">`
            : `<span class="avatar-initial" style="background:${nick?.nick_color||'var(--accent)'}">${esc((nick?.username||'?').charAt(0).toUpperCase())}</span>`}
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
      <label class="form-label accent">פרטים נוספים</label>
      <textarea class="form-textarea" id="f-extra_info">${esc(nick?.extra_info||'')}</textarea>
    </div>
    <div class="form-group" style="margin-bottom:12px">
      <label class="form-label">הערות (מסונכרנות)</label>
      <textarea class="form-textarea" id="f-notes">${esc(nick?.notes||'')}</textarea>
    </div>
    <div class="form-group" style="margin-bottom:12px">
      <label class="form-label warn">🔒 הערות אישיות (לא מיוצאות בברירת מחדל)</label>
      <textarea class="form-textarea private" id="f-private_notes">${esc(nick?.private_notes||'')}</textarea>
    </div>

    ${conflictsHtml}
    ${shelvedHtml}
  `;

  openModal(title, html, [
    { label: '💾 שמור', cls: 'btn-primary', action: () => saveNick(nickId) },
    { label: 'ביטול',   cls: 'btn-ghost',   action: closeModal },
  ], 'modal-lg');

  // wire up contacts
  if (nick) wireContactsSection(nick);
  if (nick) wireIdentitiesSection(nick);
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
      <span class="ct-val">${esc(ct.value)}</span>
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

async function searchForIdentity(q, nickId) {
  const box = document.getElementById('id-results');
  if (!q.trim()) { box.style.display = 'none'; return; }
  const nicks = await api('get_nicks', q);
  const nick  = await api('get_nick', nickId);
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

function renderShelvedSection(shelved) {
  const fieldLabel = k => (COLS.find(c => c.key===k)?.label) || k;
  return `
    <div class="section-hdr" style="color:var(--subtext)">⚠️ מידע סותר מייבוא אחר (נשמר בצד)</div>
    <p style="font-size:11.5px;color:var(--subtext);margin-bottom:8px">
      ערכים אלו הוכרעו לרעתם לפי דירוג אמינות, אך נשמרו. אפשר לקדם ערך שמור לערך הפעיל.
    </p>
    ${shelved.map(s => `
      <div class="conflict-item" style="display:flex;gap:8px;align-items:center;justify-content:space-between">
        <div>
          <div><span class="conflict-field">${esc(fieldLabel(s.field_name))}: </span>
               <span class="conflict-val">${esc(s.value)}</span>
               <span title="ממקור: ${esc(s.source_name)} (אמינות ${s.source_trust}/10)" style="cursor:help">⚠️</span>
          </div>
          <div class="conflict-src">מקור: ${esc(s.source_name)} · אמינות ${s.source_trust}/10</div>
        </div>
        <button class="btn btn-sm btn-ghost" onclick="promoteShelved(${s.id})">↑ קדם לפעיל</button>
      </div>`).join('')}`;
}

async function promoteShelved(shelvedId) {
  await api('promote_shelved', shelvedId);
  const nickId = S.selectedId;
  closeModal();
  await loadNicks(document.getElementById('search-input').value);
  if (nickId) openNickDialog(nickId);
  toast('הערך קודם לפעיל ✓', 'success');
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
    await api('update_nick', nickId, data);
    toast('ניק עודכן ✓', 'success');
  } else {
    const res = await api('create_nick', data);
    if (res?.ok) toast('ניק נוסף ✓', 'success');
  }
  closeModal();
  await loadNicks(document.getElementById('search-input').value);
}

// ══ IDENTITY DIALOG ═══════════════════════════════════════════════════
function openIdentityDialog(nickId) {
  openNickDialog(nickId); // opens full dialog, identity section is there
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
        <span class="forum-dot" style="background:${f.color}"></span>
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
          <span class="forum-dot" style="background:${f.color}"></span>
          <span class="forum-name" style="font-size:13px">${esc(f.name)}</span>
          ${f.url ? `<a href="${esc(f.url)}" target="_blank"
             style="color:var(--subtext);font-size:11px;margin-right:auto;text-decoration:none;
                    flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px">
            ${esc(f.url.replace(/https?:\/\//,'').slice(0,30))}
          </a>` : '<span style="flex:1"></span>'}
          ${isActive
            ? `<span style="font-size:11px;color:var(--success);padding:3px 8px;
                            background:rgba(63,185,80,.12);border-radius:10px">✓ קיים</span>`
            : `<button class="btn btn-sm btn-primary btn-icon"
                       onclick="fmAddKnown('${esc(f.name)}','${f.color}','${esc(f.url||'')}')">➕</button>`
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
      <input class="form-input" id="rename-url" placeholder="קישור (URL)" style="flex:1">
      <button class="btn btn-ghost btn-sm" onclick="fmRename()">✏️ שמור</button>
    </div>

    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:14px">
      <div style="font-size:12px;font-weight:700;color:var(--subtext);margin-bottom:8px">
        ➕ הוסף פורום חדש
      </div>
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
        <input class="form-input" id="new-forum-name" placeholder="שם"
               style="flex:1" oninput="fmAutoFill(this.value)">
        <input class="form-input" id="new-forum-url" placeholder="קישור (אופציונלי)" style="flex:1">
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
    await loadNicks(document.getElementById('search-input').value);
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
async function openSyncMgr() {
  const fields   = await api('get_all_nick_fields');
  const sync     = await api('get_sync_settings');
  const forumIo  = await api('get_forum_io_flags') || {};
  const policy   = await api('get_conflict_policy') || 'ask';
  const myTrust  = await api('get_my_trust') ?? 10;
  const impLog   = await api('get_import_sources') || [];

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
    </div>`;

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

  // ── סעיף 3: מדיניות התנגשות בסנכרון מהאינטרנט ──
  const opt = (val, label, desc) => `
    <label class="policy-opt" style="display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid var(--border-soft);border-radius:10px;margin-bottom:10px;cursor:pointer">
      <input type="radio" name="cpolicy" value="${val}" ${policy===val?'checked':''} style="margin-top:3px">
      <div>
        <div style="font-weight:700;font-size:13.5px">${label}</div>
        <div style="font-size:12px;color:var(--subtext);margin-top:2px">${desc}</div>
      </div>
    </label>`;
  const sec3 = `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:14px">
      כשסריקה מהאינטרנט מוצאת ערך שונה בשדה שכבר קיים, מה לעשות?
    </p>
    ${opt('ask', '🙋 לשאול אותי', 'ייפתח חלון פתרון התנגשויות בסיום הסריקה (ברירת מחדל)')}
    ${opt('existing', '🛡️ תמיד לשמור את הקיים', 'המידע הקיים לא ישתנה; הערך הסרוק יידחה אוטומטית')}
    ${opt('new', '🔄 תמיד להעדיף את החדש', 'הערך שנסרק מהפורום ידרוס את הקיים אוטומטית')}`;

  // ── סעיף 4: אמינות ולוג ייבואים ──
  const logRows = impLog.length ? impLog.map(s => `
    <tr>
      <td style="padding:6px 8px">${esc(s.name)}</td>
      <td style="padding:6px 8px;text-align:center">${s.trust}/10</td>
      <td style="padding:6px 8px;text-align:center">${s.nick_count}</td>
      <td style="padding:6px 8px;text-align:center">${s.conflict_count}</td>
      <td style="padding:6px 8px;font-size:11px;color:var(--subtext)">${esc((s.created_at||'').slice(0,16))}</td>
    </tr>${s.notes ? `<tr><td colspan="5" style="padding:2px 8px 8px;font-size:11px;color:var(--subtext)">📝 ${esc(s.notes)}</td></tr>`:''}`).join('')
    : `<tr><td colspan="5" style="padding:14px;text-align:center;color:var(--subtext)">עדיין לא בוצעו ייבואים</td></tr>`;
  const sec4 = `
    <div class="section-hdr">דרגת האמינות שלי</div>
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:10px">
      האמינות של המידע שאתה מזין ידנית ושנסרק על ידך. בהתנגשות בייבוא — מקור עם אמינות
      גבוהה יותר משלך ידרוס; אחרת שלך נשמר.
    </p>
    <label class="form-label">האמינות שלי: <b id="mytrust-val">${myTrust}</b> / 10</label>
    <input type="range" min="1" max="10" value="${myTrust}" id="mytrust" style="width:100%"
           oninput="document.getElementById('mytrust-val').textContent=this.value">

    <div class="section-hdr" style="margin-top:22px">לוג ייבואים</div>
    <div style="max-height:240px;overflow-y:auto;border:1px solid var(--border-soft);border-radius:8px">
      <table style="width:100%;border-collapse:collapse;font-size:12.5px">
        <thead><tr style="background:var(--card2)">
          <th style="padding:7px 8px;text-align:right">מקור</th>
          <th style="padding:7px 8px">אמינות</th>
          <th style="padding:7px 8px">ניקים</th>
          <th style="padding:7px 8px">התנגשויות</th>
          <th style="padding:7px 8px;text-align:right">תאריך</th>
        </tr></thead>
        <tbody>${logRows}</tbody>
      </table>
    </div>`;

  const html = `
    <div class="tab-bar" style="display:flex;gap:6px;margin-bottom:16px;border-bottom:1px solid var(--border-soft);flex-wrap:wrap">
      <button class="tab-btn active" data-tab="s1" onclick="switchSyncTab('s1')">📄 עמודות בקובץ</button>
      <button class="tab-btn" data-tab="s2" onclick="switchSyncTab('s2')">🏛️ פורומים</button>
      <button class="tab-btn" data-tab="s3" onclick="switchSyncTab('s3')">⚠️ התנגשויות אינטרנט</button>
      <button class="tab-btn" data-tab="s4" onclick="switchSyncTab('s4')">🎖️ אמינות ולוג</button>
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
      // סעיף 1
      for (const f of fields) {
        const el = document.getElementById(`st-${f.key}`);
        if (el) await api('set_sync_setting', f.key, el.checked);
      }
      // סעיף 2
      for (let i = 0; i < forumNames.length; i++) {
        const el = document.getElementById(`fio-${i}`);
        if (el) await api('set_forum_io_flag', el.dataset.forum, el.checked);
      }
      // סעיף 3
      const chosen = document.querySelector('input[name="cpolicy"]:checked');
      if (chosen) await api('set_conflict_policy', chosen.value);
      // סעיף 4
      const mt = document.getElementById('mytrust');
      if (mt) await api('set_my_trust', parseInt(mt.value) || 10);
      toast('הגדרות סנכרון נשמרו ✓', 'success');
      closeModal();
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
}

// ══ EXPORT / IMPORT ════════════════════════════════════════════════════
async function exportData() {
  const res = await api('export_data');
  if (res?.ok) toast(`יוצאו ${res.count} ניקים ✓`, 'success');
  else if (res?.error !== 'בוטל') toast('שגיאה בייצוא', 'error');
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
  // שלב 1.5: פרטי הייבוא (שם, הערות, דרגת אמינות)
  showImportDetailsDialog(res);
}

async function showImportDetailsDialog(res) {
  const myTrust = await api('get_my_trust') ?? 10;
  openModal('📥 פרטי הייבוא', `
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
      _pendingImportMeta = {
        name: document.getElementById('imp-name').value.trim() || 'ייבוא',
        notes: document.getElementById('imp-notes').value.trim(),
        trust: parseInt(document.getElementById('imp-trust').value) || 7,
      };
      closeModal();
      proceedImport(res);
    }},
    { label: 'ביטול', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
}

async function proceedImport(res) {
  const unknown = res.unknown_forums || [];
  if (unknown.length === 0) {
    const r2 = await api('confirm_import', {}, _pendingImportMeta.name,
                         _pendingImportMeta.notes, _pendingImportMeta.trust);
    if (r2?.ok) {
      await loadNicks(document.getElementById('search-input').value);
      toast(`יובאו ${r2.imported} ניקים, ${r2.conflicts} התנגשויות ✓`, 'success');
    } else {
      toast('שגיאה בייבוא: ' + (r2?.error||''), 'error');
    }
    return;
  }
  showForumMappingDialog(unknown, res.nick_count);
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
        <select class="form-select fmap-select" data-fname="${esc(fname)}" style="flex:1"
                onchange="fmapOnChange(this,'${esc(fname)}')">
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
    { label: '📥 ייבא', cls: 'btn-primary', action: async () => {
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
      const r2 = await api('confirm_import', mapping, _pendingImportMeta.name,
                           _pendingImportMeta.notes, _pendingImportMeta.trust);
      if (r2?.ok) {
        await loadForums();
        await loadNicks(document.getElementById('search-input').value);
        toast(`יובאו ${r2.imported} ניקים, ${r2.conflicts} התנגשויות ✓`, 'success');
      } else {
        toast('שגיאה בייבוא: ' + (r2?.error||''), 'error');
      }
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
  const nick = await api('get_nick', nickId);
  const cts  = nick?.contacts || [];
  if (!cts.length) return;
  const html = cts.map(ct =>
    `<div>${ct.type==='phone'?'📞':'📧'} ${esc(ct.value)}${ct.label?' ['+esc(ct.label)+']':''}</div>`
  ).join('');
  showTooltip(e, `<b>פרטי קשר נוספים:</b><br>${html}`);
}

async function showIdentityTooltip(e, nickId) {
  const ids = S.nicks.find(n => n.id === nickId);
  if (!ids) return;
  const nick = await api('get_nick', nickId);
  const list = nick?.identities || [];
  if (!list.length) return;
  const html = list.map(i =>
    `<div><span style="color:${S.forumColors[i.forum]||'#8b90a0'}">[${esc(i.forum)}]</span>
    <b style="margin-right:6px">${esc(i.username)}</b></div>`
  ).join('');
  showTooltip(e, `<b>זהויות נוספות:</b><br>${html}<br><small>לחץ לניהול</small>`);
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
  document.getElementById('tooltip').style.display = 'none';
}

// ══ MODAL ═════════════════════════════════════════════════════════════
function openModal(title, bodyHtml, buttons = [], extraClass = '') {
  closeModal();
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'modal-overlay';
  overlay.onclick = e => { if (e.target === overlay) closeModal(); };

  const btnsHtml = buttons.map(b =>
    `<button class="btn ${b.cls}" id="mb-${b.label}">${b.label}</button>`
  ).join('');

  overlay.innerHTML = `
    <div class="modal ${extraClass}">
      <div class="modal-header">
        <div class="modal-title">${title}</div>
        <button class="modal-close" onclick="closeModal()">✕</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      <div class="modal-footer">${btnsHtml}</div>
    </div>`;

  document.body.appendChild(overlay);

  buttons.forEach(b => {
    const el = overlay.querySelector(`#mb-${CSS.escape(b.label)}`);
    if (el) el.onclick = b.action;
  });
}

function closeModal() {
  document.getElementById('modal-overlay')?.remove();
}

// ══ TOAST ═════════════════════════════════════════════════════════════
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 3500);
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
  density: 'normal', hidden_cols: '',
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
  prev.innerHTML = `<span class="avatar-initial" style="background:${color}">${esc(uname.charAt(0).toUpperCase())}</span>`;
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

async function openInternetSync() {
  const forums = await api('get_scrapable_forums') || [];
  const opts = forums.map(f =>
    `<option value="${esc(f.name)}" data-url="${esc(f.url || '')}">${esc(f.name)}</option>`
  ).join('');

  openModal('🌐 סנכרון לאינטרנט', `
    <p style="color:var(--subtext);font-size:13px;line-height:1.6;margin-bottom:16px">
      סורק את רשימת המשתמשים של פורום NodeBB דרך ה-API הרשמי, ומוסיף/מעדכן ניקים
      אוטומטית. שדות ריקים מתמלאים בשקט; ערך שונה בשדה קיים נרשם כהתנגשות לפתרון.
    </p>

    <div class="section-hdr">בחירת פורום</div>
    <label style="display:block;font-size:12px;margin-bottom:6px;color:var(--subtext)">פורום לסריקה</label>
    <select id="sync-forum" class="form-select" style="width:100%;margin-bottom:12px">${opts}</select>

    <label style="display:block;font-size:12px;margin-bottom:6px;color:var(--subtext)">
      עוגיית התחברות (express.sid) — רק אם הפורום דורש התחברות לצפייה במשתמשים (לא חובה)
    </label>
    <input id="sync-cookie" class="form-input" style="width:100%;margin-bottom:12px" dir="ltr"
           placeholder="express.sid=s%3A...  (השאר ריק אם הפורום ציבורי)">

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
    { label: 'סגור',        cls: 'btn-ghost',   action: closeSyncModal },
  ], 'modal-lg');
}

function closeSyncModal() {
  if (_scrapePoll) { clearInterval(_scrapePoll); _scrapePoll = null; }
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
    const cnt = r.user_count != null ? `~${r.user_count} משתמשים` : 'זמין';
    box.innerHTML = `<span style="color:var(--success)">✓ פורום NodeBB תקין (${esc(String(cnt))})</span>`;
  } else {
    box.innerHTML = `<span style="color:var(--danger)">✕ ${esc(r?.error || 'בדיקה נכשלה')}</span>`;
  }
}

async function doStartScrape() {
  const sel = document.getElementById('sync-forum');
  const name = sel.value;
  const url  = sel.selectedOptions[0]?.dataset.url || '';
  const cookie = document.getElementById('sync-cookie').value.trim();
  if (!url) { toast('לפורום זה אין כתובת URL', 'error'); return; }

  const start = await api('start_scrape', name, url, cookie, null);
  if (!start || !start.ok) { toast(start?.error || 'לא ניתן להתחיל סריקה', 'error'); return; }

  document.getElementById('sync-progress-wrap').style.display = '';
  document.getElementById('sync-check-result').innerHTML = '';

  _scrapePoll = setInterval(async () => {
    const p = await api('get_scrape_progress');
    if (!p) return;
    const pct = p.total_pages ? Math.round((p.page / p.total_pages) * 100) : 0;
    document.getElementById('sync-bar').style.width = pct + '%';
    document.getElementById('sync-progress-text').textContent =
      `עמוד ${p.page}/${p.total_pages || '?'} · נוספו ${p.added} · עודכנו ${p.updated} · התנגשויות ${p.conflicts}`;

    if (p.done || !p.running) {
      clearInterval(_scrapePoll); _scrapePoll = null;
      if (p.error) {
        toast('שגיאת סריקה: ' + p.error, 'error');
      } else {
        const msg = p.cancelled ? 'הסריקה בוטלה' : 'הסריקה הושלמה';
        let extra = '';
        if (p.auto_resolved) extra = `, ${p.auto_resolved} התנגשויות נפתרו אוטומטית`;
        else if (p.conflicts) extra = `, ${p.conflicts} התנגשויות`;
        toast(`${msg} — נוספו ${p.added}, עודכנו ${p.updated}${extra}`, 'success');
      }
      await loadNicks(document.getElementById('search-input').value);
      if (p.conflicts > 0) {
        setTimeout(() => {
          if (confirm(`נמצאו ${p.conflicts} התנגשויות. לפתור אותן עכשיו?`)) {
            closeSyncModal();
            if (typeof openConflictsResolver === 'function') openConflictsResolver();
          }
        }, 300);
      }
    }
  }, 700);
}

// ══ פותר התנגשויות גלובלי ═══════════════════════════════════════════════
async function openConflictsResolver() {
  const conflicts = await api('get_all_conflicts') || [];
  openModal('⚠️ פתרון התנגשויות', renderResolverBody(conflicts), [
    { label: 'העדף הכל: החדש',  cls: 'btn-warning', action: () => resolveAllConflicts('new') },
    { label: 'העדף הכל: הקיים', cls: 'btn-ghost',   action: () => resolveAllConflicts('existing') },
    { label: 'סגור',            cls: 'btn-ghost',   action: closeModal },
  ], 'modal-lg');
}

function renderResolverBody(conflicts) {
  if (!conflicts.length) {
    return `<div style="text-align:center;padding:30px;color:var(--subtext)">
      <div style="font-size:44px;margin-bottom:10px">✓</div>אין התנגשויות פתוחות</div>`;
  }
  return `
    <p style="color:var(--subtext);font-size:13px;margin-bottom:14px">
      לכל שדה: הערך הקיים מול הערך שנסרק. בחר איזה לשמור, או השתמש בכפתורים למטה לפתרון גורף.
    </p>
    <div id="resolver-list">
      ${conflicts.map(c => `
        <div class="conflict-item" data-cid="${c.id}" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:10px;border-bottom:1px solid var(--border-soft)">
          <div style="flex:1;min-width:220px">
            <div style="font-weight:700;font-size:12px;margin-bottom:4px">
              ${esc(c.username)} · <span style="color:var(--accent-2)">${esc(c.field_name)}</span>
            </div>
            <div style="font-size:12.5px">
              <span style="color:var(--subtext)">קיים:</span> ${esc(String(c.current_value ?? '') || '(ריק)')}
              &nbsp;→&nbsp;
              <span style="color:var(--subtext)">חדש:</span> <b>${esc(c.conflicting_value)}</b>
            </div>
          </div>
          <div style="display:flex;gap:6px">
            <button class="btn btn-sm btn-primary" onclick="resolveOne(${c.id}, true)">קבל חדש</button>
            <button class="btn btn-sm btn-ghost"   onclick="resolveOne(${c.id}, false)">שמור קיים</button>
          </div>
        </div>`).join('')}
    </div>`;
}

async function resolveOne(conflictId, acceptNew) {
  if (acceptNew) await api('apply_conflict', conflictId);
  else           await api('delete_conflict', conflictId);
  const el = document.querySelector(`.conflict-item[data-cid="${conflictId}"]`);
  if (el) el.remove();
  await loadNicks(document.getElementById('search-input').value);
  const list = document.getElementById('resolver-list');
  if (list && !list.querySelector('.conflict-item')) {
    list.innerHTML = `<div style="text-align:center;padding:24px;color:var(--subtext)">✓ כל ההתנגשויות נפתרו</div>`;
  }
}

async function resolveAllConflicts(prefer) {
  const label = prefer === 'new' ? 'להחיל את כל הערכים החדשים' : 'לשמור על כל הערכים הקיימים';
  if (!confirm(`${label}?`)) return;
  const r = await api('resolve_all_conflicts', prefer);
  await loadNicks(document.getElementById('search-input').value);
  toast(`${r?.count ?? 0} התנגשויות נפתרו`, 'success');
  closeModal();
}

function openChazonishnik() {
  openModal('📖 Chazonishnik', `
    <div style="text-align:center;padding:30px 20px">
      <div style="font-size:52px;margin-bottom:16px">📖</div>
      <h3 style="font-size:18px;margin-bottom:10px">Chazonishnik</h3>
      <p style="color:var(--subtext);font-size:14px;line-height:1.6">
        פיצ'ר זה עדיין בפיתוח.<br>הפונקציונליות תתווסף בקרוב.
      </p>
    </div>`, [
    { label: 'סגור', cls: 'btn-primary', action: closeModal },
  ], 'modal-sm');
}

function openStinknik() {
  openModal('🦨 Stinknik', `
    <div style="text-align:center;padding:30px 20px">
      <div style="font-size:52px;margin-bottom:16px">🦨</div>
      <h3 style="font-size:18px;margin-bottom:10px">Stinknik</h3>
      <p style="color:var(--subtext);font-size:14px;line-height:1.6">
        פיצ'ר זה עדיין בפיתוח.<br>הפונקציונליות תתווסף בקרוב.
      </p>
    </div>`, [
    { label: 'סגור', cls: 'btn-primary', action: closeModal },
  ], 'modal-sm');
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

  grid.innerHTML = '';
  const upTo = Math.min(S.cardsRendered || S.cardsChunk, S.nicks.length);
  for (let i = 0; i < upTo; i++) {
    grid.appendChild(buildCardElement(S.nicks[i]));
  }
}

function appendMoreCards() {
  const grid = document.getElementById('cards-grid');
  if (!grid) return;
  const from = S.cardsRendered;
  const to = Math.min(from + S.cardsChunk, S.nicks.length);
  for (let i = from; i < to; i++) {
    grid.appendChild(buildCardElement(S.nicks[i]));
  }
  S.cardsRendered = to;
}

let _cardsScrollRaf = null;
function onCardsScroll() {
  if (_cardsScrollRaf) return;
  _cardsScrollRaf = requestAnimationFrame(() => {
    _cardsScrollRaf = null;
    const wrap = document.getElementById('cards-wrap');
    if (!wrap) return;
    const nearBottom = wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 600;
    if (nearBottom && S.cardsRendered < S.nicks.length) appendMoreCards();
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
    const nickCol = n.nick_color || color;
    const avatarHtml = n.avatar_image
      ? `<div class="card-avatar" style="padding:0;overflow:hidden"><img src="${n.avatar_image}" style="width:100%;height:100%;object-fit:cover"></div>`
      : `<div class="card-avatar" style="background:linear-gradient(135deg,${nickCol},${shade(nickCol,-25)})">${esc(initial)}</div>`;

    // rows — only fields that exist
    const rows = [];
    if (n.real_name)  rows.push(cardRow('👤', n.real_name));
    if (n.phone)      rows.push(cardRow('📞', n.phone + (n.extra_contacts ? ' ❕' : '')));
    if (n.email)      rows.push(cardRow('📧', n.email));
    if (n.groups)     rows.push(cardRow('🏷️', n.groups));
    if (n.reputation) rows.push(cardRow('⭐', String(n.reputation)));
    if (n.extra_info) rows.push(cardRow('ℹ️', n.extra_info));
    if (n.private_notes) rows.push(cardRow('🔒', n.private_notes, true));

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
      ${n.notes ? `<div class="card-notes">${esc(n.notes)}</div>` : ''}
      <div class="card-footer">
        <span class="card-badge ${stCls}">● ${esc(st)}</span>
        ${n.has_identity ? '<span class="card-badge" style="background:var(--accent-soft);color:var(--accent-2)">👤 זהות</span>' : ''}
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
    card.onclick    = e => selectRow(n.id, e);
    card.ondblclick = () => openNickDialog(n.id);
    return card;
}

function cardRow(icon, val, isPrivate) {
  return `<div class="card-row${isPrivate ? ' private' : ''}">
    <span class="ci">${icon}</span>
    <span class="cv">${esc(val)}</span>
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

  const colItems = COLS.filter(cc => cc.key !== '_open').map(cc => {
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
    </div>`;

  openModal('🎨 הגדרות תצוגה', html, [
    { label: '↺ אפס לברירת מחדל', cls: 'btn-ghost', action: resetDisplay },
    { label: 'סגור', cls: 'btn-primary', action: closeModal },
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
  if (key === 'density')  document.body.dataset.density  = val;
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
  Object.assign(DISPLAY, {theme:'dark',accent:'amber',view:'table',density:'normal',hidden_cols:''});
  await applyDisplaySettings();
  buildTableHeader();
  renderTable();
  closeModal();
  toast('הגדרות התצוגה אופסו', 'info');
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                         .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
