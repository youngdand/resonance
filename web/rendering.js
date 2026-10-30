function status(f) {
  const local = f.localStatus;
  let label = local
    ? succeeded(local)
      ? 'Downloaded'
      : failed(local)
        ? 'Failed'
        : /cancelled/i.test(local)
          ? 'Cancelled'
          : /replaced/i.test(local)
            ? 'Replaced'
            : /unconfirmed|missing|pending/i.test(local)
              ? 'Unconfirmed'
              : local === 'Previously tried'
                ? 'Previously tried'
                : 'Queued'
    : f.ownership === 'owned'
      ? 'Owned'
      : f.ownership === 'possible'
        ? 'Possible match'
        : 'New to you';
  return `<span class="status ${local ? 'queued' : f.ownership}">${icon(label === 'Owned' || label === 'Downloaded' ? 'check' : 'clock')}${esc(label)}</span>`;
}
function table(files, scope = 'search') {
  const visible = files.slice(0, S.limit);
  return `<div class="results-shell"><table class="results-table"><colgroup><col style="width:34%"><col style="width:12%"><col style="width:10%"><col style="width:15%"><col style="width:21%"><col style="width:8%"></colgroup><thead><tr><th>TRACK / ALBUM</th><th>FORMAT</th><th>SIZE</th><th>YOUR COLLECTION</th><th>SOURCE</th><th></th></tr></thead><tbody>${visible
    .map((f) => {
      const index = (scope === 'browse' ? S.browseFiles : S.files).indexOf(f);
      return `<tr><td><div class="track-cell">${cover(f)}<div class="track-text"><span class="track-title" title="${esc(f.filename)}">${esc(title(f))}</span><span class="track-sub">${esc(artist(f))} <span>·</span> ${esc(album(f))}</span></div></div></td><td><span class="format-badge ${['flac', 'wav', 'aiff', 'alac', 'ape'].includes(fmt(f)) ? '' : 'lossy'}">${esc(fmt(f).toUpperCase())}</span><span class="quality-sub">${['flac', 'wav', 'aiff', 'alac', 'ape'].includes(fmt(f)) ? (f.bitDepth && f.sampleRate ? `${f.bitDepth}-bit / ${(f.sampleRate / 1000).toFixed(1)} kHz` : 'Lossless') : `${f.bitrate || '?'} kbps`}</span></td><td><span class="track-title">${size(f.size)}</span><span class="quality-sub">${duration(f.duration)}</span></td><td>${status(f)}</td><td><button class="user-button" data-user="${esc(f.username)}">${esc(f.username)}</button> <button class="chat-link" data-chat-user="${esc(f.username)}" title="Chat with ${esc(f.username)}" aria-label="Chat with ${esc(f.username)}">${icon('chat')}</button><span class="user-sub ${f.slots ? 'slot' : ''}">${f.slots ? '● Slot available' : `◷ Queue: ${f.queue || 'unknown'}`} · ${rate(f.speed)}</span></td><td><div class="row-actions"><button class="icon-button" data-queue="${index}" data-scope="${scope}" aria-label="Download ${esc(title(f))}" title="Queue download" ${f.localStatus ? 'disabled' : ''}>${icon('downloads')}</button></div></td></tr>`;
    })
    .join(
      '',
    )}</tbody></table><div class="table-foot"><span>Showing <b>${visible.length}</b> of <b>${files.length}</b> matching files</span><span>Filters remembered ${S.demo ? 'for this demo' : 'on this computer'} <b>·</b> Possible matches stay visible</span></div></div>${files.length > S.limit ? '<button class="secondary load-more" data-action="more">Show 100 more files</button>' : ''}`;
}
function groups(files) {
  const m = new Map();
  for (const f of files) {
    const key = f.username + '|' + releaseFolder(f);
    if (!m.has(key)) m.set(key, []);
    m.get(key).push(f);
  }
  return [...m.values()];
}
function albums(files, scope = 'search') {
  return `<div class="album-grid">${groups(files)
    .slice(0, S.limit)
    .map((fs) => {
      const f = fs[0],
        i = (scope === 'browse' ? S.browseFiles : S.files).indexOf(f);
      return `<article class="album-card">${cover(f, true)}<h3 title="${esc(album(f))}">${esc(album(f))}</h3><p>${esc(artist(f))}</p><div class="album-meta"><span class="format-badge">${esc([...new Set(fs.map(fmt))].join(' / ').toUpperCase())}</span><span>${fs.length} ${scope === 'search' ? 'results' : 'files'}</span></div><p>${esc(f.username)} · ${size(fs.reduce((n, x) => n + x.size, 0))}</p><button class="secondary" data-album="${i}" data-scope="${scope}">${icon('downloads')} Get full album</button></article>`;
    })
    .join(
      '',
    )}</div><p class="page-note">${scope === 'search' ? 'Search results may show only part of an album. Browse the source to inspect its full folder.' : 'Folders are grouped as supplied by the user; names and tags may vary.'} Possible matches are included; confidently owned tracks are skipped.</p>${groups(files).length > S.limit ? '<button class="secondary load-more" data-action="more">Show more albums</button>' : ''}`;
}
function empty(title, sub, action = '') {
  return `<div class="empty">${icon('music')}<h3>${title}</h3><p>${sub}</p>${action}</div>`;
}
function renderSearch() {
  const files = filtered(S.files),
    hidden = S.files.length - files.length;
  return (
    heading(
      'LESS SEARCHING. MORE LISTENING.',
      'Find your next favourite.',
      'Search the network. See what you own. Keep the music moving.',
      `<button class="secondary" data-page="downloads">${icon('downloads')} Your downloads</button>`,
    ) +
    demoNotice() +
    `${!S.query ? `<section class="hero"><div class="eyebrow">A LITTLE LESS FRICTION</div><h2>Your collection is the starting point.</h2><p>Skip the duplicates, filter out the noise and find another source<br>without starting all over again.</p><div class="micro">${icon('shield')} Local library matching. Your files stay yours.</div><div class="record-art"></div><div class="record-line"></div></section>` : ''}${S.recovery ? `<div class="notice warning">${icon('refresh')} Finding a replacement for ${esc(title(S.recovery.file))}. Previously tried sources are marked.<button data-action="clearRecovery">Finish recovery</button></div>` : ''}<form class="search-box" id="searchForm">${icon('search')}<input id="query" aria-label="Search music" placeholder="Artist, album or track…" value="${esc(S.query)}" autocomplete="off"><span class="keycap">/</span><button class="primary" type="submit">${S.searching ? '<span class="spinner"></span>' : 'Search'} ${icon('arrow')}</button></form>${
      !S.demo && S.history.length
        ? `<div class="recent-searches"><span>Recent</span>${S.history
            .slice(0, 4)
            .map(
              (h) =>
                `<button data-history="${esc(h.query)}">${icon('clock')}${esc(h.query)}</button>`,
            )
            .join('')}</div>`
        : ''
    }${filters()}<div class="section-top"><h3>${S.query ? 'Search results' : 'Your next discovery'} <span class="muted">${S.searching ? 'Listening for replies…' : S.files.length ? files.length + ' files · ' + new Set(files.map((f) => f.username)).size + ' sources' + (hidden ? ' · ' + hidden + ' filtered out' : '') : 'Start with an artist or album'}</span></h3><div class="segmented"><button data-view="grouped" class="${S.view === 'grouped' ? 'active' : ''}">${icon('user')} Sources</button><button data-view="tracks" class="${S.view === 'tracks' ? 'active' : ''}">${icon('list')} Tracks</button><button data-view="albums" class="${S.view === 'albums' ? 'active' : ''}">${icon('grid')} Albums</button></div></div>${files.length ? (S.view === 'grouped' ? sourceGroups(files) : S.view === 'albums' ? albums(files) : table(files)) : empty(S.searching ? 'Searching the network…' : S.files.length ? 'No files match these filters' : S.query ? 'No results yet' : 'A better way to find your music', S.files.length ? 'Try enabling another format, reducing the bitrate filter or showing owned tracks.' : S.demo ? 'Try “Massive Attack”, “Portishead” or “Radiohead” in this sample workspace.' : S.query ? 'Peers may still be replying. Search again or try fewer words.' : 'Connect slskd to search live, or explore the sample workspace.', !S.query ? '<button class="secondary" data-action="' + (S.demo ? 'example' : 'demo') + '">' + (S.demo ? 'Try an example search' : 'Explore demo') + '</button>' : '')}<div class="insight-grid"><div class="insight"><div class="insight-icon">${icon('library')}</div><div><h3>A collection with a memory</h3><p>Owned and possible matches, right in your results.</p></div></div><div class="insight"><div class="insight-icon">${icon('refresh')}</div><div><h3>A second chance, one click away</h3><p>Your original search stays with every download.</p></div></div><div class="insight"><div class="insight-icon">${icon('filter')}</div><div><h3>Only the formats you want</h3><p>One set of filters, across search and browsing.</p></div></div></div>`
  );
}
function renderDownloads() {
  const rs = S.requests.filter((r) => !r.archived).sort((a, b) => b.created - a.created);
  const markup =
    heading(
      'KEEP YOUR PLACE',
      'Downloads',
      'Every request remembers the search that found it.',
      `<div class="page-actions"><button class="secondary" data-action="clearDownloads" ${clearingTransfers ? 'disabled' : ''} title="Clear successful transfers; keep music files and failed requests">${icon('check')} Clear completed</button>${transferFeedStatus('downloads')}</div>`,
    ) +
    demoNotice() +
    (rs.length
      ? rs
          .map(
            (r) =>
              `<article class="download-card">${cover(r.file)}<div class="download-info"><h3>${esc(title(r.file))}</h3><p>${esc(artist(r.file))} · ${esc(album(r.file))} · ${esc(fmt(r.file).toUpperCase())} · ${esc(r.file.username)}</p><div class="download-state ${failed(r.status) ? 'failed' : ''}">${failed(r.status) ? 'Source unavailable · ' : ''}${esc(r.status)}${r.attempts?.length ? ' · ' + r.attempts.length + ' previous source(s)' : ''}</div>${transferProgress(r, 'download')}</div><div class="download-actions">${failed(r.status) ? `<button class="secondary" data-recover="${r.id}">${icon('refresh')} Find another source</button>` : ''}${/unconfirmed|missing/i.test(r.status) ? `<button class="secondary" data-reconcile="${esc(r.id)}">Reconcile / retry</button>` : ''}${r.transferId && !complete(r.status) && !['Replaced', 'Cancelled'].includes(r.status) ? `<button class="icon-button" data-cancel="${r.id}" aria-label="Cancel transfer">✕</button>` : ''}</div></article>`,
          )
          .join('')
      : empty(
          'Your queue starts here',
          'Find a track or browse a user’s folders. Downloads will appear here with their original search attached.',
          '<button class="primary" data-page="search">Find music ' + icon('arrow') + '</button>',
        )) +
    '<p class="page-note">Source replacement is manual in this version. Confirm the format and edition before queuing an alternative. Progress, speed and time remaining update automatically.</p>';
  const jobs = renderAlbumJobs();
  const anchor = markup.indexOf('<article class="download-card">');
  return anchor < 0 ? markup + jobs : markup.slice(0, anchor) + jobs + markup.slice(anchor);
}
function renderLibrary() {
  const rows = S.demo
    ? demoFiles
        .filter((f) => f.ownership === 'owned')
        .map((f) => ({
          artist: artist(f),
          album: album(f),
          title: title(f),
          format: fmt(f),
          duration: f.duration,
          path: 'Sample collection',
        }))
    : S.library;
  return (
    heading(
      'KNOW WHAT YOU HAVE',
      'Your collection',
      S.settings.librarySource === 'folders'
        ? 'A local index of your selected music folders.'
        : 'Linked to slskd’s shared library, with cached artist and album tags.',
      `<button class="secondary" data-action="scan" ${S.scan.running ? 'disabled' : ''}>${icon('refresh')} ${S.scan.running ? 'Refreshing…' : S.settings.librarySource === 'folders' ? 'Scan music folders' : 'Rescan shared library'}</button>`,
    ) +
    demoNotice() +
    `<div class="library-stats"><div class="stat-card"><strong>${S.demo ? '11,284' : S.trackCount.toLocaleString()}</strong><small>Tracks ${S.demo ? 'in sample collection' : 'indexed'}</small></div><div class="stat-card"><strong>${S.demo ? '946' : S.libraryAlbums || 0}</strong><small>Albums ${S.demo ? 'in sample collection' : 'matching your filter'}</small></div><div class="stat-card"><strong>${S.demo ? '3' : S.settings.librarySource === 'folders' ? S.settings.roots?.length || 0 : S.scan.roots || 0}</strong><small>${S.settings.librarySource === 'folders' ? 'Music folders' : 'Linked shares'}</small></div></div>${S.scan.running ? `<div class="notice"><span class="spinner"></span> ${S.scan.phase === 'slskd' ? 'Waiting for slskd’s share scan… ' + Math.round((S.scan.progress || 0) * 100) + '%' : S.scan.phase === 'inventory' ? 'Reading slskd’s cached file list…' : 'Updating collection… ' + (S.scan.count || 0) + ' / ' + (S.scan.total || '?') + ' audio files · ' + (S.scan.tagsRead || 0) + ' tags read'}. You can keep browsing.</div>` : S.scan.error ? `<div class="notice warning">${esc(S.scan.error)}</div>` : S.scan.warning ? `<div class="notice warning">${esc(S.scan.warning)}</div>` : ''}<form class="search-box" id="libraryForm">${icon('search')}<input id="libraryQuery" value="${esc(S.libraryQuery || '')}" placeholder="Filter your collection by artist, album or track" aria-label="Filter collection"><button class="primary">Filter</button></form><div style="height:20px"></div>${rows.length ? `<div class="results-shell"><table class="results-table"><thead><tr><th>TRACK</th><th>ARTIST</th><th>ALBUM</th><th>FORMAT</th><th>DISCOVER</th></tr></thead><tbody>${rows.map((r) => `<tr><td title="${esc(r.path)}">${esc(r.title)}</td><td>${esc(r.artist || 'Unknown artist')}</td><td>${esc(r.album)}</td><td><span class="format-badge">${esc(r.format.toUpperCase())}</span></td><td><button class="text-button" data-explore-artist="${esc(r.artist)}" data-explore-album="${esc(r.album)}">Find related</button></td></tr>`).join('')}</tbody></table><div class="table-foot"><button class="secondary" data-library-page="${Math.max(0, (S.libraryOffset || 0) - 100)}" ${(S.libraryOffset || 0) === 0 ? 'disabled' : ''}>Previous</button> Showing ${(S.libraryOffset || 0) + 1}–${(S.libraryOffset || 0) + rows.length} of ${S.libraryTotal || rows.length} matches. <button class="secondary" data-library-page="${(S.libraryOffset || 0) + 100}" ${(S.libraryOffset || 0) + rows.length >= (S.libraryTotal || 0) ? 'disabled' : ''}>Next</button></div></div>` : empty('Let’s meet your music', 'Refresh to import slskd’s shared audio files. Tags are read once and reused until files change. Select folder scanning in Settings to include unshared music.', '<button class="primary" data-action="settings">' + icon('plus') + ' Add music folders</button>')}<p class="page-note">“Owned” requires matching title, artist context and duration. Filename-only matches are labelled “Possible match” and are never hidden automatically. Download history survives rescans and file moves.</p>`
  );
}
function renderCore() {
  UIState.before($('#main'));
  const active = document.activeElement;
  const focus = active?.id;
  const activeValue = active?.value;
  const opened = new Map(
    [...document.querySelectorAll('details[data-result-key]')].map((d) => [
      d.dataset.resultKey,
      d.open,
    ]),
  );
  const selection = ['INPUT', 'TEXTAREA'].includes(active?.tagName)
    ? [active.selectionStart, active.selectionEnd]
    : null;
  nav();
  $('#main').innerHTML =
    S.page === 'foryou'
      ? renderDiscovery()
      : S.page === 'uploads'
        ? renderUploads()
        : S.page === 'chat'
          ? renderChat()
          : S.page === 'downloads'
            ? renderDownloads()
            : S.page === 'library'
              ? renderLibrary()
              : S.page === 'browse'
                ? renderBrowse()
                : renderSearch();
  for (const d of document.querySelectorAll('details[data-result-key]'))
    if (opened.has(d.dataset.resultKey)) d.open = opened.get(d.dataset.resultKey);
  if (focus && document.getElementById(focus) && selection) {
    const el = document.getElementById(focus);
    if (activeValue !== undefined) el.value = activeValue;
    el.focus();
    try {
      el.setSelectionRange(...selection);
    } catch {}
  }
  UIState.after($('#main'), S.page);
  $('#footerStatus').textContent = S.demo
    ? 'Demo workspace · no network activity'
    : S.connected
      ? 'Connected through your local slskd'
      : 'Local workspace · connect slskd to search';
}
