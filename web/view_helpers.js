'use strict';
const $ = (s) => document.querySelector(s),
  esc = (v) =>
    String(v ?? '').replace(
      /[&<>"']/g,
      (c) =>
        ({
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#39;',
        })[c],
    );
const paths = {
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  library: '<path d="M4 4v16M9 4v16m5-16 5 16M2 20h20"/>',
  downloads: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  browse: '<path d="M3 6h7l2 3h9v11H3zM3 6V4h6l2 2"/>',
  settings:
    '<circle cx="12" cy="12" r="3"/><path d="m9 3-1 3-3 1-2 3 2 2-1 3 3 2 1 3h4l1-3 3-1 3-3-2-2 1-3-3-2-1-3z"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 6M4 12l2 6a7 7 0 0 0 12-1"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
  music:
    '<path d="M9 17V5l11-2v12M9 7l11-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="17" cy="16" rx="3" ry="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.1M3 12h.1M3 18h.1"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
};
const icon = (n) => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[n] || paths.music}</svg>`;
const fmt = (f) => (f.filename.split('.').pop() || '').toLowerCase(),
  filename = (f) => f.filename.replace(/\\/g, '/').split('/').pop(),
  folder = (f) => f.filename.replace(/\\/g, '/').split('/').slice(0, -1).join('/'),
  title = (f) =>
    filename(f)
      .replace(/\.[^.]+$/, '')
      .replace(/^\d+[\s._-]+/, ''),
  releaseFolder = (f) => {
    const p = folder(f).split('/');
    if (/^(cd|disc|disk)[ ._-]*\d+$/i.test(p[p.length - 1])) p.pop();
    return p.join('/');
  },
  album = (f) => releaseFolder(f).split('/').pop() || 'Shared files',
  artist = (f) => releaseFolder(f).split('/').slice(-2, -1)[0] || f.username;
const size = (n) =>
  n >= 1e9
    ? (n / 1e9).toFixed(1) + ' GB'
    : n >= 1e6
      ? (n / 1e6).toFixed(1) + ' MB'
      : (n / 1e3).toFixed(0) + ' KB';
const duration = (n) =>
  n ? Math.floor(n / 60) + ':' + String(Math.floor(n % 60)).padStart(2, '0') : '—';
const hash = (s) => [...s].reduce((a, c) => (a + c.charCodeAt(0)) % 6, 0),
  cover = (f, big = false) =>
    `<div class="cover c${hash(album(f))}" aria-hidden="true">${icon('music')}</div>`;
