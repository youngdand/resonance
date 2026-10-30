'use strict';
paths.sparkles =
  '<path d="m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5zM21 2v4m-2-2h4"/>';
Object.assign(S, {
  discovery: {
    profile: [],
    items: [],
    job: { running: false, errors: [], candidates: [] },
    online: false,
  },
  discoveryTab: 'discover',
  discoveryFilter: 'all',
  discoveryHideOwned: true,
  discoveryError: '',
  discoveryArtist: '',
  discoveryAlbum: '',
  discoveryMode: 'easy',
  discoveryLoaded: false,
  releaseOptions: {
    country: 'GB',
    days: 30,
    type: 'albums',
    worldwide: true,
    includeOlder: false,
    genre: 'all',
  },
  releaseFeed: null,
  releaseOffset: 0,
  releaseError: '',
  releaseLoading: false,
});
let discoveryTimer,
  discoveryAutoAttempted = false,
  discoveryBusy = false,
  releaseBusy = false,
  releaseGeneration = 0,
  releaseAutoAttempted = new Set(),
  pendingReleaseCheck = null;
const isRelease = (i) => ['new-library-release', 'new-country-release'].includes(i.kind);
const releaseSection = () => (S.discoveryTab === 'country' ? 'country' : 'library');
function discoveryMainTabs() {
  return `<div class="for-you-tabs" role="tablist" aria-label="For you sections">${[
    ['discover', 'Discover', 'sparkles'],
    ['library', 'New from your artists', 'user'],
    ['country', 'New releases by country', 'music'],
  ]
    .map(
      ([key, label, glyph]) =>
        `<button role="tab" id="for-you-${key}" aria-controls="forYouPanel" aria-selected="${S.discoveryTab === key}" data-discovery-tab="${key}" class="${S.discoveryTab === key ? 'active' : ''}">${icon(glyph)} ${label}</button>`,
    )
    .join('')}</div>`;
}
function discoveryConsent() {
  const d = S.discovery,
    related = S.discoveryTab === 'discover';
  return S.demo
    ? ''
    : `<div class="discovery-consent"><div><strong>${d.online ? 'Online discovery enabled' : 'Enable online discovery'}</strong><p>${related ? 'Related discovery uses MusicBrainz and ListenBrainz.' : S.discoveryTab === 'country' ? 'UK release listings come from Official Charts. Optional international picks come from AllMusic. This lookup sends no library artist names.' : 'Official Charts and AllMusic release listings are matched against your library locally. The optional artist-catalogue check sends up to 10 artist names per action to Apple iTunes.'} Opening a release sends its artist and album name to supported publisher search endpoints, checks recent indexes and requests matched articles. No complete library is sent. Missing artwork sends the selected artist and album name to Apple and, if needed, Deezer. Known catalogue IDs can use Cover Art Archive. Cover images load from supplier image hosts while online discovery is enabled. Audio files, local paths and Soulseek credentials are not uploaded.</p></div><button class="${d.online ? 'secondary' : 'primary'}" data-discovery="consent">${d.online ? 'Turn off online lookups' : 'Enable online discovery'}</button></div>`;
}
function discoveryJobStatus() {
  let j = S.discovery.job || {};
  const expected = S.discoveryTab === 'discover' ? 'related' : 'releases-' + releaseSection();
  if ((j.kind || 'related') !== expected) {
    if (!j.running) return '';
    const name =
      j.kind === 'releases-library'
        ? 'A library artist check'
        : j.kind === 'releases-country'
          ? 'A country release check'
          : 'A related-music check';
    return `<div class="notice">${name} is running in the background. ${S.discoveryTab === 'country' ? 'Country releases use only your country, date, type and genre filters. No artist confirmations are needed.' : ''}${S.discoveryTab !== 'discover' ? `<button class="secondary" data-release-action="switch" ${pendingReleaseCheck ? 'disabled' : ''}>${pendingReleaseCheck ? 'Stopping the background check…' : S.discoveryTab === 'country' ? 'Stop background check and check country' : 'Stop background check and check my artists'}</button>` : ''}</div>`;
  }
  if (S.discoveryTab === 'country') j = { ...j, candidates: [] };
  return `${j.running ? `<div class="notice"><span class="spinner"></span>${esc(j.progress)}<button data-discovery="stop">Stop</button></div>` : ''}${j.warnings?.length ? `<div class="notice warning">${esc([...new Set(j.warnings)].slice(0, 3).join(' '))}</div>` : ''}${j.retryAt > Date.now() / 1000 ? `<div class="notice">A catalogue service is busy. Online retries are paused until ${esc(new Date(j.retryAt * 1000).toLocaleTimeString())}. Existing discoveries have been kept.</div>` : ''}${j.errors?.length ? `<div class="notice warning">${esc([...new Set(j.errors)].slice(0, 3).join(' '))}</div>` : ''}${j.candidates?.length ? `<section class="discovery-matches"><h3>Confirm the artist</h3><p class="hint">Names can refer to different artists. Confirm a catalogue identity before its releases are included.</p>${j.candidates.map((m, i) => `<div><strong>${esc(m.artist)}</strong>${m.choices.map((c, n) => `<button class="secondary" data-match-group="${i}" data-match-choice="${n}">${esc(c.name)}${c.detail ? ' · ' + esc(c.detail) : ''}</button>`).join('') || '<span class="muted">No confirmed catalogue match.</span>'}</div>`).join('')}</section>` : ''}`;
}
function sampleDiscovery() {
  const profile = [
    {
      artist: 'Massive Attack',
      albums: ['Mezzanine', 'Blue Lines'],
      tracks: 10,
    },
    { artist: 'Portishead', albums: ['Dummy'], tracks: 4 },
    { artist: 'Radiohead', albums: ['In Rainbows'], tracks: 4 },
  ];
  const items = [
    {
      id: 'demo-missing',
      kind: 'missing-album',
      artist: 'Massive Attack',
      album: 'Heligoland',
      year: '2010',
      libraryStatus: 'not-in-library',
      reasons: ['More studio albums by Massive Attack from your sample library'],
      source: 'Demo catalogue example',
    },
    {
      id: 'demo-artist',
      kind: 'artist',
      artist: 'Tricky',
      libraryStatus: 'new-artist',
      reasons: ['Related to Massive Attack in your sample library'],
      source: 'Demo related-artist example',
    },
    {
      id: 'demo-related',
      kind: 'related-album',
      artist: 'Tricky',
      album: 'Maxinquaye',
      year: '1995',
      libraryStatus: 'not-in-library',
      reasons: ['Albums by an artist related to Massive Attack'],
      source: 'Demo catalogue example',
    },
  ];
  return {
    profile,
    items,
    online: false,
    job: {
      running: false,
      progress: 'Sample recommendations',
      errors: [],
      candidates: [],
      updated: 0,
    },
  };
}
function buildDemoReleaseFeed() {
  const today = new Date(),
    day = [
      today.getFullYear(),
      String(today.getMonth() + 1).padStart(2, '0'),
      String(today.getDate()).padStart(2, '0'),
    ].join('-'),
    kind = S.discoveryTab === 'country' ? 'new-country-release' : 'new-library-release';
  return {
    items: [
      {
        id: 'demo-' + kind,
        kind,
        artist: S.discoveryTab === 'country' ? 'Demo artist' : 'Massive Attack',
        album: 'Example release (fictional demo)',
        genres: ['Electronic & Dance'],
        genreCategories: ['Electronic & Dance'],
        releaseDate: day,
        originalDate: day,
        releaseType: 'Album',
        classification: 'new-release',
        eventCountry: S.releaseOptions.country,
        country: S.releaseOptions.country,
        libraryStatus: 'not-in-library',
        source: 'Fictional demo — not a real release',
        reasons: ['Sample layout; no online lookup was made'],
      },
    ],
    total: 1,
    offset: 0,
    hasMore: false,
    libraryArtists: 3,
    check: { complete: true },
    options: S.releaseOptions,
    countries: ['GB', 'LU', 'US', 'IE', 'FR', 'DE', 'AU', 'CA', 'JP'],
  };
}
function demoReleaseFeed() {
  const feed = buildDemoReleaseFeed();
  feed.unfilteredTotal = feed.items.length;
  feed.genreCounts = { 'Electronic & Dance': 1 };
  feed.unclassified = 0;
  const genre = S.releaseOptions.genre || 'all';
  if (genre !== 'all') feed.items = feed.items.filter((i) => i.genreCategories.includes(genre));
  feed.total = feed.items.length;
  return feed;
}
async function loadDiscovery(quiet = false) {
  const generation = UIState.next('discovery');
  const tab = S.discoveryTab;
  if (S.demo) {
    if (!S.discoveryLoaded || !S.discovery.demo) {
      S.discovery = { ...sampleDiscovery(), demo: true };
      S.discoveryLoaded = true;
    }
    if (S.discoveryTab !== 'discover') S.releaseFeed = demoReleaseFeed();
    if (S.page === 'foryou') render();
    return;
  }
  try {
    const discovery = await api('discovery' + (tab === 'discover' ? '' : '?summary=1'));
    if (!UIState.current('discovery', generation) || tab !== S.discoveryTab) return;
    S.discovery = {
      ...discovery,
      profile: tab === 'discover' ? discovery.profile : S.discovery.profile || [],
      items: tab === 'discover' ? discovery.items : S.discovery.items || [],
    };
    S.discoveryLoaded = true;
    S.discoveryError = '';
    if (!S.releaseOptionsLoaded) {
      Object.assign(S.releaseOptions, S.discovery.releasePreferences || {});
      S.releaseOptionsLoaded = true;
    }
    if (S.discoveryTab !== 'discover') await loadReleaseFeed(false);
    if (S.page === 'foryou') render();
    if (pendingReleaseCheck && !S.discovery.online) pendingReleaseCheck = null;
    if (pendingReleaseCheck && !S.discovery.job.running && !releaseBusy) {
      const pending = pendingReleaseCheck;
      pendingReleaseCheck = null;
      await startReleaseCheck(false, pending.section, pending.options);
      return;
    }
    if (S.discovery.job.running || pendingReleaseCheck) watchDiscovery();
    else if (
      S.discovery.online &&
      S.discoveryTab === 'discover' &&
      !discoveryAutoAttempted &&
      !S.discovery.items.some((i) => !isRelease(i)) &&
      S.discovery.profile.length
    ) {
      discoveryAutoAttempted = true;
      startDiscovery();
    } else if (S.discovery.online && S.discoveryTab !== 'discover') maybeStartReleases();
  } catch (e) {
    S.discoveryError = e.message;
    if (S.page === 'foryou') render();
    if (!quiet) toast(e.message, true);
  }
}
let discoveryPayloadAt = 0;
function watchDiscovery() {
  clearTimeout(discoveryTimer);
  discoveryTimer = setTimeout(async () => {
    try {
      const job = await api('discovery/progress');
      S.discovery.job = job;
      if (!job.running || Date.now() - discoveryPayloadAt > 5000) {
        discoveryPayloadAt = Date.now();
        await loadDiscovery(true);
      } else {
        if (S.page === 'foryou') render();
        watchDiscovery();
      }
    } catch (error) {
      S.discoveryError = error.message;
    }
  }, 1600);
}
async function startDiscovery() {
  if (discoveryBusy) return;
  discoveryAutoAttempted = true;
  if (S.demo) {
    toast('Sample recommendations only. No online lookup was made.');
    return;
  }
  discoveryBusy = true;
  try {
    await api('discovery/start', {
      artist: S.discoveryArtist,
      album: S.discoveryAlbum,
      mode: S.discoveryMode,
    });
    await loadDiscovery(true);
    watchDiscovery();
  } catch (e) {
    toast(e.message, true);
  } finally {
    discoveryBusy = false;
  }
}
function releaseQueryKey() {
  const { genre, q, sort, focus, ...catalogueOptions } = S.releaseOptions;
  return JSON.stringify([releaseSection(), catalogueOptions, new Date().toDateString()]);
}
function maybeStartReleases() {
  const key = releaseQueryKey(),
    feed = S.releaseFeed;
  if (
    !feed ||
    S.discovery.job.running ||
    releaseBusy ||
    releaseAutoAttempted.has(key) ||
    (releaseSection() === 'library' && !feed.libraryArtists)
  )
    return;
  const today = new Date(),
    iso = [
      today.getFullYear(),
      String(today.getMonth() + 1).padStart(2, '0'),
      String(today.getDate()).padStart(2, '0'),
    ].join('-');
  if (feed.check?.toDate === iso && !feed.libraryChanged) return;
  releaseAutoAttempted.add(key);
  startReleaseCheck();
}
async function loadReleaseFeed(draw = true) {
  const generation = ++releaseGeneration,
    section = releaseSection();
  S.releaseLoading = true;
  if (S.demo) {
    S.releaseFeed = demoReleaseFeed();
    S.releaseLoading = false;
    if (draw) render();
    return;
  }
  try {
    const q = new URLSearchParams({
      section,
      ...S.releaseOptions,
      offset: S.releaseOffset,
      limit: 48,
    });
    const feed = await api('discovery/releases?' + q);
    if (generation !== releaseGeneration) return;
    S.releaseFeed = feed;
    S.releaseCountries = feed.countries;
    S.releaseError = '';
  } catch (e) {
    if (generation === releaseGeneration) S.releaseError = e.message;
  } finally {
    if (generation === releaseGeneration) {
      S.releaseLoading = false;
      if (draw && S.page === 'foryou') render();
    }
  }
}
async function startReleaseCheck(
  continuation = false,
  section = releaseSection(),
  options = { ...S.releaseOptions },
) {
  if (releaseBusy || S.discovery.job.running) return;
  if (S.demo) {
    S.releaseFeed = demoReleaseFeed();
    render();
    toast('Fictional demo releases. No online lookup was made.');
    return;
  }
  releaseBusy = true;
  releaseAutoAttempted.add(releaseQueryKey());
  S.releaseOffset = 0;
  try {
    const response = await api('discovery/releases/start', {
      section,
      ...options,
      continue: continuation,
    });
    if (response.alreadyRunning)
      toast('A discovery check is already running. Its progress is shown above.');
    await loadDiscovery(true);
    watchDiscovery();
  } catch (e) {
    S.releaseError = e.message;
    render();
    toast(e.message, true);
  } finally {
    releaseBusy = false;
  }
}
async function switchReleaseCheck() {
  if (pendingReleaseCheck) return;
  pendingReleaseCheck = {
    section: releaseSection(),
    options: { ...S.releaseOptions },
  };
  render();
  try {
    await api('discovery/stop', {});
    await loadDiscovery(true);
    watchDiscovery();
  } catch (e) {
    pendingReleaseCheck = null;
    render();
    toast(e.message, true);
  }
}
function countryName(code) {
  if (code === 'UNVERIFIED') return 'Market unverified';
  if (code === 'XW') return 'Worldwide';
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' }).of(code) || code;
  } catch {
    return { GB: 'United Kingdom', LU: 'Luxembourg', US: 'United States' }[code] || code;
  }
}
function releaseDate(value) {
  if (!value) return 'Not supplied';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const d = new Date(value + 'T12:00:00');
    if (!Number.isNaN(d.valueOf()))
      return d.toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      });
  }
  return value;
}
function discoveryActions(item) {
  return `<div class="discovery-actions"><button class="primary" data-discovery-search="${esc(item.id)}">${icon('search')} Find on Soulseek</button><button class="icon-button ${item.feedback === 'saved' ? 'saved' : ''}" data-discovery-save="${esc(item.id)}" title="${item.feedback === 'saved' ? 'Unsave' : 'Save'}" aria-label="${item.feedback === 'saved' ? 'Unsave' : 'Save'} ${esc(item.album || item.artist)}">${icon(item.feedback === 'saved' ? 'check' : 'plus')}</button><button class="icon-button" data-discovery-dismiss="${esc(item.id)}" aria-label="Dismiss ${esc(item.album || item.artist)}">✕</button></div>`;
}
function releaseGenreFilter(feed, options) {
  const genres = [
    'Alternative & Indie',
    'Blues',
    'Classical',
    'Country',
    'Electronic & Dance',
    'Folk & Acoustic',
    'Hip-Hop & Rap',
    'Jazz',
    'Metal',
    'Pop',
    'Punk',
    'R&B & Soul',
    'Reggae',
    'Rock',
    'Soundtracks',
    'World & Latin',
  ];
  const choices = [
    ['all', 'All genres', feed?.unfilteredTotal],
    ...genres.map((g) => [g, g, feed?.genreCounts?.[g]]),
    ['unclassified', 'Unclassified', feed?.unclassified],
  ];
  return `<label>Genre<select id="releaseGenre" class="select">${choices.map(([v, label, count]) => `<option value="${esc(v)}" ${(options.genre || 'all') === v ? 'selected' : ''}>${esc(label)}${count === undefined ? '' : ' (' + count + ')'}</option>`).join('')}</select></label>`;
}
function renderReleaseFeed() {
  const country = S.discoveryTab === 'country',
    feed = S.releaseFeed,
    options = S.releaseOptions,
    check = feed?.check || {},
    busy = S.discovery.job?.running;
  const countries = [
    ...new Set([
      options.country,
      ...(S.releaseCountries ||
        feed?.countries || ['GB', 'LU', 'US', 'IE', 'FR', 'DE', 'AU', 'CA', 'JP']),
    ]),
  ].sort((a, b) => countryName(a).localeCompare(countryName(b)));
  const items = (feed?.items || []).filter(
    (i) =>
      country ||
      !S.discoveryHideOwned ||
      !['album-in-library', 'possible-album'].includes(i.libraryStatus),
  );
  return (
    heading(
      'FOR YOU',
      country ? 'New releases by country' : 'New from your artists',
      country
        ? 'Recent catalogue releases listed for your selected market.'
        : 'Recent albums, EPs and singles from artists already in your collection.',
      `<button class="secondary" data-release-action="refresh" ${busy ? 'disabled' : ''}>${icon('refresh')} ${country ? 'Check releases' : 'Refresh release listings'}</button>`,
    ) +
    discoveryMainTabs() +
    `<section id="forYouPanel" role="tabpanel" aria-labelledby="for-you-${S.discoveryTab}">` +
    demoNotice() +
    discoveryConsent() +
    `<div class="release-intro"><div><h2>${country ? 'Your next record is waiting.' : 'New chapters from familiar artists.'}</h2><p>${country ? 'Choose your country below. UK listings come from Official Charts. International editorial picks are labelled separately; their local availability is unverified.' : 'Current release lists are matched to all your library artists locally. Use the optional Apple check to explore individual artist catalogues in batches of 10.'}</p></div>${!country ? `<strong>${feed?.libraryArtists ?? S.discovery.profile.length}<small>library artists</small></strong>` : `<strong>${esc(options.country)}<small>${esc(countryName(options.country))}</small></strong>`}</div>${showcaseToolbar(feed, options)}<details class="showcase-more"><summary>More filters · country, release type & editions</summary><div class="release-filters">${country ? `<label>Country<select id="releaseCountry" class="select">${countries.map((code) => `<option value="${code}" ${code === options.country ? 'selected' : ''}>${esc(countryName(code))} (${code})</option>`).join('')}</select></label>` : ''}<label>Released<select id="releaseDays" class="select">${[
      [7, 'Last 7 days'],
      [30, 'Last 30 days'],
      [90, 'Last 90 days'],
    ]
      .map(
        ([n, t]) =>
          `<option value="${n}" ${Number(options.days) === n ? 'selected' : ''}>${t}</option>`,
      )
      .join(
        '',
      )}</select></label>${releaseGenreFilter(feed, options)}<label>Type<select id="releaseType" class="select">${[
      ['albums', 'Albums & EPs'],
      ['singles', 'Singles'],
      ['eps', 'EPs'],
      ['all', 'Albums, EPs & singles'],
    ]
      .map(([v, t]) => `<option value="${v}" ${options.type === v ? 'selected' : ''}>${t}</option>`)
      .join(
        '',
      )}</select></label>${country ? `<label class="switch-label"><input type="checkbox" id="releaseWorldwide" ${options.worldwide ? 'checked' : ''}>Include international picks</label><label class="switch-label"><input type="checkbox" id="releaseIncludeOlder" ${options.includeOlder ? 'checked' : ''}>Include older albums / new editions</label>` : ''}${!country ? `<label class="switch-label"><input type="checkbox" id="discoveryHideOwned" ${S.discoveryHideOwned ? 'checked' : ''}>Hide library matches</label>` : ''}</div></details>${S.releaseError ? `<div class="notice warning">${esc(S.releaseError)}</div>` : ''}${discoveryJobStatus()}${feed ? `<div class="release-coverage"><span>${check.summary ? esc(check.summary) : country ? 'No release listing check completed yet' : `${check.checkedArtists || 0} of ${feed.libraryArtists} library artists matched against release listings`}${check.checkedAt ? ' · Last check ' + esc(new Date(check.checkedAt * 1000).toLocaleString()) : ''}${check.partial ? ' · Partial results' : ''}${check.ambiguousArtists ? ' · ' + check.ambiguousArtists + ' artist matches need confirmation' : ''}</span>${country && check.hasMore ? `<button class="secondary" data-release-action="continue" ${busy ? 'disabled' : ''}>Continue catalogue check</button>` : ''}</div>` : ''}${!country ? `<div class="release-coverage"><span>${esc(feed?.artistCheck?.summary || 'Optional: check individual Apple artist catalogues. This can take at least roughly 30 seconds per 10 uncached artists; your country lookup does not need it.')}</span><button class="secondary" data-release-action="artists" ${busy ? 'disabled' : ''}>${feed?.artistCheck?.hasMore ? 'Check next 10 artists' : 'Check 10 artist catalogues'}</button></div>` : ''}${S.releaseLoading && !feed ? '<p class="hint"><span class="spinner"></span>Loading cached releases…</p>' : ''}${items.length ? `<div class="discovery-grid">${items.map(releaseCard).join('')}</div>` : empty(!country && !(feed?.libraryArtists || S.discovery.profile.length) ? 'Start with a library scan' : busy && S.discovery.job.kind === 'releases-' + releaseSection() ? 'Checking recent releases…' : 'No matching releases in the checked results', !country && !(feed?.libraryArtists || S.discovery.profile.length) ? 'Add artist tags to your collection, then return here.' : !S.discovery.online && !S.demo ? 'Enable online discovery to check the catalogue. Existing cached releases are kept.' : country && check.hasMore ? 'Continue the catalogue check to search more editions, or widen the date/type filters.' : 'Try clearing the search or genre filter, widening the period, or choosing another release type.')}<div class="browse-pager"><button class="secondary" data-release-action="previous" ${S.releaseOffset === 0 ? 'disabled' : ''}>Previous</button><span>${feed?.total ? `${S.releaseOffset + 1}–${Math.min(S.releaseOffset + 48, feed.total)} of ${feed.total} matching releases` : 'No matching releases'}${!country && S.discoveryHideOwned ? ' · library matches hidden on this page' : ''}</span><button class="secondary" data-release-action="next" ${!feed?.hasMore ? 'disabled' : ''}>Next</button></div><p class="page-note">Genre filters use the publishers’ metadata; missing genres appear under Unclassified. The default release check makes no MusicBrainz requests. UK checks load the dated weekly release archive for your selected 7/30/90-day range. International picks use current AllMusic selections and cached weeks. Publisher selections are not an exhaustive catalogue. Listing dates do not confirm original release dates; reissues can appear. Country availability is unverified for international picks. Apple artist checks are optional and cached for seven days.</p></section>`
  );
}
function renderRelatedDiscovery() {
  const d = S.discovery,
    artists = d.profile || [],
    current = artists.find((a) => a.artist === S.discoveryArtist);
  const items = (d.items || []).filter(
    (i) =>
      i.feedback !== 'dismissed' &&
      (!S.discoveryHideOwned ||
        !['album-in-library', 'possible-album', 'artist-in-library'].includes(i.libraryStatus)) &&
      (S.discoveryFilter === 'saved'
        ? i.feedback === 'saved'
        : !isRelease(i) &&
          (S.discoveryFilter === 'all' ||
            (S.discoveryFilter === 'artists' && i.kind === 'artist') ||
            (S.discoveryFilter === 'missing' && i.kind === 'missing-album') ||
            (S.discoveryFilter === 'related' && ['related-album', 'tag-album'].includes(i.kind)))),
  );
  return (
    heading(
      'FOR YOU',
      'Follow the music.',
      'Related artists, album discoveries and gaps in your collection.',
      `<button class="secondary" data-discovery="refresh" ${d.job.running ? 'disabled' : ''}>${icon('refresh')} Refresh discoveries</button>`,
    ) +
    discoveryMainTabs() +
    `<section id="forYouPanel" role="tabpanel" aria-labelledby="for-you-discover">` +
    demoNotice() +
    `<section class="discovery-hero"><div><span class="eyebrow">MADE FROM WHAT YOU OWN</span><h2>A new direction, from a familiar record.</h2><p>Explore connections from an artist or album in your collection, or keep up with new releases in the tabs above.</p><div class="discovery-stat">${artists.length} indexed artists · ${d.items.filter((i) => !isRelease(i)).length} ${S.demo ? 'sample' : 'cached'} discoveries</div></div><div class="discovery-orbit" aria-hidden="true">${icon('sparkles')}<span>collection</span></div></section>` +
    discoveryConsent() +
    `${S.discoveryError ? `<div class="notice warning">${esc(S.discoveryError)}</div>` : ''}<div class="discovery-seed"><label>Start with<select id="discoveryArtist" class="select"><option value="">A mix from my library</option>${artists.map((a) => `<option value="${esc(a.artist)}" ${S.discoveryArtist === a.artist ? 'selected' : ''}>${esc(a.artist)} · ${a.albums.length} albums</option>`).join('')}</select></label><label>Album<select id="discoveryAlbum" class="select" ${!current ? 'disabled' : ''}><option value="">Any album by this artist</option>${(current?.albums || []).map((a) => `<option value="${esc(a)}" ${S.discoveryAlbum === a ? 'selected' : ''}>${esc(a)}</option>`).join('')}</select></label><label>Explore<select id="discoveryMode" class="select">${[
      ['easy', 'Closer to home'],
      ['medium', 'Broaden my taste'],
      ['hard', 'Further afield'],
    ]
      .map(
        ([v, t]) => `<option value="${v}" ${S.discoveryMode === v ? 'selected' : ''}>${t}</option>`,
      )
      .join(
        '',
      )}</select></label><button class="primary" data-discovery="generate" ${d.job.running || (!S.demo && !d.online) ? 'disabled' : ''}>${icon('sparkles')} Find discoveries</button></div>${discoveryJobStatus()}<div class="section-top"><div class="discovery-tabs">${[
      ['all', 'For you'],
      ['artists', 'Related artists'],
      ['related', 'Related albums'],
      ['missing', 'Collection gaps'],
      ['saved', 'Saved'],
    ]
      .map(
        ([v, t]) =>
          `<button data-discovery-filter="${v}" class="${S.discoveryFilter === v ? 'active' : ''}">${t}</button>`,
      )
      .join(
        '',
      )}</div><label class="switch-label"><input id="discoveryHideOwned" type="checkbox" ${S.discoveryHideOwned ? 'checked' : ''}>Hide library matches</label></div>${
      items.length
        ? `<div class="discovery-grid">${items
            .slice(0, 120)
            .map((i) => (isRelease(i) ? releaseCard(i) : discoveryCard(i)))
            .join('')}</div>`
        : empty(
            !artists.length && !S.demo
              ? 'Start with a library scan'
              : d.job.running
                ? 'Finding your next discovery…'
                : S.discoveryFilter === 'saved'
                  ? 'Your saved discoveries live here'
                  : 'Your next connection is waiting',
            !artists.length && !S.demo
              ? 'Scan your music in My collection. You can use the country tab without a library.'
              : 'Choose an artist or album, enable online discovery and refresh. Suggestions depend on catalogue coverage.',
            !artists.length && !S.demo
              ? '<button class="primary" data-page="library">Open my collection</button>'
              : '',
          )
    }<p class="page-note">Related artists come from ListenBrainz; collection gaps and shared-tag suggestions come from MusicBrainz. A library title match does not confirm a complete album or the same edition.</p></section>`
  );
}
function renderDiscovery() {
  return S.discoveryTab === 'discover' ? renderRelatedDiscovery() : renderReleaseFeed();
}
function discoveryCard(i) {
  const owned = ['album-in-library', 'possible-album', 'artist-in-library'].includes(
    i.libraryStatus,
  );
  return `<article class="discovery-card"><div class="discovery-art c${hash(i.artist)}"><span>${icon(i.kind === 'artist' ? 'user' : 'music')}</span><small>${i.kind === 'artist' ? 'ARTIST CONNECTION' : i.kind === 'missing-album' ? 'COLLECTION GAP' : i.kind === 'tag-album' ? 'SHARED TAGS' : 'ALBUM DISCOVERY'}</small></div><div class="discovery-card-body"><h3>${esc(i.album || i.artist)}</h3><p class="discovery-artist">${i.album ? esc(i.artist) : 'Explore a related artist'}${i.year ? ' · ' + esc(i.year) : ''}</p><div class="discovery-reason">${icon('sparkles')}<span>${esc(i.reasons?.[0] || 'From your collection')}</span></div><span class="discovery-ownership ${owned ? 'owned' : ''}">${owned ? 'Already in your library index' : 'New to your library'}</span>${discoveryActions(i)}<div class="discovery-source">${esc(i.source)}${i.url ? ` · <a href="${esc(i.url)}" target="_blank" rel="noreferrer">Catalogue ↗</a>` : ''}</div></div></article>`;
}
async function discoveryFeedback(id, status) {
  if (S.demo) {
    for (const i of [...S.discovery.items, ...(S.releaseFeed?.items || [])])
      if (i.id === id) i.feedback = status;
    render();
    return;
  }
  await api('discovery/feedback', { id, status });
  await loadDiscovery(true);
}
async function changeReleaseOptions(target) {
  const fields = {
      releaseCountry: 'country',
      releaseDays: 'days',
      releaseType: 'type',
      releaseWorldwide: 'worldwide',
      releaseIncludeOlder: 'includeOlder',
      releaseGenre: 'genre',
      releaseSort: 'sort',
    },
    key = fields[target.id];
  if (!key) return;
  S.releaseOptions[key] =
    target.type === 'checkbox'
      ? target.checked
      : target.id === 'releaseDays'
        ? Number(target.value)
        : target.value;
  S.releaseOffset = 0;
  S.releaseFeed = null;
  S.releaseLoading = true;
  render();
  if (!S.demo)
    try {
      await api('discovery/releases/preferences', S.releaseOptions);
    } catch (e) {
      toast(e.message, true);
      return;
    }
  await loadReleaseFeed();
  if (!['genre', 'sort', 'focus', 'q'].includes(key) && !S.demo && S.discovery.online)
    maybeStartReleases();
}
document.addEventListener('change', async (e) => {
  if (e.target.id === 'discoveryArtist') {
    S.discoveryArtist = e.target.value;
    S.discoveryAlbum = '';
    render();
  }
  if (e.target.id === 'discoveryAlbum') S.discoveryAlbum = e.target.value;
  if (e.target.id === 'discoveryMode') S.discoveryMode = e.target.value;
  if (e.target.id === 'discoveryHideOwned') {
    S.discoveryHideOwned = e.target.checked;
    render();
  }
  if (e.target.id.startsWith('release')) await changeReleaseOptions(e.target);
});
document.addEventListener('click', async (e) => {
  const t = e.target.closest('button');
  if (!t) return;
  try {
    if (t.dataset.discoveryTab) {
      S.discoveryTab = t.dataset.discoveryTab;
      S.releaseOffset = 0;
      S.releaseFeed = null;
      render();
      await loadDiscovery(true);
      return;
    }
    if (t.dataset.releaseAction) {
      const a = t.dataset.releaseAction;
      if (a === 'switch') {
        await switchReleaseCheck();
        return;
      }
      if (a === 'artists') {
        await startReleaseCheck(true, releaseSection(), {
          ...S.releaseOptions,
          artistLookup: true,
        });
        return;
      }
      if (a === 'refresh' || a === 'continue') await startReleaseCheck(a === 'continue');
      else {
        S.releaseOffset = Math.max(0, S.releaseOffset + (a === 'next' ? 48 : -48));
        await loadReleaseFeed();
      }
      return;
    }
    if (t.dataset.exploreArtist) {
      S.discoveryTab = 'discover';
      S.discoveryArtist = t.dataset.exploreArtist;
      S.discoveryAlbum = t.dataset.exploreAlbum || '';
      go('foryou');
      if (S.discovery.online && !S.demo) await startDiscovery();
      return;
    }
    if (t.dataset.discoveryFilter) {
      S.discoveryFilter = t.dataset.discoveryFilter;
      render();
      return;
    }
    if (t.dataset.discoverySearch) {
      const i = [...S.discovery.items, ...(S.releaseFeed?.items || [])].find(
        (x) => x.id === t.dataset.discoverySearch,
      );
      if (i) {
        S.recovery = null;
        S.replaces = null;
        S.view = 'grouped';
        await search(i.artist + (i.album ? ' ' + i.album : ''));
      }
      return;
    }
    if (t.dataset.discoverySave) {
      const i = [...S.discovery.items, ...(S.releaseFeed?.items || [])].find(
        (x) => x.id === t.dataset.discoverySave,
      );
      await discoveryFeedback(i.id, i.feedback === 'saved' ? '' : 'saved');
      return;
    }
    if (t.dataset.discoveryDismiss) {
      await discoveryFeedback(t.dataset.discoveryDismiss, 'dismissed');
      return;
    }
    if (t.dataset.matchGroup !== undefined) {
      const m = S.discovery.job.candidates[Number(t.dataset.matchGroup)],
        c = m.choices[Number(t.dataset.matchChoice)];
      await api('discovery/match', { artist: m.artist, mbid: c.mbid });
      S.discoveryArtist = m.artist;
      if (S.discovery.job.running) {
        toast('Match saved. Refresh after the current check finishes.');
        return;
      }
      if (S.discoveryTab === 'discover') await startDiscovery();
      else await startReleaseCheck();
      return;
    }
    const a = t.dataset.discovery;
    if (a === 'consent') {
      pendingReleaseCheck = null;
      const enabled = !S.discovery.online;
      discoveryAutoAttempted = true;
      releaseAutoAttempted.add(releaseQueryKey());
      await api('discovery/consent', { enabled });
      await loadDiscovery(true);
      if (enabled) {
        if (S.discoveryTab === 'discover') await startDiscovery();
        else await startReleaseCheck();
      }
      return;
    }
    if (a === 'generate' || a === 'refresh') await startDiscovery();
    if (a === 'stop') {
      pendingReleaseCheck = null;
      await api('discovery/stop', {});
      toast('Stopping after the current catalogue request…');
      watchDiscovery();
    }
  } catch (e) {
    toast(e.message, true);
  }
});
document.addEventListener('keydown', (e) => {
  const tab = e.target.closest?.('[data-discovery-tab]');
  if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  const tabs = [...document.querySelectorAll('[data-discovery-tab]')],
    index = tabs.indexOf(tab),
    next =
      e.key === 'Home'
        ? 0
        : e.key === 'End'
          ? tabs.length - 1
          : (index + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  e.preventDefault();
  tabs[next].click();
  document.getElementById(tabs[next].id)?.focus();
});
function resetDiscoveryState(demo) {
  pendingReleaseCheck = null;
  S.discoveryFilter = 'all';
  clearTimeout(discoveryTimer);
  discoveryAutoAttempted = false;
  releaseAutoAttempted.clear();
  S.discoveryLoaded = false;
  S.releaseOptionsLoaded = false;
  S.releaseFeed = null;
  S.discovery = demo
    ? { ...sampleDiscovery(), demo: true }
    : {
        profile: [],
        items: [],
        job: { running: false, errors: [], candidates: [] },
        online: false,
      };
  S.discoveryError = '';
  S.discoveryArtist = '';
  S.discoveryAlbum = '';
}
