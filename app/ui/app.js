'use strict';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const PAGE = 120; // so viele Karten auf einmal zeichnen, Rest beim Scrollen

// Epics Cover sind 1200x1600 (entpackt ~7,7 MB je Bild). Der Bildserver
// liefert auf Wunsch eine passende Groesse - 2x Kartenbreite reicht fuer scharfe Anzeige.
function thumb(url, width = 336) {
  if (!url) return '';
  return url.includes('cdn1.epicgames.com') && !url.includes('?') ? `${url}?h=${Math.round(width * 4 / 3)}&w=${width}&resize=1&quality=medium` : url;
}

const state = { openLogs: new Set(), logs: {}, fabTab: 'library', local: null, view: 'home', library: null, fab: null, projects: null, thumbs: {}, fabProject: null, shown: 0, list: [] };
let api;

// Deutsche Texte sind die Uebersetzungs-Schluessel (siehe i18n.js)
const TITLES = { tools: 'Werkzeuge', crashes: 'Abstürze', cleanup: 'Speicher aufräumen', account: 'Konto verwalten', home: 'Übersicht', games: 'Spiele', unreal: 'Unreal Engine', projects: 'UE-Projekte', fab: 'Fab-Bibliothek', store: 'Store', downloads: 'Downloads', settings: 'Einstellungen' };
const FAB_ACTION = { ASSET_PACK: 'Zum Projekt', CODE_PLUGIN: 'In Engine', COMPLETE_PROJECT: 'Als Projekt' };
const STATUS = { queued: 'Wartet', running: 'Läuft', paused: 'Pausiert', done: 'Fertig', failed: 'Fehler', cancelled: 'Abgebrochen' };
const OPEN = ['queued', 'running', 'paused'];
let jobs = [];

function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), 4000);
}

// Rueckfrage im Launcher-Design statt des Browser-Fensters ("127.0.0.1 says").
// Erster Absatz = Frage, Rest = Erklaerung. Antwort: true/false.
// Mit input: { value } gibt es ein Eingabefeld; Antwort: der Text oder null.
function askConfirm(message, { ok = 'OK', cancel = 'Abbrechen', danger = false, input = null } = {}) {
  const [title, ...rest] = message.split('\n\n');
  $('#ask-title').textContent = title;
  $('#ask-body').innerHTML = rest.map((para) => `<p>${esc(para).replace(/\n/g, '<br>')}</p>`).join('');
  const yes = $('#ask-ok');
  const no = $('#ask-cancel');
  yes.textContent = t(ok);
  no.textContent = t(cancel);
  yes.className = danger ? 'btn danger' : 'btn';
  const dlg = $('#askdlg');
  const field = $('#ask-input');
  field.hidden = !input;
  field.value = input?.value || '';
  const before = document.activeElement;
  dlg.hidden = false;
  if (input) { field.focus(); field.select(); } else (danger ? no : yes).focus(); // bei Riskantem steht der Fokus auf dem sicheren Knopf
  return new Promise((resolve) => {
    const done = (answer) => {
      dlg.hidden = true;
      dlg.onkeydown = yes.onclick = no.onclick = dlg.onclick = null;
      before?.focus?.();
      resolve(input ? (answer ? field.value : null) : answer);
    };
    yes.onclick = () => done(true);
    no.onclick = () => done(false);
    dlg.onclick = (e) => { if (e.target === dlg) done(false); };
    dlg.onkeydown = (e) => {
      if (e.key === 'Escape') done(false);
      if (input && e.key === 'Enter' && e.target === field) done(true);
      if (!input && e.key === 'Tab') { e.preventDefault(); (document.activeElement === yes ? no : yes).focus(); }
    };
  });
}

// Fenster schliessen, waehrend Downloads laufen (Aufruf aus main.py)
window.askClose = async () => {
  if (!$('#askdlg').hidden) return;
  if (state.view === 'store' || state.view === 'account') await show('downloads'); // der Store liegt sonst ueber dem Dialog
  const sure = await askConfirm(`${t('Downloads laufen noch')}\n\n${t('Beim Schließen wird der Download pausiert. Nach dem nächsten Start kannst du ihn unter „Downloads“ an derselben Stelle fortsetzen.')}`,
    { ok: 'Trotzdem schließen', cancel: 'Zurück' });
  if (sure) call('close_app');
};

// Fehler der Oberflaeche ins Debug-Protokoll (das Backend speichert sie nur mit debug.flag)
let uiErrors = 0;
function reportUiError(kind, text) {
  if (uiErrors++ > 50 || !api) return;
  try { Promise.resolve(api.debug_event(kind, String(text).slice(0, 2000))).catch(() => {}); } catch { /* egal */ }
}
window.addEventListener('error', (e) => reportUiError('error', `${e.message} @ ${e.filename}:${e.lineno}`));
window.addEventListener('unhandledrejection', (e) => reportUiError('promise', e.reason?.stack || e.reason));

async function call(name, ...args) {
  const res = await api[name](...args);
  if (res && res.error) throw new Error(res.error);
  return res;
}

function ago(ts) {
  if (!ts) return '';
  const min = Math.round((Date.now() / 1000 - ts) / 60);
  if (min < 1) return t('gerade eben');
  if (min < 60) return t('vor {n} Min.', { n: min });
  if (min < 1440) return t('vor {n} Std.', { n: Math.round(min / 60) });
  const days = Math.round(min / 1440);
  return days === 1 ? t('gestern') : t('vor {n} Tagen', { n: days });
}

// --- Sprache & Spiele-Bereich ----------------------------------------------
async function setLanguage(lang) {
  LANG = lang;
  await call('set_language', lang);
  applyStatic();
}

// Der Launcher ist aufs Arbeiten ausgerichtet - der Spiele-Bereich laesst sich ausblenden
function applyGamesVisibility(visible) {
  $('.nav[data-view="games"]').hidden = !visible;
  if (!visible && state.view === 'games') show('home');
}

// --- Anmeldung -----------------------------------------------------------
async function refreshAccount() {
  const acc = await call('account');
  $('#acc-dot').classList.toggle('on', acc.loggedIn);
  $('#acc-name').textContent = acc.loggedIn ? acc.name : t('Nicht angemeldet');
  $('#acc-open').title = acc.loggedIn ? acc.name : ''; // lange Namen werden abgeschnitten
  $('#acc-open').disabled = !acc.loggedIn;
  $('#acc-manage').hidden = $('#acc-arrow').hidden = $('#acc-logout').hidden = !acc.loggedIn;
  $('#login').hidden = acc.loggedIn;
  return acc.loggedIn;
}

$('#login-open').onclick = () => call('open_login_page');
$('#login-start').onclick = async () => {
  $('#login-error').textContent = '';
  $('#login-status').textContent = t('Anmeldefenster ist offen – bitte dort anmelden …');
  await call('start_login');
};

// Rueckruf aus dem Anmeldefenster (main.py start_login), sobald Epic den Code geliefert hat
window.onEpicLogin = async (res) => {
  if (!res || !res.ok) {
    $('#login-error').textContent = (res && res.error) || t('Anmeldung fehlgeschlagen – bitte erneut versuchen.');
    $('#login-status').textContent = t('Es öffnet sich Epics Anmeldefenster. Dein Passwort geht nur an Epic – diese App sieht es nie.');
    return;
  }
  await refreshAccount();
  const s = await call('settings');
  show(s.showGames ? 'games' : 'unreal');
  autoCheckUpdates(true);
};
$('#login-send').onclick = async () => {
  $('#login-error').textContent = '';
  const res = await call('login', $('#login-text').value);
  $('#login-text').value = '';
  if (!res.ok) { $('#login-error').textContent = res.error; return; }
  await refreshAccount();
  show(state.view);
};
$('#acc-logout').onclick = async () => {
  if (state.view === 'store' || state.view === 'account') await show('downloads'); // das Browser-Element laege sonst ueber der Anmeldung
  await call('logout');
  state.library = state.fab = state.projects = null;
  $('#content').innerHTML = '';
  refreshAccount();
};

// --- Daten ---------------------------------------------------------------
async function loadLibrary(refresh = false) {
  if (!state.library || refresh) state.library = await call('library', refresh);
  return state.library;
}

function rebuildEngineFilter() {
  if (!state.fab) return;
  const sel = $('#filter-engine');
  const current = sel.value;
  const engines = [...new Set(state.fab.items.flatMap((i) => i.engines))]
    .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
  sel.innerHTML = `<option value="">${esc(t('Alle UE-Versionen'))}</option>` +
    engines.map((e) => `<option>${esc(e)}</option>`).join('');
  sel.value = current;
}

async function loadProjects(refresh = false) {
  if (!state.projects || refresh) state.projects = await call('projects', refresh);
  return state.projects;
}

function fabCategoryOf(a) { return a.categories[0] || ''; }

function rebuildFabFilters() {
  if (!state.fab) return;
  const items = state.fab.items;
  const typeSel = $('#filter-type');
  const catSel = $('#filter-cat');
  const curType = typeSel.value;
  const curCat = catSel.value;
  const count = (list, key) => list.reduce((m, a) => { const k = key(a); if (k) m.set(k, (m.get(k) || 0) + 1); return m; }, new Map());
  const opts = (map) => [...map].sort((x, y) => x[0].localeCompare(y[0])).map(([k, n]) => `<option value="${esc(k)}">${esc(k)} (${n})</option>`).join('');
  typeSel.innerHTML = `<option value="">${esc(t('Alle Typen'))}</option>${opts(count(items, (a) => a.type))}`;
  typeSel.value = curType;
  if (typeSel.value !== curType) typeSel.value = '';
  const inType = items.filter((a) => !typeSel.value || a.type === typeSel.value);
  catSel.innerHTML = `<option value="">${esc(t('Alle Kategorien'))}</option>${opts(count(inType, fabCategoryOf))}`;
  catSel.value = curCat;
  if (catSel.value !== curCat) catSel.value = '';
}

const newestEngine = (a) => a.engines.reduce((m, e) => (e.localeCompare(m, undefined, { numeric: true }) > 0 ? e : m), '');
const FAB_SORT = {
  title: (x, y) => x.title.localeCompare(y.title),
  category: (x, y) => (x.type || '').localeCompare(y.type || '') || fabCategoryOf(x).localeCompare(fabCategoryOf(y)) || x.title.localeCompare(y.title),
  seller: (x, y) => (x.seller || '').localeCompare(y.seller || '') || x.title.localeCompare(y.title),
  engine: (x, y) => newestEngine(y).localeCompare(newestEngine(x), undefined, { numeric: true }) || x.title.localeCompare(y.title),
};

async function loadFab(refresh = false) {
  if (!state.fab || refresh) {
    state.fab = await call('fab', refresh);
    state.cached = new Set(state.fab.epicCached || []); // schon in Epics Vault-Cache
    rebuildEngineFilter();
    rebuildFabFilters();
  }
  return state.fab;
}

// installierbar = direkt ladbar ODER schon in Epics Vault-Cache
const versionUsable = (v) => v.downloadable || state.cached?.has(v.artifactId);

// --- Ansichten -----------------------------------------------------------
function matches(text) {
  const q = $('#search').value.trim().toLowerCase();
  return !q || text.toLowerCase().includes(q);
}

function stateFilter(item) {
  const f = $('#filter-state').value;
  return !f || (f === 'installed' && item.installed) || (f === 'update' && item.updateAvailable);
}

function busy(appName) {
  return jobs.find((j) => j.appName === appName && OPEN.includes(j.status));
}

// Knoepfe je Zustand - gleich fuer Spiele, Engines und DevKits
function itemActions(i, extra = '', tile = false) {
  const app = esc(i.appName);
  const job = busy(i.appName);
  if (job) return `<button class="btn ghost small" data-view-go="downloads">${esc(t(STATUS[job.status]))} · ${Math.floor(job.progress)} %</button>`;
  if (!i.installed) return `<button class="btn small" data-install="${app}">${esc(t('Installieren'))}</button>`;
  // in der Box sitzen Update (neben dem Namen) und Entfernen (X oben rechts) woanders
  return (i.updateAvailable && !tile ? `<button class="btn small" data-update="${app}">${esc(t('Update'))}</button>` : '') + extra +
    (i.kind !== 'game' ? `<button class="btn ghost small" data-options="${app}">${esc(t('Optionen'))}</button>` : '') +
    `<button class="btn ghost small" data-folder="${esc(i.path)}">${esc(t('Ordner'))}</button>` +
    `<button class="btn ghost small" data-repair="${app}" title="${esc(t('Dateien prüfen und defekte neu laden'))}">${esc(t('Prüfen'))}</button>` +
    (tile ? '' : `<button class="btn danger small" data-uninstall="${app}" data-title="${esc(i.title)}">${esc(t('Entfernen'))}</button>`);
}

// --- DLCs: haengen am Spiel; ohne Spiel nicht installierbar ------------------------
function dlcsOf(appName) {
  return (state.library?.items || []).filter((i) => i.kind === 'dlc' && i.parent === appName);
}

function dlcLink(g) {
  const list = dlcsOf(g.appName);
  if (!list.length) return '';
  const inst = list.filter((d) => d.installed).length;
  const upd = list.some((d) => d.installed && d.updateAvailable);
  return `<button class="link dlc-link" data-dlcs="${esc(g.appName)}">${esc(t('DLCs: {i} von {n} installiert', { i: inst, n: list.length }))}${upd ? ` · ${esc(t('Update'))}` : ''}</button>`;
}

function openDlcs(appName) {
  const game = state.library?.items.find((i) => i.appName === appName);
  if (!game) return;
  const list = dlcsOf(appName).sort((a, b) => a.title.localeCompare(b.title));
  const dlg = $('#dlcdlg');
  $('#dlc-title').textContent = t('DLCs – {title}', { title: game.title });
  const row = (d) => {
    const job = busy(d.appName);
    let state_ = d.installed ? t('Installiert') : t('Nicht installiert');
    let btns = '';
    if (job) state_ = `${t(STATUS[job.status])} · ${Math.floor(job.progress)} %`;
    else if (!game.installed) btns = '';
    else if (!d.installed) btns = `<button class="btn small" data-dlc-install="${esc(d.appName)}">${esc(t('Installieren'))}</button>`;
    else {
      btns = (d.updateAvailable ? `<button class="btn small" data-dlc-update="${esc(d.appName)}">${esc(t('Update'))}</button>` : '')
        + `<button class="btn ghost small" data-dlc-remove="${esc(d.appName)}" data-title="${esc(d.title)}">${esc(t('Entfernen'))}</button>`;
    }
    return `<div class="dlc-row"><span class="dlc-name" title="${esc(d.title)}">${esc(d.title)}</span>
      <span class="dlc-state${d.installed ? ' ok' : ''}">${esc(state_)}</span><span class="dlc-btns">${btns}</span></div>`;
  };
  $('#dlc-body').innerHTML = `${game.installed ? '' : `<p class="note">${esc(t('Installiere zuerst das Spiel – seine DLCs werden dann automatisch mitinstalliert.'))}</p>`}
    <div class="dlc-list">${list.map(row).join('')}</div>`;
  const missing = list.filter((d) => !d.installed && !busy(d.appName));
  $('#dlc-all').hidden = !game.installed || !missing.length;
  const refresh = async () => { await pollDownloads.once(); openDlcs(appName); };
  const run = async (fn) => { try { await fn(); } catch (err) { toast(err.message); } await refresh(); };
  $('#dlc-all').onclick = () => run(async () => { for (const d of missing) await call('install', d.appName); toast(t('Zur Warteschlange hinzugefügt.')); });
  dlg.querySelectorAll('[data-dlc-install]').forEach((b) => { b.onclick = () => run(() => call('install', b.dataset.dlcInstall)); });
  dlg.querySelectorAll('[data-dlc-update]').forEach((b) => { b.onclick = () => run(() => call('update', b.dataset.dlcUpdate)); });
  dlg.querySelectorAll('[data-dlc-remove]').forEach((b) => {
    b.onclick = async () => {
      if (!(await askConfirm(t('„{title}“ wirklich entfernen?', { title: b.dataset.title }), { ok: 'Entfernen', danger: true }))) return;
      run(() => call('uninstall', b.dataset.dlcRemove));
    };
  });
  $('#dlc-close').onclick = () => { dlg.hidden = true; };
  dlg.hidden = false;
}

