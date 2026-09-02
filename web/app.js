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
  { key: 'notes',         label: 'הערות',           width: 180, render: renderNotes },
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
  // גרסה ב-footer מיד מההפעלה (לא תלוי בבדיקת עדכונים / אינטרנט)
  api('get_app_version').then(v => {
    const el = document.getElementById('footer-version');
    if (el && v?.version) el.textContent = `v${v.version} | Tik-Nick`;
  });
  await applyDisplaySettings();
  buildTableHeader();
  await loadForums();
  await loadNicks();
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
  const conflictFields = n.conflict_fields ? String(n.conflict_fields).split(',') : [];
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

async function showFieldSourcesTooltip(e, nickId, fieldKey) {
  // שמור קואורדינטות מיד — לפני ה-await (אחרת האירוע עלול להתאפס)
  const cx = e.clientX, cy = e.clientY;
  const srcs = await api('get_field_sources', nickId, fieldKey);
  if (!srcs || srcs.length < 2) return;
  const srcKind = s => s.kind==='me' ? 'אני' : s.kind==='scrape' ? 'סריקה' : s.name;
  const rows = srcs.map((s, i) =>
    `<div style="padding-right:8px">${i===0?'▸':'◦'} ${esc(String(s.value))} <span style="opacity:.65">— ${esc(srcKind(s))}</span></div>`
  ).join('');
  showTooltipAt(cx, cy, `<b>גרסאות לפי מקור:</b>${rows}`);
}

function showTooltipAt(cx, cy, html) {
  const tt = document.getElementById('tooltip');
  tt.innerHTML = html;
  tt.style.display = '';
  tt.style.left = Math.min(cx + 12, window.innerWidth  - 300) + 'px';
  tt.style.top  = Math.min(cy + 12, window.innerHeight - 150) + 'px';
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
  const shelvedHtml = (nick?.field_sources && Object.keys(nick.field_sources).length)
    ? renderFieldSourcesSection(nick.field_sources) : '';

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
        <input class="form-input tag-field" id="f-address" value="${esc(nick?.address||'')}">
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
            ? `<img src="${esc(nick.avatar_image)}" alt="">`
            : `<span class="avatar-initial" style="background:${esc(nick?.nick_color||'var(--accent)')}">${esc((nick?.username||'?').charAt(0).toUpperCase())}</span>`}
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

// ══ תיוג ניקים בטקסט חופשי (@username) ═══════════════════════════════════
let _tagField = null;

