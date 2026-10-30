'use strict';
const vm = require('node:vm'),
  fs = require('node:fs'),
  path = require('node:path'),
  assert = require('node:assert/strict');
const root = path.join(__dirname, '../web');
const ctx = {
  console,
  Intl,
  Date,
  Set,
  Map,
  URL,
  URLSearchParams,
  Number,
  S: { settings: {}, page: 'foryou', demo: false },
  paths: {},
  document: {
    addEventListener() {},
    querySelectorAll() {
      return [];
    },
    getElementById() {
      return null;
    },
  },
  render() {},
  demoNotice: () => '',
  heading: (e, t) => `<h1>${t}</h1>`,
  empty: (a, b) => `<p>${a}</p><p>${b}</p>`,
  demoSetup() {},
  live: async () => {},
  setTimeout: () => 0,
  clearTimeout() {},
  toast() {},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root, 'view_helpers.js'), 'utf8'), ctx);
for (const name of ['discovery.js', 'showcase.js'])
  vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), ctx);
const item = {
  id: 'album',
  kind: 'new-country-release',
  artist: 'Artist',
  album: 'A new record',
  releaseDate: '2026-10-30',
  genres: ['Jazz'],
  artwork: 'https://fastly-s3.allmusic.com/cover.jpg',
  ratings: [
    {
      publisher: 'AllMusic',
      value: 8,
      best: 10,
      url: 'https://www.allmusic.com/album/example',
    },
  ],
  source: 'AllMusic',
  sources: [{ name: 'AllMusic', url: 'https://www.allmusic.com/album/example' }],
  overview: 'A factual release note.',
  dateBasis: 'listing-week',
};
ctx.S.discovery = {
  profile: [],
  items: [],
  online: true,
  job: { running: false, errors: [], candidates: [] },
};
ctx.S.discoveryTab = 'country';
ctx.S.releaseFeed = { items: [item], total: 1, libraryArtists: 0, check: {} };
const card = ctx.releaseCard(item);
assert.ok(card.includes('<img '));
assert.ok(card.includes('loading="lazy"'));
assert.ok(card.includes('8<small>/10'));
assert.ok(card.includes('critic score'));
assert.ok(card.includes('data-release-detail="album"'));
const page = ctx.renderReleaseFeed();
assert.ok(page.includes('id="showcaseQuery"'));
assert.ok(page.includes('id="showcaseGenre"'));
assert.ok(page.includes('With critic scores'));
assert.ok(page.includes('<details class="showcase-more">'));
assert.equal((page.match(/id="releaseGenre"/g) || []).length, 1);
const dossier = ctx.renderDossier(item, {
  publications: [
    {
      publisher: 'AllMusic',
      url: item.url,
      excerpt: 'An attributed excerpt.',
      author: 'Critic',
      tracks: [{ title: 'Opening', duration: 'PT3M20S' }],
    },
  ],
  warnings: [],
  researchLinks: [],
});
assert.ok(dossier.includes('An attributed excerpt.'));
assert.ok(dossier.includes('short source excerpt'));
assert.ok(dossier.includes('Opening'));
assert.ok(dossier.includes('original scales'));
const malicious = ctx.releaseCard({
  ...item,
  album: '<script>bad</script>',
  artwork: 'javascript:alert(1)',
  overview: '<img onerror=bad>',
});
assert.ok(!malicious.includes('<script>'));
assert.ok(!malicious.includes('src="javascript:'));
assert.ok(malicious.includes('&lt;script&gt;'));
ctx.S.discovery.online = false;
assert.ok(
  !ctx.releaseCard(item).includes('<img '),
  'online discovery off must not issue new artwork requests',
);
const key = ctx.releaseQueryKey();
Object.assign(ctx.S.releaseOptions, {
  q: 'Jazz',
  sort: 'rating',
  focus: 'saved',
});
assert.equal(ctx.releaseQueryKey(), key, 'presentation filters must not restart archive scans');
console.log(
  'Showcase UI passed: cover-led cards, lazy artwork, source-labelled scores, compact filters, attributed dossier/tracklist, safe text/URLs, offline artwork privacy and scan-independent filtering.',
);

const reviewSources = ctx.renderDossier(item, {
  reviewsLoading: true,
  reviewSources: [
    {
      name: 'The Guardian',
      status: 'No match in recent index',
      searchUrl: 'https://www.google.com/search?q=album',
    },
  ],
});
assert.ok(reviewSources.includes('Finding coverage for this album'));
assert.ok(reviewSources.includes('No match in recent index'));
assert.ok(reviewSources.includes('Search The Guardian'));
assert.ok(reviewSources.includes('<details class="reading-sources">'));
assert.ok(!reviewSources.includes('<details class="reading-sources" open'));
assert.ok(!reviewSources.includes('Read the full article'));
assert.ok(reviewSources.includes('No readable coverage found yet') === false);
assert.ok(reviewSources.includes('Aggregator and audience scores are not imported'));

const emptyStory = ctx.renderDossier(item, {
  publications: [
    {
      publisher: 'Official Charts',
      excerpt: '',
      url: 'https://www.officialcharts.com/albums/test/',
    },
  ],
  reviewSources: [],
});
assert.ok(emptyStory.includes('No readable coverage found yet'));
assert.ok(!emptyStory.includes('No review excerpt supplied'));
assert.ok(!emptyStory.includes('is an album by'));
const storyCard = ctx.releaseCard({
  ...item,
  coveragePreview: {
    text: 'An actual review preview.',
    publisher: 'Clash',
    kind: 'review',
  },
});
assert.ok(storyCard.includes('An actual review preview.'));
assert.ok(storyCard.includes('Clash · review preview'));