function gameCard(g) {
  const job = busy(g.appName);
  const badge = g.installed ? `<span class="badge ok">${esc(t('Installiert'))}</span>` : '';
  const img = g.image ? `<img src="${esc(thumb(g.image))}" loading="lazy" decoding="async" alt="">` : '';
  const remove = g.installed && !job ? `<button class="tile-x" data-uninstall="${esc(g.appName)}" data-title="${esc(g.title)}" title="${esc(t('Entfernen'))}" aria-label="${esc(t('{title} entfernen', { title: g.title }))}">✕</button>` : '';
  const update = g.installed && g.updateAvailable && !job ? `<button class="btn small" data-update="${esc(g.appName)}">${esc(t('Update'))}</button>` : '';
  const start = g.installed && !job ? `<button class="btn small" data-start="${esc(g.appName)}" data-title="${esc(g.title)}">${esc(t('Starten'))}</button>` : '';
  return `<article class="card" data-app="${esc(g.appName)}">
    <div class="img">${img}${badge}${remove}</div>
    <div class="body">
      <div class="tile-name"><div class="title" title="${esc(g.title)}">${esc(g.title)}</div>${update}</div>
      ${g.developer ? `<div class="sub">${esc(g.developer)}</div>` : ''}
      ${dlcLink(g)}
      <div class="actions${start ? ' game-actions' : ''}">${itemActions(g, start, true)}</div>
    </div></article>`;
}

function fabCard(a) {
  const img = a.image ? `<img src="${esc(a.image)}" loading="lazy" decoding="async" alt="">` : '';
  const engines = a.engines.slice(-3).map((e) => `<span class="chip">${esc(e.replace('UE_', ''))}</span>`).join('');
  const usable = a.versions.some(versionUsable);
  const badge = a.downloadable ? ''
    : usable ? `<span class="badge ok">${esc(t('Im Epic-Cache'))}</span>`
      : `<span class="badge">${esc(t('Nur im Editor'))}</span>`;
  return `<article class="card">
    <div class="img">${img}${badge}</div>
    <div class="body">
      <div class="title" title="${esc(a.title)}">${esc(a.title)}</div>
      <div class="sub">${esc(a.seller || '')}</div>
      <div class="cat">${a.type ? `<button class="link" data-fab-type="${esc(a.type)}">${esc(a.type)}</button>` : ''}${fabCategoryOf(a) ? ` › <button class="link" data-fab-cat="${esc(fabCategoryOf(a))}" data-fab-cat-type="${esc(a.type || '')}">${esc(fabCategoryOf(a))}</button>` : ''}</div>
      <div class="chips">${engines}</div>
      <div class="actions">
        ${usable && FAB_ACTION[a.kind] ? `<button class="btn small" data-fab="${esc(a.id)}">${esc(t(FAB_ACTION[a.kind]))}</button>` : ''}
        <button class="btn ghost small" data-url="${esc(a.url)}">${esc(t('Auf Fab'))}</button>
      </div>
    </div></article>`;
}

function projectCard(p) {
  const thumb = state.thumbs[p.uproject];
  const img = thumb ? `<img src="${esc(thumb)}" alt="">`
    : `<span class="initial">${esc(p.displayName.slice(0, 1).toUpperCase())}</span>`;
  const when = p.lastOpened ? t('Zuletzt geöffnet {ago}', { ago: ago(p.lastOpened) }) : t('Geändert {ago}', { ago: ago(p.modified) });
  const engine = p.engineLabel || t('Engine unbekannt ({a})', { a: p.association || '–' });
  const up = esc(p.uproject);
  return `<article class="card project" ${p.hasThumb && !thumb ? `data-thumb="${up}"` : ''}>
    <div class="img">${img}
      <div class="card-corner">
        <button class="corner-btn" data-hide-project="${up}" data-name="${esc(p.displayName)}" title="${esc(t('Nur aus dieser Liste nehmen. Das Projekt bleibt auf der Festplatte.'))}">${esc(t('Ausblenden'))}</button>
        ${p.deleteBlock ? '' : `<button class="corner-btn danger" data-delete-project="${up}" title="${esc(t('Projektordner von der Festplatte in den Papierkorb verschieben'))}">${esc(t('Projekt löschen'))}</button>`}
      </div></div>
    <div class="body">
      <div class="title-row"><div class="title" title="${esc(p.description || p.displayName)}">${esc(p.displayName)}</div>
        <button class="tile-edit" data-rename-project="${up}" title="${esc(t('Anzeigename ändern'))}" aria-label="${esc(t('Anzeigename ändern'))}">✎</button></div>
      <div class="sub">${p.displayName !== p.name ? `${esc(p.name)} · ` : ''}${esc(engine)}</div>
      <div class="path" title="${up}">${esc(p.dir)}</div>
      <div class="sub">${esc(when)}</div>
      <div class="actions">
        ${p.canOpen ? `<button class="btn small" data-open-project="${up}">${esc(t('Öffnen'))}</button>`
          : `<button class="btn ghost small" data-open-project="${up}" title="${esc(t('Passende Engine nicht gefunden – Windows fragt nach der Engine.'))}">${esc(t('Öffnen …'))}</button>`}
        <button class="btn ghost small" data-project-assets="${up}" title="${esc(t('Fab-Assets zu diesem Projekt hinzufügen'))}">${esc(t('Assets'))}</button>
        <button class="btn ghost small" data-folder="${esc(p.dir)}">${esc(t('Ordner'))}</button>
      </div>
    </div></article>`;
}

// Vorschaubilder nachladen (liegen als Datei im Projekt, kommen als data:-URL)
async function loadThumbs() {
  for (const card of document.querySelectorAll('#content [data-thumb]')) {
    const key = card.dataset.thumb;
    card.removeAttribute('data-thumb');
    try {
      const { url } = await call('project_thumb', key);
      if (!url) continue;
      state.thumbs[key] = url;
      (card.querySelector('.img') || card).innerHTML = `<img src="${esc(url)}" alt="">`;
    } catch { /* ohne Bild weiter */ }
  }
}

// --- Fab: lokal gespeicherte Assets (Vault) ansehen und loeschen ----------------
function fabTabs() {
  const tab = (k, label) => `<button class="tab ${state.fabTab === k ? 'active' : ''}" data-fab-tab="${k}">${esc(t(label))}</button>`;
  return `<div class="tabs fab-tabs">${tab('library', 'Bibliothek')}${tab('local', 'Lokal gespeichert')}</div>`;
}

const engineRange = (list) => {
  const e = (list || []).map(engineLabel);
  return e.length > 1 ? `${e[0]} – ${e[e.length - 1].replace('UE ', '')}` : (e[0] || '');
};

function localTile(a) {
  const art = a.image ? `<img src="${esc(a.image)}" loading="lazy" decoding="async" alt="">`
    : `<span class="initial">${esc(a.title.slice(0, 1).toUpperCase())}</span>`;
  const badge = a.incomplete ? `<span class="badge">${esc(t('Unvollständig'))}</span>`
    : a.redownload ? '' : `<span class="badge">${esc(t('Nicht neu ladbar'))}</span>`;
  const place = t(a.where === 'epic' ? 'Epics Vault-Cache' : 'Behaltenes Asset');
  const usable = a.assetId && FAB_ACTION[a.kind] && !a.incomplete;
  return `<article class="tile">
    <div class="img">${art}${badge}<button class="tile-x" data-del-local="${esc(a.key)}" title="${esc(t('Löschen'))}" aria-label="${esc(t('{title} löschen', { title: a.title }))}">✕</button></div>
    <div class="tile-body"><div class="tile-name"><div class="tile-title" title="${esc(a.title)}">${esc(a.title)}</div><span class="tile-size">${esc(mb(a.sizeMb))}</span></div>
      <div class="tile-sub">${esc([engineRange(a.engines), place].filter(Boolean).join(' · '))}</div>
      <div class="actions">${usable ? `<button class="btn small" data-fab="${esc(a.assetId)}">${esc(t(FAB_ACTION[a.kind]))}</button>` : ''}
        <button class="btn ghost small" data-folder="${esc(a.path)}">${esc(t('Ordner'))}</button></div></div></article>`;
}

async function renderLocal() {
  if (!state.local) {
    $('#meta').textContent = '';
    $('#content').innerHTML = `${fabTabs()}<p class="loading">${esc(t('Lese lokale Assets …'))}</p>`;
    state.local = (await call('local_assets')).items;
    if (state.view !== 'fab' || state.fabTab !== 'local') return;
  }
  const items = state.local.filter((a) => matches(`${a.title} ${a.seller} ${a.name}`));
  const total = state.local.reduce((sum, a) => sum + a.sizeMb, 0);
  $('#meta').textContent = t('{n} Assets · {size} belegt', { n: state.local.length, size: mb(total) });
  $('#content').innerHTML = `${fabTabs()}
    <p class="local-note">${esc(t('Downloads im Zwischenspeicher, aus denen Assets in Projekte kopiert werden. Löschen betrifft nur diesen Speicher – nie Engines, DevKits oder Projekte.'))}</p>
    ${items.length ? `<div class="items">${items.map(localTile).join('')}</div>` : `<p class="home-empty">${esc(t(state.local.length ? 'Nichts gefunden.' : 'Keine lokal gespeicherten Assets.'))}</p>`}`;
}

async function deleteLocal(key) {
  const a = state.local.find((x) => x.key === key);
  if (!a) return;
  const why = a.incomplete ? t('Das ist ein abgebrochener Download, er ist nicht nutzbar.')
    : a.redownload ? t('Das Asset lässt sich jederzeit neu laden.')
      : a.assetId ? t('Achtung: Der Launcher kann dieses Asset nicht selbst neu laden. Das geht danach nur noch über das Fab-Plugin im Editor.')
        : t('Achtung: Dieses Asset steht nicht in deiner Fab-Bibliothek und lässt sich danach evtl. nicht mehr laden.');
  const sure = await askConfirm(`${t('„{title}“ löschen?', { title: a.title })}\n\n${why}\n\n${t('{size} werden endgültig gelöscht, nicht in den Papierkorb. Projekte, in die das Asset schon kopiert wurde, sind nicht betroffen.', { size: mb(a.sizeMb) })}`,
    { ok: 'Löschen', danger: true });
  if (!sure) return;
  const res = await call('delete_local_asset', key);
  toast(t('„{title}“ gelöscht – {size} frei.', { title: a.title, size: mb(res.sizeMb || 0) }));
  state.local = null;
  state.fab = null; // Kennzeichnung "Im Epic-Cache" neu einlesen
  await render();
}

// --- Startseite: Bausteine ----------------------------------------------------
const LOCALES = { de: 'de-DE', en: 'en-US', fr: 'fr-FR', es: 'es-ES', it: 'it-IT', pl: 'pl-PL', pt: 'pt-PT', nl: 'nl-NL' };
const locale = () => LOCALES[LANG] || 'en-US';

function money(value, currency) {
  if (value == null || !currency) return '';
  return new Intl.NumberFormat(locale(), { style: 'currency', currency }).format(value);
}

function shortDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(locale(), { day: 'numeric', month: 'short' });
}

const shortVersion = (v) => (v || '').split('+')[0].split('-')[0];

function updateCard(u) {
  const version = u.title.match(/\d+\.\d+/);
  const art = u.image ? `<img src="${esc(thumb(u.image, 336))}" loading="lazy" decoding="async" alt="">`
    : `<span class="engine-art small">${esc(version ? version[0] : '')}</span>`;
  return `<div class="status-update">
    <div class="status-art">${art}</div>
    <div class="status-text"><div class="tile-title" title="${esc(u.title)}">${esc(u.title)}</div>
      <div class="tile-sub" title="${esc(shortVersion(u.version))} → ${esc(shortVersion(u.latest))}">${esc(shortVersion(u.version))} → ${esc(shortVersion(u.latest))}</div></div>
    <button class="btn small" data-update="${esc(u.appName)}">${esc(t('Update'))}</button></div>`;
}

function assetUpdateCard(a) {
  return `<div class="status-update">
    <div class="status-text"><div class="tile-title" title="${esc(a.title)}">${esc(a.title)}</div>
      <div class="tile-sub">${esc(a.local)} → ${esc(a.current)}</div></div>
    <button class="btn ghost small" data-go-asset="${esc(a.title)}">${esc(t('Zum Asset'))}</button></div>`;
}

// Neue Version des Launchers selbst (GitHub-Release)
function selfUpdateCard(s) {
  const action = s.canInstall
    ? `<button class="btn small" data-self-update="1">${esc(t('Update'))}</button>`
    : s.page ? `<button class="btn ghost small" data-url="${esc(s.page)}">${esc(t('Auf GitHub'))}</button>` : '';
  return `<div class="status-update">
    <div class="status-art"><img class="mark" src="siccora-mark.svg" alt=""></div>
    <div class="status-text"><div class="tile-title">Siccora Launcher</div>
      <div class="tile-sub">${esc(s.current)} → ${esc(s.latest)}</div></div>
    ${action}</div>`;
}

function renderVersion() {
  const s = state.self;
  const el = $('#app-version');
  if (!s) return;
  el.hidden = false;
  el.textContent = `v${s.current}`;
  el.classList.toggle('has-update', !!s.available);
  el.title = s.available ? t('Update auf {v} verfügbar', { v: s.latest }) : t('Siccora Launcher ist aktuell');
}

async function checkSelfUpdate(force = false) {
  try { state.self = await call('self_update', force); } catch { /* offline - beim naechsten Mal */ }
  renderVersion();
}

// Vor dem Update zeigen, was neu ist (Patch Notes aus dem GitHub-Release, in der Launcher-Sprache)
function openSelfUpdate() {
  const s = state.self;
  const notes = (s.notes && (s.notes[LANG] || s.notes.en)) || [];
  const running = jobs.some((j) => j.status === 'running' || j.status === 'queued');
  $('#update-heading').textContent = `Siccora Launcher ${s.latest}`;
  $('#update-versions').textContent = t('Installiert: {v}', { v: s.current });
  $('#update-notes').innerHTML = notes.length
    ? `<ul class="update-notes">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>`
    : `<p class="home-empty">${esc(t('Für diese Version gibt es keine Beschreibung.'))}</p>`;
  $('#update-info').textContent = t('Das Update wird geladen und geprüft. Danach schließt sich der Launcher kurz und startet von selbst neu.')
    + (running ? ` ${t('Laufende Downloads werden pausiert und lassen sich danach fortsetzen.')}` : '');
  $('#update-go').disabled = false;
  $('#updatedlg').hidden = false;
}

$('#update-close').onclick = () => ($('#updatedlg').hidden = true);
$('#update-go').onclick = async () => {
  $('#update-go').disabled = true;
  $('#update-close').disabled = true;
  $('#update-progress').hidden = false;
  $('#update-info').hidden = true;
  $('#update-step').textContent = t('Lade Update …');
  let running = true;
  (async () => {  // Fortschritt sichtbar machen - sonst wirkt ein langsamer Download wie ein Haenger
    while (running) {
      try { paintSelfUpdate(await call('self_update_progress')); } catch { /* naechster Versuch */ }
      await new Promise((r) => setTimeout(r, 500));
    }
  })();
  try {
    await call('install_self_update');
  } catch (err) {
    toast(err.message);
    $('#update-go').disabled = $('#update-close').disabled = false;
    $('#update-progress').hidden = true;
    $('#update-info').hidden = false;
  } finally { running = false; }
};

function paintSelfUpdate(p) {
  if (p.phase === 'download') {
    $('#update-fill').style.width = `${p.total ? Math.min(100, (p.done / p.total) * 100) : 0}%`;
    $('#update-step').textContent = t('Lade Update … {done} von {total}', { done: mb(p.done / 1048576), total: mb(p.total / 1048576) })
      + (p.attempt > 1 ? ` · ${t('Langsame Verbindung – neuer Versuch {n} von {m}', { n: p.attempt, m: p.attempts })}` : '');
  } else if (p.phase === 'verify') {
    $('#update-fill').style.width = '100%';
    $('#update-step').textContent = t('Prüfe Signatur und Prüfsumme …');
  } else if (p.phase === 'install') {
    $('#update-step').textContent = t('Starte Installation – der Launcher startet gleich neu …');
  }
}

function statusUpdates(h) {
  const self = state.self?.available ? 1 : 0;
  const n = h.updates.length + h.assetUpdates.length + self;
  const body = state.checking && !n ? `<p class="status-empty">${esc(t('Suche nach Updates …'))}</p>`
    : n ? (self ? selfUpdateCard(state.self) : '') + h.updates.map(updateCard).join('') + h.assetUpdates.map(assetUpdateCard).join('')
      : `<p class="status-empty ok">${esc(t('Alles aktuell'))}</p>`;
  return `<section class="status-box ${n ? 'has-updates' : ''}">
    <div class="home-head"><h2>${esc(t('Updates'))}${n ? ` <span class="count">${n}</span>` : ''}</h2>
      <button class="link" data-check-updates="1" ${state.checking ? 'disabled' : ''}>${esc(t('Jetzt prüfen'))}</button></div>
    ${body}
    ${h.libraryUpdated ? `<p class="status-note">${esc(t('Stand {ago}', { ago: ago(h.libraryUpdated) }))}</p>` : ''}</section>`;
}

