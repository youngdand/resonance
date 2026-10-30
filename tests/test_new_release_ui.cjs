'use strict';
const vm = require('node:vm'),
  fs = require('node:fs'),
  path = require('node:path'),
  assert = require('node:assert/strict');
const web = path.join(__dirname, '../web'),
  ctx = {
    console,
    Intl,
    Date,
    Set,
    Map,
    URLSearchParams,
    Number,
    URL,
    S: { settings: {}, page: 'foryou', demo: false },
    paths: {},
    document: {
      addEventListener() {},
      querySelectorAll() {
        return [];
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
vm.runInContext(fs.readFileSync(path.join(web, 'view_helpers.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(path.join(web, 'ui_state.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(path.join(web, 'discovery.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(path.join(web, 'showcase.js'), 'utf8'), ctx);
ctx.S.discovery = {
  profile: [],
  items: [],
  online: false,
  job: { running: false, errors: [], warnings: [], candidates: [] },
};
ctx.S.discoveryTab = 'country';
ctx.S.releaseOptions = {
  country: 'LU',
  days: 30,
  type: 'albums',
  worldwide: true,
  includeOlder: false,
};
const item = {
  id: 'new',
  kind: 'new-country-release',
  artist: 'Example Artist',
  album: 'Fresh Music',
  releaseDate: '2026-10-20',
  originalDate: '2026-10-19',
  releaseType: 'Album',
  classification: 'new-release',
  eventCountry: 'LU',
  country: 'LU',
  libraryStatus: 'not-in-library',
  source: 'MusicBrainz',
  reasons: ['A country release'],
};
ctx.S.releaseFeed = {
  items: [item],
  total: 1,
  offset: 0,
  hasMore: false,
  countries: ['GB', 'LU'],
  libraryArtists: 0,
  check: {},
};
const country = ctx.renderDiscovery();
assert.ok(country.includes('Luxembourg'));
assert.ok(country.includes('Fresh Music'));
assert.ok(!country.includes('Start with a library scan'));
assert.equal((country.match(/role="tab" /g) || []).length, 3);
assert.ok(country.includes('aria-selected="true" data-discovery-tab="country"'));
assert.ok(country.includes('value="7"'));
assert.ok(country.includes('value="90"'));
assert.ok(country.includes('Include international picks'));
const edition = ctx.releaseCard({
  ...item,
  classification: 'catalogue-edition',
  originalDate: '1995-01-01',
});
assert.ok(edition.includes('NEW EDITION / REGIONAL RELEASE'));
assert.ok(edition.includes('1995'));
assert.ok(!edition.includes('release-label new'));
const unknown = ctx.releaseCard({
  ...item,
  classification: 'original-date-unconfirmed',
  originalDate: '',
});
assert.ok(unknown.includes('ORIGINAL DATE UNCONFIRMED'));
assert.ok(!unknown.includes('Original 2026'));
const malicious = ctx.releaseCard({
  ...item,
  album: '<script>alert(1)</script>',
  artist: '<img src=x onerror=evil()>',
  reasons: ['<svg onload=evil()>'],
});
assert.ok(!malicious.includes('<script>'));
assert.ok(!malicious.includes('<img '));
assert.ok(malicious.includes('&lt;script&gt;'));
ctx.S.discoveryTab = 'library';
ctx.S.releaseFeed = { items: [], libraryArtists: 0, check: {} };
assert.ok(ctx.renderDiscovery().includes('Start with a library scan'));
let calls = 0;
ctx.api = () => {
  calls++;
  return Promise.resolve({});
};
ctx.maybeStartReleases();
assert.equal(calls, 0, 'empty libraries must not trigger an automatic release check');
ctx.S.discoveryTab = 'discover';
ctx.S.discoveryHideOwned = false;
ctx.S.discovery.items = [
  { ...item, feedback: 'saved' },
  {
    id: 'related',
    kind: 'artist',
    artist: 'Related Person',
    libraryStatus: 'new-artist',
    source: 'ListenBrainz',
    reasons: ['Related'],
  },
];
ctx.S.discoveryFilter = 'all';
const related = ctx.renderDiscovery();
assert.ok(related.includes('Related Person'));
assert.ok(!related.includes('<h3>Fresh Music</h3>'));
ctx.S.discoveryFilter = 'saved';
assert.ok(ctx.renderDiscovery().includes('<h3>Fresh Music</h3>'));
console.log(
  'Release UI passed: three accessible tabs, country without a library, Luxembourg/date/type controls, edition/unknown-date labels, escaped metadata, related-feed separation and cross-section Saved.',
);

ctx.S.discoveryTab = 'country';
ctx.S.releaseOptions.genre = 'Jazz';
const genreUI = ctx.renderReleaseFeed();
assert.ok(genreUI.includes('id="releaseGenre"'));
assert.ok(genreUI.includes('value="Jazz" selected'));
assert.ok(genreUI.includes('Unclassified'));
assert.ok(
  ctx
    .releaseCard({ ...item, genres: ['Jazz', '<img src=x>'] })
    .includes('Jazz / &lt;img src=x&gt;'),
);
assert.ok(ctx.releaseCard(item).includes('Unclassified'));
const key = ctx.releaseQueryKey();
ctx.S.releaseOptions.genre = 'Rock';
assert.equal(ctx.releaseQueryKey(), key, 'genre switching must not restart catalogue checks');
console.log(
  'Genre UI passed: accessible selector, retained choice, unclassified and escaped labels, unchanged catalogue check identity.',
);
ctx.S.discoveryTab = 'country';
ctx.S.discoveryHideOwned = true;
ctx.S.releaseFeed = {
  items: [{ ...item, libraryStatus: 'album-in-library' }],
  total: 1,
  libraryArtists: 1496,
  check: {},
};
ctx.S.discovery.job = {
  kind: 'releases-library',
  running: true,
  progress: 'Checking new releases: 1460 of 1496 library artists checked…',
  candidates: [{ artist: 'Paul Simon', choices: [{ name: 'Photographer' }] }],
};
const scoped = ctx.renderReleaseFeed();
assert.ok(
  scoped.includes('Fresh Music'),
  'country must show owned albums even when library hide preference is set',
);
assert.ok(!scoped.includes('id="discoveryHideOwned"'));
assert.ok(!scoped.includes('Confirm the artist'));
assert.ok(!scoped.includes('Photographer'));
assert.ok(!scoped.includes('1460 of 1496'));
assert.ok(scoped.includes('Stop background check and check country'));
ctx.S.discovery.job.running = false;
assert.equal(
  ctx.discoveryJobStatus(),
  '',
  'previous artist-job warnings must not appear as country status',
);
ctx.S.discovery.job = {
  kind: 'releases-country',
  running: true,
  progress: 'Checking GB release listings',
  candidates: [{ artist: 'Paul Simon', choices: [] }],
};
assert.ok(ctx.discoveryJobStatus().includes('Checking GB'));
assert.ok(!ctx.discoveryJobStatus().includes('Confirm the artist'));

ctx.S.discoveryTab = 'library';
ctx.S.discovery.job = {
  kind: 'releases-library',
  running: false,
  errors: [],
  warnings: [],
  candidates: [],
};
ctx.S.releaseFeed = {
  items: [],
  libraryArtists: 1496,
  check: {
    summary: '97 published release listings checked against all 1496 library artists locally.',
  },
  artistCheck: {
    hasMore: true,
    summary: 'Apple artist catalogues: 10 of 1496 checked.',
  },
};
let supplierUI = ctx.renderReleaseFeed();
assert.ok(supplierUI.includes('Check next 10 artists'));
assert.ok(supplierUI.includes('97 published release listings'));
assert.ok(!supplierUI.includes('Enable MusicBrainz'));
const external = ctx.releaseCard({
  ...item,
  provider: 'independent',
  dateBasis: 'listing-week',
  eventCountry: 'UNVERIFIED',
  sources: [{ name: 'AllMusic', url: 'https://www.allmusic.com/newreleases' }],
});
assert.ok(external.includes('Listed week of'));
assert.ok(external.includes('AllMusic ↗'));
assert.ok(!external.includes('NEW RELEASE</div>'));
ctx.S.discoveryTab = 'country';
assert.ok(ctx.discoveryConsent().includes('This lookup sends no library artist names'));
assert.ok(!ctx.discoveryConsent().includes('MusicBrainz'));
console.log(
  'Supplier UI passed: bounded Apple action, local match summary, honest listing dates/source links, and no MusicBrainz consent on country tab.',
);

(async () => {
  const requests = [];
  let running = true;
  let kind = 'releases-library';
  ctx.S.discovery.job = { kind, running, errors: [], candidates: [] };
  ctx.S.releaseOptionsLoaded = true;
  ctx.S.discovery.online = true;
  ctx.api = async (route, body) => {
    requests.push([route, body]);
    if (route === 'discovery/stop') return { ok: true };
    if (route === 'discovery' || route.startsWith('discovery?'))
      return {
        online: true,
        profile: [],
        items: [],
        job: { running, kind, errors: [], candidates: [] },
      };
    if (route.startsWith('discovery/releases?'))
      return { items: [], libraryArtists: 0, check: { toDate: '2099-01-01' } };
    if (route === 'discovery/releases/start') {
      running = true;
      kind = 'releases-country';
      return { running: true, kind };
    }
    throw Error(route);
  };
  await ctx.switchReleaseCheck();
  assert.equal(
    requests.filter(([r]) => r === 'discovery/releases/start').length,
    0,
    'wait for cancellation before using shared provider',
  );
  running = false;
  await ctx.loadDiscovery(true);
  const starts = requests.filter(([r]) => r === 'discovery/releases/start');
  assert.equal(starts.length, 1);
  assert.equal(starts[0][1].section, 'country');
  assert.equal(starts[0][1].country, 'LU');
  assert.ok(!requests.some(([r, b]) => r === 'discovery/start' || b?.section === 'library'));
  console.log(
    'Country separation passed: no library hiding/artist prompts, scoped background status, and cancel-then-country handoff without overlapping requests.',
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
