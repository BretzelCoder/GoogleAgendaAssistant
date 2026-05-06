const State = { parsedEvents: [], calendars: [] };
const CONFIG_KEY = 'ics_gcal_client_id';
const getClientId = () => localStorage.getItem(CONFIG_KEY) || '';
const saveClientId = id => localStorage.setItem(CONFIG_KEY, id.trim());
const $ = id => document.getElementById(id);

// ── Refs UI ────────────────────────────────────────────────────────────────
const UI = {
  clientIdInput:   () => $('client-id-input'),
  saveClientIdBtn: () => $('save-client-id-btn'),
  loginBtn:        () => $('login-btn'),
  logoutBtn:       () => $('logout-btn'),
  userEmail:       () => $('user-email'),
  authSpinner:     () => $('auth-spinner'),
  step1:           () => $('step-1'),
  step2:           () => $('step-2'),
  step3:           () => $('step-3'),
  fileInput:       () => $('file-input'),
  dropZone:        () => $('drop-zone'),
  fileLabel:       () => $('file-label'),
  urlInput:        () => $('url-input'),
  parseBtn:        () => $('parse-btn'),
  previewCount:    () => $('preview-count'),
  previewBody:     () => $('preview-body'),
  selectAllChk:    () => $('select-all'),
  calendarSelect:  () => $('calendar-select'),
  strategySelect:  () => $('strategy-select'),
  importBtn:       () => $('import-btn'),
  backBtn:         () => $('back-btn'),
  resultSummary:   () => $('result-summary'),
  resultDetails:   () => $('result-details'),
  newImportBtn:    () => $('new-import-btn'),
  progressBar:     () => $('progress-bar'),
  progressFill:    () => $('progress-fill'),
  progressText:    () => $('progress-text'),
  toast:           () => $('toast'),
};

// ── Toast ──────────────────────────────────────────────────────────────────
function showToast(msg, type = 'info') {
  const t = UI.toast();
  t.textContent = msg;
  t.className = `toast toast--${type} toast--visible`;
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('toast--visible'), 5000);
}

// ── Étapes ─────────────────────────────────────────────────────────────────
function showStep(n) {
  [1,2,3].forEach(i => { const e = $('step-'+i); if(e) e.hidden = i !== n; });
  $('progress-bar').hidden = true;
}

// ── Auth état UI ───────────────────────────────────────────────────────────
function setAuthState(state) {
  // state: 'loading' | 'disconnected' | 'connected'
  UI.authSpinner().hidden = state !== 'loading';
  UI.loginBtn().hidden    = state !== 'disconnected';
  UI.logoutBtn().hidden   = state !== 'connected';
}

// ── Callback token ─────────────────────────────────────────────────────────
async function onTokenReceived(token, errorMsg) {
  if (!token) {
    setAuthState('disconnected');
    UI.userEmail().textContent = '';
    UI.step1().hidden = true;
    if (errorMsg) showToast(errorMsg, 'error');
    return;
  }
  setAuthState('connected');
  try {
    State.calendars = await GCal.listCalendars();
    const primary = State.calendars.find(c => c.primary);
    if (primary) UI.userEmail().textContent = '✅ ' + primary.id;
    const sel = UI.calendarSelect();
    sel.innerHTML = '';
    State.calendars.forEach(cal => {
      const o = document.createElement('option');
      o.value = cal.id;
      o.textContent = (cal.summaryOverride || cal.summary || cal.id) + (cal.primary ? ' (principal)' : '');
      if (cal.primary) o.selected = true;
      sel.appendChild(o);
    });
  } catch(e) { showToast('Erreur chargement agendas : ' + e.message, 'error'); }
  UI.step1().hidden = false;
  showStep(1);
}