async function loadStorage() {
  try {
    const s = await call('home_storage');
    const el = $('#status-storage');
    if (!el) return;
    el.innerHTML = s.drives.map((d) => `<div class="status-job">
        <div class="status-row"><span class="tile-title">${esc(d.drive)}</span><span class="tile-sub">${esc(t('{free} GB von {total} GB frei', { free: d.freeGb, total: d.totalGb }))}</span></div>
        <div class="track"><div class="fill ${d.usedPct >= 90 ? 'full' : ''}" style="width:${d.usedPct}%"></div></div></div>`).join('') +
      `<button class="status-link" data-go-local="1"><span>${esc(t('Fab-Downloads'))}</span><span class="tile-size">${esc(mb(s.vaultMb))}</span></button>`;
  } catch { /* Startseite funktioniert auch ohne */ }
}

function freeTile(a) {
  const img = a.image ? `<img src="${esc(a.image)}" loading="lazy" decoding="async" alt="">` : '';
  const foot = a.owned
    ? `<span class="owned">${esc(t('In deiner Bibliothek'))}</span>`
    : `${a.price ? `<s>${esc(money(a.price, a.currency))}</s>` : ''}<strong>${esc(t('Gratis'))}</strong>${a.until ? `<span>${esc(t('bis {date}', { date: shortDate(a.until) }))}</span>` : ''}`;
  return `<button class="tile free" data-url="${esc(a.url)}">
    <span class="img">${img}</span>
    <span class="tile-body"><span class="tile-title" title="${esc(a.title)}">${esc(a.title)}</span>
      <span class="tile-sub">${esc(a.seller)}</span><span class="tile-foot">${foot}</span></span></button>`;
}

function freeTiles(data) {
  if (data.items.length) return `<div class="tiles">${data.items.map(freeTile).join('')}</div>`;
  return `<p class="home-empty">${esc(t(data.failed ? 'Fab ist gerade nicht erreichbar.' : 'Gerade keine Gratis-Assets.'))}</p>`;
}

async function loadFree() {
  try {
    state.free = await call('free_assets');
    const el = $('#home-free');
    if (el) el.innerHTML = freeTiles(state.free);
  } catch { /* Startseite funktioniert auch ohne */ }
}

function launchTile(r) {
  const version = r.title.match(/\d+\.\d+/);
  const art = r.image ? `<img src="${esc(thumb(r.image, 800))}" loading="lazy" decoding="async" alt="">`
    : `<span class="engine-art"><small>Unreal Engine</small>${esc(version ? version[0] : '')}</span>`;
  return `<article class="tile" data-app="${esc(r.appName)}">
    <div class="img">${art}</div>
    <div class="tile-body"><div class="tile-title" title="${esc(r.title)}">${esc(r.title)}</div>
      <div class="tile-row"><span class="tile-sub">${esc(ago(r.time))}</span>
        <button class="btn small" data-start="${esc(r.appName)}" data-title="${esc(r.title)}">${esc(t('Starten'))}</button></div></div></article>`;
}

function projectTile(p) {
  const url = state.thumbs[p.uproject];
  const when = p.lastOpened ? ago(p.lastOpened) : t('angelegt {ago}', { ago: ago(p.created) });
  return `<article class="tile" ${p.hasThumb && !url ? `data-thumb="${esc(p.uproject)}"` : ''}>
    <div class="img">${url ? `<img src="${esc(url)}" alt="">` : `<span class="initial">${esc(p.displayName.slice(0, 1).toUpperCase())}</span>`}</div>
    <div class="tile-body"><div class="tile-title" title="${esc(p.name)}">${esc(p.displayName)}</div>
      <div class="tile-row"><span class="tile-sub">${esc(p.engineLabel || p.association)} · ${esc(when)}</span>
        <button class="btn small" data-open-project="${esc(p.uproject)}">${esc(t('Öffnen'))}</button></div></div></article>`;
}

async function goToAsset(title) {
  state.fabTab = 'library';
  $('#filter-type').value = '';
  $('#filter-engine').value = '';
  rebuildFabFilters();
  $('#filter-cat').value = '';
  $('#search').value = title;
  await show('fab');
}

function itemTile(e) {
  const job = busy(e.appName);
  const badge = job ? `<span class="badge">${esc(t(STATUS[job.status]))}</span>` : '';
  const remove = e.installed && !job ? `<button class="tile-x" data-uninstall="${esc(e.appName)}" data-title="${esc(e.title)}" title="${esc(t('Entfernen'))}" aria-label="${esc(t('{title} entfernen', { title: e.title }))}">✕</button>` : '';
  const update = e.updateAvailable && e.installed && !job ? `<button class="btn small" data-update="${esc(e.appName)}">${esc(t('Update'))}</button>` : '';
  const version = e.title.match(/\d+\.\d+/);
  const art = e.image ? `<img src="${esc(thumb(e.image, 800))}" loading="lazy" decoding="async" alt="">`
    : `<span class="engine-art"><small>Unreal Engine</small>${esc(version ? version[0] : '')}</span>`;
  const info = e.installed ? [(e.version || '').split('+')[0], e.path].filter(Boolean).join(' · ') : t('Wird installiert …');
  const launch = e.installed && !job ? `<button class="btn small" data-start="${esc(e.appName)}" data-title="${esc(e.title)}">${esc(t('Starten'))}</button>` : '';
  return `<article class="tile" data-app="${esc(e.appName)}">
    <div class="img">${art}${badge}${remove}</div>
    <div class="tile-body"><div class="tile-name"><div class="tile-title" title="${esc(e.title)}">${esc(e.title)}</div>${update}</div>
      <div class="tile-sub" title="${esc(info)}">${esc(info)}</div>
      ${e.plugins?.length ? `<div class="tile-sub" title="${esc(e.plugins.join(', '))}">${esc(t('Plugins'))}: ${esc(e.plugins.join(', '))}</div>` : ''}
      <div class="actions">${itemActions(e, launch, true)}</div></div></article>`;
}

const mb = (v) => (v >= 1024 ? `${(v / 1024).toFixed(1)} GB` : `${Math.round(v)} MB`);

const n0 = (v) => Number(v || 0).toLocaleString(locale());

// Was gerade auf der Platte passiert - Pruefen liest, Laden schreibt
function activity(j) {
  if (j.phase === 'verify' && j.verifyTotal) {
    return t('Geprüft: {num} von {total} Dateien · Lesen {read} MB/s · Probleme: {bad}',
      { num: n0(j.verifyNum), total: n0(j.verifyTotal), read: (j.readSpeed || 0).toFixed(1), bad: n0(j.verifyBad) });
  }
  if (j.writeSpeed !== undefined) {
    const parts = [t('Geladen {a}', { a: mb(j.downloadedMb || 0) }), t('Geschrieben {a}', { a: mb(j.writtenMb || 0) }),
      t('Schreiben {w} MB/s · Lesen {r} MB/s', { w: (j.writeSpeed || 0).toFixed(1), r: (j.readSpeed || 0).toFixed(1) })];
    if (j.tasks !== undefined) parts.push(t('{n} aktive Aufgaben', { n: j.tasks }));
    if (j.verifyBad) parts.push(t('{n} Dateien werden repariert', { n: n0(j.verifyBad) }));
    return parts.join(' · ');
  }
  return t('Arbeitet … (Details unter „Aktivität“)');
}

function jobRow(j) {
  const size = j.downloadMb ? ` · ${t('{a} von {b}', { a: mb(j.downloadedMb), b: mb(j.downloadMb) })}` : '';
  const live = j.status === 'running' && j.progress > 0 && j.phase !== 'verify' ? ` · ${j.speed.toFixed(1)} MB/s · ${t('noch {eta}', { eta: j.eta })}` : '';
  const pausable = j.action !== 'uninstall';
  let btn = '';
  if (j.status === 'running' && pausable) btn = `<button class="btn ghost small" data-pause="${j.id}">${esc(t('Pause'))}</button>`;
  if (j.status === 'paused') btn = `<button class="btn small" data-resume="${j.id}">${esc(t('Fortsetzen'))}</button>`;
  if (j.status === 'failed') btn = `<button class="btn ghost small" data-resume="${j.id}">${esc(t('Erneut versuchen'))}</button>`;
  if (OPEN.includes(j.status) && (j.status !== 'running' || pausable)) {
    btn += `<button class="btn danger small" data-cancel="${j.id}" data-action="${esc(j.action)}">${esc(t('Abbrechen'))}</button>`;
  }
  const bar = (j.status === 'running' || j.status === 'paused') && pausable;
  const logOpen = state.openLogs.has(j.id);
  btn = `<button class="btn ghost small ${logOpen ? 'active' : ''}" data-log-toggle="${j.id}" title="${esc(t('Was der Launcher gerade tut'))}">${esc(t('Aktivität'))}</button>` + btn;
  return `<div class="job ${j.status}">
    <div><span class="name">${esc(j.title)}</span><span class="kind">${esc(j.label)} · ${esc(t(STATUS[j.status]))}</span></div>
    <div class="actions">${btn}</div>
    ${bar ? `<div class="track"><div class="fill" style="width:${j.progress}%"></div></div>` : ''}
    <div class="msg">${esc(j.message)}${bar ? esc(` ${Math.floor(j.progress)} %${j.phase === 'verify' ? '' : size}${j.status === 'running' ? live : ''}`) : ''}</div>
    ${j.status === 'running' ? `<div class="activity">${esc(activity(j))}</div>` : ''}
    ${logOpen ? `<pre class="joblog">${esc((state.logs[j.id] || []).join('\n') || t('Noch keine Ausgabe.'))}</pre>` : ''}
  </div>`;
}

// Fortschritt abfragen: schnell solange etwas laeuft, sonst selten
async function pollDownloads() {
  try {
    const before = jobs;
    jobs = (await call('downloads_list')).jobs;
    const active = jobs.filter((j) => j.status === 'queued' || j.status === 'running');
    const running = jobs.find((j) => j.status === 'running');
    const open = jobs.filter((j) => OPEN.includes(j.status));
    $('#dl-count').hidden = !open.length;
    $('#dl-count').textContent = open.length;
    $('#dl-mini').hidden = !running;
    if (running) {
      $('#dl-mini-title').textContent = `${running.title} · ${Math.floor(running.progress)} %`;
      $('#dl-mini-fill').style.width = `${running.progress}%`;
    }
    const finished = jobs.some((j) => {
      const old = before.find((o) => o.id === j.id);
      return old && old.status !== j.status && !OPEN.includes(j.status);
    });
    if (finished) {
      state.library = null; // Installationsstatus neu einlesen
      const last = jobs.filter((j) => ['done', 'failed'].includes(j.status)).pop();
      if (last) toast(t(last.status === 'done' ? '{title}: fertig' : '{title}: Fehler', { title: last.title }));
    }
    if (state.view === 'downloads') render();
    else if (finished && ['games', 'unreal', 'home'].includes(state.view)) render();
    setTimeout(pollDownloads, active.length || state.view === 'downloads' ? 1000 : 5000);
  } catch {
    setTimeout(pollDownloads, 5000);
  }
}

// --- Update-Vorschau: erst zeigen, was passieren wuerde, dann auf Wunsch starten
async function openPreview(appName) {
  const body = $('#preview-body');
  $('#preview').hidden = false;
  $('#preview-start').hidden = true;
  body.innerHTML = `<p class="loading">${esc(t('Vergleiche installierte Version mit der neuen … bei großen DevKits bis zu 2 Minuten.'))}</p>`;
  let p;
  try { p = await call('update_preview', appName); } catch (err) {
    body.innerHTML = `<p class="note bad">${esc(err.message)}</p>`;
    return;
  }
  // Klartext statt Technik: kurze Versionsnummern, echte Komponenten-Namen, ganze Saetze
  const short = (v) => String(v || '').split('+')[0];
  const onlyVersion = p.upToDate && p.oldVersion !== p.newVersion;
  const comps = p.components.length ? `${p.components.map(compName).join(', ')} – ${t('bleiben installiert')}` : t('keine');
  const files = [
    p.changed && t('{n} werden aktualisiert', { n: n0(p.changed) }),
    p.added && t('{n} kommen neu dazu', { n: n0(p.added) }),
    p.removed && t('{n} werden entfernt', { n: n0(p.removed) }),
  ].filter(Boolean).join(', ');
  const change = Math.abs(p.sizeChangeMb) < 1 ? t('kaum Änderung')
    : t(p.sizeChangeMb > 0 ? '{size} mehr belegt' : '{size} weniger belegt', { size: mb(Math.abs(p.sizeChangeMb)) });
  const lead = p.upToDate
    ? t(p.acknowledged ? 'Bereits aktuell. Epic führt für diesen Eintrag intern eine abweichende Versionsnummer – der Update-Hinweis wird ausgeblendet, bis eine wirklich neue Version erscheint.'
      : onlyVersion ? 'Es haben sich keine Dateien geändert, nur die Versionsnummer. Es wird nichts heruntergeladen, nur der Stand wird aktualisiert.'
        : 'Bereits aktuell – nichts zu tun.')
    : t('Das Update lädt {dl} herunter und bringt {title} auf Version {v}.', { dl: mb(p.downloadMb), title: p.title, v: short(p.newVersion) });
  const removed = p.removed
    ? `<div class="note${p.removed > 50 ? ' bad' : ''}">${esc(t('{n} Dateien gibt es in der neuen Version nicht mehr und werden entfernt.', { n: n0(p.removed) }))}
         ${esc(t('Deine eigenen Dateien (z. B. Mod-Projekte) sind nicht betroffen – entfernt wird nur, was Epic selbst installiert hat.'))}
         <details class="preview-files"><summary>${esc(t('Beispiele anzeigen'))}</summary>
         <ul>${p.removedSample.map((f) => `<li>${esc(f)}</li>`).join('')}${p.removed > p.removedSample.length ? '<li>…</li>' : ''}</ul></details></div>` : '';
  body.innerHTML = `
    <p class="preview-lead">${esc(lead)}</p>
    <dl class="facts">
      <dt>${esc(t('Was'))}</dt><dd>${esc(p.title)}</dd>
      <dt>${esc(t('Version'))}</dt><dd title="${esc(`${p.oldVersion} → ${p.newVersion}`)}">${esc(p.upToDate && !onlyVersion ? short(p.oldVersion) : `${short(p.oldVersion)} → ${short(p.newVersion)}`)}</dd>
      <dt>${esc(t('Ordner'))}</dt><dd>${esc(p.path)}</dd>
      ${p.upToDate ? '' : `
      <dt>${esc(t('Herunterladen'))}</dt><dd>${esc(mb(p.downloadMb))}</dd>
      <dt>${esc(t('Dateien'))}</dt><dd>${esc(files || t('keine Änderungen'))}</dd>
      <dt>${esc(t('Speicherplatz'))}</dt><dd>${esc(t('{change} · noch {free} frei', { change, free: mb(p.freeMb) }))}${p.enoughSpace ? '' : ` <strong class="bad-text">${esc(t('– zu wenig Platz!'))}</strong>`}</dd>`}
      <dt>${esc(t('Optionale Inhalte'))}</dt><dd>${esc(comps)}</dd>
    </dl>
    ${p.upToDate ? '' : removed}
    ${!p.upToDate && p.source === 'egl' ? `<p class="note">${esc(t('Wurde mit dem Epic Launcher installiert. Er bekommt den neuen Stand danach automatisch mitgeteilt.'))}</p>` : ''}`;
  // Neue Versionsnummer ohne geaenderte Dateien: das Update muss trotzdem laufen, sonst bleibt die Meldung stehen
  $('#preview-start').hidden = p.upToDate ? !onlyVersion : !p.enoughSpace;
  if (p.acknowledged) {  // Hinweis sofort aus Liste und Uebersicht nehmen
    const lib = state.library?.items.find((i) => i.appName === appName);
    if (lib) lib.updateAvailable = false;
    if (['games', 'unreal', 'home'].includes(state.view)) render();
  }
  $('#preview-start').onclick = async () => {
    $('#preview').hidden = true;
    await call('update', appName);
    toast(t('Update in der Warteschlange.'));
    await pollDownloads.once();
  };
}
$('#preview-close').onclick = () => ($('#preview').hidden = true);

// --- Optionen: optionale Komponenten waehlen (wie im Epic Launcher) ----------
const COMPONENT_NAMES = {
  textures: 'Hochauflösende Texturen', TheCenter: 'The Center', LostColony: 'Lost Colony',
  ScorchedEarth: 'Scorched Earth', engine_source: 'Engine-Quellcode', templates: 'Templates & Feature Packs',
  starter_content: 'Starter Content', editor_symbols: 'Editor-Symbole zum Debuggen', metahuman_content: 'MetaHuman-Inhalte',
};
function compName(tag) {
  if (COMPONENT_NAMES[tag]) return t(COMPONENT_NAMES[tag]);
  if (tag.startsWith('platform_')) return t('Zielplattform {p}', { p: tag.slice(9) });
  return tag;
}
const bytes = (b) => mb(b / 1048576);
const optDlg = { app: null, data: null };