// האזנה גלובלית — תופסת כל שדה עם class="tag-field" גם אם נוצר דינמית
document.addEventListener('input', (e) => {
  if (e.target && e.target.classList && e.target.classList.contains('tag-field')) {
    onTagInput(e);
  }
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
  const results = await api('search_usernames', prefix, 8) || [];
  if (!results.length) { box.style.display = 'none'; return; }
  box.innerHTML = results.map(r => `
    <div class="tag-opt" style="padding:7px 12px;cursor:pointer;font-size:13px;direction:rtl"
         onmousedown="pickTag(event,'${esc(r.username).replace(/'/g,"\\'")}')">
      <span style="color:${S.forumColors[r.forum]||'#8b90a0'}">[${esc(r.forum)}]</span>
      ${esc(r.username)}
    </div>`).join('');
  const rect = ta.getBoundingClientRect();
  box.style.left = rect.left + 'px';
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
      const safeRaw = esc(raw).replace(/'/g,"\\'");
      return `<span class="nick-tag" style="color:var(--accent);cursor:pointer;font-weight:600"
                onclick="goToTag(event,'${safeRaw}')"
                onmouseenter="tagHover(event,'${safeRaw}')"
                onmouseleave="hideTooltip()">@${esc(display)}</span>`;
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

async function searchForIdentity(q, nickId) {
  const box = document.getElementById('id-results');
  if (!q.trim()) { box.style.display = 'none'; return; }
  const res   = await api('get_nicks', q, 0, 50);
  const nicks = res && Array.isArray(res.rows) ? res.rows : (Array.isArray(res) ? res : []);
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

function renderFieldSourcesSection(fieldSources) {
  const fieldLabel = k => (COLS.find(c => c.key===k)?.label) || k;
  const srcKind = s => s.kind==='me' ? '👤 אני' : s.kind==='scrape' ? '🌐 סריקה' : `📥 ${esc(s.name)}`;
  const blocks = Object.entries(fieldSources).map(([field, srcs]) => {
    // srcs כבר ממוין: absolute תחילה, ואז trust יורד → הראשון הוא המנצח
    const winner = srcs[0];
    const others = srcs.slice(1);
    return `
      <div class="conflict-item" style="display:block">
        <div style="font-weight:700;font-size:12.5px;margin-bottom:4px">
          ${esc(fieldLabel(field))}
          <span title="מידע סותר מכמה מקורות" style="cursor:help">⚠️</span>
        </div>
        <div style="font-size:12.5px;margin-bottom:3px">
          <span style="color:var(--success)">▸ מוצג:</span> ${esc(winner.value)}
          <span style="color:var(--subtext);font-size:11px"> (${srcKind(winner)}${winner.absolute?', אבסולוטי':`, אמינות ${winner.trust}`})</span>
        </div>
        ${others.map(o => `
          <div style="font-size:12px;color:var(--subtext);padding-right:14px">
            ◦ ${esc(o.value)} <span style="font-size:11px">(${srcKind(o)}${o.absolute?', אבסולוטי':`, אמינות ${o.trust}`})</span>
          </div>`).join('')}
      </div>`;
  }).join('');
  return `
    <div class="section-hdr" style="color:var(--subtext)">⚠️ מידע לפי מקור (אבות)</div>
    <p style="font-size:11.5px;color:var(--subtext);margin-bottom:8px">
      שדות עם יותר ממקור אחד. המוצג נבחר לפי האמינות הגבוהה. שינוי אמינות מקור בהגדרות סנכרון ישנה את המוצג.
    </p>
    ${blocks}`;
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
  setTimeout(() => document.getElementById('lookup-input')?.focus(), 60);
}

function onLookupInput(val) {
  clearTimeout(_lookupTimer);
  _lookupTimer = setTimeout(() => lookupSearch(val), 200);
}

async function lookupSearch(query) {
  const box = document.getElementById('lookup-results');
  if (!box) return;
  if (!query.trim()) { box.innerHTML = ''; return; }
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

async function showMergedProfile(nickId) {
  const box = document.getElementById('lookup-profile');
  const results = document.getElementById('lookup-results');
  if (results) results.innerHTML = '';
  if (box) box.innerHTML = '<div style="padding:14px;color:var(--subtext)">טוען…</div>';
  const p = await api('get_merged_profile', nickId);
  if (!p) { if (box) box.innerHTML = '<div style="padding:14px;color:var(--danger)">לא נמצא</div>'; return; }
  if (box) box.innerHTML = renderMergedProfile(p);
}

function renderMergedProfile(p) {
  const members = p.members || [];
  const primary = members[0] || {};
  const initial = esc((primary.username || '?').charAt(0).toUpperCase());
  // nick_color/avatar_image מגיעים מהפורום (לא בטוחים) — חובה esc בתוך innerHTML
  const avatarBg = esc(primary.nick_color || S.forumColors[primary.forum] || 'var(--accent)');
  const avatarHtml = primary.avatar_image
    ? `<img src="${esc(primary.avatar_image)}" style="width:100%;height:100%;object-fit:cover">`
    : `<span style="width:100%;height:100%;display:grid;place-items:center;font-size:22px;font-weight:800;color:#fff;background:${avatarBg}">${initial}</span>`;

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
        <b>${esc(c.value)}</b>
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
      <div style="margin-bottom:6px">${memberChips}</div>
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

async function applyFieldFilter() {
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
  const results = await api('filter_nicks_multi', conditions) || [];
  _fieldFilterActive = true;
  S.nicks = results;
  S.total = results.length;
  S.multiSelected.clear();
  sortNicks();
  renderTable();
  updateBulkBar();
  document.getElementById('flt-count').textContent = `${results.length} תוצאות`;
}

async function clearFieldFilter() {
  _fieldFilterActive = false;
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
      closeModal();
      toast(`${r?.count ?? 0} ניקים עודכנו ✓`, 'success');
      if (_fieldFilterActive) await applyFieldFilter();
      else await loadNicks(document.getElementById('search-input').value);
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

async function onSrcTrust(sid, val) {
  await api('update_source', sid, null, null, parseInt(val), null);
  await loadNicks(document.getElementById('search-input').value);
}
async function onSrcAbsolute(sid, checked) {
  await api('update_source', sid, null, null, null, checked);
  const row = document.querySelector(`.sync-item[data-sid="${sid}"]`);
  if (row) {
    const slider = row.querySelector('.src-trust');
    const wrap = row.querySelector('.src-trust-wrap');
    if (slider) slider.disabled = checked;
    if (wrap) wrap.style.opacity = checked ? '.4' : '1';
  }
  await loadNicks(document.getElementById('search-input').value);
}
async function onSrcDelete(sid) {
  if (!confirm('למחוק את המקור הזה? כל הערכים שהגיעו ממנו יימחקו, והנתונים ייפלו לערך הבא לפי אמינות.')) return;
  const r = await api('delete_source', sid);
  if (r?.ok) {
    document.querySelector(`.sync-item[data-sid="${sid}"]`)?.remove();
    await loadNicks(document.getElementById('search-input').value);
    toast('המקור נמחק, הנתונים עודכנו ✓', 'success');
  }
}

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

  // ── סעיף 3: התנגשויות בייבוא קובץ ──
  // (התנגשויות בסריקה מהאינטרנט נפתרות אוטומטית ע"י מנוע המקורות לפי אמינות —
  //  אין עוד מדיניות נפרדת לסריקה.)
  const sec3 = `
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
      <span style="display:flex;align-items:center;gap:6px" class="src-trust-wrap"
            style="${s.kind==='me' && s.absolute?'opacity:.4':''}">
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
      const im = document.getElementById('import-manual');
      if (im) await api('set_setting', 'import_manual_conflicts', im.checked ? '1' : '0');
      toast('הגדרות סנכרון נשמרו ✓', 'success');
      // לא סוגר — סגירה דרך כפתור "סגור"
    }},
    { label: 'סגור', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
}

// ══ EXPORT / IMPORT ════════════════════════════════════════════════════
async function exportData() {
  const counts = await api('get_export_counts') || { all: 0, has_info: 0, my_info: 0 };
  const opt = (mode, icon, title, desc, count) => `
    <label class="policy-opt" style="display:flex;gap:10px;align-items:flex-start;padding:12px;border:1px solid var(--border-soft);border-radius:10px;margin-bottom:10px;cursor:pointer">
      <input type="radio" name="expmode" value="${mode}" ${mode === 'all' ? 'checked' : ''} style="margin-top:3px">
      <div style="flex:1">
        <div style="font-weight:700;font-size:13.5px">${icon} ${title}
          <span style="float:left;color:var(--accent-2);font-weight:800">${count}</span></div>
        <div style="font-size:12px;color:var(--subtext);margin-top:2px">${desc}</div>
      </div>
    </label>`;
  openModal('📤 ייצוא נתונים', `
    <p style="color:var(--subtext);font-size:12.5px;margin-bottom:14px">
      בחר אילו ניקים לייצא. חלים גם כללי הסנכרון (אילו שדות ופורומים כלולים).
    </p>
    ${opt('all', '📦', 'כל הניקים', 'ייצוא מלא של כל המאגר', counts.all)}
    ${opt('has_info', '✓', 'רק ניקים עם מידע', 'ניקים עם שם אמיתי / טלפון / מייל / הערות / אנשי קשר / זהות', counts.has_info)}
    ${opt('my_info', '👤', 'רק מידע שהוספתי בעצמי', 'ניקים שיש בהם ערך שאני הזנתי (מקור "אני") או אנשי קשר / הערות אישיות', counts.my_info)}
  `, [
    { label: '📤 ייצא', cls: 'btn-primary', action: async () => {
      const mode = document.querySelector('input[name="expmode"]:checked')?.value || 'all';
      closeModal();
      const res = await api('export_data', mode);
      if (res?.ok) toast(`יוצאו ${res.count} ניקים ✓`, 'success');
      else if (res?.error !== 'בוטל') toast('שגיאה בייצוא', 'error');
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
      if (r2.manual && r2.conflicts && r2.conflicts.length) {
        startImportConflictResolver(r2.conflicts);
      } else {
        toast(`הייבוא הושלם ✓ · ניקים חדשים: ${r2.imported} · ערכים שנקלטו: ${r2.conflicts}`, "success");
      }
    } else {
      toast('שגיאה בייבוא: ' + (r2?.error||''), 'error');
    }
    return;
  }
  showForumMappingDialog(unknown, res.nick_count);
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
  ], 'modal-sm');
}

async function resolveImportConflict(accept) {
  const all = document.getElementById('imp-apply-all')?.checked;
  const c = _impConflicts[_impConflictIdx];
  await api('apply_import_conflict', c.nick_id, c.field, c.new_value, c.source_id, accept);
  _impConflictIdx++;
  if (all) {
    // החל את אותה בחירה על כל השאר
    for (; _impConflictIdx < _impConflicts.length; _impConflictIdx++) {
      const rest = _impConflicts[_impConflictIdx];
      await api('apply_import_conflict', rest.nick_id, rest.field, rest.new_value, rest.source_id, accept);
    }
  }
  showNextImportConflict();
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
        if (r2.manual && r2.conflicts && r2.conflicts.length) {
          startImportConflictResolver(r2.conflicts);
        } else {
          toast(`הייבוא הושלם ✓ · ניקים חדשים: ${r2.imported} · ערכים שנקלטו: ${r2.conflicts}`, "success");
        }
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
  const cx = e.clientX, cy = e.clientY;
  const nick = await api('get_nick', nickId);
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
  document.getElementById('tooltip').style.display = 'none';
}

// ══ MODAL ═════════════════════════════════════════════════════════════
function openModal(title, bodyHtml, buttons = [], extraClass = '') {
  closeModal();
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'modal-overlay';
  overlay.onclick = e => { if (e.target === overlay) closeModal(); };

  const btnsHtml = buttons.map((b, i) =>
    `<button class="btn ${b.cls}" id="mb-idx-${i}">${b.label}</button>`
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

  buttons.forEach((b, i) => {
    const el = overlay.querySelector(`#mb-idx-${i}`);
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
        עוגיית התחברות (express.sid) — רק אם הפורום דורש התחברות לצפייה במשתמשים (לא חובה). נשמרת לפעם הבאה.
      </label>
      <button class="btn btn-ghost btn-sm" style="white-space:nowrap;flex-shrink:0"
              onclick="openChazonishnikHelp()" title="איך משיגים עוגיות?">🍪 איך משיגים?</button>
    </div>
    <input id="sync-cookie" class="form-input" style="width:100%;margin-bottom:12px" dir="ltr"
           placeholder="express.sid=s%3A...  (השאר ריק אם הפורום ציבורי)">

    <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
      <label style="font-size:12px;color:var(--subtext);white-space:nowrap">הגבל עמודים (אופציונלי):</label>
      <input id="sync-maxpages" type="number" min="1" class="form-input" style="width:120px"
             placeholder="הכל" title="כמה עמודי משתמשים לסרוק לכל היותר (ריק = הכל)">
      <span style="font-size:11px;color:var(--subtext)">~50 משתמשים בעמוד</span>
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
    { label: '🌍 סרוק הכל', cls: 'btn-warning', action: doStartScrapeAll },
    { label: 'סגור',        cls: 'btn-ghost',   action: closeSyncModal },
  ], 'modal-lg');
  onSyncForumChange();
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
  if (!confirm('לסרוק את כל הפורומים ברצף? פורום שלא ניתן לסרוק יידלג אוטומטית.')) return;
  const cookie = document.getElementById('sync-cookie')?.value.trim() || '';
  const maxPages = parseInt(document.getElementById('sync-maxpages')?.value) || null;
  const start = await api('start_scrape_all', cookie, maxPages);
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
    const label = `${forumPrefix}עמוד ${p.page}/${p.total_pages || '?'} · נוספו ${p.added} · עודכנו ${p.updated}`;

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
        const msg = p.cancelled ? 'הסריקה בוטלה' : 'הסריקה הושלמה';
        let extra = '';
        if (p.skipped && p.skipped.length) extra = ` · דולגו ${p.skipped.length} פורומים`;
        toast(`${msg} — נוספו ${p.added}, עודכנו ${p.updated}${extra}`, 'success');
      }
      await _yieldPaint();   // תן לבאנר להיעלם לפני הטעינה הכבדה
      await loadNicks(document.getElementById('search-input').value);
    }
    } finally { busy = false; }
  }, 700);
}

