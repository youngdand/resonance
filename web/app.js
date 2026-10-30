function toast(msg, error = false) {
  $('#toast').textContent = msg;
  $('#toast').className = 'show' + (error ? ' error' : '');
  clearTimeout(toastTimer);
  if (error) {
    recordUiError(msg);
    return;
  }
  toastTimer = setTimeout(() => ($('#toast').className = ''), 5000);
}
function failed(s) {
  return TransferState.failed(s);
}
function complete(s) {
  return TransferState.terminal(s);
}
function succeeded(s) {
  return TransferState.succeeded(s);
}
let clearingTransfers = false;
async function clearCompleted(direction) {
  if (clearingTransfers) return;
  clearingTransfers = true;
  render();
  try {
    let count = 0,
      warnings = [];
    if (S.demo) {
      if (direction === 'downloads') {
        for (const r of S.requests)
          if (succeeded(r.status) && !r.archived) {
            r.archived = true;
            count++;
          }
        persistDemoQueue();
      } else {
        count = S.uploads.filter((f) => succeeded(f.state)).length;
        S.uploads = S.uploads.filter((f) => !succeeded(f.state));
      }
    } else {
      const result = await api('clear-completed', { direction });
      count = result.cleared;
      warnings = result.warnings || [];
      if (direction === 'downloads') S.requests = await api('sync');
      else await loadUploads(true);
    }
    toast(
      warnings.length
        ? warnings.join(' ')
        : `${count} completed ${direction} cleared. Music files and failed transfers kept.`,
      !!warnings.length,
    );
  } catch (e) {
    toast(e.message, true);
  } finally {
    clearingTransfers = false;
    render();
  }
}
function nav() {
  const items = [
    ['foryou', 'For you', 'sparkles'],
    ['search', 'Search', 'search'],
    ['downloads', 'Downloads', 'downloads'],
    ['library', 'My collection', 'library'],
    ['browse', 'Browse users', 'browse'],
    ['uploads', 'Uploads & sharing', 'uploads'],
    ['chat', 'Chat', 'chat'],
  ];
  $('#navigation').innerHTML = items
    .map(
      ([p, label, i]) =>
        `<button class="nav-item ${S.page === p ? 'active' : ''}" data-page="${p}">${icon(i)}<span class="nav-label">${label}</span>${p === 'downloads' && S.requests.filter((r) => !complete(r.status) && !['Cancelled', 'Replaced'].includes(r.status)).length ? `<span class="count">${S.requests.filter((r) => !complete(r.status) && !['Cancelled', 'Replaced'].includes(r.status)).length}</span>` : ''}</button>`,
    )
    .join('');
  $('#crumb').textContent = items.find((i) => i[0] === S.page)?.[1] || 'Discover';
  $('#demoToggle').textContent = S.demo ? 'Demo mode · on' : 'Try demo';
  $('#connection').className = 'connection' + (S.connected && !S.demo ? ' connected' : '');
  $('#connection').innerHTML =
    `<i></i>${S.demo ? 'Sample data' : S.connected ? 'slskd connected' : 'Not connected'}`;
  $('#libraryCount').textContent = S.demo
    ? '11,284 demo tracks'
    : S.trackCount
      ? S.trackCount.toLocaleString() + ' tracks indexed'
      : 'Your collection';
  $('#librarySub').textContent = S.demo
    ? 'Sample collection'
    : S.scan.running
      ? 'Scanning your folders…'
      : S.trackCount
        ? 'Indexed on this computer'
        : 'Connect your music folders';
  $('#settingsNav').innerHTML = icon('settings') + '<span class="nav-label">Settings</span>';
}
function go(page) {
  S.page = ['foryou', 'search', 'downloads', 'library', 'browse', 'uploads', 'chat'].includes(page)
    ? page
    : 'search';
  location.hash = S.page;
  S.limit = 100;
  render();
  if (S.page === 'library' && !S.demo) loadLibrary();
  if (S.page === 'uploads') loadUploads();
  if (S.page === 'chat') loadConversations();
  if (S.page === 'foryou') loadDiscovery();
}
function heading(eye, name, sub, action = '') {
  return `<div class="page-heading"><div><div class="eyebrow">${eye}</div><h1>${name}</h1><p class="subtitle">${sub}</p></div>${action}</div>`;
}
function demoNotice() {
  return S.demo
    ? '<div class="notice">' +
        icon('music') +
        'Demo workspace · sample results, collection and transfers. Nothing is downloading.<button data-action="live">Connect your client</button></div>'
    : '';
}
function filters() {
  const f = S.settings.formats || [];
  return `<div class="filter-bar"><span class="filter-label">${icon('filter')} Show formats</span>${['flac', 'mp3', 'm4a', 'wav'].map((x) => `<button class="chip ${f.includes(x) ? 'active' : ''}" data-format="${x}" aria-pressed="${f.includes(x)}">${f.includes(x) ? icon('check') : icon('plus')}${x.toUpperCase()}</button>`).join('')}<button class="chip ${f.some((x) => !['flac', 'mp3', 'm4a', 'wav'].includes(x)) ? 'active' : ''}" data-action="otherFormats">Other formats</button><select class="select" id="minBitrate" aria-label="Minimum lossy bitrate">${[0, 128, 192, 256, 320].map((x) => `<option value="${x}" ${Number(S.settings.minBitrate) === x ? 'selected' : ''}>${x ? 'MP3/AAC ≥ ' + x + ' kbps' : 'Any bitrate'}</option>`).join('')}</select><span class="filter-spacer"></span><label class="switch-label"><input id="hideOwned" type="checkbox" ${S.settings.hideOwned ? 'checked' : ''}>Hide owned</label></div>`;
}
async function loadState() {
  const d = await api('state');
  S.token = d.token;
  S.serverVersion = d.version || 'older than 0.3.1';
  checkBackendVersion();
  S.trackCount = d.tracks;
  S.scan = d.scan;
  S.history = d.searches;
  if (!S.demo) {
    S.settings = d.settings;
    S.requests = d.requests;
  }
  return d;
}
function demoSetup() {
  resetFeatureState();
  resetDiscoveryState(true);
  clearTimeout(pollTimer);
  searchGeneration++;
  S.searching = false;
  S.recovery = null;
  S.replaces = null;
  browseCache.clear();
  S.demo = true;
  localStorage.setItem('resonance-demo', 'true');
  S.settings = JSON.parse(localStorage.getItem('resonance-demo-settings') || 'null') || {
    formats: ['flac', 'mp3', 'm4a'],
    minBitrate: 0,
    hideOwned: false,
    blocked: [],
  };
  S.query = 'Massive Attack';
  S.files = demoFiles.filter((f) => f.filename.includes('Massive Attack')).map((f) => ({ ...f }));
  S.requests = JSON.parse(localStorage.getItem('resonance-demo-requests') || 'null') || [
    {
      id: 'demo-denied',
      query: 'Massive Attack Teardrop',
      file: { ...demoFiles[2], username: 'quiet_signals' },
      status: 'Rejected, User denied',
      created: Date.now() / 1000 - 3600,
      attempts: [],
    },
    {
      id: 'demo-complete',
      query: 'Portishead Glory Box',
      file: { ...demoFiles.find((f) => title(f) === 'Glory Box') },
      status: 'Completed, Succeeded',
      created: Date.now() / 1000 - 7200,
      attempts: [],
    },
  ];
  S.browseFiles = [];
  S.browseUser = '';
  S.browsePath = '';
  render();
}
async function live() {
  resetFeatureState();
  resetDiscoveryState(false);
  clearTimeout(pollTimer);
  searchGeneration++;
  S.demo = false;
  S.searching = false;
  S.files = [];
  S.query = '';
  S.recovery = null;
  S.replaces = null;
  S.browseFiles = [];
  browseCache.clear();
  localStorage.setItem('resonance-demo', 'false');
  await loadState();
  render();
  openSettings();
}
async function persist() {
  if (S.demo) {
    localStorage.setItem('resonance-demo-settings', JSON.stringify(S.settings));
    return;
  }
  await api('settings', S.settings);
}
function persistDemoQueue() {
  localStorage.setItem('resonance-demo-requests', JSON.stringify(S.requests));
}
async function search(query) {
  query = query.trim();
  if (!query) return;
  clearTimeout(pollTimer);
  const generation = ++searchGeneration;
  S.searchGroupPage = 0;
  S.query = query;
  S.searching = true;
  S.files = [];
  S.limit = 100;
  S.page = 'search';
  location.hash = 'search';
  render();
  if (S.demo) {
    S.files = demoFiles
      .filter((f) =>
        query
          .toLowerCase()
          .split(/\s+/)
          .every((w) => f.filename.toLowerCase().includes(w)),
      )
      .map((f) => ({ ...f }));
    S.searching = false;
    markAttempted();
    render();
    return;
  }
  try {
    const d = await api('search', { query });
    if (generation !== searchGeneration) return;
    S.searchId = d.id;
    S.history.unshift({ id: d.id, query });
    let count = 0;
    const poll = async () => {
      try {
        const d = await api('results?id=' + encodeURIComponent(S.searchId));
        if (generation !== searchGeneration) return;
        S.files = d.files;
        markAttempted();
        count++;
        S.searching = !(d.isComplete || /completed|cancelled/i.test(d.state) || count >= 30);
        if (S.page === 'search') render();
        if (S.searching) pollTimer = setTimeout(poll, 2000);
        else if (!d.isComplete && !/completed|cancelled/i.test(d.state))
          toast('Polling paused after one minute. Search again for fresh sources.');
      } catch (e) {
        if (generation !== searchGeneration) return;
        S.searching = false;
        toast(e.message, true);
        if (S.page === 'search') render();
      }
    };
    pollTimer = setTimeout(poll, 1200);
  } catch (e) {
    S.searching = false;
    toast(e.message, true);
    render();
  }
}
function markAttempted() {
  if (!S.recovery) return;
  const fs = [S.recovery.file, ...(S.recovery.attempts || [])];
  for (const f of S.files)
    if (fs.some((a) => a.username === f.username && a.filename === f.filename))
      f.localStatus = 'Previously tried';
}
const pendingQueueFiles = new Set();
async function queue(f, albumConfirmed = false, albumRoot = null) {
  if (!f) return;
  const queueKey = f.username + '|' + f.filename;
  if (pendingQueueFiles.has(queueKey)) return;
  if (
    S.recovery &&
    fmt(f) !== fmt(S.recovery.file) &&
    !confirm(
      `The original file was ${fmt(S.recovery.file).toUpperCase()}. This source is ${fmt(f).toUpperCase()}. Queue it anyway?`,
    )
  )
    return;
  if (
    !albumConfirmed &&
    f.ownership === 'owned' &&
    !confirm('This track appears to be in your collection. Download another copy?')
  )
    return;
  if (
    S.recovery &&
    !confirm(
      `Replace the source for “${title(S.recovery.file)}” with “${title(f)}” from ${f.username}? Check that this is the same track and edition.`,
    )
  )
    return;
  pendingQueueFiles.add(queueKey);
  try {
    if (S.demo) {
      if (
        S.requests.some(
          (r) =>
            r.file.username === f.username &&
            r.file.filename === f.filename &&
            !['Cancelled', 'Replaced'].includes(r.status),
        )
      )
        throw Error('This source is already queued.');
      let attempts = [];
      if (S.recovery) {
        S.recovery.status = 'Replaced';
        attempts = [...(S.recovery.attempts || []), S.recovery.file];
      }
      S.requests.push({
        id: 'demo-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2),
        query: S.recovery?.query || S.query || artist(f) + ' ' + album(f),
        file: { ...f },
        status: 'Queued (demo)',
        created: Date.now() / 1000,
        attempts,
      });
      persistDemoQueue();
    } else {
      const r = await api('queue', {
        file: f,
        query: S.recovery?.query || S.query || artist(f) + ' ' + album(f),
        replaces: S.replaces,
        albumRoot,
      });
      if (S.recovery && r.status === 'Queued') S.recovery.status = 'Replaced';
      if (!S.requests.some((x) => x.id === r.id)) S.requests.push(r);
      f.localStatus = r.status;
    }
    if (S.demo) f.localStatus = 'Queued';
    S.recovery = null;
    S.replaces = null;
    toast(
      S.demo
        ? 'Added to demo queue. No download was started.'
        : f.localStatus === 'Unconfirmed'
          ? 'Request saved; engine acceptance is unconfirmed. Reconcile it on Downloads.'
          : 'Download request tracked in the engine.',
    );
    render();
  } catch (e) {
    toast(e.message, true);
  } finally {
    pendingQueueFiles.delete(queueKey);
  }
}
async function queueAlbum(f, scope) {
  await fullAlbum(f, scope);
}
async function browsePeer(user) {
  if (!user.trim()) return;
  const oldUser = S.browseUser;
  if (oldUser && S.browseFiles.length)
    browseCache.set(oldUser, {
      files: S.browseFiles,
      path: S.browsePath,
      term: S.browseTerm,
      view: S.view,
    });
  const cached = browseCache.get(user.trim());
  if (cached) {
    S.browseUser = user.trim();
    S.browseFiles = cached.files;
    S.browsePath = cached.path;
    S.browseTerm = cached.term;
    S.view = cached.view;
    go('browse');
    return;
  }
  S.browseUser = user.trim();
  S.browsePath = '';
  S.browseTerm = '';
  S.page = 'browse';
  S.view = 'albums';
  location.hash = 'browse';
  S.browseFiles = [];
  render();
  $('#footerStatus').textContent = 'Requesting shared files…';
  try {
    S.browseFiles = S.demo
      ? demoFiles.filter((f) => f.username === S.browseUser).map((f) => ({ ...f }))
      : (await api('browse?username=' + encodeURIComponent(S.browseUser))).files;
    render();
    if (!S.browseFiles.length)
      toast('No shared files returned. The user may be offline or restricting access.', true);
  } catch (e) {
    toast(e.message, true);
    render();
  }
}
async function loadLibrary(q = S.libraryQuery || '', autoSync = true) {
  const generation = UIState.next('library');
  if (q !== S.libraryQuery) S.libraryOffset = 0;
  S.libraryQuery = q;
  if (
    autoSync &&
    S.settings.hasKey &&
    S.settings.librarySource !== 'folders' &&
    !S.scan.running &&
    Date.now() - (S.librarySyncAt || 0) > 60000
  ) {
    S.librarySyncAt = Date.now();
    api('library-sync', {})
      .then((scan) => {
        S.scan = scan;
        watchScan();
      })
      .catch((error) => {
        S.scan.warning = error.message;
      });
  }
  try {
    const page = await api(
      'library?q=' + encodeURIComponent(q) + '&offset=' + (S.libraryOffset || 0) + '&limit=100',
    );
    if (!UIState.current('library', generation)) return;
    S.library = page.items;
    S.libraryTotal = page.total;
    S.libraryAlbums = page.albums;
    if (S.page === 'library') render();
  } catch (error) {
    if (UIState.current('library', generation)) toast(error.message, true);
  }
}
function openSettings() {
  $('#librarySource').value = S.settings.librarySource || 'slskd';
  $('#slskdConfig').value = S.settings.slskdConfig || '';
  $('#slskUrl').value = S.settings.url || 'http://127.0.0.1:5030';
  $('#slskKey').value = '';
  $('#slskKey').placeholder = S.settings.hasKey
    ? 'Saved key · leave blank to keep'
    : 'Paste your slskd API key';
  $('#roots').value = (S.settings.roots || []).join('\n');
  $('#blocked').value = (S.settings.blocked || []).join('\n');
  $('#settingsStatus').textContent = S.demo
    ? 'Settings here configure your live client. Demo filters are stored separately.'
    : '';
  $('#settingsDialog').showModal();
}
async function sync() {
  if (S.demo) {
    toast('Demo transfers are simulated. Connect slskd for live status.');
    return;
  }
  try {
    S.requests = await api('sync');
    render();
    toast('Transfer status refreshed.');
  } catch (e) {
    toast(e.message, true);
  }
}
document.addEventListener('click', async (e) => {
  const t = e.target.closest('button');
  if (!t) return;
  try {
    if (t.dataset.libraryPage !== undefined) {
      S.libraryOffset = Number(t.dataset.libraryPage);
      await loadLibrary(S.libraryQuery || '', false);
      return;
    }
    if (t.dataset.history) {
      await search(t.dataset.history);
      return;
    }
    if (t.dataset.page) {
      go(t.dataset.page);
      return;
    }
    if (t.dataset.view) {
      S.view = t.dataset.view;
      render();
      return;
    }
    if (t.dataset.format) {
      const f = t.dataset.format;
      S.settings.formats = S.settings.formats.includes(f)
        ? S.settings.formats.filter((x) => x !== f)
        : [...S.settings.formats, f];
      await persist();
      render();
      return;
    }
    if (t.dataset.user) {
      await browse(t.dataset.user);
      return;
    }
    if (t.hasAttribute('data-folder')) {
      S.browsePath = t.dataset.folder;
      S.limit = 100;
      render();
      return;
    }
    if (t.dataset.queue !== undefined) {
      await queue(
        (t.dataset.scope === 'browse' ? S.browseFiles : S.files)[Number(t.dataset.queue)],
      );
      return;
    }
    if (t.dataset.album !== undefined) {
      await queueAlbum(
        (t.dataset.scope === 'browse' ? S.browseFiles : S.files)[Number(t.dataset.album)],
        t.dataset.scope,
      );
      return;
    }
    if (t.dataset.reconcile) {
      await api('reconcile', { id: t.dataset.reconcile });
      await sync();
      return;
    }
    if (t.dataset.recover) {
      S.view = 'tracks';
      S.recovery = S.requests.find((r) => r.id === t.dataset.recover);
      S.replaces = S.recovery.id;
      await search(S.recovery.query || artist(S.recovery.file) + ' ' + title(S.recovery.file));
      return;
    }
    if (t.dataset.cancel) {
      if (confirm('Cancel this transfer in slskd?')) {
        await api('cancel', { id: t.dataset.cancel });
        await sync();
      }
      return;
    }
    const a = t.dataset.action;
    if (a === 'demo') {
      demoSetup();
      return;
    }
    if (a === 'live') {
      await live();
      return;
    }
    if (a === 'settings') openSettings();
    if (a === 'example') await search('Massive Attack');
    if (a === 'sync') await sync();
    if (a === 'clearDownloads') await clearCompleted('downloads');
    if (a === 'more') {
      S.limit += 100;
      render();
    }
    if (a === 'clearRecovery') {
      S.recovery = null;
      S.replaces = null;
      S.files.forEach((f) => {
        if (f.localStatus === 'Previously tried') delete f.localStatus;
      });
      render();
    }
    if (a === 'otherFormats') {
      const formats = ['aiff', 'ogg', 'opus', 'aac', 'ape', 'wma', 'alac'];
      const on = formats.every((x) => S.settings.formats.includes(x));
      S.settings.formats = S.settings.formats
        .filter((x) => !formats.includes(x))
        .concat(on ? [] : formats);
      await persist();
      render();
      toast(on ? 'Other formats excluded.' : 'AIFF, OGG, Opus, AAC, APE, WMA and ALAC included.');
    }
    if (a === 'scan') {
      if (S.demo) {
        toast('Demo collection is a sample. Connect your client to scan real folders.');
        return;
      }
      S.scan = await api('scan', {});
      S.librarySyncAt = Date.now();
      render();
      toast(
        S.settings.librarySource === 'folders'
          ? 'Scanning your music folders…'
          : 'Rescanning slskd, then updating your collection…',
      );
      watchScan();
    }
  } catch (err) {
    toast(err.message, true);
  }
});
document.addEventListener('submit', async (e) => {
  if (e.target.id === 'searchForm') {
    e.preventDefault();
    await search($('#query').value);
  }
  if (e.target.id === 'browseForm') {
    e.preventDefault();
    await browse($('#browseUsername').value);
  }
  if (e.target.id === 'withinForm') {
    e.preventDefault();
    S.browseTerm = $('#withinQuery').value;
    render();
  }
  if (e.target.id === 'libraryForm') {
    e.preventDefault();
    const q = $('#libraryQuery').value;
    if (S.demo) {
      S.library = [];
      toast('This demo shows a small sample of the collection.');
      return;
    }
    await loadLibrary(q);
  }
});
document.addEventListener('change', async (e) => {
  if (e.target.id === 'hideOwned' || e.target.id === 'minBitrate') {
    if (e.target.id === 'hideOwned') S.settings.hideOwned = e.target.checked;
    else S.settings.minBitrate = Number(e.target.value);
    try {
      await persist();
      render();
    } catch (err) {
      toast(err.message, true);
    }
  }
});
$('#settingsNav').onclick = openSettings;
$('#avatar').onclick = openSettings;
$('#closeSettings').onclick = () => $('#settingsDialog').close();
$('#demoToggle').onclick = async () => (S.demo ? live() : demoSetup());
$('#settingsForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const d = {
      librarySource: $('#librarySource').value,
      slskdConfig: $('#slskdConfig').value.trim(),
      url: $('#slskUrl').value.trim(),
      key: $('#slskKey').value,
      roots: $('#roots')
        .value.split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
      blocked: $('#blocked')
        .value.split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
    };
    await api('settings', d);
    S.demo = false;
    localStorage.setItem('resonance-demo', 'false');
    searchGeneration++;
    clearTimeout(pollTimer);
    S.searching = false;
    S.files = [];
    S.query = '';
    S.browseFiles = [];
    browseCache.clear();
    S.recovery = null;
    S.replaces = null;
    await loadState();
    $('#settingsDialog').close();
    render();
    toast('Settings saved. Open My collection to import your library.');
    checkConnection();
  } catch (err) {
    $('#settingsStatus').textContent = err.message;
  }
};
$('#testConnection').textContent = 'Test saved connection';
$('#testConnection').onclick = async () => {
  const el = $('#settingsStatus');
  el.textContent = 'Testing saved connection…';
  try {
    await api('ping');
    S.connected = true;
    el.textContent = 'Connected successfully. This tests your saved settings; save changes first.';
    nav();
  } catch (e) {
    el.textContent = e.message;
  }
};
async function checkConnection() {
  if (S.demo || !S.settings.hasKey) return;
  try {
    await api('ping');
    S.connected = true;
    nav();
  } catch {
    S.connected = false;
    nav();
  }
}
function watchScan() {
  clearTimeout(scanTimer);
  scanTimer = setTimeout(async () => {
    try {
      await loadState();
      if (S.page === 'library') {
        await loadLibrary(S.libraryQuery || '', false);
      } else nav();
      if (S.scan.running) watchScan();
      else {
        S.librarySyncAt = Date.now();
        toast(
          S.scan.error || `Scan finished. ${S.trackCount.toLocaleString()} tracks indexed.`,
          !!S.scan.error,
        );
      }
    } catch (e) {
      toast(e.message, true);
    }
  }, 1500);
}
document.addEventListener('keydown', (e) => {
  if (
    e.key === '/' &&
    !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName) &&
    !$('#settingsDialog').open
  ) {
    e.preventDefault();
    if (S.page !== 'search') go('search');
    $('#query')?.focus();
  }
  if ((e.ctrlKey || e.metaKey) && e.key === ',') {
    e.preventDefault();
    if (!$('#settingsDialog').open) openSettings();
  }
});
window.addEventListener('hashchange', () => {
  const p = location.hash.slice(1);
  if (p !== S.page) go(p);
});
window.addEventListener('load', async () => {
  try {
    await loadState();
    if (S.demo) demoSetup();
    else render();
    if (S.scan.running) watchScan();
    if (S.page === 'library' && !S.demo) loadLibrary();
    if (S.page === 'foryou') loadDiscovery();
    checkConnection();
  } catch (e) {
    render();
    toast('Start Resonance with Start-Resonance.cmd to enable its local service.', true);
  }
});

function render() {
  renderWithBrowseScroll(renderCore, () => $('.folder-sidebar'));
}