// gleiche Regel wie backend/components.summarize - nur fuer die Anzeige
function optSummary(selected) {
  const d = optDlg.data;
  const sel = new Set(selected);
  const inst = new Set(d.components.filter((c) => c.installed).map((c) => c.tag));
  const removed = [...inst].filter((x) => !sel.has(x));
  const added = selected.filter((x) => !inst.has(x));
  const touches = (g, set) => g.tags.some((x) => set.has(x));
  const gone = d.groups.filter((g) => touches(g, new Set(removed)) && !touches(g, sel));
  // bleiben stehen, weil eine weiterhin gewaehlte Komponente sie mitbenutzt
  const shared = d.groups.filter((g) => touches(g, new Set(removed)) && touches(g, sel));
  const download = added.length ? d.baseMissing + d.groups.filter((g) => touches(g, sel)).reduce((s, g) => s + g.missingSize, 0) : 0;
  const required = d.baseSize + d.groups.filter((g) => touches(g, sel)).reduce((s, g) => s + g.presentSize + g.missingSize, 0);
  return { added, removed, download, required,
    freed: gone.reduce((s, g) => s + g.presentSize, 0), files: gone.reduce((s, g) => s + g.present, 0),
    sharedFiles: shared.reduce((s, g) => s + g.present, 0), sharedSize: shared.reduce((s, g) => s + g.presentSize, 0) };
}

function selectedComponents() {
  return [...document.querySelectorAll('#opt-body input[data-tag]:checked')].map((el) => el.dataset.tag);
}

function renderOptSummary() {
  const s = optSummary(selectedComponents());
  document.querySelectorAll('#opt-body .opt-row').forEach((row) => {
    const tag = row.querySelector('input').dataset.tag;
    row.classList.toggle('changed', s.added.includes(tag) || s.removed.includes(tag));
  });
  const item = state.library?.items.find((i) => i.appName === optDlg.app);
  $('#opt-summary').innerHTML = `
    <span>${esc(t('Download (unkomprimiert, höchstens)'))}</span><strong>${bytes(s.download)}</strong>
    <span>${esc(t('Wird frei'))}</span><strong>${bytes(s.freed)}${s.files ? ` · ${esc(t('{n} Dateien', { n: s.files }))}` : ''}</strong>
    <span>${esc(t('Benötigter Speicher'))}</span><strong>${bytes(s.required)}</strong>
    <span>${esc(t('Frei auf dem Laufwerk'))}</span><strong>${bytes(optDlg.data.freeSpace)}</strong>`;
  $('#opt-note').innerHTML = (s.added.length && item?.updateAvailable
    ? `<p class="note">${esc(t('Für dieses Element steht ein Update aus – es wird beim Hinzufügen mit installiert.'))}</p>` : '') +
    (s.sharedFiles ? `<p class="note">${esc(t('{n} Dateien ({size}) bleiben stehen, weil weiterhin gewählte Komponenten sie mitbenutzen – der Ordner der abgewählten Komponente verschwindet deshalb evtl. nicht ganz.',
      { n: s.sharedFiles, size: bytes(s.sharedSize) }))}</p>` : '');
  $('#opt-apply').hidden = !s.added.length && !s.removed.length;
}

async function openOptions(appName, refresh = false) {
  Object.assign(optDlg, { app: appName, data: null });
  const item = state.library?.items.find((i) => i.appName === appName);
  $('#opt-heading').textContent = t('{title} – Optionen', { title: item ? item.title : appName });
  $('#optdlg').hidden = false;
  $('#opt-apply').hidden = true;
  $('#opt-body').innerHTML = `<p class="loading">${esc(t('Prüfe installierte Dateien … bei DevKits bis zu 2 Minuten.'))}</p>`;
  try { optDlg.data = await call('components', appName, refresh); } catch (err) {
    $('#opt-body').innerHTML = `<p class="note bad">${esc(err.message)}</p>`;
    return;
  }
  const comps = optDlg.data.components;
  if (!comps.length) {
    $('#opt-body').innerHTML = `<p class="note">${esc(t('Keine optionalen Komponenten.'))}</p>`;
    return;
  }
  $('#opt-body').innerHTML = `
    <div class="opt-list">${comps.map((c) => `
      <label class="opt-row"><span class="name">${esc(compName(c.tag))}</span>
        <span class="size">${bytes(c.size)}</span>
        <input type="checkbox" data-tag="${esc(c.tag)}" ${c.installed ? 'checked' : ''}></label>`).join('')}</div>
    <div class="opt-sum" id="opt-summary"></div>
    <div id="opt-note"></div>
    <p class="hint">${esc(t('Stand: {ago}', { ago: ago(optDlg.data.checked) }))} ·
      <button class="link" id="opt-refresh">${esc(t('Neu prüfen'))}</button></p>`;
  $('#opt-refresh').onclick = () => openOptions(appName, true);
  renderOptSummary();
}

$('#opt-body').addEventListener('change', renderOptSummary);
$('#opt-close').onclick = () => ($('#optdlg').hidden = true);
$('#opt-apply').onclick = async () => {
  const selected = selectedComponents();
  const s = optSummary(selected);
  if (s.removed.length && !(await askConfirm(t('Wirklich entfernen?\n\n{n} Dateien ({size}) der Komponenten {list} werden gelöscht.\nDeine eigenen Dateien und alle übrigen Komponenten sind nicht betroffen.',
    { n: s.files, size: bytes(s.freed), list: s.removed.map(compName).join(', ') }), { ok: 'Entfernen', danger: true }))) return;
  try {
    await call('modify_components', optDlg.app, selected);
    $('#optdlg').hidden = true;
    toast(t('Zur Warteschlange hinzugefügt – Fortschritt unter „Downloads“.'));
    await pollDownloads.once();
  } catch (err) { toast(err.message); }
};

// --- Fab-Asset installieren: Ziel waehlen -> Vorschau -> installieren ---------
const fabDlg = { opts: null, target: null, engine: null, plan: null };

function engineLabel(e) { return (e || '').replace('UE_', 'UE '); }

async function openFab(assetId) {
  Object.assign(fabDlg, { opts: null, target: null, engine: null, engineApp: null, plan: null, projects: null, ver: null, override: false });
  $('#fabdlg').hidden = false;
  $('#fab-go').hidden = true;
  $('#fab-body').innerHTML = `<p class="loading">${esc(t('Lade …'))}</p>`;
  try { fabDlg.opts = await call('fab_options', assetId); } catch (err) {
    $('#fab-body').innerHTML = `<p class="note bad">${esc(err.message)}</p>`;
    return;
  }
  $('#fab-heading').textContent = fabDlg.opts.action || t('Fab-Asset');
  if (fabDlg.opts.item.kind === 'ASSET_PACK') {
    fabDlg.projects = fabDlg.opts.projects || [];
    const pre = state.fabProject;
    if (pre) Object.assign(fabDlg, { target: pre.dir, engine: pre.engine });
  }
  renderFab();
  if (fabDlg.target) loadPlan();
}

function fabVersions() {
  return fabDlg.opts.item.versions.filter(versionUsable);
}

const engineNum = (e) => (e.match(/\d+/g) || []).map(Number);
const newerFirst = (a, b) => b.localeCompare(a, undefined, { numeric: true });

// Jede Engine-Version einzeln waehlbar: UE_5.7 -> die Asset-Version, die dafuer gebaut ist
function fabEngines() {
  const list = [...new Set(fabVersions().flatMap((v) => v.engines))];
  return list.sort(newerFirst);
}

const versionFor = (engine) => fabVersions().find((v) => v.engines.includes(engine)) || fabVersions().slice(-1)[0];

// Vorauswahl: genau die Ziel-Engine, sonst die naechstaeltere (aelter klappt eher als neuer), sonst die neueste
function autoEngine() {
  const list = fabEngines();
  const target = fabDlg.engine;
  if (!target) return list[0];
  if (list.includes(target)) return target;
  const num = engineNum(target);
  const older = list.find((e) => { const n = engineNum(e); return n[0] < num[0] || (n[0] === num[0] && n[1] < num[1]); });
  return older || list[0];
}

const chosenEngine = () => fabDlg.ver || autoEngine();

function fabResetChoice() {
  Object.assign(fabDlg, { plan: null, ver: null, override: false });
}

function renderFab() {
  const { opts, target, engine, plan } = fabDlg;
  const kind = opts.item.kind;
  const chosen = chosenEngine();
  let targetField = '';
  if (kind === 'ASSET_PACK') {
    const list = fabDlg.projects || [];
    const known = list.some((p) => p.dir === target);
    targetField = `<div class="field"><span>${esc(t('Projekt'))}</span><div class="pick">
      <select id="fab-project"><option value="">${esc(t('– wählen –'))}</option>
        ${list.map((p) => `<option value="${esc(p.uproject)}" ${p.dir === target ? 'selected' : ''}>${esc(p.displayName)} · ${esc(p.engineLabel || p.association)}${p.ueVersion ? ` (UE ${esc(p.ueVersion)})` : ''} · ${esc(p.dir)}</option>`).join('')}
        ${target && !known ? `<option value="" selected>${esc(target)}</option>` : ''}</select>
      <button class="btn ghost small" data-fab-pick="project">${esc(t('Anderes …'))}</button></div></div>`;
  } else if (kind === 'CODE_PLUGIN') {
    targetField = `<div class="field"><span>${esc(t('Ziel-Engine'))}</span>${opts.engines.length
      ? `<select id="fab-engine"><option value="">${esc(t('– wählen –'))}</option>${opts.engines.map((e) => `<option value="${esc(e.appName)}" ${e.appName === fabDlg.engineApp ? 'selected' : ''}>${esc(e.title)} (UE ${esc(e.ue)})</option>`).join('')}</select>`
      : `<p class="note bad">${esc(t('Keine Engine installiert.'))}</p>`}</div>`;
  } else {
    targetField = `<div class="field"><span>${esc(t('Zielordner (dort entsteht ein neuer Projektordner)'))}</span><div class="pick">
      <code>${esc(target || t('noch keiner gewählt'))}</code>
      <button class="btn ghost small" data-fab-pick="folder">${esc(t('Ordner wählen …'))}</button></div></div>`;
  }
  const versions = fabEngines().map((e) =>
    `<option value="${esc(e)}" ${e === chosen ? 'selected' : ''}>${esc(engineLabel(e))}${e === engine ? ` – ${esc(t('passt zum Ziel'))}` : ''}</option>`).join('');
  $('#fab-body').innerHTML = `
    <p><strong>${esc(opts.item.title)}</strong> <span class="sub">${esc(opts.item.seller || '')}</span></p>
    ${targetField}
    <div class="field"><span>${esc(t('Engine-Version des Assets'))}</span><select id="fab-version">${versions}</select></div>
    <div id="fab-plan">${plan ? planHtml(plan) : (target ? `<p class="loading">${esc(t('Prüfe …'))}</p>` : '')}</div>`;
  $('#fab-version').onchange = () => { Object.assign(fabDlg, { ver: $('#fab-version').value, plan: null, override: false }); loadPlan(); };
  const projSel = $('#fab-project');
  if (projSel) projSel.onchange = () => {
    const p = (fabDlg.projects || []).find((x) => x.uproject === projSel.value);
    Object.assign(fabDlg, { target: p ? p.dir : null, engine: p ? p.engine : null });
    fabResetChoice();
    renderFab();
    loadPlan();
  };
  const engSel = $('#fab-engine');
  if (engSel) engSel.onchange = () => {
    const e = opts.engines.find((x) => x.appName === engSel.value);
    Object.assign(fabDlg, { engineApp: e?.appName || null, engine: e ? `UE_${e.ue}` : null, target: e?.path || null });
    fabResetChoice();
    renderFab();
    loadPlan();
  };
  fabSyncGo();
}

// Installieren nur, wenn die Version passt - oder der Override bestaetigt wurde
function fabSyncGo() {
  const { plan, override } = fabDlg;
  $('#fab-go').hidden = !plan || !plan.files;
  $('#fab-go').disabled = !plan || (plan.compat?.state !== 'ok' && !override);
}

function compatWarning(c) {
  const vars = { a: engineLabel(chosenEngine()).replace('UE ', ''), t: c.target };
  const text = {
    newer: 'Dieses Asset ist für eine neuere Engine (UE {a}) gebaut als das Ziel (UE {t}). Unreal kann Inhalte neuerer Versionen in der Regel gar nicht öffnen.',
    older: 'Dieses Asset ist für eine ältere Engine (UE {a}) gebaut, das Ziel nutzt UE {t}. Das klappt oft, kann aber zu Fehlern oder fehlenden Inhalten führen.',
    unknown: 'Die Engine-Version des Ziels ist nicht bekannt, die Kompatibilität lässt sich nicht prüfen (Asset: UE {a}).',
  }[c.state];
  const plugin = fabDlg.opts.item.kind === 'CODE_PLUGIN' ? ` ${t('Code-Plugins laden in einer anderen Engine-Version meist gar nicht.')}` : '';
  return t(text, vars) + plugin;
}

function compatHtml(c) {
  if (!c) return '';
  if (c.state === 'ok') {
    return c.target ? `<p class="compat ok">${esc(t('Version passt: Asset und Ziel nutzen UE {t}.', { t: c.target }))}</p>` : '';
  }
  return `<div class="note compat-warn"><strong>${esc(t('Version passt nicht zum Ziel'))}</strong> ${esc(compatWarning(c))}
    <label class="check"><input type="checkbox" id="fab-override" ${fabDlg.override ? 'checked' : ''}> ${esc(t('Trotzdem installieren (Override)'))}</label></div>`;
}

function planHtml(p) {
  if (p.error) return `<p class="note bad">${esc(p.error)}</p>`;
  return compatHtml(p.compat) + planFacts(p);
}

function planFacts(p) {
  const source = {
    epic: t('Epics Vault-Cache – kein Download nötig'),
    kept: t('Behaltenes Asset – kein Download nötig'),
    download: t('Download ({size})', { size: mb(p.downloadMb || 0) }),
  }[p.source] || '';
  return `<dl class="facts">
      <dt>${esc(t('Quelle'))}</dt><dd>${esc(source)}</dd>
      <dt>${esc(t('Ziel'))}</dt><dd>${esc(p.destination)}</dd>
      <dt>${esc(t('Dateien'))}</dt><dd>${p.files} · ${mb(p.sizeMb)}</dd>
      <dt>${esc(t('Platz frei'))}</dt><dd>${mb(p.freeMb)}</dd></dl>
    ${p.existing ? `<div class="note"><strong>${esc(t('{n} Dateien gibt es dort schon.', { n: p.existing }))}</strong> ${esc(t('Standardmäßig bleiben sie unverändert.'))}
        <ul>${p.existingSample.map((f) => `<li>${esc(f)}</li>`).join('')}${p.existing > p.existingSample.length ? '<li>…</li>' : ''}</ul>
        <label class="check"><input type="checkbox" id="fab-overwrite"> ${esc(t('Vorhandene Dateien überschreiben'))}</label></div>` : ''}
    ${p.ignored ? `<p class="note">${esc(t('{n} Dateien gehören nicht in dieses Ziel und werden ausgelassen.', { n: p.ignored }))}</p>` : ''}
    ${p.versionVerified === false ? `<p class="note">${esc(t('Epic liefert diese Version nicht direkt aus – verwendet wird die vollständige Kopie aus Epics Vault-Cache (Version {v}). Ob sie die neueste ist, lässt sich nicht prüfen.', { v: p.version }))}</p>` : ''}`;
}

async function loadPlan() {
  if (!fabDlg.target) return;
  const artifact = versionFor(chosenEngine())?.artifactId;
  $('#fab-plan').innerHTML = `<p class="loading">${esc(t('Prüfe …'))}</p>`;
  $('#fab-go').hidden = true;
  try { fabDlg.plan = await call('fab_plan', fabDlg.opts.item.id, artifact, fabDlg.target); } catch (err) {
    fabDlg.plan = { error: err.message };
  }
  fabDlg.plan.artifactId = artifact;
  $('#fab-plan').innerHTML = planHtml(fabDlg.plan);
  fabSyncGo();
}