// ── Drag & drop ────────────────────────────────────────────────────────────
function initDropZone() {
  const dz = UI.dropZone(), fi = UI.fileInput();
  ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('drag-over'); }));
  ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, () => dz.classList.remove('drag-over')));
  dz.addEventListener('drop', e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if(f) assignFile(f); });
  fi.addEventListener('change', () => { if(fi.files[0]) assignFile(fi.files[0]); });
}
function assignFile(file) {
  if (!file.name.endsWith('.ics') && file.type !== 'text/calendar') { showToast('Fichier .ics requis', 'error'); return; }
  UI.fileLabel().textContent = '📄 ' + file.name;
  UI.urlInput().value = '';
  UI.fileInput()._file = file;
}

// ── Parse ──────────────────────────────────────────────────────────────────
async function handleParse() {
  UI.parseBtn().disabled = true; UI.parseBtn().textContent = '⏳ Analyse…';
  try {
    const file = UI.fileInput()._file, url = UI.urlInput().value.trim();
    let text = '';
    if (file) {
      text = await new Promise((res,rej) => { const r = new FileReader(); r.onload = e => res(e.target.result); r.onerror = () => rej(new Error('Lecture impossible')); r.readAsText(file,'UTF-8'); });
    } else if (url) {
      const resp = await fetch(url).catch(e => { throw new Error('CORS ou réseau : ' + e.message); });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      text = await resp.text();
    } else { showToast('Choisissez un fichier ou entrez une URL', 'error'); return; }
    State.parsedEvents = ICSParser.parseICS(text);
    if (!State.parsedEvents.length) { showToast('Aucun événement trouvé', 'error'); return; }
    renderPreview(); showStep(2);
  } catch(e) { showToast(e.message, 'error'); }
  finally { UI.parseBtn().disabled = false; UI.parseBtn().textContent = '🔍 Analyser'; }
}

// ── Prévisualisation ───────────────────────────────────────────────────────
const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

function renderPreview() {
  const evs = State.parsedEvents, v = evs.filter(e=>e.isValid), inv = evs.filter(e=>!e.isValid);
  UI.previewCount().innerHTML = `<strong>${evs.length}</strong> événement(s) — <span class="count-valid">${v.length} valide(s)</span>${inv.length ? ` · <span class="count-error">${inv.length} invalide(s)</span>` : ''}`;
  const tb = UI.previewBody(); tb.innerHTML = '';
  evs.forEach((ev, i) => {
    const tr = document.createElement('tr'), key = ev.uid || '_idx_'+i;
    tr.className = ev.isValid ? '' : 'row-invalid';
    tr.innerHTML = `<td class="col-check">${ev.isValid ? `<input type="checkbox" class="evt-check" data-key="${key}" checked>` : `<span title="${esc(ev.error)}">⚠️</span>`}</td><td class="col-title">${esc(ev.summary)}</td><td class="col-date">${esc(ev.startDisplay)}</td><td class="col-date">${esc(ev.endDisplay)}</td><td class="col-tags">${ev.isRecurring?'<span class="tag tag-rec">🔁 Récurrent</span>':''}${ev.location?`<span class="tag tag-loc" title="${esc(ev.location)}">📍</span>`:''}${!ev.isValid?`<span class="tag tag-err" title="${esc(ev.error)}">❌</span>`:''}</td>`;
    tb.appendChild(tr);
  });
  UI.selectAllChk().checked = true;
  UI.selectAllChk().onchange = () => { document.querySelectorAll('.evt-check').forEach(c => c.checked = UI.selectAllChk().checked); updateBtn(); };
  updateBtn();
  document.querySelectorAll('.evt-check').forEach(c => c.addEventListener('change', updateBtn));
}
function updateBtn() {
  const n = document.querySelectorAll('.evt-check:checked').length;
  UI.importBtn().textContent = `⬆️ Importer ${n} événement(s)`;
  UI.importBtn().disabled = n === 0;
}

