const vm = require('node:vm'),
  fs = require('node:fs'),
  assert = require('node:assert/strict'),
  path = require('node:path');
const web = path.join(__dirname, '../web');
const context = {
  console,
  Set,
  Map,
  Date,
  setTimeout,
  clearTimeout,
  S: {
    browseFiles: [],
    browsePath: '',
    browseTerm: '',
    settings: { formats: ['flac'], blocked: [] },
  },
  document: { addEventListener() {} },
  browsePeer: async () => {},
  render() {},
  browseCache: new Map(),
  rate: () => '',
  status: () => '',
  isArtwork: (f) => /\.(jpg|png|pdf)$/i.test(f.filename),
  filtered: (fs) => fs.filter((f) => f.filename.endsWith('.flac')),
  table: (rows) => rows.map((f) => `<tr>${f.filename}</tr>`).join(''),
  groups: (files) => {
    const m = new Map();
    for (const f of files) {
      const key = f.filename
        .replace(/\\/g, '/')
        .split('/')
        .slice(0, -1)
        .join('/')
        .replace(/\/Disc \d+$/, '');
      if (!m.has(key)) m.set(key, []);
      m.get(key).push(f);
    }
    return [...m.values()];
  },
  heading: () => '',
  demoNotice: () => '',
  filters: () => '',
  empty: () => '',
  basicBrowse: undefined,
};
vm.createContext(context);
// Use production path, label and escaping helpers.
vm.runInContext(fs.readFileSync(path.join(web, 'view_helpers.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(web, 'browse.js'), 'utf8'), context);
const files = [];
for (let a = 0; a < 4000; a++)
  for (let t = 0; t < 19; t++)
    files.push({
      filename: `Music/Artist ${String(a % 400).padStart(3, '0')}/Album ${String(a).padStart(4, '0')}/${t + 1}.flac`,
      username: 'test',
      size: 100,
    });
context.S.browseFiles = files;
let tree = context.buildBrowseModel(files);
assert.equal(tree.count, 76000);
assert.equal(tree.children.size, 1);
const treeHTML = context.treeMarkup(tree);
assert.equal((treeHTML.match(/class="tree-row"/g) || []).length, 150);
assert.ok(treeHTML.includes('Show more folders'));
const albums = context.browserAlbums(files);
assert.equal((albums.match(/<article /g) || []).length, 48);
assert.ok(albums.includes('of 4,000'));
context.S.browseOffset = 48;
const second = context.browserAlbums(files);
assert.notEqual(second, albums);
assert.ok(second.includes('49–96'));
context.S.browseOffset = 0;
const artists = context.browserArtists(files);
assert.equal((artists.match(/class="browse-artist"/g) || []).length, 60);
const tracks = context.browserTracks(files);
assert.equal((tracks.match(/<tr>/g) || []).length, 101);
context.S.folderTerm = 'Artist 123';
assert.ok(context.treeMarkup(tree).includes('Artist 123'));
assert.ok(!context.treeMarkup(tree).includes('Artist 124'));
context.S.browseUser = 'test';
context.S.browsePath = 'Music/Artist 123';
context.S.browseMode = 'albums';
context.S.folderTerm = '';
let selection = context.renderBrowse();
assert.ok(selection.includes('10 albums'));
assert.ok(!selection.includes('data-open-album="Music/Artist 124'));
context.S.browseAlbum = 'Music/Artist 123/Album 0123';
selection = context.renderBrowse();
assert.ok(selection.includes('19 of 19 tracks shown'));
assert.ok(selection.includes('Back to albums'));
assert.ok(selection.includes('Download album'));
const hostile = [{ filename: 'Music/<script>/A & B/01.flac', username: 'test' }];
context.S.browseFiles = hostile;
context.S.browseOffset = 0;
const safe = context.browserAlbums(hostile);
assert.ok(safe.includes('&lt;script&gt;'));
assert.ok(!safe.includes('<script>'));
console.log(
  'Browse UI passed: 76,000-file inventory, bounded tree/cards/tracks, pagination, artist and album scope, escaped folder names.',
);
// Exercise the actual audio filter and album selection together: artwork bypasses audio filters.
const artStart = fs.readFileSync(path.join(web, 'features.js'), 'utf8');
vm.runInContext(fs.readFileSync(path.join(web, 'file_filters.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(web, 'album_selection.js'), 'utf8'), context);
context.S.settings = {
  formats: ['flac'],
  hideOwned: true,
  minBitrate: 0,
  blocked: [],
};
const audio = [
  { filename: 'Music/Album/01.flac', username: 'test', ownership: 'owned' },
  { filename: 'Music/Album/01.mp3', username: 'test', ownership: 'new' },
  { filename: 'Music/Album/02.flac', username: 'test', ownership: 'new' },
];
const art = [
  { filename: 'Music/Album/cover.jpg', username: 'test' },
  { filename: 'Music/Album/Art/booklet.pdf', username: 'test' },
  {
    filename: 'Music/Album/Art/back.png',
    username: 'test',
    localStatus: 'Queued',
  },
];
const chosen = context.albumQueueSelection(audio, art, 'flac', true);
assert.equal(chosen.length, 3);
assert.ok(chosen.some((f) => f.filename.endsWith('cover.jpg')));
assert.ok(chosen.some((f) => f.filename.endsWith('booklet.pdf')));
assert.ok(!chosen.some((f) => f.filename.endsWith('.mp3')));
assert.ok(!chosen.some((f) => f.ownership === 'owned'));
assert.equal(context.S.settings.hideOwned, true);
console.log(
  'Album selection passed: FLAC only, artwork/booklets included, owned audio and queued artwork skipped.',
);

// A redraw replaces the sidebar element, but must keep its independent scroll.
let sidebar = { dataset: { browseUser: 'listener-a' }, scrollTop: 432 };
context.renderWithBrowseScroll(
  () => {
    sidebar = { dataset: { browseUser: 'listener-a' }, scrollTop: 0 };
  },
  () => sidebar,
);
assert.equal(sidebar.scrollTop, 432);
context.renderWithBrowseScroll(
  () => {
    sidebar = { dataset: { browseUser: 'listener-b' }, scrollTop: 0 };
  },
  () => sidebar,
);
assert.equal(sidebar.scrollTop, 0);
sidebar.scrollTop = 117;
context.renderWithBrowseScroll(
  () => {
    sidebar = null;
  },
  () => sidebar,
);
context.renderWithBrowseScroll(
  () => {
    sidebar = { dataset: { browseUser: 'listener-a' }, scrollTop: 0 };
  },
  () => sidebar,
);
assert.equal(sidebar.scrollTop, 432);
context.renderWithBrowseScroll(
  () => {
    sidebar = { dataset: { browseUser: 'listener-b' }, scrollTop: 0 };
  },
  () => sidebar,
);
assert.equal(sidebar.scrollTop, 117);
console.log(
  'Browse scroll passed: preserved across redraws/page changes and independently for each user.',
);