function openChazonishnikHelp() {
  openChazonishnik();
}

function updateSyncHint() {
  const sel = document.getElementById('sync-forum');
  const opt = sel?.selectedOptions[0];
  const hint = document.getElementById('sync-forum-hint');
  if (!opt || !hint) return;
  const plat = opt.dataset.platform || 'nodebb';
  if (!SCRAPABLE_PLATFORMS.has(plat)) {
    hint.innerHTML = `⛔ פלטפורמת ${esc(PLATFORM_LABELS[plat] || plat)} — אין API ציבורי לרשימת משתמשים, ` +
                     `לכן אין סריקה אוטומטית. אפשר להוסיף ולנהל ניקים בפורום זה ידנית.`;
    hint.style.color = 'var(--danger)';
  } else if (opt.dataset.login === '1') {
    hint.innerHTML = '🔒 פורום זה דורש התחברות — הזן עוגיית express.sid למטה (ראה "🍪 איך משיגים?").';
    hint.style.color = 'var(--accent-2)';
  } else {
    hint.innerHTML = '';
  }
}

// מופעל בהחלפת פורום: עדכן רמז + טען עוגייה שמורה של הפורום החדש
function onSyncForumChange() {
  updateSyncHint();
  syncPrefillCookie();
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

      <div style="margin-bottom:14px;padding:14px;border:1px solid var(--accent-2);border-radius:10px">
        <b style="font-size:13px">✅ דרך מומלצת: תוסף Get cookies.txt</b>
        <ol style="margin:8px 0 0;padding-inline-start:20px;font-size:12px;line-height:1.9">
          <li>לחץ כאן להתקנת התוסף:
            <b style="color:var(--accent-2);cursor:pointer;text-decoration:underline"
               onclick="openExt('https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc')">Get cookies.txt LOCALLY</b>
            → בחלון שנפתח לחץ "Add to Chrome" / "הוסף ל-Chrome" ואשר.</li>
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
      </div>

      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">שם משתמש לניתוח</label>
        <input id="chz-user" class="form-input" placeholder="שם המשתמש בפורום (למשל: בנימין)">
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

async function runChazonishnik() {
  const username = document.getElementById('chz-user')?.value.trim();
  const cookie   = document.getElementById('chz-cookie')?.value.trim() || '';
  const baseUrl  = document.getElementById('chz-forum')?.value || 'https://mitmachim.top';
  const maxPosts = parseInt(document.getElementById('chz-maxposts')?.value) || null;
  if (!username) { toast('הזן שם משתמש', 'error'); return; }
  const start = await api('run_chazonishnik', username, cookie, baseUrl, maxPosts);
  if (!start?.ok) { toast('שגיאה: ' + (start?.error || ''), 'error'); return; }
  showChazonishnikProgress(username);
}

function showChazonishnikProgress(username) {
  openModal('📊 מנתח פעילות…', `
    <div style="text-align:center;padding:24px 16px">
      <div style="font-size:40px;margin-bottom:14px">⏳</div>
      <div id="chz-progress-text" style="font-size:14px;margin-bottom:8px">מתחיל…</div>
      <div style="font-size:12px;color:var(--subtext)">מנתח את הפעילות של ${esc(username)} — רץ ברקע, אפשר לצאת ולחזור</div>
      <div style="height:8px;background:var(--card2);border-radius:99px;overflow:hidden;margin-top:16px">
        <div id="chz-bar" style="height:100%;width:20%;background:linear-gradient(90deg,var(--accent),var(--accent-2));transition:width .4s"></div>
      </div>
    </div>
  `, [
    { label: '✕ בטל', cls: 'btn-danger', action: cancelChazonishnik },
    { label: '🏠 המשך ברקע', cls: 'btn-ghost', action: closeModal },
  ], 'modal-sm');
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

    const txt = document.getElementById('chz-progress-text');
    const bar = document.getElementById('chz-bar');
    if (txt) txt.textContent = label;
    if (bar && p.total) bar.style.width = Math.min(90, 20 + (p.count / p.total) * 70) + '%';
    const bTxt = document.getElementById('chz-banner-text');
    if (bTxt) bTxt.textContent = p.running ? label : 'מסיים…';

    if (p.done || !p.running) {
      clearInterval(_chzPoll); _chzPoll = null;
      if (banner) banner.style.display = 'none';
      if (p.cancelled) { toast('הניתוח בוטל', 'info'); if (isModalOpen()) closeModal(); return; }
      if (p.error) { toast('שגיאה: ' + p.error, 'error'); if (isModalOpen()) closeModal(); return; }
      if (p.html) { showChazonishnikReport(p.html, p.count); toast('הניתוח הושלם ✓', 'success'); }
      else if (isModalOpen()) closeModal();
    }
    } finally { busy = false; }
  }, 600);
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
  if (isModalOpen()) closeModal();
}

