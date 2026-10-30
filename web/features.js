'use strict';
paths.uploads = '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>';
paths.chat = '<path d="M3 4h18v13H9l-6 4z"/>';
Object.assign(S, {
  uploads: [],
  sharing: null,
  uploadError: '',
  conversations: [],
  chatUser: '',
  messages: [],
  chatError: '',
  chatDrafts: {},
  albumFiles: [],
  albumBusy: false,
  albumJobs: [],
});
const rate = (n) =>
  n > 0
    ? size(n).replace(' GB', ' GB/s').replace(' MB', ' MB/s').replace(' KB', ' KB/s')
    : 'Speed unknown';
let chatRefreshBusy = false;
let liveRefresh,
  albumScope = 'search',
  featureBusy = false;
const searchOpenAlbums = new Set();
function sourceGroups(files) {
  const all = groups(files).sort(
    (a, b) =>
      b.reduce((m, f) => Math.max(m, f.speed || 0), 0) -
        a.reduce((m, f) => Math.max(m, f.speed || 0), 0) ||
      a[0].username.localeCompare(b[0].username) ||
      releaseFolder(a[0]).localeCompare(releaseFolder(b[0])),
  );
  const page = Math.max(
    0,
    Math.min(S.searchGroupPage || 0, Math.max(0, Math.ceil(all.length / 40) - 1)),
  );
  S.searchGroupPage = page;
  const users = new Map();
  for (const gs of all.slice(page * 40, page * 40 + 40)) {
    const name = gs[0].username;
    if (!users.has(name)) users.set(name, []);
    users.get(name).push(gs);
  }
  let budget = 300;
  return `<div class="source-groups">${[...users]
    .map(
      ([username, albums], rank) =>
        `<details class="source-group" data-result-key="${esc(username)}" open><summary><span class="source-rank">${page * 40 + rank + 1}</span><strong>${esc(username)}</strong><span class="source-speed">${rate(albums.flat().reduce((m, f) => Math.max(m, f.speed || 0), 0))}</span><span class="source-count">${albums.length} album folders on this page</span></summary><div class="source-inner"><div class="source-tools"><button class="secondary" data-user="${esc(username)}">Browse all</button><button class="secondary" data-chat-user="${esc(username)}">Chat</button></div>${albums
          .map((gs) => {
            const f = gs[0],
              key = username + '|' + releaseFolder(f),
              open = searchOpenAlbums.has(key),
              visible = open ? gs.slice(0, Math.min(100, budget)) : [];
            budget -= visible.length;
            return `<section class="artist-group"><h3>${esc(artist(f))}</h3><details class="album-group" data-result-key="${esc(key)}" ${open ? 'open' : ''}><summary><span class="album-group-name">${esc(album(f))}<small>${esc(releaseFolder(f))}</small></span><span>${gs.length} matching tracks</span></summary>${open ? `<div class="album-group-content"><button class="primary" data-album="${S.files.indexOf(f)}" data-scope="search">Get full album</button>${visible.length ? table(visible) : '<p>Close another expanded album to display more tracks.</p>'}${gs.length > visible.length ? `<p class="hint">${visible.length} preview tracks. Browse this user to view the complete folder.</p>` : ''}</div>` : ''}</details></section>`;
          })
          .join('')}</div></details>`,
    )
    .join(
      '',
    )}</div><div class="table-foot"><button class="secondary" data-search-groups="${page - 1}" ${page === 0 ? 'disabled' : ''}>Previous</button><span>Album folders ${page * 40 + 1}–${Math.min(all.length, (page + 1) * 40)} of ${all.length}</span><button class="secondary" data-search-groups="${page + 1}" ${(page + 1) * 40 >= all.length ? 'disabled' : ''}>Next</button></div>`;
}
document.addEventListener(
  'toggle',
  (e) => {
    const d = e.target;
    if (!d.matches?.('.album-group[data-result-key]')) return;
    const key = d.dataset.resultKey;
    if (d.open === searchOpenAlbums.has(key)) return;
    if (d.open) searchOpenAlbums.add(key);
    else searchOpenAlbums.delete(key);
    render();
  },
  true,
);
document.addEventListener('click', (e) => {
  const button = e.target.closest('[data-search-groups]');
  if (!button) return;
  S.searchGroupPage = Number(button.dataset.searchGroups);
  render();
});
function albumDialog() {
  let d = $('#albumDialog');
  if (!d) {
    d = document.createElement('dialog');
    d.id = 'albumDialog';
    document.body.append(d);
  }
  return d;
}
async function fullAlbum(f, scope) {
  if (S.recovery) {
    toast('Choose an individual track when replacing a failed source.', true);
    return;
  }
  if (!f) return;
  albumScope = scope;
  S.albumFiles = [];
  S.albumArtwork = [];
  S.albumRoot = releaseFolder(f);
  S.albumJobId = crypto.randomUUID();
  S.albumJobSelection = '';
  const d = albumDialog();
  d.innerHTML = `<button class="icon-button" data-feature="closeAlbum" aria-label="Close album">✕</button><h2>${esc(album(f))}</h2><p><span class="spinner"></span> Checking audio and artwork in the full album folder…</p>`;
  d.showModal();
  try {
    if (S.demo) {
      const files = demoFiles
        .filter(
          (x) =>
            x.username === f.username &&
            (folder(x) === S.albumRoot || folder(x).startsWith(S.albumRoot + '/')),
        )
        .map((x) => ({ ...x }));
      S.albumFiles = files.filter((x) => !isArtwork(x));
      S.albumArtwork = [
        {
          username: f.username,
          filename: S.albumRoot + '/cover.jpg',
          size: 450000,
        },
        {
          username: f.username,
          filename: S.albumRoot + '/Artwork/back.png',
          size: 650000,
        },
      ];
    } else {
      const result = await api(
        'album-folder?username=' +
          encodeURIComponent(f.username) +
          '&directory=' +
          encodeURIComponent(S.albumRoot),
      );
      S.albumFiles = result.files;
      S.albumArtwork = result.artwork || [];
    }
    for (const x of [...S.albumFiles, ...S.albumArtwork]) {
      const existing = S.requests.find(
        (r) =>
          r.file.username === x.username &&
          r.file.filename === x.filename &&
          !['Cancelled', 'Replaced'].includes(r.status),
      );
      if (existing) x.localStatus = existing.status;
    }
    const preview = (x) =>
      `<div><span>${esc(x.filename.replace(/\\/g, '/').slice(S.albumRoot.length + 1))}</span><span class="format-badge">${esc(fmt(x).toUpperCase())}</span><small>${x.localStatus ? esc(x.localStatus) : size(x.size)}</small></div>`;
    d.innerHTML = `<div class="dialog-top"><div><span class="eyebrow">ONE ALBUM. ONE SOURCE.</span><h2>${esc(album(f))}</h2><p class="subtitle">${esc(f.username)} · ${S.albumFiles.length} audio files · ${S.albumArtwork.length} artwork / booklet files</p></div><button class="icon-button" data-feature="closeAlbum">✕</button></div><div class="notice">Artwork is always included with the album, regardless of audio format filters. Album subfolders are preserved under the album’s download folder.</div><label>Album audio format<select class="select" id="albumFormat">${[
      ...new Set(S.albumFiles.map(fmt)),
    ]
      .filter((x) => S.settings.formats.includes(x))
      .map((x) => `<option value="${esc(x)}">${esc(x.toUpperCase())}</option>`)
      .join(
        '',
      )}<option value="all">All enabled formats</option></select></label><label class="switch-label"><input id="albumSkipOwned" type="checkbox">Skip confidently owned tracks</label><p class="hint">Other audio formats remain excluded. Already queued or downloaded files from this source are skipped. Images and PDF booklets within this album folder are included; files outside it are not fetched.</p><h3>Audio</h3><div class="album-preview-list">${S.albumFiles.map(preview).join('')}</div><h3>Artwork & booklets · always included</h3><div class="album-preview-list">${S.albumArtwork.map(preview).join('') || '<p class="hint">No separate artwork shared in this album folder. Embedded artwork stays inside its audio file.</p>'}</div><div class="dialog-actions"><button class="secondary" data-feature="closeAlbum">Cancel</button><button class="primary" data-feature="confirmAlbum">Queue album + artwork</button></div><p id="albumProgress" class="hint" role="status"></p>`;
  } catch (e) {
    d.innerHTML = `<h2>Folder unavailable</h2><p>${esc(e.message)}</p><button class="secondary" data-feature="closeAlbum">Close</button>`;
  }
}
async function confirmAlbum() {
  if (S.albumBusy) return;
  const chosen = $('#albumFormat').value,
    skip = $('#albumSkipOwned').checked;
  if (
    !S.albumFiles.some(
      (f) => S.settings.formats.includes(fmt(f)) && (chosen === 'all' || fmt(f) === chosen),
    )
  ) {
    toast('No audio matches the enabled formats. Enable this album’s format first.', true);
    return;
  }
  const fs = albumQueueSelection(S.albumFiles, S.albumArtwork || [], chosen, skip);
  if (!fs.length) {
    toast('No unqueued files remain for this album.');
    return;
  }
  S.albumBusy = true;
  const btn = $('[data-feature="confirmAlbum"]');
  btn.disabled = true;
  let done = 0;
  try {
    if (S.demo) {
      for (const f of fs) {
        const before = S.requests.length;
        await queue(f, true, S.albumRoot);
        if (S.requests.length > before) done++;
      }
    } else {
      $('#albumProgress').textContent = 'Queuing album batches and saving the expected-file list…';
      const expected = albumQueueSelection(S.albumFiles, S.albumArtwork || [], chosen, skip, true);
      const selectionKey = JSON.stringify(expected.map((f) => f.filename));
      if (S.albumJobSelection && S.albumJobSelection !== selectionKey)
        S.albumJobId = crypto.randomUUID();
      S.albumJobSelection = selectionKey;
      const job = await api('queue-album', {
        id: S.albumJobId,
        username: expected[0].username,
        directory: S.albumRoot,
        query: S.query || '',
        files: expected,
      });
      done = job.files.filter((f) => f.status === 'Queued' || complete(f.status)).length;
      const state = await api('state');
      S.requests = state.requests;
      S.albumJobs = [job, ...S.albumJobs.filter((j) => j.id !== job.id)];
      $('#albumProgress').textContent =
        `${job.completed} of ${job.expected} files completed · ${job.status}. ${job.warnings.join(' ')}`;
    }
    for (const f of [...S.files, ...S.browseFiles, ...S.albumFiles, ...S.albumArtwork]) {
      const r = S.requests.find(
        (r) => r.file.username === f.username && r.file.filename === f.filename,
      );
      if (r) f.localStatus = r.status;
    }
    render();
    toast(
      `${done} album and artwork files ${S.demo ? 'added to demo queue' : 'queued or already present'}.`,
    );
  } finally {
    S.albumBusy = false;
    btn.disabled = false;
  }
}
function demoUploads() {
  return [
    {
      id: 'sample-upload-completed',
      username: 'vinyl_listener',
      filename: 'Music/Radiohead/OK Computer/01 - Airbag.flac',
      size: 35000000,
      bytesTransferred: 35000000,
      averageSpeed: 0,
      state: 'Completed, Succeeded',
    },
    {
      id: 'sample-upload-1',
      username: 'cassette_culture',
      filename: 'E:\\Music\\Portishead\\Dummy\\04 - Glory Box.flac',
      size: 35200000,
      bytesTransferred: 17600000,
      averageSpeed: 825000,
      state: 'InProgress, Transferring',
    },
    {
      id: 'sample-upload-2',
      username: 'deep_cut_archive',
      filename: 'E:\\Music\\Massive Attack\\Mezzanine\\03 - Teardrop.flac',
      size: 32900000,
      bytesTransferred: 0,
      averageSpeed: 0,
      state: 'Queued, Remotely',
    },
  ];
}
async function loadUploads(quiet = false) {
  S.uploadsInitialized = true;
  if (S.demo) {
    if (!S.demoUploadsInitialized) {
      S.uploads = demoUploads();
      S.demoUploadsInitialized = true;
    }
    S.sharing = S.sharing || {
      directories: ['E:\\Music'],
      blockedUsers: [],
      paused: false,
    };
    if (S.page === 'uploads') render();
    return;
  }
  try {
    S.uploads = await api('uploads');
    S.uploadError = '';
    try {
      S.sharing = await api('sharing');
    } catch (e) {
      S.sharing = null;
      S.uploadError = e.message;
    }
    if (S.page === 'uploads') render();
  } catch (e) {
    S.uploadError = e.message;
    if (S.page === 'uploads') render();
    if (!quiet) toast(e.message, true);
  }
}
function renderUploads() {
  const active = S.uploads.filter(
    (f) =>
      !complete(f.state) &&
      !failed(f.state) &&
      !['Cancelled', 'Completed, Cancelled'].includes(f.state),
  );
  return (
    heading(
      'YOUR SHARE, YOUR RULES',
      'Uploads & sharing',
      'See who is taking what, stop a transfer, and decide what you share.',
      `<div class="page-actions"><button class="secondary" data-feature="clearUploads" ${clearingTransfers ? 'disabled' : ''} title="Clear successful transfers; keep music files and failed uploads">${icon('check')} Clear completed</button>${transferFeedStatus('uploads')}</div>`,
    ) +
    demoNotice() +
    `<div class="library-stats"><div class="stat-card"><strong>${active.length}</strong><small>Active or queued transfers</small></div><div class="stat-card"><strong>${new Set(active.map((f) => f.username)).size}</strong><small>People receiving files</small></div><div class="stat-card"><strong>${S.sharing?.paused ? 'Paused' : S.sharing ? 'Enabled' : 'Set up'}</strong><small>Sharing configuration</small></div></div>${S.uploadError ? `<div class="notice warning">${esc(S.uploadError)} <button data-action="settings">Settings</button></div>` : ''}<section class="sharing-controls"><div><h3>What people can take</h3><p class="hint">Shared folders apply to everyone. Blocked users cannot browse or request new files, and their messages are ignored.</p></div><div class="source-tools">${S.sharing ? `<button class="${S.sharing.paused ? 'primary' : 'secondary'}" data-feature="${S.sharing.paused ? 'resumeSharing' : 'pauseSharing'}">${S.sharing.paused ? 'Resume sharing' : 'Pause all sharing'}</button><button class="secondary" data-feature="editFolders">${icon('browse')} Shared folders</button>` : '<button class="secondary" data-action="settings">Enable sharing controls</button>'}</div>${S.sharing?.blockedUsers?.length ? `<div class="blocked-users">${S.sharing.blockedUsers.map((u) => `<span>${esc(u)} <button data-unblock-user="${esc(u)}">Unblock</button></span>`).join('')}</div>` : ''}</section><div class="section-top"><h3>Outgoing transfers <span class="muted">Live progress while this screen is open</span></h3></div>${S.uploads.length ? S.uploads.map((f, i) => `<article class="download-card">${cover(f)}<div class="download-info"><h3>${esc(title(f))}</h3><p><button class="user-button" data-user="${esc(f.username)}">${esc(f.username)}</button> · ${esc(f.filename)}</p><div class="download-state">${esc(f.state)}</div>${transferProgress(f, 'upload')}</div><div class="download-actions"><button class="secondary" data-chat-user="${esc(f.username)}">${icon('chat')} Chat</button>${!complete(f.state) && !/cancelled|rejected|errored/i.test(f.state) ? `<button class="secondary" data-stop-upload="${i}">Stop</button>` : ''}<button class="secondary danger" data-block-user="${esc(f.username)}" ${!S.sharing ? 'disabled' : ''}>Block user</button></div></article>`).join('') : empty('No outgoing transfers', 'Uploads and queued requests from other users will appear here.')}<p class="page-note">Stop cancels a transfer; the user may request it again. Block user also cancels their active/queued uploads. Sharing changes update slskd.yml with backups; folder rescans and configuration reloads are asynchronous.</p>`
  );
}
async function sharingAction(b) {
  if (featureBusy) return;
  featureBusy = true;
  try {
    if (S.demo) {
      S.sharing = S.sharing || {
        directories: ['E:\\Music'],
        blockedUsers: [],
        paused: false,
      };
      if (b.action === 'block') {
        S.sharing.blockedUsers.push(b.username);
        S.uploads = S.uploads.filter((f) => f.username !== b.username);
      }
      if (b.action === 'unblock')
        S.sharing.blockedUsers = S.sharing.blockedUsers.filter((u) => u !== b.username);
      if (b.action === 'pause') {
        S.sharing.paused = true;
        S.uploads = [];
      }
      if (b.action === 'resume') S.sharing.paused = false;
      if (b.action === 'folders') S.sharing.directories = b.directories;
      toast('Demo sharing controls updated.');
    } else {
      toast('Applying sharing settings…');
      const r = await api('sharing', b);
      S.sharing = r;
      toast(
        r.warnings?.length
          ? r.warnings.join(' ')
          : 'Sharing settings saved. slskd is applying the change.',
        !!r.warnings?.length,
      );
      await loadUploads(true);
    }
    render();
  } catch (e) {
    toast(e.message, true);
  } finally {
    featureBusy = false;
  }
}
function foldersDialog() {
  const d = albumDialog();
  d.innerHTML = `<div class="dialog-top"><div><span class="eyebrow">CHOOSE WHAT YOU SHARE</span><h2>Shared music folders</h2></div><button class="icon-button" data-feature="closeAlbum">✕</button></div><label>One existing full path per line<textarea id="shareRoots" rows="7">${esc((S.sharing.paused ? S.sharing.resumeDirectories || S.sharing.directories : S.sharing.directories).join('\n'))}</textarea></label><p class="hint">These folders and their subfolders are accessible to other users. Removing a folder stops sharing it after slskd reloads and rescans. Applying a change also cancels current uploads, which users may re-request if still shared.</p><button class="primary" data-feature="saveFolders">Save shared folders</button>`;
  d.showModal();
}
async function loadConversations(quiet = false) {
  if (S.demo) {
    if (!S.conversations.length)
      S.conversations = [{ username: 'analogue_days', hasUnAcknowledgedMessages: false }];
    if (S.page === 'chat') render();
    return;
  }
  try {
    S.conversations = await api('conversations');
    S.chatError = '';
    if (S.page === 'chat') render();
  } catch (e) {
    S.chatError = e.message;
    if (S.page === 'chat') render();
    if (!quiet) toast(e.message, true);
  }
}
async function openChat(username) {
  if (S.demo && !S.conversations.some((c) => c.username === username))
    S.conversations.push({ username });
  S.chatUser = username;
  S.messages = [];
  go('chat');
  await refreshChat();
}
async function refreshChat() {
  if (!S.chatUser) return;
  if (S.demo) {
    if (!S.messages.length)
      S.messages = [
        {
          direction: 'In',
          message: 'Hi! Feel free to browse my collection.',
          timestamp: new Date().toISOString(),
        },
      ];
    render();
    return;
  }
  try {
    const target = S.chatUser;
    const messages = await api('messages?username=' + encodeURIComponent(target));
    if (target !== S.chatUser) return;
    S.messages = messages;
    S.chatError = '';
    if (S.page === 'chat') render();
    await api('read-messages', { username: target });
  } catch (e) {
    S.chatError = e.message;
    if (S.page === 'chat') render();
  }
}
function renderChat() {
  return (
    heading(
      'A CONVERSATION AWAY',
      'Chat',
      'Private messages with people on Soulseek.',
      `<button class="secondary" data-feature="refreshChat">${icon('refresh')} Refresh</button>`,
    ) +
    demoNotice() +
    `<form class="browse-form" id="newChatForm"><input class="inline-input" id="chatUsername" placeholder="Enter a username to start a chat" aria-label="Chat username"><button class="primary">${icon('chat')} Open chat</button></form>${S.chatError ? `<div class="notice warning">${esc(S.chatError)}</div>` : ''}<div class="chat-layout"><aside class="chat-sidebar">${S.conversations.map((c) => `<button class="conversation ${S.chatUser === c.username ? 'active' : ''}" data-chat-user="${esc(c.username)}">${icon('user')} ${esc(c.username)} ${c.hasUnAcknowledgedMessages ? '<i class="green-dot"></i>' : ''}</button>`).join('') || '<p class="hint">No conversations yet.</p>'}</aside><section class="chat-panel">${
      S.chatUser
        ? `<div class="chat-heading"><strong>${esc(S.chatUser)}</strong><button class="secondary" data-user="${esc(S.chatUser)}">${icon('browse')} Browse files</button></div><div class="message-list" aria-live="polite">${
            S.messages
              .map((m) => {
                const out = m.direction === 'Out' || m.direction === 0;
                return `<div class="message ${out ? 'out' : ''}"><span>${esc(m.message)}</span><small>${out ? 'You' : esc(S.chatUser)} · ${new Date(m.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></div>`;
              })
              .join('') || '<p class="hint">No messages yet. Say hello.</p>'
          }</div><form id="messageForm" class="message-form"><textarea id="messageText" placeholder="Message ${esc(S.chatUser)}…" aria-label="Your message" maxlength="5000" required>${esc(S.chatDrafts[S.chatUser] || '')}</textarea><button class="primary" type="submit">Send ${icon('arrow')}</button></form><p class="hint">Sends to ${esc(S.chatUser)} through Soulseek. Messages refresh every 5 seconds while this screen is open.</p>`
        : empty(
            'Choose a conversation',
            'Open a chat from a search result, upload, or the username field above.',
          )
    }</section></div>`
  );
}
// Keep active screens fresh without polling the network from hidden pages.
setInterval(async () => {
  if (document.hidden || featureBusy || $('#settingsDialog').open || $('#albumDialog')?.open)
    return;
  if (S.page === 'chat' && !chatRefreshBusy) {
    chatRefreshBusy = true;
    try {
      await loadConversations(true);
      await refreshChat();
    } finally {
      chatRefreshBusy = false;
    }
  }
}, 5000);
document.addEventListener('click', async (e) => {
  const t = e.target.closest('button');
  if (!t) return;
  try {
    if (t.dataset.chatUser) {
      await openChat(t.dataset.chatUser);
      return;
    }
    if (t.dataset.stopUpload !== undefined) {
      const f = S.uploads[Number(t.dataset.stopUpload)];
      if (!confirm(`Stop uploading “${title(f)}” to ${f.username}?`)) return;
      if (S.demo) {
        S.uploads = S.uploads.filter((x) => x !== f);
        render();
      } else {
        await api('stop-upload', { username: f.username, id: f.id });
        await loadUploads();
      }
      return;
    }
    if (t.dataset.blockUser) {
      if (
        confirm(
          `Block ${t.dataset.blockUser} from your shares and cancel their current uploads? This also blocks their messages.`,
        )
      )
        await sharingAction({ action: 'block', username: t.dataset.blockUser });
      return;
    }
    if (t.dataset.unblockUser) {
      await sharingAction({
        action: 'unblock',
        username: t.dataset.unblockUser,
      });
      return;
    }
    const a = t.dataset.feature;
    if (a === 'closeAlbum') {
      if (!S.albumBusy) $('#albumDialog').close();
      return;
    }
    if (a === 'confirmAlbum') await confirmAlbum();
    if (a === 'refreshUploads') await loadUploads();
    if (a === 'clearUploads') await clearCompleted('uploads');
    if (a === 'refreshChat') {
      await loadConversations();
      await refreshChat();
    }
    if (a === 'editFolders') foldersDialog();
    if (
      a === 'pauseSharing' &&
      confirm(
        'Pause sharing all folders and cancel current uploads? Your shared-folder list is saved for Resume.',
      )
    )
      await sharingAction({ action: 'pause' });
    if (a === 'resumeSharing') await sharingAction({ action: 'resume' });
    if (a === 'saveFolders') {
      const directories = $('#shareRoots')
        .value.split('\n')
        .map((x) => x.trim())
        .filter(Boolean);
      await sharingAction({ action: 'folders', directories });
      $('#albumDialog').close();
    }
  } catch (e) {
    toast(e.message, true);
  }
});
document.addEventListener('submit', async (e) => {
  if (e.target.id === 'newChatForm') {
    e.preventDefault();
    const u = $('#chatUsername').value.trim();
    if (u) await openChat(u);
  }
  if (e.target.id === 'messageForm') {
    e.preventDefault();
    const input = $('#messageText'),
      message = input.value.trim(),
      username = S.chatUser;
    if (!message) return;
    const submit = e.target.querySelector('button');
    submit.disabled = true;
    try {
      if (S.demo) {
        S.messages.push({
          direction: 'Out',
          message,
          timestamp: new Date().toISOString(),
        });
        S.chatDrafts[username] = '';
        input.value = '';
        render();
        toast('Demo message saved locally. Nothing was sent.');
      } else {
        await api('send-message', { username, message });
        S.chatDrafts[username] = '';
        if (username === S.chatUser) {
          input.value = '';
          await refreshChat();
        }
      }
    } catch (err) {
      toast(err.message, true);
    } finally {
      submit.disabled = false;
    }
  }
});

