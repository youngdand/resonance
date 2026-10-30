'use strict';
// A bounded folder tree and paginated collection views for large remote shares.
Object.assign(S, {
  browseMode: 'albums',
  browseAlbum: '',
  browseSort: 'artist',
  browseOffset: 0,
  folderTerm: '',
  browseLoading: false,
});
const browsePositions = new Map();
let browseModelInput = null,
  browseModel = null,
  treeOpen = new Set(),
  treeLimit = 150,
  folderTimer;
function buildBrowseModel(files) {
  if (files === browseModelInput) return browseModel;
  const root = { path: '', name: 'All folders', children: new Map(), count: 0 };
  for (const f of files) {
    let node = root;
    node.count++;
    const parts = folder(f).split('/').filter(Boolean);
    let path = '';
    for (const name of parts) {
      path = path ? path + '/' + name : name;
      if (!node.children.has(name))
        node.children.set(name, { path, name, children: new Map(), count: 0 });
      node = node.children.get(name);
      node.count++;
    }
  }
  browseModelInput = files;
  browseModel = root;
  if (root.children.size === 1) treeOpen.add([...root.children.values()][0].path);
  return root;
}
function browseNav(path) {
  S.browsePath = path;
  S.browseAlbum = '';
  S.browseOffset = 0;
  const parts = path.split('/');
  for (let i = 1; i <= parts.length; i++) treeOpen.add(parts.slice(0, i).join('/'));
  render();
}
function treeMarkup(root) {
  const term = S.folderTerm.trim().toLocaleLowerCase(),
    rows = [];
  function visit(node, depth) {
    const children = [...node.children.values()].sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { numeric: true }),
    );
    for (const child of children) {
      if (term) {
        if (child.path.toLocaleLowerCase().includes(term)) rows.push([child, Math.min(depth, 4)]);
        visit(child, depth + 1);
      } else {
        rows.push([child, depth]);
        if (treeOpen.has(child.path)) visit(child, depth + 1);
      }
    }
  }
  visit(root, 0);
  return `<button class="folder-item ${!S.browsePath ? 'active' : ''}" data-browse-path="">${icon('library')}<span>All folders</span><small>${root.count.toLocaleString()}</small></button><div class="browse-tree">${rows
    .slice(0, treeLimit)
    .map(
      ([n, depth]) =>
        `<div class="tree-row" style="--depth:${Math.min(depth, 8)}"><button class="tree-toggle" data-tree-toggle="${esc(n.path)}" aria-label="${treeOpen.has(n.path) ? 'Collapse' : 'Expand'} ${esc(n.name)}" aria-expanded="${treeOpen.has(n.path)}" ${!n.children.size ? 'disabled' : ''}>${n.children.size ? (treeOpen.has(n.path) ? '▾' : '▸') : '·'}</button><button class="tree-name ${S.browsePath === n.path ? 'active' : ''}" data-browse-path="${esc(n.path)}" title="${esc(n.path)}">${icon('browse')}<span>${esc(n.name)}</span><small>${n.count.toLocaleString()}</small></button></div>`,
    )
    .join(
      '',
    )}</div>${rows.length > treeLimit ? `<button class="secondary tree-more" data-browse-action="moreFolders">Show more folders (${(rows.length - treeLimit).toLocaleString()})</button>` : ''}${!rows.length ? '<p class="hint">No folders match.</p>' : ''}`;
}
function browsePager(total, offset, per) {
  return total > per
    ? `<div class="browse-pager"><span>${(offset + 1).toLocaleString()}–${Math.min(offset + per, total).toLocaleString()} of ${total.toLocaleString()}</span><div><button class="secondary" data-browse-action="previous" ${offset === 0 ? 'disabled' : ''}>Previous</button><button class="secondary" data-browse-action="next" ${offset + per >= total ? 'disabled' : ''}>Next</button></div></div>`
    : '';
}
function browserAlbums(files) {
  const albumsByFolder = groups(files);
  albumsByFolder.sort((a, b) =>
    S.browseSort === 'tracks'
      ? b.length - a.length
      : S.browseSort === 'album'
        ? album(a[0]).localeCompare(album(b[0]), undefined, { numeric: true })
        : artist(a[0]).localeCompare(artist(b[0]), undefined, {
            numeric: true,
          }) || album(a[0]).localeCompare(album(b[0]), undefined, { numeric: true }),
  );
  const per = 48;
  S.browseOffset = Math.min(
    S.browseOffset,
    Math.max(0, Math.floor((albumsByFolder.length - 1) / per) * per),
  );
  const slice = albumsByFolder.slice(S.browseOffset, S.browseOffset + per);
  return (
    `<div class="browse-albums">${slice
      .map((fs) => {
        const f = fs[0],
          p = releaseFolder(f),
          index = S.browseFiles.indexOf(f);
        return `<article class="browse-album"><button class="browse-album-open" data-open-album="${esc(p)}">${cover(f)}<span><strong>${esc(album(f))}</strong><span>${esc(artist(f))}</span><small>${fs.length} matching tracks · ${esc([...new Set(fs.map(fmt))].join(' / ').toUpperCase())}</small></span></button><div class="browse-album-bottom"><small title="${esc(p)}">${esc(p)}</small><button class="secondary" data-album="${index}" data-scope="browse" aria-label="Download album ${esc(album(f))}">${icon('downloads')} Download</button></div></article>`;
      })
      .join('')}</div>` + browsePager(albumsByFolder.length, S.browseOffset, per)
  );
}
function browserArtists(files) {
  const artists = new Map();
  for (const f of files) {
    const a = artist(f);
    if (!artists.has(a))
      artists.set(a, {
        name: a,
        albums: new Set(),
        tracks: 0,
        path: releaseFolder(f).split('/').slice(0, -1).join('/'),
      });
    const g = artists.get(a);
    g.albums.add(releaseFolder(f));
    g.tracks++;
  }
  const rows = [...artists.values()].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { numeric: true }),
  );
  const per = 60;
  S.browseOffset = Math.min(S.browseOffset, Math.max(0, Math.floor((rows.length - 1) / per) * per));
  return (
    `<div class="browse-artists">${rows
      .slice(S.browseOffset, S.browseOffset + per)
      .map(
        (a) =>
          `<button class="browse-artist" data-browse-artist="${esc(a.name)}">${icon('user')}<span><strong>${esc(a.name)}</strong><small>${a.albums.size} albums · ${a.tracks.toLocaleString()} matching tracks</small></span>${icon('arrow')}</button>`,
      )
      .join('')}</div>` + browsePager(rows.length, S.browseOffset, per)
  );
}
function browserTracks(files) {
  const rows = files
      .slice()
      .sort((a, b) => a.filename.localeCompare(b.filename, undefined, { numeric: true })),
    per = 100;
  S.browseOffset = Math.min(S.browseOffset, Math.max(0, Math.floor((rows.length - 1) / per) * per));
  const html = `<div class="results-shell"><table class="results-table browse-track-table"><thead><tr><th>TRACK</th><th>ALBUM / ARTIST</th><th>FORMAT</th><th>TIME / SIZE</th><th>YOUR COLLECTION</th><th></th></tr></thead><tbody>${rows
    .slice(S.browseOffset, S.browseOffset + per)
    .map(
      (f) =>
        `<tr><td title="${esc(f.filename)}"><strong>${esc(title(f))}</strong></td><td>${esc(album(f))}<small>${esc(artist(f))}</small></td><td><span class="format-badge">${esc(fmt(f).toUpperCase())}</span></td><td>${duration(f.duration)}<small>${size(f.size || 0)}</small></td><td>${status(f)}</td><td><button class="icon-button" data-queue="${S.browseFiles.indexOf(f)}" data-scope="browse" aria-label="Download ${esc(title(f))}" ${f.localStatus ? 'disabled' : ''}>${icon('downloads')}</button></td></tr>`,
    )
    .join('')}</tbody></table></div>`;
  return html + browsePager(rows.length, S.browseOffset, per);
}
function renderBrowse() {
  const root = buildBrowseModel(S.browseFiles),
    all = S.browseFiles;
  let scoped = all.filter(
    (f) => !S.browsePath || folder(f) === S.browsePath || folder(f).startsWith(S.browsePath + '/'),
  );
  if (S.browseArtist) scoped = scoped.filter((f) => artist(f) === S.browseArtist);
  if (S.browseAlbum) scoped = scoped.filter((f) => releaseFolder(f) === S.browseAlbum);
  const words = S.browseTerm.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const files = filtered(scoped).filter((f) =>
    words.every((w) => f.filename.toLocaleLowerCase().includes(w)),
  );
  const albumCount = new Set(files.map(releaseFolder)).size,
    artistCount = new Set(files.map(artist)).size;
  const audioTypes = new Set([
      'flac',
      'mp3',
      'm4a',
      'aac',
      'ogg',
      'opus',
      'wav',
      'aiff',
      'aif',
      'alac',
      'wma',
      'ape',
    ]),
    audio = scoped.filter((f) => audioTypes.has(fmt(f))),
    art = scoped.filter(isArtwork),
    counts = new Map();
  for (const f of audio) counts.set(fmt(f), (counts.get(fmt(f)) || 0) + 1);
  const scopeSummary = `<div class="browse-file-summary"><strong>${scoped.length.toLocaleString()} files in this selection</strong><span>${audio.length.toLocaleString()} audio · ${
    esc(
      [...counts]
        .sort()
        .map(([f, n]) => n + ' ' + f.toUpperCase())
        .join(', '),
    ) || 'no audio'
  }</span><span>${art.length.toLocaleString()} artwork / booklet files · ${(scoped.length - audio.length - art.length).toLocaleString()} other files</span>${
    art.length
      ? `<details><summary>Artwork included with album downloads</summary>${art
          .slice(0, 60)
          .map((f) => `<p>${esc(f.filename)} <small>${size(f.size || 0)}</small></p>`)
          .join(
            '',
          )}${art.length > 60 ? '<p>Showing the first 60 artwork files in this selection.</p>' : ''}</details>`
      : ''
  }</div>`;
  const crumbs = S.browsePath.split('/').filter(Boolean),
    first = S.browseAlbum ? audio[0] : null;
  return (
    heading(
      'EXPLORE THEIR COLLECTION',
      S.browseUser ? esc(S.browseUser) + '’s collection' : 'Browse a collection',
      'Explore artists, open an album, or follow the folder tree.',
    ) +
    demoNotice() +
    `<form class="browse-form" id="browseForm"><input class="inline-input" id="browseUsername" aria-label="Soulseek username" placeholder="Enter a Soulseek username" value="${esc(S.browseUser)}"><button class="primary" ${S.browseLoading ? 'disabled' : ''}>${S.browseLoading ? '<span class="spinner"></span> Loading…' : icon('browse') + ' Browse files'}</button>${all.length ? '<button class="secondary" type="button" data-browse-action="reload">' + icon('refresh') + ' Reload user</button>' : ''}</form>${filters()}${S.browseLoading ? '<div class="notice"><span class="spinner"></span> Requesting this user’s shared files…</div>' : ''}${
      all.length
        ? `<div class="browse-overview"><span><strong>${all.length.toLocaleString()}</strong> shared files</span><span><strong>${new Set(all.map(releaseFolder)).size.toLocaleString()}</strong> album folders</span><button class="text-button" data-chat-user="${esc(S.browseUser)}">${icon('chat')} Chat with ${esc(S.browseUser)}</button></div><div class="browse-layout improved-browser"><aside class="folder-sidebar" data-browse-user="${esc(S.browseUser)}"><h3>FOLDERS</h3><input id="folderQuery" class="inline-input folder-query" aria-label="Find a folder" placeholder="Find a folder…" value="${esc(S.folderTerm)}"><div id="browseTreePanel">${treeMarkup(root)}</div></aside><section class="folder-content"><nav class="browse-path" aria-label="Folder location"><button data-browse-path="">All folders</button>${crumbs.map((p, i) => `<span>/</span><button data-browse-path="${esc(crumbs.slice(0, i + 1).join('/'))}">${esc(p)}</button>`).join('')}${S.browseArtist ? `<span>/</span><button data-browse-action="clearArtist">${esc(S.browseArtist)} ✕</button>` : ''}</nav><form class="search-box browse-search" id="withinForm">${icon('search')}<input id="withinQuery" value="${esc(S.browseTerm)}" placeholder="Search ${S.browsePath || S.browseArtist ? 'this selection' : 'all shared music'}…" aria-label="Search user's files"><button class="primary">Search</button>${S.browseTerm ? '<button type="button" class="secondary" data-browse-action="clearSearch">Clear</button>' : ''}</form>${
            S.browseAlbum
              ? `<div class="browse-album-heading"><button class="secondary" data-browse-action="backAlbums">← Back to albums</button><div><h2>${esc(first ? album(first) : S.browseAlbum.split('/').pop())}</h2><p>${esc(first ? artist(first) : '')} · ${files.length} of ${audio.length} tracks shown</p></div>${first ? `<button class="primary" data-album="${S.browseFiles.indexOf(first)}" data-scope="browse">${icon('downloads')} Download album</button>` : ''}</div>`
              : `<div class="section-top browse-view-tools"><div><h3>${files.length.toLocaleString()} matching tracks</h3><small>${artistCount.toLocaleString()} artists · ${albumCount.toLocaleString()} albums ${scoped.length !== files.length ? '· filters applied' : ''}</small></div><div class="segmented">${[
                  ['artists', 'Artists', 'user'],
                  ['albums', 'Albums', 'grid'],
                  ['tracks', 'Tracks', 'list'],
                ]
                  .map(
                    ([mode, label, i]) =>
                      `<button data-browse-mode="${mode}" class="${S.browseMode === mode ? 'active' : ''}">${icon(i)} ${label}</button>`,
                  )
                  .join('')}</div>${
                  S.browseMode === 'albums'
                    ? `<select id="browseSort" class="select" aria-label="Sort albums">${[
                        ['artist', 'Artist, then album'],
                        ['album', 'Album name'],
                        ['tracks', 'Most matching tracks'],
                      ]
                        .map(
                          ([v, l]) =>
                            `<option value="${v}" ${S.browseSort === v ? 'selected' : ''}>${l}</option>`,
                        )
                        .join('')}</select>`
                    : ''
                }</div>`
          }${scopeSummary}${files.length ? (S.browseAlbum || S.browseMode === 'tracks' ? browserTracks(files) : S.browseMode === 'artists' ? browserArtists(files) : browserAlbums(files)) : empty('No music matches this selection', 'Try clearing the search, choosing another folder or adjusting the format and Hide owned filters.', '<button class="secondary" data-browse-action="reset">Show all folders</button>')}<p class="page-note">Artist and album names come from shared folder paths. Filters affect the displayed counts. Download opens a full-folder preview before anything is queued.</p></section></div>`
        : S.browseLoading
          ? ''
          : empty(
              'Explore a user’s music',
              'Enter a username above or browse someone from your search results. Artist and album views use their folder names.',
            )
    }`
  );
}
async function browse(username) {
  username = username.trim();
  if (!username || S.browseLoading) return;
  if (S.browseUser)
    browsePositions.set(S.browseUser, {
      path: S.browsePath,
      term: S.browseTerm,
      mode: S.browseMode,
      album: S.browseAlbum,
      artist: S.browseArtist,
      offset: S.browseOffset,
      folderTerm: S.folderTerm,
      open: [...treeOpen],
    });
  const saved = browsePositions.get(username);
  S.browseLoading = true;
  S.browseArtist = '';
  S.browseAlbum = '';
  S.browseMode = 'albums';
  S.browseOffset = 0;
  S.folderTerm = '';
  treeOpen = new Set();
  try {
    await browsePeer(username);
    if (saved) {
      Object.assign(S, {
        browsePath: saved.path,
        browseTerm: saved.term,
        browseMode: saved.mode,
        browseAlbum: saved.album,
        browseArtist: saved.artist,
        browseOffset: saved.offset,
        folderTerm: saved.folderTerm,
      });
      treeOpen = new Set(saved.open);
    }
  } finally {
    S.browseLoading = false;
    render();
  }
}
document.addEventListener('click', async (e) => {
  const t = e.target.closest('button');
  if (!t) return;
  if (t.hasAttribute('data-tree-toggle')) {
    const p = t.dataset.treeToggle;
    treeOpen.has(p) ? treeOpen.delete(p) : treeOpen.add(p);
    $('#browseTreePanel').innerHTML = treeMarkup(buildBrowseModel(S.browseFiles));
    return;
  }
  if (t.hasAttribute('data-browse-path')) {
    S.browseArtist = '';
    browseNav(t.dataset.browsePath);
    return;
  }
  if (t.dataset.openAlbum) {
    S.browseAlbum = t.dataset.openAlbum;
    S.browseOffset = 0;
    render();
    return;
  }
  if (t.dataset.browseArtist) {
    S.browseArtist = t.dataset.browseArtist;
    S.browseAlbum = '';
    S.browseMode = 'albums';
    S.browseOffset = 0;
    render();
    return;
  }
  if (t.dataset.browseMode) {
    S.browseMode = t.dataset.browseMode;
    S.browseOffset = 0;
    render();
    return;
  }
  const action = t.dataset.browseAction;
  if (!action) return;
  if (action === 'reload') {
    browsePositions.delete(S.browseUser);
    browseCache.delete(S.browseUser);
    await browse(S.browseUser);
    return;
  }
  if (action === 'moreFolders') {
    treeLimit += 150;
    $('#browseTreePanel').innerHTML = treeMarkup(buildBrowseModel(S.browseFiles));
    return;
  }
  if (action === 'clearArtist') {
    S.browseArtist = '';
    S.browseOffset = 0;
  }
  if (action === 'backAlbums') {
    S.browseAlbum = '';
    S.browseOffset = 0;
  }
  if (action === 'clearSearch') {
    S.browseTerm = '';
    S.browseOffset = 0;
  }
  if (action === 'reset') {
    S.browseArtist = '';
    S.browseTerm = '';
    browseNav('');
    return;
  }
  if (action === 'previous' || action === 'next') {
    const per =
      S.browseAlbum || S.browseMode === 'tracks' ? 100 : S.browseMode === 'artists' ? 60 : 48;
    S.browseOffset = Math.max(0, S.browseOffset + (action === 'next' ? per : -per));
  }
  render();
});
document.addEventListener('input', (e) => {
  if (e.target.id === 'folderQuery') {
    S.folderTerm = e.target.value;
    treeLimit = 150;
    clearTimeout(folderTimer);
    folderTimer = setTimeout(() => {
      if ($('#browseTreePanel'))
        $('#browseTreePanel').innerHTML = treeMarkup(buildBrowseModel(S.browseFiles));
    }, 120);
  }
});
document.addEventListener('change', (e) => {
  if (e.target.id === 'browseSort') {
    S.browseSort = e.target.value;
    S.browseOffset = 0;
    render();
  }
});
document.addEventListener(
  'submit',
  (e) => {
    if (e.target.id === 'withinForm') S.browseOffset = 0;
  },
  true,
);

// Replacing the main view must not reset the independently scrolled folder tree.
const browseScrollPositions = new Map();
function renderWithBrowseScroll(draw, getSidebar) {
  const before = getSidebar();
  if (before) browseScrollPositions.set(before.dataset.browseUser, before.scrollTop);
  draw();
  const after = getSidebar();
  if (after && browseScrollPositions.has(after.dataset.browseUser))
    after.scrollTop = browseScrollPositions.get(after.dataset.browseUser);
}