function showChazonishnikReport(html, postCount) {
  openModal(`📊 דוח פעילות${postCount ? ` · ${postCount} פוסטים` : ''}`, `
    <iframe id="chz-frame" style="width:100%;height:68vh;border:none;border-radius:8px;background:#0f172a"></iframe>
  `, [
    { label: '💾 שמור כ-HTML', cls: 'btn-primary', action: () => saveChazonishnikReport(html) },
    { label: '🔄 ניתוח נוסף', cls: 'btn-ghost', action: openChazonishnik },
    { label: '🏠 תפריט ראשי', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
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
        שגיאת הרשאה, אפשר להוסיף עוגייה — <b style="color:var(--accent-2);cursor:pointer" onclick="openChazonishnik()">ראה הדרכה ב-Chazonishnik</b>.
      </div>
      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">פורום</label>
        <select id="stink-forum" class="form-select" onchange="stinkPrefillCookie()">${opts}</select>
      </div>
      <div class="form-group" style="margin-bottom:10px">
        <label class="form-label">שם משתמש או קישור לפרופיל</label>
        <input id="stink-user" class="form-input" placeholder="בנימין  או  קישור מלא לפרופיל">
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
  ], 'modal-sm');
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
      if (p.cancelled) { toast('הסריקה בוטלה', 'info'); if (isModalOpen()) closeModal(); return; }
      if (p.error) { toast('שגיאה: ' + p.error, 'error'); if (isModalOpen()) closeModal(); return; }
      if (p.html) { showStinknikReport(p.html, p.disliked); toast('הסריקה הושלמה ✓', 'success'); }
      else if (isModalOpen()) closeModal();
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
  if (isModalOpen()) closeModal();
}

function showStinknikReport(html, disCount) {
  openModal(`🦨 דוח דיסלייקים${disCount != null ? ` · ${disCount} פוסטים` : ''}`, `
    <iframe id="stink-frame" style="width:100%;height:68vh;border:none;border-radius:8px;background:#0f172a"></iframe>
  `, [
    { label: '💾 שמור כ-HTML', cls: 'btn-primary', action: () => saveStinknikReport(html) },
    { label: '🔄 ניתוח נוסף', cls: 'btn-ghost', action: openStinknik },
    { label: '🏠 תפריט ראשי', cls: 'btn-ghost', action: closeModal },
  ], 'modal-lg');
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
      ? `<div class="card-avatar" style="padding:0;overflow:hidden"><img src="${esc(n.avatar_image)}" style="width:100%;height:100%;object-fit:cover"></div>`
      : `<div class="card-avatar" style="background:linear-gradient(135deg,${esc(nickCol)},${esc(shade(nickCol,-25))})">${esc(initial)}</div>`;

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