document.addEventListener('input', (e) => {
  if (e.target.id === 'messageText') S.chatDrafts[S.chatUser] = e.target.value;
});
function resetFeatureState() {
  S.demoUploadsInitialized = false;
  S.uploadsInitialized = false;
  S.uploads = [];
  S.sharing = null;
  S.messages = [];
  S.chatUser = '';
  S.conversations = [];
}
function renderAlbumJobs() {
  const jobs = (S.albumJobs || []).filter((j) => !j.archived);
  if (!jobs.length) return '';
  const cards =
    '<section class="album-jobs"><h3>Album downloads</h3>' +
    jobs
      .map(
        (j) =>
          `<article class="download-card"><div class="download-info"><h3>${esc(j.directory.split('/').pop())}</h3><p>${esc(j.username)} · ${j.completed} / ${j.expected} selected audio and artwork files complete</p><div class="download-state ${j.failed ? 'failed' : ''}">${esc(j.status)}${j.failed ? ' · ' + j.failed + ' files need attention' : ''}</div>${transferProgress(j, 'album')}<small>Missing or unconfirmed files keep this album open.</small>${j.files.some((f) => /unconfirmed|missing/i.test(f.status)) ? `<button class="secondary" data-reconcile-album="${esc(j.id)}">Reconcile album / retry missing files</button>` : ''}</div></article>`,
      )
      .join('') +
    '</section>';
  return cards;
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-reconcile-album]');
  if (!button || S.demo) return;
  button.disabled = true;
  try {
    await api('reconcile-album', { id: button.dataset.reconcileAlbum });
    await sync();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
});