// ── Import ─────────────────────────────────────────────────────────────────
async function handleImport() {
  const keys = new Set([...document.querySelectorAll('.evt-check:checked')].map(c => c.dataset.key));
  if (!keys.size) { showToast('Aucun événement sélectionné', 'error'); return; }
  const toImport = State.parsedEvents.filter((ev,i) => ev.isValid && keys.has(ev.uid||'_idx_'+i)).map(ev => ev.googleEvent);
  if (!toImport.length) { showToast('Aucun événement valide', 'error'); return; }
  const bar = UI.progressBar(), fill = UI.progressFill(), txt = UI.progressText();
  bar.hidden = false; fill.style.width = '0%'; UI.importBtn().disabled = true;
  try {
    const report = await GCal.importAll(UI.calendarSelect().value, toImport, UI.strategySelect().value, (done, total) => {
      fill.style.width = Math.round(done/total*100)+'%'; txt.textContent = done+' / '+total;
    });
    bar.hidden = true; renderResult(report); showStep(3);
  } catch(e) { bar.hidden = true; UI.importBtn().disabled = false; showToast('Erreur : '+e.message, 'error'); }
}

// ── Résultat ───────────────────────────────────────────────────────────────
function renderResult(r) {
  const p = []; if(r.imported) p.push(`✅ ${r.imported} importé(s)`); if(r.updated) p.push(`🔄 ${r.updated} mis à jour`); if(r.skipped) p.push(`⏭ ${r.skipped} ignoré(s)`); if(r.errors.length) p.push(`❌ ${r.errors.length} erreur(s)`);
  UI.resultSummary().textContent = p.join(' · ') || 'Aucun résultat.';
  const d = UI.resultDetails(); d.innerHTML = '';
  if (r.errors.length) { const ul = document.createElement('ul'); ul.className='error-list'; r.errors.slice(0,10).forEach(e=>{const li=document.createElement('li');li.textContent=e;ul.appendChild(li);}); d.appendChild(ul); }
}

// ── Setup Client ID ────────────────────────────────────────────────────────
function initSetupPanel() {
  UI.clientIdInput().value = getClientId();
  UI.saveClientIdBtn().addEventListener('click', () => {
    const id = UI.clientIdInput().value.trim();
    if (!id || !id.includes('.apps.googleusercontent.com')) { showToast('Client ID invalide', 'error'); return; }
    saveClientId(id); showToast('Sauvegardé, rechargement…', 'success');
    setTimeout(() => location.reload(), 1000);
  });
}

// ── Init ───────────────────────────────────────────────────────────────────
function init() {
  console.log('[app] init() démarré');
  initSetupPanel();
  initDropZone();

  const clientId = getClientId();
  console.log('[app] clientId:', clientId ? clientId.substring(0,20)+'…' : 'ABSENT');

  if (!clientId) {
    setAuthState('disconnected');
    UI.loginBtn().disabled = true;
    UI.loginBtn().title = 'Entrez d\'abord votre Client ID';
    UI.step1().hidden = true;
    return;
  }

  setAuthState('loading');

  console.log('[app] Appel GCal.init()');
  GCal.init(clientId, onTokenReceived);

  UI.loginBtn().addEventListener('click', () => {
    console.log('[app] Clic Se connecter');
    GCal.requestToken();
  });
  UI.logoutBtn().addEventListener('click', () => { GCal.revokeToken(); State.parsedEvents = []; showStep(1); });
  UI.parseBtn().addEventListener('click', handleParse);
  UI.importBtn().addEventListener('click', handleImport);
  UI.backBtn().addEventListener('click', () => showStep(1));
  UI.newImportBtn().addEventListener('click', () => {
    UI.fileInput()._file = null; UI.fileInput().value = ''; UI.fileLabel().textContent = ''; UI.urlInput().value = ''; State.parsedEvents = []; showStep(1);
  });

  UI.step1().hidden = true;
}

// Polling : attend que google.accounts.oauth2 soit disponible (script async)
let _initCalled = false;
(function waitForGIS(n) {
  if (_initCalled) return;
  if (typeof google !== 'undefined' && google.accounts?.oauth2) {
    _initCalled = true;
    console.log('[app] GIS disponible → init()');
    init();
  } else if (n < 100) {
    setTimeout(() => waitForGIS(n + 1), 100);
  } else {
    console.error('[app] GIS non chargé après 10s');
    setAuthState('disconnected');
    showToast('Impossible de charger Google. Vérifiez votre connexion Internet.', 'error');
  }
})(0);