$('#fab-close').onclick = () => ($('#fabdlg').hidden = true);
// Override: erst nach der Warnung aktiv
$('#fab-body').addEventListener('change', async (e) => {
  if (e.target.id !== 'fab-override') return;
  const box = e.target;
  if (box.checked && !(await askConfirm(t('Asset trotzdem installieren?\n\n{warn}\n\nDas Asset funktioniert dann eventuell nicht ordnungsgemäß.', { warn: compatWarning(fabDlg.plan.compat) }),
    { ok: 'Trotzdem installieren', danger: true }))) {
    box.checked = false;
  }
  fabDlg.override = box.checked;
  fabSyncGo();
});
$('#fab-body').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-fab-pick]');
  if (!b) return;
  try {
    if (b.dataset.fabPick === 'project') {
      const p = await call('choose_project');
      if (p.cancelled) return;
      Object.assign(fabDlg, { target: p.dir, engine: p.engine });
    } else {
      const p = await call('choose_folder');
      if (p.cancelled) return;
      fabDlg.target = p.path;
    }
    fabResetChoice();
    renderFab();
    loadPlan();
  } catch (err) { toast(err.message); }
});
$('#fab-go').onclick = async () => {
  const p = fabDlg.plan;
  const overwrite = $('#fab-overwrite')?.checked || false;
  try {
    await call('fab_install', fabDlg.opts.item.id, p.artifactId, fabDlg.target, overwrite, fabDlg.override);
    $('#fabdlg').hidden = true;
    toast(t('Zur Warteschlange hinzugefügt – Fortschritt unter „Downloads“.'));
    await pollDownloads.once();
  } catch (err) { toast(err.message); }
};

// --- Projekt loeschen: pruefen -> Uebersicht -> Namen eintippen -> Papierkorb ---------
const delDlg = { uproject: null, name: null };

async function openDelete(uproject) {
  Object.assign(delDlg, { uproject, name: null });
  $('#deldlg').hidden = false;
  $('#del-go').hidden = true;
  $('#del-body').innerHTML = `<p class="loading">${esc(t('Prüfe Projektordner …'))}</p>`;
  let info;
  try { info = await call('delete_project_info', uproject); } catch (err) {
    $('#del-body').innerHTML = `<p class="note bad">${esc(err.message)}</p>`;
    return;
  }
  if (info.blocked) {
    $('#del-body').innerHTML = `<p class="note bad">${esc(info.blockedText)}</p>
      ${info.others ? `<ul class="plain">${info.others.map((o) => `<li><code>${esc(o)}</code></li>`).join('')}</ul>` : ''}`;
    return;
  }
  delDlg.name = info.name;
  delDlg.shown = info.displayName;
  $('#del-body').innerHTML = `
    <dl class="facts">
      <dt>${esc(t('Projekt'))}</dt><dd><strong>${esc(info.displayName)}</strong>${info.displayName !== info.name ? ` (${esc(info.name)})` : ''} · ${esc(info.engineLabel)}</dd>
      <dt>${esc(t('Ordner'))}</dt><dd><code>${esc(info.dir)}</code></dd>
      <dt>${esc(t('Inhalt'))}</dt><dd>${esc(t('{n} Dateien · {size}', { n: info.files, size: mb(info.sizeMb) }))}</dd>
      <dt></dt><dd class="sub">${info.top.map(esc).join(' · ')}${info.topMore ? ` · ${esc(t('und {n} weitere', { n: info.topMore }))}` : ''}</dd></dl>
    <p class="note">${esc(t('Der komplette Projektordner wird in den Papierkorb verschoben – mit allem, was darin liegt, auch eigenen Dateien. Passt er nicht in den Papierkorb, fragt Windows, ob endgültig gelöscht werden soll.'))}</p>
    <label class="field"><span>${esc(t('Zur Bestätigung den Projektnamen eintippen:'))}</span> <code class="confirm-name">${esc(info.name)}</code>
      <input id="del-confirm" type="text" autocomplete="off" spellcheck="false"></label>`;
  $('#del-go').hidden = false;
  $('#del-go').disabled = true;
  const input = $('#del-confirm');
  input.oninput = () => { $('#del-go').disabled = input.value !== delDlg.name; };
  input.focus();
}

$('#del-close').onclick = () => ($('#deldlg').hidden = true);
$('#del-go').onclick = async () => {
  const go = $('#del-go');
  go.disabled = true;
  $('#del-body').insertAdjacentHTML('beforeend', `<p class="loading">${esc(t('Wird gelöscht …'))}</p>`);
  try {
    const res = await call('delete_project', delDlg.uproject, $('#del-confirm').value);
    if (res.blocked) {
      $('#del-body').innerHTML = `<p class="note bad">${esc(res.blockedText)}</p>`;
      go.hidden = true;
      return;
    }
    $('#deldlg').hidden = true;
    toast(t('„{name}“ wurde in den Papierkorb verschoben ({size} frei).', { name: delDlg.shown, size: mb(res.sizeMb || 0) }));
    state.projects = await call('projects');
    render();
  } catch (err) {
    $('#del-body').innerHTML = `<p class="note bad">${esc(err.message)}</p>`;
    go.hidden = true;
  }
};

// --- Engine oder DevKit hinzufuegen: Auswahl aus allem, was noch nicht installiert ist ---
async function openAdd(kind) {
  const data = await loadLibrary();
  const items = data.items.filter((i) => i.kind === kind && !i.installed && !busy(i.appName))
    .sort((a, b) => (kind === 'engine' ? b.title.localeCompare(a.title, undefined, { numeric: true }) : a.title.localeCompare(b.title)));
  const s = await call('settings');
  const what = kind === 'engine' ? 'Engine' : 'DevKit';
  // Epic fuehrt alles als "Software" - Kits und Editoren zuerst, Spotify & Co. getrennt darunter
  const isDevkit = (i) => /kit|editor|sdk/i.test(i.title);
  const devkits = items.filter(isDevkit);
  const others = items.filter((i) => !isDevkit(i));
  const options = (list) => list.map((i) => `<option value="${esc(i.appName)}">${esc(i.title)}</option>`).join('');
  $('#add-heading').textContent = t(kind === 'engine' ? 'Neue Engine installieren' : 'Neues DevKit installieren');
  $('#add-body').innerHTML = items.length ? `
    <label class="field"><span>${esc(t(kind === 'engine' ? 'Unreal-Engine-Version' : 'DevKit oder Tool'))}</span>
      <select id="add-app">${kind === 'engine' ? options(items) : `<optgroup label="${esc(t('DevKits'))}">${options(devkits)}</optgroup>
        ${others.length ? `<optgroup label="${esc(t('Sonstige Software'))}">${options(others)}</optgroup>` : ''}`}</select></label>
    <div class="field"><span>${esc(t('Installationsordner'))}</span><div class="pick">
      <code>${esc(s.installDir || t('noch nicht festgelegt'))}</code>
      <button class="btn ghost small" id="add-dir">${esc(t('Ändern'))}</button></div></div>`
    : `<p class="home-empty">${esc(t(`Alle verfügbaren ${what}s sind installiert.`))}</p>`;
  $('#add-go').hidden = !items.length;
  $('#add-go').textContent = t('Installieren');
  state.adopt = null;
  $('#adddlg').hidden = false;
  const dir = $('#add-dir');
  if (dir) dir.onclick = async () => { if (!(await call('choose_install_dir')).cancelled) openAdd(kind); };
}

$('#add-close').onclick = () => ($('#adddlg').hidden = true);
$('#add-go').onclick = async () => {
  const app = $('#add-app').value;
  if (state.adopt) {
    if (!state.adopt.path) { toast(t('Bitte zuerst den Ordner wählen.')); return; }
    try {
      await call('adopt_install', app, state.adopt.path);
      $('#adddlg').hidden = true;
      toast(t('Zur Warteschlange hinzugefügt.'));
      await pollDownloads.once();
    } catch (err) { toast(err.message); }
    return;
  }
  $('#adddlg').hidden = true;
  try { await startInstall(app); } catch (err) { toast(err.message); }
};

// Vorhandene Engine oder vorhandenes DevKit uebernehmen (z. B. aus Heroic), ohne neuen Download
async function openAdopt(kind) {
  const data = await loadLibrary();
  const { heroic } = await call('adopt_options');
  const items = data.items.filter((i) => i.kind === kind && !i.installed && !busy(i.appName)).sort((a, b) =>
    (heroic[b.appName] ? 1 : 0) - (heroic[a.appName] ? 1 : 0)
      || (kind === 'engine' ? b.title.localeCompare(a.title, undefined, { numeric: true }) : a.title.localeCompare(b.title)));
  state.adopt = { kind, heroic, path: items[0] ? heroic[items[0].appName] || null : null };
  const label = (i) => `${i.title}${heroic[i.appName] ? ` (${t('in Heroic gefunden')})` : ''}`;
  $('#add-heading').textContent = t({ engine: 'Vorhandene Engine hinzufügen', game: 'Vorhandenes Spiel hinzufügen' }[kind] || 'Vorhandenes DevKit hinzufügen');
  $('#add-body').innerHTML = items.length ? `
    <label class="field"><span>${esc(t({ engine: 'Unreal-Engine-Version', game: 'Spiel aus deiner Epic-Bibliothek' }[kind] || 'DevKit oder Tool'))}</span>
      <select id="add-app">${items.map((i) => `<option value="${esc(i.appName)}">${esc(label(i))}</option>`).join('')}</select></label>
    <div class="field"><span>${esc(t('Installationsordner'))}</span><div class="pick">
      <code id="adopt-path"></code>
      <button class="btn ghost small" id="adopt-dir">${esc(t('Ändern'))}</button></div></div>
    <p class="note">${esc(t('Es wird nichts neu heruntergeladen. Der Launcher prüft, ob der Ordner zum gewählten Eintrag passt. Stammt die Installation nicht aus dem Epic Launcher, werden danach alle Dateien geprüft; das kann eine Weile dauern. Nur Fehlendes oder Veraltetes wird nachgeladen.'))}</p>`
    : `<p class="home-empty">${esc(t('Nichts gefunden.'))}</p>`;
  $('#add-go').hidden = !items.length;
  $('#add-go').textContent = t('Hinzufügen');
  $('#adddlg').hidden = false;
  if (!items.length) return;
  const showPath = () => ($('#adopt-path').textContent = state.adopt.path || t('noch nicht festgelegt'));
  showPath();
  $('#add-app').onchange = () => { state.adopt.path = heroic[$('#add-app').value] || null; showPath(); };
  $('#adopt-dir').onclick = async () => {
    const p = await call('choose_folder');
    if (!p.cancelled) { state.adopt.path = p.path; showPath(); }
  };
}

async function startInstall(appName) {
  const item = state.library?.items.find((i) => i.appName === appName);
  if (item?.preview && !(await askConfirm(t('{title} installieren?\n\nDas ist eine Vorabversion von Epic: Sie kann Fehler enthalten und ändert sich bis zur fertigen Version noch. Für echte Projekte besser nicht verwenden.', { title: item.title }), { ok: 'Trotzdem installieren' }))) return;
  let res = await call('install', appName);
  if (res.needsInstallDir) {
    toast(t('Wähle zuerst den Ordner, in den installiert werden soll.'));
    const s = await call('choose_install_dir');
    if (s.cancelled) return;
    res = await call('install', appName);
  }
  toast(t('Zur Warteschlange hinzugefügt.'));
  await pollDownloads.once();
}
pollDownloads.once = async () => { jobs = (await call('downloads_list')).jobs; render(); };

function renderPaged(items, cardFn, gridClass) {
  state.list = items;
  state.shown = 0;
  state.cardFn = cardFn;
  $('#content').innerHTML = items.length ? `<div class="grid paged ${gridClass}"></div>` : `<p class="empty">${esc(t('Nichts gefunden.'))}</p>`;
  renderMore();
}

function renderMore() {
  const grid = $('#content .grid.paged');
  if (!grid || state.shown >= state.list.length) return;
  const next = state.list.slice(state.shown, state.shown + PAGE);
  grid.insertAdjacentHTML('beforeend', next.map(state.cardFn).join(''));
  state.shown += next.length;
  if (state.view === 'projects') loadThumbs();
}

new IntersectionObserver((e) => e[0].isIntersecting && renderMore(), { root: $('main'), rootMargin: '600px' })
  .observe($('#sentinel'));

async function render() {
  const v = state.view;
  const fabFilters = v !== 'fab' || state.fabTab === 'local';
  $('#filter-engine').hidden = $('#filter-type').hidden = $('#filter-cat').hidden = $('#filter-sort').hidden = fabFilters;
  $('#filter-state').hidden = v !== 'games';
  $('#search').hidden = $('#refresh').hidden = ['home', 'store', 'account', 'downloads', 'settings', 'tools'].includes(v);
  if (v === 'unreal' || v === 'cleanup') $('#search').hidden = true;
  if (v === 'crashes') $('#search').hidden = false;
  const none = `<p class="empty">${esc(t('Nichts gefunden.'))}</p>`;

  if (v === 'settings') {
    const s = await call('settings');
    $('#meta').textContent = t('Änderungen werden sofort gespeichert.');
    const setting = (label, help, control) => `<div class="setting">
        <div class="label">${esc(t(label))}</div><div class="control">${control}</div>
        <div class="help">${esc(t(help))}</div></div>`;
    $('#content').innerHTML = `<div class="settings">
      <div>
        <h2 class="section">${esc(t('Allgemein'))}</h2>
        ${setting('Sprache', 'Sprache der Oberfläche. Beim ersten Start wird die Windows-Sprache übernommen.',
          `<select data-setting="language">${Object.entries(LANGUAGES).map(([k, n]) =>
            `<option value="${k}" ${k === LANG ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`)}
        ${setting('Mit Windows starten', 'Startet den Launcher bei der Windows-Anmeldung – normal im Fenster oder still im Infobereich neben der Uhr.',
          `<select data-setting="autostart">${[['off', 'Aus'], ['normal', 'Normal'], ['tray', 'Im Infobereich']].map(([k, n]) =>
            `<option value="${k}" ${k === s.autostart ? 'selected' : ''}>${esc(t(n))}</option>`).join('')}</select>`)}
        ${setting('Beim Schließen im Infobereich weiterlaufen', 'Das X schließt nur das Fenster, der Launcher läuft neben der Uhr weiter – z. B. für Downloads. Ganz beenden über das Symbol dort.',
          `<label class="switch"><input type="checkbox" data-setting="closeToTray" ${s.closeToTray ? 'checked' : ''}><span></span></label>`)}
        ${setting('Bereich „Spiele“ anzeigen', 'Der Launcher ist aufs Arbeiten mit Unreal ausgerichtet. Ausgeblendet verschwindet „Spiele“ aus dem Menü.',
          `<label class="switch"><input type="checkbox" data-setting="showGames" ${s.showGames ? 'checked' : ''}><span></span></label>`)}
      </div>
      <div>
        <h2 class="section">${esc(t('Downloads'))}</h2>
        ${setting('Installationsordner', 'Hier landen neu installierte Spiele, Engines und DevKits. Updates bleiben immer im vorhandenen Ordner.',
          `<code title="${esc(s.installDir || '')}">${esc(s.installDir || t('noch nicht festgelegt'))}</code>
           <button class="btn ghost small" data-pick-setting="installDir">${esc(t('Ändern'))}</button>`)}
        ${setting('Zwischenordner für Fab-Assets', 'Fab-Assets werden hier zwischengespeichert und danach ins Projekt kopiert. Der Ordner wird danach wieder geleert.',
          `<code title="${esc(s.vaultDir)}">${esc(s.vaultDir)}</code>
           <button class="btn ghost small" data-pick-setting="vaultDir">${esc(t('Ändern'))}</button>
           <button class="btn ghost small" data-reset-setting="vaultDir">${esc(t('Standard'))}</button>`)}
        ${setting('Assets behalten', 'Geladene Fab-Assets bleiben im Zwischenordner liegen – für weitere Projekte ist dann kein neuer Download nötig. Braucht entsprechend Speicherplatz.',
          `<label class="switch"><input type="checkbox" data-setting="keepAssets" ${s.keepAssets ? 'checked' : ''}><span></span></label>`)}
        ${setting('Epics Vault-Cache mitnutzen', 'Liegt ein Asset schon vollständig und aktuell in Epics Vault-Cache, wird es von dort kopiert statt neu geladen. Gelöscht wird dort nur, was du selbst unter „Lokal gespeichert“ entfernst.',
          `<label class="switch"><input type="checkbox" data-setting="useEpicVault" ${s.useEpicVault ? 'checked' : ''}><span></span></label>`)}
        <p class="help vault-dirs">${esc(t('Gefundene Vault-Ordner des Epic Launchers:'))} ${s.epicVaultDirs.length
          ? s.epicVaultDirs.map((d) => `<code>${esc(d)}</code>`).join(' ') : esc(t('keine'))}</p>
        ${setting('Nachkontrolle nach Installation und Update', 'Wie beim Epic Launcher: Nach einem Update werden die geänderten Dateien, nach einer Installation alle Dateien mit Epics Prüfsummen verglichen. Fehlerhaftes wird automatisch neu geladen. Bei großen DevKits dauert eine Neuinstallation dadurch länger.',
          `<label class="switch"><input type="checkbox" data-setting="verifyAfter" ${s.verifyAfter ? 'checked' : ''}><span></span></label>`)}
        ${setting('Download-Tempo', 'Begrenzt das Tempo aller Downloads, damit genug Leitung für anderes bleibt. Gilt sofort, auch für laufende Downloads.',
          `<select data-setting="speedLimit">${s.speedChoices.map((n) =>
            `<option value="${n}" ${n === s.speedLimit ? 'selected' : ''}>${n ? `${n} MB/s` : esc(t('Maximal'))}</option>`).join('')}</select>`)}
        ${setting('Parallele Verbindungen', 'Epic begrenzt das Tempo je Verbindung – mehr Verbindungen laden schneller, brauchen aber mehr Arbeitsspeicher (ca. 40 MB je Verbindung). Gilt ab dem nächsten Start oder Fortsetzen eines Downloads. Bei einem Tempolimit nutzt der Launcher nur so viele, wie dafür nötig sind.',
          `<select data-setting="maxWorkers">${s.workerChoices.map((n) =>
            `<option value="${n}" ${n === s.maxWorkers ? 'selected' : ''}>${n}${n === 16 ? ` (${esc(t('Standard'))})` : ''}</option>`).join('')}</select>`)}
      </div></div>`;
    return;
  }

  if (v === 'downloads') {
    const s = await call('settings');
    for (const id of state.openLogs) {
      try { state.logs[id] = (await call('download_log', id)).lines; } catch { /* weiter */ }
    }
    $('#meta').textContent = jobs.length ? t('{n} aktiv', { n: jobs.filter((j) => j.status === 'queued' || j.status === 'running').length }) : '';
    $('#content').innerHTML = `
      <div class="settings-line">${esc(t('Neue Installationen landen in'))}
        <code>${esc(s.installDir || t('noch nicht festgelegt'))}</code>
        <button class="btn ghost small" data-choose-dir="1">${esc(t('Ändern'))}</button>
        ${jobs.some((j) => !OPEN.includes(j.status)) ? `<button class="btn ghost small" data-clear="1">${esc(t('Erledigte ausblenden'))}</button>` : ''}
      </div>
      <div class="rows">${jobs.length ? [...jobs].reverse().map(jobRow).join('') : `<p class="empty">${esc(t('Keine Downloads.'))}</p>`}</div>`;
    document.querySelectorAll('.joblog').forEach((el) => { el.scrollTop = el.scrollHeight; }); // neueste Zeile sichtbar
    return;
  }

  if (v === 'tools') return renderTools();
  if (v === 'cleanup') return renderCleanup();
  if (v === 'crashes') return renderCrashes();

  if (v === 'account') {
    $('#meta').textContent = '';
    $('#content').innerHTML = `<div class="store-bar"><div class="store-nav">
        <button class="btn ghost small" data-store-go="back" title="${esc(t('Zurück'))}">←</button>
        <button class="btn ghost small" data-store-go="reload" title="${esc(t('Neu laden'))}">⟳</button></div></div>
      <div id="store-frame" class="store-frame"><p class="loading">${esc(t('Lade …'))}</p></div>`;
    await call('store_show', (await call('account_url')).url, storeRect(), 'account');
    return;
  }

  if (v === 'store') {
    $('#meta').textContent = '';
    const tab = (k, label) => `<button class="tab ${state.storeTab === k ? 'active' : ''}" data-store-tab="${k}">${esc(label)}</button>`;
    $('#content').innerHTML = `
      <div class="store-bar">
        <div class="tabs">${tab('fab', 'Fab')}${tab('epic', 'Epic Games Store')}</div>
        <div class="store-nav">
          <button class="btn ghost small" data-store-go="back" title="${esc(t('Zurück'))}">←</button>
          <button class="btn ghost small" data-store-go="forward" title="${esc(t('Vor'))}">→</button>
          <button class="btn ghost small" data-store-go="reload" title="${esc(t('Neu laden'))}">⟳</button>
          <button class="btn ghost small" data-store-window="1">${esc(t('Im eigenen Fenster'))}</button>
        </div>
      </div>
      <div id="store-frame" class="store-frame"><p class="loading">${esc(t('Lade …'))}</p></div>`;
    await showStorePanel(state.storeUrl);
    state.storeUrl = null;
    return;
  }

  if (v === 'home') {
    const h = await call('home');
    state.home = h;
    $('#meta').textContent = '';
    state.list = [];
    const head = (title, extra = '') => `<div class="home-head"><h2>${esc(t(title))}</h2>${extra}</div>`;
    const tiles = (items, card, empty) => (items.length
      ? `<div class="tiles">${items.map(card).join('')}</div>` : `<p class="home-empty">${esc(t(empty))}</p>`);
    $('#content').innerHTML = `<div class="home"><div class="home-main">
      <section>${head('Gratis auf Fab', `<button class="link" data-url="https://www.fab.com/limited-time-free">${esc(t('Alle auf Fab ansehen'))}</button>`)}
        <div id="home-free">${state.free ? freeTiles(state.free) : `<p class="home-empty">${esc(t('Lade …'))}</p>`}</div></section>
      <section>${head('Zuletzt gestartet')}${tiles(h.recent, launchTile, 'Noch nichts gestartet.')}</section>
      <section>${head('Letzte Projekte', `<button class="link" data-view-go="projects">${esc(t('Alle Projekte'))}</button>`)}${tiles(h.projects, projectTile, 'Keine Projekte gefunden.')}</section>
    </div>
    <aside class="home-status">
      ${statusUpdates(h)}
      <section class="status-box"><div class="home-head"><h2>${esc(t('Speicherplatz'))}</h2><button class="link" data-view-go="cleanup">${esc(t('Aufräumen'))}</button></div><div id="status-storage"><p class="status-empty">${esc(t('Lade …'))}</p></div></section>
    </aside></div>`;
    loadThumbs();
    loadFree();
    loadStorage();
    return;
  }

  if (v === 'projects') {
    const data = await loadProjects();
    const items = data.items.filter((p) => matches(`${p.displayName} ${p.name} ${p.engineLabel} ${p.dir}`));
    $('#meta').textContent = t('{n} von {total} Projekten', { n: items.length, total: data.items.length });
    renderPaged(items, projectCard, 'wide');
    $('#content').insertAdjacentHTML('afterbegin', `<div class="settings-line">
      <button class="btn ghost small" data-add-project="1">${esc(t('Projekt hinzufügen …'))}</button>
      <button class="btn ghost small" data-add-project-folder="1">${esc(t('Projektordner hinzufügen …'))}</button>
      <span class="help">${esc(t('Gefunden werden zuletzt geöffnete Projekte, Projekte in den Projektordnern von Unreal und dem Epic Launcher sowie in installierten DevKits.'))}</span></div>`);
    return;
  }

  if (v === 'fab' && state.fabTab === 'local') {
    await renderLocal();
    return;
  }

  if (v === 'fab') {
    const data = await loadFab();
    const eng = $('#filter-engine').value;
    const type = $('#filter-type').value;
    const cat = $('#filter-cat').value;
    const sort = FAB_SORT[$('#filter-sort').value];
    const items = data.items.filter((a) => matches(`${a.title} ${a.seller} ${a.type || ''} ${a.categories.join(' ')}`) &&
      (!eng || a.engines.includes(eng)) && (!type || a.type === type) && (!cat || fabCategoryOf(a) === cat));
    if (sort) items.sort(sort);
    $('#meta').textContent = t('{n} von {total} Assets · Stand {ago}', { n: items.length, total: data.items.length, ago: ago(data.updated) });
    renderPaged(items, fabCard, 'wide');
    if (state.fabProject) {
      $('#content').insertAdjacentHTML('afterbegin', `<div class="settings-line">
        ${esc(t('Ziel für „Zum Projekt“:'))} <code>${esc(state.fabProject.displayName)}</code> <span class="help">${esc(state.fabProject.engineLabel || '')}</span>
        <button class="btn ghost small" data-fab-project-clear="1">${esc(t('Ziel aufheben'))}</button></div>`);
    }
    $('#content').insertAdjacentHTML('afterbegin', fabTabs());
    return;
  }

  const data = await loadLibrary();
  if (v === 'games') {
    const all = data.items.filter((i) => i.kind === 'game');
    const items = all.filter((i) => matches(i.title) && stateFilter(i));
    const installed = items.filter((i) => i.installed || busy(i.appName));
    const others = items.filter((i) => !installed.includes(i));
    $('#meta').textContent = t('{n} von {total} Spielen · {inst} installiert · Stand {ago}',
      { n: items.length, total: all.length, inst: all.filter((i) => i.installed).length, ago: ago(data.updated) });
    // Eigener Bereich fuer Installiertes, darunter der Rest seitenweise
    renderPaged(others, gameCard, '');
    {  // Kopf immer zeigen: dort sitzt "Vorhandenes hinzufuegen"
      $('#content').insertAdjacentHTML('afterbegin', `<section class="items-block">
        <div class="home-head"><h2>${esc(t('Installierte Spiele'))}</h2><div class="home-actions"><button class="btn ghost small" data-adopt-kind="game">${esc(t('Vorhandene hinzufügen'))}</button></div></div>
        ${installed.length ? `<div class="grid">${installed.map(gameCard).join('')}</div>` : `<p class="home-empty">${esc(t('Noch kein Spiel installiert.'))}</p>`}</section>
        <div class="home-head games-rest"><h2>${esc(t('Nicht installiert'))}</h2></div>`);
    }
    return;
  }

  // Unreal-Bereich: nur Installiertes (und was gerade installiert wird)
  const shown = (kind) => data.items.filter((i) => i.kind === kind && (i.installed || busy(i.appName)));
  const engines = shown('engine').sort((a, b) => b.title.localeCompare(a.title, undefined, { numeric: true }));
  const tools = shown('tool').sort((a, b) => a.title.localeCompare(b.title));
  const block = (title, kind, label, items, empty) => `<section class="items-block">
    <div class="home-head"><h2>${esc(t(title))}</h2><div class="home-actions"><button class="btn ghost small" data-adopt-kind="${kind}">${esc(t('Vorhandene hinzufügen'))}</button><button class="btn ghost small" data-add-kind="${kind}">${esc(t(label))}</button></div></div>
    ${items.length ? `<div class="items">${items.map(itemTile).join('')}</div>` : `<p class="home-empty">${esc(t(empty))}</p>`}</section>`;
  state.list = [];
  $('#meta').textContent = t('{e} Engines und {t} Tools installiert · Stand {ago}',
    { e: engines.filter((x) => x.installed).length, t: tools.filter((x) => x.installed).length, ago: ago(data.updated) });
  $('#content').innerHTML = block('Engine-Versionen', 'engine', 'Neue Engine installieren', engines, 'Noch keine Engine installiert.') +
    block('DevKits & Tools', 'tool', 'Neues DevKit installieren', tools, 'Noch kein DevKit installiert.');
}

// --- Store rechts im Hauptfenster (eigenes Browser-Element ueber #store-frame) ---
state.storeTab = 'fab';
state.storeOpened = {}; // je Reiter: schon einmal geladen? (dann aktuelle Seite behalten)

function storeRect() {
  const frame = $('#store-frame');
  if (!frame) return null;
  // bis zum unteren Fensterrand ausdehnen
  frame.style.height = `${Math.max(200, window.innerHeight - frame.getBoundingClientRect().top - 16)}px`;
  const r = frame.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  return { x: r.left * dpr, y: r.top * dpr, w: r.width * dpr, h: r.height * dpr };
}

async function showStorePanel(url) {
  const rect = storeRect();
  if (!rect) return;
  if (!url && !state.storeOpened[state.storeTab]) url = (await call('store_home', state.storeTab)).url;
  state.storeOpened[state.storeTab] = true;
  await call('store_show', url || null, rect);
}

function openInStore(tab, url) {
  state.storeTab = tab;
  state.storeUrl = url;
  state.storeOpened[tab] = true;
  show('store');
}

window.addEventListener('resize', () => {
  if (state.view !== 'store' && state.view !== 'account') return;
  clearTimeout(window.__storeResize);
  window.__storeResize = setTimeout(() => { const r = storeRect(); if (r) call('store_resize', r, state.view); }, 80);
});

// --- Abstuerze: Berichte von Unreal in normaler Sprache (alles lokal) ------------
const CRASH_CATEGORIES = {
  vram: ['Grafikspeicher voll', 'Die Grafikkarte hatte keinen freien Speicher mehr für Texturen oder Meshes.', [
    'Andere Programme mit Grafiklast schließen (Browser, Spiele, Videos, ein zweiter Editor).',
    'Die Qualität im Viewport senken: Settings → Engine Scalability Settings → Medium oder Low.',
    'Bei großen Maps weniger Regionen gleichzeitig laden (World Partition: nur die benötigten Bereiche).',
    'Sehr große Texturen (4K/8K) prüfen und wo möglich verkleinern, zum Beispiel über „Maximum Texture Size“.',
  ]],
  gpu: ['Grafikkarte hat nicht mehr reagiert', 'Der Grafiktreiber hat die Verbindung zur Grafikkarte verloren, etwa durch einen Treiberabsturz oder eine Zeitüberschreitung.', [
    'Den Grafiktreiber auf die neueste Version aktualisieren (Studio-Treiber laufen oft stabiler).',
    'Übertaktung von Grafikkarte und Arbeitsspeicher abschalten, auch eine Werksübertaktung.',
    'Die Qualität im Viewport senken: Settings → Engine Scalability Settings → Medium oder Low.',
    'Passiert es immer an derselben Stelle, dort zuerst schwere Effekte, Lumen oder sehr detaillierte Meshes prüfen.',
  ]],
  memory: ['Arbeitsspeicher voll', 'Windows konnte dem Editor keinen weiteren Arbeitsspeicher geben.', [
    'Andere Programme schließen, besonders Browser mit vielen Tabs.',
    'Die Auslagerungsdatei von Windows verwalten lassen und auf dem Systemlaufwerk mindestens 32 GB frei halten.',
    'Bei großen Maps weniger Regionen gleichzeitig laden (World Partition: nur die benötigten Bereiche).',
    'Beim Cooken oder Erzeugen von HLODs keinen zweiten Editor offen haben.',
  ]],
  shader: ['Problem mit einem Shader', 'Beim Übersetzen oder Laden eines Shaders ist etwas schiefgegangen.', [
    'Das zuletzt bearbeitete Material öffnen und auf Fehler prüfen (rote Knoten, fehlende Texturen).',
    'Den Editor neu starten – manchmal war nur ein einzelner Durchlauf fehlerhaft.',
    'Hilft das nicht: unter Werkzeuge → Speicher aufräumen den Shader- und Textur-Zwischenspeicher löschen. Das nächste Öffnen dauert dann länger.',
  ]],
  worldpartition: ['Problem mit World Partition, HLOD oder Landscape', 'Der Fehler trat beim Laden, Bearbeiten oder Aufbauen einer großen Map auf.', [
    'Wurden gerade HLODs erzeugt? Dann diesen Schritt mit einer kleineren Region oder einzelnen HLOD-Layern wiederholen.',
    'Beim Bearbeiten der Landscape: den zuletzt bearbeiteten Bereich und dessen Layer prüfen.',
    'Die Protokolle unter Saved/WorldPartition nennen oft das betroffene Objekt.',
  ]],
  save: ['Fehler beim Speichern eines Assets', 'Ein Asset ließ sich nicht speichern, meist wegen eines ungültigen Verweises.', [
    'Das oben genannte Asset öffnen und auf fehlende oder ungültige Verweise prüfen.',
    'Im Content Browser per Rechtsklick auf den Ordner „Fix Up Redirectors“ ausführen.',
    'Verweist das Asset auf etwas aus einer anderen Map oder einem anderen Mod, diesen Verweis entfernen.',
  ]],
  asset: ['Asset fehlt oder ist beschädigt', 'Ein Asset konnte nicht geladen werden – es fehlt, ist beschädigt oder stammt aus einer anderen Version.', [
    'Prüfen, ob das oben genannte Asset noch existiert.',
    'Beschädigte Assets aus einem Backup holen oder neu importieren.',
    'Fehlen Dateien des DevKits oder der Engine selbst: die Installation im Launcher prüfen lassen (Verify).',
  ]],
  blueprint: ['Problem in einem Blueprint', 'Ein Blueprint hat beim Ausführen oder Kompilieren einen Fehler ausgelöst.', [
    'Den genannten Blueprint öffnen und „Compile“ klicken – Fehler stehen danach im Compiler-Fenster.',
    'Zuletzt geänderte Knoten prüfen, besonders Casts und Zugriffe auf leere Variablen (None).',
  ]],
  assert: ['Interne Prüfung der Engine fehlgeschlagen', 'Unreal hat einen Zustand erkannt, der nie vorkommen sollte, und sich sicherheitshalber beendet.', [
    'Unter „Beteiligt“ und „Gerade offen“ steht, wo es passiert ist – dort zuerst suchen.',
    'Prüfen, ob es bei demselben Schritt wieder passiert. Wenn ja, liegt es meist an diesem Inhalt.',
    'Ohne erkennbaren Auslöser ist es oft ein Fehler der Engine, den erst ein Update behebt. Dann hilft eine Meldung an den Hersteller mit der Originalmeldung.',
  ]],
  ensure: ['Warnung der Engine', 'Unreal hat etwas Unerwartetes bemerkt, aber weitergearbeitet.', [
    'Meist nichts zu tun, solange der Editor normal weiterläuft.',
    'Häufen sich diese Warnungen bei einem Asset, dieses genauer prüfen.',
  ]],
  access: ['Zugriffsfehler im Programm', 'Der Editor hat auf ungültige Daten zugegriffen (Access Violation).', [
    'Ist unter „Beteiligt“ ein Plugin genannt: dieses aktualisieren oder testweise deaktivieren.',
    'Prüfen, ob es bei demselben Schritt wieder passiert. Wenn ja, liegt es meist an diesem Inhalt.',
    'Bei Blueprint-Warnungen in den letzten Log-Zeilen zuerst diese Blueprints prüfen.',
    'Den Grafiktreiber auf die neueste Version aktualisieren (Studio-Treiber laufen oft stabiler).',
  ]],
  hang: ['Editor reagierte nicht mehr', 'Der Editor hing zu lange an einer Aufgabe fest und wurde beendet.', [
    'Bei großen Maps oder vielen Shadern mehr Zeit geben – nach einem Neustart ist der Zwischenspeicher oft schon gefüllt.',
    'Prüfen, ob das Laufwerk fast voll oder sehr langsam ist. DevKits gehören auf eine SSD.',
    'Passiert es immer beim selben Schritt, diesen in kleineren Teilen ausführen.',
  ]],
  unknown: ['Nicht erkannt', 'Für diesen Fehler gibt es noch keine Erklärung.', [
    'Die letzten Warnungen und Fehler vor dem Absturz zeigen oft, was kurz vorher schiefging.',
    'Mit der Originalmeldung im Internet oder in der Community suchen.',
  ]],
  unreadable: ['Nicht auswertbar', 'Dieser Bericht ließ sich nicht lesen. Eventuell ist er unvollständig oder hat ein anderes Format.', [
  ]],
};

const CRASH_AREAS = {
  directx: 'Grafik (DirectX)',
  vulkan: 'Grafik (Vulkan)',
  render: 'Darstellung (Renderer)',
  landscape: 'Landscape',
  foliage: 'Foliage',
  worldpartition: 'World Partition',
  ddc: 'Zwischenspeicher (DDC)',
  audio: 'Audio',
  shader: 'Shader',
  material: 'Material-Editor',
  niagara: 'Niagara (Effekte)',
  browser: 'Eingebetteter Browser',
  physics: 'Physik (Chaos)',
};

function crashActivity(a) {
  if (!a) return '';
  if (a.kind === 'exit') return t('Beim Beenden des Editors');
  if (a.kind === 'viewport') return t('Im Viewport');
  const label = { mode: 'Modus „{name}“', editor: 'Editor für „{name}“', tool: 'Werkzeug „{name}“' }[a.kind] || 'Fenster „{name}“';
  return t(label, { name: a.name });
}

function crashCulprit(c) {
  if (!c) return '';
  if (c.kind === 'plugin') return t('Plugin „{name}“', c);
  if (c.kind === 'project') return t('Code des Projekts ({name})', c);
  if (c.kind === 'game') return t('Spielcode des DevKits ({name})', c);
  return CRASH_AREAS[c.name] ? t(CRASH_AREAS[c.name]) : '';
}

// --- "KI fragen": Frage vorbereiten, im Backend bereinigen, Nutzer sieht und kann aendern ---
function crashPrompt(i) {
  const lines = [t('Mein Unreal Editor ist abgestürzt. Bitte erkläre mir die wahrscheinliche Ursache und wie ich das Problem Schritt für Schritt behebe.'), ''];
  const add = (label, value) => { if (value) lines.push(`${t(label)}: ${value}`); };
  add('Umgebung', [i.version && `Unreal Engine ${i.version}`, i.project].filter(Boolean).join(' – '));
  add('Art des Absturzes', t(CRASH_CATEGORIES[i.category][0]));
  add('Gerade offen', crashActivity(i.activity));
  add('Beteiligt', crashCulprit(i.culprit));
  add(i.assetSource === 'log' ? 'Zuletzt im Log genannt' : 'Betroffenes Asset', i.asset);
  add('Speicher', crashMemory(i));
  add('Wie oft', t('{n}×', { n: i.count }));
  if (i.message) lines.push('', `${t('Fehlermeldung')}:`, i.message.trim());
  if (i.log && i.log.length) {
    lines.push('', `${t('Letzte Warnungen und Fehler vor dem Absturz')}:`, ...i.log.map((l) => `${l.count > 1 ? `${l.count}× ` : ''}${l.text}`));
  }
  return lines.join('\n');
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return; } catch { /* Ersatzweg unten */ }
  const area = document.createElement('textarea');
  area.value = text;
  document.body.appendChild(area);
  area.select();
  try { document.execCommand('copy'); } catch { /* dann eben nur im Browser */ }
  area.remove();
}

async function openAskAi(item) {
  if (!item) return;
  const dlg = $('#aidlg');
  const area = $('#ai-text');
  area.value = (await call('ai_prompt', crashPrompt(item))).text;
  const close = () => { dlg.hidden = true; dlg.onclick = dlg.onkeydown = null; };
  dlg.hidden = false;
  area.scrollTop = 0;
  dlg.querySelectorAll('[data-ai-provider]').forEach((b) => {
    b.onclick = async () => {
      await copyText(area.value);
      try {
        await call('ask_ai', b.dataset.aiProvider, area.value);
        toast(t('Browser wird geöffnet – der Text liegt auch in der Zwischenablage.'));
      } catch (err) {
        toast(err.message);
      }
      close();
    };
  });
  $('#ai-close').onclick = close;
  dlg.onclick = (e) => { if (e.target === dlg) close(); };
  dlg.onkeydown = (e) => { if (e.key === 'Escape') close(); };
  dlg.querySelector('[data-ai-provider]').focus();
}

function crashMemory(i) {
  const f = i.facts || {};
  if (i.category === 'vram' && f.vramBudget) return t('Grafikspeicher: {used} von {total} belegt', { used: mb(f.vramUsed || 0), total: mb(f.vramBudget) });
  if (i.category === 'memory' && f.ramTotal) return t('Arbeitsspeicher: {used} von {total} belegt', { used: mb(f.ramUsed || 0), total: mb(f.ramTotal) });
  return '';
}

async function renderCrashes() {
  $('#meta').textContent = '';
  if (!state.crashes) {
    $('#content').innerHTML = `${toolTabs()}<p class="loading">${esc(t('Lese Absturzberichte …'))}</p>`;
    state.crashes = await call('crash_reports');
    if (state.view !== 'crashes') return;
  }
  const { items, total, projects } = state.crashes;
  $('#meta').textContent = t('{n} Berichte in {p} Projekten', { n: total, p: projects });
  const names = [...new Set(items.map((i) => i.project))].sort((a, b) => a.localeCompare(b));
  if (state.crashProject && !names.includes(state.crashProject)) state.crashProject = '';
  const shown = state.crashShown = items.filter((i) => (!state.crashProject || i.project === state.crashProject)
    && matches(`${t(CRASH_CATEGORIES[i.category][0])} ${i.message} ${i.project} ${i.asset || ''} ${crashCulprit(i.culprit)}`));
  const card = (i, n) => {
    const [title, what, steps] = CRASH_CATEGORIES[i.category];
    const facts = [
      ['Gerade offen', crashActivity(i.activity)],
      ['Beteiligt', crashCulprit(i.culprit)],
      [i.assetSource === 'log' ? 'Zuletzt im Log genannt' : 'Betroffenes Asset', i.asset],
      ['Speicher', crashMemory(i)],
    ].filter(([, v]) => v);
    const log = (i.log || []).map((l) => `${l.count > 1 ? `${l.count}× ` : ''}${l.text}`).join('\n');
    return `<article class="crash">
      <div class="crash-head"><h3>${esc(t(title))}</h3><span class="crash-count">${esc(t('{n}×', { n: i.count }))}</span></div>
      <p class="crash-tip">${esc(t(what))}</p>
      ${facts.length ? `<dl class="crash-facts">${facts.map(([k, v]) => `<div><dt>${esc(t(k))}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>` : ''}
      ${steps.length ? `<div class="crash-steps"><span>${esc(t('Das kannst du tun'))}</span><ol>${steps.map((x) => `<li>${esc(t(x))}</li>`).join('')}</ol></div>` : ''}
      <p class="crash-meta">${esc([i.project, i.version && `UE ${i.version}`, t('Zuletzt {ago}', { ago: ago(i.last) })].filter(Boolean).join(' · '))}</p>
      <div class="crash-foot"><div class="crash-more">
        ${log ? `<details><summary>${esc(t('Letzte Warnungen und Fehler vor dem Absturz'))}</summary><pre>${esc(log)}</pre></details>` : ''}
        ${i.message ? `<details><summary>${esc(t('Originalmeldung anzeigen'))}</summary><pre>${esc(i.message)}</pre></details>` : ''}
      </div><div class="crash-buttons">${i.category !== 'unreadable' ? `<button class="btn ghost small" data-ask-ai="${n}">${esc(t('KI fragen'))}</button>` : ''}
        <button class="btn ghost small" data-folder="${esc(i.folder)}">${esc(t('Ordner'))}</button></div></div></article>`;
  };
  $('#content').innerHTML = `${toolTabs()}<div class="crashes">
    <p class="note">${esc(t('Die Einordnung ist ein Anhaltspunkt und nennt nicht immer die genaue Ursache. Die Berichte werden nur hier auf deinem PC gelesen.'))}</p>
    ${names.length > 1 ? `<label class="field crash-filter"><span>${esc(t('Projekt'))}</span><select id="crash-project"><option value="">${esc(t('Alle Projekte'))}</option>${names.map((n) => `<option value="${esc(n)}" ${n === state.crashProject ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>` : ''}
    ${shown.length ? shown.map((i, n) => card(i, n)).join('') : `<p class="empty">${esc(t(total ? 'Nichts gefunden.' : 'Keine Absturzberichte gefunden.'))}</p>`}
  </div>`;
  const filter = $('#crash-project');
  if (filter) filter.onchange = () => { state.crashProject = filter.value; renderCrashes(); };
}

// --- Speicher aufraeumen: nur unkritische Ordner, nichts vorausgewaehlt ----------
const CLEAN_CATEGORIES = {
  logs: ['Protokolle', 'Protokolle des Editors. Werden bei jedem Start neu angelegt.'],
  crashes: ['Absturzberichte', 'Berichte zu früheren Abstürzen. Nur nötig, wenn du diese noch untersuchen möchtest.'],
  worldpartition: ['World-Partition-Protokolle', 'Protokolle vom Aufbau großer Maps. Werden bei Bedarf neu angelegt.'],
  shaderdebug: ['Shader-Debug-Daten', 'Daten für die Fehlersuche bei Shadern. Für die normale Arbeit nicht nötig.'],
  materialstats: ['Material-Statistiken', 'Auswertungen zu Materialien. Werden bei Bedarf neu angelegt.'],
  localcook: ['Lokale Cooks', 'Ergebnisse lokaler Cooks des DevKits (ModTools/Output). Werden beim nächsten Cook neu erzeugt.'],
  ddc: ['Shader- und Textur-Zwischenspeicher', 'Berechnete Shader und Texturen. Unreal erzeugt sie neu, das nächste Öffnen dauert dann aber deutlich länger.'],
};

// --- Werkzeuge: Aufraeumen und Abstuerze unter einem Menuepunkt, spaeter erweiterbar ---
const TOOL_VIEWS = ['cleanup', 'crashes'];

const TOOLS = [
  { view: 'cleanup', name: 'Speicher aufräumen', start: 'Suche starten',
    text: 'Findet Protokolle, Absturzberichte, Zwischenspeicher und lokale Cooks in deinen Projekten und DevKits, die Unreal bei Bedarf neu erzeugt. Du wählst selbst aus, was gelöscht wird.',
    hint: 'Die Suche löscht nichts.',
    icon: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>' },
  { view: 'crashes', name: 'Abstürze', start: 'Berichte einlesen',
    text: 'Liest die Absturzberichte deiner Projekte und DevKits, fasst gleiche Fehler zusammen und erklärt in einfachen Schritten, was du tun kannst.',
    hint: 'Alles bleibt auf deinem PC.',
    icon: '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.5"/>' },
];

function toolTabs() {  // Kopf der einzelnen Werkzeuge: zurueck zur Uebersicht
  return `<div class="tool-back"><button class="btn ghost small" data-view-go="tools">← ${esc(t('Alle Werkzeuge'))}</button></div>`;
}

function renderTools() {
  $('#meta').textContent = '';
  $('#content').innerHTML = `<div class="tools-grid">${TOOLS.map((x) => `<article class="tool-card">
      <svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true">${x.icon}</svg>
      <h2>${esc(t(x.name))}</h2>
      <p>${esc(t(x.text))}</p>
      <div class="tool-foot"><span>${esc(t(x.hint))}</span><button class="btn" data-tool-start="${x.view}">${esc(t(x.start))}</button></div>
    </article>`).join('')}</div>`;
}

function progressBox(title) {
  return `${toolTabs()}<div class="clean-progress"><h2>${esc(t(title))}</h2>
    <div class="track"><div class="fill js-clean-fill"></div></div>
    <p class="clean-step js-clean-step">${esc(t('Wird vorbereitet …'))}</p></div>`;
}

// Fragt den Stand ab, solange Suche oder Loeschen laufen (die Aufrufe laufen parallel)
async function watchCleanup(work) {
  let running = true;
  (async () => {
    while (running) {
      try { paintCleanProgress(await call('cleanup_progress')); } catch { /* naechster Versuch */ }
      await new Promise((r) => setTimeout(r, 300));
    }
  })();
  try { return await work; } finally { running = false; }
}

function paintCleanProgress(p) {
  if (!p.phase) return;
  // die Suche steht auf der Seite, das Loeschen im Popup
  const box = p.phase === 'clean' ? $('#cleandlg') : $('#content');
  const fill = box.querySelector('.js-clean-fill');
  const step = box.querySelector('.js-clean-step');
  if (!fill || !step) return;
  fill.style.width = `${p.total ? Math.min(100, (p.done / p.total) * 100) : 0}%`;
  const cat = CLEAN_CATEGORIES[p.category] ? t(CLEAN_CATEGORIES[p.category][0]) : '';
  if (p.phase === 'scan') {
    step.textContent = p.step === 'manifest'
      ? t('{project}: lese Epics Dateiliste, damit nichts von Epic gelöscht wird …', { project: p.project })
      : t('Durchsuche {project} ({n} von {m})', { project: p.project, n: Math.min(p.done + 1, p.total), m: p.total }) + (cat ? ` · ${cat}` : '');
  } else {
    step.textContent = t('{done} von {total} gelöscht · {files} Dateien', { done: mb(p.done / 1048576), total: mb(p.total / 1048576), files: n0(p.files) })
      + (p.project ? ` · ${cat} – ${p.project}` : '');
  }
}

async function renderCleanup() {
  $('#meta').textContent = '';
  if (!state.cleanup) {
    $('#content').innerHTML = progressBox('Suche nach aufräumbaren Ordnern …');
    // laeuft schon eine Suche (Tab gewechselt und zurueck), wird auf dieselbe gewartet
    state.cleanScan ||= watchCleanup(call('cleanup_scan')).finally(() => { state.cleanScan = null; });
    state.cleanup = await state.cleanScan;
    if (state.view !== 'cleanup' || state.cleanRun) return;
  }
  const groups = new Map();
  for (const i of state.cleanup.items) {
    if (!groups.has(i.dir)) groups.set(i.dir, { name: i.project, dir: i.dir, items: [] });
    groups.get(i.dir).items.push(i);
  }
  const sum = (g) => g.items.reduce((n, i) => n + i.mb, 0); // groesste Einsparung zuerst
  const row = (i) => {
    const [name, help] = CLEAN_CATEGORIES[i.category];
    return `<label class="clean-row"><input type="checkbox" data-clean="${esc(i.id)}" data-mb="${Number(i.mb)}">
      <span class="clean-text"><span class="clean-name">${esc(t(name))}</span><span class="clean-help">${esc(t(help))}</span></span>
      <span class="clean-size">${esc(mb(i.mb))}</span></label>`;
  };
  $('#content').innerHTML = `${toolTabs()}<div class="cleanup">
    <p class="note">${esc(t('Hier stehen nur Ordner, die Unreal neu erzeugt oder die reine Protokolle sind. Deine Arbeit, Autosaves und Einstellungen sind nicht dabei, und Dateien von Epic werden nie gelöscht. Das Löschen ist endgültig und geschieht auf eigene Gefahr.'))}</p>
    ${state.cleanup.editorRunning ? `<p class="note bad">${esc(t('Bitte zuerst den Unreal Editor schließen.'))}</p>` : ''}
    ${groups.size ? [...groups.values()].sort((a, b) => sum(b) - sum(a)).map((g) => `<section class="clean-group"><div class="home-head"><h2 title="${esc(g.dir)}">${esc(g.name)}</h2><span class="clean-dir">${esc(g.dir)}</span></div>${g.items.map(row).join('')}</section>`).join('')
    : `<p class="empty">${esc(t('Nichts zum Aufräumen gefunden.'))}</p>`}
    ${groups.size ? `<div class="clean-bar"><span id="clean-total"></span><button class="btn danger" id="clean-go" data-clean-go="1" disabled>${esc(t('Auswahl löschen'))}</button></div>` : ''}
  </div>`;
  updateCleanBar();
}

function updateCleanBar() {
  const picked = [...document.querySelectorAll('[data-clean]:checked')];
  const total = picked.reduce((sum, c) => sum + Number(c.dataset.mb), 0);
  const label = $('#clean-total');
  if (!label) return;
  label.textContent = t('Ausgewählt: {size}', { size: mb(total) });
  $('#clean-go').disabled = !picked.length || !!state.cleanup?.editorRunning;
}

async function runCleanup() {
  const picked = [...document.querySelectorAll('[data-clean]:checked')];
  const total = picked.reduce((sum, c) => sum + Number(c.dataset.mb), 0);
  if (!(await askConfirm(t('{size} endgültig löschen?\n\nDie Dateien kommen nicht in den Papierkorb. Das Löschen geschieht auf eigene Gefahr.', { size: mb(total) }), { ok: 'Endgültig löschen', danger: true }))) return;
  // Loeschen im Popup: laesst sich nicht wegklicken, solange es laeuft
  const dlg = $('#cleandlg');
  const ok = $('#cleandlg-ok');
  const fill = dlg.querySelector('.js-clean-fill');
  const step = dlg.querySelector('.js-clean-step');
  $('#cleandlg-title').textContent = t('Wird gelöscht …');
  fill.style.width = '0%';
  step.textContent = t('Wird vorbereitet …');
  ok.hidden = true;
  dlg.hidden = false;
  state.cleanRun = true;
  try {
    const res = await watchCleanup(call('cleanup_run', picked.map((c) => c.dataset.clean)));
    $('#cleandlg-title').textContent = t('Aufräumen fertig');
    fill.style.width = '100%';
    step.textContent = t(res.skipped ? '{size} freigegeben, {n} Dateien waren in Benutzung.' : '{size} freigegeben.', { size: mb(res.freedMb), n: res.skipped });
  } catch (err) {
    $('#cleandlg-title').textContent = t('Löschen nicht möglich');
    step.textContent = err.message;
  } finally {
    state.cleanRun = false;
  }
  ok.hidden = false;
  ok.focus();
  ok.onclick = () => { dlg.hidden = true; };
  state.cleanup = null; // Uebersicht hinter dem Popup gleich neu einlesen
  if (state.view === 'cleanup') render();
}

async function show(view, refresh = false) {
  const panel = (x) => x === 'store' || x === 'account'; // eigenes Browser-Element ueber dem Inhalt
  if (panel(state.view) && state.view !== view) call('store_hide', state.view);
  state.view = view;
  document.body.classList.toggle('store-mode', panel(view));
  document.body.classList.toggle('home-mode', view === 'home');
  document.querySelectorAll('.nav').forEach((b) => b.classList.toggle('active', b.dataset.view === view
    || (b.dataset.view === 'tools' && TOOL_VIEWS.includes(view))));
  $('#acc-open').classList.toggle('active', view === 'account');
  $('#view-title').textContent = t(TITLES[view]);
  try {
    if (refresh) {
      $('#content').innerHTML = `<p class="loading">${esc(t(view === 'crashes' ? 'Lese Absturzberichte …' : view === 'cleanup' ? 'Suche nach aufräumbaren Ordnern …' : view === 'projects' ? 'Suche Projekte …' : view === 'fab' && state.fabTab === 'local' ? 'Lese lokale Assets …' : 'Lade von Epic … das kann beim ersten Mal eine Minute dauern.'))}</p>`;
      if (view === 'fab' && state.fabTab === 'local') state.local = null; // nur neu nachmessen, kein Epic-Abruf
      else if (view === 'cleanup') state.cleanup = null;
      else if (view === 'crashes') state.crashes = null;
      else if (view === 'fab') await loadFab(true);
      else if (view === 'projects') await loadProjects(true);
      else await loadLibrary(true);
    } else if ((view === 'fab' && !state.fab) || (['games', 'unreal', 'home'].includes(view) && !state.library)) {
      $('#content').innerHTML = `<p class="loading">${esc(t('Lade Bibliothek …'))}</p>`;
    }
    await render();
    $('main').scrollTop = 0;
  } catch (err) {
    $('#content').innerHTML = `<p class="empty">${esc(t('Fehler beim Laden: {msg}', { msg: err.message }))}</p>`;
  }
}

// --- Einstellungen speichern ---------------------------------------------
async function saveSetting(changes) {
  const s = await call('save_settings', changes);
  if ('language' in changes) {
    LANG = s.language;
    applyStatic();
    rebuildEngineFilter();
    await refreshAccount();
  }
  if ('showGames' in changes) applyGamesVisibility(s.showGames);
  if ('useEpicVault' in changes) state.fab = null; // Fab-Liste mit/ohne Epic-Cache neu laden
  toast(t('Gespeichert.'));
  if (state.view === 'settings') show('settings');
}

$('#content').addEventListener('change', (e) => { if (e.target.closest('[data-clean]')) updateCleanBar(); });
$('#content').addEventListener('change', async (e) => {
  const el = e.target.closest('[data-setting]');
  if (!el) return;
  const value = el.type === 'checkbox' ? el.checked : el.value;
  try { await saveSetting({ [el.dataset.setting]: ['maxWorkers', 'speedLimit'].includes(el.dataset.setting) ? Number(value) : value }); }
  catch (err) { toast(err.message); show('settings'); }
});

// --- Ereignisse ----------------------------------------------------------
document.querySelectorAll('.nav').forEach((b) => (b.onclick = () => show(b.dataset.view)));
$('#acc-open').onclick = () => show('account');
$('#app-version').onclick = () => show('home'); // dort steht ein Launcher-Update ganz oben
$('#refresh').onclick = () => show(state.view, true);
let searchTimer;
$('#search').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(render, 150); };
$('#filter-engine').onchange = render;
$('#filter-type').onchange = () => { $('#filter-cat').value = ''; rebuildFabFilters(); render(); };
$('#filter-cat').onchange = render;
$('#filter-sort').onchange = render;
$('#filter-state').onchange = render;

$('#content').addEventListener('click', async (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  try {
    if (b.dataset.folder) await call('open_folder', b.dataset.folder);
    else if (b.dataset.url?.startsWith('https://www.fab.com/')) openInStore('fab', b.dataset.url);
    else if (b.dataset.url) await call('open_url', b.dataset.url);
    else if (b.dataset.storeTab) {
      if (b.dataset.storeTab === state.storeTab) return;
      state.storeTab = b.dataset.storeTab;
      const home = (await call('store_home', state.storeTab)).url;
      state.storeOpened[state.storeTab] = true;
      document.querySelectorAll('[data-store-tab]').forEach((x) => x.classList.toggle('active', x.dataset.storeTab === state.storeTab));
      await call('store_show', home, storeRect());
    }
    else if (b.dataset.storeGo) await call('store_go', b.dataset.storeGo, state.view);
    else if (b.dataset.storeWindow) await call('open_store', state.storeTab);
    else if (b.dataset.launch) { await call('launch_engine', b.dataset.launch); toast(t('Unreal Editor wird gestartet …')); }
    else if (b.dataset.start) {
      toast(t('{title} wird gestartet …', { title: b.dataset.title || '' }));
      await call('launch_app', b.dataset.start);
      if (state.view === 'home') setTimeout(render, 800);
    }
    else if (b.dataset.checkUpdates) {
      state.checking = true;
      render();
      try { await checkSelfUpdate(true); state.library = await call('check_updates', true); } finally { state.checking = false; render(); }
    }
    else if (b.dataset.selfUpdate) openSelfUpdate();
    else if (b.dataset.goAsset) await goToAsset(b.dataset.goAsset);
    else if (b.dataset.goLocal) { state.fabTab = 'local'; await show('fab'); }
    else if (b.dataset.install) await startInstall(b.dataset.install);
    else if (b.dataset.update) await openPreview(b.dataset.update);
    else if (b.dataset.fab) await openFab(b.dataset.fab);
    else if (b.dataset.options) await openOptions(b.dataset.options);
    else if (b.dataset.repair) { await call('repair', b.dataset.repair); toast(t('Prüfung in der Warteschlange.')); await pollDownloads.once(); }
    else if (b.dataset.uninstall) {
      if (!(await askConfirm(t('„{title}“ wirklich entfernen?\n\nAlle Dateien im Installationsordner werden gelöscht.', { title: b.dataset.title }), { ok: 'Entfernen', danger: true }))) return;
      await call('uninstall', b.dataset.uninstall);
      await pollDownloads.once();
    }
    else if (b.dataset.pause) { await call('pause_download', Number(b.dataset.pause)); await pollDownloads.once(); }
    else if (b.dataset.resume) { await call('resume_download', Number(b.dataset.resume)); await pollDownloads.once(); }
    else if (b.dataset.cancel) {
      const what = {
        install: 'Die halb fertige Installation wird gelöscht.',
        fab: 'Die Zwischendateien werden gelöscht.',
        update: 'Die Installation ist danach evtl. unvollständig – später „Update“ oder „Prüfen“ ausführen.',
        modify: 'Die Installation ist danach evtl. unvollständig – später „Update“ oder „Prüfen“ ausführen.',
        repair: 'Die Installation ist danach evtl. unvollständig – später erneut „Prüfen“.',
      }[b.dataset.action];
      if (!(await askConfirm(t('Wirklich abbrechen?\n\n{what}\n\nZum späteren Weitermachen stattdessen „Pause“ nutzen.', { what: what ? t(what) : '' }), { ok: 'Ja, abbrechen', cancel: 'Weitermachen', danger: true }))) return;
      await call('cancel_download', Number(b.dataset.cancel));
      await pollDownloads.once();
    }
    else if (b.dataset.logToggle) {
      const id = Number(b.dataset.logToggle);
      if (state.openLogs.has(id)) state.openLogs.delete(id); else state.openLogs.add(id);
      render();
    }
    else if (b.dataset.clear) { await call('clear_downloads'); await pollDownloads.once(); }
    else if (b.dataset.chooseDir) { await call('choose_install_dir'); render(); }
    else if (b.dataset.viewGo) show(b.dataset.viewGo);
    else if (b.dataset.addKind) await openAdd(b.dataset.addKind);
    else if (b.dataset.adoptKind) await openAdopt(b.dataset.adoptKind);
    else if (b.dataset.cleanGo) await runCleanup();
    else if (b.dataset.openProject) { await call('open_project', b.dataset.openProject); toast(t('Unreal Editor wird gestartet …')); }
    else if (b.dataset.projectAssets) {
      state.fabProject = state.projects.items.find((p) => p.uproject === b.dataset.projectAssets) || null;
      show('fab');
    }
    else if (b.dataset.deleteProject) await openDelete(b.dataset.deleteProject);
    else if (b.dataset.dlcs) openDlcs(b.dataset.dlcs);
    else if (b.dataset.askAi) openAskAi(state.crashShown?.[Number(b.dataset.askAi)]);
    else if (b.dataset.toolStart) {  // frisch starten, kein altes Ergebnis zeigen
      if (b.dataset.toolStart === 'cleanup' && !state.cleanScan) state.cleanup = null;
      if (b.dataset.toolStart === 'crashes') state.crashes = null;
      show(b.dataset.toolStart);
    }
    else if (b.dataset.fabTab) { state.fabTab = b.dataset.fabTab; await render(); $('main').scrollTop = 0; }
    else if (b.dataset.delLocal) await deleteLocal(b.dataset.delLocal);
    else if (b.dataset.renameProject) {
      const p = state.projects.items.find((x) => x.uproject === b.dataset.renameProject);
      const name = await askConfirm(t('Anzeigename für „{name}“\n\nDer Name gilt nur im Launcher. Projektordner und Projektdatei bleiben unverändert. Leer lassen für den Originalnamen.', { name: p.name }),
        { ok: 'Speichern', input: { value: p.displayName } });
      if (name === null) return;
      state.projects = await call('rename_project', p.uproject, name);
      render();
    }
    else if (b.dataset.fabType !== undefined || b.dataset.fabCat !== undefined) {
      $('#filter-type').value = b.dataset.fabType ?? b.dataset.fabCatType ?? '';
      rebuildFabFilters();
      $('#filter-cat').value = b.dataset.fabCat || '';
      render();
      $('main').scrollTop = 0;
    }
    else if (b.dataset.fabProjectClear) { state.fabProject = null; render(); }
    else if (b.dataset.hideProject) {
      if (!(await askConfirm(t('„{name}“ aus der Liste ausblenden?\n\nDas Projekt selbst bleibt unverändert auf der Festplatte. Über „Projekt hinzufügen …“ holst du es zurück.', { name: b.dataset.name }), { ok: 'Ausblenden' }))) return;
      state.projects = await call('hide_project', b.dataset.hideProject);
      render();
    }
    else if (b.dataset.addProject || b.dataset.addProjectFolder) {
      const res = await call(b.dataset.addProject ? 'add_project' : 'add_project_folder');
      if (!res.cancelled) { state.projects = res; render(); }
    }
    else if (b.dataset.pickSetting) {
      const p = await call('choose_folder');
      if (!p.cancelled) await saveSetting({ [b.dataset.pickSetting]: p.path });
    }
    else if (b.dataset.resetSetting) await saveSetting({ [b.dataset.resetSetting]: null });
  } catch (err) { toast(err.message); }
});

// Beim Start (und dann stuendlich) nachsehen, ob es neue Versionen gibt
// Beim Start immer frisch bei Epic nachsehen, danach stuendlich
async function autoCheckUpdates(atStart = false) {
  state.checking = true;
  if (state.view === 'home') render();
  try {
    // Beim Start immer frisch bei GitHub nachsehen, danach hoechstens alle 6 Stunden
    await checkSelfUpdate(atStart === true);
    if (state.self?.available && state.view === 'home') render();  // nicht auf die langsamere Epic-Abfrage warten
    if (state.self?.available && atStart === true && state.view !== 'home') toast(t('Update auf {v} verfügbar', { v: state.self.latest }));
    const data = await call('check_updates', atStart === true);
    if (data) {
      state.library = data;
      if (data.newItems?.length) toast(t('Neu verfügbar: {list}', { list: data.newItems.join(', ') }));
      const upd = data.items.filter((i) => i.updateAvailable && i.installed);
      if (upd.length && state.view !== 'home') toast(t('Update verfügbar: {list}', { list: upd.map((i) => i.title).join(', ') }));
    }
  } catch { /* still - beim naechsten Mal */ }
  state.checking = false;
  if (['games', 'unreal', 'home'].includes(state.view)) render();
  setTimeout(autoCheckUpdates, 3600 * 1000);
}

async function boot(backend) {
  api = backend;
  const settings = await call('settings');
  await setLanguage(detectLanguage(settings.language));
  $('.nav[data-view="games"]').hidden = !settings.showGames;
  pollDownloads();
  if (await refreshAccount()) {
    await show('home');
    autoCheckUpdates(true);
  } else {
    checkSelfUpdate(true);  // Versionsnummer unten links auch ohne Anmeldung
  }
}

window.addEventListener('pywebviewready', () => boot(window.pywebview.api));

// Entwicklungs-Vorschau im Browser (dev_server.py): gleiche Api ueber HTTP.
// Nur auf dem Vorschau-Port - das App-Fenster laeuft ebenfalls ueber 127.0.0.1,
// dort darf dieser Weg nie anspringen (sonst zwei Ladevorgaenge im Wettlauf).
if (location.port === '8765' && ['127.0.0.1', 'localhost'].includes(location.hostname)) {
  boot(new Proxy({}, {
    get: (_, name) => async (...args) =>
      (await fetch(`/api/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args) })).json(),
  }));
}
